"""LLM reasoning. Any OpenAI-compatible server (LLM_BASE_URL, e.g. a local proxy) and/or Gemini.
Grounded answers now; extraction / tagging / MOM come next."""
import asyncio
import os

import httpx
from google import genai
from google.genai import types

import db

FALLBACK = "I don't have that information in my current records."
SORRY = "Sorry, I couldn't get that. Could you ask again?"
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
General knowledge or concept questions may be answered from your own knowledge.
Never invent record IDs, dates, amounts or owners."""

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
    rec_txt = "\n".join(
        f"- {r['id']} [{r['kind']}] {r['name']} | status: {r['status']} | owner: {r['owner']} | {r['details']}"
        + "".join(f"\n    note ({n['ts'][:10]}): {n['note']}" for n in notes if n["record_id"] == r["id"])
        for r in records)
    return (f"MEETING: {m.get('title', '')}\nAGENDA:\n{m.get('agenda') or '-'}\n"
            f"CONTEXT:\n{m.get('context_text') or '-'}\n\nRECORDS:\n{rec_txt}\n\n"
            f"OPEN TASKS:\n" + ("\n".join(f"- #{t['id']} {t['title']} (owner {t['owner']}, due {t['due_at']}, "
                                          f"{t['status']})" for t in tasks) or "-")
            + "\n\nTRANSCRIPT (most recent last):\n" + "\n".join(f"{u['speaker']}: {u['text']}" for u in lines))


async def chat_completion(model: str, system: str, prompt: str) -> str:
    model, _, effort = model.partition("@")
    effort = effort or LLM_REASONING_EFFORT
    global _http
    _http = _http or httpx.AsyncClient(timeout=LLM_TIMEOUT)  # kept alive: no TLS/TCP setup per reply
    r = await _http.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"},
        json={"model": model, "temperature": 0.2, "max_tokens": LLM_MAX_TOKENS,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
              **({"reasoning_effort": effort} if effort else {})},
    )
    r.raise_for_status()
    choice = r.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError(f"{model} hit the token cap, reply would be cut off")
    return (choice["message"].get("content") or "").strip()


async def gemini(model: str, system: str, prompt: str) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=120, temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=0))  # thinking adds seconds of latency
    r = await asyncio.wait_for(
        client().aio.models.generate_content(model=model, contents=prompt, config=cfg), CALL_TIMEOUT)
    if r.candidates and r.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS:
        raise RuntimeError(f"{model} hit the token cap, reply would be cut off")
    return (r.text or "").strip()


def providers() -> list[tuple[str, callable]]:
    """Ordered fallbacks: the OpenAI-compatible endpoint first, then Gemini models."""
    out = []
    if LLM_BASE_URL:
        out += [(f"openai:{m}", lambda s, p, m=m: chat_completion(m, s, p)) for m in LLM_MODELS]
    if os.getenv("GEMINI_API_KEY"):
        out += [(f"gemini:{m}", lambda s, p, m=m: gemini(m, s, p)) for m in MODELS]
    return out


async def complete(system: str, prompt: str) -> str:
    err: Exception = RuntimeError("no LLM configured: set LLM_BASE_URL or GEMINI_API_KEY")
    for name, call in providers():
        try:
            return await call(system, prompt)
        except Exception as e:  # 429 / 503 overload / timeout / truncation -> try the next one
            print(f"[brain] {name} failed: {type(e).__name__} {str(e)[:80]}")
            err = e
    raise err


async def answer(mid: int, speaker: str, question: str) -> str:
    prompt = f"{build_context(mid)}\n\n{speaker} asked Amber: {question}"
    return await complete(ANSWER_RULES, prompt) or FALLBACK
