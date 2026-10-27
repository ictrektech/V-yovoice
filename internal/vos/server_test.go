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
	if got := rpc(s, "alice", "state.get", "{}"); got.Code != 200 || !strings.Contains(got.Body.String(), `"assistant":{"available":false}`) {
		t.Fatalf("状态缺少助手可用性: %d %s", got.Code, got.Body.String())
	}
}

// 歌词校准只修改当前用户的历史元数据，不能操作其他用户的生成版本。
func TestBrowserLyricTimingIsUserScoped(t *testing.T) {
	s := testServer(t)
	request := httptest.NewRequest("POST", "/studio-api/call", nil)
	request.Header.Set("Authorization", "Bearer alice")
	identity, err := s.identity(request)
	if err != nil {
		t.Fatal(err)
	}
	w, err := s.user(identity.Key)
	if err != nil {
		t.Fatal(err)
	}
	id := schema.NewID()
	if err = os.WriteFile(filepath.Join(w.Store.Root, "outputs", id+".wav"), []byte("audio"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = w.Store.Update(func(state *schema.State) {
		state.History = []schema.Generation{{ID: id, FileName: id + ".wav", Duration: 3, Settings: schema.DefaultDraft()}}
	}, true); err != nil {
		t.Fatal(err)
	}
	data := `{"id":"` + id + `","times":[0,1,2]}`
	if got := rpc(s, "", "generation.lyricTimes", data); got.Code != 401 {
		t.Fatalf("未登录请求 status=%d", got.Code)
	}
	if got := rpc(s, "bob", "generation.lyricTimes", data); !strings.Contains(got.Body.String(), `"error"`) {
		t.Fatal("允许跨用户校准", got.Body.String())
	}
	if got := rpc(s, "alice", "generation.lyricTimes", data); got.Code != 200 || !strings.Contains(got.Body.String(), `"result":true`) {
		t.Fatal("歌词校准失败", got.Body.String())
	}
	if got := w.Store.Read().History[0].LyricTimes; len(got) != 3 || got[1] != 1 {
		t.Fatal("歌词校准未保存", got)
	}
	if got := rpc(s, "alice", "generation.lyricTimes", `{"id":"`+id+`","times":[2,1]}`); !strings.Contains(got.Body.String(), `"error"`) {
		t.Fatal("允许倒序校准", got.Body.String())
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
	for _, method := range []string{"project.import", "model.import", "storage.relocate", "runtime.install", "model.download", "assistant.send", "assistant.run", "ai.codex.login", "logs.export", "assets.delete"} {
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
