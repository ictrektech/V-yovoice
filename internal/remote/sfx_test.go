package remote

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/catalog"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

// 远程音效生成保留作品类型和默认参数；缺省 kind 的语音请求保持原行为。
func TestRemoteSFXGeneration(t *testing.T) {
	plain, err := workbench.DecodeRemoteGeneration(strings.NewReader(`{"text":"hello"}`))
	must(t, err)
	if plain.Kind != "" || plain.ModelOptions["stable_audio"] != nil {
		t.Fatalf("空 kind 不应套用音效默认值：%+v", plain)
	}

	wb, err := workbench.New(t.TempDir())
	must(t, err)
	defer wb.Close()
	executable, err := os.Executable()
	must(t, err)
	model := filepath.Join(wb.Store.Root, "models", "sfx.gguf")
	must(t, os.WriteFile(model, []byte("test"), 0600))
	must(t, wb.Store.Update(func(s *schema.State) {
		s.Models = []schema.InstalledModel{{ID: "stable-audio-3-small-sfx-q8", Path: model}}
		s.RuntimePath = &executable
		s.RuntimeBackend = ptr("cpu")
		s.RuntimeVersion = ptr(catalog.EngineVersion)
		s.Preferences.Backend = "cpu"
	}, true))
	token := strings.Repeat("s", 32)
	api := &API{Workbench: wb, Token: token}
	req := httptest.NewRequest("POST", "/v1/generate", strings.NewReader(`{"kind":"sfx","text":"rain on a tin roof","modelId":"stable-audio-3-small-sfx-q8"}`))
	req.Header.Set("Authorization", "Bearer "+token)
	res := httptest.NewRecorder()
	api.ServeHTTP(res, req)
	if res.Code != 200 {
		t.Fatal(res.Code, res.Body.String())
	}
	state := wb.Store.Read()
	if len(state.History) != 1 {
		t.Fatalf("生成历史数量不对：%d", len(state.History))
	}
	settings := state.History[0].Settings
	if settings.Kind != "sfx" || !settings.Instrumental || settings.ModelOptions["stable_audio"]["duration_seconds"] != float64(5) {
		t.Fatalf("远程音效历史映射不对：%+v", settings)
	}
}
