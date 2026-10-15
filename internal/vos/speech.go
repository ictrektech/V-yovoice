package vos

import (
	"bytes"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"yovoice/internal/catalog"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

type speechInput struct {
	Model            string   `json:"model"`
	Text             string   `json:"text"`
	Voice            string   `json:"voice"`
	Language         string   `json:"language"`
	Speed            float64  `json:"speed"`
	ReferenceAudio   string   `json:"reference_audio"`
	ReferenceText    string   `json:"reference_text"`
	VoiceDescription string   `json:"voice_description"`
	EmotionText      string   `json:"emotion_text"`
	EmotionStrength  *float64 `json:"emotion_strength"`
}

// speech 只接受同容器推理入口调用；Scheduler 准入由 Python 兼容层统一处理。
func (s *Server) speech(out http.ResponseWriter, r *http.Request) {
	secret := os.Getenv("VVOICE_STUDIO_INTERNAL_TOKEN")
	if len(secret) < 32 || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+secret)) != 1 {
		http.Error(out, "Unauthorized", 401)
		return
	}
	if r.Method != "POST" {
		http.Error(out, "Method not allowed", 405)
		return
	}
	var input speechInput
	if err := json.NewDecoder(http.MaxBytesReader(out, r.Body, 32<<20)).Decode(&input); err != nil {
		http.Error(out, "Invalid speech request", 422)
		return
	}
	body, err := s.synthesize(r, input)
	if err != nil {
		http.Error(out, "Voice generation failed; check model readiness and reference audio", 422)
		return
	}
	out.Header().Set("Content-Type", "audio/wav")
	_, _ = out.Write(body)
}

func (s *Server) synthesize(r *http.Request, input speechInput) ([]byte, error) {
	base := filepath.Join(s.Root, "api")
	if err := os.MkdirAll(base, 0700); err != nil {
		return nil, err
	}
	root, err := os.MkdirTemp(base, "speech-")
	if err != nil {
		return nil, err
	}
	// 只清理本次创建的临时目录；不触碰任何用户项目或共享权重。
	defer os.RemoveAll(root)
	w, err := workbench.New(root)
	if err != nil {
		return nil, err
	}
	defer w.Close()
	if err = w.UseBundled(s.Runtime); err != nil {
		return nil, err
	}
	if err = w.SyncSharedModels(); err != nil {
		return nil, err
	}
	d := schema.DefaultDraft()
	d.ModelID = input.Model
	d.Text = input.Text
	d.Title = "API speech"
	d.Mode = "speaker"
	d.EmotionText = ""
	d.SynthesisLanguage = input.Language
	d.ReferenceText = input.ReferenceText
	d.VoiceDescription = input.VoiceDescription
	m, err := catalog.Lookup(input.Model)
	if err != nil {
		return nil, err
	}
	if m.Family == "index_tts2" && input.Language != "" && input.Language != "auto" {
		d.Language = input.Language
	}
	if input.VoiceDescription != "" && (m.Family == "index_tts2" || m.Family == "kokoro_tts" || (m.Family == "qwen3_tts" && m.Variant == "base")) {
		return nil, fmt.Errorf("voice design unsupported by selected model")
	}
	if input.ReferenceAudio != "" && (m.Family == "kokoro_tts" || (m.Family == "qwen3_tts" && m.Variant != "base")) {
		return nil, fmt.Errorf("voice cloning unsupported by selected model")
	}
	if input.EmotionText != "" {
		if m.Family != "index_tts2" {
			return nil, fmt.Errorf("emotion control unsupported")
		}
		d.Mode, d.EmotionText = "text", input.EmotionText
	}
	if input.EmotionStrength != nil {
		d.EmotionStrength = *input.EmotionStrength
	}
	// 设计与克隆映射到各模型原生模式；绝不把参考音频路径暴露给外部调用方。
	d.VoiceMode, d.VoxMode = "design", "design"
	if m.Family == "omnivoice" {
		d.OmniSpeed = input.Speed
	}
	if input.Speed != 0 {
		d.Speed = input.Speed
	}
	if input.Voice != "" && input.Voice != "default" {
		d.Speaker = input.Voice
	}
	if m.Family == "kokoro_tts" {
		d.SynthesisLanguage = kokoroSpeechLanguage(d.KokoroSpeaker(m), input.Language)
	}
	if input.ReferenceAudio != "" {
		audio, decodeErr := base64.StdEncoding.DecodeString(input.ReferenceAudio)
		if decodeErr != nil {
			return nil, decodeErr
		}
		voice, importErr := w.ImportVoiceFrom(r.Context(), bytes.NewReader(audio), "API reference")
		if importErr != nil {
			return nil, importErr
		}
		d.VoiceID = &voice.ID
		d.VoiceMode = "clone"
		d.VoxMode = "clone"
	}
	g, err := w.Synthesize(r.Context(), d)
	if err != nil {
		return nil, err
	}
	path, err := w.MediaFile("outputs", g.ID)
	if err != nil {
		return nil, err
	}
	info, err := os.Stat(path)
	if err != nil || info.Size() > 256<<20 {
		return nil, fmt.Errorf("audio output unavailable")
	}
	// 函数返回前 defer Close 已经等待并停止引擎，再由 HTTP 层发送完整终态响应。
	return os.ReadFile(path)
}

// 公共 API 可使用 en/fr/pt；具体口音仍由实际音色决定，不接受冲突的地区码。
func kokoroSpeechLanguage(voice, language string) string {
	exact := schema.KokoroLanguage(voice)
	if language != "" && language == strings.SplitN(exact, "-", 2)[0] {
		return exact
	}
	return language
}
