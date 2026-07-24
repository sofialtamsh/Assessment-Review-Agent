"""Parse an XLSX mastersheet, extracting the cell HYPERLINKS (which CSV export
drops), and aggregate rows into logical units.

Each Unit name (e.g. "Digital Image Fundamentals") appears across several rows with
different Unit Types:
  * Session      -> slide content  (Embedded links / PPT hyperlink)
  * Tutorial     -> tutorial doc with in-class MCQs at the end (PPT hyperlink)
  * MCQ Practice -> the MCQ assignment doc (PPT hyperlink)
We collapse them into one UnitSpec carrying the links to fetch content + questions.
"""
from __future__ import annotations

import io
import re

from ..schemas import UnitSpec
from .common import split_list

_SLUG = re.compile(r"[^a-z0-9]+")


def parse_mastersheet_xlsx(data: bytes) -> list[UnitSpec]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    idx = {h.lower(): i for i, h in enumerate(header)}

    def col(*names: str) -> int | None:
        for n in names:
            if n.lower() in idx:
                return idx[n.lower()]
        return None

    c_course = col("course")
    c_topic = col("topic")
    c_unit = col("unit")
    c_cover = col("what to cover", "subtopics")
    c_type = col("unit type", "type")
    c_ppt = col("ppt")
    c_embed = col("embedded links", "embedded link")
    c_sid = col("s-id", "s_id", "sid")

    units: dict[str, UnitSpec] = {}
    for row in ws.iter_rows(min_row=2):
        unit_name = _cell(row, c_unit)
        if not unit_name:
            continue
        course = _cell(row, c_course)
        key = _SLUG.sub("-", f"{course}-{unit_name}".lower()).strip("-")
        u = units.setdefault(key, UnitSpec(
            unit_id=key, course=course, module=_cell(row, c_topic), unit=unit_name,
        ))
        utype = _cell(row, c_type).lower()
        ppt_link = _hyperlink(row, c_ppt)
        embed_link = _hyperlink(row, c_embed) or _cell(row, c_embed)

        if "session" in utype:
            cover = _cell(row, c_cover)
            if cover:
                u.subtopics = split_list(cover)
            u.content_url = embed_link or ppt_link or u.content_url
            u.s_id = _cell(row, c_sid) or u.s_id
            if not u.module:
                u.module = _cell(row, c_topic)
        elif "mcq" in utype:            # "MCQ Practice"
            u.mcq_doc_url = u.mcq_doc_url or ppt_link
        elif "tutorial" in utype:
            u.quiz_doc_url = u.quiz_doc_url or ppt_link
        # (Coding Assignment / Exam rows are ignored for review sourcing)

    # keep only units that have at least a question source or content
    return [u for u in units.values()
            if u.mcq_doc_url or u.quiz_doc_url or u.content_url]


def _cell(row, i: int | None) -> str:
    if i is None or i >= len(row):
        return ""
    v = row[i].value
    return str(v).strip() if v is not None else ""


def _hyperlink(row, i: int | None) -> str | None:
    if i is None or i >= len(row):
        return None
    c = row[i]
    if c.hyperlink and c.hyperlink.target:
        return c.hyperlink.target
    # sometimes the URL is the plain value
    v = str(c.value or "").strip()
    return v if v.lower().startswith("http") else None
