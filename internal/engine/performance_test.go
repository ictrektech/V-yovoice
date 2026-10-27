package engine

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
	"yovoice/internal/catalog"
	"yovoice/internal/msg"
	"yovoice/internal/store"
)

func performanceTestEngine(t *testing.T) (*Engine, string, string, context.Context) {
	t.Helper()
	root := t.TempDir()
	_, err := store.New(root)
	must(t, err)
	engine := New(root)
	t.Cleanup(engine.Stop)
	executable, err := os.Executable()
	must(t, err)
	model := filepath.Join(root, "model.gguf")
	must(t, os.WriteFile(model, []byte("test"), 0600))
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	t.Cleanup(cancel)
	return engine, executable, model, ctx
}

func performanceSessionOptions(t *testing.T, engine *Engine) map[string]string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(engine.root, "runtime", "server.json"))
	must(t, err)
	var config struct {
		Models []struct {
			SessionOptions map[string]string `json:"session_options"`
		} `json:"models"`
	}
	must(t, json.Unmarshal(data, &config))
	if len(config.Models) != 1 {
		t.Fatalf("模型配置数量为 %d", len(config.Models))
	}
	return config.Models[0].SessionOptions
}

func TestPerformanceFirstFamilies(t *testing.T) {
	for _, modelID := range []string{"ace-step-1.5-turbo-q8", "qwen3-tts-base-q8", "yue2-3b-q8", "voxcpm2-q8"} {
		t.Run(modelID, func(t *testing.T) {
			engine, executable, model, ctx := performanceTestEngine(t)
			definition, err := catalog.Lookup(modelID)
			must(t, err)
			definition.SessionOptions = map[string]string{"test.existing": "kept"}
			original := definition.SessionOptions
			must(t, engine.start(ctx, executable, model, definition, "cuda", true, 0, func(msg.Code, msg.Params) {}))
			options := performanceSessionOptions(t, engine)
			if options[definition.Family+".perf_mode"] != "cuda_perf" || options["test.existing"] != "kept" {
				t.Fatalf("会话选项未正确合并：%v", options)
			}
			if _, ok := original[definition.Family+".perf_mode"]; ok {
				t.Fatal("启动时修改了模型目录中的原始会话选项")
			}
		})
	}
}

func TestPerformanceFirstCUDA13(t *testing.T) {
	engine, executable, model, ctx := performanceTestEngine(t)
	definition, err := catalog.Lookup("qwen3-tts-base-q8")
	must(t, err)
	must(t, engine.start(ctx, executable, model, definition, "cuda13", true, 0, func(msg.Code, msg.Params) {}))
	if got := performanceSessionOptions(t, engine)["qwen3_tts.perf_mode"]; got != "cuda_perf" {
		t.Fatalf("CUDA 13 性能模式为 %q", got)
	}
}

func TestPerformanceFirstDisabledOrNonCUDA(t *testing.T) {
	for _, item := range []struct {
		name             string
		backend          string
		performanceFirst bool
	}{{"disabled", "cuda", false}, {"cpu", "cpu", true}, {"vulkan", "vulkan", true}} {
		t.Run(item.name, func(t *testing.T) {
			engine, executable, model, ctx := performanceTestEngine(t)
			definition, err := catalog.Lookup("qwen3-tts-base-q8")
			must(t, err)
			must(t, engine.start(ctx, executable, model, definition, item.backend, item.performanceFirst, 0, func(msg.Code, msg.Params) {}))
			if got := performanceSessionOptions(t, engine)["qwen3_tts.perf_mode"]; got != "" {
				t.Fatalf("不应注入性能模式，实际为 %q", got)
			}
		})
	}
}

func TestPerformanceFirstCacheKey(t *testing.T) {
	engine, executable, model, ctx := performanceTestEngine(t)
	definition, err := catalog.Lookup("qwen3-tts-base-q8")
	must(t, err)
	start := func(performanceFirst bool) int {
		t.Helper()
		must(t, engine.start(ctx, executable, model, definition, "cuda", performanceFirst, 0, func(msg.Code, msg.Params) {}))
		return engine.process.Process.Pid
	}
	disabled := start(false)
	if pid := start(false); pid != disabled {
		t.Fatal("开关不变时未复用内核")
	}
	enabled := start(true)
	if enabled == disabled {
		t.Fatal("开启性能优先后未重启内核")
	}
	if pid := start(true); pid != enabled {
		t.Fatal("性能优先保持开启时未复用内核")
	}
	if pid := start(false); pid == enabled {
		t.Fatal("关闭性能优先后未重启内核")
	}
}
