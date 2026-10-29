package workbench

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/catalog"
)

func TestSharedModelsRetainPreviousWeightsAndUseStrippedPackageRoot(t *testing.T) {
	root := t.TempDir()
	t.Setenv("MODEL_HUB_SHARED_MODELS_PATH", root)
	w, err := New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	old, err := catalog.Lookup("kokoro-82m-q8")
	if err != nil {
		t.Fatal(err)
	}
	old = old.PreviousVersion()
	base := filepath.Join(root, "export", "ms", SharedRepository, "current")
	path := filepath.Join(base, filepath.FromSlash(old.RemotePath))
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Truncate(old.Size); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	if err := w.SyncSharedModels(); err != nil {
		t.Fatal(err)
	}
	models := w.Store.Read().Models
	if len(models) != 1 || models[0].ID != old.ID || models[0].SHA256 != old.MainFile().SHA256 {
		t.Fatal("升级目录不应把已安装的旧共享模型移除", models)
	}

	original := catalog.Models
	catalog.Models = []catalog.ModelPackage{{ID: "stripped", Repo: "owner/repo", Directory: "package", StripPrefix: "q8", RemotePath: "q8/main.gguf", Files: []catalog.ModelFile{{Path: "q8/main.gguf", Size: 4, SHA256: "known"}}}}
	defer func() { catalog.Models = original }()
	packageRoot := filepath.Join(base, "mirrors", "owner", "repo", "q8")
	if err := os.MkdirAll(packageRoot, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(packageRoot, "main.gguf"), []byte("data"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := w.SyncSharedModels(); err != nil {
		t.Fatal(err)
	}
	models = w.Store.Read().Models
	if len(models) != 1 || models[0].Path != packageRoot || models[0].SHA256 != "known" {
		t.Fatal("多文件共享模型应加载配套文件实际所在目录", models)
	}
}

func TestSharedModelCancellationOnlyTargetsMatchingActiveFiles(t *testing.T) {
	original := catalog.Models
	catalog.Models = []catalog.ModelPackage{{ID: "selected", RemotePath: "selected.gguf", Size: 4}}
	defer func() { catalog.Models = original }()
	var cancelled []string
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/tasks" {
			_, _ = w.Write([]byte(`[{"task_id":"mine","model_id":"ms://` + SharedRepository + `","phase":"DOWNLOADING","files":["selected.gguf"]},{"task_id":"other-file","model_id":"` + SharedRepository + `","phase":"DOWNLOADING","files":["other.gguf"]},{"task_id":"finished","model_id":"` + SharedRepository + `","phase":"READY","files":["selected.gguf"]},{"task_id":"other-repo","model_id":"other/repo","phase":"DOWNLOADING","files":["selected.gguf"]}]`))
			return
		}
		cancelled = append(cancelled, r.URL.Path)
		w.WriteHeader(200)
	}))
	defer hub.Close()
	t.Setenv("MODEL_HUB_API_URL", hub.URL)
	if err := CancelSharedModel(context.Background(), "selected"); err != nil {
		t.Fatal(err)
	}
	if len(cancelled) != 1 || cancelled[0] != "/api/v1/tasks/mine/cancel" {
		t.Fatalf("cancelled unrelated tasks: %v", cancelled)
	}
}

func TestSharedModelBrowsingDoesNotHashWeights(t *testing.T) {
	root := t.TempDir()
	t.Setenv("MODEL_HUB_SHARED_MODELS_PATH", root)
	w, err := New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	original := catalog.Models
	catalog.Models = []catalog.ModelPackage{{ID: "test-browse", RemotePath: "test.gguf", Size: 4, SHA256: strings.Repeat("0", 64)}}
	defer func() { catalog.Models = original }()
	base := filepath.Join(root, "export", "ms", SharedRepository, "current")
	if err := os.MkdirAll(base, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(base, "test.gguf"), []byte("data"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := w.SyncSharedModels(); err != nil {
		t.Fatal(err)
	}
	if len(w.Store.Read().Models) != 1 {
		t.Fatal("browsing should inspect metadata; the execution boundary verifies bytes")
	}
}

func TestSharedCatalogRetainsEveryUpstreamModelVariant(t *testing.T) {
	models := SharedCatalog()
	if len(models) != len(catalog.Models) {
		t.Fatal("shared catalog must not be a curated subset")
	}
	for i, original := range catalog.Models {
		got := models[i]
		if got.ID != original.ID || got.SHA256 != original.SHA256 || got.Size != original.Size || got.Precision != original.Precision {
			t.Fatalf("model contract changed: %s", original.ID)
		}
		if original.Repo != "" && !strings.HasPrefix(got.RemotePath, "mirrors/"+original.Repo+"/") {
			t.Fatalf("missing repo namespace: %s", got.RemotePath)
		}
		for n, f := range got.Files {
			if f.SHA256 != original.Files[n].SHA256 || f.Size != original.Files[n].Size {
				t.Fatal("shared mapping changed file integrity")
			}
		}
	}
}

// 共享仓库失败后不能追加，补下载应改为仅下载当前模型文件，保证“继续下载”能重试。
func TestPullSharedModelRetriesWithoutAppendWhenRepositoryFailed(t *testing.T) {
	original := catalog.Models
	catalog.Models = []catalog.ModelPackage{{ID: "selected", RemotePath: "selected.gguf", Size: 4}}
	defer func() { catalog.Models = original }()
	var bodies []map[string]any
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Errorf("invalid pull body")
		}
		bodies = append(bodies, body)
		if body["append"] == true {
			w.WriteHeader(http.StatusBadRequest)
			_, _ = w.Write([]byte(`{"code":"BAD_REQUEST","detail":"append requires a ready model","error":{"message":"append requires a ready model"}}`))
			return
		}
		_, _ = w.Write([]byte(`{"task_id":"task-1"}`))
	}))
	defer hub.Close()
	t.Setenv("MODEL_HUB_API_URL", hub.URL)

	if err := PullSharedModel(context.Background(), "selected"); err != nil {
		t.Fatalf("pull failed: %v", err)
	}
	if len(bodies) != 2 {
		t.Fatalf("expected append and fallback pulls, got %d", len(bodies))
	}
	if bodies[1]["append"] != false {
		t.Fatalf("fallback should not append: %v", bodies[1])
	}
	if files, ok := bodies[1]["files"].([]any); !ok || len(files) != 1 || files[0] != "selected.gguf" {
		t.Fatalf("fallback must keep selected files: %v", bodies[1])
	}
}

// 其他失败原因不应重复下载，直接返回服务端说明。
func TestPullSharedModelReportsOtherErrors(t *testing.T) {
	original := catalog.Models
	catalog.Models = []catalog.ModelPackage{{ID: "selected", RemotePath: "selected.gguf", Size: 4}}
	defer func() { catalog.Models = original }()
	calls := 0
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"detail":"selected file is absent from repository"}`))
	}))
	defer hub.Close()
	t.Setenv("MODEL_HUB_API_URL", hub.URL)

	err := PullSharedModel(context.Background(), "selected")
	if err == nil || err.Error() != "selected file is absent from repository" {
		t.Fatalf("unexpected error: %v", err)
	}
	if calls != 1 {
		t.Fatalf("unexpected retry: %d calls", calls)
	}
}
