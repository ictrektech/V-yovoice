package vos

import (
	"encoding/json"
	"strings"
	"testing"
	"yovoice/internal/schema"
)

func TestMusicSnapshotFixesAuxiliaryModelAndRejectsForeignProject(t *testing.T) {
	j, _ := jobFixture(t)
	w, err := j.Server.user("alice")
	if err != nil {
		t.Fatal(err)
	}
	d := schema.DefaultDraft()
	if err = w.Store.Update(func(s *schema.State) {
		s.Drafts = []schema.Draft{d}
		s.Models = []schema.InstalledModel{{ID: "sheetsage2-orig"}, {ID: "generaluser-gs-sf2"}}
	}, false); err != nil {
		t.Fatal(err)
	}
	snapshot, err := musicSnapshot(w, "melody.cover", json.RawMessage(`{"projectId":"`+d.ID+`","base64":"YXVkaW8=","modelId":"unapproved-client-model"}`), map[string]string{"sheetsage2-orig": "executor"})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(snapshot), `"modelId":"sheetsage2-orig"`) || strings.Contains(string(snapshot), "unapproved-client-model") {
		t.Fatal("预算模型由浏览器控制", string(snapshot))
	}
	if _, err = musicSnapshot(w, "melody.cover", json.RawMessage(`{"projectId":"`+schema.NewID()+`","base64":"YXVkaW8="}`), map[string]string{"sheetsage2-orig": "executor"}); err == nil {
		t.Fatal("允许为其他用户的作品排队")
	}
	j.Config.Models = map[string]string{"unapproved-client-model": "executor"}
	if _, err = j.Enqueue("alice", schema.NewID(), "melody.cover", snapshot); err == nil {
		t.Fatal("允许未获批准的扒谱模型排队")
	}
}

func TestMelodyTextStaysPrivateUntilSchedulerConfirms(t *testing.T) {
	for _, method := range []string{"melody.plan", "melody.cover", "generation.start"} {
		t.Run(method, func(t *testing.T) {
			j, job := jobFixture(t)
			job.Method, job.BeforeMelodyID, job.OutputMelodyID = method, "before", "new"
			state := schema.State{Melody: &schema.MelodyResult{ID: "new", Abc: "private score"}}
			for _, status := range []string{"running", "failed", "cancelled", "succeeded"} {
				job.Status, job.Stopped = status, status != "running"
				if err := atomicJSON(j.path(job.ID), job); err != nil {
					t.Fatal(err)
				}
				if (j.VisibleState("alice", state).Melody != nil) != (status == "succeeded") {
					t.Fatal("谱面在调度确认前泄露", status)
				}
				if j.VisibleState("bob", state).Melody == nil {
					t.Fatal("影响了其他用户的谱面")
				}
			}
			// 执行中的新谱面还没写回任务日志，也不能提前可见。
			job.Status, job.Stopped, job.OutputMelodyID = "running", false, ""
			if err := atomicJSON(j.path(job.ID), job); err != nil {
				t.Fatal(err)
			}
			if j.VisibleState("alice", state).Melody != nil {
				t.Fatal("执行中的谱面提前可见")
			}
		})
	}
}

func TestMelodyPreviewRequiresOwnerAndConfirmedSuccess(t *testing.T) {
	j, job := jobFixture(t)
	job.Method, job.OutputFiles, job.Stopped = "melody.listen", []string{"preview.wav"}, true
	for _, status := range []string{"running", "failed", "cancelled", "succeeded"} {
		job.Status = status
		if err := atomicJSON(j.path(job.ID), job); err != nil {
			t.Fatal(err)
		}
		if result, _ := j.musicResult("alice", job.ID); (result != nil) != (status == "succeeded") {
			t.Fatal("试听未经确认便可访问", status)
		}
		if _, err := j.musicResult("bob", job.ID); err == nil {
			t.Fatal("允许跨用户读取试听结果")
		}
	}
}

// 多个音色库同时安装时，不能因为目录中第一个没有审批就忽略后面的已批准模型。
func TestMelodyPreviewSelectsAnApprovedInstalledSoundFont(t *testing.T) {
	j, _ := jobFixture(t)
	w, err := j.Server.user("alice")
	if err != nil {
		t.Fatal(err)
	}
	if err = w.Store.Update(func(s *schema.State) {
		s.Models = []schema.InstalledModel{{ID: "musescore-general-sf2"}, {ID: "generaluser-gs-sf2"}}
	}, false); err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(map[string]string{"modelId": "musescore-general-sf2", "abc": `X:1
T:
M:4/4
L:1/32
Q:1/4=90
V: Vocal clef=treble name="Vocal Melody" snm="Vocal"
V: Ins clef=treble name="Ins Melody" snm="Inst."
K:C
V: Vocal
C32|
V: Ins
z32|
`})
	snapshot, err := musicSnapshot(w, "melody.listen", data, map[string]string{"generaluser-gs-sf2": "executor"})
	if err != nil || !strings.Contains(string(snapshot), `"modelId":"generaluser-gs-sf2"`) {
		t.Fatal("未选择已批准的试听模型", string(snapshot), err)
	}
	if _, err := musicSnapshot(w, "melody.listen", data, nil); err == nil {
		t.Fatal("没有批准模型时允许试听")
	}
}
