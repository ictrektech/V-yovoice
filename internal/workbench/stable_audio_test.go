package workbench

import (
	"os"
	"path/filepath"
	"testing"
	"time"
	"yovoice/internal/schema"
)

// Stable Audio 改编从本作品已生成的版本出发：起点必须属于同一作品且音频仍在；生成的版本记为纯音乐。
func TestStableAudioSource(t *testing.T) {
	w, err := New(t.TempDir())
	must(t, err)
	defer w.Close()
	d := schema.DefaultDraft()
	d.Kind, d.ModelID, d.Text, d.Lyrics = "music", "stable-audio-3-small-sfx-q8", "footsteps on gravel", "[verse]\n不会被唱"
	d.ModelOptions = map[string]map[string]any{"stable_audio": {"edit": "init_audio"}}
	model := schema.InstalledModel{ID: d.ModelID, Path: filepath.Join(w.Store.Root, "model.gguf")}
	must(t, os.WriteFile(model.Path, []byte("test"), 0600))
	own, foreign := schema.Generation{ID: "own", FileName: "own.wav", CreatedAt: time.Now(), Settings: d}, schema.Generation{ID: "foreign", FileName: "foreign.wav", CreatedAt: time.Now()}
	foreign.Settings.ID = "another-work"
	for _, g := range []schema.Generation{own, foreign} {
		path, err := w.Store.MediaPath("outputs", g.FileName)
		must(t, err)
		must(t, os.WriteFile(path, []byte("RIFF"), 0600))
	}
	must(t, w.Store.Update(func(s *schema.State) {
		s.Models = []schema.InstalledModel{model}
		s.History = []schema.Generation{own, foreign}
	}, true))

	for _, id := range []string{"", "foreign", "missing"} {
		d.SourceGenerationID = id
		if _, err := w.prepareSynthesis(d, w.Store.Read()); err == nil {
			t.Fatal("起点版本无效时应拒绝", id)
		}
	}
	d.SourceGenerationID = "own"
	parts, err := w.prepareSynthesis(d, w.Store.Read())
	must(t, err)
	want, _ := w.Store.MediaPath("outputs", "own.wav")
	if len(parts) != 1 || parts[0].voice != want || !parts[0].draft.Instrumental {
		t.Fatal("应以本作品的版本为起点并记为纯音乐", parts)
	}
	// 文件已删除时同样拒绝，避免内核读不到音频才报错。
	must(t, os.Remove(want))
	if _, err := w.prepareSynthesis(d, w.Store.Read()); err == nil {
		t.Fatal("起点音频丢失时应拒绝")
	}
	// 文字生成不需要起点。
	d.ModelOptions["stable_audio"]["edit"] = "off"
	parts, err = w.prepareSynthesis(d, w.Store.Read())
	must(t, err)
	if parts[0].voice != "" {
		t.Fatal(parts[0].voice)
	}
}
