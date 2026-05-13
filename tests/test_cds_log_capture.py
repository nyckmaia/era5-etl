"""Tests for the cdsapi log -> structured event capture (Melhoria 04)."""

from __future__ import annotations

import logging

from era5_etl.download.cds_log_capture import CDSEventCapture


def _fire(handler: CDSEventCapture, message: str) -> None:
    logger = logging.getLogger("cdsapi")
    record = logger.makeRecord("cdsapi", logging.INFO, "x.py", 0, message, None, None)
    handler.emit(record)


def test_parse_request_id_yields_submitting():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.set_chunk_context("c1", 1, 3)
    _fire(h, "Request ID is 1234abcd")
    assert events == [
        {
            "phase": "submitting",
            "message": "Request ID is 1234abcd",
            "chunk_id": "c1",
            "chunk_index": 1,
            "chunks_total": 3,
        }
    ]


def test_parse_queued():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.set_chunk_context("c1", 1, 1)
    _fire(h, "Request 1234abcd is queued")
    assert events[0]["phase"] == "queued"


def test_parse_running():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.set_chunk_context("c1", 1, 1)
    _fire(h, "Request 1234abcd is running")
    assert events[0]["phase"] == "running"


def test_parse_downloading_extracts_bytes_total():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.set_chunk_context("c1", 1, 1)
    _fire(h, "Downloading https://example/file.nc to /tmp/x.nc (12.34 MB)")
    assert events[0]["phase"] == "downloading"
    assert events[0]["bytes_total"] == int(12.34 * 1024 * 1024)


def test_unknown_message_is_silent():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.set_chunk_context("c1", 1, 1)
    _fire(h, "Some random cdsapi info we don't care about")
    assert events == []


def test_chunk_context_overrides_persist_across_messages():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.set_chunk_context("c1", 1, 2)
    _fire(h, "Request ID is XXX")
    _fire(h, "Request XXX is queued")
    h.set_chunk_context("c2", 2, 2)
    _fire(h, "Request ID is YYY")
    assert [e["chunk_id"] for e in events] == ["c1", "c1", "c2"]
    assert [e["chunk_index"] for e in events] == [1, 1, 2]


def test_clear_context_drops_chunk_metadata():
    events: list[dict] = []
    h = CDSEventCapture(events.append)
    h.clear_chunk_context()
    _fire(h, "Request ID is XXX")
    assert "chunk_id" not in events[0]


def test_callback_exception_is_swallowed():
    """A buggy callback must not crash the cdsapi logger."""

    def explode(_payload: dict) -> None:
        raise RuntimeError("boom")

    h = CDSEventCapture(explode)
    h.set_chunk_context("c1", 1, 1)
    # Should not raise.
    _fire(h, "Request ID is XXX")
