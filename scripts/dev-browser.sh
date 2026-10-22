#!/usr/bin/env bash
set -euo pipefail

studio_build="/tmp/yovoice-studio-dev"
studio_assets="/tmp/yovoice-studio-assets"
studio_data="${YOVOICE_DEV_DATA:-/tmp/yovoice-dev-data}"
dev_token="${VVOICE_DEV_TOKEN:-yovoice-local-development-token-0001}"
speech_mode="${VVOICE_DEV_SPEECH:-local}"

if [[ ! "$dev_token" =~ ^[a-zA-Z0-9_-]{32,}$ ]]; then
  echo 'VVOICE_DEV_TOKEN 至少需要 32 个字符，且只能包含字母、数字、下划线和连字符。' >&2
  exit 1
fi
case "$speech_mode" in local|external|off) ;; *) echo 'VVOICE_DEV_SPEECH 仅支持 local、external、off。' >&2; exit 1 ;; esac
if [[ "$speech_mode" == external && -z "${VITE_VOS_SPEECH_SERVICE_BASE:-}" ]]; then
  echo 'external 模式需要 VITE_VOS_SPEECH_SERVICE_BASE 指向已运行的 V-Voice。' >&2
  exit 1
fi
export VVOICE_DEV_TOKEN="$dev_token" YOVOICE_DEV_DATA="$studio_data" VVOICE_DEV_SPEECH="$speech_mode"

# 已有开发进程占用端口时立即退出，不能把旧后端的健康响应当成本次启动成功。
node --input-type=module <<'JS'
import { createServer } from 'node:net';
const ports = process.env.VVOICE_DEV_SPEECH === 'local' ? [5173, 7080, 22700] : [5173, 7080];
await Promise.all(ports.map(port => new Promise((resolve, reject) => {
  const server = createServer();
  server.once('error', () => reject(new Error(`端口 ${port} 不可用，请先停止占用端口的开发进程。`)));
  server.listen(port, '0.0.0.0', () => server.close(resolve));
}))).catch(error => { console.error(error.message); process.exitCode = 1; });
JS

# 空资源目录让 Vite 提供页面；Go 只负责真实 RPC、媒体和 VOS 鉴权边界。
mkdir -p "$studio_assets" "$studio_data"
npm --prefix frontend run build
go build -o "$studio_build" ./cmd/vvoice-studio

run_web() {
  # 直接管理 Vite 进程，退出时不遗留包管理器派生的服务。
  cd web
  exec node node_modules/vite/bin/vite.js --host 0.0.0.0
}

studio_pid=
web_pid=
cleanup() {
  if [[ -n "$web_pid" ]]; then
    kill "$web_pid" 2>/dev/null || true
    wait "$web_pid" 2>/dev/null || true
  fi
  if [[ -n "$studio_pid" ]]; then
    if [[ "$speech_mode" == local ]]; then
      docker stop --time 45 "vvoice-dev-$(id -u)" >/dev/null 2>&1 || true
    fi
    kill "$studio_pid" 2>/dev/null || true
    wait "$studio_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$speech_mode" == local ]]; then
  mkdir -p .local/dev
  cp "$studio_build" .local/dev/vvoice-studio
  python3 scripts/dev-speech.py &
  studio_pid=$!
  # 本机语音服务只监听回环地址；局域网浏览器统一经过 Vite。
  export VITE_VOS_SPEECH_SERVICE_BASE=http://127.0.0.1:22700
  backend_health=http://127.0.0.1:22700/health
else
  VVOICE_STUDIO_ASSETS="$studio_assets" \
  VVOICE_STUDIO_DATA_DIR="$studio_data" \
  VVOICE_STUDIO_DEV_TOKEN="$dev_token" \
  VVOICE_SCHEDULER_CONFIG="${VVOICE_SCHEDULER_CONFIG:-$studio_data/absent-scheduler.json}" \
  VOS_USERINFO_URL="${VOS_USERINFO_URL:-https://192.168.1.207:1180/v1000/oauth2/userinfo}" \
  MODEL_HUB_SHARED_MODELS_PATH="${MODEL_HUB_SHARED_MODELS_PATH:-$studio_data/modelhub}" \
  "$studio_build" &
  studio_pid=$!
  backend_health=http://127.0.0.1:7080/health
fi

for _ in {1..120}; do
  if ! kill -0 "$studio_pid" 2>/dev/null; then
    wait "$studio_pid"
    exit 1
  fi
  if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS "$backend_health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS "$backend_health" >/dev/null

export VITE_VOS_SERVICE_BASE="${VITE_VOS_SERVICE_BASE:-http://127.0.0.1:7080}"
export VITE_VOS_DEV_TOKEN="$dev_token"
run_web &
web_pid=$!
# 任一服务退出就停止整套开发服务，避免页面继续连接已经失效的后端。
while kill -0 "$studio_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
if ! kill -0 "$studio_pid" 2>/dev/null; then
  wait "$studio_pid"
else
  wait "$web_pid"
fi
