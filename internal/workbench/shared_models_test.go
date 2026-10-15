package workbench

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"yovoice/internal/catalog"
)

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
