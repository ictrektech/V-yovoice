#!/usr/bin/env bash
set -euo pipefail

studio_build="/tmp/yovoice-studio-dev"
studio_assets="/tmp/yovoice-studio-assets"
studio_data="${YOVOICE_DEV_DATA:-/tmp/yovoice-dev-data}"
dev_token="${VVOICE_DEV_TOKEN:-yovoice-local-development-token-0001}"
export VVOICE_GATEWAY_BASE="${VVOICE_GATEWAY_BASE:-http://127.0.0.1:22888}"

if [[ ! "$dev_token" =~ ^[a-zA-Z0-9_-]{32,}$ ]]; then
  echo 'VVOICE_DEV_TOKEN 至少需要 32 个字符，且只能包含字母、数字、下划线和连字符。' >&2
  exit 1
fi
if [[ -n "${VITE_VOS_SPEECH_SERVICE_BASE:-}" || -n "${VVOICE_DEV_SPEECH:-}" ]]; then
  echo '开发模式现使用平台模型网关，请改用 VVOICE_GATEWAY_BASE=http://<VOS-IP>:22888 make dev-browser。' >&2
  exit 1
fi

# 已有开发进程占用端口时立即退出，不能把旧后端的健康响应当成本次启动成功。
node --input-type=module <<'JS'
import { createServer } from 'node:net';
await Promise.all([5173, 7080].map(port => new Promise((resolve, reject) => {
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
    kill "$studio_pid" 2>/dev/null || true
    wait "$studio_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

VVOICE_STUDIO_ASSETS="$studio_assets" \
VVOICE_STUDIO_DATA_DIR="$studio_data" \
VVOICE_STUDIO_DEV_TOKEN="$dev_token" \
VVOICE_SCHEDULER_CONFIG="${VVOICE_SCHEDULER_CONFIG:-$studio_data/absent-scheduler.json}" \
VOS_USERINFO_URL="${VOS_USERINFO_URL:-https://192.168.1.207:1180/v1000/oauth2/userinfo}" \
VVOICE_SHARED_MODELS=false \
"$studio_build" &
studio_pid=$!
backend_health=http://127.0.0.1:7080/health

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
