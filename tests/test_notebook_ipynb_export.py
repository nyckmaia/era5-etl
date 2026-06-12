"""Stored-notebook -> Jupyter .ipynb conversion."""

from __future__ import annotations

import pytest

nbformat = pytest.importorskip("nbformat")

from era5_etl.notebooks.ipynb_export import ipynb_filename, notebook_to_ipynb


def _doc(cells):
    return {"id": "abc123", "name": "My NB", "cells": cells, "runs": []}


def test_filename_slug():
    assert ipynb_filename("Meu Notebook (v2)!") == "meu-notebook-v2.ipynb"
    assert ipynb_filename("") == "notebook.ipynb"
    assert ipynb_filename("---") == "notebook.ipynb"


def test_markdown_and_code_cells_map():
    doc = _doc(
        [
            {"id": "c1", "type": "markdown", "source": "# Title", "outputs": []},
            {"id": "c2", "type": "code", "source": "print(1)", "outputs": []},
        ]
    )
    nb = notebook_to_ipynb(doc)
    nbformat.validate(nb)  # well-formed v4
    assert nb.cells[0].cell_type == "markdown"
    assert nb.cells[0].source == "# Title"
    assert nb.cells[1].cell_type == "code"
    assert nb.cells[1].source == "print(1)"


def test_sql_cell_becomes_code_with_sql_magic():
    doc = _doc([{"id": "c1", "type": "sql", "source": "SELECT 1", "outputs": []}])
    nb = notebook_to_ipynb(doc)
    assert nb.cells[0].cell_type == "code"
    assert nb.cells[0].source == "%%sql\nSELECT 1"


def test_collapsed_flag_carried_to_metadata():
    doc = _doc(
        [{"id": "c1", "type": "code", "source": "x=1", "outputs": [], "collapsed": True}]
    )
    nb = notebook_to_ipynb(doc)
    assert nb.cells[0].metadata.get("collapsed") is True


def test_stream_error_and_display_outputs_map():
    doc = _doc(
        [
            {
                "id": "c1",
                "type": "code",
                "source": "run()",
                "outputs": [
                    {"type": "stream", "name": "stdout", "text": "hi\n"},
                    {"type": "stream", "name": "warning", "text": "careful\n"},
                    {
                        "type": "error",
                        "ename": "ValueError",
                        "evalue": "bad",
                        "traceback": ["tb1", "tb2"],
                    },
                    {
                        "type": "display",
                        "mime": "application/vnd.plotly.v1+json",
                        "data": {"figure": {"data": [], "layout": {}}},
                    },
                    {
                        "type": "display",
                        "mime": "application/vnd.dataframe+json",
                        "data": {
                            "schema": [{"name": "a", "dtype": "int64"}],
                            "rows": [[1], [2]],
                            "index": [0, 1],
                            "index_name": "",
                            "ellipsis_after": None,
                            "float_precision": 2,
                            "truncated": False,
                            "total_rows": 2,
                        },
                    },
                    {"type": "done", "cell_id": "c1", "duration_s": 0.1},
                ],
            }
        ]
    )
    nb = notebook_to_ipynb(doc)
    nbformat.validate(nb)
    outs = nb.cells[0].outputs
    # "done" is internal bookkeeping and must be dropped.
    assert len(outs) == 5
    assert outs[0].output_type == "stream" and outs[0].name == "stdout"
    assert outs[1].name == "stderr"  # warning -> stderr
    assert outs[2].output_type == "error" and outs[2].ename == "ValueError"
    assert "application/vnd.plotly.v1+json" in outs[3].data
    html = outs[4].data["text/html"]
    assert "<table" in html and "<td>1</td>" in html
    assert "text/plain" in outs[4].data


def test_dataframe_html_escapes_and_ellipsis():
    doc = _doc(
        [
            {
                "id": "c1",
                "type": "code",
                "source": "df",
                "outputs": [
                    {
                        "type": "display",
                        "mime": "application/vnd.dataframe+json",
                        "data": {
                            "schema": [{"name": "<b>", "dtype": "object"}],
                            "rows": [["<x>"], ["y"]],
                            "index": [0, 1],
                            "index_name": "",
                            "ellipsis_after": 1,
                            "float_precision": 2,
                            "truncated": True,
                            "total_rows": 100,
                        },
                    }
                ],
            }
        ]
    )
    nb = notebook_to_ipynb(doc)
    html = nb.cells[0].outputs[0].data["text/html"]
    assert "&lt;x&gt;" in html and "&lt;b&gt;" in html  # escaped
    assert "…" in html  # ellipsis row


def test_unknown_display_degrades_to_text_plain():
    doc = _doc(
        [
            {
                "id": "c1",
                "type": "code",
                "source": "obj",
                "outputs": [{"type": "display", "mime": "text/plain", "data": "Foo()"}],
            }
        ]
    )
    nb = notebook_to_ipynb(doc)
    assert nb.cells[0].outputs[0].data["text/plain"] == "Foo()"
