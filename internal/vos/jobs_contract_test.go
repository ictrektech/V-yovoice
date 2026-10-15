package vos

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
	"yovoice/internal/schema"
)

// 仅验证既有回调协议，不启动原生引擎、不占用真实计算许可。
func jobFixture(t *testing.T) (*Jobs, Job) {
	t.Helper()
	s := testServer(t)
	j := &Jobs{Server: s, Config: SchedulerConfig{URL: "http://scheduler.invalid", Token: strings.Repeat("s", 32), ExecutorToken: strings.Repeat("e", 32)}}
	job := Job{ID: schema.NewID(), User: "alice", TaskID: "scheduler-task", Status: "running", Attempt: "attempt-one", Fence: 7, Created: time.Now(), Stopped: false}
	if err := atomicJSON(j.path(job.ID), job); err != nil {
		t.Fatal(err)
	}
	return j, job
}

func callback(j *Jobs, job Job, attempt, action, token string, fence uint64) *httptest.ResponseRecorder {
	body, _ := json.Marshal(map[string]any{"task_id": job.TaskID, "fence": fence, "lease_seconds": 10, "parameters": map[string]string{"job_id": job.ID}})
	r := httptest.NewRequest("POST", "/scheduler/executions/"+attempt+"/"+action, strings.NewReader(string(body)))
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	j.ServeHTTP(w, r)
	return w
}

func TestCallbackRejectsWrongCredentialAndStaleAttempt(t *testing.T) {
	j, job := jobFixture(t)
	if r := callback(j, job, job.Attempt, "inspect", "wrong", job.Fence); r.Code != 401 {
		t.Fatalf("wrong credential status %d", r.Code)
	}
	for _, attempt := range []struct {
		id    string
		fence uint64
	}{{"older-attempt", job.Fence}, {job.Attempt, job.Fence - 1}} {
		if r := callback(j, job, attempt.id, "cancel", j.Config.ExecutorToken, attempt.fence); r.Code != 409 {
			t.Fatalf("stale callback status %d", r.Code)
		}
	}
	stored, err := j.read(job.ID)
	if err != nil || stored.Cancel || stored.Stopped {
		t.Fatal("rejected callback changed the journal")
	}
}

func TestRestartedAttemptRemainsUnknownUntilStopIsProven(t *testing.T) {
	j, job := jobFixture(t)
	for _, action := range []string{"inspect", "cancel"} {
		r := callback(j, job, job.Attempt, action, j.Config.ExecutorToken, job.Fence)
		var result struct {
			Status  string `json:"status"`
			Stopped bool   `json:"stopped"`
		}
		if r.Code != 200 || json.Unmarshal(r.Body.Bytes(), &result) != nil || result.Status != "unknown" || result.Stopped {
			t.Fatalf("%s fabricated stop: %d %s", action, r.Code, r.Body.String())
		}
	}
	stored, err := j.read(job.ID)
	if err != nil || !stored.Cancel || stored.Stopped {
		t.Fatal("cancel lost uncertainty after restart")
	}
}

func TestCancelledQueuedJobNeverStartsNativeWork(t *testing.T) {
	j, job := jobFixture(t)
	job.Attempt, job.Fence, job.Status, job.Cancel, job.Stopped = "", 0, "queued", true, true
	if err := atomicJSON(j.path(job.ID), job); err != nil {
		t.Fatal(err)
	}
	r := callback(j, job, "new-attempt", "start", j.Config.ExecutorToken, 1)
	var result struct {
		Status  string `json:"status"`
		Stopped bool   `json:"stopped"`
	}
	if r.Code != 200 || json.Unmarshal(r.Body.Bytes(), &result) != nil || result.Status != "cancelled" || !result.Stopped {
		t.Fatalf("early cancellation: %d %s", r.Code, r.Body.String())
	}
	if j.executing != "" || len(j.active) != 0 || len(j.Server.users) != 0 {
		t.Fatal("cancelled queued job opened a native workbench")
	}
}

func TestResultsStayPrivateUntilSchedulerConfirmsSuccess(t *testing.T) {
	j, job := jobFixture(t)
	job.ExecutionStatus, job.Stopped = "succeeded", true
	job.BeforeFiles, job.OutputFiles = []string{"existing.wav"}, []string{"new.wav"}
	state := func() schema.State {
		return schema.State{History: []schema.Generation{{ID: "existing", FileName: "existing.wav"}, {ID: "new", FileName: "new.wav"}}}
	}
	for _, status := range []string{"running", "failed", "cancelled", "succeeded"} {
		job.Status = status
		if err := atomicJSON(j.path(job.ID), job); err != nil {
			t.Fatal(err)
		}
		visible := j.VisibleState("alice", state())
		allowed := status == "succeeded"
		if j.OutputAllowed("alice", "new.wav", state()) != allowed || (len(visible.History) == 2) != allowed {
			t.Fatalf("result exposed before confirmed success: %s", status)
		}
		if !j.OutputAllowed("alice", "existing.wav", state()) || len(j.VisibleState("bob", state()).History) != 2 {
			t.Fatal("unrelated output or another user was affected")
		}
	}
}

func TestCancelOnlyMarksCurrentUsersNonterminalJobs(t *testing.T) {
	j, job := jobFixture(t)
	foreign, finished := job, job
	foreign.ID, foreign.User = schema.NewID(), "bob"
	finished.ID, finished.Status = schema.NewID(), "succeeded"
	for _, row := range []Job{foreign, finished} {
		if err := atomicJSON(j.path(row.ID), row); err != nil {
			t.Fatal(err)
		}
	}
	if err := j.Cancel("alice"); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{job.ID, foreign.ID, finished.ID} {
		stored, err := j.read(id)
		if err != nil || stored.Cancel != (id == job.ID) {
			t.Fatal("cancellation crossed user or terminal-state boundaries")
		}
	}
}
