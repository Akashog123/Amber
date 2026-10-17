"""Draft labels for real meetings: which human lines were (part of) a request to Amber. Writes evals/live.json in
the eval_scenarios format, so the same scorer measures turn-taking on what people actually said. The draft is
model-made: review it by hand before trusting it (see "reviewed" in the file).

  uv run python evals/label_live.py 17 18 19 20
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import httpx  # noqa: E402

import brain  # noqa: E402
import db  # noqa: E402

RULES = """You label a real meeting transcript for evaluating an AI meeting assistant named Amber. The transcript
includes Amber's own spoken replies (marked AMBER) for context. For EVERY human line (numbered), decide if it is
(part of) a request to Amber: a question or instruction for her, including follow-ups without her name when the
person is clearly still talking with her ("and the booster pump?", "summary bolo", "can you resume the
recording?"). Lines aimed at other people, side talk between humans, acknowledgements ("okay", "thanks"), thinking
aloud, or talk ABOUT Amber are not requests. Consecutive segments of one request share one integer id.
Return ONLY JSON: {"labels": {"<line number>": <request id or null>, ...}} covering every numbered line."""


def lines_of(mid: int) -> list[dict]:
    return db.rows("SELECT id, speaker, text, ts FROM utterances WHERE meeting_id=? ORDER BY id", mid)


def draft(mid: int) -> dict:
    rows = lines_of(mid)
    numbered, human, n = [], [], 0
    for r in rows:
        if r["speaker"] == "Amber":
            numbered.append(f"AMBER: {r['text']}")
        else:
            n += 1
            human.append(r)
            numbered.append(f"{n}. {r['speaker']}: {r['text']}")
    model = brain.LLM_MODELS[0].partition("@")[0]
    with httpx.Client(timeout=300) as c:
        r = c.post(f"{brain.LLM_BASE_URL}/chat/completions",
                   headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"},
                   json={"model": model, "temperature": 0, "max_tokens": 6000, "messages": [
                       {"role": "system", "content": RULES}, {"role": "user", "content": "\n".join(numbered)}]})
        r.raise_for_status()
    labels = brain._parse_json(r.json()["choices"][0]["message"]["content"] or "").get("labels", {})
    out, prev = [], None
    for i, h in enumerate(human, 1):
        ts = h["ts"]
        gap = 1.0 if prev is None or ts is None else max(0.2, min(8.0, ts - prev))
        prev = ts if ts is not None else prev
        q = labels.get(str(i))
        out.append({"speaker": h["speaker"].split(" ")[0], "text": h["text"], "gap": round(gap, 2),
                    "q": None if q is None else int(q) + mid * 1000})
    speakers = sorted({x["speaker"] for x in out})
    return {"title": f"Live meeting {mid}", "speakers": speakers, "lines": out, "reviewed": False}


if __name__ == "__main__":
    path = Path(__file__).parent / "live.json"
    saved = {s["title"]: s for s in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])}
    for mid in map(int, sys.argv[1:]):
        sc = draft(mid)
        saved[sc["title"]] = sc
        print(f"meeting {mid}: {len(sc['lines'])} lines, {len({x['q'] for x in sc['lines'] if x['q']})} requests")
    path.write_text(json.dumps(list(saved.values()), ensure_ascii=False, indent=1), encoding="utf-8")
