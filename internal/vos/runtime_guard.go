package vos

import (
	"encoding/json"
	"yovoice/internal/catalog"
)

// restrictedRuntime 拒绝调度器尚未批准的推理配置，包括嵌套角色设置。
func restrictedRuntime(raw json.RawMessage) bool {
	var input any
	if json.Unmarshal(raw, &input) != nil {
		return false
	}
	var restricted func(any) bool
	restricted = func(value any) bool {
		switch node := value.(type) {
		case map[string]any:
			if runtime, ok := node["runtime"]; ok && runtime != nil {
				return true
			}
			if families, ok := node["modelOptions"].(map[string]any); ok {
				for family, value := range families {
					options, ok := value.(map[string]any)
					if !ok {
						continue
					}
					for _, spec := range catalog.GenerationOptions[family] {
						if _, present := options[spec.Key]; present && spec.RequiresRuntime {
							return true
						}
					}
				}
			}
			for _, child := range node {
				if restricted(child) {
					return true
				}
			}
		case []any:
			for _, child := range node {
				if restricted(child) {
					return true
				}
			}
		}
		return false
	}
	return restricted(input)
}
