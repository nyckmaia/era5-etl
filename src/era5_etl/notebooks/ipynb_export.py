"""Convert a stored notebook document into a Jupyter ``.ipynb`` (nbformat v4).

Mapping (internal JSON -> ipynb):

* ``markdown`` cell -> markdown cell.
* ``code`` cell     -> code cell; outputs converted below.
* ``sql`` cell      -> code cell whose first line is ``%%sql`` (jupysql
  convention — Jupyter has no native SQL cell).
* output ``stream``  -> ``stream`` output (our ``warning`` stream -> stderr).
* output ``error``   -> ``error`` output.
* Plotly display     -> ``display_data`` with the standard plotly MIME
  (renders natively in JupyterLab).
* DataFrame display  -> ``display_data`` with a static ``text/html`` table
  rebuilt from the stored rows + a ``text/plain`` fallback.
* output ``done``    -> dropped (internal bookkeeping).

Unknown output shapes degrade to ``text/plain`` — the export never fails on
exotic outputs.
"""

from __future__ import annotations

import html
import re
from typing import Any

import nbformat
from nbformat import v4

PLOTLY_MIME = "application/vnd.plotly.v1+json"
DATAFRAME_MIME = "application/vnd.dataframe+json"


def ipynb_filename(name: str) -> str:
    """Slugify a notebook name into a safe ``.ipynb`` filename."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return f"{slug or 'notebook'}.ipynb"


def _dataframe_html(data: dict[str, Any]) -> str:
    """Static HTML table from the kernel's DataFrame payload.

    Payload shape (see ``kernel_runner._serialize_dataframe``): ``schema``
    (list of {name, dtype}), ``rows``, ``index``, ``index_name``,
    ``ellipsis_after`` (row position of the Jupyter-style ``…`` row).
    """
    schema = data.get("schema") or []
    rows = data.get("rows") or []
    index = data.get("index") or []
    index_name = html.escape(str(data.get("index_name") or ""))
    ellipsis_after = data.get("ellipsis_after")
    head = "".join(
        f"<th>{html.escape(str(c.get('name', '')))}</th>" for c in schema
    )
    body: list[str] = []
    for i, row in enumerate(rows):
        if ellipsis_after is not None and i == ellipsis_after:
            cells = "".join("<td>…</td>" for _ in schema)
            body.append(f"<tr><th>…</th>{cells}</tr>")
        idx_val = html.escape(str(index[i])) if i < len(index) else ""
        cells = "".join(
            f"<td>{'' if v is None else html.escape(str(v))}</td>" for v in row
        )
        body.append(f"<tr><th>{idx_val}</th>{cells}</tr>")
    return (
        f'<table border="1"><thead><tr><th>{index_name}</th>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _convert_output(out: dict[str, Any]) -> nbformat.NotebookNode | None:
    kind = out.get("type")
    if kind == "stream":
        name = "stderr" if out.get("name") in ("stderr", "warning") else "stdout"
        return v4.new_output("stream", name=name, text=str(out.get("text", "")))
    if kind == "error":
        return v4.new_output(
            "error",
            ename=str(out.get("ename", "Error")),
            evalue=str(out.get("evalue", "")),
            traceback=[str(t) for t in out.get("traceback") or []],
        )
    if kind == "display":
        mime = out.get("mime")
        data = out.get("data")
        if mime == PLOTLY_MIME and isinstance(data, dict):
            return v4.new_output(
                "display_data", data={PLOTLY_MIME: data.get("figure") or {}}
            )
        if mime == DATAFRAME_MIME and isinstance(data, dict):
            total = data.get("total_rows", len(data.get("rows") or []))
            return v4.new_output(
                "display_data",
                data={
                    "text/html": _dataframe_html(data),
                    "text/plain": f"DataFrame: {total} rows",
                },
            )
        return v4.new_output("display_data", data={"text/plain": str(data)})
    return None  # "done" and anything unknown carries no user content


def notebook_to_ipynb(doc: dict[str, Any]) -> nbformat.NotebookNode:
    """Build a validated nbformat-v4 notebook from a stored notebook dict."""
    cells: list[nbformat.NotebookNode] = []
    for cell in doc.get("cells") or []:
        ctype = cell.get("type", "code")
        source = str(cell.get("source", ""))
        metadata = {"collapsed": True} if cell.get("collapsed") else {}
        if ctype == "markdown":
            cells.append(v4.new_markdown_cell(source, metadata=metadata))
            continue
        if ctype == "sql":
            source = "%%sql\n" + source
        outputs = []
        for out in cell.get("outputs") or []:
            converted = _convert_output(out)
            if converted is not None:
                outputs.append(converted)
        cells.append(v4.new_code_cell(source, outputs=outputs, metadata=metadata))
    node = v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3",
                "language": "python",
            },
            "language_info": {"name": "python"},
            "era5_etl": {
                "notebook_id": str(doc.get("id", "")),
                "name": str(doc.get("name", "")),
            },
        },
    )
    nbformat.validate(node)
    return node


__all__ = ["ipynb_filename", "notebook_to_ipynb"]
