"""Lifecycle manager for one Python subprocess per notebook.

Each notebook gets at most one kernel at a time. The kernel is started lazily
on the first ``run_cell``, kept alive across cells, and reaped when:

- the user explicitly stops it (``stop``),
- the user restarts it (``restart``),
- it has been idle longer than ``KERNEL_IDLE_TIMEOUT_S`` (a daemon thread
  sweeps every 60s),
- the parent server shuts down (subprocess inherits parent's lifecycle).

Concurrency: one cell at a time per kernel — a second ``run_cell`` call while
the kernel is busy raises :class:`KernelBusyError` (the HTTP layer turns
that into a 409).
"""

from __future__ import annotations

import json
import logging
import secrets
import subprocess
import sys
import threading
import time
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KERNEL_IDLE_TIMEOUT_S = 60 * 60  # 1 hour
KERNEL_BOOT_TIMEOUT_S = 60
KERNEL_REAPER_INTERVAL_S = 60


class KernelBusyError(RuntimeError):
    """Raised when a cell run is requested while the kernel is mid-execution."""


class KernelDeadError(RuntimeError):
    """Raised when interacting with a kernel whose subprocess has exited."""


class _Kernel:
    """One subprocess + its mailbox."""

    def __init__(
        self,
        notebook_id: str,
        data_dir: Path,
        runs_url: str,
    ) -> None:
        self.notebook_id = notebook_id
        self.data_dir = data_dir
        self.runs_url = runs_url
        self.token = secrets.token_urlsafe(32)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()  # serialise cell execution
        self._running_cell: str | None = None
        self.last_activity: float = time.time()
        self.started_at: float = time.time()

    # --- lifecycle ---------------------------------------------------

    def start(self) -> None:
        env = {
            "ERA5_NB_DATA_DIR": str(self.data_dir),
            "ERA5_NB_ID": self.notebook_id,
            "ERA5_NB_RUNS_URL": self.runs_url,
            "ERA5_NB_RUNS_TOKEN": self.token,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        # Inherit the parent env (PATH, etc.) but override our keys.
        import os

        full_env = {**os.environ, **env}
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "era5_etl.notebooks.kernel_runner"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
            text=True,
            encoding="utf-8",
            bufsize=1,  # line-buffered
        )
        # Drain the boot phase (anything emitted before "ready").
        self._consume_boot()
        self.started_at = time.time()
        self.last_activity = self.started_at

    def _consume_boot(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        deadline = time.time() + KERNEL_BOOT_TIMEOUT_S
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise KernelDeadError("Kernel exited during boot")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ready":
                return
            if msg.get("type") == "error":
                logger.warning(
                    "Kernel boot for %s emitted error: %s",
                    self.notebook_id,
                    msg.get("evalue"),
                )
        raise KernelDeadError("Kernel did not become ready in time")

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> str:
        if not self.is_alive():
            return "dead"
        return "busy" if self._running_cell is not None else "idle"

    def stop(self, timeout: float = 5.0) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None

    # --- cell execution ----------------------------------------------

    def run_cell(self, cell_id: str, code: str, lang: str) -> Iterator[dict[str, Any]]:
        if not self.is_alive():
            raise KernelDeadError("Kernel is not running")
        if not self._lock.acquire(blocking=False):
            raise KernelBusyError(
                f"Kernel is busy running cell {self._running_cell!r}"
            )
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        self._running_cell = cell_id
        self.last_activity = time.time()
        req = json.dumps({"type": "exec", "cell_id": cell_id, "code": code, "lang": lang})
        try:
            proc.stdin.write(req + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._running_cell = None
            self._lock.release()
            raise KernelDeadError(f"Kernel died before exec: {exc}") from exc
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise KernelDeadError(
                        "Kernel exited mid-execution; stderr below.\n"
                        + (proc.stderr.read() if proc.stderr else "")
                    )
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield msg
                if msg.get("type") == "done":
                    return
        finally:
            self._running_cell = None
            self.last_activity = time.time()
            self._lock.release()


class KernelManager:
    """Process-wide kernel registry (one kernel per notebook id)."""

    def __init__(self) -> None:
        self._kernels: dict[str, _Kernel] = {}
        self._lock = threading.Lock()
        self._reaper_started = False

    def get_or_start(
        self,
        notebook_id: str,
        data_dir: Path,
        runs_url: str,
    ) -> _Kernel:
        with self._lock:
            kernel = self._kernels.get(notebook_id)
            if kernel and kernel.is_alive():
                return kernel
            if kernel is not None:
                # dead — drop the reference so we start fresh
                self._kernels.pop(notebook_id, None)
            kernel = _Kernel(notebook_id, data_dir, runs_url)
            kernel.start()
            self._kernels[notebook_id] = kernel
            self._ensure_reaper()
            return kernel

    def get_existing(self, notebook_id: str) -> _Kernel | None:
        with self._lock:
            return self._kernels.get(notebook_id)

    def stop(self, notebook_id: str) -> bool:
        with self._lock:
            kernel = self._kernels.pop(notebook_id, None)
        if kernel is None:
            return False
        kernel.stop()
        return True

    def restart(
        self,
        notebook_id: str,
        data_dir: Path,
        runs_url: str,
    ) -> _Kernel:
        self.stop(notebook_id)
        return self.get_or_start(notebook_id, data_dir, runs_url)

    def status(self, notebook_id: str) -> str:
        with self._lock:
            kernel = self._kernels.get(notebook_id)
        if kernel is None:
            return "dead"
        return kernel.status()

    def stop_all(self) -> None:
        with self._lock:
            kernels = list(self._kernels.values())
            self._kernels.clear()
        for k in kernels:
            try:
                k.stop()
            except Exception:
                logger.exception("Failed to stop kernel for %s", k.notebook_id)

    def _ensure_reaper(self) -> None:
        if self._reaper_started:
            return
        self._reaper_started = True
        ref = weakref.ref(self)

        def _reap() -> None:
            while True:
                time.sleep(KERNEL_REAPER_INTERVAL_S)
                mgr = ref()
                if mgr is None:
                    return
                cutoff = time.time() - KERNEL_IDLE_TIMEOUT_S
                with mgr._lock:
                    stale = [
                        nb_id
                        for nb_id, k in mgr._kernels.items()
                        if k.status() == "idle" and k.last_activity < cutoff
                    ]
                for nb_id in stale:
                    logger.info("Reaping idle kernel for notebook %s", nb_id)
                    mgr.stop(nb_id)

        threading.Thread(target=_reap, daemon=True, name="kernel-reaper").start()


# Process-wide singleton.
MANAGER = KernelManager()


__all__ = [
    "MANAGER",
    "KernelBusyError",
    "KernelDeadError",
    "KernelManager",
]
