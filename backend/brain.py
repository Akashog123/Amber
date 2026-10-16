"""LLM reasoning (Gemini). Grounded answers now; extraction / tagging / MOM come next."""
import os

from google import genai
from google.genai import types

import db

FALLBACK = "I don't have that information in my current records."
# 2.5 models 404 for new keys; lite models were slower (5-7s) in testing. Second = fallback on 429/503.
MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash"), "gemini-3.8-flash"]

ANSWER_RULES = f"""You are Amber, an AI meeting assistant built by this team for this meeting (not made by Google or any
AI company). You take part in the live call, answer questions from the meeting context and records, and keep notes.
You were just addressed by name.
Reply in 1-2 short spoken sentences, under 35 words. No markdown, no lists, no preamble.
For facts about this company, its records, orders, equipment, people, tasks, numbers or decisions,
use ONLY the CONTEXT, RECORDS, OPEN TASKS and TRANSCRIPT below. If that information is not there,
reply exactly: "{FALLBACK}"
General knowledge or concept questions may be answered from your own knowledge.
Never invent record IDs, dates, amounts or owners."""

_client: genai.Client | None = None


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
    rec_txt = "\n".join(
        f"- {r['id']} [{r['kind']}] {r['name']} | status: {r['status']} | owner: {r['owner']} | {r['details']}"
        + "".join(f"\n    note ({n['ts'][:10]}): {n['note']}" for n in notes if n["record_id"] == r["id"])
        for r in records)
    return (f"MEETING: {m.get('title', '')}\nAGENDA:\n{m.get('agenda') or '-'}\n"
            f"CONTEXT:\n{m.get('context_text') or '-'}\n\nRECORDS:\n{rec_txt}\n\n"
            f"OPEN TASKS:\n" + ("\n".join(f"- #{t['id']} {t['title']} (owner {t['owner']}, due {t['due_at']}, "
                                          f"{t['status']})" for t in tasks) or "-")
            + "\n\nTRANSCRIPT (most recent last):\n" + "\n".join(f"{u['speaker']}: {u['text']}" for u in lines))


async def answer(mid: int, speaker: str, question: str) -> str:
    prompt = f"{build_context(mid)}\n\n{speaker} asked Amber: {question}"
    cfg = types.GenerateContentConfig(
        system_instruction=ANSWER_RULES, max_output_tokens=120, temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=0))  # thinking adds seconds of latency
    err = None
    for model in MODELS:
        try:
            r = await client().aio.models.generate_content(model=model, contents=prompt, config=cfg)
            if r.candidates and r.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS:
                raise RuntimeError(f"{model} hit the token cap, reply would be cut off")
            return (r.text or "").strip() or FALLBACK
        except Exception as e:  # 429 / 503 overload / truncation -> try the next model
            err = e
    raise err
