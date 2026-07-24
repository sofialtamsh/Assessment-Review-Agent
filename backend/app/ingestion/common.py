"""Shared tabular-file helpers (CSV / XLSX) with no heavy pandas dependency."""
from __future__ import annotations

import csv
import io
from typing import Any


def _norm_key(k: str) -> str:
    return str(k or "").strip().lower().replace(" ", "_").replace("-", "_")


def read_table(data: bytes, filename: str) -> list[dict[str, Any]]:
    """Return a list of row dicts with normalized (snake_case) header keys.

    Supports .csv and .xlsx. Falls back to CSV parsing for unknown extensions.
    """
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        rows = _read_xlsx(data)
    else:
        rows = _read_csv(data)
    return [{_norm_key(k): ("" if v is None else v) for k, v in row.items()} for row in rows]


def _read_csv(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def _read_xlsx(data: bytes) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        return []
    header = [str(h) if h is not None else f"col{i}" for i, h in enumerate(header)]
    out: list[dict[str, Any]] = []
    for row in rows_iter:
        if row is None or all(c is None for c in row):
            continue
        out.append({header[i]: row[i] if i < len(row) else None for i in range(len(header))})
    return out


def split_list(value: Any) -> list[str]:
    """Split a cell that may hold a delimited list (comma/semicolon/pipe)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip()
    if not s:
        return []
    # newline-separated lists (e.g. a "What to Cover" cell) split first
    if "\n" in s:
        return [p.strip(" -•\t") for p in s.splitlines() if p.strip(" -•\t")]
    for sep in [";", "|", ","]:
        if sep in s:
            return [p.strip() for p in s.split(sep) if p.strip()]
    return [s]


def first(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for k in keys:
        if k in row and str(row[k]).strip() != "":
            return row[k]
    return default
