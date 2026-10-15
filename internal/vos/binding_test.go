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
