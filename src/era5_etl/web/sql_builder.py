"""Pure builder-spec -> SQL. Single source of truth for generated SQL.

Mirrors the old ``comparison.py`` epsilon join (``abs(a-b) < eps``) so a
user can reproduce ``era5_inmet`` visually. View/alias identifiers are
validated (they come from a controlled UI list, not free text); column
names are double-quoted on top of validation.
"""

from __future__ import annotations

import re

from era5_etl.web.models import BuildSpec, JoinPair, SourceSel  # noqa: F401

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(s: str) -> str:
    if not _IDENT_RE.match(s):
        raise ValueError(f"Unsafe identifier: {s!r}")
    return s


def _ref(qualified: str) -> str:
    """``'alias.col'`` -> ``'alias."col"'`` with both parts validated."""
    alias, _, col = qualified.partition(".")
    return f'{_ident(alias)}."{_ident(col)}"'


def build_view_sql(spec: BuildSpec) -> str:
    name = _ident(spec.name)
    jt = spec.join_type.upper()
    if jt not in ("INNER", "LEFT"):
        raise ValueError(f"Unsupported join type: {spec.join_type}")
    if not spec.sources:
        raise ValueError("At least one source is required.")

    select_parts: list[str] = []
    for s in spec.sources:
        a = _ident(s.alias)
        for c in s.columns:
            select_parts.append(f'{a}."{_ident(c)}" AS "{a}_{_ident(c)}"')
    if not select_parts:
        raise ValueError("Select at least one column.")

    head, *rest = spec.sources
    from_sql = f"{_ident(head.view)} AS {_ident(head.alias)}"

    join_sql_parts: list[str] = []
    for s in rest:
        s_alias = _ident(s.alias)
        conds = [
            (
                f"abs({_ref(j.right)} - {_ref(j.left)}) < {j.epsilon}"
                if j.approx
                else f"{_ref(j.right)} = {_ref(j.left)}"
            )
            for j in spec.joins
            if j.right.split(".")[0] == s.alias
        ]
        if not conds:
            raise ValueError(
                f"No join condition for source '{s.alias}'."
            )
        join_sql_parts.append(
            f"{jt} JOIN {_ident(s.view)} AS {s_alias} ON "
            + " AND ".join(conds)
        )

    select_sql = ",\n       ".join(select_parts)
    joins_sql = (
        ("\n  " + "\n  ".join(join_sql_parts)) if join_sql_parts else ""
    )
    return (
        f'CREATE OR REPLACE VIEW "{name}" AS\n'
        f"SELECT {select_sql}\n"
        f"FROM {from_sql}{joins_sql}"
    )


__all__ = ["build_view_sql", "BuildSpec", "JoinPair", "SourceSel"]
