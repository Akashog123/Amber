# Amber Live: write-up

Amber is an AI participant an operator sends into a Google Meet. Zoom and Teams links go through the same
Recall.ai API. Before the call she loads the agenda, one document, the company's records and the last three
meetings of the same type. During the call she answers by voice or in chat when someone speaks to her. After
the call she writes the minutes, emails a recap, reminds task owners and adds notes to the right records.
This is a POC: one operator, mock procurement and equipment records, and no accounts.

## Setup (run it yourself)

**Prerequisites:** Python 3.13 with `uv`, Node 22 with `pnpm` (`.mise.toml` pins both), and `cloudflared`
or ngrok. For live calls you also need a Recall.ai key, an ElevenLabs key, an LLM (any OpenAI-compatible
endpoint and/or a Gemini key) and a Gmail app password for SMTP. Without a Recall key, use the replay
mode below.

```bash
# 1. Backend: every variable is explained in backend/.env.example
cd backend
cp .env.example .env          # fill RECALL_API_KEY, LLM_* or GEMINI_API_KEY, ELEVENLABS_API_KEY, SMTP_USER/PASS, WEBHOOK_TOKEN
uv run uvicorn main:app --port 8000

# 2. Public tunnel so Recall can reach the webhooks (put the https URL in PUBLIC_URL, then restart the backend)
cloudflared tunnel --url http://127.0.0.1:8000

# 3. Dashboard (proxies /api to :8000)
pnpm install && pnpm dev      # http://localhost:5173
```

**First meeting:** create a workspace and meet type, paste a Meet link, add attendees as `Name, email`,
click **Send Amber**, then admit "Amber" in Meet. [LIVE_TESTS.md](LIVE_TESTS.md) lists the exact lines to say
for each feature. [DEMO_SCRIPT.md](DEMO_SCRIPT.md) is a timed walkthrough of the full lifecycle for one
presenter, with a sample document to upload ([chiller-vibration-note.txt](chiller-vibration-note.txt)).

**No keys:** `uv run python replay.py` plays a scripted meeting through the same webhook handler. Add
`--email you@x.com` to receive the recap and reminder emails.

**Tests:**

```bash
uv run python test_core.py       # turn-taking, grounding, extraction, record routing; APIs stubbed; prints ok
uv run python test_golden.py     # replays recorded live calls at real timing
uv run python eval_scenarios.py  # labelled model-written meetings through real routing + real model
```

## Architecture

```
React dashboard ──REST + WS───► FastAPI (backend/main.py) ── SQLite (stdlib sqlite3)
                                   │
Recall.ai bot in the meeting ──webhooks / websocket──► /webhooks/recall, /ws/recall
   ▲                               │
   └── output_audio, chat ◄────────┤ turns.py   decides who Amber is talking with (pure, no I/O)
       or /media/amber page        │ brain.py   LLM calls: answer, "is this for Amber?", extract, minutes
       (streaming voice)           │ voice.py   ElevenLabs TTS
                                   │ mailer.py  Gmail SMTP + outbox table in the dashboard
replay.py, test_golden.py ─────────┘ post the same webhook payloads locally
```

| Stage | How it works |
|---|---|
| Context in | Agenda, one PDF/TXT, attendees, linked records, the last 3 minutes of the same meet type and open tasks are built into one context. |
| Participation | Recall bot joins and Deepgram nova-3 transcribes. Every final line goes through `turns.route()`. When a line is for Amber, she answers from her context only, or says she doesn't have that information. Chat works the same way. |
| Recap | When the bot leaves, Amber writes minutes (summary, decisions, action items, open questions, attendance) and sends an HTML email to all attendees, including people who typed their email in chat. |
| Follow-ups | Every 4 human lines, an extraction pass finds tasks (owner, due date, the owner's own words) and progress on existing tasks. Owners get a reminder 24 h before the due date. |
| Records | The same pass tags discussion to records. A note is written only when the speaker's words point to one record. When they fit several, Amber raises her hand and asks which one. |

Also built: off-the-record mode, screen-share questions, Hindi/Hinglish, scheduled joins, recording
playback, voice commands such as "Amber, leave the meeting", and deleting a finished meeting. Deleting removes
its transcript, chat, minutes, tasks, record notes and outbox here, its recording and transcript at Recall, and
its raw log, so later meetings of the same type no longer remember it.

## Key decisions

| Decision | Why | What it costs |
|---|---|---|
| **Recall.ai, not our own headless-browser bot** | One API covers joining, transcription, chat and audio output on Meet, Zoom and Teams. That made a working live POC possible in days. | Billed per hour. A host must admit the bot. Some Workspace meetings block guests. |
| **Turn-taking as one pure state machine** (`turns.py`) | It replaced six independent timers that conflicted. Every decision (ignore, start, append, merge, queue, classify) is logged with a reason in the activity feed and can be tested without I/O. | Only unclear lines inside an open conversation go to the model, about two small calls per meeting. |
| **Conversation engagement, not a fixed window** | People drop "Amber" in follow-up questions, and a 10 s window cut real conversations short. A conversation now ends on "that's all", 3 lines between other people, or 75 s idle. | She can occasionally answer a line that wasn't meant for her. Golden replays guard the known cases. |
| **Grounded answers only** | An assistant in a meeting that invents a PO number is worse than one that says "I don't have that". | She declines more often than a general chatbot would. |
| **Record writes need the speaker's own words, not model confidence alone** | Several records share words (for example, two pump orders). A wrong write to a system of record is expensive. | She asks more often (raised hand, then a chat question). |
| **Off the record handled by Amber, not by pausing Recall** | Pausing Recall also stopped the live transcript, so she couldn't hear anything. | Recall's raw recording still contains that stretch. |
| **LLM provider chain** (any OpenAI-compatible endpoint first, then Gemini, with per-call fallback) | Free-tier spikes of 4–7 s would otherwise stall a live answer. | More configuration. Answer quality varies by provider. |
| **SQLite, in-process event socket, one worker** | Nothing to run except the app. | No horizontal scaling and no durable queue. |
| **Deleting a meeting removes everything it produced**, including its tasks and the notes it added to records | Amber's memory of a meet type is built from those rows. If any stayed, a "deleted" meeting would still shape her answers in the next call. A meeting she is still in, or still writing minutes for, can't be deleted. | A correct record note from that meeting goes too. Emails already sent can't be recalled; the confirmation dialog says so. |
| **Fillers only after 1.2 s** | A filler before a fast answer only adds delay. | A slow reply still starts with a short silence. |

## What doesn't work yet

- **No auth or multi-tenancy.** Workspaces, meet types and the profile live in browser `localStorage`. The
  operator API is only protected by refusing tunnelled requests.
- **Records are mock seed data** (`backend/seed.py`), not a real ERP or CMMS. There are no external
  integrations besides Recall, Deepgram, ElevenLabs, the LLMs and Gmail SMTP.
- **Not durable.** Scheduled joins rely on Recall `join_at`. Reminders run in-process. A crash during a meeting
  loses in-memory conversation state. There is one uvicorn worker.
- **Latency.** First word usually comes 1–2 s after the question, with 4–7 s spikes on free LLM tiers. In `mp3`
  mode, interrupting her stops her in 0.5–1 s, not instantly. `mp3` is the working default.
- **Streaming voice is silent in Meet.** In a live Meet test (2026-10-18), the `stream` page played her speech
  and Recall captured it: her answers are in the bot's own recording (`AMBER_RECORD_SELF=1`). But participants
  heard nothing. The audio stops between Recall and Meet, so it needs Recall support or a different output path.
- **Recognition.** ASR sometimes mishears "Amber". Sound-alikes only count near the start of a request.
- **One speaker talking to the room.** A conversation with her also ends after 3 lines for other people,
  which never happens when only one person is in the call. A solo presenter has to say "that's all" (or wait
  75 s) before narrating, or she may treat the narration as a follow-up. Her name anywhere in a sentence can
  open a question, so "notice Amber stayed quiet" may get an answer.
- **Reminders need a matching attendee.** A task owner gets a reminder only when their name matches an
  attendee with an email (full name, or a unique first name). A task for someone not on the invite is saved
  but nobody is reminded.
- **Quality isn't measured end to end.** Routing has evals (6 model-written scenarios: 15/16 requests
  answered, 0 false triggers, plus golden replays). Minutes and record-tagging accuracy are only checked by
  hand.
- **Off the record** stays in Recall's raw recording until the whole meeting is deleted. There is no way to
  cut just that stretch.
- **One team timezone** (`AMBER_TZ`) for due dates and reminders.
- **Code shape.** `src/App.tsx` (~4,200 lines) and `backend/main.py` (~1,600 lines) need to be split.
- Raised hand shows on her video tile only in streaming mode. Screen vision answers on demand only; it doesn't
  narrate slides continuously.

## With another two weeks

**Week 1: make it trustworthy**

1. **Real integrations behind one interface.** Add a small `RecordSource` / `TaskSink` / `Notifier` boundary.
   The mock seed data becomes one implementation and real systems plug in beside it (see the list below). Then
   ship two real ones end to end: one task tracker (Jira or Linear) and one chat tool (Slack or Teams).
2. **Auth and server-side workspaces.** One operator login (OAuth), and workspaces, meet types and the profile
   moved from `localStorage` into the database with an `owner_id`, as in
   [docs/production-design.md](docs/production-design.md).
3. **Durability.** Persist conversation state and pending questions per meeting so a restart mid-call
   recovers. Move reminders and scheduled joins to a durable job table with idempotency keys, so a repeated
   dispatch can't launch two bots.
4. **Measure minutes and tagging.** Label 10–15 real meetings with expected decisions, tasks and record
   notes, then score precision/recall in `eval_scenarios.py` and run it in CI next to `test_golden.py`.

**Week 2: make it better in the call**

5. **Fix streaming voice in Meet** with Recall (her page's audio reaches the recording but not the call), then
   make it the default. That means about 0.9 s to first sound and instant barge-in.
6. **Write-back with approval.** Draft record and ticket updates during the meeting and let the operator (or
   the task owner, from the recap email) approve them in one click before anything reaches the real system.
7. **Calendar auto-join.** Read Google or Outlook calendars, show upcoming meetings that match a meet type,
   and dispatch Amber automatically. Recurring series come from the calendar, not manual scheduling.
8. **Split `App.tsx` and `main.py`** along the existing seams: dispatch, live view, recap, records, outbox.
9. **Per-attendee timezone** for reminders, and a retention policy (delete meetings automatically after N
   days, per meet type) on top of today's manual delete.

## External integrations roadmap

Each one plugs into a stage Amber already has, so it extends the pipeline without changing it:

| Stage | Integration | What it adds |
|---|---|---|
| Context in | **Google Drive, SharePoint/OneDrive, Notion, Confluence** | Pull the agenda and linked documents from the calendar invite instead of uploading one file. |
| Context in | **Google Calendar, Outlook/Graph** | Auto-dispatch, the attendee list and emails from the invite, recurring series. |
| Records | **ERP: SAP, Oracle NetSuite, Odoo** | Real purchase orders, vendors and delivery status, replacing the procurement seed data. |
| Records | **CMMS: IBM Maximo, UpKeep, Fiix** | Real equipment, work orders and maintenance history, replacing the equipment seed data. |
| Records | **CRM: Salesforce, HubSpot** | Account and deal context for client meetings; notes logged on the account. |
| Follow-ups | **Jira, Linear, Asana, ClickUp** | Action items become tickets with owner and due date. Spoken progress updates the ticket. |
| Recap | **Slack, Microsoft Teams** | Post the minutes to the team channel and send reminders as DMs instead of only email. |
| Recap | **Gmail API / Microsoft Graph mail** | Replace SMTP with OAuth sending from the operator's own mailbox, with threading and delivery status. |
| Platform | **Native Zoom / Teams apps** | Fall back to native SDKs where Recall is blocked or too expensive, behind the adapter interface in the production design. |
| Any | **MCP server / outbound webhooks** | Expose meetings, minutes and tasks as tools and events so other agents and internal systems can subscribe without a custom connector for each one. |

The rule that stays the same: **reads can be broad, writes need evidence.** An integration can read
anything Amber is allowed to see. A write needs the speaker's own words to point at one target, plus operator
approval for systems of record.

## Other improvements

- **Speaker identity.** Map Recall participant IDs to attendee emails so task owners resolve reliably, even
  when a name is misheard.
- **Faster turn detection.** Use a voice-activity or end-of-turn model instead of a fixed debounce
  (`AMBER_DEBOUNCE`) and partials.
- **Proactive mode, opt-in per meet type.** Flag when a decision contradicts a record ("PO-1042 is already
  marked delivered") instead of only answering when asked.
- **Cost controls.** Per-meeting token and Recall-minute budgets in the dashboard, and cheaper models for
  classification.
- **Observability.** Request IDs, stable error codes, latency histograms (question end → first audio), and
  alerts when a bot fails or isn't admitted.
- **Consent.** A join announcement and a chat notice with an opt-out, and recording disabled by default
  where required.
- **More languages** beyond English and Hindi, with fillers and fixed lines in each one.
