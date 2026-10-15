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
			_, _ = w.Write([]byte(`{"sub":"disabled","enable":false}`))
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"sub": sub, "enable": true, "role_code": "member"})
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
