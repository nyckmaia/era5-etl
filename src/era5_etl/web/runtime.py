"""Bridge between :class:`ERA5Pipeline` and the SSE progress stream.

A web client opens an EventSource on ``/api/pipeline/progress``. The pipeline
runs in a background thread, pushes events to the bridge, and the SSE handler
yields them to the client as they arrive.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

ChunkPhase = Literal[
    "submitting",
    "queued",
    "running",
    "downloading",
    "processing",
    "completed",
    "failed",
]


@dataclass
class ProgressEvent:
    """One progress tick sent to the browser via SSE.

    Two flavours of event share this dataclass:

    - **Stage events**: ``stage``, ``stage_progress``, ``global_progress``
      describe overall pipeline progress.
    - **Chunk events** (Melhoria 04): when ``chunk_id`` is set, this event
      reports the lifecycle of one CDS request --
      ``phase`` cycles through submitting -> queued -> running ->
      downloading -> completed, optionally with byte-progress in
      ``bytes_downloaded`` / ``bytes_total``.

    Pipeline-level phase fields (``pipeline_phase``, ``phase_index``,
    ``phase_total``) describe multi-phase runs — e.g. the INMET flow that
    auto-bootstraps ERA5 and ERA5-LAND before fetching INMET. ``None``/1/1
    on single-phase runs; the UI hides the phase chip in that case.
    """

    stage: str
    stage_progress: float
    message: str
    global_progress: float
    timestamp: float = field(default_factory=time.time)
    chunk_id: str | None = None
    chunk_index: int | None = None
    chunks_total: int | None = None
    phase: ChunkPhase | None = None
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    # Conversion-stage progress (NetCDF -> Parquet). Set only on
    # ``stage == "convert"`` events; ``None`` on download/chunk events.
    files_done: int | None = None
    files_total: int | None = None
    # Multi-phase orchestration (INMET flow).
    pipeline_phase: str | None = None
    phase_index: int | None = None
    phase_total: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineRuntime:
    """In-process registry of running pipelines, keyed by run id."""

    def __init__(self) -> None:
        self._runs: dict[str, PipelineRun] = {}
        self._lock = threading.Lock()

    def register(self, run_id: str, run: PipelineRun) -> None:
        with self._lock:
            self._runs[run_id] = run

    def get(self, run_id: str) -> PipelineRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def remove(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._runs)


class PipelineRun:
    """One in-flight pipeline run, exposed to the web UI via events + status."""

    _SENTINEL = object()

    def __init__(self, run_id: str, dataset: str) -> None:
        self.run_id = run_id
        self.dataset = dataset
        self.created_at = time.time()
        self.status: str = "pending"
        self.error: str | None = None
        self._queue: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()
        # Multi-phase orchestration state (INMET auto-bootstrap flow).
        # ``pipeline_phase`` is the stable label of the active sub-pipeline
        # (``bootstrap-era5``, ``bootstrap-era5-land``, ``inmet``); index/
        # total describe its position in the queue. Single-phase runs leave
        # these at None/1/1 — emit_chunk_event simply attaches whatever is
        # set, so a regular ERA5 run looks identical to before.
        self.pipeline_phase: str | None = None
        self.phase_index: int = 1
        self.phase_total: int = 1

    # ---- phase orchestration ---------------------------------------------

    def set_phase(self, name: str, index: int, total: int) -> None:
        """Mark the start of a sub-pipeline phase. Subsequent ``emit*``
        calls stamp events with this label until the next ``set_phase``."""
        with self._lock:
            self.pipeline_phase = name
            self.phase_index = index
            self.phase_total = total

    # ---- producer (called from pipeline thread) ---------------------------

    def emit(
        self,
        stage: str,
        stage_progress: float,
        message: str,
        global_progress: float,
    ) -> None:
        event = ProgressEvent(
            stage=stage,
            stage_progress=stage_progress,
            message=message,
            global_progress=global_progress,
            pipeline_phase=self.pipeline_phase,
            phase_index=self.phase_index,
            phase_total=self.phase_total,
        )
        self._queue.put(event)

    def emit_chunk_event(self, payload: dict[str, Any]) -> None:
        """Queue a progress event from the pipeline.

        ``payload`` is the dict produced by ``CDSDownloader.on_event`` /
        ``CDSEventCapture`` (download/chunk lifecycle) OR by the conversion
        stage (``stage="convert"``). Missing keys default to ``None``; we
        explicitly bridge to ``ProgressEvent`` rather than letting Pydantic
        strip unknown fields downstream.
        """
        if payload.get("stage") == "convert":
            done = int(payload.get("files_done", 0) or 0)
            total = int(payload.get("files_total", 0) or 0)
            frac = (done / total) if total else 0.0
            self._queue.put(
                ProgressEvent(
                    stage="convert",
                    stage_progress=frac,
                    message=str(payload.get("message", "")),
                    global_progress=frac,
                    files_done=done,
                    files_total=total,
                    pipeline_phase=self.pipeline_phase,
                    phase_index=self.phase_index,
                    phase_total=self.phase_total,
                )
            )
            return
        if payload.get("stage") == "finalizing":
            # Post-convert / pre-completion housekeeping: refresh indexes,
            # create DuckDB views. The UI uses this to render a "Finalizando…"
            # banner so the user doesn't think the run hung between the
            # convert bar reaching 100% and the success card.
            self._queue.put(
                ProgressEvent(
                    stage="finalizing",
                    stage_progress=1.0,
                    message=str(payload.get("message", "")),
                    global_progress=1.0,
                    pipeline_phase=self.pipeline_phase,
                    phase_index=self.phase_index,
                    phase_total=self.phase_total,
                )
            )
            return
        chunks_total = payload.get("chunks_total")
        chunk_index = payload.get("chunk_index")
        global_progress = 0.0
        if chunks_total and chunk_index:
            # Coarse: chunks are equal-weighted slices of the download stage.
            global_progress = max(0.0, min(1.0, (chunk_index - 1) / chunks_total))
            if payload.get("phase") == "completed":
                global_progress = min(1.0, chunk_index / chunks_total)
        event = ProgressEvent(
            stage="download",
            stage_progress=global_progress,
            message=str(payload.get("message", "")),
            global_progress=global_progress,
            chunk_id=payload.get("chunk_id"),
            chunk_index=chunk_index,
            chunks_total=chunks_total,
            phase=payload.get("phase"),
            bytes_downloaded=payload.get("bytes_downloaded"),
            bytes_total=payload.get("bytes_total"),
            pipeline_phase=self.pipeline_phase,
            phase_index=self.phase_index,
            phase_total=self.phase_total,
        )
        self._queue.put(event)

    def mark_started(self) -> None:
        with self._lock:
            self.status = "running"

    def mark_completed(self) -> None:
        with self._lock:
            self.status = "completed"
        self._queue.put(self._SENTINEL)

    def mark_failed(self, message: str) -> None:
        with self._lock:
            self.status = "failed"
            self.error = message
        self._queue.put(self._SENTINEL)

    # ---- consumer (used by SSE handler) -----------------------------------

    def stream(self) -> Iterator[dict[str, Any]]:
        """Yield events as they arrive until the run completes.

        ``data`` MUST be a JSON string: ``sse_starlette`` writes the SSE
        ``data:`` line via ``str(data)``, so passing a raw ``dict`` would
        emit a Python repr (single quotes, ``None``) that the browser's
        ``JSON.parse`` rejects -- silently dropping every progress event
        and turning a successful run into a frontend "Unknown error".
        """
        while True:
            try:
                item = self._queue.get(timeout=30.0)
            except queue.Empty:
                # Heartbeat keeps the connection open through proxies.
                yield {"event": "heartbeat", "data": json.dumps({"ts": time.time()})}
                continue
            if item is self._SENTINEL:
                yield {
                    "event": "end",
                    "data": json.dumps(
                        {"status": self.status, "error": self.error}
                    ),
                }
                return
            assert isinstance(item, ProgressEvent)
            yield {"event": "progress", "data": json.dumps(item.as_dict())}


# A module-level singleton runtime is convenient for in-process use; tests can
# swap it out via dependency injection.
RUNTIME = PipelineRuntime()
