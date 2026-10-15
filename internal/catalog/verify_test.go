package catalog

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestVerifyPackageRejectsCorruptionAndHonorsCancellation(t *testing.T) {
	path := filepath.Join(t.TempDir(), "model.gguf")
	data := []byte("good")
	sum := sha256.Sum256(data)
	model := ModelPackage{Size: 4, SHA256: hex.EncodeToString(sum[:])}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPackage(context.Background(), model, path); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("evil"), 0600); err != nil {
		t.Fatal(err)
	}
	changed := time.Now().Add(time.Second)
	if err := os.Chtimes(path, changed, changed); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPackage(context.Background(), model, path); err == nil {
		t.Fatal("same-size corrupted file was accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := VerifyPackage(ctx, model, path); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled verification: %v", err)
	}
}
