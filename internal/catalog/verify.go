package catalog

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
)

var verifiedFiles sync.Map

// VerifyPackage 校验实际将使用的模型；目录浏览不读取其他大模型，取消也不启动引擎。
func VerifyPackage(ctx context.Context, model ModelPackage, root string) error {
	for _, file := range model.PackageFiles() {
		path := root
		if len(model.Files) > 0 {
			path = filepath.Join(root, filepath.FromSlash(model.LocalPath(file.Path)))
		}
		if err := verifyFile(ctx, path, file); err != nil {
			return err
		}
	}
	return nil
}

func verifyFile(ctx context.Context, path string, want ModelFile) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() != want.Size {
		return fmt.Errorf("model file size mismatch")
	}
	key := fmt.Sprintf("%s|%d|%d", path, info.Size(), info.ModTime().UnixNano())
	got, cached := verifiedFiles.Load(key)
	if !cached {
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		defer file.Close()
		hash := sha256.New()
		buffer := make([]byte, 1<<20)
		for {
			if err := ctx.Err(); err != nil {
				return err
			}
			n, readErr := file.Read(buffer)
			_, _ = hash.Write(buffer[:n])
			if readErr == io.EOF {
				break
			}
			if readErr != nil {
				return readErr
			}
		}
		got = hex.EncodeToString(hash.Sum(nil))
		verifiedFiles.Store(key, got)
	}
	if got.(string) != want.SHA256 {
		return fmt.Errorf("model checksum mismatch")
	}
	return ctx.Err()
}
