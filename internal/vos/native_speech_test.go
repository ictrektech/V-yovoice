package vos

import (
	"context"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"yovoice/internal/platform"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

// 仅在构建机显式指定真实内核和共享模型时运行；失败日志只包含本测试的合成文本。
func TestNativeKokoroSpeech(t *testing.T) {
	runtime := os.Getenv("VVOICE_NATIVE_TEST_RUNTIME")
	if runtime == "" {
		t.Skip("real native runtime not selected")
	}
	for _, tool := range []string{"kokoro/libespeak-ng.so", "kokoro/libmecab.so.2", "ffmpeg", "ffprobe"} {
		if _, err := platform.PackagedTool(tool); err != nil {
			t.Fatalf("packaged tool unavailable: %s", tool)
		}
	}
	w, err := workbench.New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	if err = w.UseBundled(runtime); err != nil {
		t.Fatal(err)
	}
	if err = w.SyncSharedModels(); err != nil {
		t.Fatal(err)
	}
	d := schema.DefaultDraft()
	d.ModelID, d.Speaker, d.SynthesisLanguage = "kokoro-82m-q8", "af_heart", "en-us"
	d.Text = "Hello, welcome to V Voice."
	if _, err = w.Synthesize(context.Background(), d); err != nil {
		for _, name := range []string{"engine.log", "engine.log.out", "last-inference-error.txt"} {
			if b, e := os.ReadFile(filepath.Join(w.Store.Root, "logs", name)); e == nil {
				if len(b) > 16000 {
					b = b[len(b)-16000:]
				}
				t.Logf("%s: %s", name, b)
			}
		}
		t.Fatal(err)
	}
	server := &Server{Root: t.TempDir(), Runtime: runtime}
	strength := 0.6
	if _, err = server.synthesize(httptest.NewRequest("POST", "/internal/speech", nil), speechInput{Model: d.ModelID, Text: d.Text, Voice: d.Speaker, Language: "en", Speed: 1, EmotionStrength: &strength}); err != nil {
		t.Fatalf("standard speech mapping: %v", err)
	}
}
