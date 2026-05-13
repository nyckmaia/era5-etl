"""Parse cdsapi log messages into structured lifecycle events.

The cdsapi library is a thin synchronous wrapper around the Copernicus CDS
REST API. ``client.retrieve(...)`` blocks for the entire submit/queue/
process/download flow, so we can't intercept the phases via API hooks. The
library *does* emit informative log records at each transition, however,
so we attach a ``logging.Handler`` that pattern-matches those records and
emits a structured dict via a callback.

This handler is purely additive: it does not consume the record or silence
the underlying logger. The CLI keeps seeing the usual cdsapi messages in
its terminal output.

Recognised messages (regex, tolerant to wording drift)::

    "Request ID is XXX"                 -> phase=submitting
    "Request <id> is queued"            -> phase=queued
    "Request <id> is running"           -> phase=running
    "Downloading https://... to ... (NN.NN MB)"
                                        -> phase=downloading, bytes_total
    "Download rate ... MB/s"            -> (ignored; not actionable)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_DOWNLOAD_RE = re.compile(
    r"Downloading\s+\S+\s+to\s+\S+\s*\(([0-9.,]+)\s*([KMG]?)B\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ChunkContext:
    """Per-chunk metadata threaded into every parsed event."""

    chunk_id: str
    chunk_index: int
    chunks_total: int


class CDSEventCapture(logging.Handler):
    """Translate cdsapi log records into structured chunk-lifecycle events.

    Attach with :meth:`logging.Logger.addHandler` to the ``cdsapi`` logger
    *before* a chunk download starts; remove it after. Use
    :meth:`set_chunk_context` between chunks so every emitted event carries
    the right chunk_id/index/total without the caller threading those
    through cdsapi's own log records (which only know the CDS request id,
    not our chunk_id).
    """

    def __init__(self, callback: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(level=logging.INFO)
        self.callback = callback
        self._ctx: _ChunkContext | None = None

    def set_chunk_context(
        self, chunk_id: str, chunk_index: int, chunks_total: int
    ) -> None:
        self._ctx = _ChunkContext(chunk_id, chunk_index, chunks_total)

    def clear_chunk_context(self) -> None:
        self._ctx = None

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - logging API
        try:
            payload = self._parse(record.getMessage())
        except Exception:  # pragma: no cover - never let logging crash the app
            return
        if payload is None:
            return
        ctx = self._ctx
        if ctx is not None:
            payload.setdefault("chunk_id", ctx.chunk_id)
            payload.setdefault("chunk_index", ctx.chunk_index)
            payload.setdefault("chunks_total", ctx.chunks_total)
        try:
            self.callback(payload)
        except Exception:  # pragma: no cover - protect the logger
            self.handleError(record)

    # ------------------------------------------------------------------ parse

    @staticmethod
    def _parse(message: str) -> dict[str, Any] | None:
        lower = message.lower()
        if "request id is" in lower:
            return {"phase": "submitting", "message": message}
        if "is queued" in lower or "request is queued" in lower:
            return {"phase": "queued", "message": message}
        if "is running" in lower or "request is running" in lower:
            return {"phase": "running", "message": message}
        if lower.startswith("downloading "):
            match = _DOWNLOAD_RE.search(message)
            payload: dict[str, Any] = {"phase": "downloading", "message": message}
            if match:
                value = float(match.group(1).replace(",", ""))
                multiplier = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[
                    match.group(2).upper()
                ]
                payload["bytes_total"] = int(value * multiplier)
            return payload
        return None
