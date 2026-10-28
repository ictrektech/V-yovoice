package engine

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/catalog"
	"yovoice/internal/msg"
	"yovoice/internal/schema"
)

// 新的音乐入口也必须校验共享目录中的实际权重，不能只校验语音生成入口。
func TestMelodyTasksRejectCorruptedSharedWeightsBeforeStartingEngine(t *testing.T) {
	t.Setenv("VVOICE_SHARED_MODELS", "true")
	for _, id := range []string{"yue2-3b-q8", "sheetsage2-orig", "lyric-align-q8"} {
		t.Run(id, func(t *testing.T) {
			model, err := catalog.Lookup(id)
			if err != nil {
				t.Fatal(err)
			}
			root := t.TempDir()
			weights := filepath.Join(root, "weights")
			file := weights
			if len(model.Files) > 0 {
				file = filepath.Join(weights, model.PackageFiles()[0].Path)
			}
			must(t, os.MkdirAll(filepath.Dir(file), 0700))
			must(t, os.WriteFile(file, []byte("invalid weights"), 0600))
			link := filepath.Join(root, "shared-model")
			if err := os.Symlink(weights, link); err != nil {
				t.Skipf("当前环境不支持符号链接: %v", err)
			}
			e := New(root)
			defer e.Stop()
			installed := schema.InstalledModel{ID: id, Path: link}
			progress := func(msg.Code, msg.Params) {}
			if model.Family == "yue2" {
				d := schema.DefaultDraft()
				d.ModelID, d.Kind, d.Text, d.Lyrics = id, "music", "gentle pop", "Hello world"
				_, _, err = e.PlanMelody(context.Background(), "missing-engine", installed, "cpu", d, progress)
			} else if model.Family == "lyric_align" {
				err = e.SeparateVocals(context.Background(), "missing-engine", installed, "cpu", "song.wav", "vocals.wav", progress)
				if err == nil || !strings.Contains(err.Error(), "model file size mismatch") {
					t.Fatal("分离人声未校验权重", err)
				}
				_, err = e.AlignWords(context.Background(), "missing-engine", installed, "cpu", "song.wav", "你好", "Chinese", progress)
			} else {
				_, err = e.Transcribe(context.Background(), "missing-engine", installed, "cpu", "song.wav", progress)
			}
			if err == nil || !strings.Contains(err.Error(), "model file size mismatch") || e.process != nil {
				t.Fatalf("未在启动前拒绝损坏权重: %v", err)
			}
		})
	}
}
