"""Reusable process boundary for potentially non-terminating SymPy work."""

from __future__ import annotations

import multiprocessing
import queue
import time
import uuid
from collections.abc import Callable
from multiprocessing.context import BaseContext
from typing import Any

from texada.cas.model import CASResult
from texada.cas.policy import POLICY_VERSION, compare_expressions

WorkerTarget = Callable[[Any, Any], None]


class CASWorkerTimeout(TimeoutError):
    """Raised after the worker is killed and reset following a deadline."""


class CASWorkerError(RuntimeError):
    """Raised when the isolated worker cannot complete a request."""


class CASWorkerMemoryExceeded(RuntimeError):
    """Raised after a worker exceeds its parent-observed RSS budget."""

    def __init__(self, *, peak_rss_bytes: int, limit_bytes: int):
        self.peak_rss_bytes = peak_rss_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"CAS worker RSS {peak_rss_bytes} exceeded limit {limit_bytes} bytes and was restarted"
        )


class CASWorker:
    """Keep SymPy warm; kill and recreate the process after any timeout."""

    def __init__(
        self,
        *,
        timeout_ms: int = 1000,
        startup_timeout_ms: int = 10_000,
        max_rss_bytes: int | None = 512 * 1024**2,
        rss_poll_interval_ms: int = 50,
        context: BaseContext | None = None,
        target: WorkerTarget | None = None,
    ):
        if timeout_ms <= 0 or startup_timeout_ms <= 0 or rss_poll_interval_ms <= 0:
            raise ValueError("worker timeouts must be positive")
        if max_rss_bytes is not None and max_rss_bytes <= 0:
            raise ValueError("worker RSS limit must be positive or None")
        self.timeout_ms = timeout_ms
        self.startup_timeout_ms = startup_timeout_ms
        self.max_rss_bytes = max_rss_bytes
        self.rss_poll_interval_ms = rss_poll_interval_ms
        self.context = context or multiprocessing.get_context("spawn")
        self.target = target or _worker_main
        self._process: Any | None = None
        self._inbox: Any | None = None
        self._outbox: Any | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def compare(
        self,
        lhs: Any,
        rhs: Any,
        *,
        assumptions: list[str] | None = None,
        timeout_ms: int | None = None,
        seed: int = 0,
    ) -> CASResult:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("CAS seed must be an integer")
        self._ensure_started()
        worker_pid = self.pid
        request_id = uuid.uuid4().hex
        self._inbox.put(
            {
                "id": request_id,
                "operation": "compare",
                "lhs": lhs,
                "rhs": rhs,
                "assumptions": assumptions or [],
                "seed": seed,
            }
        )
        deadline_ms = timeout_ms or self.timeout_ms
        try:
            payload, peak_rss_bytes = self._receive(request_id, deadline_ms)
        except queue.Empty as exc:
            self._reset(force=True)
            raise CASWorkerTimeout(
                f"CAS worker exceeded {deadline_ms} ms and was restarted"
            ) from exc
        except CASWorkerMemoryExceeded:
            self._reset(force=True)
            raise
        if not payload.get("ok"):
            error = str(payload.get("error") or "unknown worker error")
            self._reset(force=True)
            raise CASWorkerError(error)
        result = CASResult.from_dict(payload["result"])
        result.seed = seed if result.seed is None else result.seed
        result.observation.setdefault("worker_pid", worker_pid)
        result.observation.setdefault("peak_rss_bytes", peak_rss_bytes)
        result.observation.setdefault("rss_monitor", "parent_pid_psutil")
        return result

    def close(self) -> None:
        self._reset(force=False)

    def __enter__(self) -> CASWorker:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._reset(force=True)
        self._inbox = self.context.Queue()
        self._outbox = self.context.Queue()
        self._process = self.context.Process(
            target=self.target,
            args=(self._inbox, self._outbox),
            daemon=True,
            name="texada-cas-worker",
        )
        self._process.start()
        try:
            ready = self._outbox.get(timeout=self.startup_timeout_ms / 1000)
        except queue.Empty as exc:
            self._reset(force=True)
            raise CASWorkerError(
                f"CAS worker did not become ready within {self.startup_timeout_ms} ms"
            ) from exc
        if not ready.get("ready"):
            error = str(ready.get("error") or "CAS worker failed during startup")
            self._reset(force=True)
            raise CASWorkerError(error)

    def _receive(
        self,
        request_id: str,
        timeout_ms: int,
    ) -> tuple[dict[str, Any], int | None]:
        deadline = time.monotonic() + timeout_ms / 1000
        peak_rss_bytes: int | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            wait_seconds = min(remaining, self.rss_poll_interval_ms / 1000)
            try:
                payload = self._outbox.get(timeout=wait_seconds)
            except queue.Empty:
                peak_rss_bytes = self._sample_and_enforce_rss(peak_rss_bytes)
                continue
            peak_rss_bytes = self._sample_and_enforce_rss(peak_rss_bytes)
            if payload.get("id") == request_id:
                return payload, peak_rss_bytes

    def _sample_and_enforce_rss(self, previous_peak: int | None) -> int | None:
        rss_bytes = _process_rss_bytes(self.pid)
        if rss_bytes is None:
            return previous_peak
        peak = max(previous_peak or 0, rss_bytes)
        if self.max_rss_bytes is not None and peak > self.max_rss_bytes:
            raise CASWorkerMemoryExceeded(
                peak_rss_bytes=peak,
                limit_bytes=self.max_rss_bytes,
            )
        return peak

    def _reset(self, *, force: bool) -> None:
        process = self._process
        inbox = self._inbox
        outbox = self._outbox
        self._process = None
        self._inbox = None
        self._outbox = None
        if process is not None and process.is_alive():
            if not force and inbox is not None:
                inbox.put({"operation": "stop"})
                process.join(timeout=0.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        for channel in (inbox, outbox):
            if channel is not None:
                channel.close()
                channel.join_thread()


def _worker_main(inbox: Any, outbox: Any) -> None:
    try:
        import sympy
        from sympy.core.random import seed as set_sympy_seed
    except Exception as exc:
        outbox.put({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return
    outbox.put({"ready": True})
    while True:
        request = inbox.get()
        if request.get("operation") == "stop":
            return
        request_id = request.get("id")
        try:
            selected_seed = int(request.get("seed", 0))
            set_sympy_seed(selected_seed)
            result = compare_expressions(
                request["lhs"],
                request["rhs"],
                assumptions=request.get("assumptions"),
            )
            result.seed = selected_seed
            result.sympy_version = sympy.__version__
            result.policy_version = POLICY_VERSION
            outbox.put({"id": request_id, "ok": True, "result": result.to_dict()})
        except Exception as exc:
            outbox.put(
                {
                    "id": request_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )


def _process_rss_bytes(pid: int | None) -> int | None:
    """Read a worker's current RSS by PID; units are normalized to bytes."""
    if pid is None:
        return None
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process(pid).memory_info().rss)
    except (psutil.Error, OSError):
        return None
