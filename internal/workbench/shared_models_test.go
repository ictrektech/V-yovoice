package workbench

import (
	"strings"
	"testing"
	"yovoice/internal/catalog"
)

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
