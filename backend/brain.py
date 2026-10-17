"""LLM reasoning. Any OpenAI-compatible server (LLM_BASE_URL, e.g. a local proxy) and/or Gemini.
Grounded answers, task extraction, record tagging and the post-meeting MOM."""
import asyncio
import base64
import json
import os
import re
from datetime import datetime

import httpx
from google import genai
from google.genai import types

import db

FALLBACK = "I don't have that information in my current records."
SORRY = "Sorry, I couldn't get that. Could you ask again?"
FALLBACK_HI = "मेरे पास अभी के रिकॉर्ड में यह जानकारी नहीं है।"
SORRY_HI = "माफ़ कीजिए, मैं समझ नहीं पाई। क्या आप फिर से पूछ सकते हैं?"
# 2.5 models 404 for new keys. On 503 (overloaded), 429 or a timeout, fall through to the next model.
MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash"), "gemini-3.8-flash", "gemini-flash-latest"]
CALL_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "5"))  # an overloaded call otherwise hangs for minutes

# OpenAI-compatible endpoint (local proxy, OpenAI, Groq, LM Studio...). Used first when LLM_BASE_URL is set.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")  # include the /v1, e.g. http://localhost:8317/v1
# Comma-separated, tried in order. "model@low" sets that model's reasoning_effort (overrides LLM_REASONING_EFFORT).
# e.g. "gemma4:31b,gpt-6-luna@low,gemini-3.5-flash-lite"
LLM_MODELS = [m.strip() for m in os.getenv("LLM_MODEL", "").split(",") if m.strip()]
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "10"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "300"))  # headroom for models that reason before answering
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")  # none / low / medium / high; empty = model default

ANSWER_RULES = f"""You are Amber, an AI meeting assistant built by this team for this meeting (not made by Google or any
AI company). You take part in the live call, answer questions from the meeting context and records, and keep notes.
You were just addressed by name.
Reply in 1-2 short spoken sentences, under 35 words. No markdown, no lists, no preamble.
For facts about this company, its records, orders, equipment, people, tasks, numbers or decisions,
use ONLY the CONTEXT, RECORDS, OPEN TASKS and TRANSCRIPT below. If that information is not there,
reply exactly: "{FALLBACK}"
What people said in this meeting (TRANSCRIPT) is information you have: use it for questions like
"what did I just say" or "what have we discussed".
PREVIOUS MEETINGS are earlier meetings of this same series: use them for "what did we decide last time" questions.
If a SCREEN image is attached, it is what is being screen-shared right now: use it for questions about the
screen, slide, chart or document being shown.
General knowledge or concept questions may be answered from your own knowledge.
Never invent record IDs, dates, amounts or owners.
Reply in the language of the question: a Hindi or Hinglish question gets a natural spoken Hindi reply in
Devanagari script (keep record IDs like PO-1041 as they are); an English question gets English. The fallback
line in Hindi is: "{FALLBACK_HI}\""""

_client: genai.Client | None = None
_http: httpx.AsyncClient | None = None


def client() -> genai.Client:
    global _client
    _client = _client or genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def build_context(mid: int, transcript_lines: int = 40) -> str:
    m = db.row("SELECT title, agenda, context_text, series_id FROM meetings WHERE id=?", mid) or {}
    records = db.rows("SELECT * FROM records ORDER BY id")
    notes = db.rows("SELECT record_id, note, ts FROM record_notes ORDER BY id")
    tasks = db.rows("SELECT id, title, owner, due_at, status, last_update FROM tasks "
                    "WHERE status != 'done' AND (series_id=? OR meeting_id=?)", m.get("series_id"), mid)
    lines = db.rows("SELECT speaker, text FROM utterances WHERE meeting_id=? ORDER BY id DESC LIMIT ?",
                    mid, transcript_lines)[::-1]
    # Long-term series memory: what the last meetings of this series decided and left open.
    prev = db.rows("SELECT title, created_at, mom_json FROM meetings WHERE series_id=? AND id<? AND mom_json IS NOT NULL "
                   "ORDER BY id DESC LIMIT 3", m.get("series_id"), mid) if m.get("series_id") else []
    rec_txt = "\n".join(
        f"- {r['id']} [{r['kind']}] {r['name']} | status: {r['status']} | owner: {r['owner']} | {r['details']}"
        + "".join(f"\n    note ({n['ts'][:10]}): {n['note']}" for n in notes if n["record_id"] == r["id"])
        for r in records)
    return (f"MEETING: {m.get('title', '')}\nAGENDA:\n{m.get('agenda') or '-'}\n"
            f"CONTEXT:\n{m.get('context_text') or '-'}\n\nRECORDS:\n{rec_txt}\n\n"
            f"OPEN TASKS:\n" + ("\n".join(f"- #{t['id']} {t['title']} (owner {t['owner']}, due {t['due_at']}, "
                                          f"{t['status']})" for t in tasks) or "-")
            + "\n\nPREVIOUS MEETINGS:\n" + ("\n".join(_mom_brief(p) for p in prev[::-1]) or "-")
            + "\n\nTRANSCRIPT (most recent last):\n" + "\n".join(f"{u['speaker']}: {u['text']}" for u in lines))


def _mom_brief(p: dict) -> str:
    mom = json.loads(p["mom_json"] or "{}")
    return (f"- {p['title']} ({(p['created_at'] or '')[:10]}): {mom.get('executive_summary') or '-'}"
            + "".join(f"\n    decided: {d}" for d in mom.get("decisions") or [])
            + "".join(f"\n    left open: {q}" for q in mom.get("open_questions") or []))


async def chat_completion(model: str, system: str, prompt: str, max_tokens: int | None = None,
                          image_png: bytes | None = None) -> str:
    model, _, effort = model.partition("@")
    effort = effort or LLM_REASONING_EFFORT
    global _http
    _http = _http or httpx.AsyncClient(timeout=LLM_TIMEOUT)  # kept alive: no TLS/TCP setup per reply
    r = await _http.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"},
        json={"model": model, "temperature": 0.2, "max_tokens": max_tokens or LLM_MAX_TOKENS,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt if not image_png else [
                  {"type": "text", "text": prompt},
                  {"type": "image_url",
                   "image_url": {"url": "data:image/png;base64," + base64.b64encode(image_png).decode()}}]}],
              **({"reasoning_effort": effort} if effort else {})},
    )
    r.raise_for_status()
    choice = r.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError(f"{model} hit the token cap, reply would be cut off")
    return (choice["message"].get("content") or "").strip()


async def gemini(model: str, system: str, prompt: str, max_tokens: int | None = None,
                 image_png: bytes | None = None) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=max_tokens or 120, temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=0))  # thinking adds seconds of latency
    r = await asyncio.wait_for(
        client().aio.models.generate_content(
            model=model, config=cfg,
            contents=[types.Part.from_bytes(data=image_png, mime_type="image/png"), prompt] if image_png else prompt), CALL_TIMEOUT)
    if r.candidates and r.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS:
        raise RuntimeError(f"{model} hit the token cap, reply would be cut off")
    return (r.text or "").strip()


def providers() -> list[tuple[str, callable]]:
    """Ordered fallbacks: the OpenAI-compatible endpoint first, then Gemini models."""
    out = []
    if LLM_BASE_URL:
        out += [(f"openai:{m}", lambda s, p, t, i, m=m: chat_completion(m, s, p, t, i)) for m in LLM_MODELS]
    if os.getenv("GEMINI_API_KEY"):
        out += [(f"gemini:{m}", lambda s, p, t, i, m=m: gemini(m, s, p, t, i)) for m in MODELS]
    return out


async def complete(system: str, prompt: str, max_tokens: int | None = None, image_png: bytes | None = None) -> str:
    err: Exception = RuntimeError("no LLM configured: set LLM_BASE_URL or GEMINI_API_KEY")
    for name, call in providers():
        try:
            return await call(system, prompt, max_tokens, image_png)
        except Exception as e:  # 429 / 503 overload / timeout / truncation -> try the next one
            print(f"[brain] {name} failed: {type(e).__name__} {str(e)[:80]}")
            err = e
    raise err


async def answer(mid: int, speaker: str, question: str, screen_png: bytes | None = None) -> str:
    screen = "SCREEN: the attached image is the current screen share.\n\n" if screen_png else ""
    prompt = f"{build_context(mid)}\n\n{screen}{speaker} asked Amber: {question}"
    return await complete(ANSWER_RULES, prompt, image_png=screen_png) or FALLBACK


EXTRACT_RULES = """You keep the action items and the record system up to date for a live work meeting.
Read the NEW TRANSCRIPT lines and return ONLY a JSON object, no prose, no code fences:
{"tasks": [{"title": "...", "owner": "person name", "due": "YYYY-MM-DD or null", "quote": "exact words"}],
 "task_updates": [{"task_id": 3, "status": "open|in_progress|done|blocked", "note": "...", "quote": "..."}],
 "record_notes": [{"record_id": "PO-1041", "note": "...", "new_status": "short status or null",
                   "confidence": 0.0, "candidates": ["PO-1041"], "quote": "exact words"}]}
Rules:
- tasks: only explicit commitments or assignments ("I'll send the quote by Friday", "Priya, please close the
  PPE order by Wednesday"). owner = the person who will do the work. Resolve relative dates against TODAY.
  If a task already exists in OPEN TASKS, do not repeat it; report progress on it in task_updates instead.
- record_notes: only when the discussion gives NEW information about a specific record (status change, delay,
  issue, decision). Never restate what the record already says. confidence = how sure you are WHICH record
  is meant. candidates = every record id that could fit. If more than one could fit (e.g. "the pump" with
  several pump-related records), list them all and keep confidence at 0.7 or below.
- new_status: only if the discussion clearly changes the record's status, else null.
- Ignore questions asked to Amber and Amber's own lines. Use empty lists when nothing applies."""


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in fences or add a sentence; take the outermost object."""
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


async def extract(mid: int, after_id: int) -> tuple[dict, int]:
    """Tasks, task updates and record notes from human lines with id > after_id. Returns (result, last id seen)."""
    m = db.row("SELECT series_id FROM meetings WHERE id=?", mid) or {}
    new = db.rows("SELECT id, speaker, text FROM utterances WHERE meeting_id=? AND id>? AND speaker!='Amber' "
                  "ORDER BY id", mid, after_id)
    if not new:
        return {}, after_id
    before = db.rows("SELECT speaker, text FROM utterances WHERE meeting_id=? AND id<=? AND speaker!='Amber' "
                     "ORDER BY id DESC LIMIT 6", mid, after_id)[::-1]
    records = db.rows("SELECT id, kind, name, aliases, status, owner FROM records ORDER BY id")
    tasks = db.rows("SELECT id, title, owner, due_at, status FROM tasks WHERE status!='done' "
                    "AND (series_id=? OR meeting_id=?)", m.get("series_id"), mid)
    people = db.rows("SELECT name FROM attendees WHERE meeting_id=?", mid)
    now = datetime.now().astimezone()
    prompt = (
        f"TODAY: {now:%A %Y-%m-%d}\nATTENDEES: {', '.join(p['name'] for p in people) or '-'}\n\nRECORDS:\n"
        + "\n".join(f"- {r['id']} [{r['kind']}] {r['name']} (aka {r['aliases']}) | status: {r['status']} | "
                    f"owner: {r['owner']}" for r in records)
        + "\n\nOPEN TASKS:\n" + ("\n".join(f"- #{t['id']} {t['title']} (owner {t['owner']}, due {t['due_at']}, "
                                          f"{t['status']})" for t in tasks) or "-")
        + "\n\nEARLIER CONTEXT (already processed):\n" + ("\n".join(f"{u['speaker']}: {u['text']}" for u in before) or "-")
        + "\n\nNEW TRANSCRIPT:\n" + "\n".join(f"{u['speaker']}: {u['text']}" for u in new))
    return _parse_json(await complete(EXTRACT_RULES, prompt, max_tokens=1200)), new[-1]["id"]


MOM_RULES = """You write the Minutes of Meeting (MOM) for a work meeting from its transcript.
Return ONLY a JSON object, no prose, no code fences:
{"executive_summary": "3-5 sentences: what the meeting was about and what came out of it",
 "agenda_alignment": [{"item": "agenda item", "status": "covered|partly covered|not covered", "notes": "one line"}],
 "decisions": ["each decision actually made, one line each"],
 "open_questions": ["things raised but left unresolved or deferred, one line each"]}
Rules: use only what is in the transcript, records and tasks given. Do not invent decisions; a commitment
someone made is a task, not a decision. If there was no agenda, use an empty agenda_alignment list.
Use empty lists when nothing applies. Lines from "Amber" are the AI assistant's answers."""


MOM_MAX_CHARS = int(os.getenv("AMBER_MOM_MAX_CHARS", "80000"))  # ~20k tokens; a long meeting keeps its latest part


def _tail(text: str) -> str:
    return text if len(text) <= MOM_MAX_CHARS else "[earlier part of the meeting omitted]\n" + text[-MOM_MAX_CHARS:]


async def make_mom(mid: int) -> dict:
    """Narrative parts of the MOM from the LLM. Facts (tasks, record notes, attendance) are added by the caller
    straight from the database, so they can't be hallucinated."""
    m = db.row("SELECT title, agenda, context_text FROM meetings WHERE id=?", mid) or {}
    lines = db.rows("SELECT speaker, text FROM utterances WHERE meeting_id=? ORDER BY id", mid)
    tasks = db.rows("SELECT title, owner, due_at, status FROM tasks WHERE meeting_id=?", mid)
    notes = db.rows("SELECT record_id, note FROM record_notes WHERE meeting_id=?", mid)
    prompt = (f"MEETING: {m.get('title')}\nAGENDA:\n{m.get('agenda') or '-'}\nCONTEXT:\n{m.get('context_text') or '-'}\n\n"
              "TASKS CAPTURED:\n" + ("\n".join(f"- {t['owner']}: {t['title']} (due {t['due_at']}, {t['status']})"
                                              for t in tasks) or "-")
              + "\n\nRECORD UPDATES:\n" + ("\n".join(f"- {n['record_id']}: {n['note']}" for n in notes) or "-")
              + "\n\nTRANSCRIPT:\n" + _tail("\n".join(f"{u['speaker']}: {u['text']}" for u in lines)))
    out = _parse_json(await complete(MOM_RULES, prompt, max_tokens=1500))
    return {k: out.get(k) or ([] if k != "executive_summary" else "") for k in
            ("executive_summary", "agenda_alignment", "decisions", "open_questions")}
