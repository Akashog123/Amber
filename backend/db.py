import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("AMBER_DB", os.path.join(os.path.dirname(__file__), "amber.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY, series_id TEXT, title TEXT, url TEXT, platform TEXT,
  agenda TEXT, context_text TEXT, status TEXT, bot_id TEXT UNIQUE,
  started_at TEXT, ended_at TEXT, mom_json TEXT, recording_url TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS attendees (meeting_id INTEGER, name TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, name TEXT, joined_at TEXT, left_at TEXT
);
CREATE TABLE IF NOT EXISTS utterances (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, speaker TEXT, text TEXT, ts REAL, addressed INTEGER
);
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, sender TEXT, text TEXT, ts TEXT, is_amber INTEGER
);
CREATE TABLE IF NOT EXISTS records (
  id TEXT PRIMARY KEY, kind TEXT, name TEXT, aliases TEXT, status TEXT, owner TEXT, details TEXT
);
CREATE TABLE IF NOT EXISTS record_notes (
  id INTEGER PRIMARY KEY, record_id TEXT, meeting_id INTEGER, note TEXT, confidence REAL, ts TEXT
);
CREATE TABLE IF NOT EXISTS pending_confirmations (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, question TEXT, candidates_json TEXT,
  created_at TEXT, resolved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, series_id TEXT, title TEXT, owner TEXT,
  owner_email TEXT, due_at TEXT, status TEXT, last_update TEXT, reminded_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    # ponytail: connection per call, fine for one operator; pool if it ever matters
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with db() as c:
        c.executescript(SCHEMA)


def rows(sql: str, *args) -> list[dict]:
    with db() as c:
        return [dict(r) for r in c.execute(sql, args)]


def row(sql: str, *args) -> dict | None:
    r = rows(sql, *args)
    return r[0] if r else None


def execute(sql: str, *args) -> int:
    with db() as c:
        return c.execute(sql, args).lastrowid


def meeting_detail(meeting_id: int) -> dict | None:
    m = row("SELECT * FROM meetings WHERE id=?", meeting_id)
    if not m:
        return None
    m["mom"] = json.loads(m.pop("mom_json") or "null")
    for key, sql in {
        "attendees": "SELECT name, email FROM attendees WHERE meeting_id=?",
        "participants": "SELECT name, joined_at, left_at FROM participants WHERE meeting_id=? ORDER BY id",
        "transcript": "SELECT speaker, text, ts, addressed FROM utterances WHERE meeting_id=? ORDER BY id",
        "chat": "SELECT sender, text, ts, is_amber FROM chat WHERE meeting_id=? ORDER BY id",
        "tasks": "SELECT * FROM tasks WHERE meeting_id=? ORDER BY id",
        "record_notes": "SELECT * FROM record_notes WHERE meeting_id=? ORDER BY id",
    }.items():
        m[key] = rows(sql, meeting_id)
    return m
