# Amber Live: demo video script (solo presenter)

A 3–5 minute recorded video covering the full lifecycle: context loaded before the call, Amber answering
questions by voice, the recap and follow-ups sent, and a record updated from the discussion.

Abhishek presents alone. The only participants in the Meet are **Abhishek and Amber**, so every line in the
call is Abhishek's. The follow-ups are a task he takes on himself, plus one for an absent colleague, which
shows that the right owner gets a reminder.

| Criterion | Weight | Where it's shown |
|---|---|---|
| Works end to end | 30% | The whole video, one take inside the call |
| Quality of participation | 25% | 0:50–3:00 |
| Recap, follow-ups & tagging | 15% | 3:00–4:15 |
| Engineering | 15% | Not in the video; covered by the README and write-up |
| Ownership & communication | 15% | The close (honest limits) |

---

## Three rules for presenting alone (read these first)

Amber hears everything you say, including what you say to the viewer. Turn-taking was built for a room
full of people, so with one voice you need a little discipline:

1. **Close every exchange with "Thanks Amber, that's all."** After she answers, she stays in the
   conversation for up to 75 seconds and judges your next lines as possible follow-ups. If you start
   explaining to the viewer while that's open, she may answer your explanation. "That's all" closes it
   straight away. She may reply with a short "you're welcome", which is fine.
2. **While she's in the call, say "she", never "Amber", when you narrate.** Her name anywhere in a
   sentence can open a new question. "Notice Amber stayed quiet" will get you an answer. "Notice she stayed
   quiet" won't.
3. **Pause about a second after "Amber,"** and wait for her to finish before you speak again (except in the
   interruption test, where talking over her is the point).

You can also mute your Meet mic while narrating, which is the safest option for the recorded video.

---

## Before you start (pre-flight, about 10 min)

1. **Records.** The Records page should list the 10 mock records with no notes. If it's empty, load them
   (safe to run while the backend is up; it never overwrites existing records):
   ```bash
   cd backend && uv run python seed.py
   ```
   Old notes from earlier runs are not removed by this. Delete those meetings or notes from the dashboard
   first.
2. **Backend, tunnel, dashboard** running, in that order (README "Running it"). Check that `PUBLIC_URL`
   in `.env` matches the current tunnel URL. It changes every time cloudflared restarts.
3. **Voice mode is `mp3`** (the default). Don't use `stream`: participants can't hear it in Meet yet.
4. **Warm up the LLM** with one throwaway question a few minutes before. The first call of the day is the
   slowest.
5. **Your Meet display name must be "Abhishek"**, matching the attendee list, so tasks you take on are
   matched to your email.
6. **Attendees** in the dispatch form:
   ```
   Abhishek, <your email>
   Priya, <your-gmail>+priya@gmail.com
   ```
   Priya is invited but absent, just like a real colleague who missed the sync. With Gmail's `+` addressing,
   her recap and reminder land in **your** inbox, so you can show that the right owner was emailed.
   If you don't use Gmail, leave her out and skip the Priya task.
7. **The document.** Upload [`chiller-vibration-note.txt`](chiller-vibration-note.txt) (repo root) in the dispatch form. Its facts
   exist only in the document, not in the records, so one question proves she read it:
   ```
   Chiller #2 vibration inspection, 14 Oct
   Inspected by: Ankit
   Finding: vibration at the compressor bearing is 7.8 mm/s, above the 4.5 mm/s alarm limit.
   Likely cause: worn compressor bearing.
   Recommendation: replace the bearing within two weeks; bring it under the AMC renewal (PO-1043) if possible.
   ```
8. **Agenda text:**
   ```
   Weekly plant ops sync
   1. Grundfos pump order (PO-1041): vendor quote
   2. Chiller #2 vibration and the service contract renewal
   3. PPE kits
   ```
9. **Screen layout.** Meet on the left, dashboard on the right, Gmail in a tab. Turn on Meet captions.
   Zoom the dashboard to 110–125% so the activity feed is readable.
10. **Plan B.** If Recall misbehaves, `uv run python replay.py --email you@x.com` plays a scripted
    meeting through the exact same webhook handler. Say it's a replay; don't pass it off as live.

### The records Amber knows (mock seed data, unchanged)

These are the answers to expect. The owners (Rahul, Priya, Ankit, Sneha) are colleagues who aren't in
this call. That's realistic, because a records owner is rarely in every sync. The data is left as it is
because the tests and golden replays are built on it.

| ID | Item | Status | Owner |
|---|---|---|---|
| PO-1041 | Centrifugal pump Grundfos CR-32 (main pump) | Awaiting vendor quote | Rahul |
| PO-1042 | Pump mechanical seal kit | Ordered, ETA 24 Oct | Priya |
| PO-1043 | Chiller compressor service contract (AMC) | Under review, renewal 1 Nov | Ankit |
| PO-1044 | VFD drives 15kW | Delivered 10 Oct, installation pending | Rahul |
| PO-1045 | PPE kits (50) | Approved, not ordered | Sneha |
| PO-1046 | Booster pump Grundfos CM-5 | Ordered, ETA 30 Oct | Priya |
| EQ-201 | Chiller #2 | Running, high vibration flagged | Ankit |
| EQ-202 | Boiler B1 | Operational, inspection 15 Dec | Priya |
| EQ-203 | Cooling tower CT-1 | Fan motor replaced 3 Oct | Ankit |
| EQ-204 | Air compressor AC-2 | Down, waiting on filter kit | Sneha |

Two Grundfos pumps (PO-1041 and PO-1046) are there on purpose: "the Grundfos shipment" is ambiguous, so
Amber has to ask before writing.

---

# The video (target 4:30)

Narration is plain text. **On-screen actions are in bold.** Lines said *in the meeting* are quoted.
Narration during the call either goes over a muted mic or follows the three rules above.

### 0:00–0:20 · The hook

**Dashboard home.**

> Hi, I'm Abhishek, and this is Amber. She's an AI teammate you can send into a Google Meet. She reads up
> before the call, answers when you talk to her, keeps quiet when you don't, and afterwards she writes the
> minutes, chases the action items and updates the records. It's just me and her today, one real meeting
> from start to finish, with no cuts in the call.

### 0:20–0:50 · Stage 1: context in

**Open "Schedule a meet". Pick the "Plant ops" meet type. Paste the Meet link and the agenda. Upload
`chiller-vibration-note.txt`. Add the two attendees.**

> Before the call I give her what a good colleague would read first: the agenda, a document (here, an
> inspection note on Chiller 2) and who's invited. She also has the company's records, which are a
> procurement log and an equipment list, plus the minutes of the last few meetings of this type and any
> open tasks. That's everything she knows. If it isn't in there, she won't make it up.

**Click Send Amber. Switch to Meet, admit "Amber".**

> And she's joined, as a normal participant. I have to let her in like anyone else.

### 0:50–3:00 · Stage 2: participation

**Abhishek:** "Amber, what's the status of the pump order?"
**Amber:** *PO-1041, awaiting the vendor quote; Rahul owns it.*

**Abhishek:** "And when are the pump seals arriving?"
**Amber:** *24 October, PO-1042.*

**Abhishek:** "What did the inspection report recommend for the chiller?"
**Amber:** *Replace the compressor bearing within two weeks, possibly under the AMC renewal.*

**Abhishek:** "And what was last quarter's marketing spend?"
**Amber:** *"I don't have that information in my current records."*

**Abhishek:** "Thanks Amber, that's all."

> *(mic muted, or voiceover)* Three things there. I only said her name once, and she followed the
> conversation like a person would. The chiller answer came from the document I uploaded, not the
> records. And when she didn't know, she said so instead of inventing a number. In a meeting, a confident
> wrong answer is worse than no answer.

**Now speak as if running the meeting for the team. Don't say her name. She should stay silent.**

**Abhishek:** "Okay, let's look at the chiller first."
**Abhishek:** "Chiller two vibrated badly again this morning, so that bearing really can't wait."
**Abhishek:** "Also, the Grundfos shipment is delayed to next month."
**Abhishek:** "On the pump order, I'll chase the vendor for the quote myself and send it by Friday."
**Abhishek:** "And Priya needs to place the PPE order by Wednesday."

> She's quiet, because I wasn't talking to her. But she's listening. Look at the dashboard.

**Point at the activity feed: the "no name, nothing open" ignore lines, then the tasks and the chiller note
appearing.**

> Every few lines she pulls out the action items. My task is there, the vendor quote due Friday, in my own
> words. Priya's is there too, due Wednesday, even though she isn't on the call. And "chiller two" can only
> mean one thing, so she's put a note on Chiller 2 straight away.
>
> "The Grundfos shipment" is different. We have two Grundfos orders, the main pump and the booster pump.
> She won't guess on a system of record, so she asks.

**Show Meet chat: "Did you mean 1) PO-1041 … or 2) PO-1046 …?" Type `2`.**
**Chat:** *"Got it, noted on PO-1046."*

**Abhishek:** "Amber, please leave the meeting."
**Amber:** *(says goodbye and leaves)*

### 3:00–4:15 · Stages 3, 4, 5: recap, follow-ups, records

**Dashboard → open the meeting → Summary tab.**

> As soon as she leaves, she writes the minutes: a summary, decisions, action items, open questions, and
> attendance.

**Tasks tab.**

> The follow-ups: mine, the vendor quote by Friday, and Priya's PPE order by Wednesday. Each owner gets a
> reminder 24 hours before it's due. If I say in next week's sync "I've sent the quote", she moves my task
> along instead of creating a new one.

**Outbox tab, then the Gmail tab: open the recap email (and the copy addressed to Priya).**

> The recap has gone out to everyone on the invite, including Priya, who missed the call. This is the real
> email in my inbox.

**Records page → EQ-201 Chiller #2, then PO-1046.**

> And stage five, the record. Chiller 2 has a note with the date, the meeting and what I said. PO-1046 got
> the shipment delay, but only once I'd confirmed which pump I meant.

### 4:15–4:30 · Close

> That's the full loop: context in, she takes part, the recap goes out, the follow-ups are set and the
> records are updated, all from one ordinary meeting. It's a proof of concept. The records are mock data,
> there's no login, and her answers usually start a second or two after the question, sometimes longer on
> a slow model. The write-up lists everything that doesn't work yet. Thanks for watching.

### Recording tips

- Record the call in one take. Cuts are fine between stages, for example while the minutes are generating,
  but not inside the meeting.
- If an answer is slow, leave the silence in. You mention latency at the end, and a real pause is more
  convincing than a perfect edit.
- If she mishears her name, just say it again. A natural retry looks better than a reshoot.

---

## If something goes wrong while recording

| Problem | What to say and do |
|---|---|
| She doesn't answer | Repeat with a pause: "Amber… what's…". Then check the activity feed and say what it shows. It's a good moment to show the logging. |
| She answers your narration | You forgot "that's all". Say "Thanks Amber, that's all", then: "That's the follow-up window doing its job a bit too well." |
| Slow answer (5 s+) | "That's a free-tier model spike, I'll come back to latency at the end." Keep going. |
| No task for you | Check that your Meet name matches the attendee name. The task is in the Tasks tab even when no email was matched. |
| Bot can't join | Check that `PUBLIC_URL` matches the tunnel. If it's still stuck, run `replay.py` and say it's a replay through the same handler. |
| No recap email | Show the Outbox tab (it logs every send and its status), then check the SMTP app password. |
