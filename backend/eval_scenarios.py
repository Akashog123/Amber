"""Generated meetings as an eval of Amber's turn-taking (uses the real model; not a unit test).

The model writes realistic multi-person meeting scripts and labels which lines are (part of) a request to
Amber. Each script becomes timed webhook events (partials included) and goes through the real routing, with the
real "is this for Amber?" check; answers themselves are stubbed. Reported: missed requests, false triggers,
and how many lines needed the model (each is an extra LLM call).

  uv run python eval_scenarios.py          # run the saved scenarios (evals/scenarios.json)
  uv run python eval_scenarios.py --new 4  # generate 4 new ones first (appended to the file)
"""
import os
import sys

from dotenv import load_dotenv  # noqa: E402

load_dotenv()  # before brain is imported: it reads the LLM settings at import
os.environ["GOLDEN_REAL_LLM"] = "1"  # and test_golden must not blank them

import asyncio  # noqa: E402
import json  # noqa: E402
import httpx  # noqa: E402
from pathlib import Path  # noqa: E402

import test_golden as g  # noqa: E402
import brain  # noqa: E402

FILE = Path(__file__).parent / "evals" / "scenarios.json"
WORD_SEC = 0.32  # speaking pace

GEN_RULES = """You write realistic transcripts of short work meetings (procurement / plant maintenance, India) that an
AI assistant named Amber attends. Write it as live speech recognition delivers it: one item per final transcript
segment, so a sentence can be split ("Amber," then "what's the ETA on the seals"), with fillers, half sentences,
people talking to each other, and some Hinglish. Amber's own replies are NOT in the script.
Label every item: "q" = the same integer for all segments of one request to Amber (a question or an instruction
for her), null for everything else. A follow-up to Amber right after she answered that person counts as a request
even without her name ("and the booster pump?"). Lines naming or aimed at other people, acknowledgements ("okay,
thanks"), thinking aloud and side talk are null.
Each scenario must include: a request with "Amber," split from its question; a follow-up without her name; a line
that names another person right after asking Amber something; a backchannel; a correction ("actually, I mean ...");
one cancelled request ("never mind"); and plain discussion Amber must not answer.
"gap" = seconds of silence before the segment (people wait ~5 s for Amber's answer after a request).
Return ONLY JSON: {"scenarios": [{"title": "...", "speakers": ["Akash", "Priya", "Rahul"],
"lines": [{"speaker": "Akash", "text": "...", "gap": 1.0, "q": 1}]}]}"""


def to_events(sc: dict) -> list[dict]:
    """A script -> Recall-shaped events: partials word by word, then the final."""
    t, out = 0.0, []
    for s in sc["speakers"]:
        out.append({"event": "participant_events.join",
                    "data": {"data": {"participant": {"name": s}, "timestamp": {"relative": t}}}})
    for line in sc["lines"]:
        t += float(line.get("gap") or 1.0)
        words = []
        for i, w in enumerate(line["text"].split()):
            words.append({"text": w, "start_timestamp": {"relative": t + i * WORD_SEC},
                          "end_timestamp": {"relative": t + (i + 1) * WORD_SEC - 0.05}})
            if i % 3 == 2:  # a partial every few words, like Deepgram
                out.append({"event": "transcript.partial_data",
                            "data": {"data": {"participant": {"name": line["speaker"]}, "words": list(words)}}})
        out.append({"event": "transcript.data", "data": {"data": {"participant": {"name": line["speaker"]},
                                                                  "words": words}}})
        t = words[-1]["end_timestamp"]["relative"]
    return out


def score(sc: dict, answered: list[tuple[str, str]]) -> dict:
    asks: dict[int, list[dict]] = {}
    for line in sc["lines"]:
        if line.get("q") is not None:
            asks.setdefault(int(line["q"]), []).append(line)
    # A request is withdrawn if it, or the same speaker's very next segment, cancels it ("..." / "never mind").
    lines = sc["lines"]
    nxt = {i: next((x for x in lines[i + 1:] if x["speaker"] == lines[i]["speaker"]), None) for i in range(len(lines))}
    cancelled = {int(line["q"]) for i, line in enumerate(lines) if line.get("q") is not None and any(
        x and g.main.CANCEL.search(x["text"]) for x in (line, nxt[i]))}
    missed = [q for q, ls in asks.items() if q not in cancelled and not any(
        s == ls[-1]["speaker"] and ls[-1]["text"].lower().strip(" ?.") in a.lower() for s, a in answered)]
    false = [line["text"] for line in sc["lines"] if line.get("q") is None and len(line["text"].split()) > 1
             and any(line["text"].lower().strip(" ?.") in a.lower() for _, a in answered)]
    return {"requests": len(asks) - len(cancelled), "missed": [asks[q][-1]["text"] for q in missed], "false": false}


async def generate(n: int, start: int = 0) -> list[dict]:
    """One scenario per call, with a long timeout (the live-answer timeout is far too short for this)."""
    model = brain.LLM_MODELS[0].partition("@")[0]
    themes = ["pump and seal deliveries", "chiller vibration and the service contract", "PPE order and safety audit",
              "boiler inspection and cooling tower", "VFD installation and budget", "air compressor downtime"]
    out = []
    async with httpx.AsyncClient(timeout=240) as c:
        for i in range(n):
            r = await c.post(f"{brain.LLM_BASE_URL}/chat/completions",
                             headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"},
                             json={"model": model, "temperature": 0.9, "max_tokens": 3000, "messages": [
                                 {"role": "system", "content": GEN_RULES},
                                 {"role": "user", "content": f"Write 1 scenario about {themes[(start + i) % len(themes)]}, "
                                                             "18-26 segments."}]})
            r.raise_for_status()
            out += brain._parse_json(r.json()["choices"][0]["message"]["content"] or "").get("scenarios", [])
    return out


def main():
    saved = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else []
    if sys.argv[1:2] == ["--new"]:
        new = asyncio.run(generate(int(sys.argv[2]) if len(sys.argv) > 2 else 3, len(saved)))
        saved += new
        FILE.parent.mkdir(exist_ok=True)
        FILE.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"generated {len(new)} scenarios -> {FILE.name} ({len(saved)} total)")
    totals = {"requests": 0, "missed": 0, "false": 0, "classified": 0}
    for sc in saved:
        answered, _ = g.replay(to_events(sc), real_classifier=True)
        r = score(sc, answered)
        totals["requests"] += r["requests"]
        totals["missed"] += len(r["missed"])
        totals["false"] += len(r["false"])
        totals["classified"] += len(g.classified)
        print(f"{sc['title'][:60]}: {r['requests'] - len(r['missed'])}/{r['requests']} answered, "
              f"{len(r['false'])} false, {len(g.classified)} model checks")
        for m in r["missed"]:
            print(f"    missed: {m}")
        for f in r["false"]:
            print(f"    false trigger: {f}")
    print(f"TOTAL: {totals['requests'] - totals['missed']}/{totals['requests']} requests answered, "
          f"{totals['false']} false triggers, {totals['classified']} model checks")


if __name__ == "__main__":
    main()
