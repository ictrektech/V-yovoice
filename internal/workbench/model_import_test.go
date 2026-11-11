package workbench

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"yovoice/internal/catalog"
	"yovoice/internal/msg"
)

func localGGUF(family string) []byte {
	var b bytes.Buffer
	b.WriteString("GGUF")
	_ = binary.Write(&b, binary.LittleEndian, uint32(3))
	_ = binary.Write(&b, binary.LittleEndian, uint64(1))
	_ = binary.Write(&b, binary.LittleEndian, uint64(1))
	_ = binary.Write(&b, binary.LittleEndian, uint64(len("general.architecture")))
	b.WriteString("general.architecture")
	_ = binary.Write(&b, binary.LittleEndian, uint32(8))
	_ = binary.Write(&b, binary.LittleEndian, uint64(len(family)))
	b.WriteString(family)
	b.Write(make([]byte, 64))
	return b.Bytes()
}

func TestImportLocalModelPreservesExternalFile(t *testing.T) {
	w, err := New(t.TempDir())
	must(t, err)
	defer w.Close()
	path := filepath.Join(t.TempDir(), "my-converted-model.gguf")
	content := localGGUF("kokoro_tts")
	must(t, os.WriteFile(path, content, 0600))
	must(t, w.ImportCatalogModel("kokoro-82m-q8", path))
	<-w.ModelDone()
	s := w.Store.Read()
	if s.ModelActivity.Status != "completed" || len(s.Models) != 1 {
		t.Fatalf("%+v", s.ModelActivity)
	}
	m := s.Models[0]
	if m.ID != "kokoro-82m-q8" || m.Path != path || m.Managed || m.SHA256 != fmt.Sprintf("%x", sha256.Sum256(content)) || s.Preferences.ModelDirectory != nil {
		t.Fatal(m)
	}
	must(t, w.ForgetModel(m.ID))
	got, err := os.ReadFile(path)
	must(t, err)
	if !bytes.Equal(got, content) || len(w.Store.Read().Models) != 0 {
		t.Fatal("移除只能解除登记")
	}
}

func TestImportLocalModelRejectsWrongFamilyAndRawWeights(t *testing.T) {
	w, err := New(t.TempDir())
	must(t, err)
	defer w.Close()
	for _, content := range [][]byte{localGGUF("llama"), []byte("PyTorch weights"), []byte("GGUF")} {
		path := filepath.Join(t.TempDir(), "renamed.gguf")
		must(t, os.WriteFile(path, content, 0600))
		must(t, w.ImportCatalogModel("kokoro-82m-q8", path))
		<-w.ModelDone()
		s := w.Store.Read()
		if s.ModelActivity.Status != "failed" || (s.ModelActivity.ErrorCode == nil || *s.ModelActivity.ErrorCode != msg.ErrLocalModelInvalid) || len(s.Models) != 0 {
			t.Fatalf("%+v", s.ModelActivity)
		}
	}
	if err := w.ImportCatalogModel("kokoro-82m-q8", "relative.gguf"); err == nil {
		t.Fatal("不接受相对路径")
	}
}

func TestImportLocalPackageVerifiesCompanionsAndStrippedPrefix(t *testing.T) {
	w, err := New(t.TempDir())
	must(t, err)
	defer w.Close()
	original := catalog.Models
	defer func() { catalog.Models = original }()
	main, companion := []byte("main"), []byte("side")
	model := catalog.ModelPackage{ID: "test-package", Family: "xtts_v2", RemotePath: "q8/main.gguf", StripPrefix: "q8", Files: []catalog.ModelFile{
		{Path: "q8/main.gguf", Size: 4, SHA256: fmt.Sprintf("%x", sha256.Sum256(main))},
		{Path: "q8/side.gguf", Size: 4, SHA256: fmt.Sprintf("%x", sha256.Sum256(companion))},
	}}
	catalog.Models = []catalog.ModelPackage{model}
	dir := t.TempDir()
	path := filepath.Join(dir, "main.gguf")
	must(t, os.WriteFile(path, main, 0600))
	for _, data := range [][]byte{nil, []byte("bad!"), companion} {
		if data != nil {
			must(t, os.WriteFile(filepath.Join(dir, "side.gguf"), data, 0600))
		}
		must(t, w.ImportCatalogModel(model.ID, path))
		<-w.ModelDone()
		s := w.Store.Read()
		if bytes.Equal(data, companion) {
			if s.ModelActivity.Status != "completed" || len(s.Models) != 1 || s.Models[0].Path != dir || s.Models[0].Managed {
				t.Fatalf("%+v %+v", s.ModelActivity, s.Models)
			}
		} else if s.ModelActivity.Status != "failed" || (s.ModelActivity.ErrorCode == nil || *s.ModelActivity.ErrorCode != msg.ErrLocalModelIncomplete) || len(s.Models) != 0 {
			t.Fatalf("%+v", s.ModelActivity)
		}
	}
}

func TestModelImportAndDownloadAreMutuallyExclusive(t *testing.T) {
	w, err := New(t.TempDir())
	must(t, err)
	defer w.Close()
	for _, kind := range []string{"download", "import"} {
		must(t, w.begin(kind, msg.ActivityVerifying, nil, nil, func(ctx context.Context) error { <-ctx.Done(); return ctx.Err() }))
		other := "import"
		if kind == "import" {
			other = "download"
		}
		if err := w.begin(other, msg.ActivityVerifying, nil, nil, func(context.Context) error { return nil }); err == nil {
			t.Fatal("导入与下载不应同时修改登记")
		}
		done := w.ModelDone()
		w.CancelModel()
		<-done
	}
}

func TestDownloadDoesNotReplaceImportedOrUnregisteredFiles(t *testing.T) {
	w, err := New(t.TempDir())
	must(t, err)
	defer w.Close()
	model, err := catalog.Lookup("kokoro-82m-q8")
	must(t, err)
	external := filepath.Join(t.TempDir(), "external.gguf")
	content := localGGUF("kokoro_tts")
	must(t, os.WriteFile(external, content, 0600))
	must(t, w.ImportCatalogModel(model.ID, external))
	<-w.ModelDone()
	if err := w.DownloadModel(model.ID); err == nil {
		t.Fatal("不能覆盖导入模型登记")
	}
	got, err := os.ReadFile(external)
	must(t, err)
	if !bytes.Equal(got, content) {
		t.Fatal("导入文件被修改")
	}
	must(t, w.ForgetModel(model.ID))
	other, err := catalog.Lookup("index-2-q8")
	must(t, err)
	dest := modelDestination(w.Store.Read(), w.Store.Root, other)
	must(t, os.MkdirAll(filepath.Dir(dest), 0700))
	must(t, os.WriteFile(dest, []byte("local weights"), 0600))
	must(t, w.DownloadModel(other.ID))
	<-w.ModelDone()
	activity := w.Store.Read().ModelActivity
	if activity == nil || activity.ErrorCode == nil || *activity.ErrorCode != msg.ErrLocalModelProtected {
		t.Fatalf("未保护已有文件: %+v", activity)
	}
	got, err = os.ReadFile(dest)
	must(t, err)
	if string(got) != "local weights" {
		t.Fatal("已有文件被修改")
	}
}
