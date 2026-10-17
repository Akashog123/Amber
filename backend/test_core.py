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


screens_seen = []


async def fake_answer(mid, speaker, question, screen_png=None):
    asked.append(question)
    screens_seen.append(screen_png)
    await asyncio.sleep(0.15)  # answer is "in flight" for a moment, like the real API
    return brain.FALLBACK if "marketing" in question else f"answer to {speaker}"

real_answer, real_complete = brain.answer, brain.complete
brain.answer = fake_answer


async def no_extract(mid, after_id):
    return {}, after_id

brain.extract = no_extract  # background passes would need a real LLM; apply_extraction is tested directly
main.DEBOUNCE = 0.1
main.BARE_WAIT = 0.5

c = TestClient(main.app)
c.__enter__()  # keep the app's event loop alive between requests so reply tasks run


def say(bot, who, text):  # real call-relative time, so repeated lines aren't mistaken for re-delivered webhooks
    c.post("/webhooks/recall?token=t", json=replay.payload(bot, time.monotonic(), "say", who, text)).raise_for_status()


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
async def broken_answer(mid, speaker, question, screen_png=None):
    raise RuntimeError("503 UNAVAILABLE")

brain.answer = broken_answer
say(d["bot_id"], "Akash", "Amber, what's the status of the VFD drives?")
assert replies(d["id"])[0][-1] == brain.SORRY
assert not main.conv(d["id"]).pending  # nothing left behind to leak into the next question
brain.answer = fake_answer

# --- Edge cases found in the final audit ---
D = d["id"]
# URL without a scheme is accepted; bad attendee emails are refused before anything is created.
ok = c.post("/api/meetings/dispatch", json={"title": " ", "url": " meet.google.com/abc-defg-hij ", "replay": True})
assert ok.status_code == 200 and db.row("SELECT url, title FROM meetings WHERE id=?", ok.json()["id"]) == \
    {"url": "https://meet.google.com/abc-defg-hij", "title": "Meeting"}
assert c.post("/api/meetings/dispatch", json={"title": "x", "url": "https://meet.google.com/q", "replay": True,
              "attendees": [{"name": "R", "email": "r@x.com\nBcc: evil@x.com"}]}).status_code == 400
# Operator API isn't reachable through the public tunnel; Recall's webhook is.
assert c.get("/api/meetings", headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 403
assert c.post("/webhooks/recall?token=t", json={}, headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 200
# Owner email: full name wins; an ambiguous first name gets no email rather than the wrong person's.
with db.db() as conn:
    conn.executemany("INSERT INTO attendees VALUES (?,?,?)", [(D, "Rahul Mehta", "rm@x.com"), (D, "Rahul Shah", "rs@x.com")])
assert main._attendee_email(D, "Rahul Shah") == "rs@x.com" and main._attendee_email(D, "Rahul") == ""
# Sloppy model output doesn't crash the pass or store junk.
asyncio.run(main.apply_extraction(D, {"tasks": [{"title": "Call vendor", "owner": "null", "due": "next Friday"}, "junk"],
                                      "task_updates": [{"task_id": 99999, "status": "finished"}],
                                      "record_notes": [{"record_id": "eq-201", "note": "Belt replaced",
                                                        "confidence": "high", "candidates": "EQ-201"}]}))
assert [(t["owner"], t["due_at"]) for t in db.rows("SELECT * FROM tasks WHERE meeting_id=?", D)] == [(None, None)]
asyncio.run(main.apply_extraction(D, None))
# Record ids are normalised: a confident lowercase id still writes.
asyncio.run(main.apply_extraction(D, {"record_notes": [{"record_id": "eq-202", "note": "Filter swapped",
                                                        "confidence": 0.9, "candidates": ["eq-202"]}]}))
assert db.row("SELECT record_id FROM record_notes WHERE meeting_id=?", D)["record_id"] == "EQ-202"

# Raise-hand: Amber's record question goes to chat with a hand up; "Amber, go ahead" makes her ask out loud.
asyncio.run(main.apply_extraction(D, {"record_notes": [pump_note]}))
assert c.get(f"/api/meetings/{D}").json()["hand_raised"].startswith("✋ Quick check")
say(d["bot_id"], "Akash", "Amber, go ahead")
time.sleep(0.3)
assert "1, PO-1041, the Centrifugal pump" in replies(D)[0][-1]
c.post("/webhooks/recall?token=t", json=replay.payload(d["bot_id"], 0, "chat", "Akash", "neither")).raise_for_status()
time.sleep(0.2)
assert c.get(f"/api/meetings/{D}").json()["hand_raised"] is None

# Voice-commanded recording: pause (Amber explains how to resume, since she can't hear while paused) and resume.
say(d["bot_id"], "Priya", "Amber, please stop the recording")
time.sleep(0.3)
assert db.row("SELECT recording_paused FROM meetings WHERE id=?", D)["recording_paused"] == 1
assert "resume recording" in replies(D)[1][-1]["text"]
c.post("/webhooks/recall?token=t", json=replay.payload(d["bot_id"], 0, "chat", "Priya", "Amber, resume recording")).raise_for_status()
time.sleep(0.3)
assert db.row("SELECT recording_paused FROM meetings WHERE id=?", D)["recording_paused"] == 0
assert replies(D)[1][-1]["text"] == "Recording resumed."
assert c.post(f"/api/meetings/{D}/recording/pause").json() == {"paused": True}
assert c.post(f"/api/meetings/{D}/recording/explode").status_code == 404
c.post(f"/api/meetings/{D}/recording/resume")

# Screen vision: the latest screen-share frame reaches the answer only for screen questions.
png = base64.b64encode(b"\x89PNG fake").decode()
with c.websocket_connect("/ws/recall?token=t") as ws:
    ws.send_text('{"event": "video_separate_png.data", "data": {"bot": {"id": "%s"}, "data": {"type": "webcam", '
                 '"buffer": "x"}}}' % d["bot_id"])
    ws.send_text('{"event": "video_separate_png.data", "data": {"bot": {"id": "%s"}, "data": {"type": "screenshare", '
                 '"buffer": "%s", "participant": {"name": "Priya"}}}}' % (d["bot_id"], png))
time.sleep(0.2)
assert main.screens[D][0] == png
screens_seen.clear()
say(d["bot_id"], "Akash", "Amber, what does this slide say about the budget?")
say(d["bot_id"], "Rahul", "Amber, who owns the boiler?")
time.sleep(0.8)
assert sorted(screens_seen, key=bool) == [None, b"\x89PNG fake"], screens_seen

# Barge-in: backchannel while Amber talks doesn't cut her off; a real interruption does.
def spoken(text, secs):  # words spread over `secs` seconds, like a partial transcript
    ws = text.split()
    step = secs / len(ws)
    return [{"text": w, "start_timestamp": {"relative": i * step}, "end_timestamp": {"relative": (i + 1) * step}}
            for i, w in enumerate(ws)]

# Durations measured on the live call: "Yeah." 0.32s, "Sorry." 0.32s, real interruptions pass 0.8s.
assert not main.interrupts(spoken("Yeah.", 0.32)) and not main.interrupts(spoken("Sorry.", 0.32))
assert not main.interrupts(spoken("haan haan", 0.5))  # any language: it's the length that counts
assert main.interrupts(spoken("What about the status", 1.28)) and main.interrupts(spoken("Wait", 0.2))
assert main.interrupts(spoken("Amber,", 0.32)) and not main.interrupts([])
# Her name again while she's answering = a new question, not glued onto the old one (seen live).
async def slow_answer(mid, speaker, question, screen_png=None):
    asked.append(question)
    await asyncio.sleep(0.5)
    return f"answer to {speaker}"

brain.answer = slow_answer
asked.clear()
say(d["bot_id"], "Akash", "Hey Amber, what's the status of Chiller two?")
time.sleep(0.25)  # debounce fired, answer in flight
say(d["bot_id"], "Akash", "Amber,")
time.sleep(0.2)
say(d["bot_id"], "Akash", "have we ordered the PPE kits")
time.sleep(1.8)
assert asked == ["Hey Amber, what's the status of Chiller two?", "Amber, have we ordered the PPE kits"], asked
# While her answer is on its way, the asker's next question needs no "Amber" and is queued, not lost;
# a statement in between is still ignored.
asked.clear()
say(d["bot_id"], "Akash", "Amber, what's the status of the boiler?")
time.sleep(0.25)
say(d["bot_id"], "Akash", "Okay, next item is the PPE order.")
say(d["bot_id"], "Akash", "and when is the next inspection?")
time.sleep(1.8)
assert asked == ["Amber, what's the status of the boiler?", "and when is the next inspection?"], asked
# ...but the tail of the same question, cut off by the transcriber, is merged (seen live: "...service" + "contract?").
asked.clear()
say(d["bot_id"], "Akash", "What about Amber? Who owns the chiller service")
time.sleep(0.25)
say(d["bot_id"], "Akash", "contract?")
time.sleep(1.2)
assert asked[-1] == "What about Amber? Who owns the chiller service contract?" and len(set(asked)) == 2, asked
brain.answer = fake_answer

# Recording requests the phrase list misses are caught by the answer model's action token.
brain.answer = lambda *a, **k: asyncio.sleep(0, brain.PAUSE_TOKEN)
say(d["bot_id"], "Priya", "Amber, can you hold off on capturing this bit?")
time.sleep(0.5)
assert db.row("SELECT recording_paused FROM meetings WHERE id=?", D)["recording_paused"] == 1
assert brain.PAUSE_TOKEN not in " ".join(replies(D)[0])  # the token itself is never spoken
c.post(f"/api/meetings/{D}/recording/resume")
brain.answer = fake_answer

# Reworded tasks aren't logged twice; different tasks for the same person are kept.
asyncio.run(main.apply_extraction(D, {"tasks": [{"title": "Send vendor quote for the pump", "owner": "Rahul"}]}))
asyncio.run(main.apply_extraction(D, {"tasks": [{"title": "send the vendor quote for pumps by Friday", "owner": "Rahul Mehta"},
                                                {"title": "Send vendor quote for the chiller", "owner": "Rahul"}]}))
assert [t["title"] for t in db.rows("SELECT title FROM tasks WHERE meeting_id=? AND owner LIKE 'Rahul%'", D)] == \
    ["Send vendor quote for the pump", "Send vendor quote for the chiller"]
# Extraction progress survives a restart (stored with the meeting).
seen_after = []


async def advancing_extract(mid, after_id):
    seen_after.append(after_id)
    return {}, after_id + 7

brain.extract = advancing_extract
asyncio.run(main.run_extract(D))
asyncio.run(main.run_extract(D))  # same process, but it reads the stored offset, as a restarted one would
brain.extract = no_extract
assert seen_after[1] == seen_after[0] + 7 and \
    db.row("SELECT extracted_upto FROM meetings WHERE id=?", D)["extracted_upto"] == seen_after[0] + 14
# A re-delivered webhook doesn't store or answer the line twice.
asked.clear()
dup = replay.payload(d["bot_id"], 12345.6, "say", "Akash", "Amber, who owns the boiler?")
c.post("/webhooks/recall?token=t", json=dup).raise_for_status()
c.post("/webhooks/recall?token=t", json=dup).raise_for_status()
time.sleep(0.5)
assert asked == ["Amber, who owns the boiler?"], asked

# Misheard record names are matched by sound in code and handed to the model as a hint, so it never guesses.
assert brain.sounds_like_records("When are the pump sales arriving?") == [("PO-1042", "pump seals", "pump sales")]
assert brain.sounds_like_records("is the cooling tour fixed") == [("EQ-203", "cooling tower", "cooling tour")]
assert brain.sounds_like_records("what about the pump seals") == []  # heard right: no hint
assert brain.sounds_like_records("how is the boiler doing") == []
prompts = []
brain.complete = lambda system, prompt, **k: (prompts.append(prompt), asyncio.sleep(0, "ok"))[1]
asyncio.run(real_answer(D, "Akash", "When are the pump sales arriving?"))
assert prompts[-1].endswith('HEARD-AS: "pump sales" was probably "pump seals" (PO-1042).'), prompts[-1][-120:]
# Amber's own earlier lines are labelled in her context (unlabelled, the model imitated an earlier bad answer).
db.execute("INSERT INTO utterances (meeting_id,speaker,text,ts,addressed) VALUES (?,?,?,NULL,0)", D, "Amber", "Earlier.")
assert "Amber (your earlier reply): Earlier." in brain.build_context(D)
brain.complete = real_complete

# Streaming voice (Output Media page): filler + answer go down the page's socket as PCM; talking over her stops it.
import voice  # noqa: E402


async def fake_stream(text, model=None):
    for _ in range(3):
        yield b"\0" * 64000  # 3 x 2 s of audio


voice.tts_stream, voice.filler_pcm = fake_stream, lambda text: asyncio.sleep(0, b"\0" * 8000)
os.environ["ELEVENLABS_API_KEY"] = "stub"
with c.websocket_connect(f"/ws/media?m={D}&token=t") as page:
    assert page.receive_json() == {"type": "hand", "on": False}
    say(d["bot_id"], "Akash", "Amber, who owns the boiler?")
    frames = [len(page.receive_bytes()) for _ in range(4)]
    assert frames == [8000, 64000, 64000, 64000], frames  # filler, then the streamed answer
    words = [{"text": w, "start_timestamp": {"relative": i * 0.4}, "end_timestamp": {"relative": i * 0.4 + 0.35}}
             for i, w in enumerate("hold on one sec".split())]
    c.post("/webhooks/recall?token=t", json={"event": "transcript.partial_data", "data": {
        "data": {"words": words, "participant": {"name": "Priya"}}, "bot": {"id": d["bot_id"]}}}).raise_for_status()
    assert page.receive_json() == {"type": "stop"}
    assert main.conv(D).followups["Akash"][0] > time.monotonic()  # a streamed answer still opens the follow-up window
assert c.get("/media/amber").status_code == 200 and "amberStats" in c.get("/media/amber").text
assert c.get("/media/amber", headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 200  # Recall loads it via the tunnel
os.environ["ELEVENLABS_API_KEY"] = ""
time.sleep(0.3)

# Cancel + new question in one breath (seen live): the old one is dropped, the new one answered.
asked.clear()
say(d["bot_id"], "Priya", "Amber, what's the boiler status")
say(d["bot_id"], "Priya", "Sorry, forget about that. Amber, have we ordered the PPE kits?")
time.sleep(0.5)
assert asked == ["Amber, have we ordered the PPE kits"], asked
asked.clear()
say(d["bot_id"], "Priya", "Amber, what's the boiler status")
say(d["bot_id"], "Priya", "oh forget it")
time.sleep(0.5)
assert asked == [], asked

# Follow-up window: a question needs no "Amber", but a line naming someone else is for them.
asked.clear()
main.conv(D).followups["Akash"] = (time.monotonic() + 10, False)
say(d["bot_id"], "Akash", "Rahul, please send the quote by Friday.")
time.sleep(0.4)
assert asked == [], asked
say(d["bot_id"], "Akash", "and when does it arrive?")
time.sleep(0.4)
assert asked == ["and when does it arrive?"], asked

# Record tagging can't be talked into a guess: words that fit two records get a question even at confidence 1.0.
recs_all = {r["id"]: r for r in db.rows("SELECT id, name, aliases FROM records")}
assert main.which_records("the Grundfos shipment is delayed", recs_all) == ["PO-1041", "PO-1046"]
assert main.which_records("the CR-32 pump arrived", recs_all) == ["PO-1041"]
assert main.which_records("pump seals came in", recs_all) == ["PO-1042"]
assert main.which_records("chiller service contract renewed", recs_all) == ["PO-1043"]
assert main.which_records("it slipped again", recs_all) == []
assert main.which_records("Chiller two flagged high vibration again on Tuesday", recs_all) == ["EQ-201"]
assert main.which_records("the booster pump is stuck at customs", recs_all) == ["PO-1046"]
assert len(main.which_records("the pump delivery slipped by two weeks", recs_all)) == 3  # three pump records
assert main.which_records("PO-1046 shipped", recs_all) == ["PO-1046"]
before = db.row("SELECT COUNT(*) n FROM record_notes")["n"]
asyncio.run(main.apply_extraction(D, {"record_notes": [{"record_id": "PO-1041", "note": "Delayed 3 weeks",
                                                        "confidence": 1.0, "candidates": ["PO-1041"],
                                                        "quote": "The Grundfos pump shipment got pushed out"}]}))
assert db.row("SELECT COUNT(*) n FROM record_notes")["n"] == before  # not written
q_open = main.open_confirmation(D)["question"]
assert "1) PO-1041" in q_open and "2) PO-1046" in q_open, q_open
c.post("/webhooks/recall?token=t", json=replay.payload(d["bot_id"], 0, "chat", "Akash", "neither")).raise_for_status()
time.sleep(0.2)

# Two webhooks landing back to back start one extraction pass, not two; the same line is asked about once.
calls = []


async def counting_extract(mid, after_id):
    calls.append(mid)
    await asyncio.sleep(0.05)
    return {}, after_id


async def burst():
    main.since_extract[D] = main.EXTRACT_EVERY - 1
    main.maybe_extract(D)
    main.maybe_extract(D)
    await asyncio.sleep(0.2)

brain.extract = counting_extract
asyncio.run(burst())
brain.extract = no_extract
assert calls == [D], calls
n_q = db.row("SELECT COUNT(*) n FROM pending_confirmations WHERE meeting_id=?", D)["n"]
asyncio.run(main.apply_extraction(D, {"record_notes": [pump_note]}))
asyncio.run(main.apply_extraction(D, {"record_notes": [pump_note]}))
assert db.row("SELECT COUNT(*) n FROM pending_confirmations WHERE meeting_id=?", D)["n"] == n_q + 1
c.post("/webhooks/recall?token=t", json=replay.payload(d["bot_id"], 0, "chat", "Akash", "neither")).raise_for_status()
time.sleep(0.2)

# No quote from the model: the note text is checked instead, so a confident guess still can't auto-write.
before = db.row("SELECT COUNT(*) n FROM record_notes")["n"]
asyncio.run(main.apply_extraction(D, {"record_notes": [{"record_id": "PO-1041", "confidence": 0.95,
                                                        "candidates": ["PO-1041"], "note": "Grundfos pump delayed"}]}))
assert db.row("SELECT COUNT(*) n FROM record_notes")["n"] == before and main.open_confirmation(D)
c.post("/webhooks/recall?token=t", json=replay.payload(d["bot_id"], 0, "chat", "Akash", "neither")).raise_for_status()
time.sleep(0.2)

# Hindi: questions get Hindi fillers, follow-ups in Hindi count, the fixed lines are said in Hindi.
brain.answer = lambda *a, **k: asyncio.sleep(0, brain.FALLBACK)
say(d["bot_id"], "Priya", "Amber, marketing ka budget kitna hai?")
time.sleep(0.4)
assert replies(D)[0][-1] == brain.FALLBACK_HI
brain.answer = fake_answer
assert main.filler_kind("Amber, PO-1041 ka status kya hai?") == "lookup_hi"
assert main.is_addressed("अंबर, पंप का ऑर्डर कब आएगा?")

# Long-term series memory: the next meeting of a series sees what the last one decided.
s1 = c.post("/api/meetings/dispatch", json={"title": "Sync 1", "url": "https://meet.google.com/s", "replay": True,
                                            "series_id": "ws:proc"}).json()["id"]
db.execute("UPDATE meetings SET mom_json=? WHERE id=?",
           '{"executive_summary": "First sync.", "decisions": ["Switch PPE vendor"], "open_questions": ["Compressor?"]}', s1)
s2 = c.post("/api/meetings/dispatch", json={"title": "Sync 2", "url": "https://meet.google.com/s", "replay": True,
                                            "series_id": "ws:proc"}).json()["id"]
ctx = brain.build_context(s2)
assert "Sync 1" in ctx and "decided: Switch PPE vendor" in ctx and "left open: Compressor?" in ctx
assert "Switch PPE vendor" not in brain.build_context(D)  # other series don't leak in

# Bot kicked / never admitted (fatal) still closes the meeting out, without emailing an empty recap.
sent.clear()
mailer._send_sync = lambda to, subject, html, text: sent.append(to)
f = c.post("/api/meetings/dispatch", json={"title": "kicked", "url": "https://meet.google.com/k", "replay": True,
                                           "attendees": [{"name": "A", "email": "a@x.com"}]}).json()
c.post("/webhooks/recall?token=t", json=replay.payload(f["bot_id"], 0, "bot", "", "fatal")).raise_for_status()
time.sleep(0.5)
fm = c.get(f"/api/meetings/{f['id']}").json()
assert fm["status"] == "completed" and "No conversation" in fm["mom"]["executive_summary"] and not sent, fm["status"]
# Stop is idempotent after the meeting is over; a scheduled meeting is cancelled instead of recapped.
assert c.post(f"/api/meetings/{f['id']}/stop").json() == {"ok": True}
assert c.get(f"/api/meetings/{f['id']}").json()["status"] == "completed"
db.execute("UPDATE meetings SET status='scheduled' WHERE id=?", s2)
c.post(f"/api/meetings/{s2}/stop")
assert c.get(f"/api/meetings/{s2}").json()["status"] == "cancelled"
# Scheduling: a time well ahead is passed to Recall (UTC); sooner just joins now.
from datetime import datetime, timedelta, timezone  # noqa: E402
later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
assert main._join_at(later).startswith(later[:16]) and main._join_at(datetime.now().isoformat()) is None
assert c.post("/api/meetings/dispatch", json={"title": "x", "url": "https://meet.google.com/q", "replay": True,
                                              "join_at": "tomorrow"}).status_code == 400
print("ok")
