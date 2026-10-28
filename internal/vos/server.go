// Package vos 为 VOS 提供真实浏览器传输，保留上游桌面传输的安全边界。
package vos

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"yovoice/internal/catalog"
	"yovoice/internal/desktop"
	"yovoice/internal/msg"
	"yovoice/internal/schema"
	"yovoice/internal/workbench"
)

type Server struct {
	Root, Assets, UserinfoURL, Runtime, SchedulerPath string
	Client                                            *http.Client
	Jobs                                              *Jobs
	mu                                                sync.Mutex
	users                                             map[string]*workbench.Workbench
}

type Identity struct{ Key, Role, Subject string }

// identity 始终在服务端核验访问令牌，不信任浏览器提供的用户名或路径。
func (s *Server) identity(r *http.Request) (Identity, error) {
	return s.verifyIdentity(r, false)
}

func (s *Server) verifyIdentity(r *http.Request, legacyApplication bool) (Identity, error) {
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer ") {
		return Identity{}, fmt.Errorf("VOS sign-in required")
	}
	req, err := http.NewRequestWithContext(r.Context(), "GET", s.UserinfoURL, nil)
	if err != nil {
		return Identity{}, err
	}
	req.Header.Set("Authorization", auth)
	client := s.Client
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	res, err := client.Do(req)
	if err != nil {
		return Identity{}, err
	}
	defer res.Body.Close()
	var user struct {
		Sub    string `json:"sub"`
		Role   string `json:"role_code"`
		Enable int    `json:"enable"`
	}
	if res.StatusCode != 200 {
		// 旧版 VOS 的应用令牌在 userinfo 查库失败，但 user/check 可核验签名身份。
		var rejected struct {
			Error string `json:"error"`
		}
		if !legacyApplication || res.StatusCode != 401 || json.NewDecoder(http.MaxBytesReader(nil, res.Body, 65536)).Decode(&rejected) != nil || rejected.Error != "invalid_token" {
			return Identity{}, fmt.Errorf("VOS sign-in rejected")
		}
		return s.legacySchedulerIdentity(r, client)
	}
	if err = json.NewDecoder(http.MaxBytesReader(nil, res.Body, 65536)).Decode(&user); err != nil || user.Sub == "" || user.Enable != 1 {
		return Identity{}, fmt.Errorf("invalid VOS identity")
	}
	hash := sha256.Sum256([]byte(user.Sub))
	return Identity{Key: hex.EncodeToString(hash[:]), Role: user.Role, Subject: user.Sub}, nil
}

func (s *Server) user(id string) (*workbench.Workbench, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.users == nil {
		s.users = map[string]*workbench.Workbench{}
	}
	if w := s.users[id]; w != nil {
		return w, nil
	}
	w, err := workbench.New(filepath.Join(s.Root, "users", id))
	if err != nil {
		return nil, err
	}
	if err = w.UseBundled(s.Runtime); err != nil {
		w.Close()
		return nil, err
	}
	s.users[id] = w
	return w, nil
}

func jsonReply(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

// 浏览器可调用的方法为明确白名单，拒绝上游任意文件路径、内核安装及外部命令。
var allowed = map[string]bool{
	"draft.save": true, "draft.delete": true, "generation.start": true, "generation.cue": true,
	"character.save": true, "character.preview": true, "character.delete": true, "character.discardPreview": true,
	"voice.fromGeneration": true, "voice.suggest": true, "voice.update": true, "voice.record": true, "timeline.import": true,
	"media.rename": true, "media.delete": true, "generation.lyricTimes": true, "generation.lyricWords": true, "melody.inspect": true, "melody.transform": true, "melody.dismiss": true, "operation.cancel": true, "diag.client": true,
}

func (s *Server) ServeHTTP(out http.ResponseWriter, r *http.Request) {
	out.Header().Set("X-Content-Type-Options", "nosniff")
	if r.Method == "GET" && r.URL.Path == "/health" {
		jsonReply(out, map[string]string{"status": "ok"})
		return
	}
	if r.URL.Path == "/api/v1/scheduler/binding" {
		s.binding(out, r)
		return
	}
	if r.URL.Path == "/internal/speech" {
		s.speech(out, r)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/scheduler/executions/") {
		if s.Jobs == nil {
			http.Error(out, "Scheduler unavailable", 503)
			return
		}
		s.Jobs.ServeHTTP(out, r)
		return
	}
	if !strings.HasPrefix(r.URL.Path, "/studio-api/") {
		if r.URL.Path == "/" || strings.HasSuffix(r.URL.Path, ".html") {
			out.Header().Set("Cache-Control", "no-store")
		}
		http.FileServer(http.Dir(s.Assets)).ServeHTTP(out, r)
		return
	}
	identity, err := s.identity(r)
	if err != nil {
		http.Error(out, "VOS sign-in required", 401)
		return
	}
	id := identity.Key
	w, err := s.user(id)
	if err != nil {
		http.Error(out, "Workbench unavailable", 503)
		return
	}
	if err = w.SyncSharedModels(); err != nil {
		http.Error(out, "Shared models unavailable", 503)
		return
	}
	out.Header().Set("Cache-Control", "no-store")
	switch {
	case r.Method == "POST" && r.URL.Path == "/studio-api/call":
		var call struct {
			Method    string          `json:"method"`
			Data      json.RawMessage `json:"data"`
			RequestID string          `json:"requestId"`
		}
		if json.NewDecoder(http.MaxBytesReader(out, r.Body, 28<<20)).Decode(&call) != nil {
			http.Error(out, "Invalid request", 400)
			return
		}
		var result any
		switch call.Method {
		case "model.download":
			if identity.Role != "system_admin" && identity.Role != "platform_admin" {
				http.Error(out, "Model administrator required", 403)
				return
			}
			var input struct {
				ID string `json:"id"`
			}
			if err = json.Unmarshal(call.Data, &input); err == nil {
				err = workbench.PullSharedModel(r.Context(), input.ID)
			}
			result = true
		case "model.cancel":
			if identity.Role != "system_admin" && identity.Role != "platform_admin" {
				http.Error(out, "Model administrator required", 403)
				return
			}
			var input struct {
				ID string `json:"id"`
			}
			if err = json.Unmarshal(call.Data, &input); err == nil {
				err = workbench.CancelSharedModel(r.Context(), input.ID)
			}
			result = true
		case "model.forget":
			w.UnloadRuntime()
			result = true
		case "generation.start", "generation.cue", "character.preview":
			if s.Jobs == nil {
				http.Error(out, "V-Scheduler configuration required", 503)
				return
			}
			result, err = s.Jobs.Enqueue(id, call.RequestID, call.Method, call.Data)
		case "generation.alignLyrics":
			if s.Jobs == nil {
				http.Error(out, "V-Scheduler configuration required", 503)
				return
			}
			var snapshot json.RawMessage
			if snapshot, err = s.Jobs.alignmentSnapshot(id, w, call.Data); err == nil {
				result, err = s.Jobs.Enqueue(id, call.RequestID, call.Method, snapshot)
			}
		case "melody.plan", "melody.cover", "melody.listen":
			if s.Jobs == nil {
				http.Error(out, "V-Scheduler configuration required", 503)
				return
			}
			var snapshot json.RawMessage
			if snapshot, err = musicSnapshot(w, call.Method, call.Data, s.Jobs.config().Models); err == nil {
				result, err = s.Jobs.Enqueue(id, call.RequestID, call.Method, snapshot)
			}
		case "melody.result":
			if s.Jobs == nil {
				http.Error(out, "V-Scheduler configuration required", 503)
				return
			}
			var input struct {
				ID string `json:"id"`
			}
			if err = json.Unmarshal(call.Data, &input); err == nil {
				result, err = s.Jobs.musicResult(id, input.ID)
			}
		case "operation.cancel":
			if s.Jobs == nil {
				http.Error(out, "V-Scheduler configuration required", 503)
				return
			}
			err = s.Jobs.Cancel(id)
			result = true
		case "state.get":
			state := w.Store.Read()
			if s.Jobs != nil {
				state = s.Jobs.VisibleState(id, state)
			}
			result = map[string]any{"state": state, "catalog": workbench.SharedCatalog(), "engine": map[string]string{"version": catalog.EngineVersion, "minimum": catalog.EngineMinimum}, "desktop": false, "assistant": map[string]bool{"available": false}}
		case "preferences.save":
			// 浏览器只能保存语言等个人偏好，不能修改共享目录、代理及推理后端。
			var p struct {
				UiLocale schema.UiLocale `json:"uiLocale"`
			}
			if err = json.Unmarshal(call.Data, &p); err == nil {
				if _, err = schema.ParseUiLocale(string(p.UiLocale)); err == nil {
					err = w.Store.Update(func(state *schema.State) { state.Preferences.UiLocale = p.UiLocale }, true)
				}
			}
		case "runtime.unload":
			w.UnloadRuntime()
			result = true
		default:
			if !allowed[call.Method] {
				http.Error(out, "Unsupported browser method", 403)
				return
			}
			invoke := func() (any, error) { return desktop.Call(r.Context(), w, call.Method, call.Data) }
			if s.Jobs != nil && (call.Method == "draft.delete" || call.Method == "character.delete" || call.Method == "media.delete" || call.Method == "generation.lyricWords" || call.Method == "generation.lyricTimes") {
				result, err = s.Jobs.withoutPending(id, invoke)
			} else {
				result, err = invoke()
			}
		}
		if err != nil {
			jsonReply(out, map[string]any{"error": msg.Encode(err)})
			return
		}
		jsonReply(out, map[string]any{"result": result})
	case r.Method == "GET" && strings.HasPrefix(r.URL.Path, "/studio-api/media/"):
		parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/studio-api/media/"), "/")
		if len(parts) != 2 {
			http.NotFound(out, r)
			return
		}
		if parts[0] == "outputs" && s.Jobs != nil && !s.Jobs.OutputAllowed(id, parts[1], w.Store.Read()) {
			http.NotFound(out, r)
			return
		}
		path, e := w.Store.MediaPath(parts[0], parts[1])
		if e != nil || (parts[0] != "voices" && parts[0] != "outputs") {
			http.NotFound(out, r)
			return
		}
		http.ServeFile(out, r, path)
	default:
		http.NotFound(out, r)
	}
}

func (s *Server) Close(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, w := range s.users {
		w.Close()
	}
}

func DefaultUserinfo() string {
	if url := os.Getenv("VOS_USERINFO_URL"); url != "" {
		return url
	}
	return "http://host.docker.internal:" + os.Getenv("VOS_API_GW_PORT_INTERNAL") + "/v1000/oauth2/userinfo"
}
