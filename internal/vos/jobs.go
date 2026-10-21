package vos

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"
	"yovoice/internal/desktop"
	"yovoice/internal/msg"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

// SchedulerConfig 只读取私有配置；令牌不下发浏览器、不写入安装包。
type SchedulerConfig struct {
	LifecycleProtocolVersion int                           `json:"lifecycle_protocol_version,omitempty"`
	ProtocolVersion          int                           `json:"protocol_version,omitempty"`
	BindingRevision          int64                         `json:"binding_revision,omitempty"`
	AppID                    string                        `json:"app_id,omitempty"`
	URL                      string                        `json:"url"`
	Token                    string                        `json:"token"`
	ExecutorToken            string                        `json:"executor_token"`
	Models                   map[string]string             `json:"models"`
	UpstreamURL              string                        `json:"upstream_url,omitempty"`
	GatewayExecutors         map[string]string             `json:"gateway_executors,omitempty"`
	SecondaryModels          map[string][]string           `json:"secondary_models,omitempty"`
	ModelLimits              map[string]map[string]float64 `json:"model_limits,omitempty"`
	InputLimitsVersion       int                           `json:"input_limits_version,omitempty"`
	MixedInputLimitsVersion  *int                          `json:"mixed_input_limits_version,omitempty"`
	LegacyUnboundedModels    []string                      `json:"legacy_unbounded_models,omitempty"`
	ExecutionSettings        map[string]any                `json:"execution_settings,omitempty"`
}

type Job struct {
	ID              string          `json:"id"`
	User            string          `json:"user"`
	Method          string          `json:"method"`
	Data            json.RawMessage `json:"data"`
	Executor        string          `json:"executor"`
	TaskID          string          `json:"task_id"`
	Status          string          `json:"status"`
	ExecutionStatus string          `json:"execution_status"`
	Created         time.Time       `json:"created_at"`
	Cancel          bool            `json:"cancel"`
	Attempt         string          `json:"attempt"`
	Fence           uint64          `json:"fence"`
	Stopped         bool            `json:"stopped"`
	Error           string          `json:"error,omitempty"`
	BeforeFiles     []string        `json:"before_files,omitempty"`
	OutputFiles     []string        `json:"output_files,omitempty"`
}

type execution struct {
	cancel   context.CancelFunc
	deadline time.Time
	done     chan struct{}
}

type Jobs struct {
	Server     *Server
	Config     SchedulerConfig
	ConfigPath string
	mu         sync.Mutex
	active     map[string]*execution
	// 当前镜像只允许一个创作引擎运行，跨用户也不能并行加载多个大模型。
	executing string
}

func atomicJSON(path string, v any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".job-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(b)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	if err == nil {
		d, e := os.Open(filepath.Dir(path))
		if e != nil {
			return e
		}
		defer d.Close()
		err = d.Sync()
	}
	return err
}

func (j *Jobs) path(id string) string { return filepath.Join(j.Server.Root, "jobs", id+".json") }
func (j *Jobs) read(id string) (Job, error) {
	var job Job
	if !schema.ValidID(id) {
		return job, fmt.Errorf("invalid job ID")
	}
	b, err := os.ReadFile(j.path(id))
	if err == nil {
		err = json.Unmarshal(b, &job)
	}
	return job, err
}

func (j *Jobs) configured() bool {
	config := j.config()
	return config.URL != "" && len(config.Token) >= 32 && len(config.ExecutorToken) >= 32
}

// 配置由同应用的绑定端点原子替换；每次读取快照，避免轮换时并发改写共享 map。
func (j *Jobs) config() SchedulerConfig {
	if j.ConfigPath == "" {
		return j.Config
	}
	config, err := readSchedulerConfig(j.ConfigPath)
	if err != nil {
		return SchedulerConfig{}
	}
	return config
}

func (j *Jobs) controller(ctx context.Context, method, path string, body any, key string) (map[string]any, error) {
	config := j.config()
	if config.URL == "" || len(config.Token) < 32 {
		return nil, fmt.Errorf("V-Scheduler configuration required")
	}
	b, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(config.URL, "/")+path, bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+config.Token)
	req.Header.Set("Content-Type", "application/json")
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	res, err := (&http.Client{Timeout: 8 * time.Second}).Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	var envelope struct {
		Code string `json:"code"`
		Data any    `json:"data"`
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("V-Scheduler HTTP %d", res.StatusCode)
	}
	if err = json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&envelope); err != nil {
		return nil, err
	}
	if envelope.Code != "OK" {
		return nil, fmt.Errorf("V-Scheduler rejected request")
	}
	if value, ok := envelope.Data.(map[string]any); ok {
		return value, nil
	}
	if value, ok := envelope.Data.([]any); ok {
		return map[string]any{"items": value}, nil
	}
	return nil, fmt.Errorf("invalid scheduler data")
}

// Enqueue 先持久化业务任务，再以同一幂等键提交；失败绝不直接启动模型。
func (j *Jobs) Enqueue(user, key, method string, data json.RawMessage) (string, error) {
	if !j.configured() {
		return "", fmt.Errorf("V-Scheduler configuration required")
	}
	if !schema.ValidID(key) {
		return "", fmt.Errorf("stable request ID required")
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		return "", err
	}
	canonical, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	data = canonical
	j.mu.Lock()
	defer j.mu.Unlock()
	if old, err := j.read(key); err == nil {
		if old.User != user || old.Method != method || !bytes.Equal(old.Data, data) {
			return "", fmt.Errorf("idempotency conflict")
		}
		return old.ID, nil
	}
	// 固定模板必须显式覆盖作品中所有模型，不接受客户端自报资源预算。
	models := map[string]bool{}
	var collect func(any)
	collect = func(v any) {
		switch row := v.(type) {
		case map[string]any:
			for k, v := range row {
				if k == "modelId" {
					if id, ok := v.(string); ok && id != "" {
						models[id] = true
					}
				}
				collect(v)
			}
		case []any:
			for _, v := range row {
				collect(v)
			}
		}
	}
	collect(value)
	executor := ""
	for model := range models {
		approved := j.config().Models[model]
		if approved == "" || (executor != "" && approved != executor) {
			return "", fmt.Errorf("model budget not approved")
		}
		executor = approved
	}
	if executor == "" {
		return "", fmt.Errorf("model budget not approved")
	}
	job := Job{ID: key, User: user, Method: method, Data: append(json.RawMessage{}, data...), Executor: executor, Status: "queued", Created: time.Now().UTC(), Stopped: true}
	return job.ID, atomicJSON(j.path(job.ID), job)
}

// Run 只恢复提交和查询，不重放引擎执行；重启后的旧 attempt 保持未知直到停止核验。
func (j *Jobs) Run(ctx context.Context) {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		j.poll(ctx)
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (j *Jobs) poll(ctx context.Context) {
	paths, _ := filepath.Glob(filepath.Join(j.Server.Root, "jobs", "*.json"))
	for _, path := range paths {
		id := strings.TrimSuffix(filepath.Base(path), ".json")
		j.mu.Lock()
		job, err := j.read(id)
		j.mu.Unlock()
		if err != nil || job.Status == "succeeded" || job.Status == "failed" || job.Status == "cancelled" {
			continue
		}
		if job.TaskID == "" {
			// discovery 的执行器列表按服务身份过滤；缺少批准契约时不提交。
			available, lookupErr := j.controller(ctx, "GET", "/executors", nil, "")
			if lookupErr != nil {
				continue
			}
			approved := false
			if rows, ok := available["items"].([]any); ok {
				for _, row := range rows {
					if executor, ok := row.(map[string]any); ok && executor["id"] == job.Executor && executor["contract_version"] == "1" && executor["task_type"] == "voice.generate" {
						approved = true
					}
				}
			}
			if !approved {
				continue
			}
			var result map[string]any
			result, err = j.controller(ctx, "POST", "/tasks", map[string]any{"protocol_version": 1, "app_task_id": job.ID,
				"executor":   map[string]string{"id": job.Executor, "contract_version": "1", "task_type": "voice.generate"},
				"parameters": map[string]string{"job_id": job.ID}, "inputs": []any{}}, job.ID)
			if err != nil {
				continue
			}
			job.TaskID, _ = result["task_id"].(string)
			if job.TaskID == "" {
				continue
			}
			j.mu.Lock()
			current, e := j.read(id)
			if e == nil {
				current.TaskID = job.TaskID
				_ = atomicJSON(j.path(id), current)
				job = current
			}
			j.mu.Unlock()
		}
		if job.Cancel {
			_, _ = j.controller(ctx, "POST", "/tasks/"+job.TaskID+"/cancel", map[string]any{}, "")
		}
		result, err := j.controller(ctx, "GET", "/tasks/"+job.TaskID, nil, "")
		if err != nil {
			continue
		}
		status, _ := result["status"].(string)
		if status == "succeeded" || status == "failed" || status == "cancelled" {
			j.mu.Lock()
			current, e := j.read(id)
			if e == nil {
				current.Status = status
				_ = atomicJSON(j.path(id), current)
			}
			j.mu.Unlock()
		}
	}
}

// Cancel 只请求取消；收到执行端停止证据前不伪造终态。
func (j *Jobs) Cancel(user string) error {
	j.mu.Lock()
	defer j.mu.Unlock()
	paths, _ := filepath.Glob(filepath.Join(j.Server.Root, "jobs", "*.json"))
	for _, path := range paths {
		job, err := j.read(strings.TrimSuffix(filepath.Base(path), ".json"))
		if err != nil {
			continue
		}
		if job.User == user && job.Status != "succeeded" && job.Status != "failed" && job.Status != "cancelled" {
			job.Cancel = true
			if err = atomicJSON(path, job); err != nil {
				return err
			}
		}
	}
	return nil
}

// withoutPending 串行检查排队引用与删除，避免尚未启动的快照失去输入素材。
func (j *Jobs) withoutPending(user string, action func() (any, error)) (any, error) {
	j.mu.Lock()
	defer j.mu.Unlock()
	paths, err := filepath.Glob(filepath.Join(j.Server.Root, "jobs", "*.json"))
	if err != nil {
		return nil, err
	}
	for _, path := range paths {
		job, err := j.read(strings.TrimSuffix(filepath.Base(path), ".json"))
		if err != nil {
			return nil, err
		}
		if job.User == user && job.Status != "succeeded" && job.Status != "failed" && job.Status != "cancelled" {
			return nil, msg.Err(msg.ErrBusy, nil)
		}
	}
	return action()
}

func (j *Jobs) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if !j.configured() || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+j.config().ExecutorToken)) != 1 {
		http.Error(w, "Unauthorized", 401)
		return
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/scheduler/executions/"), "/")
	if len(parts) != 2 || r.Method != "POST" || parts[0] == "" {
		http.NotFound(w, r)
		return
	}
	var body struct {
		TaskID       string `json:"task_id"`
		Fence        uint64 `json:"fence"`
		LeaseSeconds int    `json:"lease_seconds"`
		Parameters   struct {
			JobID string `json:"job_id"`
		} `json:"parameters"`
	}
	if json.NewDecoder(http.MaxBytesReader(w, r.Body, 65536)).Decode(&body) != nil {
		http.Error(w, "Invalid request", 422)
		return
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	job, err := j.read(body.Parameters.JobID)
	if err != nil || job.TaskID == "" || job.TaskID != body.TaskID {
		http.Error(w, "Job binding conflict", 409)
		return
	}
	if job.Attempt != "" && (job.Attempt != parts[0] || job.Fence != body.Fence) {
		http.Error(w, "Stale attempt", 409)
		return
	}
	if j.active == nil {
		j.active = map[string]*execution{}
	}
	run := j.active[job.ID]
	switch parts[1] {
	case "start":
		if job.Attempt == "" {
			if job.Cancel {
				job.ExecutionStatus = "cancelled"
				job.Stopped = true
				_ = atomicJSON(j.path(job.ID), job)
				break
			}
			if j.executing != "" {
				http.Error(w, "Executor busy", 409)
				return
			}
			job.Attempt = parts[0]
			job.Fence = body.Fence
			job.ExecutionStatus = "running"
			job.Stopped = false
			workbench, openErr := j.Server.user(job.User)
			if openErr != nil {
				http.Error(w, "Workbench unavailable", 503)
				return
			}
			job.BeforeFiles = stateFiles(workbench.Store.Read())
			if err = atomicJSON(j.path(job.ID), job); err != nil {
				http.Error(w, "Journal unavailable", 503)
				return
			}
			ctx, cancel := context.WithCancel(context.Background())
			run = &execution{cancel: cancel, done: make(chan struct{})}
			j.active[job.ID] = run
			j.executing = job.ID
			go j.execute(ctx, job, run)
		}
		fallthrough
	case "inspect":
		if run != nil {
			run.deadline = time.Now().Add(time.Duration(max(1, min(30, body.LeaseSeconds))) * time.Second)
		}
	case "cancel":
		job.Cancel = true
		_ = atomicJSON(j.path(job.ID), job)
		if run != nil {
			run.cancel()
		}
		if job.Attempt == "" {
			job.ExecutionStatus = "cancelled"
			job.Stopped = true
			_ = atomicJSON(j.path(job.ID), job)
		}
	default:
		http.NotFound(w, r)
		return
	}
	status := job.ExecutionStatus
	if status == "" {
		status = "queued"
	}
	if run == nil && !job.Stopped {
		status = "unknown"
	}
	// running ACK 和成功终态严格分开，重启不把未知状态当成停止。
	jsonReply(w, map[string]any{"status": status, "stopped": job.Stopped, "result": map[string]any{"job_id": job.ID, "error": job.Error}})
}

func (j *Jobs) execute(ctx context.Context, job Job, run *execution) {
	defer close(run.done)
	// 租约监控覆盖准备与完整性校验，不能等大文件读取结束后才开始计时。
	go func() {
		ticker := time.NewTicker(200 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-run.done:
				return
			case <-ctx.Done():
				return
			case <-ticker.C:
				j.mu.Lock()
				expired := time.Now().After(run.deadline)
				j.mu.Unlock()
				if expired {
					run.cancel()
					return
				}
			}
		}
	}()
	w, err := j.Server.user(job.User)
	if err == nil {
		err = w.SyncSharedModels()
	}
	var actionErr error
	if err == nil {
		actionErr = startSnapshot(ctx, w, job)
		if actionErr == nil {
			select {
			case <-w.Done():
			case <-ctx.Done():
				w.UnloadRuntime()
				actionErr = ctx.Err()
			}
		}
		// 等待结束并卸载驻留模型，固定模板包含装载峰值，无隐含跨任务驻留预算。
		w.UnloadRuntime()
		state := w.Store.Read()
		if actionErr == nil && state.Activity != nil && state.Activity.Status != "completed" {
			actionErr = fmt.Errorf("generation did not complete")
		}
	}
	if err == nil {
		err = actionErr
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	current, e := j.read(job.ID)
	if e != nil {
		return
	}
	current.Stopped = true
	if w != nil {
		for _, file := range stateFiles(w.Store.Read()) {
			if !slices.Contains(current.BeforeFiles, file) {
				current.OutputFiles = append(current.OutputFiles, file)
			}
		}
	}
	current.ExecutionStatus = "succeeded"
	if err != nil {
		current.ExecutionStatus = "failed"
		current.Error = "Voice generation failed"
	}
	if current.Cancel || ctx.Err() != nil {
		current.ExecutionStatus = "cancelled"
	}
	_ = atomicJSON(j.path(job.ID), current)
	delete(j.active, job.ID)
	j.executing = ""
}

func startSnapshot(ctx context.Context, w *workbench.Workbench, job Job) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	switch job.Method {
	case "generation.start":
		d := schema.DefaultDraft()
		if err := json.Unmarshal(job.Data, &d); err != nil {
			return err
		}
		return w.GenerateSnapshot(d, "", "")
	case "generation.cue":
		var input struct {
			Draft  schema.Draft `json:"draft"`
			CueID  string       `json:"cueId"`
			ClipID string       `json:"clipId"`
		}
		if err := json.Unmarshal(job.Data, &input); err != nil {
			return err
		}
		return w.GenerateSnapshot(input.Draft, input.CueID, input.ClipID)
	case "character.preview":
		_, err := desktop.Call(ctx, w, job.Method, job.Data)
		return err
	default:
		return fmt.Errorf("unsupported queued method")
	}
}

func stateFiles(state schema.State) []string {
	files := []string{}
	for _, g := range state.History {
		files = append(files, g.FileName)
	}
	for _, g := range state.Previews {
		files = append(files, g.FileName)
	}
	for _, c := range state.Characters {
		if c.Preview != nil {
			files = append(files, c.Preview.FileName)
		}
	}
	return files
}

func (j *Jobs) hiddenFiles(user string, state schema.State) (map[string]bool, *Job) {
	hidden := map[string]bool{}
	var pending *Job
	paths, _ := filepath.Glob(filepath.Join(j.Server.Root, "jobs", "*.json"))
	for _, path := range paths {
		job, err := j.read(strings.TrimSuffix(filepath.Base(path), ".json"))
		if err != nil || job.User != user || job.Status == "succeeded" {
			continue
		}
		for _, file := range job.OutputFiles {
			hidden[file] = true
		}
		if job.Attempt != "" && !job.Stopped {
			for _, file := range stateFiles(state) {
				if !slices.Contains(job.BeforeFiles, file) {
					hidden[file] = true
				}
			}
		}
		if job.Status != "failed" && job.Status != "cancelled" && (pending == nil || job.Created.Before(pending.Created)) {
			copy := job
			pending = &copy
		}
	}
	return hidden, pending
}

// VisibleState 只有调度器确认当前任务成功后才向用户发布暂存结果。
func (j *Jobs) VisibleState(user string, state schema.State) schema.State {
	j.mu.Lock()
	defer j.mu.Unlock()
	hidden, pending := j.hiddenFiles(user, state)
	state.History = slices.DeleteFunc(state.History, func(g schema.Generation) bool { return hidden[g.FileName] })
	state.Previews = slices.DeleteFunc(state.Previews, func(g schema.CharacterPreview) bool { return hidden[g.FileName] })
	for i := range state.Characters {
		if state.Characters[i].Preview != nil && hidden[state.Characters[i].Preview.FileName] {
			state.Characters[i].Preview = nil
		}
	}
	if pending != nil && (state.Activity == nil || state.Activity.Status != "running") {
		state.Activity = &schema.Activity{Kind: "generate", Code: msg.ActivityGenerate, Status: "running", RequestID: pending.ID, StartedAt: pending.Created}
	}
	return state
}

func (j *Jobs) OutputAllowed(user, file string, state schema.State) bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	hidden, _ := j.hiddenFiles(user, state)
	return !hidden[file]
}
