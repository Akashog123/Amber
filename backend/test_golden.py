"""Real calls as permanent tests. Each golden/<name>.jsonl is a trimmed Recall webhook log from a live meeting;
it is replayed through the real webhook handler at the call's own timing (sped up), with the LLM stubbed, and
golden/<name>.expect.json says which questions Amber must answer (in order) and which lines she must not.

  uv run python test_golden.py                                   # check every fixture
  uv run python test_golden.py --add logs/recall-<bot>.jsonl name # new fixture + a draft expectation to edit
"""
import os
import sys
import tempfile

os.environ["AMBER_DB"] = os.path.join(tempfile.mkdtemp(), "golden.db")
for k in ("RECALL_API_KEY", "SMTP_USER") + (() if os.getenv("GOLDEN_REAL_LLM") else ("GEMINI_API_KEY", "LLM_BASE_URL")):
    os.environ[k] = ""  # blank, not unset: main's load_dotenv() would reload real keys
os.environ["ELEVENLABS_API_KEY"] = "stub"  # voice is stubbed below; set so Amber "speaks" and timing is real
os.environ["WEBHOOK_TOKEN"] = "t"

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import db  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import brain  # noqa: E402
import main  # noqa: E402
import voice  # noqa: E402

DIR = Path(__file__).parent / "golden"
SPEED = 4.0       # replay 4x faster; Amber's timers are scaled to match
ANSWER_SEC = 3.0  # real question-end -> reply time on live calls (model + voice + playback upload)
MAX_GAP = 12.0    # seconds of call time
REPLY_AUDIO = 4.0   # seconds a typical spoken answer lasts (she's "speaking" this long: barge-in, follow-up window)
FILLER_AUDIO = 0.8
classified: list[tuple[str, str]] = []  # unclear lines sent to the model (each is an extra LLM call)
real_is_for_amber = brain.is_for_amber


def silence(secs: float) -> bytes:
    return b"\0" * int(16000 * secs / SPEED)  # main reads 16 KB as one second of audio
EVENTS = {"transcript.data", "transcript.partial_data", "participant_events.join", "participant_events.leave",
          "participant_events.chat_message"}


def trim(event: dict) -> dict | None:
    """Keep what the handler reads; first names only (fixtures are committed)."""
    if event.get("event") not in EVENTS:
        return None
    d = (event.get("data") or {}).get("data") or {}
    who = ((d.get("participant") or {}).get("name") or "Unknown").split(" ")[0]
    out = {"participant": {"name": who}}
    for k in ("words", "timestamp", "data"):
        if d.get(k) is not None:
            out[k] = d[k]
    return {"event": event["event"], "data": {"data": out}}


def at(event: dict) -> float:
    """Seconds into the call when Recall would have sent this event."""
    d = event["data"]["data"]
    if d.get("words"):
        end = d["words"][-1]["end_timestamp"]["relative"]
        return end + (0.3 if event["event"] == "transcript.data" else 0)  # finals wait out Deepgram endpointing
    return (d.get("timestamp") or {}).get("relative") or 0


def replay(events: list[dict], extract_script: list[dict] = (), real_classifier: bool = False,
           ) -> tuple[list[tuple[str, str]], list[str]]:
    """Returns (answered questions, records a person confirmed). extract_script: what the extraction model
    "finds" once a line containing `after` has been said, e.g. an ambiguous record note. real_classifier: unclear
    lines go to the real model (eval_scenarios.py) instead of a stub that always says no."""
    answered: list[tuple[str, str]] = []
    script = list(extract_script)

    async def stub_answer(mid, speaker, question, screen_png=None):
        await asyncio.sleep(ANSWER_SEC / SPEED)
        answered.append((speaker, question))  # only answers that weren't cancelled/restarted along the way
        return "ok"

    async def stub_extract(mid, after):
        new = db.rows("SELECT id, text FROM utterances WHERE meeting_id=? AND id>? AND speaker!='Amber'", mid, after)
        hit = next((s for s in script if any(s["after"].lower() in u["text"].lower() for u in new)), None)
        if hit:
            script.remove(hit)
        return (hit or {}).get("result", {}), (new[-1]["id"] if new else after)

    brain.answer = stub_answer
    brain.extract = stub_extract
    classified.clear()

    async def stub_is_for_amber(mid, speaker, line):  # conservative: unclear lines aren't for her
        classified.append((speaker, line))
        return await real_is_for_amber(mid, speaker, line) if real_classifier else False

    brain.is_for_amber = stub_is_for_amber
    voice.tts = lambda text, model=None: asyncio.sleep(0, silence(REPLY_AUDIO))
    voice.filler_mp3 = lambda text: asyncio.sleep(0, silence(FILLER_AUDIO))
    voice.warm_fillers = lambda *a: asyncio.sleep(0)
    for name in ("DEBOUNCE", "BARE_WAIT", "FOLLOWUP", "FILLER_AFTER", "FILLER_GAP"):
        setattr(main, name, getattr(main, name) / SPEED)
    with TestClient(main.app) as c:
        bot = c.post("/api/meetings/dispatch", json={"title": "golden", "url": "https://meet.google.com/g",
                                                      "replay": True}).json()["bot_id"]
        # Arrival order as logged (that's what Recall did); times never go backwards. Long silences are squeezed
        # to MAX_GAP, still longer than every timer Amber has.
        clock, prev, times = 0.0, at(events[0]), []
        for e in events:
            now = max(at(e), prev)
            clock += min(now - prev, MAX_GAP)
            prev = now
            times.append(clock)
        t0 = time.monotonic()
        for e, t in zip(events, times):
            time.sleep(max(0, t / SPEED - (time.monotonic() - t0)))
            e["data"]["bot"] = {"id": bot}
            c.post("/webhooks/recall?token=t", json=e).raise_for_status()
        time.sleep((ANSWER_SEC + main.BARE_WAIT * SPEED + 1) / SPEED + 0.5)
        mid = db.row("SELECT id FROM meetings WHERE bot_id=?", bot)["id"]
    for name in ("DEBOUNCE", "BARE_WAIT", "FOLLOWUP", "FILLER_AFTER", "FILLER_GAP"):
        setattr(main, name, getattr(main, name) * SPEED)
    confirmed = [n["record_id"] for n in db.rows(
        "SELECT record_id FROM record_notes WHERE meeting_id=? AND confidence=1.0 ORDER BY id", mid)]
    return answered, confirmed


def check(name: str) -> list[str]:
    events = [json.loads(line) for line in (DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]
    expect = json.loads((DIR / f"{name}.expect.json").read_text(encoding="utf-8"))
    answered, confirmed = replay(events, expect.get("extract", []))
    problems, i = [], 0
    if "confirmed" in expect and confirmed != expect["confirmed"]:
        problems.append(f"records confirmed {confirmed}, expected {expect['confirmed']}")
    for want in expect["answers"]:  # in order, each matched by a later answer than the previous one
        j = next((j for j in range(i, len(answered)) if answered[j][0] == want["speaker"]
                  and want["has"].lower() in answered[j][1].lower()), None)
        if j is None:
            problems.append(f"not answered: {want['speaker']}: ...{want['has']}...")
        else:
            i = j + 1
    for bad in expect.get("never", []):
        problems += [f"answered a line she should ignore: {s}: {q}" for s, q in answered if bad.lower() in q.lower()]
    if len(answered) > expect.get("max_answers", 999):
        problems.append(f"{len(answered)} answers, expected at most {expect['max_answers']}")
    if problems:
        problems.append("answered: " + json.dumps(answered, ensure_ascii=False, indent=1))
    return problems


def add(log: str, name: str):
    DIR.mkdir(exist_ok=True)
    raw = [json.loads(line) for line in Path(log).read_text(encoding="utf-8").splitlines()]
    events = [t for t in map(trim, raw) if t]
    (DIR / f"{name}.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), "utf-8")
    answered, _ = replay(json.loads(json.dumps(events)))
    draft = {"answers": [{"speaker": s, "has": q} for s, q in answered], "never": [], "max_answers": len(answered)}
    path = DIR / f"{name}.expect.json"
    if not path.exists():
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=1), "utf-8")
    print(f"wrote {name}: {len(events)} events. Edit {path.name}: answers she MUST give, lines she must NOT answer.")
    for s, q in answered:
        print(f"  {s}: {q}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--add"]:
        add(sys.argv[2], sys.argv[3])
        sys.exit()
    failed = False
    for f in sorted(DIR.glob("*.expect.json")):
        name = f.name.removesuffix(".expect.json")
        problems = check(name)
        print(f"{name}: {'ok' if not problems else 'FAILED'} ({len(classified)} unclear lines sent to the model)")
        for s, line in classified:
            print(f"    classify: {s}: {line}")
        for p in problems:
            print("  " + p)
        failed |= bool(problems)
    sys.exit(1 if failed else 0)
