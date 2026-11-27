package vos

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/schema"
)

func TestNodeSnapshotLimitsStateToJobReferences(t *testing.T) {
	draft := schema.DefaultDraft()
	unrelated := schema.DefaultDraft()
	voice := schema.NewID()
	draft.VoiceID = &voice
	data, _ := json.Marshal(draft)
	original := schema.State{
		Drafts: []schema.Draft{unrelated, draft},
		Voices: []schema.Voice{{ID: voice, FileName: "needed.wav"}, {ID: schema.NewID(), FileName: "private.wav"}},
	}
	bundle := nodeSnapshot(Job{ID: schema.NewID(), Method: "generation.start", Data: data}, original)
	if len(bundle.State.Drafts) != 1 || bundle.State.Drafts[0].ID != draft.ID || len(bundle.State.Voices) != 1 || !nodeMedia(bundle.State)["voices/needed.wav"] {
		t.Fatal("job snapshot omitted input or copied an unrelated project")
	}
}

func TestWorkbenchNodeJobStagesInputAndPublishesOnlyMatchingReceipt(t *testing.T) {
	for _, mismatch := range []bool{false, true} {
		t.Run(map[bool]string{false: "matching-node", true: "wrong-node"}[mismatch], func(t *testing.T) {
			const node = "spark-selected"
			const executor = "speaker-executor"
			placement := NodeChoice{NodeID: node, DeploymentID: strings.Repeat("a", 32)}
			id := schema.NewID()
			s := testServer(t)
			gotUpload := false
			phase := "assigned"
			output := filepath.Join(t.TempDir(), "output.zip")
			pack := nodeBundle{ID: id, Method: "melody.plan", State: schema.State{Melody: &schema.MelodyResult{ID: schema.NewID()}}}
			if err := writeNodeBundle(output, pack, map[string]bool{}, nil); err != nil {
				t.Fatal(err)
			}
			contents, err := os.ReadFile(output)
			if err != nil {
				t.Fatal(err)
			}
			sum := sha256.Sum256(contents)
			data := hex.EncodeToString(sum[:])
			address := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				ok := func(result any) { jsonReply(w, map[string]any{"code": "OK", "data": result}) }
				switch r.URL.Path {
				case "/backend-deployments/" + placement.DeploymentID + "/models":
					ok(map[string]any{"items": []map[string]any{{"executor_id": executor, "node_id": node, "model_id": "audiocpp-yue2-3b-q4", "task_type": nodeTaskType}}})
				case "/tasks":
					var in map[string]any
					if err := json.NewDecoder(r.Body).Decode(&in); err != nil || r.Header.Get("Idempotency-Key") != id ||
						in["executor"].(map[string]any)["id"] != executor {
						t.Error("submission did not pin the approved executor")
					}
					ok(map[string]any{"task_id": "node-task"})
				case "/tasks/node-task":
					actual := node
					if mismatch && phase == "succeeded" {
						actual = "another-node"
					}
					ok(map[string]any{"status": phase, "attempt_id": "node-attempt", "node_id": actual, "executor_id": executor, "fence": 1,
						"result": map[string]any{"output": map[string]any{"file_id": "workbench.zip", "size_bytes": len(contents), "sha256": data}}})
				case "/backend-deployments/" + placement.DeploymentID + "/executions/node-attempt/inputs/reference":
					raw, _ := io.ReadAll(r.Body)
					gotUpload = r.Header.Get("X-Scheduler-Fence") == "1" && r.URL.Query().Get("offset") == "0" && len(raw) > 0
					ok(map[string]any{"received_bytes": len(raw)})
				case "/backend-deployments/" + placement.DeploymentID + "/executions/node-attempt/outputs/workbench.zip":
					if mismatch {
						t.Error("mismatched receipt attempted a result download")
					}
					ok(map[string]any{"offset": 0, "data_b64": base64.StdEncoding.EncodeToString(contents)})
				default:
					http.NotFound(w, r)
				}
			}))
			defer address.Close()
			j := &Jobs{Server: s, Config: SchedulerConfig{URL: address.URL, Token: strings.Repeat("s", 32), ExecutorToken: strings.Repeat("e", 32)}}
			if _, err = j.Enqueue("alice", id, "melody.plan", json.RawMessage(`{"modelId":"yue2-3b-q4"}`), &placement); err != nil {
				t.Fatal(err)
			}
			for _, state := range []string{"assigned", "assigned", "succeeded"} {
				phase = state
				job, err := j.read(id)
				if err != nil {
					t.Fatal(err)
				}
				if err = j.pollNode(context.Background(), job); err != nil {
					t.Fatal(err)
				}
			}
			if !gotUpload {
				t.Fatal("scheduler never received the job input")
			}
			job, err := j.read(id)
			if err != nil {
				t.Fatal(err)
			}
			if mismatch {
				if job.Status != "failed" || job.ActualNode != "" {
					t.Fatalf("mismatched receipt published: %+v", job)
				}
			} else {
				w, err := s.user("alice")
				if err != nil {
					t.Fatal(err)
				}
				state := j.VisibleState("alice", w.Store.Read())
				if job.Status != "succeeded" || job.ActualNode != node || state.Melody == nil || state.Activity == nil || state.Activity.ActualNode != node {
					t.Fatalf("result or verified execution metadata missing: %+v", job)
				}
			}
		})
	}
}
