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

func TestInstalledVersionUsesOnlyFrozenFileDefinitions(t *testing.T) {
	current, err := Lookup("kokoro-82m-q8")
	if err != nil {
		t.Fatal(err)
	}
	old := current.PreviousVersion()
	if old.SHA256 == current.SHA256 || current.InstalledVersion(old.SHA256).SHA256 != old.SHA256 {
		t.Fatal("未保留已发布的旧模型版本")
	}
	if got := current.InstalledVersion("untrusted"); got.SHA256 != current.SHA256 {
		t.Fatal("未知摘要不应放宽文件校验")
	}
}

func TestVerifyStrippedPackageFiles(t *testing.T) {
	root := t.TempDir()
	sum := sha256.Sum256([]byte("good"))
	model := ModelPackage{StripPrefix: "q8_0", Files: []ModelFile{{Path: "q8_0/model.gguf", Size: 4, SHA256: hex.EncodeToString(sum[:])}}}
	if err := os.WriteFile(filepath.Join(root, "model.gguf"), []byte("good"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPackage(context.Background(), model, root); err != nil {
		t.Fatal("内核加载目录应按本地路径校验配套文件", err)
	}
}
