"""uv run python test_core.py — wake word, URL detection, and a full replay through the webhook."""
import os
import tempfile

os.environ["AMBER_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
# Blank (not pop): main's load_dotenv() would otherwise re-load real keys from .env and hit live APIs.
for k in ("RECALL_API_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY", "LLM_BASE_URL", "RECALL_TRANSCRIBER"):
    os.environ[k] = ""
os.environ["WEBHOOK_TOKEN"] = "t"

from fastapi.testclient import TestClient  # noqa: E402

import asyncio  # noqa: E402
import time  # noqa: E402

import brain  # noqa: E402
import main  # noqa: E402
import replay  # noqa: E402

assert main.is_addressed("Agreed. Amber, what's the status?")
assert main.is_addressed("ember can you check")  # ASR mishearing
assert not main.is_addressed("the amberjack fish")
# Real mishearings from the live Meet test, plus lookalikes that must NOT trigger.
assert main.is_addressed("hey i'm very can you tell me what's the time now")
assert main.is_addressed("ember what's the pump status")
assert main.is_addressed("hamburger can you tell me who are you")
assert not main.is_addressed("i am very sure about the quote")  # sounds similar but not a request
assert not main.is_addressed("the number of pumps is two")
assert not main.is_addressed("hello am i audible to you")
assert main.detect_platform("https://meet.google.com/abc-defg-hij") == "google_meet"
assert main.detect_platform("https://us02web.zoom.us/j/123") == "zoom"
assert main.detect_platform("http://meet.google.com/abc") is None
assert main.detect_platform("https://evil.com/meet.google.com") is None

asked = []


async def fake_answer(mid, speaker, question):
    asked.append(question)
    await asyncio.sleep(0.15)  # answer is "in flight" for a moment, like the real API
    return brain.FALLBACK if "marketing" in question else f"answer to {speaker}"

brain.answer = fake_answer
main.DEBOUNCE = 0.1
main.BARE_WAIT = 0.5

c = TestClient(main.app)
c.__enter__()  # keep the app's event loop alive between requests so reply tasks run


def say(bot, who, text):
    c.post("/webhooks/recall?token=t", json=replay.payload(bot, 0, "say", who, text)).raise_for_status()


def replies(mid):
    time.sleep(0.6)
    m = c.get(f"/api/meetings/{mid}").json()
    return [u["text"] for u in m["transcript"] if u["speaker"] == "Amber"], [x for x in m["chat"] if x["is_amber"]]


assert c.post("/webhooks/recall?token=wrong", json={}).status_code == 401
mid = replay.run(c, speed=20)  # real gaps between lines (shortest 0.05s... see SCRIPT)
m = c.get(f"/api/meetings/{mid}").json()
assert m["status"] == "done" and m["ended_at"], m["status"]
voice, chat = replies(mid)
m = c.get(f"/api/meetings/{mid}").json()
assert voice == ["answer to Akash", brain.FALLBACK], voice  # both spoken questions answered, in order
assert len(chat) == 1 and chat[0]["text"] == "answer to Priya"  # chat question answered in chat
assert len([u for u in m["transcript"] if u["speaker"] != "Amber"]) == sum(1 for s in replay.SCRIPT if s[1] == "say")
assert sum(u["addressed"] for u in m["transcript"]) == 2
assert {p["name"] for p in m["participants"]} == {"Akash", "Rahul", "Priya"}
assert all(p["left_at"] for p in m["participants"])
assert m["chat"][0]["sender"] == "Priya"
assert len(m["attendees"]) == 3
assert len(c.get("/api/records").json()) == 9
# Speaker rephrases before the debounce fires -> one answer built from the whole question.
d = c.post("/api/meetings/dispatch", json={"title": "t", "url": "https://meet.google.com/x", "replay": True}).json()
asked.clear()
say(d["bot_id"], "Akash", "Amber, what's the status of the pump")
say(d["bot_id"], "Akash", "actually no, the chiller service contract?")
say(d["bot_id"], "Rahul", "unrelated chatter")  # other people talking doesn't cancel Akash's question
assert replies(d["id"])[0] == ["answer to Akash"]
assert asked == ["Amber, what's the status of the pump actually no, the chiller service contract?"], asked

# "never mind" withdraws a pending question.
say(d["bot_id"], "Rahul", "Amber, how many PPE kits")
say(d["bot_id"], "Rahul", "oh never mind, found it")
assert replies(d["id"])[0] == ["answer to Akash"]  # still only the earlier answer
# Once Amber is answering, the asker moving on doesn't rewrite the question; a correction does.
asked.clear()
say(d["bot_id"], "Priya", "Amber, who owns the boiler?")
time.sleep(0.15)  # debounce fired, answer in flight
say(d["bot_id"], "Priya", "Okay, next item is the PPE order.")
time.sleep(0.6)
assert asked == ["Amber, who owns the boiler?"], asked
say(d["bot_id"], "Priya", "Amber, who owns the boiler?")
time.sleep(0.15)
say(d["bot_id"], "Priya", "actually I mean the cooling tower")
time.sleep(0.6)
assert asked[-1] == "Amber, who owns the boiler? actually I mean the cooling tower", asked
# Transcriber: Recall's English by default; Deepgram en-IN with Amber + record names when enabled.
import recall  # noqa: E402
terms = main.keyterms(mid)
assert terms[0] == "Amber" and "PO-1041" in terms and "Akash" in terms and len(terms) == len(set(terms))
assert "recallai_streaming" in recall.transcript_provider(terms)
os.environ["RECALL_TRANSCRIBER"] = "deepgram"
dg = recall.transcript_provider(terms)["deepgram_streaming"]
assert dg["model"] == "nova-3" and dg["language"] == "en-IN" and dg["keyterm"][0] == "Amber"
os.environ["RECALL_TRANSCRIBER"] = ""

# Fillers fit the question; greetings and questions about Amber herself get none.
assert main.filler_kind("amber what's the status of the pump order") == "lookup"
assert main.filler_kind("amber what is a vfd drive") == "think"
assert main.filler_kind("amber are you there") is None
assert main.filler_kind("amber who made you") is None
assert main.filler_kind("hey amber") is None

# Bare "Amber" then the question a moment later (seen live) -> one answer to the whole thing.
asked.clear()
say(d["bot_id"], "Priya", "amber")
time.sleep(0.3)  # longer than DEBOUNCE, shorter than BARE_WAIT
say(d["bot_id"], "Priya", "what's the status of the vfd drives")
time.sleep(0.8)
assert asked == ["amber what's the status of the vfd drives"], asked

# Every model down -> Amber says sorry instead of going silent.
async def broken_answer(mid, speaker, question):
    raise RuntimeError("503 UNAVAILABLE")

brain.answer = broken_answer
say(d["bot_id"], "Akash", "Amber, what's the status of the VFD drives?")
assert replies(d["id"])[0][-1] == brain.SORRY
brain.answer = fake_answer
print("ok")
