"""Mastersheet ingestion: one row per session/unit -> Session records."""
from __future__ import annotations

from typing import Any

from ..schemas import Session
from .common import first, read_table, split_list


def parse_mastersheet(data: bytes, filename: str) -> list[Session]:
    rows = read_table(data, filename)
    sessions: list[Session] = []
    for row in rows:
        # session id: explicit column, else the platform session id (s-id), else the unit name
        sid = str(
            first(row, "session_id", "session", "sessionid", "session_no", "id",
                  "s_id", "sid", "t_id", "unit")
        ).strip()
        if not sid:
            continue
        # Skip non-session rows (e.g. Tutorial/Reading rows in a curriculum sheet)
        unit_type = str(first(row, "unit_type", "type")).strip().lower()
        if unit_type and unit_type not in ("session", ""):
            continue
        sessions.append(
            Session(
                session_id=sid,
                course=str(first(row, "course", "course_name")).strip(),
                # "Topic" in a curriculum sheet is the module-level grouping
                module=str(first(row, "module", "module_name", "topic")).strip(),
                unit=str(first(row, "unit", "unit_name")).strip(),
                topic=str(first(row, "topic", "topics", "unit", "unit_name")).strip(),
                subtopics=split_list(
                    first(row, "subtopics", "subtopics_covered", "sub_topics",
                          "what_to_cover", "whattocover")
                ),
                content_path=(
                    str(first(row, "content_path", "content_link", "content",
                              "embedded_links", "ppt", "pdf", "notes", "unit_link")).strip()
                    or None
                ),
            )
        )
    return sessions
