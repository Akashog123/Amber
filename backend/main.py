"""Amber Live backend. Run: uv run uvicorn main:app --reload --port 8000"""
import asyncio
import json
import os
import re
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import db  # noqa: E402
import recall  # noqa: E402
import seed  # noqa: E402

app = FastAPI(title="Amber Live")
seed.seed()  # creates tables + mock records; idempotent
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
# ASR often mishears the name; chat may also start with "@Amber".
WAKE = re.compile(r"\b(amber|ember|amba|ambar|umber)\b", re.I)
PLATFORMS = {"meet.google.com": "google_meet", "zoom.us": "zoom", "teams.microsoft.com": "microsoft_teams",
             "teams.live.com": "microsoft_teams"}

# --- realtime fan-out to the dashboard (SSE) ---------------------------------
# ponytail: in-process queues, single uvicorn worker only; Redis pub/sub if we ever scale
subscribers: set[asyncio.Queue] = set()


def publish(type_: str, meeting_id: int | None, data: dict):
    msg = {"type": type_, "meeting_id": meeting_id, "data": data}
    for q in list(subscribers):
        q.put_nowait(msg)


def is_addressed(text: str) -> bool:
    return bool(WAKE.search(text))


def detect_platform(url: str) -> str | None:
    p = urlparse(url)
    if p.scheme != "https":
        return None
    host = p.hostname or ""
    return next((v for k, v in PLATFORMS.items() if host == k or host.endswith("." + k)), None)


# --- operator API ------------------------------------------------------------
class Attendee(BaseModel):
    name: str
    email: str = ""


class Dispatch(BaseModel):
    title: str
    url: str
    agenda: str = ""
    context: str = ""
    attendees: list[Attendee] = []
    series_id: str | None = None
    replay: bool = False  # skip Recall; events come from replay.py


@app.post("/api/meetings/dispatch")
async def dispatch(body: Dispatch):
    platform = detect_platform(body.url)
    if not platform:
        raise HTTPException(400, "Unsupported meeting URL (Google Meet, Zoom or Teams https link).")
    mid = db.execute(
        "INSERT INTO meetings (series_id,title,url,platform,agenda,context_text,status,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        body.series_id, body.title, body.url, platform, body.agenda, body.context, "queued", db.now())
    with db.db() as c:
        c.executemany("INSERT INTO attendees VALUES (?,?,?)", [(mid, a.name, a.email) for a in body.attendees])
    if recall.enabled() and not body.replay:
        hook = f"{os.environ['PUBLIC_URL'].rstrip('/')}/webhooks/recall?token={WEBHOOK_TOKEN}"
        try:
            bot_id = await recall.create_bot(body.url, hook)
        except Exception as e:
            db.execute("UPDATE meetings SET status='failed' WHERE id=?", mid)
            raise HTTPException(502, f"Recall bot creation failed: {e}")
        status = "joining"
    else:
        bot_id, status = f"replay-{uuid4().hex[:8]}", "replay"  # no key: drive it with replay.py
    db.execute("UPDATE meetings SET bot_id=?, status=? WHERE id=?", bot_id, status, mid)
    publish("meeting.status", mid, {"status": status})
    return {"id": mid, "bot_id": bot_id, "status": status}


@app.get("/api/meetings")
async def list_meetings():
    return db.rows("SELECT id,series_id,title,url,platform,status,started_at,ended_at,created_at "
                   "FROM meetings ORDER BY id DESC")


@app.get("/api/meetings/{mid}")
async def get_meeting(mid: int):
    return db.meeting_detail(mid) or _404()


@app.post("/api/meetings/{mid}/stop")
async def stop(mid: int):
    m = db.row("SELECT bot_id FROM meetings WHERE id=?", mid) or _404()
    if recall.enabled() and m["bot_id"] and not m["bot_id"].startswith("replay-"):
        await recall.leave(m["bot_id"])
    _set_status(mid, "ended")
    return {"ok": True}


@app.get("/api/records")
async def list_records():
    recs = db.rows("SELECT * FROM records ORDER BY id")
    notes = db.rows("SELECT * FROM record_notes ORDER BY id")
    for r in recs:
        r["notes"] = [n for n in notes if n["record_id"] == r["id"]]
    return recs


@app.get("/api/events")
async def events():
    q: asyncio.Queue = asyncio.Queue()
    subscribers.add(q)

    async def stream():
        try:
            while True:
                yield f"data: {json.dumps(await q.get())}\n\n"
        finally:
            subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _404():
    raise HTTPException(404, "Not found")


def _set_status(mid: int, status: str):
    col = {"in_call_recording": "started_at", "ended": "ended_at", "done": "ended_at"}.get(status)
    db.execute(f"UPDATE meetings SET status=?{f', {col}=COALESCE({col}, ?)' if col else ''} WHERE id=?",
               *([status, db.now(), mid] if col else [status, mid]))
    publish("meeting.status", mid, {"status": status})


# --- Recall webhooks ---------------------------------------------------------
@app.post("/webhooks/recall")
async def recall_webhook(request: Request):
    # ponytail: shared URL token instead of Svix signature verification; fine for a POC tunnel
    if WEBHOOK_TOKEN and request.query_params.get("token") != WEBHOOK_TOKEN:
        raise HTTPException(401)
    payload = await request.json()
    event, data = payload.get("event", ""), payload.get("data") or {}
    bot_id = (data.get("bot") or {}).get("id")
    m = db.row("SELECT id FROM meetings WHERE bot_id=?", bot_id)
    if not m:
        return {"ignored": "unknown bot"}
    handle_event(m["id"], event, data)
    return {"ok": True}


def handle_event(mid: int, event: str, data: dict):
    inner = data.get("data") or {}
    who = (inner.get("participant") or {}).get("name") or "Unknown"
    ts = (inner.get("timestamp") or {}).get("absolute") or db.now()

    if event == "transcript.data":
        words = inner.get("words") or []
        text = " ".join(w["text"] for w in words).strip()
        if not text:
            return
        start = (words[0].get("start_timestamp") or {}).get("relative")
        addressed = is_addressed(text)
        db.execute("INSERT INTO utterances (meeting_id,speaker,text,ts,addressed) VALUES (?,?,?,?,?)",
                   mid, who, text, start, int(addressed))
        publish("transcript", mid, {"speaker": who, "text": text, "ts": start, "addressed": addressed})
    elif event == "participant_events.join":
        db.execute("INSERT INTO participants (meeting_id,name,joined_at) VALUES (?,?,?)", mid, who, ts)
        publish("participant.join", mid, {"name": who, "at": ts})
    elif event == "participant_events.leave":
        db.execute("UPDATE participants SET left_at=? WHERE id=(SELECT MAX(id) FROM participants "
                   "WHERE meeting_id=? AND name=? AND left_at IS NULL)", ts, mid, who)
        publish("participant.leave", mid, {"name": who, "at": ts})
    elif event == "participant_events.chat_message":
        text = (inner.get("data") or {}).get("text", "")
        db.execute("INSERT INTO chat (meeting_id,sender,text,ts,is_amber) VALUES (?,?,?,?,0)", mid, who, text, ts)
        publish("chat", mid, {"sender": who, "text": text, "at": ts, "addressed": is_addressed(text)})
    elif event.startswith("bot."):
        # Status webhooks (configured in the Recall dashboard): bot.joining_call, bot.in_call_recording, bot.done ...
        _set_status(mid, event.removeprefix("bot."))
