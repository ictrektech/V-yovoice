package workbench

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"yovoice/internal/catalog"
	"yovoice/internal/schema"
)

var SharedRepository = catalog.VOSRepository

var sharedHashes sync.Map

// 只读共享文件按路径、大小和修改时间缓存校验，所有用户共用，避免反复扫描大权重。
func verifiedSharedFile(path string, size int64, want string) bool {
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() != size {
		return false
	}
	key := fmt.Sprintf("%s|%d|%d", path, size, info.ModTime().UnixNano())
	if value, ok := sharedHashes.Load(key); ok {
		return value.(string) == want
	}
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return false
	}
	got := hex.EncodeToString(h.Sum(nil))
	sharedHashes.Store(key, got)
	return got == want
}

// SharedModelsMode 仅 VOS 开启；桌面端继续沿用上游模型安装方式。
func SharedModelsMode() bool { return os.Getenv("VVOICE_SHARED_MODELS") == "true" }

// SharedCatalog 保留上游全部模型与精度；其他仓库文件加目录前缀防止同名覆盖。
func SharedCatalog() []catalog.ModelPackage {
	models := []catalog.ModelPackage{}
	for _, m := range catalog.Models {
		if m.RemotePath == "" {
			m.RemotePath = "imports/" + m.ID + ".gguf"
		}
		if m.Repo != "" {
			prefix := filepath.ToSlash(filepath.Join("mirrors", m.Repo))
			m.RemotePath = prefix + "/" + m.RemotePath
			m.Files = append([]catalog.ModelFile(nil), m.Files...)
			for i := range m.Files {
				m.Files[i].Path = prefix + "/" + m.Files[i].Path
			}
		}
		models = append(models, m)
	}
	return models
}

// SyncSharedModels 只读取 Model Hub 的稳定导出，不拷贝或删除共享权重。
func (w *Workbench) SyncSharedModels() error {
	root := os.Getenv("MODEL_HUB_SHARED_MODELS_PATH")
	if root == "" {
		root = "/modelhub"
	}
	base := filepath.Join(root, "export", "ms", SharedRepository, "current")
	models := []schema.InstalledModel{}
	for _, m := range SharedCatalog() {
		ready := true
		for _, f := range m.PackageFiles() {
			if !verifiedSharedFile(filepath.Join(base, filepath.FromSlash(f.Path)), f.Size, f.SHA256) {
				ready = false
				break
			}
		}
		if !ready {
			continue
		}
		path := filepath.Join(base, filepath.FromSlash(m.RemotePath))
		if len(m.Files) > 0 {
			path = base
			if m.Repo != "" {
				path = filepath.Join(base, "mirrors", m.Repo)
			}
		}
		models = append(models, schema.InstalledModel{ID: m.ID, Path: path, Managed: false})
	}
	if slices.Equal(w.Store.Read().Models, models) {
		return nil
	}
	return w.Store.Update(func(s *schema.State) { s.Models = models }, true)
}

// PullSharedModel 使用文件级补下载，避免把整个 GGUF 仓库全部下载。
func PullSharedModel(ctx context.Context, id string) error {
	var selected *catalog.ModelPackage
	for _, m := range SharedCatalog() {
		if m.ID == id {
			selected = &m
			break
		}
	}
	if selected == nil {
		return fmt.Errorf("unsupported shared model")
	}
	files := []string{}
	for _, f := range selected.PackageFiles() {
		files = append(files, f.Path)
	}
	body, err := json.Marshal(map[string]any{"source": "ms", "model_id": SharedRepository, "files": files, "append": true})
	if err != nil {
		return err
	}
	base := os.Getenv("MODEL_HUB_API_URL")
	if base == "" {
		base = "http://model-hub-backend:5005"
	}
	req, err := http.NewRequestWithContext(ctx, "POST", base+"/api/v1/models/pull", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusConflict && (res.StatusCode < 200 || res.StatusCode >= 300) {
		return fmt.Errorf("Model Hub HTTP %d", res.StatusCode)
	}
	return nil
}

// UnloadRuntime 等待当前生成真正结束，再停止引擎；不删除共享模型。
func (w *Workbench) UnloadRuntime() {
	w.Cancel()
	<-w.Done()
	w.engine.Stop()
}
