package workbench

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"
	"yovoice/internal/catalog"
	"yovoice/internal/schema"
)

var SharedRepository = catalog.VOSRepository

// SharedModelsMode 仅 VOS 开启；桌面端继续沿用上游模型安装方式。
func SharedModelsMode() bool { return os.Getenv("VVOICE_SHARED_MODELS") == "true" }

// SharedCatalog 保留上游全部模型与精度；其他仓库文件加目录前缀防止同名覆盖。
func SharedCatalog() []catalog.ModelPackage {
	models := []catalog.ModelPackage{}
	for _, m := range catalog.Models {
		models = append(models, sharedModel(m))
	}
	return models
}

func sharedModel(m catalog.ModelPackage) catalog.ModelPackage {
	if m.RemotePath == "" {
		m.ImportRequired = true
		m.RemotePath = "imports/" + m.ID + ".gguf"
	}
	if m.Repo != "" {
		prefix := filepath.ToSlash(filepath.Join("mirrors", m.Repo))
		m.RemotePath = prefix + "/" + m.RemotePath
		m.Files = append([]catalog.ModelFile(nil), m.Files...)
		for i := range m.Files {
			m.Files[i].Path = prefix + "/" + m.Files[i].Path
		}
	}
	return m
}

// SyncSharedModels 只检查共享导出的文件元数据；实际使用前由引擎/编曲入口校验摘要。
func (w *Workbench) SyncSharedModels() error {
	root := os.Getenv("MODEL_HUB_SHARED_MODELS_PATH")
	if root == "" {
		root = "/modelhub"
	}
	base := filepath.Join(root, "export", "ms", SharedRepository, "current")
	models := []schema.InstalledModel{}
	for _, current := range catalog.Models {
		var m catalog.ModelPackage
		ready := false
		for _, version := range []catalog.ModelPackage{current, current.PreviousVersion()} {
			m = sharedModel(version)
			ready = true
			for _, f := range m.PackageFiles() {
				info, err := os.Stat(filepath.Join(base, filepath.FromSlash(f.Path)))
				if err != nil || !info.Mode().IsRegular() || info.Size() != f.Size {
					ready = false
					break
				}
			}
			if ready {
				break
			}
		}
		if !ready {
			continue
		}
		path := filepath.Join(base, filepath.FromSlash(m.RemotePath))
		if len(m.Files) > 0 {
			path = base
			if m.Repo != "" {
				path = filepath.Join(base, "mirrors", m.Repo)
			}
			if m.StripPrefix != "" {
				path = filepath.Join(path, filepath.FromSlash(m.StripPrefix))
			}
		}
		models = append(models, schema.InstalledModel{ID: m.ID, Path: path, Managed: false, SHA256: m.MainFile().SHA256})
	}
	if slices.Equal(w.Store.Read().Models, models) {
		return nil
	}
	return w.Store.Update(func(s *schema.State) { s.Models = models }, true)
}

// PullSharedModel 使用文件级补下载，避免把整个 GGUF 仓库全部下载。
func PullSharedModel(ctx context.Context, id string) error {
	var selected *catalog.ModelPackage
	for _, m := range SharedCatalog() {
		if m.ID == id {
			selected = &m
			break
		}
	}
	if selected == nil {
		return fmt.Errorf("unsupported shared model")
	}
	if selected.ImportRequired {
		return fmt.Errorf("this model requires administrator-provided weights in Model Hub")
	}
	files := []string{}
	for _, f := range selected.PackageFiles() {
		files = append(files, f.Path)
	}
	base := os.Getenv("MODEL_HUB_API_URL")
	if base == "" {
		base = "http://v-scheduler-model-hub:6005"
	}
	body := map[string]any{"source": "ms", "model_id": SharedRepository, "files": files, "append": true}
	err := postPull(ctx, base, body)
	var hubErr *modelHubError
	// 共享仓库上次下载失败后记录不是 ready，追加下载会被拒绝；改为只下载本模型文件，让失败可以重试。
	if errors.As(err, &hubErr) && hubErr.Status == http.StatusBadRequest && strings.Contains(hubErr.Detail, "append requires a ready model") {
		body["append"] = false
		err = postPull(ctx, base, body)
	}
	return err
}

type modelHubError struct {
	Status int
	Detail string
}

func (e *modelHubError) Error() string {
	if e.Detail != "" {
		return e.Detail
	}
	return fmt.Sprintf("Model Hub HTTP %d", e.Status)
}

func postPull(ctx context.Context, base string, body map[string]any) error {
	data, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, "POST", base+"/api/v1/models/pull", bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode == http.StatusConflict || (res.StatusCode >= 200 && res.StatusCode < 300) {
		return nil
	}
	payload, _ := io.ReadAll(io.LimitReader(res.Body, 64<<10))
	var reply struct {
		Detail string `json:"detail"`
		Error  struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if json.Unmarshal(payload, &reply) != nil {
		return &modelHubError{Status: res.StatusCode}
	}
	detail := reply.Detail
	if detail == "" {
		detail = reply.Error.Message
	}
	return &modelHubError{Status: res.StatusCode, Detail: detail}
}

// CancelSharedModel 只取消同一共享仓库且包含选中模型文件的活动任务。
func CancelSharedModel(ctx context.Context, id string) error {
	var files map[string]bool
	for _, model := range SharedCatalog() {
		if model.ID == id {
			files = map[string]bool{}
			for _, file := range model.PackageFiles() {
				files[file.Path] = true
			}
			break
		}
	}
	if files == nil {
		return fmt.Errorf("unsupported shared model")
	}
	base := os.Getenv("MODEL_HUB_API_URL")
	if base == "" {
		base = "http://v-scheduler-model-hub:6005"
	}
	client := &http.Client{Timeout: 30 * time.Second}
	req, err := http.NewRequestWithContext(ctx, "GET", base+"/api/v1/tasks", nil)
	if err != nil {
		return err
	}
	res, err := client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return fmt.Errorf("Model Hub tasks unavailable")
	}
	var tasks []struct {
		ID    string   `json:"task_id"`
		Repo  string   `json:"model_id"`
		Phase string   `json:"phase"`
		Files []string `json:"files"`
	}
	if json.NewDecoder(http.MaxBytesReader(nil, res.Body, 1<<20)).Decode(&tasks) != nil {
		return fmt.Errorf("invalid Model Hub tasks")
	}
	for _, task := range tasks {
		if strings.TrimPrefix(task.Repo, "ms://") != SharedRepository || (task.Phase != "PENDING" && task.Phase != "DOWNLOADING" && task.Phase != "VERIFYING") {
			continue
		}
		relevant := len(task.Files) == 0
		for _, file := range task.Files {
			relevant = relevant || files[file]
		}
		if !relevant || task.ID == "" || strings.ContainsAny(task.ID, "/?#") {
			continue
		}
		cancel, err := http.NewRequestWithContext(ctx, "POST", base+"/api/v1/tasks/"+task.ID+"/cancel", nil)
		if err != nil {
			return err
		}
		reply, err := client.Do(cancel)
		if err != nil {
			return err
		}
		reply.Body.Close()
		if reply.StatusCode < 200 || reply.StatusCode >= 300 {
			return fmt.Errorf("Model Hub cancellation rejected")
		}
	}
	return nil
}

// UnloadRuntime 等待当前生成真正结束，再停止引擎；不删除共享模型。
func (w *Workbench) UnloadRuntime() {
	w.Cancel()
	<-w.Done()
	w.engine.Stop()
}
