#!/usr/bin/env bash
set -euo pipefail

studio_build="/tmp/yovoice-studio-dev"
studio_assets="/tmp/yovoice-studio-assets"
studio_data="${YOVOICE_DEV_DATA:-/tmp/yovoice-dev-data}"
dev_token="${VVOICE_DEV_TOKEN:-yovoice-local-development-token-0001}"
pnpm_command="${YOVOICE_PNPM:-pnpm}"

if ! command -v "$pnpm_command" >/dev/null 2>&1; then
  pnpm_command=corepack
fi

# 空资源目录让 Vite 提供页面；Go 只负责真实 RPC、媒体和 VOS 鉴权边界。
mkdir -p "$studio_assets" "$studio_data"
go build -o "$studio_build" ./cmd/vvoice-studio

run_web() {
  if [[ "$pnpm_command" == "corepack" ]]; then
    corepack pnpm --dir web "$@"
  else
    "$pnpm_command" --dir web "$@"
  fi
}

studio_pid=
cleanup() {
  if [[ -n "$studio_pid" ]]; then
    kill "$studio_pid" 2>/dev/null || true
    wait "$studio_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

VVOICE_STUDIO_ASSETS="$studio_assets" \
VVOICE_STUDIO_DATA_DIR="$studio_data" \
VVOICE_STUDIO_DEV_TOKEN="$dev_token" \
VVOICE_SCHEDULER_CONFIG="${VVOICE_SCHEDULER_CONFIG:-$studio_data/absent-scheduler.json}" \
VOS_USERINFO_URL="${VOS_USERINFO_URL:-https://192.168.1.207:1180/v1000/oauth2/userinfo}" \
MODEL_HUB_SHARED_MODELS_PATH="${MODEL_HUB_SHARED_MODELS_PATH:-$studio_data/modelhub}" \
"$studio_build" &
studio_pid=$!

for _ in {1..50}; do
  if curl -fsS http://127.0.0.1:7080/health >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$studio_pid" 2>/dev/null; then
    wait "$studio_pid"
  fi
  sleep 0.1
done

export VITE_VOS_SERVICE_BASE="${VITE_VOS_SERVICE_BASE:-http://127.0.0.1:7080}"
export VITE_VOS_DEV_TOKEN="$dev_token"
run_web exec vite --host 127.0.0.1
