from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import secrets
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import admission
from .config import Settings, settings

logger = logging.getLogger(__name__)

MODEL_KEY = "haru-4b-q8"
FRAME_SECONDS = 3200 / 24000


def _state_path(data_dir: Path) -> Path:
    return data_dir / "dialogue" / "residency.json"


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(f".{secrets.token_hex(8)}.pending")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except (OSError, TypeError, ValueError):
        with contextlib.suppress(OSError):
            os.close(descriptor)
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _read_state(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_mode & 0o077:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _process_start_ticks(pid: int) -> int:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        end = raw.rfind(")")
        if end < 0:
            return 0
        fields = raw[end + 2 :].split()
        return int(fields[19])
    except (OSError, ValueError, IndexError):
        return 0


def _process_alive(pid: int) -> bool:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        end = raw.rfind(")")
        return end >= 0 and raw[end + 2 :].split()[0] not in {"Z", "X"}
    except (OSError, ValueError, IndexError):
        return False


def _is_haru_worker(pid: int, start_ticks: int, model: Path) -> bool:
    if pid <= 0 or (start_ticks and _process_start_ticks(pid) != start_ticks):
        return False
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            errors="replace"
        )
    except OSError:
        return False
    return (
        "speechcpp/speech" in command
        and " worker " in f" {command} "
        and str(model) in command
    )


def _stop_process_group(pid: int) -> bool:
    if pid <= 0:
        return True
    for sig, wait_seconds in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return True
        except OSError:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, sig)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if not _process_alive(pid):
                return True
            time.sleep(0.1)
    return not _process_alive(pid)
PERSONAS: dict[str, dict[str, dict[str, str]]] = {
    "companion": {
        "zh": {
            "name": "小语",
            "persona": "温暖、自然、简洁的聊天伙伴，先倾听再回应。",
            "situation": "和用户在设备上轻松聊天。",
        },
        "en": {
            "name": "Haru",
            "persona": "A warm, natural and concise conversation partner who listens before answering.",
            "situation": "A relaxed voice chat with the user on this device.",
        },
    },
    "study": {
        "zh": {
            "name": "小习",
            "persona": "耐心的中英文学习伙伴，用短句解释并鼓励用户开口。",
            "situation": "用户正在练习语言表达。",
        },
        "en": {
            "name": "Milo",
            "persona": "A patient language practice partner who explains briefly and encourages the user to speak.",
            "situation": "The user is practising spoken language.",
        },
    },
    "interview": {
        "zh": {
            "name": "面试官",
            "persona": "友好的面试练习伙伴，提出清晰问题并给出简短反馈。",
            "situation": "用户正在准备一场面试。",
        },
        "en": {
            "name": "Alex",
            "persona": "A friendly interview practice partner who asks clear questions and gives short feedback.",
            "situation": "The user is preparing for an interview.",
        },
    },
}


class DialogueError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Identity:
    subject: str
    role: str


@dataclass(frozen=True)
class Ticket:
    user: str
    language: str
    persona_id: str
    max_seconds: int
    expires_at: float = 0.0


class TicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def issue(self, user: str, language: str, persona_id: str, max_seconds: int) -> tuple[str, float]:
        self._purge()
        ticket = secrets.token_urlsafe(32)
        expires = time.time() + 300
        self._tickets[self._digest(ticket)] = Ticket(
            user=user,
            language=language,
            persona_id=persona_id,
            max_seconds=max_seconds,
            expires_at=expires,
        )
        return ticket, expires

    def consume(self, ticket: str, user: str | None = None) -> Ticket:
        self._purge()
        value = self._tickets.pop(self._digest(ticket), None)
        if value is None or (user is not None and value.user != user) or value.expires_at < time.time():
            raise DialogueError(401, "ticket_invalid", "Dialogue ticket is invalid or expired")
        return value

    def _purge(self) -> None:
        now = time.time()
        for key, value in list(self._tickets.items()):
            if value.expires_at < now:
                self._tickets.pop(key, None)


class WorkerClosed(Exception):
    pass


class SpeechWorker:
    def __init__(self, manager: DialogueManager, path: Path, model: Path):
        self.manager = manager
        self.path = path
        self.model = model
        self.process: asyncio.subprocess.Process | None = None
        self.ready: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.reader_task: asyncio.Task | None = None
        self.stderr_task: asyncio.Task | None = None
        self.write_lock = asyncio.Lock()
        self.closed = False
        self.expected_close = False

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            str(self.path),
            "worker",
            str(self.model),
            "--device",
            "CUDA0",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self.reader_task = asyncio.create_task(self._read_stdout())
        self.stderr_task = asyncio.create_task(self._read_stderr())
        try:
            ready = await asyncio.wait_for(self.ready, 30)
        except asyncio.TimeoutError:
            await self.stop()
            raise WorkerClosed("Haru worker did not become ready in 30 seconds") from None
        if ready.get("model", {}).get("task") != "dialogue":
            await self.stop()
            raise WorkerClosed("Haru worker returned the wrong task")

    async def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self.manager._worker_failed("Haru worker emitted invalid JSONL")
                    return
                if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                    await self.manager._worker_failed("Haru worker emitted an invalid message")
                    return
                if not self.ready.done():
                    if value["type"] == "ready":
                        self.ready.set_result(value)
                    elif value["type"] == "fatal":
                        self.ready.set_exception(WorkerClosed(str(value.get("error", {}).get("message", "worker fatal"))))
                        continue
                    else:
                        self.ready.set_exception(WorkerClosed("Haru worker sent a message before ready"))
                    continue
                await self.manager._worker_message(value)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.manager._worker_failed("Haru worker output failed")
        finally:
            if not self.ready.done():
                self.ready.set_exception(WorkerClosed("Haru worker exited before ready"))
            if not self.manager.closing and not self.expected_close:
                await self.manager._worker_failed("Haru worker exited unexpectedly")

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    return
                logger.debug("haru worker: %s", line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def send(self, value: dict[str, Any]) -> None:
        if self.closed or not self.process or not self.process.stdin:
            raise WorkerClosed("Haru worker is not running")
        data = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        async with self.write_lock:
            self.process.stdin.write(data)
            await self.process.stdin.drain()

    async def stop(self) -> bool:
        if self.closed:
            return True
        self.closed = True
        self.expected_close = True
        process = self.process
        if process is None:
            return True
        if process.stdin and not process.stdin.is_closing():
            with contextlib.suppress(Exception):
                process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                with contextlib.suppress(Exception):
                    await process.wait()
        current = asyncio.current_task()
        for task in (self.reader_task, self.stderr_task):
            if task:
                if task is current:
                    continue
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return process.returncode is not None


class ResidentLease:
    def __init__(self, manager: DialogueManager, config: dict[str, Any]):
        self.manager = manager
        self.config = config
        mapping = config.get("dialogue_models") or config.get("models") or {}
        self.executor = str(mapping.get(MODEL_KEY) or "")
        self.upstream = str(config.get("upstream_url") or "")
        self.permit = ""
        self.proof = secrets.token_hex(32)
        self.execution_id = secrets.token_hex(16)
        self.renew_task: asyncio.Task | None = None
        self.lost = False
        self.worker_pid = 0
        self.worker_start_ticks = 0
        self.state_path = manager._state_path()

    def persist(self) -> None:
        _write_state(
            self.state_path,
            {
                "version": 1,
                "permit_id": self.permit,
                "executor_id": self.executor,
                "upstream_url": self.upstream,
                "model_id": MODEL_KEY,
                "worker_pid": self.worker_pid,
                "worker_start_ticks": self.worker_start_ticks,
                "updated_at": time.time(),
            },
        )

    def set_worker(self, pid: int) -> None:
        if pid <= 0:
            raise OSError("invalid Haru worker pid")
        self.worker_pid = pid
        self.worker_start_ticks = _process_start_ticks(pid)
        self.persist()

    def clear_state(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.state_path.unlink()
        with contextlib.suppress(OSError):
            self.state_path.parent.rmdir()

    async def acquire(self) -> None:
        if not self.executor or not self.upstream:
            raise DialogueError(503, "model_unavailable", "Haru executor is not approved")
        body = {
            "executor_id": self.executor,
            "model_id": MODEL_KEY,
            "upstream_url": self.upstream,
            "execution_token": self.proof,
            "scheduling": {"priority": "interactive"},
        }
        try:
            reply = await asyncio.to_thread(
                admission.controller,
                self.config,
                "/permits",
                body,
                secrets.token_hex(16),
                "",
                {"x-vscheduler-queue-wait-seconds": "0"},
            )
            self.permit = str(reply.get("permit_id") or "")
            if not self.permit:
                raise ValueError("missing permit")
            try:
                self.persist()
            except OSError:
                await self.release(True, "haru_lease_not_persisted")
                raise DialogueError(503, "scheduler_unavailable", "Haru lease could not be persisted") from None
            await asyncio.to_thread(
                admission.controller,
                self.config,
                f"/permits/{self.permit}/verify",
                {
                    "executor_id": self.executor,
                    "upstream_url": self.upstream,
                    "model_id": MODEL_KEY,
                    "execution_token": self.proof,
                    "execution_id": self.execution_id,
                    "claim": True,
                },
            )
        except HTTPException as exc:
            if self.permit:
                await self.release(True, "haru_worker_not_started")
            raise DialogueError(exc.status_code, "dialogue_capacity_unavailable", str(exc.detail)) from None
        except Exception:
            if self.permit:
                await self.release(True, "haru_worker_not_started")
            raise DialogueError(503, "scheduler_unavailable", "V-Scheduler admission unavailable") from None
        self.renew_task = asyncio.create_task(self._renew())

    async def _renew(self) -> None:
        while not self.lost:
            await asyncio.sleep(5)
            try:
                await asyncio.to_thread(
                    admission.controller,
                    self.config,
                    f"/permits/{self.permit}/renew",
                    {},
                )
            except Exception:
                self.lost = True
                await self.manager._lease_lost()
                return

    async def release(self, stopped: bool, evidence: str) -> None:
        if self.renew_task and self.renew_task is not asyncio.current_task():
            self.renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.renew_task
        if not self.permit:
            self.clear_state()
            return
        released = False
        try:
            await asyncio.to_thread(
                admission.controller,
                self.config,
                f"/permits/{self.permit}/release",
                {"stopped": stopped, "evidence": evidence[:512]},
            )
            released = True
        except Exception:
            logger.warning("Haru residency lease release was not confirmed")
        if released:
            self.clear_state()
        self.permit = ""


class DialogueSession:
    def __init__(
        self,
        manager: DialogueManager,
        session_id: str,
        language: str,
        persona_id: str,
        max_seconds: int,
    ):
        self.manager = manager
        self.id = session_id
        self.language = language
        self.persona_id = persona_id
        self.max_seconds = max_seconds
        self.events: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self.sequence = 0
        self.frames = 0
        self.input_started: float | None = None
        self.output_started: float | None = None
        self.output_frames = 0
        self.last_activity = time.monotonic()
        self.hangup = False
        self.ended = False
        self.monitor_task: asyncio.Task | None = None

    async def start(self) -> None:
        persona = PERSONAS[self.persona_id][self.language]
        await self.manager.worker.send(
            {
                "type": "dialogue",
                "id": self.id,
                "sample_rate": 24000,
                "language": self.language,
                "max_seconds": self.max_seconds,
                **persona,
            }
        )
        self.monitor_task = asyncio.create_task(self._monitor())

    async def push(self, pcm: bytes) -> None:
        if self.hangup or self.ended:
            raise DialogueError(1008, "session_closed", "Conversation has ended")
        if self.input_started is None:
            self.input_started = time.monotonic()
            self.output_frames_since_input = 0
        encoded = base64.b64encode(pcm).decode()
        await self.manager.worker.send(
            {"type": "chunk", "id": self.id, "seq": self.sequence, "pcm": encoded}
        )
        self.sequence += 1
        self.last_activity = time.monotonic()

    async def hang_up(self) -> None:
        if self.hangup or self.ended:
            return
        self.hangup = True
        await self.manager.worker.send({"type": "hang_up", "id": self.id})

    async def cancel(self) -> None:
        if self.hangup or self.ended:
            return
        self.hangup = True
        with contextlib.suppress(Exception):
            await self.manager.worker.send({"type": "cancel", "id": self.id})
            await self.manager.worker.send({"type": "hang_up", "id": self.id})

    async def on_chunk(self, value: dict[str, Any]) -> None:
        now = time.monotonic()
        self.last_activity = now
        if self.input_started is not None and self.output_started is None:
            self.output_started = now
        if self.output_started is not None:
            self.output_frames += 1
        text = value.get("text")
        if isinstance(text, str) and text:
            await self.events.put(("text", text))
        pcm = value.get("pcm")
        if isinstance(pcm, str):
            try:
                audio = base64.b64decode(pcm, validate=True)
            except ValueError:
                await self.events.put(("error", ("worker_failed", "Invalid audio frame")))
                return
            self.frames += 1
            await self.events.put(("audio", audio))

    async def on_end(self, value: dict[str, Any]) -> None:
        if self.ended:
            return
        self.ended = True
        await self.events.put(("end", value))
        await self.manager._session_finished(self)

    async def on_error(self, code: str, message: str) -> None:
        if self.ended:
            return
        self.ended = True
        await self.events.put(("error", (code, message)))
        await self.manager._session_finished(self, failed=True)

    async def _monitor(self) -> None:
        while not self.ended:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            if now - self.last_activity >= self.manager.config.dialogue_idle_session_seconds:
                self.ended = True
                await self.events.put(("end", {"reason": "idle"}))
                await self.manager._session_finished(self)
                return
            if self.output_started is not None and not self.hangup:
                expected = self.output_frames * FRAME_SECONDS
                if now - self.output_started > expected + 1.0:
                    self.ended = True
                    await self.events.put(
                        ("error", ("dialogue_overloaded", "Conversation fell more than one second behind"))
                    )
                    await self.manager._session_failed(self)
                    return


class DialogueManager:
    def __init__(self, config: Settings = settings):
        self.config = config
        self.tickets = TicketStore()
        self.state = "unloaded"
        self.error = ""
        self.worker: SpeechWorker | None = None
        self.lease: ResidentLease | None = None
        self.session: DialogueSession | None = None
        self._lock = asyncio.Lock()
        self._load_task: asyncio.Task | None = None
        self._idle_task: asyncio.Task | None = None
        self._closing = False
        self._failed = False
        self._recovered = False

    @property
    def closing(self) -> bool:
        return self._closing

    @property
    def supported(self) -> bool:
        return self.config.profile == "l4t" and self.config.haru_worker_path.is_file()

    @property
    def model_installed(self) -> bool:
        try:
            return self.config.haru_model_path.is_file() and self.config.haru_model_path.stat().st_size == 6623102720
        except OSError:
            return False

    def idle_unload_seconds(self) -> int:
        path = self._settings_path()
        try:
            value = json.loads(path.read_text()).get("idle_unload_seconds")
            if isinstance(value, int) and 0 <= value <= 600:
                return value
        except (OSError, ValueError, TypeError):
            pass
        return self.config.dialogue_idle_unload_seconds

    def _settings_path(self) -> Path:
        return self.config.data_dir / "dialogue" / "settings.json"

    def _state_path(self) -> Path:
        return _state_path(self.config.data_dir)

    def _clear_state(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._state_path().unlink()
        with contextlib.suppress(OSError):
            self._state_path().parent.rmdir()

    def save_idle_seconds(self, value: int) -> None:
        if not 0 <= value <= 600:
            raise DialogueError(422, "invalid_setting", "idle_unload_seconds must be 0..600")
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{secrets.token_hex(8)}.pending")
        temporary.write_text(json.dumps({"idle_unload_seconds": value}))
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    async def recover(self) -> None:
        """Clean a worker and lease left by a previous application process."""
        async with self._lock:
            if self._recovered:
                return
            self._recovered = True
            state = _read_state(self._state_path())
            if state is None:
                return
            pid = state.get("worker_pid")
            if isinstance(pid, int) and pid > 0:
                start_ticks = state.get("worker_start_ticks")
                if _is_haru_worker(
                    pid,
                    start_ticks if isinstance(start_ticks, int) else 0,
                    self.config.haru_model_path,
                ):
                    if not _stop_process_group(pid):
                        logger.warning("recovered Haru worker pid=%s did not stop; keeping lease", pid)
                        self._recovered = False
                        return
                    logger.warning("recovered orphaned Haru worker pid=%s", pid)
            permit = state.get("permit_id")
            if not isinstance(permit, str) or not permit:
                self._clear_state()
                return
            try:
                config = await asyncio.to_thread(admission.configuration)
                await asyncio.to_thread(
                    admission.controller,
                    config,
                    f"/permits/{permit}/release",
                    {"stopped": True, "evidence": "haru_orphan_recovered"},
                )
            except Exception:
                logger.warning("recovered Haru lease could not be released; keeping state")
                self._recovered = False
                return
            self._clear_state()

    async def ensure_loaded(self) -> None:
        await self.recover()
        async with self._lock:
            if self.state == "active":
                raise DialogueError(409, "dialogue_busy", "A Haru conversation is already active")
            if self.state in {"loading", "unloading"}:
                task = self._load_task if self.state == "loading" else None
                if task is None:
                    raise DialogueError(409, "dialogue_busy", "Haru is changing state")
            elif self.state == "ready_idle" and self.worker and not self.worker.closed:
                return
            else:
                if not self.supported:
                    raise DialogueError(503, "model_unavailable", "Haru is unavailable on this profile")
                if not self.model_installed:
                    raise DialogueError(503, "model_unavailable", "Haru model is not installed")
                self.state = "loading"
                self.error = ""
                task = asyncio.create_task(self._load())
                self._load_task = task
        await task

    async def _load(self) -> None:
        self._failed = False
        lease: ResidentLease | None = None
        worker: SpeechWorker | None = None
        try:
            if os.getenv("VVOICE_SCHEDULER_REQUIRED") == "true":
                config = await asyncio.to_thread(admission.configuration)
                lease = ResidentLease(self, config)
                await lease.acquire()
            worker = SpeechWorker(self, self.config.haru_worker_path, self.config.haru_model_path)
            await worker.start()
            if lease is not None:
                if worker.process is None:
                    raise WorkerClosed("Haru worker process is unavailable")
                lease.set_worker(worker.process.pid)
            async with self._lock:
                self.lease = lease
                self.worker = worker
                self.state = "ready_idle"
        except Exception as exc:
            if worker is not None:
                await worker.stop()
            if lease is not None:
                await lease.release(False, "haru_worker_start_failed")
            async with self._lock:
                self.worker = None
                self.lease = None
                self.state = "error"
                self.error = str(exc)
            raise DialogueError(503, "model_start_failed", "Haru worker could not start") from None

    def _start_idle_timer(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_after())

    async def _idle_after(self) -> None:
        seconds = self.idle_unload_seconds()
        if seconds == 0:
            await self._unload_if_idle()
            return
        await asyncio.sleep(seconds)
        await self._unload_if_idle()

    async def _unload_if_idle(self) -> None:
        async with self._lock:
            if self.state != "ready_idle" or self.session is not None:
                return
            self.state = "unloading"
        await self._stop_worker()

    async def _stop_worker(self, stopped: bool = True, evidence: str = "haru_idle_unload") -> None:
        worker = self.worker
        lease = self.lease
        self.worker = None
        self.lease = None
        confirmed = stopped
        if worker:
            try:
                confirmed = await worker.stop() and stopped
            except Exception:
                logger.exception("Haru worker stop failed")
                confirmed = False
        if lease:
            try:
                await lease.release(confirmed, evidence)
            except Exception:
                logger.exception("Haru residency lease release failed")
        else:
            self._clear_state()
        async with self._lock:
            self.state = "unloaded" if confirmed else "error"
            if not confirmed:
                self.error = "Haru worker stop was not confirmed"

    async def open_session(self, kind: Ticket) -> DialogueSession:
        await self.ensure_loaded()
        async with self._lock:
            if self.state != "ready_idle" or self.session is not None:
                raise DialogueError(409, "dialogue_busy", "A Haru conversation is already active")
            self.session = DialogueSession(
                self,
                secrets.token_hex(16),
                kind.language,
                kind.persona_id,
                kind.max_seconds,
            )
            self.state = "active"
            if self._idle_task:
                self._idle_task.cancel()
                self._idle_task = None
            session = self.session
        try:
            await session.start()
            return session
        except Exception:
            await self._session_finished(session, failed=True)
            raise DialogueError(503, "model_start_failed", "Haru conversation could not start") from None

    async def _session_finished(self, session: DialogueSession, failed: bool = False) -> None:
        if session.monitor_task:
            session.monitor_task.cancel()
        async with self._lock:
            if self.session is session:
                self.session = None
                if self.state == "active":
                    self.state = "error" if failed else "ready_idle"
                    if failed:
                        self.error = "Haru conversation failed"
        if failed:
            await self._stop_worker(True, "haru_session_failed")
        elif self.state == "ready_idle":
            self._start_idle_timer()

    async def _session_failed(self, session: DialogueSession) -> None:
        await self._session_finished(session, failed=True)

    async def _worker_message(self, value: dict[str, Any]) -> None:
        session = self.session
        if session is None or value.get("id") != session.id:
            return
        kind = value.get("type")
        if kind == "chunk":
            await session.on_chunk(value)
        elif kind == "end":
            await session.on_end(value)
        elif kind == "error":
            error = value.get("error") or {}
            await session.on_error(str(error.get("code") or "internal"), str(error.get("message") or "Haru failed"))
        elif kind == "cancelled":
            await session.on_end({"reason": "cancelled", "frames": session.frames})

    async def _worker_failed(self, message: str) -> None:
        if self._failed:
            return
        self._failed = True
        session = self.session
        if session:
            await session.on_error("worker_failed", message)
        async with self._lock:
            self.error = message
            if self.state == "ready_idle":
                self.state = "error"
        await self._stop_worker(True, "haru_worker_exited")

    async def _lease_lost(self) -> None:
        session = self.session
        if session:
            await session.on_error("lease_lost", "Haru residency lease was lost")
        await self._stop_worker(True, "haru_lease_lost")

    async def close(self) -> None:
        self._closing = True
        if self._idle_task:
            self._idle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_task
        session = self.session
        if session:
            await session.cancel()
        await self._stop_worker(True, "haru_application_shutdown")


async def _verify_user(request: Request) -> Identity:
    if not settings.vos_userinfo_url:
        raise HTTPException(503, "VOS identity endpoint is unavailable")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "VOS sign-in required")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(settings.vos_userinfo_url, headers={"Authorization": auth})
        if response.status_code != 200:
            raise ValueError
        value = response.json()
        subject, role = str(value.get("sub") or ""), str(value.get("role_code") or "")
        if not subject or value.get("enable") != 1:
            raise ValueError
    except (httpx.HTTPError, ValueError, AttributeError):
        raise HTTPException(401, "VOS sign-in rejected") from None
    return Identity(subject=subject, role=role)


def _admin(identity: Identity) -> bool:
    return identity.role in {"system_admin", "platform_admin"}


class TicketRequest(BaseModel):
    language: str = Field(pattern="^(zh|en)$")
    persona_id: str = Field(pattern="^(companion|study|interview)$")
    max_seconds: int = Field(ge=1, le=300)


class IdleSetting(BaseModel):
    idle_unload_seconds: int = Field(ge=0, le=600)


manager = DialogueManager()
router = APIRouter(prefix="/api/v1/dialogue", tags=["Realtime dialogue"])


@router.get("/status")
async def dialogue_status(request: Request):
    await _verify_user(request)
    model = {
        "key": MODEL_KEY,
        "name": "Haru-4B Q8_0",
        "languages": ["zh", "en"],
    }
    return {
        "supported": manager.supported,
        "model_installed": manager.model_installed,
        "state": manager.state if manager.supported else "unavailable",
        "busy": manager.state in {"loading", "active", "unloading"},
        "idle_unload_seconds": manager.idle_unload_seconds(),
        "model": model,
    }


@router.post("/tickets")
async def dialogue_ticket(request: Request, body: TicketRequest):
    identity = await _verify_user(request)
    if not manager.supported:
        raise HTTPException(503, "Haru is unavailable on this profile")
    if not manager.model_installed:
        raise HTTPException(503, "Haru model is not installed")
    if manager.state in {"loading", "active", "unloading"}:
        raise HTTPException(409, "A Haru conversation is already active")
    ticket, expires = manager.tickets.issue(
        identity.subject, body.language, body.persona_id, body.max_seconds
    )
    return {"ticket": ticket, "expires_at": expires, "ws_path": "/api/v1/dialogue/ws"}


@router.get("/settings")
async def dialogue_settings(request: Request):
    await _verify_user(request)
    return {"idle_unload_seconds": manager.idle_unload_seconds()}


@router.put("/settings")
async def update_dialogue_settings(request: Request, body: IdleSetting):
    identity = await _verify_user(request)
    if not _admin(identity):
        raise HTTPException(403, "Administrator access required")
    manager.save_idle_seconds(body.idle_unload_seconds)
    return {"idle_unload_seconds": manager.idle_unload_seconds()}


def _origin_ok(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    host = websocket.headers.get("host", "")
    return bool(host) and origin.split("://", 1)[-1].split("/", 1)[0] == host


@router.websocket("/ws")
async def dialogue_websocket(websocket: WebSocket, ticket: str = ""):
    if not _origin_ok(websocket):
        await websocket.close(code=1008)
        return
    try:
        admission_ticket = manager.tickets.consume(ticket)
    except (DialogueError, HTTPException):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session: DialogueSession | None = None
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=15)
        value = json.loads(first)
        if value != {"type": "start", "protocol": 1}:
            raise DialogueError(1008, "protocol", "Expected start protocol 1")
        if manager.state == "unloaded":
            await websocket.send_json({"type": "loading", "phase": "model"})
        session = await manager.open_session(admission_ticket)
        await websocket.send_json(
            {
                "type": "started",
                "protocol": 1,
                "sample_rate": 24000,
                "frame_samples": 3200,
                "max_seconds": admission_ticket.max_seconds,
            }
        )

        async def send_events() -> None:
            assert session is not None
            while True:
                kind, value = await session.events.get()
                if kind == "audio":
                    await websocket.send_bytes(value)
                elif kind == "text":
                    await websocket.send_json({"type": "text", "text": value})
                elif kind == "end":
                    await websocket.send_json(
                        {"type": "end", "reason": value.get("reason", "complete"), "frames": session.frames}
                    )
                    await websocket.close(code=1000)
                    return
                elif kind == "error":
                    code, message = value
                    await websocket.send_json({"type": "error", "code": code, "message": message})
                    await websocket.close(code=1011)
                    return

        sender = asyncio.create_task(send_events())
        received = 0
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                if session.hangup:
                    continue
                received += len(message["bytes"])
                if received > settings.dialogue_max_input_bytes:
                    await session.on_error("input_too_large", "Dialogue input exceeds the limit")
                    break
                await session.push(message["bytes"])
            elif message.get("text") is not None:
                value = json.loads(message["text"])
                if value == {"type": "hang_up"}:
                    await session.hang_up()
                else:
                    raise DialogueError(1008, "protocol", "Unexpected dialogue message")
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
    except (DialogueError, HTTPException) as exc:
        code = exc.code if isinstance(exc, DialogueError) else "http_error"
        message = exc.message if isinstance(exc, DialogueError) else str(exc.detail)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "code": code, "message": message})
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    except (WebSocketDisconnect, asyncio.TimeoutError, json.JSONDecodeError, KeyError):
        with contextlib.suppress(Exception):
            await websocket.close(code=1008)
    finally:
        if session:
            await session.cancel()


async def _verify_user_websocket(websocket: WebSocket) -> Identity:
    if not settings.vos_userinfo_url:
        raise HTTPException(503, "VOS identity endpoint is unavailable")
    auth = websocket.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "VOS sign-in required")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(settings.vos_userinfo_url, headers={"Authorization": auth})
        if response.status_code != 200:
            raise ValueError
        value = response.json()
        subject = str(value.get("sub") or "")
        if not subject or value.get("enable") != 1:
            raise ValueError
        return Identity(subject, str(value.get("role_code") or ""))
    except (httpx.HTTPError, ValueError, AttributeError):
        raise DialogueError(401, "unauthorized", "VOS sign-in rejected") from None
