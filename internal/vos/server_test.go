package vos

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/schema"
)

func testServer(t *testing.T) *Server {
	t.Helper()
	t.Setenv("MODEL_HUB_SHARED_MODELS_PATH", t.TempDir())
	identity := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sub := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if sub == "disabled" {
			_, _ = w.Write([]byte(`{"sub":"disabled","enable":0}`))
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"sub": sub, "enable": 1, "role_code": "member"})
	}))
	t.Cleanup(identity.Close)
	s := &Server{Root: t.TempDir(), Assets: t.TempDir(), UserinfoURL: identity.URL}
	t.Cleanup(func() { s.Close(context.Background()) })
	return s
}

func rpc(s *Server, user, method, data string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("POST", "/studio-api/call", strings.NewReader(`{"method":"`+method+`","data":`+data+`}`))
	if user != "" {
		r.Header.Set("Authorization", "Bearer "+user)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func TestBrowserRequiresEnabledValidatedIdentity(t *testing.T) {
	s := testServer(t)
	for _, user := range []string{"", "disabled"} {
		if got := rpc(s, user, "state.get", "{}").Code; got != 401 {
			t.Fatalf("status=%d", got)
		}
	}
	if got := rpc(s, "alice", "state.get", "{}").Code; got != 200 {
		t.Fatalf("status=%d", got)
	}
}

func TestDevelopmentIdentityRequiresExplicitMatchingToken(t *testing.T) {
	s := &Server{DevToken: "local-development-token-at-least-32-characters"}
	for _, user := range []string{"", "wrong-token", "short"} {
		r := httptest.NewRequest("POST", "/studio-api/call", nil)
		if user != "" {
			r.Header.Set("Authorization", "Bearer "+user)
		}
		if _, err := s.identity(r); err == nil {
			t.Fatalf("development identity accepted %q", user)
		}
	}
	r := httptest.NewRequest("POST", "/studio-api/call", nil)
	r.Header.Set("Authorization", "Bearer "+s.DevToken)
	identity, err := s.identity(r)
	if err != nil || identity.Subject != "local-development" || identity.Role != "system_admin" {
		t.Fatalf("development identity rejected: %#v %v", identity, err)
	}
	s.DevToken = "short"
	r.Header.Set("Authorization", "Bearer "+s.DevToken)
	if _, err := s.identity(r); err == nil {
		t.Fatal("short development token accepted")
	}
}

func TestDevelopmentModelsUseCatalogWithoutClaimingInstallation(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "catalog"), 0700); err != nil {
		t.Fatal(err)
	}
	data := `{"models":[{"key":"test-asr","name":"Test ASR","kind":"asr","modelscope_repo":"org/test-asr","languages":["zh"]}]}`
	if err := os.WriteFile(filepath.Join(root, "catalog", "models.json"), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	s := &Server{DevToken: "local-development-token-at-least-32-characters", SchedulerPath: filepath.Join(root, "scheduler.json"), Assets: t.TempDir()}
	for _, path := range []string{"/api/v1/models", "/api/v1/creative-models"} {
		w := httptest.NewRecorder()
		s.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		var rows []struct {
			ModelScopeRepo string `json:"modelscope_repo"`
			Status         string `json:"status"`
			Loaded         bool   `json:"loaded"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &rows); w.Code != 200 || err != nil || len(rows) != 1 {
			t.Fatalf("%s: status=%d body=%s error=%v", path, w.Code, w.Body.String(), err)
		}
		if rows[0].ModelScopeRepo != "org/test-asr" || rows[0].Status != "not_installed" || rows[0].Loaded {
			t.Fatalf("%s: unexpected model: %#v", path, rows[0])
		}
	}
	s.DevToken = ""
	w := httptest.NewRecorder()
	s.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/models", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("development catalog exposed without development token: %d", w.Code)
	}
}

func TestIdentityUsesVosIntegerEnableContract(t *testing.T) {
	for _, tc := range []struct {
		name, body string
		accepted   bool
	}{
		{"enabled", `{"sub":"user","enable":1,"role_code":"system_admin"}`, true},
		{"disabled", `{"sub":"user","enable":0}`, false},
		{"missing-enable", `{"sub":"user"}`, false},
		{"wrong-type", `{"sub":"user","enable":true}`, false},
		{"invalid-enable", `{"sub":"user","enable":2}`, false},
		{"missing-sub", `{"enable":1}`, false},
		{"platform-error-envelope", `{"code":10001,"data":null}`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer test-token" {
					t.Error("missing bearer forwarding")
				}
				_, _ = w.Write([]byte(tc.body))
			}))
			defer upstream.Close()
			s := &Server{UserinfoURL: upstream.URL}
			r := httptest.NewRequest("POST", "/studio-api/call", nil)
			r.Header.Set("Authorization", "Bearer test-token")
			identity, err := s.identity(r)
			if (err == nil) != tc.accepted {
				t.Fatalf("accepted=%v, error=%v", tc.accepted, err)
			}
			if tc.accepted && identity.Role != "system_admin" {
				t.Fatal("role lost")
			}
		})
	}
}

func TestUsersHaveSeparatePersistentProjects(t *testing.T) {
	s := testServer(t)
	for _, user := range []string{"alice", "bob"} {
		if rpc(s, user, "state.get", "{}").Code != 200 {
			t.Fatal("identity failed")
		}
	}
	if len(s.users) != 2 {
		t.Fatal("users share one workbench")
	}
	var roots []string
	for _, w := range s.users {
		roots = append(roots, w.Store.Root)
	}
	if roots[0] == roots[1] {
		t.Fatal("shared private path")
	}
	for _, root := range roots {
		if !strings.HasPrefix(root, filepath.Join(s.Root, "users")) {
			t.Fatal("private root escaped")
		}
	}
}

func TestBrowserCannotUseDesktopPathsOrDownloadAsMember(t *testing.T) {
	s := testServer(t)
	for _, method := range []string{"project.import", "model.import", "storage.relocate", "runtime.install", "model.download"} {
		if got := rpc(s, "alice", method, `{"path":"/etc/passwd","id":"index-2.5-q8"}`).Code; got != 403 {
			t.Fatalf("%s status=%d", method, got)
		}
	}
}

func TestSpeechInternalEndpointCannotBeCalledWithoutSecret(t *testing.T) {
	s := testServer(t)
	t.Setenv("VVOICE_STUDIO_INTERNAL_TOKEN", strings.Repeat("x", 32))
	w := httptest.NewRecorder()
	s.ServeHTTP(w, httptest.NewRequest("POST", "/internal/speech", strings.NewReader(`{}`)))
	if w.Code != 401 {
		t.Fatalf("status=%d", w.Code)
	}
}

func TestJobOutboxIsPrivateStableAndFailClosed(t *testing.T) {
	s := testServer(t)
	j := &Jobs{Server: s}
	key := schema.NewID()
	data := json.RawMessage(`{"modelId":"index-2.5-q8","text":"test"}`)
	if _, err := j.Enqueue("alice", key, "generation.start", data); err == nil {
		t.Fatal("missing scheduler accepted")
	}
	j.Config = SchedulerConfig{URL: "http://scheduler.invalid", Token: strings.Repeat("x", 32), ExecutorToken: strings.Repeat("y", 32), Models: map[string]string{"index-2.5-q8": "voice.generate"}}
	first, err := j.Enqueue("alice", key, "generation.start", data)
	if err != nil {
		t.Fatal(err)
	}
	second, err := j.Enqueue("alice", key, "generation.start", data)
	if err != nil || first != second {
		t.Fatal("duplicate outbox")
	}
	if _, err = j.Enqueue("alice", key, "generation.start", json.RawMessage(`{"modelId":"index-2.5-q8","text":"changed"}`)); err == nil {
		t.Fatal("idempotency conflict ignored")
	}
	info, err := os.Stat(j.path(key))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatal("outbox not private")
	}
	if _, err = j.Enqueue("alice", key, "generation.start", json.RawMessage(`{ "text": "test", "modelId": "index-2.5-q8" }`)); err != nil {
		t.Fatal("equivalent JSON changed idempotency")
	}
	called := false
	if _, err = j.withoutPending("alice", func() (any, error) { called = true; return true, nil }); err == nil || called {
		t.Fatal("queued input deletion was allowed")
	}
}

func TestLegacySchedulerIdentityIsVerifiedBySameVOS(t *testing.T) {
	for _, name := range []string{"scheduler", "ordinary-admin", "other-app", "disabled", "deleted", "expired"} {
		t.Run(name, func(t *testing.T) {
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/v1000/oauth2/userinfo" {
					w.WriteHeader(401)
					json.NewEncoder(w).Encode(map[string]any{"error": "invalid_token"})
					return
				}
				if r.URL.Path != "/v1000/user/check" || r.Header.Get("Authorization") != "Bearer fixture" {
					t.Error("unexpected identity request")
					w.WriteHeader(401)
					return
				}
				user := map[string]any{"id": "context-user", "username": schedulerAppID, "role_code": "system_admin", "enable": 1, "delete": 0}
				code := 0
				switch name {
				case "ordinary-admin":
					user["username"] = "admin"
				case "other-app":
					user["username"] = "com.ictrek.other"
				case "disabled":
					user["enable"] = 0
				case "deleted":
					user["delete"] = 1
				case "expired":
					code = 10001
				}
				json.NewEncoder(w).Encode(map[string]any{"code": code, "data": user})
			}))
			defer upstream.Close()
			server := &Server{UserinfoURL: upstream.URL + "/v1000/oauth2/userinfo"}
			request := httptest.NewRequest("POST", "/api/v1/scheduler/binding", nil)
			request.Header.Set("Authorization", "Bearer fixture")
			identity, err := server.verifyIdentity(request, true)
			if name == "scheduler" {
				if err != nil || identity.Subject != schedulerAppID {
					t.Fatalf("valid service rejected: %v", err)
				}
			} else if err == nil {
				t.Fatal("untrusted identity accepted")
			}
			if _, err := server.identity(request); err == nil {
				t.Fatal("legacy service fallback leaked into browser user authentication")
			}
		})
	}
}
