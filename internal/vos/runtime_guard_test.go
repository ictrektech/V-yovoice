package vos

import (
	"encoding/json"
	"testing"
)

func TestRestrictedRuntimeRejectsNestedOverrides(t *testing.T) {
	for _, data := range []string{`{"runtime":{"device":1}}`, `{"draft":{"characters":[{"settings":{"runtime":{"streaming":true}}}]}}`, `{"modelOptions":{"index_tts2":{"text_chunk_tokens":4}}}`} {
		if !restrictedRuntime(json.RawMessage(data)) {
			t.Fatalf("未拒绝 %s", data)
		}
	}
	for _, data := range []string{`{"runtime":null}`, `{"modelOptions":{"kokoro_tts":{"speed":1}}}`} {
		if restrictedRuntime(json.RawMessage(data)) {
			t.Fatalf("误拒绝 %s", data)
		}
	}
}

func TestBrowserRejectsUnapprovedRuntime(t *testing.T) {
	s := testServer(t)
	for _, data := range []string{`{"runtime":{"device":1}}`, `{"modelOptions":{"index_tts2":{"text_chunk_tokens":4}}}`} {
		if got := rpc(s, "alice", "draft.save", data).Code; got != 403 {
			t.Fatalf("接受了未批准的参数：%s status=%d", data, got)
		}
	}
}
