package workbench

import (
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"yovoice/internal/catalog"
	"yovoice/internal/download"
	"yovoice/internal/msg"
	"yovoice/internal/store"
)

func (w *Workbench) ImportModelAuto(path string) error {
	return w.begin("import", msg.ActivityImport, nil, nil, func(ctx context.Context) error {
		paths := []string{path}
		info, e := os.Stat(path)
		if e != nil {
			return e
		}
		if info.IsDir() {
			paths, e = filepath.Glob(filepath.Join(path, "*.gguf"))
			if e != nil {
				return e
			}
		}
		count := 0
		for _, p := range paths {
			if e = ctx.Err(); e != nil {
				return e
			}
			size := download.FileSize(p)
			if !slices.ContainsFunc(catalog.Models, func(m catalog.ModelPackage) bool {
				return slices.ContainsFunc(m.PackageFiles(), func(f catalog.ModelFile) bool { return f.Path == m.RemotePath && f.Size == size })
			}) {
				continue
			}
			hash, e := download.Hash(ctx, p)
			if e != nil {
				return e
			}
			for _, m := range catalog.Models {
				if m.MainFile().SHA256 == hash {
					path := p
					if len(m.Files) > 0 {
						// 多文件模型只认完整的模型目录：主模型旁需有其余文件。
						if path = packageRoot(m, p); path == "" {
							continue
						}
					}
					// 不用自动识别覆盖已有登记或暂停中的下载。
					w.mu.Lock()
					state := w.Store.Read()
					previous, exists := installedModel(state, m.ID)
					_, pending := state.ModelDownloads[m.ID]
					if pending || (exists && !store.SamePath(previous.Path, path) && (previous.Managed || existsPath(previous.Path))) {
						w.mu.Unlock()
						continue
					}
					managed := exists && previous.Managed && store.SamePath(previous.Path, path)
					w.engine.Stop()
					e = w.register(m.ID, path, managed, hash, managed && previous.Pinned)
					w.mu.Unlock()
					if e != nil {
						return e
					}
					count++
				}
			}
		}
		if count == 0 {
			return msg.Err(msg.ErrModelImportNone, nil)
		}
		return nil
	})
}

func packageRoot(m catalog.ModelPackage, main string) string {
	root := filepath.Dir(main)
	for i := 0; i < strings.Count(m.LocalPath(m.RemotePath), "/"); i++ {
		root = filepath.Dir(root)
	}
	for _, f := range m.Files {
		if download.FileSize(filepath.Join(root, filepath.FromSlash(m.LocalPath(f.Path)))) != f.Size {
			return ""
		}
	}
	return root
}
