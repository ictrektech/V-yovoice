#!/usr/bin/env python3
"""同机 VOS 开发：共享权重及调度预算，挂载源码而不重建镜像。"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


APP_ID = "com.ictrek.v-voice.dev"
CONTROLLER = "http://127.0.0.1:38120/api/v1"
UPSTREAM = "http://127.0.0.1:22700/v1"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def request(token, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(CONTROLLER + path, data=data,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=10) as response:
            envelope = json.load(response)
    except urllib.error.HTTPError as error:
        # 只输出机器可读错误，不回显可能含凭据的响应正文。
        try:
            code = json.load(error).get("code", "UNKNOWN")
        except ValueError:
            code = "UNKNOWN"
        raise RuntimeError(f"Scheduler {path}: HTTP {error.code}, {code}") from None
    if envelope.get("code") != "OK":
        raise RuntimeError("Scheduler 接口未成功")
    return envelope["data"]


def private_json(path, value):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8))
    try:
        with open(temporary, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(value, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def local_endpoint(value):
    url = urllib.parse.urlsplit(value)
    local = {"127.0.0.1", "localhost", socket.gethostname()}
    local.update(docker_host_addresses())
    if (url.scheme != "http" or url.hostname not in local or url.port != 22700 or
            url.path not in ("", "/") or url.username or url.password or url.query or url.fragment):
        raise RuntimeError("本地语音模式的地址必须是本机 http://<IP>:22700；远程已有服务请设置 VVOICE_DEV_SPEECH=external")


def docker_host_addresses():
    return subprocess.check_output(["hostname", "-I"], text=True).split()


def development_binding(source, node_id):
    binding = copy.deepcopy(source["binding"])
    models = binding.get("models", {})
    if (set(models) != {"sensevoice-int8", "kokoro-multilang"} or
            binding.get("input_limits_version") != 1 or
            set(binding.get("model_limits", {})) != set(models) or
            any(binding.get("secondary_models", {}).values()) or
            binding.get("legacy_unbounded_models")):
        raise RuntimeError("当前开发启动器需要同机 Orin 的有界 SenseVoice/Kokoro 校准记录，不能自动扩大批准范围")
    originals = {row["id"]: row for row in source["executors"]}
    definitions = {}
    for model, old_id in models.items():
        original = originals[old_id]
        if (original["node_id"] != node_id or
                old_id != "v-voice.auto.orin-voice-native-bounded-v1.infer" or
                original["task_type"] != "model.infer"):
            raise RuntimeError("开发运行时与已校准执行节点不一致")
        executor = copy.deepcopy(original)
        executor.update(id=old_id.replace("v-voice.auto.", "v-voice.dev.", 1),
                        app_id=APP_ID, upstream_urls=[UPSTREAM])
        definitions[executor["id"]] = executor
        models[model] = executor["id"]
    binding.update(app_id=APP_ID, url=CONTROLLER, upstream_url=UPSTREAM,
                   gateway_executors={}, secondary_models={}, lifecycle_protocol_version=1)
    # 开发服务不能持有 VOS 应用或网关的旧凭据。
    binding.pop("token", None)
    binding.pop("executor_token", None)
    return binding, definitions


def prepare(state):
    local_endpoint(os.getenv("VITE_VOS_SPEECH_SERVICE_BASE", "http://127.0.0.1:22700"))
    if not Path("/etc/nv_tegra_release").is_file() or not Path("/etc/nv_tegra_release").read_text().startswith("# R36"):
        raise RuntimeError("本地运行时目前支持这台 Orin / JetPack 6；其他设备请使用已运行的 external 服务")
    controllers = docker("ps", "--filter", "label=com.docker.compose.service=controller-l4t", "--format", "{{.Names}}").splitlines()
    if len(controllers) != 1:
        raise RuntimeError("需要本机唯一运行的 V-Scheduler controller-l4t 容器")
    controller = controllers[0]
    inspect = json.loads(docker("inspect", controller))[0]
    model_root = next(Path(mount["Source"]) for mount in inspect["Mounts"] if mount["Destination"] == "/data")
    configuration = json.loads(docker("exec", controller, "cat", "/config/controller.json"))
    source = json.loads(docker("exec", controller, "cat", "/config/voice-binding.json"))
    binding, definitions = development_binding(source, configuration["local_agent"]["node_id"])
    images = docker("image", "ls", "--filter", "reference=swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice:l4t_*",
                    "--format", "{{.Repository}}:{{.Tag}}").splitlines()
    image = os.getenv("VVOICE_DEV_IMAGE") or (images[0] if images else "")
    if not image or image not in images:
        raise RuntimeError("缺少本机缓存的 V-Voice l4t 运行镜像；设置 VVOICE_DEV_IMAGE 选择已有镜像，不会自动拉取或重建")
    admin = next(item["token"] for item in configuration["principals"] if item["role"] == "admin")
    configure_scheduler(state, binding, definitions, admin)
    resources = next(iter(definitions.values()))["resources"]
    return image, model_root, resources


def configure_scheduler(state, binding, definitions, admin):
    overview = request(admin, "/management")
    existing = {row["id"]: row for row in overview["executors"]}
    for key, definition in definitions.items():
        if key in existing:
            row = existing[key]
            if row["state"] != "enabled" or any(row["definition"].get(k) != v for k, v in definition.items()):
                raise RuntimeError("已有开发执行器配置不一致，请在 Scheduler 检查后处理，启动器不会覆盖")
        else:
            request(admin, "/executors/" + key, {"version": 0, "enabled": True, "definition": definition})
    path = state / "scheduler.local.json"
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise RuntimeError("开发调度配置必须为普通私有文件（0600）")
        saved = json.loads(path.read_text())
        if any(saved.get(k) != v for k, v in binding.items()):
            raise RuntimeError("已保存的开发绑定与当前校准不同，请检查开发数据目录")
        allowed = request(saved["token"], "/executors")
        if not set(definitions).issubset({row["id"] for row in allowed}):
            raise RuntimeError("开发服务身份未获对应执行器权限")
    else:
        identity = request(admin, "/service-identities", {"app_id": APP_ID})
        binding.update(token=identity["token"], executor_token=secrets.token_hex(32))
        private_json(path, binding)


def main():
    state = Path(os.getenv("YOVOICE_DEV_DATA", "/tmp/yovoice-dev-data")).resolve()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state.stat().st_uid != os.getuid():
        raise RuntimeError("开发数据目录必须属于当前用户")
    state.chmod(0o700)
    image, model_root, resources = prepare(state)
    root = Path(__file__).resolve().parents[1]
    environment = {
        "VVOICE_APP_ID": APP_ID, "VVOICE_PROFILE": "l4t", "VVOICE_HOST": "127.0.0.1", "VVOICE_PORT": "22700",
        "VVOICE_STUDIO_ENABLED": "true", "VVOICE_SHARED_MODELS": "true", "VVOICE_SCHEDULER_REQUIRED": "true",
        "VVOICE_SCHEDULER_CONFIG": "/data/scheduler.local.json", "VVOICE_DATA_DIR": "/data",
        "VVOICE_STUDIO_DATA_DIR": "/data/studio", "VVOICE_STUDIO_DEV_TOKEN": os.environ["VVOICE_DEV_TOKEN"],
        "MODEL_HUB_SHARED_MODELS_PATH": "/modelhub", "MODEL_HUB_API_URL": "http://127.0.0.1:36005",
        "VVOICE_PROVIDER": "cuda", "VVOICE_NUM_THREADS": "4", "VVOICE_CPU_MODELS": "paraformer-zh",
        "VVOICE_MAX_CONCURRENT_INFERENCE": "2", "VVOICE_MAX_CONCURRENT_PER_MODEL": "2", "VVOICE_MAX_LOADED_MODELS": "2",
        "PYTHONPATH": "/workspace", "PYTHONDONTWRITEBYTECODE": "1", "NO_PROXY": "*", "no_proxy": "*",
    }
    # Docker 环境文件不含管理员令牌；开发提交身份只保存在私有 JSON 中。
    env_path = state / "runtime.env"
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in environment.items()))
    print("启动本地语音服务：共享 Scheduler 模型目录，独立开发调度身份，22700 仅监听本机。", flush=True)
    args = ["docker", "run", "--pull", "never", "--rm", "--init", "--name", f"vvoice-dev-{os.getuid()}",
        "--network", "host", "--runtime", "nvidia", "--env-file", str(env_path),
        "--memory", f"{resources['memory_mib']}m", "--memory-swap", f"{resources['memory_mib']}m",
        "--cpus", str(resources["cpu_millicores"] / 1000),
        "--mount", f"type=bind,src={root},dst=/workspace,readonly",
        "--mount", f"type=bind,src={root / '.local/dev/vvoice-studio'},dst=/opt/vvoice/vvoice-studio,readonly",
        "--mount", f"type=bind,src={state},dst=/data",
        "--mount", f"type=bind,src={model_root},dst=/modelhub,readonly",
        "--workdir", "/workspace", "--entrypoint", "python3", image, "-m", "vvoice.server"]
    os.execvp(args[0], args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        # 不回显 Docker inspect 或配置全文。
        print(f"本地语音服务启动失败：{error}", file=sys.stderr)
        sys.exit(1)
