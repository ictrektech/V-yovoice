package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
	"yovoice/internal/vos"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	root := os.Getenv("VVOICE_STUDIO_DATA_DIR")
	if root == "" {
		root = "/data/studio"
	}
	assets := os.Getenv("VVOICE_STUDIO_ASSETS")
	if assets == "" {
		assets = "/opt/vvoice/web"
	}
	runtime := os.Getenv("VVOICE_AUDIOCPP_SERVER")
	if runtime == "" {
		runtime = "/opt/vvoice/audiocpp/audiocpp_server"
	}
	handler := &vos.Server{Root: root, Assets: assets, UserinfoURL: vos.DefaultUserinfo(), Runtime: runtime}
	jobs := &vos.Jobs{Server: handler}
	configPath := os.Getenv("VVOICE_SCHEDULER_CONFIG")
	if configPath == "" {
		configPath = "/data/scheduler.local.json"
	}
	handler.SchedulerPath = configPath
	jobs.ConfigPath = configPath
	if info, err := os.Stat(configPath); err == nil {
		if info.Mode().Perm()&0077 != 0 {
			log.Fatal("scheduler.local.json must be private (0600)")
		}
		b, err := os.ReadFile(configPath)
		if err != nil {
			log.Fatal("Scheduler configuration unreadable")
		}
		if json.Unmarshal(b, &jobs.Config) != nil {
			log.Fatal("Scheduler configuration invalid")
		}
	}
	handler.Jobs = jobs
	go jobs.Run(ctx)
	server := &http.Server{Addr: "127.0.0.1:7080", Handler: handler, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		<-ctx.Done()
		handler.Close(context.Background())
		stop, c := context.WithTimeout(context.Background(), 5*time.Second)
		defer c()
		_ = server.Shutdown(stop)
	}()
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}
