"""System-provided DuckDB objects, always available on the query engine.

Unlike user views/macros (persisted in ``user_views.json`` and editable
on the /query page), these are defined in code, registered on every
connection before user objects, and cannot be edited or deleted. They
surface in the SCHEMA sidebar as read-only entries (``builtin=True``).
"""

from __future__ import annotations

# Bilinear interpolation macro. The doc comments are part of the stored
# SQL on purpose: clicking the macro in the /query SCHEMA sidebar loads
# this exact text into the editor, so the parameter contract and a usage
# example travel with the macro itself.
_BILINEAR_WEIGHTS_SQL = """\
-- ===========================================================
-- MACRO bilinear_weights  --  system built-in (read-only)
-- ===========================================================
-- Bilinearly interpolates a value at a point that lies INSIDE a
-- rectangular grid cell, from the cell's four corner values. It
-- is a weighted average of the 4 corners: corners closer to the
-- point receive more weight.
--
-- PARAMETERS
--   wx   normalized X (longitude) weight, in [0, 1].
--        0.0 -> point on the cell's LEFT  edge;
--        1.0 -> point on the cell's RIGHT edge.
--   wy   normalized Y (latitude) weight, in [0, 1].
--        0.0 -> point on the cell's TOP    edge;
--        1.0 -> point on the cell's BOTTOM edge.
--   q11  corner value at TOP-LEFT      (left  lon, top    lat).
--   q21  corner value at TOP-RIGHT     (right lon, top    lat).
--   q12  corner value at BOTTOM-LEFT   (left  lon, bottom lat).
--   q22  corner value at BOTTOM-RIGHT  (right lon, bottom lat).
--
-- RETURNS
--   The interpolated value. If ANY corner is NULL the result is
--   NULL (a missing corner cannot be interpolated).
--
-- USAGE EXAMPLE
--   -- Point at the cell centre (wx = 0.5, wy = 0.5); corners
--   -- 10, 20, 30, 40 -> the plain average, 25.0:
--   SELECT bilinear_weights(0.5, 0.5, 10, 20, 30, 40);
--
--   -- Typical use: interpolate an ERA5-LAND variable onto a
--   -- station from its 4 enclosing grid corners:
--   SELECT bilinear_weights(
--            wx, wy,
--            tl.temperature_2m, tr.temperature_2m,
--            bl.temperature_2m, br.temperature_2m
--          ) AS temperature_interp;
--
--   See the "vw_inmet_vs_era5_land_interpolated" template for a
--   full example over every ERA5-LAND variable.
-- ===========================================================
CREATE OR REPLACE MACRO bilinear_weights(wx, wy, q11, q21, q12, q22) AS (
  q11 * (1.0 - wx) * (1.0 - wy)
  + q21 * wx * (1.0 - wy)
  + q12 * (1.0 - wx) * wy
  + q22 * wx * wy
);"""

#: Each entry: ``name`` (SQL identifier), ``kind`` ("view" | "macro"),
#: ``sql`` (a single CREATE OR REPLACE statement).
BUILTIN_OBJECTS: list[dict[str, str]] = [
    {"name": "bilinear_weights", "kind": "macro", "sql": _BILINEAR_WEIGHTS_SQL},
]

#: Lower-cased names — used to keep user objects from shadowing a builtin.
BUILTIN_NAMES: frozenset[str] = frozenset(
    o["name"].lower() for o in BUILTIN_OBJECTS
)

__all__ = ["BUILTIN_NAMES", "BUILTIN_OBJECTS"]
