package engine

import (
	"testing"
	"yovoice/internal/schema"
)

// 音效作品复用 Stable Audio 音乐请求，只由 Normalize 补默认时长与纯音乐标记。
func TestStableAudioSFXRequest(t *testing.T) {
	d := schema.DefaultDraft()
	d.Kind, d.ModelID, d.Text = "sfx", "stable-audio-3-small-sfx-q8", " footsteps on gravel "
	d.Normalize()
	p, err := BuildRequest(d, "", "")
	must(t, err)
	r := p["request"].(map[string]any)
	o := r["options"].(map[string]any)
	if r["text"] != "footsteps on gravel" || o["duration_sec"] != float64(5) || o["route"] != nil || r["language"] != nil {
		t.Fatal(r)
	}
	d.ModelOptions["stable_audio"]["duration_seconds"] = float64(9)
	p, err = BuildRequest(d, "", "")
	must(t, err)
	if got := p["request"].(map[string]any)["options"].(map[string]any)["duration_sec"]; got != float64(9) {
		t.Fatal("显式时长不应被默认值覆盖", got)
	}

	// 旧音乐作品可以直接使用 SFX 模型，不因新增类型而被迁移或拒绝。
	legacy := schema.DefaultDraft()
	legacy.Kind, legacy.ModelID, legacy.Text = "music", "stable-audio-3-small-sfx-q8", "thunder"
	legacy.Normalize()
	if legacy.Kind != "music" || legacy.Instrumental || legacy.ModelOptions != nil {
		t.Fatalf("旧音乐作品不应按 sfx 补齐：%+v", legacy)
	}
	p, err = BuildRequest(legacy, "", "")
	must(t, err)
	if got := p["request"].(map[string]any)["options"].(map[string]any)["duration_sec"]; got != float64(30) {
		t.Fatal("旧音乐作品仍使用 Stable Audio 默认时长", got)
	}
}
