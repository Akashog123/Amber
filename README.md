# Amber Meet Agent

Amber is an operator-managed meeting agent for Google Meet, Zoom, and Microsoft
Teams. An operator uses this application to tell Amber which meeting to attend,
when to attend it, and what context or agenda to use.

> **Core product rule:** the human operator does not join a meeting through this
> application. The application schedules and controls Amber. Amber is the
> participant that joins the external meeting.

This repository contains the **Amber Live POC**: the React dashboard plus a
FastAPI backend (`backend/`) that sends Amber into real calls through Recall.ai.
The sections after "Running the POC" describe the intended production design
(auth, queues, adapters), which the POC deliberately leaves out.

## Running the POC

What it does, end to end: load agenda + document + mock records before the call →
Amber joins (Recall.ai), transcribes (Deepgram nova-3, `en-IN`), answers out loud
when addressed (or in chat), says "I don't have that information in my current
records" instead of guessing → extracts tasks and tags discussion to mock
procurement/equipment records, asking first (raised hand in chat) when the words
fit more than one record → MOM + recap email to attendees → reminder emails to
task owners. Also: pause/resume recording by voice or chat, screen-share questions,
Hindi/Hinglish, memory across meetings of the same meet type, scheduled joins,
recording playback.

```bash
# 1. Backend (Python 3.13, uv)
cd backend
cp .env.example .env          # fill in keys; every variable is explained there
uv run uvicorn main:app --port 8000

# 2. Public tunnel for Recall's webhooks (put the https URL in PUBLIC_URL, restart the backend)
cloudflared tunnel --url http://localhost:8000

# 3. Dashboard (proxies /api to :8000)
pnpm install && pnpm dev      # http://localhost:5173
```

In the dashboard: create a workspace and a meet type, paste the Meet link, add
attendees as `Name, email` lines, **Send Amber**, then admit "Amber" in Meet.
`LIVE_TESTS.md` has the exact lines to say for every feature.

Without a Recall key (or with `"replay": true`), `uv run python replay.py` plays
a scripted meeting through the same webhook handler; `--email you@x.com` sends
the recap and reminder to you. Tests: `uv run python test_core.py` (prints `ok`;
all external APIs are stubbed).

Notes:
- The operator API only answers local requests; through the tunnel only
  `/webhooks/recall` (token in the URL) and `/ws/recall` are reachable.
- Meet guests must be admitted by the host; Workspace meetings may block guests.
- `AMBER_DEMO_REMINDER_MINUTES=2` sends reminders 2 minutes after the call (demo);
  leave it empty to remind 24 h before each due date.
- While recording is paused Recall sends no transcript, so Amber can't hear
  "resume": resume from the chat or the dashboard.

## Product model

### Actors

- **Operator:** the single human managing Amber from this application.
- **Amber:** the automated meeting participant controlled by the operator.
- **Meeting platform:** Google Meet, Zoom, or Microsoft Teams.
- **Meeting participants:** people already attending on the external platform.
  They do not need an account in this application.

The first production version is designed for one operator. The data model
should still use an `ownerId` so that accounts, teams, or multiple operators can
be added later without migrating every record.

### What the operator does

1. Creates a workspace, such as a company, client, or internal team.
2. Creates reusable meeting types inside that workspace.
3. Gives a meeting type reusable context, goals, or instructions.
4. Either:
   - pastes a live meeting link and sends Amber immediately, or
   - schedules Amber to attend once or on a recurring schedule.
5. Optionally adds an occurrence-specific agenda or document.
6. Monitors whether Amber is scheduled, joining, waiting, connected,
   processing, completed, or failed.
7. Reviews the recording status, summary, participants, chat, decisions, and
   action items after the meeting.

### What Amber does

1. Receives a validated meeting link and operator instructions.
2. Identifies the meeting platform.
3. Starts at the requested time, or immediately for a live request.
4. Opens the external meeting as the Amber participant.
5. Handles a waiting room or admission flow.
6. Captures the permitted meeting media and events.
7. Produces meeting artifacts such as a transcript, summary, decisions, and
   action items.
8. Reports every lifecycle change back to the backend and frontend.
9. Leaves when the meeting ends, the operator stops it, or a configured timeout
   is reached.

### What the product does not do

- It does not launch the operator into Google Meet, Zoom, or Teams.
- It is not a video-conferencing client.
- It does not require meeting participants to use this application.
- It must not imply that a successful scheduling request means Amber has
  already entered the meeting.
- It must not mark a meeting completed solely because its scheduled time has
  passed.

## Terminology

Use these terms consistently in frontend copy, backend schemas, and logs:

| Term | Meaning |
| --- | --- |
| Workspace | A company, client, team, or other organizational grouping |
| Meeting type | Reusable configuration and context within a workspace |
| Meeting | A single external call Amber should attend |
| Series | A recurrence rule that creates meeting occurrences |
| Occurrence | One scheduled meeting in a recurring series |
| Context | Reusable information Amber should know |
| Agenda | Instructions or topics unique to one meeting occurrence |
| Dispatch | A backend request that starts or schedules Amber |
| Session | One execution of Amber against one meeting occurrence |
| Artifact | Transcript, recording, summary, decisions, chat, or action items |

Product buttons should use language such as **Send Amber**, **Schedule Amber**,
**Stop Amber**, and **View recap**. Avoid a bare **Join meeting** action because
it can imply that the operator will join.

## Current frontend

### Stack

- React 19
- TypeScript 5.7
- Vite 8
- Tailwind CSS 4
- Lucide React icons
- pnpm 10
- Node.js 22

### Repository structure

```text
.
├── public/
│   └── assets/          # Amber illustrations and meeting artwork
├── src/
│   ├── App.tsx          # Current UI, state, forms, and prototype data model
│   ├── index.css        # Tailwind import, global styles, and animation
│   └── main.tsx         # React entry point
├── index.html
├── package.json
├── vite.config.ts
└── .mise.toml
```

### Local development

```bash
pnpm install
pnpm dev
```

In Figma Make, the Vite development server is started automatically and should
not be started a second time. The default port is `8443`, or the value of
`PORT`.

Useful commands:

```bash
pnpm build
pnpm format
```

### Prototype persistence

The current frontend stores prototype data in the browser:

| Browser store | Current use |
| --- | --- |
| `amber-workspaces-v2` | Workspaces and meeting types |
| `amber-tagged-meetings-v2` | Quick-dispatch meeting records |
| `amber-scheduled-meetings-v2` | Calendar occurrences |
| `amber-profile-v2` | Operator preferences |
| IndexedDB `amber-documents/files` | Uploaded document blobs |

This storage is only suitable for the frontend prototype. It is local to one
browser, has no server-side scheduler, and cannot start Amber when the page is
closed. The backend must become the source of truth before the agent can be
considered functional.

## Required end-to-end flows

### Send Amber now

1. Operator selects a workspace and meeting type.
2. Operator enters a meeting name and external meeting URL.
3. Operator optionally writes context or uploads one supported document.
4. Frontend validates the request.
5. Frontend creates a meeting with `dispatchMode: "now"`.
6. Backend creates a session and enqueues the agent job.
7. Frontend navigates to, or displays, the live session status.
8. Backend emits lifecycle events until Amber connects, finishes, or fails.
9. The operator can stop or retry Amber without joining the external call.

### Schedule Amber

1. Operator chooses workspace, meeting type, title, URL, date, time, duration,
   and timezone.
2. Operator optionally configures recurrence.
3. Backend stores the meeting or series in UTC while preserving the source
   timezone.
4. A durable scheduler enqueues an occurrence before its start time.
5. Amber begins joining at `scheduledStartAt - joinLeadSeconds`.
6. The frontend receives live status events.
7. A missed or failed dispatch is visible and retryable.

### Add occurrence-specific agenda

1. Operator opens one scheduled occurrence.
2. The reusable meeting-type context is shown read-only.
3. Operator writes an agenda or attaches a document for that occurrence.
4. Backend stores the agenda against the occurrence, not the whole series.
5. The final agent instructions combine:
   - operator/agent preferences,
   - workspace context,
   - meeting-type context,
   - occurrence agenda, and
   - extracted document text.

### Recurring meetings

The backend should store a recurrence rule and materialize occurrences within a
bounded scheduling horizon. Do not store unrelated copies with no series ID.

The operator must eventually be able to:

- edit only this occurrence,
- edit this and future occurrences,
- edit the full series,
- cancel one occurrence, and
- stop the series.

### Meeting completion

1. Amber leaves or is removed from the meeting.
2. Session state becomes `processing`.
3. Media and event ingestion finishes.
4. Transcript and artifacts are generated.
5. Session becomes `completed`, `partially_completed`, or `failed`.
6. Frontend shows the recap only when the corresponding data is ready.

## Agent lifecycle

Use an explicit session state machine. The frontend must display the backend
state instead of inferring it only from the clock.

```text
draft
  -> scheduled
  -> queued
  -> launching
  -> joining
  -> waiting_for_admission
  -> connected
  -> recording
  -> leaving
  -> processing
  -> completed
```

Terminal or exceptional states:

```text
cancelled
missed
rejected
timed_out
failed
partially_completed
```

Recommended transition rules:

- `scheduled -> queued`: scheduler claims the occurrence.
- `queued -> launching`: an agent worker accepts the job.
- `launching -> joining`: the platform adapter opens the meeting.
- `joining -> waiting_for_admission`: Amber reaches a lobby.
- `joining|waiting_for_admission -> connected`: Amber enters the call.
- `connected -> recording`: capture is active and permitted.
- `recording -> leaving`: call ends or the operator requests a stop.
- `leaving -> processing`: live capture has stopped.
- `processing -> completed`: required artifacts are ready.
- Any nonterminal state may become `failed` with a machine-readable reason.

Every transition should store a timestamp and append an immutable lifecycle
event for audit and debugging.

## Proposed backend architecture

The backend technology is not fixed by this frontend. A production
implementation needs the following logical services:

```text
React frontend
    |
    | HTTPS + authenticated realtime channel
    v
API service
    |---- relational database
    |---- object storage
    |---- durable job queue
    |---- scheduler
    |---- notification service
    |
    v
Agent orchestrator
    |---- Google Meet adapter
    |---- Zoom adapter
    |---- Microsoft Teams adapter
    |---- transcription pipeline
    |---- artifact generation pipeline
    |
    v
Realtime event service
```

### API service

Responsible for:

- operator authentication and authorization,
- workspace and meeting-type CRUD,
- meeting and series CRUD,
- URL validation and platform detection,
- upload authorization,
- dispatch, stop, and retry commands,
- returning recap data,
- exposing audit history, and
- publishing sanitized realtime state.

### Durable scheduler and queue

Scheduling cannot depend on an open browser tab. The scheduler must:

- store times in UTC,
- preserve IANA timezone names,
- account for daylight-saving changes,
- prevent duplicate dispatches,
- retry transient failures,
- use leases so only one worker claims a session, and
- recover jobs after process restarts.

### Agent orchestrator

The orchestrator owns one agent session from launch through cleanup. It should:

- use an idempotency key per occurrence attempt,
- select the correct platform adapter,
- emit heartbeats,
- enforce maximum waiting and meeting durations,
- release browser/media resources,
- upload artifacts,
- redact secrets from logs, and
- report structured failure codes.

### Platform adapters

Expose a common internal interface:

```ts
interface MeetingPlatformAdapter {
  detect(url: URL): boolean
  validate(input: ValidateMeetingInput): Promise<ValidationResult>
  join(input: JoinMeetingInput): Promise<PlatformSession>
  getStatus(session: PlatformSession): Promise<PlatformStatus>
  leave(session: PlatformSession): Promise<void>
}
```

Platform-specific authentication, bot approval, recording consent, SDK/browser
automation, and policy requirements should remain inside each adapter.

Do not assume all platforms expose the same capabilities. Store capability
flags such as:

```ts
type PlatformCapabilities = {
  audioCapture: boolean
  videoCapture: boolean
  participantEvents: boolean
  chatEvents: boolean
  nativeRecording: boolean
  waitingRoomDetection: boolean
}
```

## Suggested data model

IDs should be opaque UUIDs. Every mutable record should include `createdAt`,
`updatedAt`, and an ownership boundary.

### Operator

```ts
type Operator = {
  id: string
  email: string
  displayName: string
  timezone: string
  defaultWorkspaceId: string | null
  emailSummaries: boolean
  agentPersonality: string
  createdAt: string
  updatedAt: string
}
```

### Workspace

```ts
type Workspace = {
  id: string
  ownerId: string
  name: string
  context: string | null
  createdAt: string
  updatedAt: string
}
```

### Meeting type

```ts
type MeetingType = {
  id: string
  ownerId: string
  workspaceId: string
  name: string
  context: string | null
  defaultDurationMinutes: number | null
  joinLeadSeconds: number
  createdAt: string
  updatedAt: string
}
```

### Meeting series

```ts
type MeetingSeries = {
  id: string
  ownerId: string
  workspaceId: string
  meetingTypeId: string
  title: string
  meetingUrl: string
  platform: "google_meet" | "zoom" | "microsoft_teams"
  timezone: string
  recurrenceRule: string
  startsAtLocal: string
  durationMinutes: number
  status: "active" | "paused" | "ended" | "cancelled"
  createdAt: string
  updatedAt: string
}
```

An RFC 5545 RRULE or a well-tested recurrence library is preferred over custom
date arithmetic.

### Meeting occurrence

```ts
type MeetingOccurrence = {
  id: string
  ownerId: string
  seriesId: string | null
  workspaceId: string
  meetingTypeId: string
  title: string
  meetingUrl: string
  platform: "google_meet" | "zoom" | "microsoft_teams"
  dispatchMode: "now" | "scheduled"
  scheduledStartAt: string
  scheduledEndAt: string | null
  timezone: string
  agenda: string | null
  status:
    | "draft"
    | "scheduled"
    | "cancelled"
    | "completed"
    | "failed"
  createdAt: string
  updatedAt: string
}
```

### Agent session

```ts
type AgentSession = {
  id: string
  ownerId: string
  occurrenceId: string
  attempt: number
  state: AgentSessionState
  stateReason: string | null
  idempotencyKey: string
  platformSessionId: string | null
  queuedAt: string | null
  launchedAt: string | null
  joinedAt: string | null
  leftAt: string | null
  completedAt: string | null
  lastHeartbeatAt: string | null
  createdAt: string
  updatedAt: string
}
```

### Document

```ts
type Document = {
  id: string
  ownerId: string
  occurrenceId: string | null
  meetingTypeId: string | null
  originalName: string
  mimeType: string
  sizeBytes: number
  storageKey: string
  extractionState: "pending" | "processing" | "ready" | "failed"
  extractedTextKey: string | null
  createdAt: string
}
```

### Meeting artifacts

```ts
type MeetingArtifacts = {
  occurrenceId: string
  sessionId: string
  transcriptState: "unavailable" | "processing" | "ready" | "failed"
  recordingState: "unavailable" | "processing" | "ready" | "failed"
  transcriptUrl: string | null
  recordingUrl: string | null
  summary: string | null
  takeaways: string[]
  decisions: string[]
  participants: ParticipantEvent[]
  chat: ChatMessage[]
  tasks: ActionItem[]
  generatedAt: string | null
}
```

## Frontend API contract

Use a versioned prefix such as `/api/v1`. The examples below define the
behavioral contract; field names can be adjusted once a backend stack is
selected.

### Authentication

```text
GET    /api/v1/me
POST   /api/v1/auth/logout
```

The browser should use a secure, HTTP-only session cookie. Do not store
long-lived authentication tokens in localStorage.

### Workspaces and meeting types

```text
GET    /api/v1/workspaces
POST   /api/v1/workspaces
PATCH  /api/v1/workspaces/:workspaceId
DELETE /api/v1/workspaces/:workspaceId

POST   /api/v1/workspaces/:workspaceId/meeting-types
PATCH  /api/v1/meeting-types/:meetingTypeId
DELETE /api/v1/meeting-types/:meetingTypeId
```

Deletion must define whether linked future meetings are cancelled, reassigned,
or block deletion. It must never silently leave orphaned occurrences.

### URL validation

```text
POST /api/v1/meeting-links/validate
```

Request:

```json
{
  "url": "https://meet.google.com/abc-defg-hij"
}
```

Response:

```json
{
  "valid": true,
  "normalizedUrl": "https://meet.google.com/abc-defg-hij",
  "platform": "google_meet",
  "warnings": []
}
```

Only supported `https` URLs should be accepted. The backend must protect any
server-side link inspection against SSRF.

### Immediate dispatch

```text
POST /api/v1/meetings/dispatch
```

Request:

```json
{
  "workspaceId": "ws_123",
  "meetingTypeId": "mt_123",
  "title": "Weekly product review",
  "meetingUrl": "https://meet.google.com/abc-defg-hij",
  "agenda": "Review release readiness",
  "documentIds": [],
  "idempotencyKey": "client-generated-uuid"
}
```

Response:

```json
{
  "meeting": {
    "id": "meeting_123",
    "status": "scheduled",
    "dispatchMode": "now"
  },
  "session": {
    "id": "session_123",
    "state": "queued"
  }
}
```

The frontend should then subscribe to `session_123`. A successful HTTP response
means the dispatch was accepted; it does not mean Amber is connected.

### Scheduled meeting

```text
POST   /api/v1/meetings
GET    /api/v1/meetings?from=:iso&to=:iso&workspaceId=:id
GET    /api/v1/meetings/:meetingId
PATCH  /api/v1/meetings/:meetingId
DELETE /api/v1/meetings/:meetingId
POST   /api/v1/meetings/:meetingId/dispatch
POST   /api/v1/meetings/:meetingId/cancel
```

Create request:

```json
{
  "workspaceId": "ws_123",
  "meetingTypeId": "mt_123",
  "title": "Weekly product review",
  "meetingUrl": "https://zoom.us/j/123456789",
  "scheduledStartAt": "2026-06-18T09:00:00-04:00",
  "timezone": "America/New_York",
  "durationMinutes": 45,
  "agenda": null,
  "documentIds": []
}
```

### Recurring series

```text
POST   /api/v1/meeting-series
GET    /api/v1/meeting-series/:seriesId
PATCH  /api/v1/meeting-series/:seriesId
DELETE /api/v1/meeting-series/:seriesId
```

Occurrence edits should accept a scope:

```json
{
  "scope": "occurrence"
}
```

or:

```json
{
  "scope": "this_and_future"
}
```

### Agent control

```text
GET  /api/v1/sessions/:sessionId
POST /api/v1/sessions/:sessionId/stop
POST /api/v1/sessions/:sessionId/retry
GET  /api/v1/sessions/:sessionId/events
```

Stop and retry endpoints must be idempotent.

### Documents

Preferred direct-to-object-storage flow:

```text
POST /api/v1/documents/upload-intent
POST /api/v1/documents/:documentId/complete
GET  /api/v1/documents/:documentId
DELETE /api/v1/documents/:documentId
```

The backend should validate file size, extension, MIME type, ownership, malware
scan status, and extraction status. The current frontend accepts PDF, DOC,
DOCX, and TXT files up to 10 MB.

### Recap

```text
GET /api/v1/meetings/:meetingId/artifacts
```

Return independent readiness states for transcript, recording, and generated
insights so that the frontend can show partial completion accurately.

## Realtime contract

Use WebSocket or Server-Sent Events. SSE is sufficient if the browser only
receives state; WebSocket is useful if interactive agent controls will expand.

Suggested stream:

```text
GET /api/v1/events
```

Event envelope:

```ts
type RealtimeEvent<T> = {
  id: string
  type: string
  occurredAt: string
  resourceType: "meeting" | "session" | "artifact" | "document"
  resourceId: string
  version: number
  data: T
}
```

Required event types:

```text
meeting.created
meeting.updated
meeting.cancelled
session.queued
session.launching
session.joining
session.waiting_for_admission
session.connected
session.recording
session.leaving
session.processing
session.completed
session.failed
artifact.updated
document.updated
```

Example:

```json
{
  "id": "evt_123",
  "type": "session.waiting_for_admission",
  "occurredAt": "2026-06-18T12:59:43.102Z",
  "resourceType": "session",
  "resourceId": "session_123",
  "version": 5,
  "data": {
    "meetingId": "meeting_123",
    "message": "Amber is waiting for a participant to admit it."
  }
}
```

The frontend should reconnect using the last received event ID and refetch the
resource after a version gap.

## Frontend integration plan

The current `src/App.tsx` should eventually be split by responsibility. A
suggested structure is:

```text
src/
├── app/
│   ├── App.tsx
│   ├── router.tsx
│   └── providers/
├── api/
│   ├── client.ts
│   ├── meetings.ts
│   ├── sessions.ts
│   ├── workspaces.ts
│   └── documents.ts
├── components/
│   ├── dialogs/
│   ├── forms/
│   └── meeting-status/
├── features/
│   ├── dashboard/
│   ├── dispatch/
│   ├── meetings/
│   ├── recaps/
│   ├── settings/
│   └── workspaces/
└── types/
    └── api.ts
```

Recommended migration:

1. Keep the existing visual components.
2. Introduce a typed API client and server response types.
3. Replace localStorage workspace data with API queries and mutations.
4. Replace `meetingsByDate` with server-provided occurrences.
5. Replace IndexedDB document persistence with upload intents.
6. Connect immediate dispatch to the dispatch endpoint.
7. Subscribe to session events and display the real lifecycle.
8. Connect the recap page to artifact readiness and data.
9. Remove duplicate or unused prototype meeting forms.
10. Retain localStorage only for harmless UI preferences.

### Recommended frontend routes

```text
/                         Landing or authenticated redirect
/calendar/:date           Scheduled occurrences and immediate dispatch
/meetings/:meetingId      Meeting details and current session state
/meetings/:meetingId/recap
/settings
```

## Environment variables

Exact names depend on the selected backend and deployment platform. A likely
frontend variable is:

```text
VITE_API_BASE_URL=
```

Potential backend variables:

```text
DATABASE_URL=
REDIS_URL=
OBJECT_STORAGE_BUCKET=
OBJECT_STORAGE_REGION=
OBJECT_STORAGE_ACCESS_KEY_ID=
OBJECT_STORAGE_SECRET_ACCESS_KEY=
SESSION_SECRET=
FRONTEND_ORIGIN=
GOOGLE_MEET_ADAPTER_CONFIG=
ZOOM_ADAPTER_CONFIG=
MICROSOFT_TEAMS_ADAPTER_CONFIG=
TRANSCRIPTION_PROVIDER_API_KEY=
LLM_PROVIDER_API_KEY=
EMAIL_PROVIDER_API_KEY=
```

Do not expose backend credentials through `VITE_` variables. All Vite-prefixed
variables are bundled into browser code.

## Security, privacy, and compliance

Meeting agents handle highly sensitive information. Production work must
include:

- explicit operator authorization for every meeting,
- visible and legally appropriate recording/agent disclosure,
- platform-specific terms and bot policies,
- consent rules for recording and transcription,
- encryption in transit and at rest,
- tenant/owner isolation on every query,
- short-lived signed artifact URLs,
- strict retention and deletion controls,
- audit logs for dispatch, join, stop, download, and deletion,
- secret redaction in logs,
- malware scanning for uploads,
- SSRF protection for meeting URLs,
- rate limits and dispatch quotas,
- idempotency on all command endpoints,
- restricted internal access to recordings and transcripts, and
- regional and contractual requirements for stored meeting data.

The backend should support deleting a meeting and all associated documents,
sessions, media, transcripts, and generated artifacts.

## Observability

Every session should be traceable by:

- `ownerId`
- `meetingId`
- `occurrenceId`
- `sessionId`
- `attempt`
- `platform`
- `workerId`
- `idempotencyKey`

Recommended operational signals:

- dispatch-to-launch latency,
- launch-to-lobby latency,
- lobby-to-connected latency,
- join success rate by platform,
- waiting-room timeout rate,
- average connected duration,
- agent heartbeat age,
- transcription completion time,
- artifact-generation completion time,
- retry count, and
- structured failure reason.

Never place meeting passwords, access tokens, transcript contents, or document
contents in routine application logs.

## Failure handling

The API should return stable machine-readable error codes. Examples:

```text
UNSUPPORTED_MEETING_URL
INVALID_MEETING_URL
MEETING_NOT_FOUND
MEETING_REQUIRES_PASSWORD
AGENT_NOT_ADMITTED
AGENT_REJECTED
PLATFORM_AUTH_REQUIRED
PLATFORM_RATE_LIMITED
JOIN_TIMEOUT
MEETING_ENDED
AGENT_HEARTBEAT_LOST
CAPTURE_FAILED
TRANSCRIPTION_FAILED
ARTIFACT_GENERATION_FAILED
DOCUMENT_REJECTED
DOCUMENT_EXTRACTION_FAILED
```

Each error response should include:

```json
{
  "error": {
    "code": "AGENT_NOT_ADMITTED",
    "message": "Amber was not admitted before the waiting-room timeout.",
    "retryable": true,
    "requestId": "req_123"
  }
}
```

The frontend should show an operator-friendly message and expose a retry action
only when `retryable` is true.

## Testing strategy

### Frontend

- Component tests for forms and lifecycle status.
- API client contract tests.
- Responsive tests at mobile, tablet, and desktop widths.
- Keyboard and screen-reader checks for dialogs and controls.
- End-to-end tests for immediate dispatch, scheduling, stop, retry, and recap.

### Backend

- Unit tests for recurrence and timezone behavior.
- State-machine transition tests.
- Idempotency and duplicate-job tests.
- Authorization and tenant-isolation tests.
- Upload validation and SSRF tests.
- Queue lease and crash-recovery tests.
- Webhook signature and replay tests.

### Platform adapters

- Adapter contract tests shared across all platforms.
- Test meetings for Google Meet, Zoom, and Microsoft Teams.
- Lobby admitted, rejected, and timeout scenarios.
- Host-ended and network-disconnected scenarios.
- Capability tests for participants, chat, media, and recording.

Use fake adapters in routine CI. Run real-platform tests in a controlled,
rate-limited integration environment.

## Delivery roadmap

### Phase 1: Backend foundation

- Authentication for one operator.
- Database schema and migrations.
- Workspace and meeting-type APIs.
- Meeting URL validation and platform detection.
- Meeting CRUD.
- Durable queue, scheduler, and realtime events.
- Signed document uploads.

### Phase 2: One working platform

- Implement one platform adapter end to end.
- Immediate dispatch.
- Scheduled dispatch.
- Stop and retry.
- Lifecycle status in the frontend.
- Operational logs and metrics.

Starting with one platform is strongly recommended. Do not implement three
partially working adapters before one complete agent flow is reliable.

### Phase 3: Meeting intelligence

- Audio/media ingestion.
- Transcription.
- Participant and chat events where supported.
- Summary, decisions, takeaways, and action items.
- Recap UI backed by real artifacts.
- Email summary delivery.

### Phase 4: Recurrence and additional platforms

- Durable meeting series.
- Occurrence-level overrides.
- Second and third platform adapters.
- Capability-aware UI.
- Platform-specific error recovery.

### Phase 5: Production hardening

- Retention controls.
- Complete deletion.
- Consent and compliance review.
- Quotas and rate limiting.
- Security testing.
- Backup and recovery.
- Load, soak, and failure-injection testing.

## Definition of done for the first complete version

The first production-ready Amber workflow is complete when:

1. The operator can sign in securely.
2. The operator can create a workspace and meeting type.
3. A supported meeting URL is validated and normalized.
4. The operator can send Amber now without joining the call.
5. The operator can schedule Amber while the browser is closed.
6. Duplicate requests do not launch duplicate agents.
7. The UI shows accurate live agent status.
8. The operator can stop and retry Amber.
9. Amber can handle a waiting room and report admission failure.
10. Amber leaves and releases resources reliably.
11. A transcript and summary are attached to the correct meeting.
12. Access to every meeting and artifact is owner-authorized.
13. Meeting data can be deleted completely.
14. Failures are observable through stable error codes and request IDs.
15. Core flows are covered by automated end-to-end tests.

## Important implementation note

The frontend currently uses “join” language in a few places inherited from the
prototype. In all backend and product work, interpret that action as:

> **Dispatch Amber to join the external meeting as the agent participant.**

It must never navigate the operator into the external meeting as the primary
product action.
