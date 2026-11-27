package vos

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
)

const nodeChunk = 1 << 20
const nodeTaskType = "voice.workbench"

var schedulerID = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$`)
var nodeDeploymentID = regexp.MustCompile(`^[a-f0-9]{32}$`)
var nodeDigest = regexp.MustCompile(`^[a-f0-9]{64}$`)

type NodeChoice struct {
	NodeID       string `json:"node_id"`
	DeploymentID string `json:"deployment_id"`
}
type nodeDispatch struct {
	NodeChoice
	Models          []string `json:"models"`
	Size            int64    `json:"size"`
	SHA256          string   `json:"sha256"`
	Received        int64    `json:"received"`
	UploadedAttempt string   `json:"uploaded_attempt,omitempty"`
}

func (j *Jobs) nodeWorkDir(id string) string {
	return filepath.Join(j.Server.Root, "node-jobs", id)
}

func (j *Jobs) selectNode(ctx context.Context, choice NodeChoice, models map[string]bool) (*nodeDispatch, string, error) {
	if len(models) == 0 || len(models) > 16 {
		return nil, "", fmt.Errorf("invalid workbench execution node")
	}
	onNode, err := j.nodeApprovedModels(ctx, choice)
	if err != nil {
		return nil, "", err
	}
	ids := make([]string, 0, len(models))
	for key := range models {
		ids = append(ids, "audiocpp-"+key)
	}
	slices.Sort(ids)
	executor := ""
	for _, model := range ids {
		matched := onNode[strings.TrimPrefix(model, "audiocpp-")]
		if !schedulerID.MatchString(matched) {
			return nil, "", fmt.Errorf("model %s is unavailable on the selected node", model)
		}
		if executor == "" {
			executor = matched
		}
	}
	return &nodeDispatch{NodeChoice: choice, Models: ids}, executor, nil
}

func (j *Jobs) nodeApprovedModels(ctx context.Context, choice NodeChoice) (map[string]string, error) {
	if !nodeDeploymentID.MatchString(choice.DeploymentID) || !schedulerID.MatchString(choice.NodeID) {
		return nil, fmt.Errorf("invalid workbench execution node")
	}
	result, err := j.controller(ctx, "GET", "/backend-deployments/"+choice.DeploymentID+"/models", nil, "")
	if err != nil {
		return nil, err
	}
	rows, _ := result["items"].([]any)
	models := map[string]string{}
	for _, item := range rows {
		row, _ := item.(map[string]any)
		key, _ := row["model_id"].(string)
		executor, _ := row["executor_id"].(string)
		if row["node_id"] == choice.NodeID && row["task_type"] == nodeTaskType && strings.HasPrefix(key, "audiocpp-") && schedulerID.MatchString(executor) {
			models[strings.TrimPrefix(key, "audiocpp-")] = executor
		}
	}
	return models, nil
}

func nodeFileReceipt(path string) (int64, string, error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, "", err
	}
	defer f.Close()
	hash := sha256.New()
	size, err := io.Copy(hash, io.LimitReader(f, nodeBundleLimit+1))
	if err == nil && (size <= 0 || size > nodeBundleLimit) {
		err = fmt.Errorf("invalid workbench bundle size")
	}
	return size, hex.EncodeToString(hash.Sum(nil)), err
}

func (j *Jobs) nodeChunk(ctx context.Context, method, path string, offset, fence int64, input []byte) (map[string]any, error) {
	config := j.config()
	if config.URL == "" || len(config.Token) < 32 {
		return nil, fmt.Errorf("V-Scheduler configuration required")
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(config.URL, "/")+path+"?offset="+strconv.FormatInt(offset, 10), bytes.NewReader(input))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+config.Token)
	req.Header.Set("X-Scheduler-Fence", strconv.FormatInt(fence, 10))
	req.Header.Set("Content-Type", "application/octet-stream")
	response, err := (&http.Client{Timeout: 25 * time.Second}).Do(req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	var envelope struct {
		Code string
		Data map[string]any
	}
	err = json.NewDecoder(io.LimitReader(response.Body, 2*nodeChunk)).Decode(&envelope)
	if err != nil {
		return nil, err
	}
	if response.StatusCode != 200 || envelope.Code != "OK" {
		return nil, fmt.Errorf("node transfer: %s", envelope.Code)
	}
	return envelope.Data, nil
}

func (j *Jobs) changeNodeJob(id string, change func(*Job)) error {
	j.mu.Lock()
	defer j.mu.Unlock()
	current, err := j.read(id)
	if err != nil {
		return err
	}
	change(&current)
	return atomicJSON(j.path(id), current)
}

func (j *Jobs) scheduleNodePoll(ctx context.Context, job Job) {
	j.mu.Lock()
	if len(j.nodePolls) >= 4 || j.nodePolls[job.ID] {
		j.mu.Unlock()
		return
	}
	if j.nodePolls == nil {
		j.nodePolls = map[string]bool{}
	}
	j.nodePolls[job.ID] = true
	j.mu.Unlock()
	go func() {
		defer func() {
			j.mu.Lock()
			delete(j.nodePolls, job.ID)
			j.mu.Unlock()
		}()
		_ = j.pollNode(ctx, job)
	}()
}

func (j *Jobs) pollNode(ctx context.Context, job Job) error {
	target := job.Node
	if job.TaskID == "" {
		if job.Cancel {
			return j.changeNodeJob(job.ID, func(row *Job) { row.Status = "cancelled" })
		}
		submitted, err := j.controller(ctx, "POST", "/tasks", map[string]any{
			"protocol_version": 1, "app_task_id": job.ID,
			"executor":   map[string]string{"id": job.Executor, "task_type": nodeTaskType, "contract_version": "1"},
			"parameters": map[string]any{"size_bytes": target.Size, "sha256": target.SHA256, "models": target.Models},
		}, job.ID)
		if err != nil {
			return err
		}
		taskID, _ := submitted["task_id"].(string)
		if !schedulerID.MatchString(taskID) {
			return fmt.Errorf("invalid scheduler task ID")
		}
		return j.changeNodeJob(job.ID, func(row *Job) { row.TaskID = taskID })
	}
	route := "/tasks/" + job.TaskID
	if job.Cancel {
		_, _ = j.controller(ctx, "POST", route+"/cancel", map[string]any{}, "")
	}
	task, err := j.controller(ctx, "GET", route, nil, "")
	if err != nil {
		return err
	}
	status, _ := task["status"].(string)
	switch status {
	case "cancelled", "failed", "expired":
		if status == "expired" {
			status = "failed"
		}
		if job.Error != "" {
			return j.finishNodeJob(job, "failed", job.Error)
		}
		return j.finishNodeJob(job, status, "")
	case "assigned", "running", "succeeded":
		if task["node_id"] != target.NodeID || task["executor_id"] != job.Executor {
			const mismatch = "execution node or executor mismatch"
			if status == "succeeded" {
				return j.finishNodeJob(job, "failed", mismatch)
			}
			return j.changeNodeJob(job.ID, func(row *Job) { row.Cancel = true; row.Error = mismatch })
		}
	default:
		return nil
	}
	attempt, _ := task["attempt_id"].(string)
	fence, _ := task["fence"].(float64)
	if status == "succeeded" && !schedulerID.MatchString(attempt) {
		attempts, err := j.controller(ctx, "GET", route+"/attempts", nil, "")
		if err != nil {
			return err
		}
		rows, _ := attempts["items"].([]any)
		for _, raw := range rows {
			row, _ := raw.(map[string]any)
			if row["status"] == "succeeded" && row["node_id"] == target.NodeID && row["fence"] == fence {
				attempt, _ = row["attempt_id"].(string)
			}
		}
	}
	if !schedulerID.MatchString(attempt) || fence < 1 {
		return fmt.Errorf("invalid scheduler attempt")
	}
	channel := "/backend-deployments/" + target.DeploymentID + "/executions/" + attempt
	if status != "succeeded" {
		if job.Cancel {
			return nil
		}
		return j.uploadNodeInput(ctx, job, channel, attempt, int64(fence))
	}
	if job.Cancel {
		return j.finishNodeJob(job, "cancelled", "")
	}
	return j.receiveNodeResult(ctx, job, task, channel, int64(fence))
}

func (j *Jobs) uploadNodeInput(ctx context.Context, job Job, channel, attempt string, fence int64) error {
	target := job.Node
	offset := target.Received
	if target.UploadedAttempt != attempt {
		offset = 0
	}
	if offset == target.Size {
		return nil
	}
	file, err := os.Open(filepath.Join(j.nodeWorkDir(job.ID), "input.zip"))
	if err != nil {
		return err
	}
	defer file.Close()
	if _, err = file.Seek(offset, io.SeekStart); err != nil {
		return err
	}
	block := make([]byte, nodeChunk)
	for i := 0; i < 8 && offset < target.Size; i++ {
		n, err := io.ReadFull(file, block[:min(int64(len(block)), target.Size-offset)])
		if err != nil {
			return err
		}
		result, err := j.nodeChunk(ctx, "PUT", channel+"/inputs/reference", offset, fence, block[:n])
		if err != nil {
			return err
		}
		received, ok := result["received_bytes"].(float64)
		if !ok || int64(received) < offset+int64(n) || int64(received) > target.Size {
			return fmt.Errorf("invalid workbench upload receipt")
		}
		offset = int64(received)
		if err = j.changeNodeJob(job.ID, func(row *Job) { row.Node.Received = offset; row.Node.UploadedAttempt = attempt }); err != nil {
			return err
		}
		if _, err = file.Seek(offset, io.SeekStart); err != nil {
			return err
		}
	}
	return nil
}

func (j *Jobs) receiveNodeResult(ctx context.Context, job Job, task map[string]any, channel string, fence int64) error {
	result, _ := task["result"].(map[string]any)
	desc, _ := result["output"].(map[string]any)
	size, _ := desc["size_bytes"].(float64)
	digest, _ := desc["sha256"].(string)
	if desc["file_id"] != "workbench.zip" || size <= 0 || size > nodeBundleLimit || !nodeDigest.MatchString(digest) {
		return j.finishNodeJob(job, "failed", "invalid workbench output receipt")
	}
	dir := j.nodeWorkDir(job.ID)
	archive := filepath.Join(dir, "output.zip")
	if n, hash, _ := nodeFileReceipt(archive); n != int64(size) || hash != digest {
		err := withNodeFile(archive, func(out *os.File) error {
			hash := sha256.New()
			for offset := int64(0); offset < int64(size); {
				part, err := j.nodeChunk(ctx, "GET", channel+"/outputs/workbench.zip", offset, fence, nil)
				if err != nil {
					return err
				}
				encoded, _ := part["data_b64"].(string)
				data, err := base64.StdEncoding.Strict().DecodeString(encoded)
				if err != nil || part["offset"] != float64(offset) || int64(len(data)) != min(nodeChunk, int64(size)-offset) {
					return fmt.Errorf("invalid node result chunk")
				}
				if _, err = io.MultiWriter(out, hash).Write(data); err != nil {
					return err
				}
				offset += int64(len(data))
			}
			if hex.EncodeToString(hash.Sum(nil)) != digest {
				return fmt.Errorf("workbench result checksum mismatch")
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	staged := filepath.Join(dir, "result")
	output, files, err := unpackNodeBundle(archive, staged)
	if err != nil {
		return j.finishNodeJob(job, "failed", err.Error())
	}
	initial, err := readNodeMetadata(filepath.Join(dir, "input.zip"))
	if err != nil {
		return j.finishNodeJob(job, "failed", err.Error())
	}
	w, err := j.Server.user(job.User)
	if err != nil {
		return err
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	latest, err := j.read(job.ID)
	if err != nil {
		return err
	}
	if latest.Cancel {
		latest.Status = "cancelled"
	} else if err = applyNodeResult(w, job, initial, output, files, staged); err != nil {
		latest.Status = "failed"
		latest.Error = err.Error()
	} else {
		latest.Status = "succeeded"
		latest.ActualNode = job.Node.NodeID
		for name := range files {
			latest.OutputFiles = append(latest.OutputFiles, strings.TrimPrefix(name, "outputs/"))
		}
	}
	if err = atomicJSON(j.path(job.ID), latest); err != nil {
		return err
	}
	return os.RemoveAll(dir)
}

func (j *Jobs) finishNodeJob(job Job, status, reason string) error {
	if err := j.changeNodeJob(job.ID, func(row *Job) { row.Status = status; row.Error = reason }); err != nil {
		return err
	}
	return os.RemoveAll(j.nodeWorkDir(job.ID))
}
