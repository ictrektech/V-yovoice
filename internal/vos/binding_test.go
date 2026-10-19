package vos

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func bindingFixture(t *testing.T) (*Server, SchedulerConfig) {
	t.Helper()
	s := testServer(t)
	s.SchedulerPath = filepath.Join(t.TempDir(), "scheduler.local.json")
	controller := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/executors" || !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") {
			http.Error(w, "not allowed", 403)
			return
		}
		jsonReply(w, map[string]any{"code": "OK", "data": []any{
			map[string]any{"id": "voice.infer", "app_id": voiceAppID, "contract_version": "1", "task_type": "model.infer", "upstream_urls": []string{"http://v-voice-backend:7070/v1"}},
			map[string]any{"id": "voice.generate", "app_id": voiceAppID, "contract_version": "1", "task_type": "voice.generate"},
			map[string]any{"id": "foreign.infer", "app_id": "other-app", "contract_version": "1", "task_type": "model.infer", "upstream_urls": []string{"http://v-voice-backend:7070/v1"}},
			map[string]any{"id": "wrong-origin.infer", "app_id": voiceAppID, "contract_version": "1", "task_type": "model.infer", "upstream_urls": []string{"http://other.invalid/v1"}},
		}})
	}))
	t.Cleanup(controller.Close)
	t.Setenv("VVOICE_SCHEDULER_URL", controller.URL+"/api/v1")
	config := SchedulerConfig{ProtocolVersion: 1, BindingRevision: 1, AppID: voiceAppID,
		URL: controller.URL + "/api/v1", Token: strings.Repeat("s", 32), ExecutorToken: strings.Repeat("e", 32),
		UpstreamURL: "http://v-voice-backend:7070/v1", Models: map[string]string{"sensevoice-int8": "voice.infer", "kokoro-82m-q8": "voice.generate"},
		GatewayExecutors: map[string]string{"sensevoice-int8": "router.voice"}}
	return s, config
}

func bindRequest(s *Server, subject string, config SchedulerConfig) *httptest.ResponseRecorder {
	b, _ := json.Marshal(config)
	r := httptest.NewRequest("POST", "/api/v1/scheduler/binding", bytes.NewReader(b))
	if subject != "" {
		r.Header.Set("Authorization", "Bearer "+subject)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func TestMixedBindingJSONRoundTripAndInvalidRotation(t *testing.T) {
	changes := map[string]func(map[string]any){
		"missing protocol":   func(v map[string]any) { delete(v, "mixed_input_limits_version") },
		"zero protocol":      func(v map[string]any) { v["mixed_input_limits_version"] = 0 },
		"unknown protocol":   func(v map[string]any) { v["mixed_input_limits_version"] = 2 },
		"missing legacy":     func(v map[string]any) { delete(v, "legacy_unbounded_models") },
		"duplicate legacy":   func(v map[string]any) { v["legacy_unbounded_models"] = []string{"kokoro-82m-q8", "kokoro-82m-q8"} },
		"unapproved legacy":  func(v map[string]any) { v["legacy_unbounded_models"] = []string{"unknown"} },
		"overlapping legacy": func(v map[string]any) { v["legacy_unbounded_models"] = []string{"kokoro-82m-q8", "sensevoice-int8"} },
		"uncovered model":    func(v map[string]any) { v["models"].(map[string]any)["whisper-tiny"] = "voice.infer" },
		"native exemption": func(v map[string]any) {
			v["models"].(map[string]any)["musicgen-small"] = "voice.infer"
			v["legacy_unbounded_models"] = []string{"kokoro-82m-q8", "musicgen-small"}
		},
	}
	for name, change := range changes {
		t.Run(name, func(t *testing.T) {
			s, config := bindingFixture(t)
			version := 1
			config.MixedInputLimitsVersion = &version
			config.InputLimitsVersion = 1
			config.LegacyUnboundedModels = []string{"kokoro-82m-q8"}
			config.ModelLimits = map[string]map[string]float64{"sensevoice-int8": {"duration_seconds": 20, "sample_rate": 24000, "hotwords_characters": 0, "input_bytes": 1048576}}
			if response := bindRequest(s, schedulerAppID, config); response.Code != 200 {
				t.Fatalf("mixed binding rejected: %d %s", response.Code, response.Body.String())
			}
			stored, err := readSchedulerConfig(s.SchedulerPath)
			if err != nil || stored.MixedInputLimitsVersion == nil || *stored.MixedInputLimitsVersion != 1 || len(stored.LegacyUnboundedModels) != 1 || stored.LegacyUnboundedModels[0] != "kokoro-82m-q8" {
				t.Fatal("mixed JSON fields lost on disk")
			}
			before, _ := os.ReadFile(s.SchedulerPath)
			config.BindingRevision++
			encoded, _ := json.Marshal(config)
			var document map[string]any
			json.Unmarshal(encoded, &document)
			change(document)
			encoded, _ = json.Marshal(document)
			r := httptest.NewRequest("POST", "/api/v1/scheduler/binding", bytes.NewReader(encoded))
			r.Header.Set("Authorization", "Bearer "+schedulerAppID)
			response := httptest.NewRecorder()
			s.ServeHTTP(response, r)
			if response.Code < 400 {
				t.Fatal("invalid mixed rotation accepted")
			}
			after, _ := os.ReadFile(s.SchedulerPath)
			if !bytes.Equal(before, after) {
				t.Fatal("invalid rotation replaced approved binding")
			}
		})
	}
}

func TestBindingPreservesCalibratedInputLimits(t *testing.T) {
	server, config := bindingFixture(t)
	config.InputLimitsVersion = 1
	config.ModelLimits = map[string]map[string]float64{"sensevoice-int8": {"duration_seconds": 20, "sample_rate": 24000, "hotwords_characters": 0, "input_bytes": 1048576}}
	if response := bindRequest(server, schedulerAppID, config); response.Code != 200 {
		t.Fatalf("binding failed: %d %s", response.Code, response.Body.String())
	}
	stored, err := readSchedulerConfig(server.SchedulerPath)
	if err != nil || stored.InputLimitsVersion != 1 || stored.ModelLimits["sensevoice-int8"]["duration_seconds"] != 20 {
		t.Fatal("calibrated input limits were not preserved")
	}
	config.InputLimitsVersion = 0
	if validateBinding(config) == nil {
		t.Fatal("missing input protocol accepted")
	}
	config.InputLimitsVersion = 1
	delete(config.ModelLimits["sensevoice-int8"], "sample_rate")
	if validateBinding(config) == nil {
		t.Fatal("incomplete input calibration accepted")
	}
}

func TestNativeMusicRequiresMatchingExecutionCalibration(t *testing.T) {
	server, config := bindingFixture(t)
	t.Setenv("VVOICE_PROVIDER", "cuda")
	config.Models["musicgen-small"] = "voice.infer"
	config.InputLimitsVersion = 1
	config.ModelLimits = map[string]map[string]float64{"musicgen-small": {"duration_seconds": 10, "prompt_characters": 128, "negative_prompt_characters": 128}}
	config.ExecutionSettings = map[string]any{"music": map[string]any{"provider": "cuda", "torch_threads": float64(4), "torch_interop_threads": float64(1), "max_concurrent_jobs": float64(1), "max_loaded_models": float64(1), "steps": float64(8), "runtime": "pytorch-music-v1"}}
	if response := bindRequest(server, schedulerAppID, config); response.Code != 200 {
		t.Fatalf("native music binding rejected: %d %s", response.Code, response.Body.String())
	}
	config.ExecutionSettings["music"].(map[string]any)["torch_threads"] = float64(8)
	if validateBinding(config) == nil {
		t.Fatal("uncalibrated thread count accepted")
	}
	config.ExecutionSettings = nil
	if validateBinding(config) == nil {
		t.Fatal("missing music calibration accepted")
	}
}

func TestBindingOnlyAcceptsSameVosSchedulerApplication(t *testing.T) {
	s, config := bindingFixture(t)
	for _, subject := range []string{"", "disabled", "admin-user", "com.ictrek.other-app"} {
		response := bindRequest(s, subject, config)
		if response.Code != 401 && response.Code != 403 {
			t.Fatalf("subject %s status %d", subject, response.Code)
		}
	}
	if _, err := os.Stat(s.SchedulerPath); !os.IsNotExist(err) {
		t.Fatal("unauthorized configuration written")
	}
	if response := bindRequest(s, schedulerAppID, config); response.Code != 200 {
		t.Fatalf("binding status=%d: %s", response.Code, response.Body.String())
	}
}

func TestBindingPersistsPrivatelyAndReloadsWithoutRestart(t *testing.T) {
	s, config := bindingFixture(t)
	jobs := &Jobs{Server: s, ConfigPath: s.SchedulerPath}
	if jobs.configured() {
		t.Fatal("missing configuration accepted")
	}
	if bindRequest(s, schedulerAppID, config).Code != 200 {
		t.Fatal("binding rejected")
	}
	info, err := os.Stat(s.SchedulerPath)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("configuration permissions")
	}
	if !jobs.configured() || jobs.config().Token != config.Token {
		t.Fatal("binding not hot loaded")
	}
	response := httptest.NewRecorder()
	s.ServeHTTP(response, httptest.NewRequest("GET", "/api/v1/scheduler/binding", nil))
	if response.Code != 200 || strings.Contains(response.Body.String(), config.Token) || strings.Contains(response.Body.String(), config.ExecutorToken) {
		t.Fatal("public status leaked credentials")
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("binding status cached")
	}
	if !strings.Contains(response.Body.String(), `"configured":true`) {
		t.Fatal("configured status missing")
	}
}

func TestBindingRevisionRetriesAndRotationAreMonotonic(t *testing.T) {
	s, config := bindingFixture(t)
	if bindRequest(s, schedulerAppID, config).Code != 200 {
		t.Fatal("initial binding")
	}
	if bindRequest(s, schedulerAppID, config).Code != 200 {
		t.Fatal("idempotent retry")
	}
	changed := config
	changed.Token = strings.Repeat("n", 32)
	if bindRequest(s, schedulerAppID, changed).Code != 409 {
		t.Fatal("same revision overwritten")
	}
	changed.BindingRevision = 2
	if bindRequest(s, schedulerAppID, changed).Code != 200 {
		t.Fatal("rotation rejected")
	}
	if bindRequest(s, schedulerAppID, config).Code != 409 {
		t.Fatal("old revision replayed")
	}
	current, err := readSchedulerConfig(s.SchedulerPath)
	if err != nil || current.BindingRevision != 2 || current.Token != changed.Token {
		t.Fatal("rotation lost")
	}
	previous, err := readSchedulerConfig(s.SchedulerPath + ".previous")
	if err != nil || previous.BindingRevision != 1 || previous.Token != config.Token {
		t.Fatal("rollback copy lost")
	}
}

func TestBindingRejectsUnapprovedExecutorsAndLeavesPreviousBinding(t *testing.T) {
	for _, executor := range []string{"missing", "foreign.infer", "wrong-origin.infer", "voice.generate"} {
		t.Run(executor, func(t *testing.T) {
			s, config := bindingFixture(t)
			if bindRequest(s, schedulerAppID, config).Code != 200 {
				t.Fatal("initial binding")
			}
			config.BindingRevision = 2
			config.Models["sensevoice-int8"] = executor
			if bindRequest(s, schedulerAppID, config).Code != 503 {
				t.Fatal("unapproved binding accepted")
			}
			previous, err := readSchedulerConfig(s.SchedulerPath)
			if err != nil || previous.BindingRevision != 1 {
				t.Fatal("preflight failure overwrote old configuration")
			}
		})
	}
}

func TestBindingCannotRedirectCredentialsOrOverwriteUnsafeFile(t *testing.T) {
	s, config := bindingFixture(t)
	redirected := config
	redirected.URL = "https://external.invalid/api/v1"
	if bindRequest(s, schedulerAppID, redirected).Code != 422 {
		t.Fatal("credential redirect accepted")
	}
	redirected = config
	redirected.UpstreamURL = "http://another-model:7070/v1"
	if bindRequest(s, schedulerAppID, redirected).Code != 422 {
		t.Fatal("wrong origin accepted")
	}
	if err := os.WriteFile(s.SchedulerPath, []byte(`{}`), 0644); err != nil {
		t.Fatal(err)
	}
	if bindRequest(s, schedulerAppID, config).Code != 503 {
		t.Fatal("unsafe existing file overwritten")
	}
}
