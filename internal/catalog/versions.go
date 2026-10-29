package catalog

import (
	_ "embed"
	"encoding/json"
)

// 只保留本次目录更新前已发布文件的精确清单，旧权重仍需逐文件校验。
//
//go:embed previous-model-files.json
var previousModelJSON []byte

var previousModels = func() map[string]ModelPackage {
	var rows []ModelPackage
	if err := json.Unmarshal(previousModelJSON, &rows); err != nil {
		panic(err)
	}
	models := make(map[string]ModelPackage, len(rows))
	for _, row := range rows {
		models[row.ID] = row
	}
	return models
}()

// PreviousVersion 返回上一次已发布的文件清单；模型 ID、能力和加载参数仍沿用当前目录。
func (m ModelPackage) PreviousVersion() ModelPackage {
	if old, ok := previousModels[m.ID]; ok {
		m.Size, m.SHA256, m.Files = old.Size, old.SHA256, old.Files
	}
	return m
}

// InstalledVersion 只按服务端登记的摘要选择已知版本，不把任意摘要当作可信权重。
func (m ModelPackage) InstalledVersion(sha256 string) ModelPackage {
	old := m.PreviousVersion()
	if sha256 != "" && old.MainFile().SHA256 == sha256 {
		return old
	}
	return m
}
