# AMBER LIVE — Complete Master Specification, Architecture, UI Design & Build Plan

## PART 1: PRODUCT MISSION & ZERO-COST TECH STACK

### 1.1 Overview
Amber Live is an active, multimodal AI meeting agent built for Google Meet that covers the entire meeting lifecycle:
1. **Before the Meeting:** Ingests pre-meeting context (agenda, background docs, notes, and system records) before joining the call.
2. **During the Meeting (Attendance & Non-Premium Recording):** Joins live Google Meet calls via Recall.ai, tracks exact participant join/leave timestamps, and starts/stops recording the screen and call via voice command without requiring Google Meet Premium.
3. **During the Meeting (Multimodal Perception):** Listens to speaker-diarized audio in real time, reads and replies to in-meeting Google Meet chat messages, and captures shared screen frames using Gemini 2.5 Flash vision so it understands slides, dashboards, and spreadsheets shown on screen.
4. **During the Meeting (Flawless Human Etiquette & Zero-Latency Voice):**
   - **Direct Wake-Word Response:** Responds concisely (1–2 sentences, `max_output_tokens=120`) when addressed ("Amber...").
   - **Polite Raise-Hand Protocol:** If two or more people are actively conversing and Amber has a relevant database insight or correction to add, Amber NEVER interrupts vocally. It raises its hand (`HAND_RAISED` state + visual banner on its video feed + polite chat notice) and waits silently until permitted to speak ("Go ahead, Amber").
   - **Instant Barge-In Cut-Off (<100ms):** If Amber is speaking and any human starts talking over it, Amber immediately stops speaking within 100ms and switches back to listening mode.
   - **Grounded Accuracy + Honest Fallback:** Answers using pre-meeting context, live transcript, screen vision, system records, or general LLM intelligence for related concepts, and explicitly states `"I don't have that information in my current records"` instead of guessing unknown internal facts.
5. **Autonomous Database Management:** Automatically extracts tasks with owners and deadlines, logs verbal status updates on existing tasks, and attaches meeting context to System Records (Procurement Log & Equipment List) with a confidence check.
6. **After the Meeting:** Automatically generates a structured Minutes of Meeting (MOM) and dispatches HTML recap emails to attendees and automated task status reminder emails to task owners.

### 1.2 100% Free-Tier Technical Stack
- **Backend:** Python 3.11+, FastAPI, Uvicorn, WebSockets, SQLAlchemy (local SQLite database `amber.db`), Pydantic v2.
- **Meeting Bot & Media Layer:** Recall.ai API (Bot Join, Live Transcript Webhook, Participant Join/Leave Webhook, Chat Read/Write, Start/Stop Recording API, and Output Media Webpage for zero-latency voice output + client-side WebRTC Voice Activity Detection).
- **Multimodal LLM & Vision:** Google Gemini API (`google-genai` SDK using `gemini-2.5-flash`) for streaming responses, screen-share image analysis, structured JSON extraction, and MOM generation.
- **Voice Output (TTS):** ElevenLabs API (`eleven_flash_v2_5` model for ~250ms latency) with automatic fallback to browser Web Speech synthesis during local simulator testing to save free credits.
- **Email Dispatcher:** Python `smtplib` / `email.mime` with Gmail SMTP App Password (plus local database email preview log in the UI).
- **Frontend:** React 18, Vite, TypeScript, Tailwind CSS, Lucide React icons.
- **Repository Hygiene:** `.gitignore` MUST ignore `.kiro/`, `node_modules/`, `.venv/`, `__pycache__/`, `.env`, and `*.db`.

---

## PART 2: SYSTEM ARCHITECTURE & DATABASE SCHEMA

### 2.1 High-Level Data Flow