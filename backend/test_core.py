"""uv run python test_core.py — wake word, URL detection, and a full replay through the webhook."""
import os
import tempfile

os.environ["AMBER_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
# Blank (not pop): main's load_dotenv() would otherwise re-load real keys from .env and hit live APIs.
for k in ("RECALL_API_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY", "LLM_BASE_URL", "RECALL_TRANSCRIBER", "SMTP_USER", "AMBER_DEMO_REMINDER_MINUTES"):
    os.environ[k] = ""
os.environ["WEBHOOK_TOKEN"] = "t"

from fastapi.testclient import TestClient  # noqa: E402

import asyncio  # noqa: E402
import time  # noqa: E402

import brain  # noqa: E402
import main  # noqa: E402
import db  # noqa: E402
import mailer  # noqa: E402
import replay  # noqa: E402
import seed  # noqa: E402

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


async def no_extract(mid, after_id):
    return {}, after_id

brain.extract = no_extract  # background passes would need a real LLM; apply_extraction is tested directly
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
assert m["status"] in ("done", "processing", "completed") and m["ended_at"], m["status"]
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
assert len(c.get("/api/records").json()) == len(seed.RECORDS)
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

# Live Deepgram case: "Amber," final, the asker keeps talking (partials) past BARE_WAIT, then the question.
asked.clear()
say(d["bot_id"], "Akash", "Amber,")
for _ in range(4):  # 4 x 0.2s of partials = 0.8s, longer than BARE_WAIT (0.5s)
    time.sleep(0.2)
    c.post("/webhooks/recall?token=t", json={**replay.payload(d["bot_id"], 0, "say", "Akash", "what's the"),
                                             "event": "transcript.partial_data"}).raise_for_status()
say(d["bot_id"], "Akash", "what's the status of Chiller two?")
time.sleep(0.8)
assert asked == ["Amber, what's the status of Chiller two?"], asked

# --- Task extraction + record tagging with the confidence check (LLM output stubbed) ---
e = c.post("/api/meetings/dispatch", json={"title": "x", "url": "https://meet.google.com/y", "replay": True,
                                           "attendees": [{"name": "Rahul Mehta", "email": "rahul@example.com"},
                                                         {"name": "Priya", "email": "priya@example.com"}]}).json()
E = e["id"]
pump_note = {"record_id": "PO-1041", "note": "Delivery slipped two weeks", "confidence": 0.6,
             "candidates": ["PO-1041", "PO-1046"], "quote": "the Grundfos pump slipped two weeks"}
asyncio.run(main.apply_extraction(E, {
    "tasks": [{"title": "Send vendor quote", "owner": "Rahul", "due": "2026-10-23", "quote": "I'll send it by Friday"},
              {"title": "Send vendor quote", "owner": "Rahul", "due": "2026-10-23", "quote": "dup in same pass"}],
    "record_notes": [
        {"record_id": "PO-1043", "note": "Renewal approved", "new_status": "Renewal approved", "confidence": 0.95,
         "candidates": ["PO-1043"], "quote": "we approved the renewal"},
        pump_note,
        {"record_id": "EQ-204", "note": "maybe noisy", "confidence": 0.3, "candidates": ["EQ-204"]},
        {"record_id": "PO-9999", "note": "made-up record", "confidence": 0.99, "candidates": ["PO-9999"]}]}))
m = c.get(f"/api/meetings/{E}").json()
assert [(t["owner"], t["owner_email"], t["due_at"]) for t in m["tasks"]] == [("Rahul", "rahul@example.com", "2026-10-23")]
recs = {r["id"]: r for r in c.get("/api/records").json()}
assert recs["PO-1043"]["status"] == "Renewal approved" and recs["PO-1043"]["notes"][-1]["note"] == "Renewal approved"
assert not [n for n in recs["PO-1041"]["notes"] + recs["PO-1046"]["notes"] if n["meeting_id"] == E]  # asked, not written
assert not recs["EQ-204"]["notes"]  # low confidence ignored
asked_q = [x["text"] for x in m["chat"] if x["is_amber"]][-1]
assert "1) PO-1041" in asked_q and "2) PO-1046" in asked_q, asked_q

# Reply "2" in chat -> note lands on PO-1046 and Amber confirms.
c.post("/webhooks/recall?token=t", json=replay.payload(e["bot_id"], 0, "chat", "Priya", "2")).raise_for_status()
time.sleep(0.2)
recs = {r["id"]: r for r in c.get("/api/records").json()}
assert [n["note"] for n in recs["PO-1046"]["notes"] if n["meeting_id"] == E] == ["Delivery slipped two weeks"]
assert "noted on PO-1046" in [x["text"] for x in c.get(f"/api/meetings/{E}").json()["chat"] if x["is_amber"]][-1]

# Voice: "Amber, the first one" answers the question instead of being treated as a new question.
asyncio.run(main.apply_extraction(E, {"record_notes": [pump_note]}))
asked.clear()
say(e["bot_id"], "Priya", "Amber, the first one")
time.sleep(0.4)
assert asked == [], asked  # not sent to the answer path
recs = {r["id"]: r for r in c.get("/api/records").json()}
assert [n["note"] for n in recs["PO-1041"]["notes"] if n["meeting_id"] == E] == ["Delivery slipped two weeks"]

# "neither" -> nothing written; unrelated chat while a question is open is not swallowed.
asyncio.run(main.apply_extraction(E, {"record_notes": [pump_note]}))
assert not main.resolve_confirmation(E, "Priya", "what time is lunch?")
c.post("/webhooks/recall?token=t", json=replay.payload(e["bot_id"], 0, "chat", "Priya", "neither")).raise_for_status()
time.sleep(0.2)
assert db.row("SELECT COUNT(*) n FROM pending_confirmations WHERE meeting_id=? AND resolved=0", E)["n"] == 0
assert len([n for n in db.rows("SELECT * FROM record_notes WHERE meeting_id=?", E)]) == 3  # PO-1043, 1046, 1041

# Progress on an existing task updates it instead of adding a new one.
tid = m["tasks"][0]["id"]
asyncio.run(main.apply_extraction(E, {"task_updates": [{"task_id": tid, "status": "done", "note": "quote sent"}],
                                      "tasks": [{"title": "Send vendor quote", "owner": "Rahul"}]}))
t = c.get(f"/api/meetings/{E}").json()["tasks"]
assert len(t) == 1 and t[0]["status"] == "done" and t[0]["last_update"] == "quote sent", t

# --- Post-meeting: MOM + recap email + reminders (LLM and SMTP stubbed) ---
sent = []
mailer._send_sync = lambda to, subject, html, text: sent.append((to, subject, html, text))
os.environ["SMTP_USER"] = "amber@example.com"


async def fake_mom(mid):
    return {"executive_summary": "Pump quote and PPE order discussed.", "decisions": ["Renew the chiller AMC"],
            "agenda_alignment": [{"item": "Pump order", "status": "covered", "notes": "quote by Friday"}],
            "open_questions": ["Replace or repair the compressor?"]}

brain.make_mom = fake_mom
with db.db() as conn:
    conn.execute("UPDATE tasks SET status='open' WHERE meeting_id=?", (E,))  # reopen the task marked done above
    conn.execute("INSERT INTO participants (meeting_id,name,joined_at,left_at) VALUES (?,?,?,?)",
                 (E, "Rahul <script>", "2026-10-17T05:00:00+00:00", "2026-10-17T05:30:00+00:00"))
asyncio.run(main.post_meeting(E))
m = c.get(f"/api/meetings/{E}").json()
assert m["status"] == "completed" and m["mom"]["decisions"] == ["Renew the chiller AMC"]
(to, subject, html, text), = sent
assert to == ["rahul@example.com", "priya@example.com"] and subject == "Recap: x", (to, subject)
for part in ("Pump quote and PPE order discussed.", "Renew the chiller AMC", "Send vendor quote", "Rahul",
             "PO-1046: Delivery slipped two weeks", "Replace or repair the compressor?", "05:00"):
    assert part in html and part in text, part
assert "<script>" not in html and "Rahul &lt;script&gt;" in html  # meeting data is escaped
asyncio.run(main.post_meeting(E))
assert len(sent) == 1  # once per meeting unless forced
c.post(f"/api/meetings/{E}/recap").raise_for_status()
assert len(sent) == 2
assert [o["status"] for o in c.get(f"/api/outbox?meeting_id={E}").json()] == ["sent", "sent"]

# LLM down -> the recap still goes out with the facts.
async def broken_mom(mid):
    raise RuntimeError("503")

brain.make_mom = broken_mom
c.post(f"/api/meetings/{E}/recap").raise_for_status()
assert "Summary unavailable" in sent[-1][2] and "Send vendor quote" in sent[-1][2]
brain.make_mom = fake_mom

# Reminders: one check-in per open task with an owner email, never twice; done tasks are left alone.
db.execute("UPDATE meetings SET ended_at=? WHERE id=?", db.now(), E)
main.DEMO_REMINDER_MIN = "0"
sent.clear()
asyncio.run(main.send_due_reminders())
(to, subject, html, text), = sent
assert to == ["rahul@example.com"] and subject == "Reminder: Send vendor quote (due 2026-10-23)", subject
assert "Hi Rahul" in text and "From the meeting: \"I'll send it by Friday\"" in text and "Latest update: quote sent" in text
asyncio.run(main.send_due_reminders())
assert len(sent) == 1
main.DEMO_REMINDER_MIN = ""
# Without the demo knob, a task due far ahead isn't reminded yet.
tid2 = db.execute("INSERT INTO tasks (meeting_id,title,owner,owner_email,due_at,status) VALUES (?,?,?,?,?,'open')",
                  E, "Later thing", "Priya", "priya@example.com", "2099-01-01")
asyncio.run(main.send_due_reminders())
assert len(sent) == 1
# Broken SMTP: logged as failed once, not retried every loop.
mailer._send_sync = lambda *a: (_ for _ in ()).throw(OSError("SMTP down"))
db.execute("UPDATE tasks SET due_at='2000-01-01' WHERE id=?", tid2)
asyncio.run(main.send_due_reminders())
assert db.row("SELECT reminded_at FROM tasks WHERE id=?", tid2)["reminded_at"].startswith("failed:")
assert c.get(f"/api/outbox?meeting_id={E}").json()[0]["status"] == "failed"

# Pre-meeting document: its text lands in Amber's context; unsupported files are refused.
import base64  # noqa: E402
doc = base64.b64encode(b"Vendor for PO-1042 seals is FlowServe India, contact Mr. Rao.").decode()
dm = c.post("/api/meetings/dispatch", json={"title": "doc", "url": "https://meet.google.com/z", "replay": True,
                                            "context": "Quarterly review", "document_name": "brief.txt",
                                            "document_b64": doc}).json()
ctx = db.row("SELECT context_text FROM meetings WHERE id=?", dm["id"])["context_text"]
assert ctx.startswith("Quarterly review") and "DOCUMENT (brief.txt):\nVendor for PO-1042" in ctx, ctx
assert c.post("/api/meetings/dispatch", json={"title": "d", "url": "https://meet.google.com/z", "replay": True,
                                              "document_name": "old.doc", "document_b64": doc}).status_code == 400
assert c.get("/api/outbox/999999").status_code == 404

# Every model down -> Amber says sorry instead of going silent.
async def broken_answer(mid, speaker, question):
    raise RuntimeError("503 UNAVAILABLE")

brain.answer = broken_answer
say(d["bot_id"], "Akash", "Amber, what's the status of the VFD drives?")
assert replies(d["id"])[0][-1] == brain.SORRY
brain.answer = fake_answer
print("ok")
