"""Map Arrow / DuckDB column types to short Python type names.

Used by the ``/api/query`` and ``/api/query/schema`` endpoints so the web
UI can show ``str`` / ``int`` / ``float`` / ``bool`` / ``datetime`` /
``date`` under each column header (Melhoria 04) and decide which columns
are floats for display-precision formatting (Melhoria 02b).
"""

from __future__ import annotations

import pyarrow as pa


def arrow_type_to_python(arrow_type: pa.DataType) -> str:
    """Return a short Python type name for an Arrow ``DataType``.

    Falls back to the lowercased Arrow type string for anything exotic
    (e.g. ``list``, ``struct``) so the UI still shows *something* useful.
    """
    if pa.types.is_floating(arrow_type):
        return "float"
    if pa.types.is_integer(arrow_type):
        return "int"
    if pa.types.is_boolean(arrow_type):
        return "bool"
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "str"
    if pa.types.is_timestamp(arrow_type):
        return "datetime"
    if pa.types.is_date(arrow_type):
        return "date"
    if pa.types.is_time(arrow_type):
        return "time"
    return str(arrow_type).lower()


def schema_python_types(schema: pa.Schema) -> list[str]:
    """Map every field of an Arrow schema to a short Python type name."""
    return [arrow_type_to_python(schema.field(i).type) for i in range(len(schema))]
