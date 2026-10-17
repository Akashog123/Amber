"""Amber Live backend. Run: uv run uvicorn main:app --reload --port 8000"""
import asyncio
import base64
import json
import os
import re
import sys
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()
# Hindi / ✋ in log lines must never crash a reply on a Windows console (cp1252).
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(errors="backslashreplace")

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import db  # noqa: E402
import documents  # noqa: E402
import recall  # noqa: E402
import brain  # noqa: E402
import mailer  # noqa: E402
import seed  # noqa: E402
import voice  # noqa: E402
from turns import (CANCEL, CORRECTION, HINDI, QUESTION, WAKE, Conversation, has_content, question_pending,  # noqa: E402
                   route)

@asynccontextmanager
async def lifespan(_app):
    loop_task = asyncio.create_task(background_loop())  # reminders + bot status polling
    yield
    loop_task.cancel()


app = FastAPI(title="Amber Live", lifespan=lifespan)
seed.seed()  # creates tables + mock records; idempotent
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
# The public tunnel exists for Recall's webhooks only; the operator API stays local (the dashboard proxies to it).
PUBLIC_PATHS = ("/webhooks/", "/ws/", "/media/")  # /media/: the page Recall renders as Amber's camera + voice


@app.middleware("http")
async def local_only(request: Request, call_next):
    # cloudflared/ngrok forward from localhost, so the client IP alone can't tell; their forwarding headers can.
    forwarded = any(h in request.headers for h in ("cf-connecting-ip", "x-forwarded-for", "ngrok-trace-id"))
    if forwarded and not request.url.path.startswith(PUBLIC_PATHS):
        return JSONResponse({"detail": "The operator API is only available locally."}, status_code=403)
    return await call_next(request)
PLATFORMS = {"meet.google.com": "google_meet", "zoom.us": "zoom", "teams.microsoft.com": "microsoft_teams",
             "teams.live.com": "microsoft_teams"}

# --- realtime fan-out to the dashboard (SSE) ---------------------------------
# ponytail: in-process queues, single uvicorn worker only; Redis pub/sub if we ever scale
subscribers: set[asyncio.Queue] = set()


def publish(type_: str, meeting_id: int | None, data: dict):
    msg = {"type": type_, "meeting_id": meeting_id, "data": data}
    for q in list(subscribers):
        q.put_nowait(msg)


_soundex_tail = brain.soundex_tail  # "amber" -> "516"; v sounds like b, so "i'm very" -> "516"

def is_addressed(text: str) -> bool:
    if WAKE.search(text):
        return True
    # Streaming ASR mangles the name ("hey amber" -> "hey i'm very"). Fuzzy-match only near the
    # start and only for request-shaped lines, so "I am very sure" doesn't summon Amber.
    words = re.sub(r"[^a-z ]", "", text.lower()).split()[:4]
    candidates = words + [a + b for a, b in zip(words, words[1:])]
    sounds_like = any(c[0] in "aeiouh" and _soundex_tail(c) == "516" for c in candidates)  # "hamburger"
    return sounds_like and bool(QUESTION.search(text))


def keyterms(mid: int) -> list[str]:
    """Words the transcriber should expect: Amber's name first, then attendees, record IDs, names and owners."""
    terms = ["Amber"]
    terms += [a["name"] for a in db.rows("SELECT name FROM attendees WHERE meeting_id=?", mid)]
    recs = db.rows("SELECT id, name, aliases, owner FROM records ORDER BY id")
    terms += [r["id"] for r in recs]
    # Aliases are how people actually say it ("pump seals" was heard as "pump sales"); names and owners next.
    terms += [a for r in recs for a in (r["aliases"] or "").split(",")]
    for r in recs:
        terms += [r["name"], r["owner"]]
    return list(dict.fromkeys(t.strip() for t in terms if t and t.strip()))


def normalize_url(url: str) -> str:
    """People paste "meet.google.com/abc-defg-hij" without the scheme."""
    url = url.strip()
    return url if "://" in url else f"https://{url}"


def detect_platform(url: str) -> str | None:
    p = urlparse(normalize_url(url))
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
    document_name: str = ""
    document_b64: str = ""  # PDF / DOCX / TXT, base64; its text becomes part of Amber's context
    join_at: str | None = None  # ISO time for a scheduled meeting; Recall sends Amber in then (empty = now)


VOICE_MODE = os.getenv("AMBER_VOICE_MODE", "mp3")  # stream = Output Media page (streamed voice, instant stop)
EMAIL = re.compile(r"^[^@\s,<>]+@[^@\s,<>]+\.[a-z]{2,}$", re.I)
SCREEN_VISION = os.getenv("AMBER_SCREEN_VISION", "") == "1"


def _join_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "join_at must be an ISO date-time.")
    when = when if when.tzinfo else when.astimezone()  # naive = the operator's local time
    now = datetime.now(timezone.utc)
    if when < now - timedelta(minutes=5):
        raise HTTPException(400, "That meeting time is in the past.")
    # Recall needs ~10 minutes of lead time to schedule; anything sooner just joins now.
    return when.astimezone(timezone.utc).isoformat() if when > now + timedelta(minutes=10) else None


@app.post("/api/meetings/dispatch")
async def dispatch(body: Dispatch):
    body.url = normalize_url(body.url)
    platform = detect_platform(body.url)
    if not platform:
        raise HTTPException(400, "Unsupported meeting URL (Google Meet, Zoom or Teams https link).")
    bad = [a.email for a in body.attendees if a.email.strip() and not EMAIL.match(a.email.strip())]
    if bad:
        raise HTTPException(400, f"Invalid attendee email: {', '.join(bad)}")
    body.attendees = [Attendee(name=a.name.strip() or a.email.split("@")[0], email=a.email.strip())
                      for a in body.attendees if a.name.strip() or a.email.strip()]
    body.title = body.title.strip() or "Meeting"
    join_at = _join_at(body.join_at)
    context = body.context
    if body.document_b64:
        try:
            text = documents.extract_text(body.document_name, body.document_b64)
            context += f"\n\nDOCUMENT ({body.document_name}):\n{text}"
        except Exception as e:
            raise HTTPException(400, f"Could not read the document: {e}")
    mid = db.execute(
        "INSERT INTO meetings (series_id,title,url,platform,agenda,context_text,status,created_at,join_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        body.series_id, body.title, body.url, platform, body.agenda, context.strip(), "queued", db.now(), join_at)
    with db.db() as c:
        c.executemany("INSERT INTO attendees VALUES (?,?,?)", [(mid, a.name, a.email) for a in body.attendees])
    if recall.enabled() and not body.replay:
        if not os.getenv("PUBLIC_URL", "").startswith("https://"):
            db.execute("UPDATE meetings SET status='failed' WHERE id=?", mid)
            raise HTTPException(500, "PUBLIC_URL (the https tunnel to this backend) is not set in backend/.env.")
        base = os.environ["PUBLIC_URL"].rstrip("/")
        hook = f"{base}/webhooks/recall?token={WEBHOOK_TOKEN}"
        ws = f"{base.replace('https://', 'wss://', 1)}/ws/recall?token={WEBHOOK_TOKEN}" if SCREEN_VISION else None
        page = f"{base}/media/amber?m={mid}&token={WEBHOOK_TOKEN}" if VOICE_MODE == "stream" else None
        try:
            bot_id = await recall.create_bot(body.url, hook, keyterms(mid), ws, join_at, page)
        except Exception as e:
            db.execute("UPDATE meetings SET status='failed' WHERE id=?", mid)
            detail = getattr(getattr(e, "response", None), "text", "") or str(e)
            raise HTTPException(502, f"Recall bot creation failed: {detail[:300]}")
        status = "scheduled" if join_at else "joining"
    else:
        bot_id, status = f"replay-{uuid4().hex[:8]}", "replay"  # no key: drive it with replay.py
    db.execute("UPDATE meetings SET bot_id=?, status=? WHERE id=?", bot_id, status, mid)
    publish("meeting.status", mid, {"status": status})
    if os.getenv("ELEVENLABS_API_KEY") and not join_at:
        _spawn(voice.warm_fillers(VOICE_MODE == "stream"))  # synthesize + cache fillers before anyone asks anything
    return {"id": mid, "bot_id": bot_id, "status": status}


@app.get("/api/meetings")
async def list_meetings():
    return db.rows("SELECT id,series_id,title,url,platform,status,started_at,ended_at,created_at,join_at,"
                   "recording_paused FROM meetings ORDER BY id DESC")


@app.get("/api/meetings/{mid}")
async def get_meeting(mid: int):
    m = db.meeting_detail(mid) or _404()
    if _real_bot(mid) and m["status"] in TERMINAL - {"cancelled", "failed"}:
        m["recording_url"] = f"/api/meetings/{mid}/recording"  # resolved to a fresh Recall link when played
    return m


@app.post("/api/meetings/{mid}/stop")
async def stop(mid: int):
    m = db.row("SELECT bot_id, status FROM meetings WHERE id=?", mid) or _404()
    if m["status"] in TERMINAL:
        return {"ok": True}  # already over; don't rerun the post-meeting pipeline
    bot = _real_bot(mid)
    if m["status"] == "scheduled":  # hasn't joined yet: cancel instead of producing an empty recap
        if bot:
            try:
                await recall.delete_bot(bot)
            except Exception as e:
                print(f"[stop] cancel bot {bot}: {e!r}")
        _set_plain_status(mid, "cancelled")
        return {"ok": True}
    if bot:
        try:
            await recall.leave(bot)
        except Exception as e:  # already left / kicked: still close the meeting out on our side
            print(f"[stop] leave bot {bot}: {e!r}")
    _set_status(mid, "ended")
    return {"ok": True}


@app.get("/api/meetings/{mid}/recording")
async def recording(mid: int):
    """Recall's download links are pre-signed and expire, so fetch a fresh one each time the video is opened."""
    db.row("SELECT id FROM meetings WHERE id=?", mid) or _404()
    bot = _real_bot(mid)
    url = await recall.recording_url(bot) if bot else None
    if not url:
        raise HTTPException(404, "No recording yet (Recall takes a minute or two after the call ends).")
    return RedirectResponse(url)


@app.post("/api/meetings/{mid}/recording/{action}")
async def recording_control(mid: int, action: str):
    if action not in ("pause", "resume"):
        _404()
    db.row("SELECT id FROM meetings WHERE id=?", mid) or _404()
    return {"paused": await set_recording(mid, action == "pause")}


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
                try:
                    yield f"data: {json.dumps(await asyncio.wait_for(q.get(), 15))}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keeps proxies from closing an idle stream
        finally:
            subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _404():
    raise HTTPException(404, "Not found")


CALL_OVER = {"done", "ended", "call_ended", "fatal"}  # fatal = kicked / never admitted: still close it out
TERMINAL = CALL_OVER | {"processing", "completed", "cancelled", "failed", "recording_done", "analysis_done"}


def _set_status(mid: int, status: str):
    prev = (db.row("SELECT status FROM meetings WHERE id=?", mid) or {}).get("status")
    if prev in ("processing", "completed", "cancelled") and status in TERMINAL:
        return  # late bot.done / recording_done after the recap: keep "completed"
    col = {"in_call_recording": "started_at", "ended": "ended_at", "done": "ended_at", "call_ended": "ended_at",
           "fatal": "ended_at"}.get(status)
    db.execute(f"UPDATE meetings SET status=?{f', {col}=COALESCE({col}, ?)' if col else ''} WHERE id=?",
               *([status, db.now(), mid] if col else [status, mid]))
    publish("meeting.status", mid, {"status": status})
    if status == "joining_call" and prev == "scheduled" and os.getenv("ELEVENLABS_API_KEY"):
        _spawn(voice.warm_fillers(VOICE_MODE == "stream"))  # scheduled bot is on its way in
    if status in CALL_OVER and prev not in CALL_OVER:
        _spawn(final_extract(mid))
        forget(mid)


def forget(mid: int):
    """Drop a finished meeting's live-call state (pending questions, playback clocks, screen frames)."""
    for q in (convs.pop(mid, None) or Conversation()).pending.values():
        if q.get("task"):
            q["task"].cancel()
    for d in (filler_until, last_filler, speaking_until, since_extract, screens, voice_locks):
        d.pop(mid, None)


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


@app.websocket("/ws/recall")
async def recall_ws(ws: WebSocket):
    """Screen-share frames (AMBER_SCREEN_VISION=1). Recall streams 2 fps PNGs of every video; only the latest
    screen share per meeting is kept, and it's only looked at when someone asks Amber about the screen."""
    if WEBHOOK_TOKEN and ws.query_params.get("token") != WEBHOOK_TOKEN:
        await ws.close(code=1008)
        return
    await ws.accept()
    meeting_of: dict[str, int | None] = {}
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            try:
                payload = json.loads(msg.get("text") or (msg.get("bytes") or b"{}").decode())
            except ValueError:
                continue
            data = payload.get("data") or {}
            inner = data.get("data") or {}
            if payload.get("event") != "video_separate_png.data" or inner.get("type") != "screenshare":
                continue
            bot_id = (data.get("bot") or {}).get("id")
            if bot_id not in meeting_of:
                meeting_of[bot_id] = (db.row("SELECT id FROM meetings WHERE bot_id=?", bot_id) or {}).get("id")
            if (mid := meeting_of[bot_id]) and inner.get("buffer"):
                if mid not in screens or time.monotonic() - screens[mid][1] > SCREEN_FRESH:
                    who = (inner.get("participant") or {}).get("name") or "Someone"
                    publish("screen.shared", mid, {"by": who})
                screens[mid] = (inner["buffer"], time.monotonic())
    except WebSocketDisconnect:
        pass


def handle_event(mid: int, event: str, data: dict):
    inner = data.get("data") or {}
    who = (inner.get("participant") or {}).get("name") or "Unknown"
    ts = (inner.get("timestamp") or {}).get("absolute") or db.now()
    if who == "Amber" and event in ("transcript.data", "transcript.partial_data", "participant_events.chat_message"):
        return  # our own voice / chat echoed back

    if event == "transcript.partial_data":
        # A real interruption, not a cough or "mm": two words, or one long one ("Wait", "Stop" count too).
        if interrupts(inner.get("words") or []):
            yield_floor(mid)
        conv(mid).talking_since.setdefault(who, time.monotonic())
        still_talking(mid, who)
    elif event == "transcript.data":
        words = inner.get("words") or []
        text = " ".join(w["text"] for w in words).strip()
        if not text:
            return
        start = (words[0].get("start_timestamp") or {}).get("relative")
        now = time.monotonic()
        began = conv(mid).talking_since.pop(who, now)
        began = began if now - began < STALE_TALK else now  # a partial whose final never came
        if start is not None and db.row("SELECT id FROM utterances WHERE meeting_id=? AND speaker=? AND ts=? AND text=?",
                                        mid, who, start, text):
            return  # Recall re-delivered a webhook: storing (and answering) it twice would be wrong
        addressed = is_addressed(text)
        db.execute("INSERT INTO utterances (meeting_id,speaker,text,ts,addressed) VALUES (?,?,?,?,?)",
                   mid, who, text, start, int(addressed))
        publish("transcript", mid, {"speaker": who, "text": text, "ts": start, "addressed": addressed})
        yield_floor(mid)
        # "Amber, the first one" / "PO-1046" may answer her confirmation question instead of asking a new one.
        if addressed and command(mid, who, text):
            pass
        elif not ((addressed or RECORD_ID.search(text) or time.monotonic() < conv(mid).record_answer_until)
                  and resolve_confirmation(mid, who, text)):
            on_speech(mid, who, text, addressed, at=began)
        maybe_extract(mid)
    elif event == "participant_events.join":
        db.execute("INSERT INTO participants (meeting_id,name,joined_at) VALUES (?,?,?)", mid, who, ts)
        publish("participant.join", mid, {"name": who, "at": ts})
    elif event == "participant_events.leave":
        db.execute("UPDATE participants SET left_at=? WHERE id=(SELECT MAX(id) FROM participants "
                   "WHERE meeting_id=? AND name=? AND left_at IS NULL)", ts, mid, who)
        publish("participant.leave", mid, {"name": who, "at": ts})
    elif event == "participant_events.chat_message":
        text = (inner.get("data") or {}).get("text", "")
        if (inner.get("timestamp") or {}).get("absolute") and db.row(
                "SELECT id FROM chat WHERE meeting_id=? AND sender=? AND ts=? AND text=?", mid, who, ts, text):
            return  # re-delivered webhook
        db.execute("INSERT INTO chat (meeting_id,sender,text,ts,is_amber) VALUES (?,?,?,?,0)", mid, who, text, ts)
        publish("chat", mid, {"sender": who, "text": text, "at": ts, "addressed": is_addressed(text)})
        with suppress(ValueError, TypeError):
            lag = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
            if lag > 2:
                print(f"[chat] {who}'s message arrived {lag:.1f}s after it was sent")
        if is_addressed(text) and command(mid, who, text, via_chat=True):
            return
        if resolve_confirmation(mid, who, text):
            return
        if is_addressed(text) and not CANCEL.search(text):
            _spawn(_reply(mid, who, {"parts": [text]}, delay=0, via_chat=True))
    elif event.startswith("bot."):
        # Status webhooks (configured in the Recall dashboard): bot.joining_call, bot.in_call_recording, bot.done ...
        _set_status(mid, event.removeprefix("bot."))


# --- live answering ----------------------------------------------------------
# Amber speaks only when spoken to. Who she's talking with and what she's waiting for lives in one Conversation
# per meeting (turns.py); every line is routed against it there. A question is buffered until the asker stops
# talking for DEBOUNCE seconds; if they keep talking the pending answer is rebuilt from everything they said.
DEBOUNCE = float(os.getenv("AMBER_DEBOUNCE", "0.7"))
BARE_WAIT = float(os.getenv("AMBER_BARE_WAIT", "2.0"))  # just "Amber" so far: wait longer for the question
FILLER_OVERLAP = float(os.getenv("AMBER_FILLER_OVERLAP", "0.3"))  # start the answer this early (Recall lag)
# A filler only covers a real wait: it plays if the answer isn't ready this many seconds after generation started
# (live, "Let me check." before every 1-2 s answer made each reply slower and robotic), and at most once per
# FILLER_GAP seconds, so a quick back-and-forth never hears "let me check" every turn.
FILLER_AFTER = float(os.getenv("AMBER_FILLER_AFTER", "1.2"))
FILLER_GAP = float(os.getenv("AMBER_FILLER_GAP", "15"))
last_filler: dict[int, float] = {}  # meeting -> monotonic time of her last filler
NO_FILLER = re.compile(r"\b(are you there|you there|can you hear me|hear me|audible|how are you|thank|thanks|"
                       r"good morning|who are you|who made you|who built you|what are you)\b", re.I)
LOOKUP = re.compile(r"\b(status|orders?|ordered|owns?|owner|who|when|where|records?|po|deliver\w*|inspection|"
                    r"contracts?|eta|arriv\w*|budget|agenda|update|discuss\w*|said|say|how many|which|tasks?|due)\b",
                    re.I)
STOP_WORDS = re.compile(r"^(no|stop|wait|hold|amber|रुको|रुकिए)\W*$", re.I)
BARGE_IN_SEC = float(os.getenv("AMBER_BARGE_IN_SEC", "0.7"))  # this much continuous speech = an interruption


def interrupts(words: list[dict]) -> bool:
    """Someone talking over Amber, judged by how long they've been speaking (any language): a "yeah" or "mm"
    is ~0.3s, a real interruption keeps going. "Stop" / "wait" count at once."""
    if any(STOP_WORDS.match(w.get("text", "").strip(".,!?")) for w in words):
        return True
    try:
        spoken = words[-1]["end_timestamp"]["relative"] - words[0]["start_timestamp"]["relative"]
    except (IndexError, KeyError, TypeError):
        return len(words) >= 3  # no timings: fall back to length
    return spoken >= BARGE_IN_SEC
RECORD_CMD = re.compile(r"\b(stop|pause|halt|start|resume|restart|continue|unpause)\b\W+(?:\w+\W+){0,2}?"
                        r"(recording|record)\b", re.I)
GO_AHEAD = re.compile(r"\b(go ahead|what is it|what's that|you had a question|your question|raised your hand|"
                      r"(do )?you have a (question|doubt)|hand (is )?(up|raised)|bolo|boliye|puchho|poochho|"
                      r"speak up|you wanted to say)\b"
                      r"|बोलो|बोलिए|पूछो|पूछिए", re.I)  # outside \b: Python's \b fails after a Hindi vowel sign
SCREEN = re.compile(r"\b(screen|slides?|shared|sharing|showing|shown|chart|graph|diagram|spreadsheet|sheet|"
                    r"table|deck|this (page|document|doc))\b|स्क्रीन|स्लाइड", re.I)
SCREEN_FRESH = 120  # seconds a screen-share frame stays usable
screens: dict[int, tuple[str, float]] = {}  # meeting -> (latest screen-share PNG, base64; monotonic time)
voice_locks: dict[int, asyncio.Lock] = {}  # meeting -> serializes Amber's audio clips
filler_until: dict[int, float] = {}         # meeting -> monotonic time the current filler finishes
speaking_until: dict[int, float] = {}       # meeting -> monotonic time Amber's audio ends
FOLLOWUP = float(os.getenv("AMBER_FOLLOWUP", "10"))  # seconds after a reply the asker can follow up
ANSWER_WINDOW = 30.0  # after asking her record question aloud, a bare spoken reply ("it's 2") counts
OTHERS_WINDOW = 6.0   # after she speaks, someone else's clear question goes to the model ("and the booster pump?")
STALE_TALK = 30.0     # a line "began" longer ago than this is a lost partial, not a long sentence
convs: dict[int, Conversation] = {}  # meeting -> turn-taking state (turns.py)
_tasks: set[asyncio.Task] = set()


def conv(mid: int) -> Conversation:
    return convs.setdefault(mid, Conversation())


def _spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tasks.add(t)  # keep a reference so the task isn't garbage-collected mid-flight
    t.add_done_callback(_tasks.discard)
    return t


def on_speech(mid: int, speaker: str, text: str, addressed: bool, why: str = "", at: float | None = None,
              judged: bool = False):
    """`at`: when they began saying it; open windows are judged at that moment (finals arrive late)."""
    c = conv(mid)
    r = route(c, speaker, text, addressed, names_someone_else(mid, speaker, text), at or time.monotonic(), judged)
    decided(mid, speaker, text, r.action, why or r.why)
    old = c.pending.get(speaker)
    if r.cancel and old:
        old["task"].cancel()
        c.pending.pop(speaker)
        publish("amber.cancelled", mid, {"speaker": speaker})
    if r.action == "ignore":
        return
    if r.action == "classify":
        _spawn(classify(mid, speaker, r.text))
        return
    c.followups.pop(speaker, None)  # the follow-up (or "yes?") has been used
    if r.action in ("append", "merge"):
        q = c.pending[speaker]
        q["task"].cancel()  # asker is still talking / corrected themselves -> restart with the fuller question
    else:  # start, queue: a new question (a queued one waits for the answer being spoken: voice lock)
        q = {"parts": []}
    q["parts"].append(r.text)
    delay = BARE_WAIT if question_pending(" ".join(q["parts"])) else DEBOUNCE
    q["task"] = _spawn(_reply(mid, speaker, q, delay=delay, key=speaker))
    c.pending[speaker] = q


QUIET = {"no name, nothing open"}  # not worth a line in the dashboard's "why" log


def decided(mid: int, speaker: str, text: str, action: str, why: str):
    """The "why" log: what Amber did with each line and the reason, for the dashboard and the server log."""
    if why in QUIET:
        return
    print(f"[turn] {speaker}: {text!r} -> {action} ({why})")
    publish("amber.decision", mid, {"speaker": speaker, "text": text, "action": action, "why": why})


async def classify(mid: int, speaker: str, text: str):
    """Unclear line while Amber is in a conversation with this speaker: let the model judge from context."""
    try:
        to_amber = await brain.is_for_amber(mid, speaker, text)
    except Exception as e:  # model down: silence is the safe default for an unclear line
        print(f"[turn] classify failed: {e!r}")
        to_amber = False
    if to_amber:
        on_speech(mid, speaker, text, addressed=True, why="the model judged it was said to Amber", judged=True)
    else:
        decided(mid, speaker, text, "ignore", "the model judged it wasn't for Amber")


def names_someone_else(mid: int, speaker: str, text: str) -> bool:
    """ "Priya, please close the PPE order" is for Priya, even right after the speaker asked Amber something."""
    people = db.rows("SELECT name FROM participants WHERE meeting_id=? UNION SELECT name FROM attendees WHERE meeting_id=?",
                     mid, mid)
    me = speaker.split(" ")[0].lower()
    firsts = {p["name"].split(" ")[0].lower() for p in people if p["name"]} - {me, "amber", "unknown", ""}
    return bool(firsts & set(re.findall(r"[a-z]+", text.lower())))


def still_talking(mid: int, speaker: str):
    """A partial transcript from someone with a pending question: restart the wait, so Amber answers
    DEBOUNCE after their last word even when the ASR splits "Amber," and the question into separate finals."""
    q = conv(mid).pending.get(speaker)
    if q and not q.get("generating"):
        q["task"].cancel()
        delay = BARE_WAIT if question_pending(" ".join(q["parts"])) else DEBOUNCE
        q["task"] = _spawn(_reply(mid, speaker, q, delay=delay, key=speaker))


def filler_kind(question: str, mid: int | None = None) -> str | None:
    """Which filler pool fits a slow answer, or None when a filler would sound wrong: Hindi (English-only pool),
    greetings / questions about Amber, a bare "Amber", a two-word follow-up ("that right?", "really?"), a recording
    command, or a short reply while her own record question is open ("the second one")."""
    words = re.sub(r"[^a-z' ]", " ", WAKE.sub(" ", question.lower())).split()
    if not has_content(question) or NO_FILLER.search(question) or HINDI.search(question) or RECORD_CMD.search(question):
        return None
    if len(words) <= 3 and not LOOKUP.search(question):
        return None
    if mid is not None and len(words) <= 8 and open_confirmation(mid):
        return None
    return "lookup" if LOOKUP.search(question) else "think"


def filler_ok(mid: int) -> bool:
    """Right now, may she say "one moment"? Not if someone has started talking (never talk over people), and not
    if she said one in the last FILLER_GAP seconds."""
    return not conv(mid).talking_since and time.monotonic() - last_filler.get(mid, -1e9) >= FILLER_GAP


def screen_for(mid: int, question: str) -> bytes | None:
    """The current screen share, only when the question is about it (images make the answer slower)."""
    frame = screens.get(mid)
    if frame and SCREEN.search(question) and time.monotonic() - frame[1] < SCREEN_FRESH:
        return base64.b64decode(frame[0])
    return None


def command(mid: int, who: str, text: str, via_chat: bool = False) -> bool:
    """Things Amber does rather than answers. True if `text` was one."""
    if m := RECORD_CMD.search(text):
        _spawn(record_command(mid, m.group(1).lower() in ("stop", "pause", "halt"), via_chat))
        return True
    if GO_AHEAD.search(text) and (pc := open_confirmation(mid)):
        # Permission given: ask out loud (short spoken form), so the hand's chat fallback is no longer needed.
        asked_aloud.add(pc["id"])
        _spawn(say(mid, pc["question"].removeprefix("✋ ") if via_chat else spoken_question(pc), via_chat))
        if not via_chat:
            conv(mid).record_answer_until = time.monotonic() + ANSWER_WINDOW  # replies are "it's 2", not "Amber, two"
        return True
    return False


def spoken_question(pc: dict) -> str:
    cands = json.loads(pc["candidates_json"])["candidates"]
    names = {r["id"]: r["name"] for r in db.rows("SELECT id, name FROM records")}
    if len(cands) == 1:
        return f"Quick check: should I note that on {cands[0]}, the {names.get(cands[0], '')}? Say Amber, yes or no."
    options = ", or ".join(f"{i + 1}, {c}, the {names.get(c, '')}" for i, c in enumerate(cands))
    return (f"Thanks. Someone mentioned a record update and I'm not sure which record: did you mean {options}? "
            "Say Amber and the number, or type it in the chat.")


async def set_recording(mid: int, pause: bool) -> bool:
    if bot := _real_bot(mid):
        try:
            await (recall.pause_recording if pause else recall.resume_recording)(bot)
        except Exception as e:
            raise HTTPException(502, f"Recall could not {'pause' if pause else 'resume'} the recording: {e}")
    db.execute("UPDATE meetings SET recording_paused=? WHERE id=?", int(pause), mid)
    publish("recording.paused" if pause else "recording.resumed", mid, {})
    return pause


async def record_command(mid: int, pause: bool, via_chat: bool):
    paused = bool((db.row("SELECT recording_paused FROM meetings WHERE id=?", mid) or {}).get("recording_paused"))
    if pause == paused:
        msg = "Recording is already paused." if pause else "I'm already recording."
    else:
        try:
            t = time.perf_counter()
            await set_recording(mid, pause)
            print(f"[amber] recall {'pause' if pause else 'resume'}_recording took {time.perf_counter() - t:.1f}s")
            # Recall may stop the live transcript while paused (chat events keep coming), so the chat is the
            # resume path that always works; a spoken "resume" also works if the transcript keeps flowing.
            msg = ("Okay, recording paused. To resume, type 'Amber, resume recording' in the chat." if pause else
                   "Recording resumed.")
        except HTTPException as e:
            print(f"[amber] {e.detail}")
            msg = "Sorry, I couldn't change the recording just now."
    await say(mid, msg, via_chat)
    if pause and not via_chat and msg.startswith("Okay"):
        await amber_chat(mid, "Recording paused. Type 'Amber, resume recording' here to resume.")


async def say(mid: int, text: str, via_chat: bool = False):
    if via_chat:
        await amber_chat(mid, text)
    else:
        await speak(mid, text)
        publish("amber.reply", mid, {"to": "", "question": "", "text": text, "via": "voice", "latency": {}})


PCM_BPS = voice.PCM_RATE * 2  # bytes per second of streamed speech
media_sockets: dict[int, WebSocket] = {}  # meeting -> its Output Media page (streaming voice)
interrupted: dict[int, int] = {}          # meeting -> times someone talked over Amber (stops a stream mid-way)


async def media_send(mid: int, payload: dict | bytes) -> bool:
    ws = media_sockets.get(mid)
    if not ws:
        return False
    try:
        await (ws.send_bytes(payload) if isinstance(payload, bytes) else ws.send_text(json.dumps(payload)))
        return True
    except Exception as e:  # page went away; it reconnects on its own
        print(f"[media] meeting {mid}: send failed: {e!r}")
        return False


async def stream_speech(mid: int, text: str):
    """Speak through the page: forward PCM as ElevenLabs makes it (first sound ~0.4 s, no clip upload)."""
    turn, start, sent = interrupted.get(mid, 0), time.monotonic(), 0
    speaking_until[mid] = start + 1.0  # until the first chunk arrives; barge-in works from the start
    try:
        async for chunk in voice.tts_stream(text):
            if interrupted.get(mid, 0) != turn or not await media_send(mid, chunk):
                return  # someone talked over her, or the page dropped: stop sending
            sent += len(chunk)
            speaking_until[mid] = max(speaking_until[mid], start + sent / PCM_BPS)
    except Exception as e:
        print(f"[amber] streamed tts failed: {e!r}")
        publish("amber.error", mid, {"question": "", "error": f"tts: {e}"})
    finally:
        if interrupted.get(mid, 0) == turn:
            conv(mid).spoke_until = speaking_until.get(mid, 0) + OTHERS_WINDOW


@app.get("/media/amber")
async def media_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "assets", "amber_media.html"))


@app.websocket("/ws/media")
async def media_ws(ws: WebSocket):
    """Amber's Output Media page connects here; audio and control messages flow down it."""
    if WEBHOOK_TOKEN and ws.query_params.get("token") != WEBHOOK_TOKEN:
        await ws.close(code=1008)
        return
    try:
        mid = int(ws.query_params.get("m", ""))
    except ValueError:
        await ws.close(code=1008)
        return
    await ws.accept()
    media_sockets[mid] = ws
    print(f"[media] meeting {mid}: page connected")
    db_hand = (db.meeting_detail(mid) or {}).get("hand_raised")
    await media_send(mid, {"type": "hand", "on": bool(db_hand)})
    try:
        while (await ws.receive())["type"] != "websocket.disconnect":
            pass
    except WebSocketDisconnect:
        pass
    finally:
        if media_sockets.get(mid) is ws:
            media_sockets.pop(mid)
        print(f"[media] meeting {mid}: page disconnected")


async def speak(mid: int, text: str, mp3: bytes | None = None, wait: bool = True):
    """Say `text` in the call and log it as Amber's line. Never raises: a voice failure must not kill the reply.
    wait=False: the caller already timed this (an answer starts slightly before its own filler ends)."""
    db.execute("INSERT INTO utterances (meeting_id,speaker,text,ts,addressed) VALUES (?,?,?,?,0)",
               mid, "Amber", text, None)
    if mid in media_sockets and os.getenv("ELEVENLABS_API_KEY"):  # streaming page: no clip to prepare
        async with voice_locks.setdefault(mid, asyncio.Lock()):
            if wait and (left := speaking_until.get(mid, 0) - time.monotonic()) > 0:
                await asyncio.sleep(min(left, 20))
            await stream_speech(mid, text)
        return
    if mp3 is None and os.getenv("ELEVENLABS_API_KEY"):
        try:
            mp3 = await voice.tts(text)
        except Exception as e:
            print(f"[amber] tts failed: {e!r}")
            publish("amber.error", mid, {"question": "", "error": f"tts: {e}"})
    if not mp3:
        return
    # One clip at a time per meeting: two answers ready together would otherwise both check, then both play.
    async with voice_locks.setdefault(mid, asyncio.Lock()):
        if wait and (left := speaking_until.get(mid, 0) - time.monotonic()) > 0:
            await asyncio.sleep(min(left, 20))  # another answer is still playing: don't talk over ourselves
        if bot := _real_bot(mid):
            try:
                await recall.output_audio(bot, mp3)
            except Exception as e:
                print(f"[amber] output_audio failed: {e!r}")
                publish("amber.error", mid, {"question": "", "error": f"audio: {e}"})
                return
        # max(): a filler-overlapped answer must not shorten the window of audio still playing (barge-in check)
        speaking_until[mid] = max(speaking_until.get(mid, 0), time.monotonic()) + len(mp3) / 16000  # 16 KB/s
        conv(mid).spoke_until = speaking_until[mid] + OTHERS_WINDOW


async def _play_filler(mid: int, kind: str):
    text = voice.pick_filler(kind)
    publish("amber.filler", mid, {"text": text})
    if not os.getenv("ELEVENLABS_API_KEY"):
        return
    try:
        if mid in media_sockets:  # streaming page
            pcm = await voice.filler_pcm(text)
            await media_sockets[mid].send_bytes(pcm)
            filler_until[mid] = speaking_until[mid] = time.monotonic() + len(pcm) / PCM_BPS
        elif bot := _real_bot(mid):
            mp3 = await voice.filler_mp3(text)
            await recall.output_audio(bot, mp3)
            filler_until[mid] = speaking_until[mid] = time.monotonic() + len(mp3) / 16000
    except Exception as e:
        print(f"[amber] filler failed: {e!r}")


def _real_bot(mid: int) -> str | None:
    bot = (db.row("SELECT bot_id FROM meetings WHERE id=?", mid) or {}).get("bot_id")
    return bot if recall.enabled() and bot and not bot.startswith("replay-") else None


def yield_floor(mid: int):
    """A human started talking while Amber's audio is playing -> stop it."""
    if time.monotonic() < speaking_until.get(mid, 0):
        speaking_until[mid] = 0
        interrupted[mid] = interrupted.get(mid, 0) + 1  # a stream still sending stops sending
        if mid in media_sockets:
            _spawn(media_send(mid, {"type": "stop"}))  # the page cuts its audio at once
        elif bot := _real_bot(mid):
            _spawn(recall.stop_audio(bot))
        publish("amber.yielded", mid, {})


async def _reply(mid: int, speaker: str, q: dict, delay: float, via_chat=False, key=None):
    try:
        await _answer(mid, speaker, q, delay, via_chat)
    finally:
        # Done or crashed: drop the pending question so its words don't leak into this speaker's next one.
        # (A restart replaced q["task"] with a newer task, which then owns the entry.)
        c = conv(mid)
        if key and c.pending.get(key) is q and q.get("task") is asyncio.current_task():
            c.pending.pop(key)


async def _answer(mid: int, speaker: str, q: dict, delay: float, via_chat: bool):
    await asyncio.sleep(delay)
    q["generating"] = True
    question = " ".join(q["parts"])
    t0 = time.perf_counter()
    answer = asyncio.ensure_future(brain.answer(mid, speaker, question, screen_for(mid, question)))
    try:
        if not via_chat and not q.get("filler") and (kind := filler_kind(question, mid)):
            done, _ = await asyncio.wait({answer}, timeout=FILLER_AFTER)
            if not done and filler_ok(mid):  # slow answer: cover the wait
                last_filler[mid] = time.monotonic()
                q["filler"] = _spawn(_play_filler(mid, kind))
        text = await answer
    except asyncio.CancelledError:  # they kept talking / withdrew it: drop the half-made answer too
        answer.cancel()
        raise
    except Exception as e:  # every model failed: say so instead of going silent
        print(f"[amber] reply failed: {e!r}")
        publish("amber.error", mid, {"question": question, "error": str(e)})
        text = brain.SORRY
    if HINDI.search(question) and text in (brain.FALLBACK, brain.SORRY):  # models keep the fixed lines in English
        text = brain.FALLBACK_HI if text == brain.FALLBACK else brain.SORRY_HI
    if m := brain.RECORD_TAG.match(text):
        # They answered her open record question in their own words ("not that one, the other"): settle it the
        # same way as a typed "2". A record outside the question's options is ignored, never written.
        text, pick = text[m.end():].strip() or "Got it.", m.group(1).upper()
        if (pc := open_confirmation(mid)) and (pick == "NONE" or pick in json.loads(pc["candidates_json"])["candidates"]):
            settle_confirmation(mid, speaker, pc, None if pick == "NONE" else pick)
    if (action := text.strip().strip(".")) in (brain.PAUSE_TOKEN, brain.RESUME_TOKEN):
        # A recording request the phrase list missed ("hold off recording for a bit"): the model spotted it.
        q["committed"] = True
        await record_command(mid, action == brain.PAUSE_TOKEN, via_chat)
        if not via_chat:  # "I'm already recording." -> "oh, then stop it" needs no name either
            conv(mid).followups[speaker] = (max(speaking_until.get(mid, 0), time.monotonic()) + FOLLOWUP, False)
        return
    t_llm = time.perf_counter()
    try:
        mp3 = None if via_chat or mid in media_sockets or not os.getenv("ELEVENLABS_API_KEY") else await voice.tts(text)
    except Exception as e:
        print(f"[amber] tts failed: {e!r}")
        publish("amber.error", mid, {"question": question, "error": f"tts: {e}"})
        mp3 = None
    t_tts = time.perf_counter()
    q["committed"] = True  # later speech no longer rewrites this answer
    if via_chat:
        await amber_chat(mid, text)
    else:
        if q.get("filler"):
            await q["filler"]  # never talk over our own "let me check"
            await asyncio.sleep(max(0, filler_until.get(mid, 0) - FILLER_OVERLAP - time.monotonic()))
        await speak(mid, text, mp3 or b"", wait=not q.get("filler"))
        # They may follow up without her name until FOLLOWUP s after she stops talking. After just her name
        # ("Amber?" -> "Yes?") their next line is the question, even without a question word.
        conv(mid).followups[speaker] = (max(speaking_until.get(mid, 0), time.monotonic()) + FOLLOWUP,
                                        question_pending(question))
    latency = {"llm": round(t_llm - t0, 2), "tts": round(t_tts - t_llm, 2), "total": round(time.perf_counter() - t0, 2)}
    print(f"[amber] {speaker}: {question!r} -> {text!r} {latency}")
    publish("amber.reply", mid, {"to": speaker, "question": question, "text": text,
                                 "via": "chat" if via_chat else "voice", "latency": latency})


# --- task extraction + record tagging ------------------------------------------
# Every few human lines (and once at the end) the new transcript goes through brain.extract().
# Record notes are written only when the model is sure which record was meant; otherwise Amber asks in chat.
AUTO_WRITE = float(os.getenv("AMBER_AUTO_WRITE", "0.8"))   # >= this: write the note straight away
CONFIRM_MIN = float(os.getenv("AMBER_CONFIRM_MIN", "0.5"))  # >= this (and < AUTO_WRITE): ask first; below: ignore
EXTRACT_EVERY = int(os.getenv("AMBER_EXTRACT_EVERY", "4"))  # new human lines between extraction passes
RECORD_ID = re.compile(r"\b(PO|EQ)-?\s?(\d{3,4})\b", re.I)
# "one" is a pronoun more often than a number ("that one", "the other one"): only a bare "one" picks option 1.
CHOICE_WORDS = {"1": 0, "first": 0, "2": 1, "two": 1, "second": 1, "3": 2, "three": 2, "third": 2,
                # Hindi ("दूसरा वाला", "pehla"); roman "do" (two) is left out: it's an English word too
                "pehla": 0, "pehli": 0, "पहला": 0, "पहली": 0, "एक": 0, "dusra": 1, "doosra": 1, "dusri": 1, "दूसरा": 1,
                "दूसरी": 1, "दो": 1, "teesra": 2, "tisra": 2, "तीसरा": 2, "तीसरी": 2, "तीन": 2}
# "not that one, the other" / "नहीं, वो नहीं": the answer model reads these against her open question
RELATIVE = re.compile(r"\b(other|not|else|instead|another|different|nahi)\b|नहीं", re.I)
YES = re.compile(r"^\W*(amber\W+)?(yes|yeah|yep|correct|right|that one|exactly|haan|han|ji|sahi)\b|^\W*(हाँ|हां|जी|सही)",
                 re.I)
NO = re.compile(r"\b(neither|none of (them|those)|no,? (it'?s )?not|ignore (it|that)|skip (it|that)|dono nahi|koi nahi)\b"
                r"|दोनों नहीं|कोई नहीं|कोई भी नहीं", re.I)
since_extract: dict[int, int] = {}
extracting: set[int] = set()


def maybe_extract(mid: int):
    since_extract[mid] = since_extract.get(mid, 0) + 1
    if mid not in extracting and since_extract[mid] >= EXTRACT_EVERY:
        extracting.add(mid)  # claim it now: a second webhook can arrive before the spawned task starts
        since_extract[mid] = 0
        _spawn(run_extract(mid))


async def run_extract(mid: int):
    extracting.add(mid)
    since_extract[mid] = 0
    try:
        # Progress lives with the meeting, so a backend restart mid-call doesn't re-read (and re-ask) everything.
        after = (db.row("SELECT extracted_upto FROM meetings WHERE id=?", mid) or {}).get("extracted_upto") or 0
        result, upto = await brain.extract(mid, after)
        await apply_extraction(mid, result)
        db.execute("UPDATE meetings SET extracted_upto=? WHERE id=?", upto, mid)
    except Exception as e:
        print(f"[extract] meeting {mid} failed: {e!r}")
        publish("extract.error", mid, {"error": str(e)})
    finally:
        extracting.discard(mid)


async def final_extract(mid: int):
    for _ in range(150):  # let an in-flight pass finish (max ~30s), then sweep what's left
        if mid not in extracting:
            break
        await asyncio.sleep(0.2)
    await run_extract(mid)
    await post_meeting(mid)  # MOM + recap email once the last tasks and notes are in


def _attendee_email(mid: int, name: str | None) -> str:
    """Full-name match first, then a unique first-name match ("Rahul" -> Rahul Mehta); ambiguous -> no email."""
    name = (name or "").strip().lower()
    people = db.rows("SELECT name, email FROM attendees WHERE meeting_id=? AND COALESCE(email,'')!=''", mid)
    exact = [a["email"] for a in people if a["name"].strip().lower() == name]
    first = [a["email"] for a in people if name and a["name"].split(" ")[0].lower() == name.split(" ")[0]]
    return (exact or (first if len(set(first)) == 1 else [""]))[0]


TASK_STATES = {"open", "in_progress", "done", "blocked"}
_GENERIC = {"the", "and", "for", "two", "with", "from", "this", "that"}


def _terms(text: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w  # "pumps" ~ "pump"
            for w in re.findall(r"[a-z0-9#-]+", (text or "").lower()) if len(w) >= 3 and w not in _GENERIC}


def _first(name: str | None) -> str:
    return (name or "").strip().split(" ")[0].lower()


def same_task(a: set[str], b: set[str]) -> bool:
    """Same commitment, reworded: one title's meaningful words contain the other's ("send vendor quote" vs
    "send the vendor quote by friday"). "...for the pump" vs "...for the chiller" differ, so both are kept."""
    small, big = sorted((a, b), key=len)
    return bool(small) and (small <= big if len(small) >= 2 else small == big)


def _phrase(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9#-]+", (text or "").lower())) + " "  # padded: whole-word matches


def which_records(quote: str, records: dict) -> list[str]:
    """Records the speaker's own words point to (best name/alias overlap). More than one = the words alone are
    ambiguous, whatever confidence the model claims: "the Grundfos pump" fits both Grundfos pump orders."""
    if ids := {f"{a.upper()}-{b}" for a, b in RECORD_ID.findall(quote or "")} & records.keys():
        return sorted(ids)
    words, said = _terms(quote), _phrase(quote)
    # A whole name/alias ("chiller two", "pump seals") outweighs single shared words ("chiller", "pump").
    scores = {rid: len(words & _terms(f"{r['name']} {r['aliases']}"))
              + 2 * sum(_phrase(p) in said for p in [r["name"], *(r["aliases"] or "").split(",")] if p.strip())
              for rid, r in records.items()}
    best = max(scores.values(), default=0)
    return [rid for rid, s in scores.items() if s == best] if best else []


def _clean(v):
    """Models write "null" / "none" / "" for missing values."""
    return None if v is None or str(v).strip().lower() in ("", "null", "none", "n/a", "unknown") else str(v).strip()


def _date(v) -> str | None:
    v = _clean(v)
    return v[:10] if v and re.match(r"^\d{4}-\d{2}-\d{2}", v) else None


async def apply_extraction(mid: int, r: dict):
    if not isinstance(r, dict):
        return
    series = (db.row("SELECT series_id FROM meetings WHERE id=?", mid) or {}).get("series_id")
    known = [(_first(t["owner"]), _terms(t["title"])) for t in db.rows(
        "SELECT owner, title FROM tasks WHERE status!='done' AND (series_id=? OR meeting_id=?)", series, mid)]
    for t in r.get("tasks") or []:
        if not isinstance(t, dict) or not _clean(t.get("title")):
            continue
        title, owner = _clean(t["title"]), _clean(t.get("owner"))
        if any(o == _first(owner) and same_task(words, _terms(title)) for o, words in known):
            continue  # the model rephrased a task it already logged ("Send the vendor quote" again)
        known.append((_first(owner), _terms(title)))  # also dedupes repeats within this same pass
        tid = db.execute("INSERT INTO tasks (meeting_id,series_id,title,owner,owner_email,due_at,status,quote) "
                         "VALUES (?,?,?,?,?,?,'open',?)", mid, series, title, owner,
                         _attendee_email(mid, owner), _date(t.get("due")), _clean(t.get("quote")))
        publish("task.created", mid, {"id": tid, "title": title, "owner": owner, "due": _date(t.get("due"))})
    for u in r.get("task_updates") or []:
        if not isinstance(u, dict):
            continue
        status = _clean(u.get("status"))
        status = status.lower() if status and status.lower() in TASK_STATES else None
        if task := db.row("SELECT id FROM tasks WHERE id=?", u.get("task_id")):
            db.execute("UPDATE tasks SET status=COALESCE(?, status), last_update=COALESCE(?, last_update) WHERE id=?",
                       status, _clean(u.get("note")) or _clean(u.get("quote")), task["id"])
            publish("task.updated", mid, {**u, "status": status})
    records = {x["id"]: x for x in db.rows("SELECT id, name, aliases FROM records")}
    for n in r.get("record_notes") or []:
        if not isinstance(n, dict) or not _clean(n.get("note")):
            continue
        try:
            conf = float(n.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        n["new_status"] = _clean(n.get("new_status"))
        rid = str(n.get("record_id") or "").strip().upper()
        alts = n.get("candidates") if isinstance(n.get("candidates"), list) else []
        cands = [c for c in dict.fromkeys([rid, *(str(a).strip().upper() for a in alts)]) if c in records]
        spoken = which_records(n.get("quote") or n.get("note") or "", records)  # no quote: judge the note
        if len(spoken) > 1 and (set(spoken) & set(cands) or not cands):
            cands = ([c for c in cands if c in spoken] + [s for s in spoken if s not in cands])[:3]
            conf = min(max(conf, CONFIRM_MIN), AUTO_WRITE - 0.01)  # the words are ambiguous: ask, don't write
        if conf >= AUTO_WRITE and rid in records and len(cands) == 1:
            write_note(mid, rid, n, conf)
        elif conf >= CONFIRM_MIN and cands:
            await ask_which_record(mid, n, cands, records)


def write_note(mid: int, rid: str, n: dict, conf: float):
    db.execute("INSERT INTO record_notes (record_id,meeting_id,note,confidence,ts) VALUES (?,?,?,?,?)",
               rid, mid, n.get("note"), conf, db.now())
    if n.get("new_status"):
        db.execute("UPDATE records SET status=? WHERE id=?", n["new_status"], rid)
    publish("record.noted", mid, {"record_id": rid, "note": n.get("note"), "new_status": n.get("new_status"),
                                  "confidence": conf})


async def amber_chat(mid: int, text: str):
    db.execute("INSERT INTO chat (meeting_id,sender,text,ts,is_amber) VALUES (?,?,?,?,1)", mid, "Amber", text, db.now())
    publish("chat", mid, {"sender": "Amber", "text": text, "at": db.now(), "addressed": False})
    if bot := _real_bot(mid):
        try:
            await recall.send_chat(bot, text)
        except Exception as e:
            print(f"[amber] chat send failed: {e!r}")


async def ask_which_record(mid: int, n: dict, cands: list[str], records: dict):
    """Confidence check: never guess which record to write to. Ask in chat (polite, doesn't interrupt)."""
    quote = (n.get("quote") or n.get("note") or "").strip().rstrip(".")
    if len(cands) > 1:
        options = " or ".join(f"{i + 1}) {c} {records[c]['name']}" for i, c in enumerate(cands))
        question = (f'Quick check before I update the records: "{quote}". Did you mean {options}? '
                    "Reply with the number, or 'neither'.")
    else:
        question = (f'Quick check: should I note "{n.get("note")}" on {cands[0]} {records[cands[0]]["name"]}? '
                    "Reply yes or no.")
    question = "✋ " + question
    if db.row("SELECT id FROM pending_confirmations WHERE meeting_id=? AND resolved=0 AND question=?", mid, question):
        return  # same line seen by two extraction passes: ask once
    pid = db.execute("INSERT INTO pending_confirmations (meeting_id,question,candidates_json,created_at) VALUES (?,?,?,?)",
                     mid, question, json.dumps({"candidates": cands, "note": n}), db.now())
    publish("confirmation.asked", mid, {"question": question, "candidates": cands})
    _spawn(raise_hand(mid, {"id": pid, "question": question}))  # waits out the hand; extraction carries on


HAND_WAIT = float(os.getenv("AMBER_HAND_WAIT", "20"))  # seconds her raised hand waits before she writes in chat
asked_aloud: set[int] = set()  # confirmations someone invited her to ask ("Amber, go ahead")


async def raise_hand(mid: int, pc: dict):
    """Raise-hand protocol: never interrupt people talking. Her tile shows a raised hand first; she asks out loud
    only if invited ("Amber, go ahead"), and writes the question in chat only if the hand is ignored for HAND_WAIT
    seconds. With no tile to show a hand on (mp3 voice), the chat is the hand."""
    publish("amber.hand_raised", mid, {"question": pc["question"]})
    if await media_send(mid, {"type": "hand", "on": True}):
        await asyncio.sleep(HAND_WAIT)
    row = db.row("SELECT resolved FROM pending_confirmations WHERE id=?", pc["id"])
    if row and not row["resolved"] and pc["id"] not in asked_aloud:
        await amber_chat(mid, pc["question"])


CONFIRM_TTL_MIN = 15  # an old unanswered question shouldn't capture "the second one" said much later


def open_confirmation(mid: int) -> dict | None:
    since = (datetime.now(timezone.utc) - timedelta(minutes=CONFIRM_TTL_MIN)).isoformat(timespec="seconds")
    return db.row("SELECT * FROM pending_confirmations WHERE meeting_id=? AND resolved=0 AND created_at>=? "
                  "ORDER BY id DESC LIMIT 1", mid, since)


def resolve_confirmation(mid: int, who: str, text: str) -> bool:
    """Handle a reply to Amber's latest open question. True if `text` was that reply."""
    pc = open_confirmation(mid)
    if not pc:
        return False
    cands = json.loads(pc["candidates_json"])["candidates"]
    words = re.sub(r"[^a-z0-9ऀ-ॿ ]", " ", WAKE.sub(" ", text.lower())).split()  # keep Devanagari
    chosen = None
    if m := RECORD_ID.search(text):
        rid = f"{m.group(1).upper()}-{m.group(2)}"
        chosen = rid if rid in cands else None
    if chosen is None and len(words) <= 6 and not RELATIVE.search(text):  # "1", "the first one", "second"
        idx = 0 if words[-2:] in (["one"], ["number", "one"], ["option", "one"]) and len(words) <= 2 else None
        idx = idx if idx is not None else next((CHOICE_WORDS[w] for w in words if w in CHOICE_WORDS), None)
        chosen = cands[idx] if idx is not None and idx < len(cands) else None
    if chosen is None and len(cands) == 1 and YES.search(text):
        chosen = cands[0]
    declined = NO.search(text) or (len(cands) == 1 and re.match(r"^\W*no\b", text, re.I))
    if chosen is None and not declined:
        return False  # not an answer to the question
    settle_confirmation(mid, who, pc, chosen)
    return True


def settle_confirmation(mid: int, who: str, pc: dict, chosen: str | None):
    """Write the confirmed note (chosen=None: neither) and lower the hand, or raise it for the next question."""
    n = json.loads(pc["candidates_json"])["note"]
    db.execute("UPDATE pending_confirmations SET resolved=1 WHERE id=?", pc["id"])
    if chosen:
        write_note(mid, chosen, n, 1.0)  # confirmed by a person
        _spawn(amber_chat(mid, f"Got it, noted on {chosen}. Thanks, {who.split(' ')[0]}."))
    else:
        _spawn(amber_chat(mid, "Okay, I won't update any record for that."))
    publish("confirmation.resolved", mid, {"chosen": chosen, "by": who})
    if nxt := open_confirmation(mid):  # an earlier question is still waiting: raise the hand for it again
        _spawn(raise_hand(mid, nxt))
    else:
        publish("amber.hand_lowered", mid, {})
        _spawn(media_send(mid, {"type": "hand", "on": False}))


# --- after the meeting: MOM, recap email, follow-up reminders -------------------
REMINDER_LEAD_H = float(os.getenv("AMBER_REMINDER_LEAD_HOURS", "24"))  # remind this long before the due date
# Demo knob: remind N minutes after the meeting ends instead of waiting for the due date (empty = off).
DEMO_REMINDER_MIN = os.getenv("AMBER_DEMO_REMINDER_MINUTES", "")
LIVE_STATES = {"scheduled", "joining", "joining_call", "in_waiting_room", "in_call_not_recording", "in_call_recording",
               "recording"}
recapping: set[int] = set()


def _set_plain_status(mid: int, status: str):
    db.execute("UPDATE meetings SET status=? WHERE id=?", status, mid)
    publish("meeting.status", mid, {"status": status})


async def post_meeting(mid: int, force: bool = False):
    """MOM + recap email, once per meeting (force=True regenerates and resends)."""
    m = db.row("SELECT * FROM meetings WHERE id=?", mid)
    if not m or mid in recapping or (m["mom_json"] and not force):
        return
    recapping.add(mid)
    try:
        db.execute("UPDATE pending_confirmations SET resolved=3 WHERE meeting_id=? AND resolved=0", mid)  # expired
        if not db.row("SELECT id FROM utterances WHERE meeting_id=? AND speaker!='Amber' LIMIT 1", mid):
            # Never admitted / nobody spoke: an empty recap email would only confuse attendees.
            mom = {"executive_summary": "No conversation was captured (Amber may not have been admitted to the call).",
                   "agenda_alignment": [], "decisions": [], "open_questions": []}
            db.execute("UPDATE meetings SET mom_json=? WHERE id=?", json.dumps(mom), mid)
            _set_plain_status(mid, "completed")
            publish("meeting.recap", mid, {"mom": mom})
            return
        _set_plain_status(mid, "processing")
        try:
            mom = await brain.make_mom(mid)
        except Exception as e:  # still send the facts (tasks, record updates, attendance) without the narrative
            print(f"[mom] meeting {mid}: LLM failed: {e!r}")
            mom = {"executive_summary": "Summary unavailable (the language model could not be reached).",
                   "agenda_alignment": [], "decisions": [], "open_questions": []}
        db.execute("UPDATE meetings SET mom_json=? WHERE id=?", json.dumps(mom), mid)
        tasks = db.rows("SELECT * FROM tasks WHERE meeting_id=? ORDER BY id", mid)
        notes = db.rows("SELECT * FROM record_notes WHERE meeting_id=? ORDER BY id", mid)
        people = db.rows("SELECT name, joined_at, left_at FROM participants WHERE meeting_id=? ORDER BY id", mid)
        subject, html, text = mailer.recap(m, mom, tasks, notes, people)
        to = [a["email"] for a in db.rows("SELECT email FROM attendees WHERE meeting_id=?", mid)]
        await mailer.send(mid, "recap", to, subject, html, text)
        _set_plain_status(mid, "completed")
        publish("meeting.recap", mid, {"mom": mom})
    finally:
        recapping.discard(mid)


def _remind_at(t: dict) -> datetime | None:
    if DEMO_REMINDER_MIN and t["ended_at"]:
        return datetime.fromisoformat(t["ended_at"]) + timedelta(minutes=float(DEMO_REMINDER_MIN))
    if t["due_at"]:
        try:  # due dates are local calendar days: remind REMINDER_LEAD_H before 09:00 that day
            day = datetime.fromisoformat(t["due_at"][:10]).replace(hour=9).astimezone()
            return day - timedelta(hours=REMINDER_LEAD_H)
        except ValueError:
            pass
    return datetime.fromisoformat(t["ended_at"]) + timedelta(hours=REMINDER_LEAD_H) if t["ended_at"] else None


async def send_due_reminders():
    """Follow up on commitments without anyone asking: one check-in email per open task, to its owner."""
    due = db.rows("SELECT t.*, m.title AS meeting_title, m.ended_at FROM tasks t JOIN meetings m ON m.id=t.meeting_id "
                  "WHERE t.status!='done' AND t.reminded_at IS NULL AND COALESCE(t.owner_email,'')!='' "
                  "AND m.ended_at IS NOT NULL")
    now = datetime.now(timezone.utc)
    for t in due:
        when = _remind_at(t)
        if when and now >= when:
            subject, html, text = mailer.reminder(t, t["meeting_title"])
            if await mailer.send(t["meeting_id"], "reminder", [t["owner_email"]], subject, html, text):
                db.execute("UPDATE tasks SET reminded_at=? WHERE id=?", db.now(), t["id"])
                publish("task.reminded", t["meeting_id"], {"id": t["id"], "to": t["owner_email"]})
            else:  # don't retry every 30s on a broken SMTP setup; the outbox has the error
                db.execute("UPDATE tasks SET reminded_at=? WHERE id=?", "failed:" + db.now(), t["id"])


async def watch_bots():
    """Recall's status webhooks need dashboard setup; polling the live bots catches the end of the call anyway."""
    if not recall.enabled():
        return
    for m in db.rows("SELECT id, bot_id, status FROM meetings WHERE bot_id NOT LIKE 'replay-%'"):
        if m["status"] not in LIVE_STATES:
            continue
        try:
            code = await recall.bot_status(m["bot_id"])
        except Exception as e:
            print(f"[watch] bot {m['bot_id']}: {e!r}")
            continue
        if code and code != m["status"] and code != "ready":  # "ready" = scheduled bot not dispatched yet
            _set_status(m["id"], code)  # done / call_ended / fatal also start the post-meeting pipeline


async def background_loop():
    while True:
        for job in (watch_bots, send_due_reminders):
            try:
                await job()
            except Exception as e:
                print(f"[background] {job.__name__}: {e!r}")
        await asyncio.sleep(30)


@app.post("/api/meetings/{mid}/recap")
async def resend_recap(mid: int):
    db.row("SELECT id FROM meetings WHERE id=?", mid) or _404()
    if mid in recapping:
        raise HTTPException(409, "The recap is still being written; try again in a moment.")
    await post_meeting(mid, force=True)
    return db.meeting_detail(mid)


@app.get("/api/outbox/{oid}")
async def outbox_item(oid: int):
    return db.row("SELECT * FROM outbox WHERE id=?", oid) or _404()


@app.get("/api/outbox")
async def outbox(meeting_id: int | None = None):
    sql = "SELECT id, meeting_id, kind, to_addr, subject, status, error, ts FROM outbox"
    return db.rows(sql + (" WHERE meeting_id=? ORDER BY id DESC" if meeting_id else " ORDER BY id DESC LIMIT 50"),
                   *([meeting_id] if meeting_id else []))
