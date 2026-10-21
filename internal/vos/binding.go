package vos

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"time"
	"yovoice/internal/catalog"
)

const voiceAppID = "com.ictrek.v-voice"
const schedulerAppID = "com.ictrek.v-scheduler"

func readSchedulerConfig(path string) (SchedulerConfig, error) {
	var config SchedulerConfig
	info, err := os.Lstat(path)
	if err != nil {
		return config, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 256<<10 {
		return config, fmt.Errorf("scheduler configuration must be a private regular file")
	}
	b, err := os.ReadFile(path)
	if err == nil {
		err = json.Unmarshal(b, &config)
	}
	return config, err
}

func (s *Server) schedulerPath() string {
	if s.SchedulerPath != "" {
		return s.SchedulerPath
	}
	if path := os.Getenv("VVOICE_SCHEDULER_CONFIG"); path != "" {
		return path
	}
	return "/data/scheduler.local.json"
}

func (s *Server) bindingStatus() map[string]any {
	config, err := readSchedulerConfig(s.schedulerPath())
	configured := err == nil && config.URL != "" && len(config.Token) >= 32 && len(config.ExecutorToken) >= 32
	return map[string]any{"protocol_version": 1, "binding_revision": config.BindingRevision,
		"configured": configured, "approved_model_count": len(config.Models)}
}

var bindingID = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,128}$`)

func validateBinding(config SchedulerConfig) error {
	expectedURL := os.Getenv("VVOICE_SCHEDULER_URL")
	if expectedURL == "" {
		expectedURL = "http://v-router:8080/scheduler/api/v1"
	}
	upstream := os.Getenv("VVOICE_SCHEDULER_UPSTREAM_URL")
	if upstream == "" {
		upstream = "http://v-voice-backend:7070/v1"
	}
	if config.ProtocolVersion != 1 || config.BindingRevision < 1 || config.AppID != voiceAppID ||
		config.URL != expectedURL || config.UpstreamURL != upstream ||
		len(config.Token) < 32 || len(config.Token) > 4096 || len(config.ExecutorToken) < 32 || len(config.ExecutorToken) > 4096 ||
		strings.ContainsAny(config.Token+config.ExecutorToken, "\r\n\t ") || len(config.Models) == 0 || len(config.Models) > 512 {
		return fmt.Errorf("invalid application binding")
	}
	for _, models := range []map[string]string{config.Models, config.GatewayExecutors} {
		if len(models) > 512 {
			return fmt.Errorf("too many model bindings")
		}
		for model, executor := range models {
			if !bindingID.MatchString(model) || !bindingID.MatchString(executor) {
				return fmt.Errorf("invalid model binding")
			}
		}
	}
	if len(config.SecondaryModels) > 512 {
		return fmt.Errorf("too many combined bindings")
	}
	if config.MixedInputLimitsVersion != nil || config.LegacyUnboundedModels != nil {
		if config.MixedInputLimitsVersion == nil || *config.MixedInputLimitsVersion != 1 || config.InputLimitsVersion != 1 ||
			len(config.LegacyUnboundedModels) == 0 || len(config.LegacyUnboundedModels) > 512 || len(config.ModelLimits) == 0 {
			return fmt.Errorf("invalid mixed calibrated input protocol")
		}
		legacy := map[string]bool{}
		for _, model := range config.LegacyUnboundedModels {
			_, bounded := config.ModelLimits[model]
			if !bindingID.MatchString(model) || config.Models[model] == "" || legacy[model] || bounded || nativeMusicModel(model) {
				return fmt.Errorf("invalid legacy input exemption")
			}
			legacy[model] = true
		}
		for model := range config.Models {
			if _, bounded := config.ModelLimits[model]; !bounded && !legacy[model] {
				return fmt.Errorf("mixed input calibration must cover every model")
			}
		}
	}
	if config.ModelLimits != nil || config.InputLimitsVersion != 0 {
		if config.InputLimitsVersion != 1 || len(config.ModelLimits) == 0 || len(config.ModelLimits) > 512 {
			return fmt.Errorf("invalid calibrated input protocol")
		}
		for model, limits := range config.ModelLimits {
			fields := []string{"text_characters", "speed_min", "speed_max"}
			if model == "sensevoice-int8" {
				fields = []string{"duration_seconds", "sample_rate", "hotwords_characters", "input_bytes"}
			} else if nativeMusicModel(model) {
				fields = []string{"duration_seconds", "prompt_characters", "negative_prompt_characters"}
				if !validMusicSettings(config.ExecutionSettings) {
					return fmt.Errorf("music execution settings require calibration")
				}
			} else if model != "kokoro-multilang" {
				return fmt.Errorf("unsupported calibrated model")
			}
			if config.Models[model] == "" || len(limits) != len(fields) {
				return fmt.Errorf("incomplete calibrated input limits")
			}
			for _, field := range fields {
				value, exists := limits[field]
				if !exists || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 || (value == 0 && field != "hotwords_characters" && field != "negative_prompt_characters") {
					return fmt.Errorf("invalid calibrated input limit")
				}
			}
			if model == "kokoro-multilang" && limits["speed_min"] > limits["speed_max"] {
				return fmt.Errorf("invalid calibrated speed range")
			}
		}
	}
	for model, secondary := range config.SecondaryModels {
		if config.Models[model] == "" || len(secondary) > 64 {
			return fmt.Errorf("invalid combined binding")
		}
		for _, id := range secondary {
			// 组合预算由已核验的调度器校准；每个模型仍须通过执行器审批预检。
			if config.Models[id] == "" {
				return fmt.Errorf("combined models require approved mappings")
			}
		}
	}
	return nil
}

// 原生配乐使用独立权重和线程参数，不能继承旧 V-Music 或 audio.cpp 的预算。
func nativeMusicModel(id string) bool {
	return id == "ace-step-1.5-turbo" || id == "stable-audio-3-small-music" || id == "stable-audio-3-medium" || id == "musicgen-small"
}

func validMusicSettings(settings map[string]any) bool {
	threads := func(key string, fallback int) float64 {
		if n, err := strconv.Atoi(os.Getenv(key)); err == nil && n > 0 {
			return float64(n)
		}
		return float64(fallback)
	}
	provider := os.Getenv("VVOICE_PROVIDER")
	if provider == "" {
		provider = "auto"
	}
	want := map[string]any{"provider": provider, "torch_threads": threads("VVOICE_MUSIC_TORCH_THREADS", 4),
		"torch_interop_threads": threads("VVOICE_MUSIC_TORCH_INTEROP_THREADS", 1), "max_concurrent_jobs": float64(1),
		"max_loaded_models": float64(1), "steps": float64(8), "runtime": "pytorch-music-v1"}
	return reflect.DeepEqual(settings["music"], want)
}

func (s *Server) verifyBinding(r *http.Request, config SchedulerConfig) error {
	req, err := http.NewRequestWithContext(r.Context(), "GET", config.URL+"/executors", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+config.Token)
	client := s.Client
	if client == nil {
		client = &http.Client{Timeout: 8 * time.Second}
	}
	boundedClient := *client
	boundedClient.CheckRedirect = func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }
	res, err := boundedClient.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	var envelope struct {
		Code string `json:"code"`
		Data []struct {
			ID              string   `json:"id"`
			AppID           string   `json:"app_id"`
			ContractVersion string   `json:"contract_version"`
			TaskType        string   `json:"task_type"`
			Upstreams       []string `json:"upstream_urls"`
		} `json:"data"`
	}
	if res.StatusCode != 200 || json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&envelope) != nil || envelope.Code != "OK" {
		return fmt.Errorf("scheduler preflight failed")
	}
	approved := map[string]string{}
	for _, executor := range envelope.Data {
		if executor.AppID != config.AppID || executor.ContractVersion != "1" {
			continue
		}
		if executor.TaskType == "voice.generate" {
			approved[executor.ID] = executor.TaskType
		}
		if executor.TaskType == "model.infer" {
			for _, upstream := range executor.Upstreams {
				if upstream == config.UpstreamURL {
					approved[executor.ID] = executor.TaskType
				}
			}
		}
	}
	for model, executor := range config.Models {
		taskType := "model.infer"
		if _, err := catalog.Lookup(model); err == nil {
			taskType = "voice.generate"
		}
		if approved[executor] != taskType {
			return fmt.Errorf("executor not approved for V-Voice")
		}
	}
	return nil
}

func (s *Server) binding(out http.ResponseWriter, r *http.Request) {
	out.Header().Set("Cache-Control", "no-store")
	if r.Method == "GET" {
		jsonReply(out, s.bindingStatus())
		return
	}
	if r.Method != "POST" {
		http.Error(out, "Method not allowed", 405)
		return
	}
	id, err := s.verifyIdentity(r, true)
	if err != nil {
		http.Error(out, "VOS application sign-in required", 401)
		return
	}
	if id.Subject != schedulerAppID {
		http.Error(out, "V-Scheduler application identity required", 403)
		return
	}
	var config SchedulerConfig
	decoder := json.NewDecoder(http.MaxBytesReader(out, r.Body, 256<<10))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&config) != nil || decoder.Decode(new(any)) != io.EOF || validateBinding(config) != nil {
		http.Error(out, "Invalid Scheduler binding", 422)
		return
	}
	// 同进程串行比较与替换 revision，避免并发重试覆盖较新的授权。
	s.mu.Lock()
	defer s.mu.Unlock()
	old, oldErr := readSchedulerConfig(s.schedulerPath())
	if oldErr != nil && !os.IsNotExist(oldErr) {
		http.Error(out, "Existing Scheduler binding is not private or readable", 503)
		return
	}
	if oldErr == nil && old.BindingRevision >= config.BindingRevision {
		oldJSON, _ := json.Marshal(old)
		newJSON, _ := json.Marshal(config)
		if old.BindingRevision == config.BindingRevision && bytes.Equal(oldJSON, newJSON) {
			jsonReply(out, s.bindingStatus())
			return
		}
		http.Error(out, "Scheduler binding revision conflict", 409)
		return
	}
	if err = s.verifyBinding(r, config); err != nil {
		http.Error(out, "Scheduler binding preflight unavailable", 503)
		return
	}
	if oldErr == nil {
		if err = atomicJSON(s.schedulerPath()+".previous", old); err != nil {
			http.Error(out, "Cannot preserve previous binding", 503)
			return
		}
	}
	if err = atomicJSON(s.schedulerPath(), config); err != nil {
		http.Error(out, "Cannot persist Scheduler binding", 503)
		return
	}
	jsonReply(out, s.bindingStatus())
}

// 兼容只支持 user/check 的旧版 VOS；只能验证已启用的 Scheduler 服务身份。
func (s *Server) legacySchedulerIdentity(r *http.Request, client *http.Client) (Identity, error) {
	target, err := url.Parse(s.UserinfoURL)
	if err != nil {
		return Identity{}, fmt.Errorf("invalid VOS endpoint")
	}
	target.Path, target.RawQuery, target.Fragment = "/v1000/user/check", "", ""
	request, err := http.NewRequestWithContext(r.Context(), "GET", target.String(), nil)
	if err != nil {
		return Identity{}, err
	}
	request.Header.Set("Authorization", r.Header.Get("Authorization"))
	bounded := *client
	bounded.CheckRedirect = func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }
	response, err := bounded.Do(request)
	if err != nil {
		return Identity{}, err
	}
	defer response.Body.Close()
	var envelope struct {
		Code *int `json:"code"`
		Data struct {
			ID       string `json:"id"`
			Username string `json:"username"`
			Role     string `json:"role_code"`
			Enable   int    `json:"enable"`
			Delete   *int   `json:"delete"`
		} `json:"data"`
	}
	if response.StatusCode != 200 || json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&envelope) != nil || envelope.Code == nil || *envelope.Code != 0 || envelope.Data.ID == "" || envelope.Data.Username != schedulerAppID || envelope.Data.Role != "system_admin" || envelope.Data.Enable != 1 || envelope.Data.Delete == nil || *envelope.Data.Delete != 0 {
		return Identity{}, fmt.Errorf("VOS application identity required")
	}
	return Identity{Subject: envelope.Data.Username, Role: envelope.Data.Role}, nil
}
