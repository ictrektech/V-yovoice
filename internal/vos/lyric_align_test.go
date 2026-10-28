package vos

import (
	"encoding/json"
	"slices"
	"strings"
	"testing"
	"time"
	"yovoice/internal/schema"
)

func TestAlignmentTimestampsWaitForSchedulerConfirmation(t *testing.T) {
	j, job := jobFixture(t)
	job.Method = "generation.alignLyrics"
	job.BeforeFiles = []string{"existing.wav"}
	job.BeforeLyrics = &lyricTiming{ID: "generation", Times: []float64{0.5}}
	job.OutputLyrics = &lyricTiming{ID: "generation", Words: []schema.LyricWord{{Word: "歌", Start: 1, End: 2}}}
	state := func() schema.State {
		return schema.State{History: []schema.Generation{{ID: "generation", FileName: "existing.wav", LyricWords: slices.Clone(job.OutputLyrics.Words)}}}
	}
	for _, status := range []string{"running", "failed", "cancelled", "succeeded"} {
		job.Status, job.Stopped = status, status != "running"
		if err := atomicJSON(j.path(job.ID), job); err != nil {
			t.Fatal(err)
		}
		visible := j.VisibleState("alice", state()).History[0]
		if (len(visible.LyricWords) > 0) != (status == "succeeded") {
			t.Fatal("对齐结果提前可见", status)
		}
		if status != "succeeded" && !slices.Equal(visible.LyricTimes, job.BeforeLyrics.Times) {
			t.Fatal("旧校准时间丢失")
		}
		if len(j.VisibleState("bob", state()).History[0].LyricWords) != 1 {
			t.Fatal("改变了其他用户的数据")
		}
	}
	job.Status, job.Stopped, job.OutputLyrics = "running", false, nil
	if err := atomicJSON(j.path(job.ID), job); err != nil {
		t.Fatal(err)
	}
	running := schema.State{History: []schema.Generation{{ID: "generation", FileName: "existing.wav", LyricWords: []schema.LyricWord{{Word: "歌", Start: 1, End: 2}}}}}
	if len(j.VisibleState("alice", running).History[0].LyricWords) != 0 {
		t.Fatal("执行日志写入前结果泄露")
	}
}

func TestFailedAlignmentDoesNotHideLaterManualEdits(t *testing.T) {
	j, job := jobFixture(t)
	job.Status, job.Stopped = "failed", true
	job.BeforeLyrics = &lyricTiming{ID: "generation", Times: []float64{0.5}}
	job.OutputLyrics = &lyricTiming{ID: "generation", Words: []schema.LyricWord{{Word: "歌", Start: 1, End: 2}}}
	if err := atomicJSON(j.path(job.ID), job); err != nil {
		t.Fatal(err)
	}
	manual := []schema.LyricWord{{Word: "歌", Start: 2, End: 3}}
	state := schema.State{History: []schema.Generation{{ID: "generation", FileName: "existing.wav", LyricWords: manual}}}
	if !slices.Equal(j.VisibleState("alice", state).History[0].LyricWords, manual) {
		t.Fatal("失败任务覆盖了之后的手动编辑")
	}
}

func TestAlignmentSnapshotChecksOwnerAndApprovedModel(t *testing.T) {
	j, job := jobFixture(t)
	job.Status, job.Stopped = "succeeded", true
	if err := atomicJSON(j.path(job.ID), job); err != nil {
		t.Fatal(err)
	}
	w, err := j.Server.user("alice")
	if err != nil {
		t.Fatal(err)
	}
	d := schema.DefaultDraft()
	d.Kind, d.Lyrics = "music", "你好"
	id := schema.NewID()
	if err = w.Store.Update(func(s *schema.State) {
		s.History = []schema.Generation{{ID: id, Duration: 4, Settings: d}}
		s.Models = []schema.InstalledModel{{ID: "lyric-align-q8"}}
	}, false); err != nil {
		t.Fatal(err)
	}
	j.Config.Models = map[string]string{"lyric-align-q8": "executor"}
	data := json.RawMessage(`{"id":"` + id + `","modelId":"client-budget"}`)
	snapshot, err := j.alignmentSnapshot("alice", w, data)
	if err != nil || !strings.Contains(string(snapshot), `"modelId":"lyric-align-q8"`) {
		t.Fatal("未固定批准模型", string(snapshot), err)
	}
	foreign, err := j.Server.user("bob")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := j.alignmentSnapshot("bob", foreign, data); err == nil {
		t.Fatal("允许对齐其他用户的版本")
	}
	j.Config.Models = nil
	if _, err := j.alignmentSnapshot("alice", w, data); err == nil {
		t.Fatal("未审批模型仍可排队")
	}
}

// 同样的音频重试往往得到相同时间戳，旧失败任务不能遮住新任务已经确认的结果。
func TestConfirmedAlignmentRetryPublishesIdenticalTimestamps(t *testing.T) {
	j, failed := jobFixture(t)
	failed.Status, failed.Stopped = "failed", true
	failed.BeforeLyrics = &lyricTiming{ID: "generation", Times: []float64{0.5}}
	failed.OutputLyrics = &lyricTiming{ID: "generation", Words: []schema.LyricWord{{Word: "歌", Start: 1, End: 2}}}
	retry := failed
	retry.ID, retry.Created, retry.Status = schema.NewID(), failed.Created.Add(time.Second), "succeeded"
	for _, job := range []Job{failed, retry} {
		if err := atomicJSON(j.path(job.ID), job); err != nil {
			t.Fatal(err)
		}
	}
	state := schema.State{History: []schema.Generation{{ID: "generation", FileName: "existing.wav", LyricWords: failed.OutputLyrics.Words}}}
	if !slices.Equal(j.VisibleState("alice", state).History[0].LyricWords, retry.OutputLyrics.Words) {
		t.Fatal("旧失败任务遮住了已确认重试结果")
	}
}

func TestAlignmentQueueWaitsForPreviousAttemptToStop(t *testing.T) {
	j, fixture := jobFixture(t)
	fixture.Status, fixture.Stopped = "succeeded", true
	if err := atomicJSON(j.path(fixture.ID), fixture); err != nil {
		t.Fatal(err)
	}
	j.Config.Models = map[string]string{"lyric-align-q8": "executor"}
	data := json.RawMessage(`{"id":"generation","modelId":"lyric-align-q8"}`)
	first, err := j.Enqueue("alice", schema.NewID(), "generation.alignLyrics", data)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := j.Enqueue("alice", schema.NewID(), "generation.alignLyrics", data); err == nil {
		t.Fatal("允许同时对齐同一版本")
	}
	old, err := j.read(first)
	if err != nil {
		t.Fatal(err)
	}
	old.Status, old.Stopped = "cancelled", false
	if err := atomicJSON(j.path(first), old); err != nil {
		t.Fatal(err)
	}
	if _, err := j.Enqueue("alice", schema.NewID(), "generation.alignLyrics", data); err == nil {
		t.Fatal("旧执行尚未停止就允许重试")
	}
	old.Stopped = true
	if err := atomicJSON(j.path(first), old); err != nil {
		t.Fatal(err)
	}
	if _, err := j.Enqueue("alice", schema.NewID(), "generation.alignLyrics", data); err != nil {
		t.Fatal(err)
	}
}
