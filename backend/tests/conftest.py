"""Shared test fixtures.

Env is configured BEFORE any app module is imported so the app uses the mock LLM
provider and a throwaway SQLite DB.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ["LLM_PROVIDER"] = "mock"
os.environ["ARP_DB_PATH"] = str(Path(tempfile.gettempdir()) / "arp_test_review.db")

# fresh DB file each test session
_db = Path(os.environ["ARP_DB_PATH"])
if _db.exists():
    _db.unlink()

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    from app.db import init_db
    init_db()
    yield


def read(name: str) -> bytes:
    return (SAMPLE / name).read_bytes()


@pytest.fixture(scope="session")
def sample_questions():
    from app.ingestion.questions import parse_questions
    return parse_questions(read("assignment_session_ds_07.csv"), "assignment.csv")


@pytest.fixture(scope="session")
def sample_quiz():
    from app.ingestion.questions import parse_questions
    return parse_questions(read("in_class_quiz_ds_07.csv"), "quiz.csv")


@pytest.fixture(scope="session")
def sample_chunks():
    from app.ingestion.content import parse_content
    return parse_content("ds_07", read("session_ds_07.pptx"), "session_ds_07.pptx")


@pytest.fixture(scope="session")
def taught_subtopics():
    from app.ingestion.mastersheet import parse_mastersheet
    return parse_mastersheet(read("mastersheet.csv"), "mastersheet.csv")[0].subtopics
