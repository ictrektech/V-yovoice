#!/usr/bin/env bash
# 在 229 上创建独立联调服务，不修改已安装应用和共享权重。
set -euo pipefail
production=${1:?Usage: bash start-native-music-handoff.sh PRODUCTION_VOICE_CONTAINER}
source_root=/home/jhu/dev/repos/V-yovoice
build_root=/home/jhu/dev/build/v-yovoice/music-merge
test_name=v-voice-music-handoff-qa
test_image=v-voice-music-runtime:thor_20261019
docker inspect "$production" >/dev/null
if docker container inspect "$test_name" >/dev/null 2>&1; then
  echo 'Existing handoff container found; inspect it before replacing.' >&2
  exit 1
fi
userinfo=$(docker inspect "$production" --format '{{range .Config.Env}}{{println .}}{{end}}' |
  sed -n 's/^VOS_USERINFO_URL=//p')
test -n "$userinfo"
test -x "$build_root/vvoice-studio-arm64"
mkdir -p "$build_root/handoff-data"
chmod 700 "$build_root/handoff-data"
docker run -d --name "$test_name" --network vos_default --runtime nvidia --gpus all \
  --cpus 4 --memory 12g --volumes-from "$production:ro" \
  -v "$build_root/handoff-data:/data" \
  -v "$source_root/vvoice:/app/vvoice:ro" \
  -v "$source_root/catalog:/app/catalog:ro" \
  -v "$source_root/internal:/app/internal:ro" \
  -v "$build_root/vvoice-studio-arm64:/opt/vvoice/vvoice-studio:ro" \
  -p 127.0.0.1:22709:7070 \
  -e VVOICE_SCHEDULER_REQUIRED=true -e VVOICE_PROFILE=thor -e VVOICE_PROVIDER=cuda \
  -e VVOICE_NUM_THREADS=4 -e VVOICE_MAX_CONCURRENT_INFERENCE=1 \
  -e VVOICE_SCHEDULER_CONFIG=/data/scheduler.local.json \
  -e VVOICE_SCHEDULER_UPSTREAM_URL=http://v-voice-music-handoff-qa:7070/v1 \
  -e "VOS_USERINFO_URL=$userinfo" "$test_image"
