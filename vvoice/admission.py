"""直接调用与 V-Router 转发共用的 V-Scheduler 准入边界。"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import gc
import json
import math
import os
import secrets
import threading
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException


current: contextvars.ContextVar[Execution | None] = contextvars.ContextVar("vvoice_execution", default=None)


def model_limits(model: str) -> dict | None:
    if os.getenv("VVOICE_SCHEDULER_REQUIRED") != "true":
        return None
    config = configuration()
    if "model_limits" not in config:
        if config.get("input_limits_version"):
            raise HTTPException(503, "Complete model input calibration required")
        return None
    if config.get("input_limits_version") != 1 or not isinstance(config["model_limits"], dict):
        raise HTTPException(503, "Input limit protocol required")
    limits = config["model_limits"].get(model)
    expected = ({"text_characters", "speed_min", "speed_max"} if model == "kokoro-multilang"
                else {"duration_seconds", "sample_rate", "hotwords_characters", "input_bytes"} if model == "sensevoice-int8" else set())
    if not isinstance(limits, dict) or not expected or set(limits) != expected:
        raise HTTPException(503, "Complete model input calibration required")
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (value == 0 and name != "hotwords_characters") for name, value in limits.items()):
        raise HTTPException(503, "Invalid model input calibration")
    if "speed_min" in limits and limits["speed_min"] > limits["speed_max"]:
        raise HTTPException(503, "Invalid calibrated speed range")
    execution = current.get()
    if execution is not None:
        if execution.validated_binding is not None and execution.validated_binding != config:
            raise HTTPException(503, "Input calibration changed; retry request")
        execution.validated_binding = config
    return limits


def validate_inputs(model: str, **values) -> None:
    limits = model_limits(model)
    if limits is None:
        return
    for name, value in values.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise HTTPException(422, "Invalid model input metric")
        if name == "speed":
            valid = limits.get("speed_min", math.inf) <= value <= limits.get("speed_max", -math.inf)
        else:
            valid = name in limits and value <= limits[name]
        if not valid:
            raise HTTPException(422, "Input exceeds calibrated model limits")


def configuration() -> dict:
    path = Path(os.getenv("VVOICE_SCHEDULER_CONFIG", "/data/scheduler.local.json"))
    try:
        if path.stat().st_mode & 0o077:
            raise HTTPException(503, "Scheduler configuration must be private (0600)")
        value = json.loads(path.read_text())
        if not value.get("url") or len(value.get("token", "")) < 32:
            raise ValueError("missing service identity")
        return value
    except (OSError, ValueError):
        raise HTTPException(503, "V-Scheduler configuration required") from None


def controller(config: dict, path: str, body: dict, key: str = "") -> dict:
    headers = {"Authorization": f"Bearer {config['token']}"}
    if key:
        headers["Idempotency-Key"] = key
    try:
        response = httpx.post(config["url"].rstrip("/") + path, json=body, headers=headers, timeout=8)
        if response.status_code == 429:
            raise HTTPException(429, "Local compute resources are busy", headers={"Retry-After": "1"})
        if response.status_code != 200:
            raise HTTPException(503, "Scheduler admission rejected")
        value = response.json()
        if value.get("code") != "OK":
            raise ValueError("invalid scheduler response")
        return value["data"]
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(503, "Scheduler admission unavailable") from None


class Execution:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers
        self.id = secrets.token_hex(16)
        self.lock = threading.RLock()
        self.config: dict = {}
        self.validated_binding: dict | None = None
        self.permit = ""
        self.model = ""
        self.executor = ""
        self.proof = ""
        self.owned = False
        self.ended = False
        self.workers = 0
        self.closed = False
        self.uncertain = False
        self.failed = False
        self.stop = threading.Event()

    def enter(self, model: str) -> None:
        with self.lock:
            if self.failed or self.closed or self.ended:
                raise HTTPException(503, "Compute lease is no longer valid")
            if self.permit:
                if model != self.model and model not in self.config.get("secondary_models", {}).get(self.model, []):
                    raise HTTPException(503, "Combined model budget is not approved")
                return
            self.config = configuration()
            if self.validated_binding is not None and self.validated_binding != self.config:
                raise HTTPException(503, "Input calibration changed; retry request")
            self.model = model
            inherited = self.headers.get("x-vscheduler-permit-id", "")
            proof = self.headers.get("x-vscheduler-execution-token", "")
            executor = self.headers.get("x-vscheduler-executor-id", "")
            if inherited or proof or executor:
                expected = self.config.get("gateway_executors", {}).get(model)
                if not inherited or len(proof) < 32 or not expected or executor != expected:
                    raise HTTPException(503, "Invalid gateway admission proof")
                self.permit, self.executor, self.proof = inherited, executor, proof
            else:
                self.executor = self.config.get("models", {}).get(model, "")
                if not self.executor:
                    raise HTTPException(503, "Model executor is not approved")
                self.proof = secrets.token_hex(32)
                reply = controller(self.config, "/permits", {
                    "executor_id": self.executor, "model_id": model,
                    "upstream_url": self.config["upstream_url"], "execution_token": self.proof,
                }, self.id)
                self.permit = str(reply.get("permit_id") or "")
                self.owned = True
            if not self.permit:
                raise HTTPException(503, "Invalid admission receipt")
            try:
                self.verify(claim=True)
            except Exception:
                # 未启动计算；自持许可可安全释放。网关许可仍由网关决定释放。
                if self.owned:
                    self._release(stopped=True)
                raise
            threading.Thread(target=self._watch, name="voice-permit", daemon=True).start()

    def verify(self, claim: bool = False) -> None:
        result = controller(self.config, f"/permits/{self.permit}/verify", {
            "executor_id": self.executor, "upstream_url": self.config["upstream_url"],
            "model_id": self.model, "execution_token": self.proof,
            "execution_id": self.id, "claim": claim,
        })
        if result.get("state") != "active" or result.get("lease_seconds", 0) < 1:
            raise HTTPException(503, "Compute lease expired")

    def _watch(self) -> None:
        while not self.stop.wait(5):
            try:
                if self.owned:
                    controller(self.config, f"/permits/{self.permit}/renew", {})
                self.verify()
            except Exception:
                # 当前同步原生调用不能凭连接断开判定停止，保留预约为 suspect。
                with self.lock:
                    self.failed = True
                return

    def _release(self, stopped: bool) -> None:
        try:
            controller(self.config, f"/permits/{self.permit}/release", {
                "stopped": stopped,
                "evidence": "vvoice_compute_completed_and_runtime_unloaded" if stopped else "vvoice_stop_not_confirmed",
            })
        except HTTPException:
            # 调度器继续保留预约，不伪造释放成功。
            pass

    def worker_started(self) -> None:
        with self.lock:
            self.workers += 1

    def worker_finished(self, _: Any = None) -> None:
        with self.lock:
            self.workers -= 1
        self.finish_if_stopped()

    def end(self) -> None:
        with self.lock:
            self.ended = True
        self.finish_if_stopped()

    def finish_if_stopped(self) -> None:
        with self.lock:
            if not self.ended or self.workers or self.closed:
                return
            self.closed = True
            self.stop.set()
            if not self.permit:
                return
        # 当前任务线程已经返回；清理缓存后才确认无跨任务驻留占用。
        from .runtime import registry
        registry.unload()
        gc.collect()
        if self.owned:
            self._release(stopped=not self.uncertain)


async def run_blocking(func, /, *args, **kwargs):
    execution = current.get()
    if execution is None:
        return await asyncio.to_thread(func, *args, **kwargs)
    execution.worker_started()
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    future = loop.run_in_executor(None, context.run, functools.partial(func, *args, **kwargs))
    future.add_done_callback(execution.worker_finished)
    # 客户端断开不取消底层 Future；真实线程退出后才确认停止。
    return await asyncio.shield(future)


async def admit_model(model: str) -> None:
    if os.getenv("VVOICE_SCHEDULER_REQUIRED") != "true":
        return
    execution = current.get()
    if execution is None:
        raise HTTPException(503, "Inference requires a scheduled request context")
    await run_blocking(execution.enter, model)


class AdmissionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        execution = Execution({key.decode().lower(): value.decode() for key, value in scope.get("headers", [])})
        received_bytes = 0

        async def guarded_receive():
            nonlocal received_bytes
            message = await receive()
            if scope["type"] == "http" and scope.get("path") in {"/transcribe", "/v1/audio/transcriptions", "/v1/audio/translations", "/v1/audio/speech"}:
                config = configuration()
                if "model_limits" in config:
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > 1048576 + 65536:
                        raise HTTPException(413, "Request exceeds calibrated upload limit")
            return message
        token = current.set(execution)
        closing = None

        async def finish_response():
            while execution.workers:
                await asyncio.sleep(0.02)
            await asyncio.to_thread(execution.end)

        async def guarded_send(message):
            nonlocal closing
            if message["type"] == "websocket.close":
                # 等处理函数真正退出、释放识别器引用后才发送停止确认关闭帧。
                closing = message
                return
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                await finish_response()
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        finally:
            current.reset(token)
            await asyncio.to_thread(execution.end)
        if closing is not None:
            await finish_response()
            await send(closing)
