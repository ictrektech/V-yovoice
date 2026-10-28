package vos

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"slices"
	"strings"
	"yovoice/internal/catalog"
	"yovoice/internal/msg"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

type alignmentInput struct {
	ID      string                `json:"id"`
	Lines   []workbench.LyricLine `json:"lines"`
	ModelID string                `json:"modelId"`
}

type lyricTiming struct {
	ID    string             `json:"id"`
	Words []schema.LyricWord `json:"words,omitempty"`
	Times []float64          `json:"times,omitempty"`
}

func timingOf(state schema.State, id string) *lyricTiming {
	for _, g := range state.History {
		if g.ID == id {
			return &lyricTiming{ID: id, Words: slices.Clone(g.LyricWords), Times: slices.Clone(g.LyricTimes)}
		}
	}
	return nil
}

// 对齐只允许引用当前用户已获确认的版本，模型选择也由服务端核验。
func (j *Jobs) alignmentSnapshot(user string, w *workbench.Workbench, data json.RawMessage) (json.RawMessage, error) {
	var input alignmentInput
	if err := json.Unmarshal(data, &input); err != nil {
		return nil, err
	}
	state := j.VisibleState(user, w.Store.Read())
	i := slices.IndexFunc(state.History, func(g schema.Generation) bool { return g.ID == input.ID })
	if i < 0 {
		return nil, msg.Err(msg.ErrAudioMissing, nil)
	}
	var err error
	if input.Lines, err = workbench.LyricAlignmentLines(state.History[i], input.Lines); err != nil {
		return nil, err
	}
	available := false
	for _, installed := range state.Models {
		model, err := catalog.Lookup(installed.ID)
		if err != nil || model.Family != "lyric_align" {
			continue
		}
		available = true
		if j.config().Models[model.ID] == "" {
			continue
		}
		input.ModelID = model.ID
		return json.Marshal(input)
	}
	if available {
		return nil, fmt.Errorf("model budget not approved")
	}
	return nil, msg.Err(msg.ErrAlignModelRequired, nil)
}

// 对齐会改写已有历史的元数据，音频文件名不变；文件过滤之外还要恢复未确认的时间戳。
// 调用方持有 j.mu，避免与执行日志更新交错；下一次执行也从这个可见版本取得旧时间戳。
func (j *Jobs) visibleLyrics(user string, state schema.State) schema.State {
	paths, _ := filepath.Glob(filepath.Join(j.Server.Root, "jobs", "*.json"))
	latest := map[string]Job{}
	for _, path := range paths {
		job, err := j.read(strings.TrimSuffix(filepath.Base(path), ".json"))
		if err != nil || job.User != user || job.BeforeLyrics == nil {
			continue
		}
		previous, found := latest[job.BeforeLyrics.ID]
		if !found || job.Created.After(previous.Created) {
			latest[job.BeforeLyrics.ID] = job
		}
	}
	for _, job := range latest {
		if job.Status == "succeeded" {
			continue
		}
		for i, g := range state.History {
			if g.ID != job.BeforeLyrics.ID {
				continue
			}
			output := job.OutputLyrics
			active := job.Attempt != "" && !job.Stopped
			if active || output != nil && slices.Equal(g.LyricWords, output.Words) && slices.Equal(g.LyricTimes, output.Times) {
				state.History[i].LyricWords = slices.Clone(job.BeforeLyrics.Words)
				state.History[i].LyricTimes = slices.Clone(job.BeforeLyrics.Times)
			}
		}
	}
	return state
}

// 同一版本的上一次对齐确认终态后才能重试，避免两个结果交错覆盖旧时间戳；调用方持有 j.mu。
func (j *Jobs) pendingAlignment(user, id string) (bool, error) {
	paths, err := filepath.Glob(filepath.Join(j.Server.Root, "jobs", "*.json"))
	if err != nil {
		return false, err
	}
	for _, path := range paths {
		job, err := j.read(strings.TrimSuffix(filepath.Base(path), ".json"))
		if err != nil {
			return false, err
		}
		if job.User != user || job.Method != "generation.alignLyrics" {
			continue
		}
		if (job.Status == "succeeded" || job.Status == "failed" || job.Status == "cancelled") && job.Stopped {
			continue
		}
		var input alignmentInput
		if err := json.Unmarshal(job.Data, &input); err != nil {
			return false, err
		}
		if input.ID == id {
			return true, nil
		}
	}
	return false, nil
}
