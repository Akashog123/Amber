"""Amber Live backend. Run: uv run uvicorn main:app --reload --port 8000"""
import asyncio
import json
import os
import re
import time
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import db  # noqa: E402
import recall  # noqa: E402
import brain  # noqa: E402
import seed  # noqa: E402
import voice  # noqa: E402

app = FastAPI(title="Amber Live")
seed.seed()  # creates tables + mock records; idempotent
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
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


QUESTION = re.compile(r"\b(can you|could you|would you|tell me|what|what's|who|whose|when|where|how|which|"
                      r"why|is there|are there|do we|did we|status|update|please|give me|check)\b", re.I)
_SOUNDEX = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"),
            "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}


def _soundex_tail(word: str) -> str:
    """Soundex digits after the first letter ("amber" -> "516"; v sounds like b, so "i'm very" -> "516")."""
    out, prev = "", _SOUNDEX.get(word[0], "")
    for ch in word[1:]:
        code = _SOUNDEX.get(ch, "")
        if code and code != prev:
            out += code
        if ch not in "hw":
            prev = code
    return out[:3]


def is_addressed(text: str) -> bool:
    if WAKE.search(text):
        return True
    # Streaming ASR mangles the name ("hey amber" -> "hey i'm very"). Fuzzy-match only near the
    # start and only for request-shaped lines, so "I am very sure" doesn't summon Amber.
    words = re.sub(r"[^a-z ]", "", text.lower()).split()[:4]
    candidates = words + [a + b for a, b in zip(words, words[1:])]
    sounds_like = any(c[0] in "aeiouh" and _soundex_tail(c) == "516" for c in candidates)  # "hamburger"
    return sounds_like and bool(QUESTION.search(text))


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
    if bot_id and not bot_id.startswith("replay-"):
        # Raw payloads per bot, for checking real shapes against replay.py (logs/ is gitignored).
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, f"recall-{bot_id}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    m = db.row("SELECT id FROM meetings WHERE bot_id=?", bot_id)
    if not m:
        return {"ignored": "unknown bot"}
    handle_event(m["id"], event, data)
    return {"ok": True}


def handle_event(mid: int, event: str, data: dict):
    inner = data.get("data") or {}
    who = (inner.get("participant") or {}).get("name") or "Unknown"
    ts = (inner.get("timestamp") or {}).get("absolute") or db.now()
    if who == "Amber" and event in ("transcript.data", "transcript.partial_data", "participant_events.chat_message"):
        return  # our own voice / chat echoed back

    if event == "transcript.partial_data":
        yield_floor(mid)
    elif event == "transcript.data":
        words = inner.get("words") or []
        text = " ".join(w["text"] for w in words).strip()
        if not text:
            return
        start = (words[0].get("start_timestamp") or {}).get("relative")
        addressed = is_addressed(text)
        db.execute("INSERT INTO utterances (meeting_id,speaker,text,ts,addressed) VALUES (?,?,?,?,?)",
                   mid, who, text, start, int(addressed))
        publish("transcript", mid, {"speaker": who, "text": text, "ts": start, "addressed": addressed})
        yield_floor(mid)
        on_speech(mid, who, text, addressed)
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
        if is_addressed(text) and not CANCEL.search(text):
            _spawn(_reply(mid, who, {"parts": [text]}, delay=0, via_chat=True))
    elif event.startswith("bot."):
        # Status webhooks (configured in the Recall dashboard): bot.joining_call, bot.in_call_recording, bot.done ...
        _set_status(mid, event.removeprefix("bot."))


# --- live answering ----------------------------------------------------------
# Amber speaks only when addressed. The asker's question is buffered until they stop
# talking for DEBOUNCE seconds; if they keep talking (rephrasing, changing their mind)
# the pending answer is cancelled and rebuilt from everything they said.
DEBOUNCE = float(os.getenv("AMBER_DEBOUNCE", "1.0"))
CORRECTION = re.compile(r"\b(actually|i mean|sorry|instead|rather|wait)\b", re.I)
CANCEL = re.compile(r"\b(never ?mind|forget it|cancel that|scratch that|no worries)\b", re.I)
pending: dict[tuple[int, str], dict] = {}  # (meeting, speaker) -> {"parts": [...], "task": Task}
speaking_until: dict[int, float] = {}       # meeting -> monotonic time Amber's audio ends
FOLLOWUP = float(os.getenv("AMBER_FOLLOWUP", "10"))  # seconds after a reply the asker can follow up
followup: dict[int, tuple[str, float]] = {}  # meeting -> (last asker, follow-up window end)
_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tasks.add(t)  # keep a reference so the task isn't garbage-collected mid-flight
    t.add_done_callback(_tasks.discard)
    return t


def on_speech(mid: int, speaker: str, text: str, addressed: bool):
    key = (mid, speaker)
    q = pending.get(key)
    if CANCEL.search(text):
        if q:
            q["task"].cancel()
            pending.pop(key)
            publish("amber.cancelled", mid, {"speaker": speaker})
        return
    who, until = followup.get(mid, ("", 0))
    if not addressed and who == speaker and time.monotonic() < until and QUESTION.search(text):
        addressed = True  # follow-up to Amber's last answer; no need to say her name again
    if not (addressed or q):
        return
    if q and q.get("generating") and not (addressed or CORRECTION.search(text)):
        return  # answer already in flight; the asker moving on doesn't rewrite it
    if q:
        q["task"].cancel()  # asker is still talking -> restart with the fuller question
    q = q or {"parts": []}
    q["parts"].append(text)
    q["task"] = _spawn(_reply(mid, speaker, q, delay=DEBOUNCE, key=key))
    pending[key] = q


def _real_bot(mid: int) -> str | None:
    bot = (db.row("SELECT bot_id FROM meetings WHERE id=?", mid) or {}).get("bot_id")
    return bot if recall.enabled() and bot and not bot.startswith("replay-") else None


def yield_floor(mid: int):
    """A human started talking while Amber's audio is playing -> stop it."""
    if time.monotonic() < speaking_until.get(mid, 0):
        speaking_until[mid] = 0
        if bot := _real_bot(mid):
            _spawn(recall.stop_audio(bot))
        publish("amber.yielded", mid, {})


async def _reply(mid: int, speaker: str, q: dict, delay: float, via_chat=False, key=None):
    await asyncio.sleep(delay)
    q["generating"] = True
    question = " ".join(q["parts"])
    t0 = time.perf_counter()
    try:
        text = await brain.answer(mid, speaker, question)
    except Exception as e:  # every model failed: say so instead of going silent
        print(f"[amber] reply failed: {e!r}")
        publish("amber.error", mid, {"question": question, "error": str(e)})
        text = brain.SORRY
    t_llm = time.perf_counter()
    try:
        mp3 = None if via_chat or not os.getenv("ELEVENLABS_API_KEY") else await voice.tts(text)
    except Exception as e:
        print(f"[amber] tts failed: {e!r}")
        publish("amber.error", mid, {"question": question, "error": f"tts: {e}"})
        mp3 = None
    t_tts = time.perf_counter()
    if key and pending.get(key) is q:
        pending.pop(key)  # committed: later speech no longer rewrites this answer
    bot = _real_bot(mid)
    if via_chat:
        db.execute("INSERT INTO chat (meeting_id,sender,text,ts,is_amber) VALUES (?,?,?,?,1)", mid, "Amber", text, db.now())
        if bot:
            await recall.send_chat(bot, text)
    else:
        db.execute("INSERT INTO utterances (meeting_id,speaker,text,ts,addressed) VALUES (?,?,?,?,0)",
                   mid, "Amber", text, None)
        if bot and mp3:
            await recall.output_audio(bot, mp3)
        if mp3:
            speaking_until[mid] = time.monotonic() + len(mp3) / 16000  # 128 kbps = 16 KB/s
        followup[mid] = (speaker, max(speaking_until.get(mid, 0), time.monotonic()) + FOLLOWUP)
    latency = {"llm": round(t_llm - t0, 2), "tts": round(t_tts - t_llm, 2), "total": round(time.perf_counter() - t0, 2)}
    print(f"[amber] {speaker}: {question!r} -> {text!r} {latency}")
    publish("amber.reply", mid, {"to": speaker, "question": question, "text": text,
                                 "via": "chat" if via_chat else "voice", "latency": latency})
