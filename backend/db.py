import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

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
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, kind TEXT, to_addr TEXT, subject TEXT, html TEXT, text TEXT,
  status TEXT, error TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, meeting_id INTEGER, series_id TEXT, title TEXT, owner TEXT,
  owner_email TEXT, due_at TEXT, status TEXT, last_update TEXT, reminded_at TEXT, quote TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def team_tz():
    """The team's timezone for due dates ("by Friday"), 09:00 reminders and typed meeting times. AMBER_TZ is a UTC
    offset ("+05:30"; India has no DST, and Windows Python ships no zone database); unset = this machine's zone,
    which is wrong on a UTC cloud server."""
    m = re.fullmatch(r"([+-]?)(\d{1,2})(?::?(\d{2}))?", os.getenv("AMBER_TZ", "").strip())
    if not m:
        return datetime.now().astimezone().tzinfo
    off = timedelta(hours=int(m[2]), minutes=int(m[3] or 0))
    return timezone(-off if m[1] == "-" else off)


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
        # ponytail: hand-rolled migrations for DBs created before these columns; use a migration tool past a few
        for table, col, kind in [("tasks", "quote", "TEXT"), ("meetings", "recording_paused", "INTEGER DEFAULT 0"),
                                 ("meetings", "join_at", "TEXT"), ("meetings", "extracted_upto", "INTEGER DEFAULT 0"),
                                 ("utterances", "off_record", "INTEGER DEFAULT 0"),
                                 ("record_notes", "edited_at", "TEXT")]:
            if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")


def rows(sql: str, *args) -> list[dict]:
    with db() as c:
        return [dict(r) for r in c.execute(sql, args)]


def row(sql: str, *args) -> dict | None:
    r = rows(sql, *args)
    return r[0] if r else None


def execute(sql: str, *args) -> int:
    with db() as c:
        return c.execute(sql, args).lastrowid


def execute_count(sql: str, *args) -> int:
    """Run an UPDATE/DELETE and return how many rows it touched."""
    with db() as c:
        return c.execute(sql, args).rowcount


def meeting_detail(meeting_id: int) -> dict | None:
    m = row("SELECT * FROM meetings WHERE id=?", meeting_id)
    if not m:
        return None
    m["mom"] = json.loads(m.pop("mom_json") or "null")
    for key, sql in {
        "attendees": "SELECT name, email FROM attendees WHERE meeting_id=?",
        "participants": "SELECT name, joined_at, left_at FROM participants WHERE meeting_id=? ORDER BY id",
        "transcript": "SELECT speaker, text, ts, addressed FROM utterances WHERE meeting_id=? AND off_record=0 ORDER BY id",
        "chat": "SELECT sender, text, ts, is_amber FROM chat WHERE meeting_id=? ORDER BY id",
        "tasks": "SELECT * FROM tasks WHERE meeting_id=? ORDER BY id",
        "record_notes": "SELECT * FROM record_notes WHERE meeting_id=? ORDER BY id",
    }.items():
        m[key] = rows(sql, meeting_id)
    # Amber's open question (hand raised) until someone answers it
    m["hand_raised"] = (row("SELECT question FROM pending_confirmations WHERE meeting_id=? AND resolved=0 "
                            "ORDER BY id DESC LIMIT 1", meeting_id) or {}).get("question")
    return m
