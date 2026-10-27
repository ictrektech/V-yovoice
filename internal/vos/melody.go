package vos

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"slices"
	"yovoice/internal/catalog"
	"yovoice/internal/msg"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

// 音乐任务的辅助模型由服务端从当前用户可用的共享目录选择，不能信任浏览器自报的预算模型。
func musicSnapshot(w *workbench.Workbench, method string, data json.RawMessage, approved map[string]string) (json.RawMessage, error) {
	if method == "melody.plan" {
		d := schema.DefaultDraft()
		if err := json.Unmarshal(data, &d); err != nil {
			return nil, err
		}
		d.Abc = ""
		if err := schema.Validate(d); err != nil {
			return nil, err
		}
		model, err := catalog.Lookup(d.ModelID)
		if err != nil || model.Family != "yue2" {
			return nil, msg.Err(msg.ErrModelUnsupported, nil)
		}
		return json.Marshal(d)
	}
	var input struct {
		ProjectID string `json:"projectId,omitempty"`
		Base64    string `json:"base64,omitempty"`
		Abc       string `json:"abc,omitempty"`
		ModelID   string `json:"modelId"`
	}
	if err := json.Unmarshal(data, &input); err != nil {
		return nil, err
	}
	family := "soundfont"
	state := w.Store.Read()
	if method == "melody.cover" {
		family = "sheetsage2"
		if !schema.ValidID(input.ProjectID) || !slices.ContainsFunc(state.Drafts, func(d schema.Draft) bool { return d.ID == input.ProjectID }) {
			return nil, msg.Err(msg.ErrDraftIDInvalid, nil)
		}
		if len(input.Base64) == 0 || len(input.Base64) > base64.StdEncoding.EncodedLen(20<<20) {
			return nil, msg.Err(msg.ErrRequestInvalid, nil)
		}
		if decoded, err := base64.StdEncoding.DecodeString(input.Base64); err != nil || len(decoded) > 20<<20 {
			return nil, msg.Err(msg.ErrRequestInvalid, nil)
		}
		input.Abc = ""
	} else {
		if result := workbench.InspectMelody(input.Abc); result.Issue != nil {
			return nil, msg.Err(msg.ErrMelodyInvalid, nil)
		}
		input.ProjectID, input.Base64 = "", ""
	}
	available := false
	for _, installed := range state.Models {
		model, err := catalog.Lookup(installed.ID)
		if err == nil && model.Family == family {
			available = true
			if approved[model.ID] == "" {
				continue
			}
			input.ModelID = model.ID
			return json.Marshal(input)
		}
	}
	if available {
		return nil, fmt.Errorf("model budget not approved")
	}
	code := msg.ErrMelodySoundFontRequired
	if family == "sheetsage2" {
		code = msg.ErrCoverModelRequired
	}
	return nil, msg.Err(code, nil)
}

func runMusicSnapshot(ctx context.Context, w *workbench.Workbench, job Job) error {
	if job.Method == "melody.plan" {
		var d schema.Draft
		if err := json.Unmarshal(job.Data, &d); err != nil {
			return err
		}
		return w.PlanMelodySnapshot(d)
	}
	var input struct {
		ProjectID, Base64, Abc, ModelID string
	}
	if err := json.Unmarshal(job.Data, &input); err != nil {
		return err
	}
	if job.Method == "melody.cover" {
		b, err := base64.StdEncoding.DecodeString(input.Base64)
		if err != nil {
			return err
		}
		return w.CoverMelodySnapshot(input.ProjectID, input.ModelID, bytes.NewReader(b))
	}
	file, err := w.ListenMelodySnapshot(ctx, input.Abc, input.ModelID)
	if err != nil {
		return err
	}
	// 复用已有的暂存音频登记，下载与状态可见性仍由调度确认控制。
	return w.Store.Update(func(state *schema.State) {
		state.Previews = append(state.Previews, schema.CharacterPreview{ID: job.ID, FileName: file})
	}, false)
}

// musicResult 只返回当前用户已由调度器确认成功的试听产物。
func (j *Jobs) musicResult(user, id string) (any, error) {
	j.mu.Lock()
	defer j.mu.Unlock()
	job, err := j.read(id)
	if err != nil || job.User != user || job.Method != "melody.listen" {
		return nil, msg.Err(msg.ErrRequestInvalid, nil)
	}
	if job.Status == "failed" || job.Status == "cancelled" {
		return nil, fmt.Errorf("melody preview %s", job.Status)
	}
	if job.Status != "succeeded" || len(job.OutputFiles) != 1 {
		return nil, nil
	}
	return map[string]string{"fileName": job.OutputFiles[0]}, nil
}
