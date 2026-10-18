# Amber Live

Amber is an AI participant an operator sends into a Google Meet (Zoom and Teams links go through the same
Recall.ai API). Before the call she loads the agenda, a document and the company's records; in the call she
answers out loud or in chat when someone talks to her; afterwards she writes the minutes, emails a recap,
reminds task owners and files what was said onto the right records.

This is a POC: one operator, mock procurement and equipment records (`backend/seed.py`), no accounts.
The target production design (auth, durable queues, platform adapters) is in
[docs/production-design.md](docs/production-design.md) and is **not** built.

## The five stages

| Stage | What happens | Where |
|---|---|---|
| Context in | Dispatch form: meet type, agenda, one PDF/TXT, attendees as `Name, email`. Amber's context = agenda + document text + records + the minutes of the last 3 meetings of the same meet type + open tasks. | `main.py` `dispatch`, `brain.build_context`, `documents.py` |
| Participation | Recall bot joins, Deepgram nova-3 transcribes. Every final line goes through `turns.route()`; when it's for her she answers from her context only, or says "I don't have that information in my current records." Chat works the same way. | `turns.py`, `brain.answer`, `voice.py`, `recall.py` |
| Recap | When the bot leaves: minutes (summary, decisions, action items, open questions, attendance) and an HTML recap email to everyone, including joiners who typed their email in chat. | `brain.make_mom`, `mailer.recap` |
| Follow-ups | Every 4 human lines a pass extracts tasks (owner, due date, the owner's own words) and progress on existing ones. Owners get a reminder 24 h before the due date. | `brain.extract`, `main.apply_extraction`, reminder loop |
| Record updated | The same pass tags discussion to records. A note is written only when the speaker's words point at one record; if they fit several, Amber raises her hand and asks which one. | `main.which_records`, `ask_which_record`, `raise_hand` |

Also built: off-the-record mode, screen-share questions (`AMBER_SCREEN_VISION=1`), Hindi/Hinglish, scheduled
joins, recording playback, "Amber, leave the meeting".

## Architecture

```
React dashboard ──REST + WS───► FastAPI (backend/main.py) ── SQLite (db.py, stdlib sqlite3)
                                   │
Recall.ai bot in the meeting ──webhooks / websocket──► /webhooks/recall, /ws/recall
   ▲                               │
   └── output_audio, chat ◄────────┤ turns.py   who is Amber talking with; pure, no I/O
       or /media/amber page        │ brain.py   LLM calls: answer, "is this for Amber?", extract, minutes
       (streaming voice)           │ voice.py   ElevenLabs TTS
                                   │ mailer.py  Gmail SMTP + outbox table shown in the dashboard
replay.py, test_golden.py ─────────┘ post the same webhook payloads locally
```

- **Turn-taking** is one state machine per meeting (`turns.py`): ignore, start, append, merge, queue, or
  `classify`. Only unclear lines inside an open conversation go to the model, so it costs about two small calls
  per meeting. Every decision and its reason goes to the dashboard's activity feed.
- **LLM**: any OpenAI-compatible endpoint first, then Gemini, falling back per call on errors or timeouts
  (`brain.providers`).
- **Voice**: `mp3` (default) sends clips through Recall `output_audio`. `stream` makes her camera tile a web page
  that plays speech as ElevenLabs streams it and shows the raised hand.

## Running it

```bash
# 1. Backend (Python 3.13, uv). Every variable is explained in .env.example
cd backend && cp .env.example .env && uv run uvicorn main:app --port 8000

# 2. Public tunnel for Recall (put the https URL in PUBLIC_URL, restart the backend)
cloudflared tunnel --url http://127.0.0.1:8000

# 3. Dashboard (proxies /api to :8000)
pnpm install && pnpm dev      # http://localhost:5173
```

Create a workspace and meet type, paste the Meet link, add attendees, **Send Amber**, then admit "Amber" in
Meet. [LIVE_TESTS.md](LIVE_TESTS.md) lists the exact lines to say for every feature.

No Recall key? `uv run python replay.py` plays a scripted meeting through the same webhook handler
(`--email you@x.com` sends the recap and reminder to you).

## Tests

- `uv run python test_core.py`: turn-taking, grounding guard, extraction and record routing, all APIs stubbed.
  Prints `ok`.
- `uv run python test_golden.py`: replays recorded live calls (`backend/golden/`) at their real timing and checks
  which lines Amber answered. Add a live call with `--add logs/recall-<bot>.jsonl <name>`, then edit
  `<name>.expect.json`.
- `uv run python eval_scenarios.py`: model-written meetings with labelled requests, run through the real routing
  and the real model; reports missed requests and false triggers (`--file evals/live.json` for hand-labelled live calls).

## Trade-offs

| Choice | Why | Cost |
|---|---|---|
| Recall.ai instead of our own browser bot | Joining, transcription, chat and audio out on three platforms with one API. | Paid per hour; a host must admit the bot; Workspace meetings may block guests. |
| A conversation starts with her name, then continues without it until "that's all", 3 lines for other people, or 75 s idle | People drop "Amber" in follow-ups; the earlier fixed 10 s window cut real conversations short. | She can answer a line that wasn't meant for her. Unclear lines go to the model, and `test_golden.py` guards known cases. |
| Notes are written only when the speaker's own words point at one record | Several records share words (two pump orders); model confidence alone isn't enough to write. | She asks more often (raised hand, then chat). |
| Off the record is handled by Amber, not by pausing Recall | Pausing Recall also stopped the live transcript, so she went deaf. | Recall's raw recording still contains that stretch. |
| SQLite, in-process event socket, one uvicorn worker | Nothing to run but the app. | No horizontal scaling. |
| Fillers only when the answer isn't ready after 1.2 s | A filler before a fast answer only adds delay. | A slow reply still has a short silence first. |

## Limitations

- **Latency**: usually 1–2 s from the end of a question to her first word. LLM spikes of 4–7 s happen on free
  tiers. In `mp3` mode, talking over her stops her in about 0.5–1 s, not instantly.
- **Recognition**: ASR sometimes mishears "Amber". Sound-alikes count only near the start of a request.
- **Records** are mock seed data in SQLite, not a real ERP/CMMS.
- **No auth**: the operator API refuses tunnelled requests; only `/webhooks/` (token in the URL), `/ws/` and
  `/media/` are public.
- **Dashboard**: workspaces, meet types and the profile live in browser `localStorage`; meetings, tasks and
  records come from the backend. `src/App.tsx` (~4,100 lines) and `backend/main.py` (~1,500 lines) are due a split.
- **Not measured**: no automatic accuracy check for the minutes or record tagging yet. Those are checked by hand
  in live runs ([LIVE_TESTS.md](LIVE_TESTS.md) sections J–K).
- **Timezone**: due dates and reminders use one team timezone (`AMBER_TZ`).

History of what was built and why, with the status of every item, is in
[docs/build-plan.md](docs/build-plan.md).
