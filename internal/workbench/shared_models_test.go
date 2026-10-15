package workbench

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/catalog"
)

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
