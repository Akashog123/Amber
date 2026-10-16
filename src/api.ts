// Typed client for the Amber backend (FastAPI on :8000, proxied by Vite at /api).
import { useEffect, useRef } from "react"
import { dateKey, type ScheduledMeet } from "./types"

export type MeetingStatus = string // queued | joining | in_call_recording | done | processing | completed | failed | replay ...

export type ApiMeeting = {
  id: number
  series_id: string | null
  title: string
  url: string
  platform: string
  status: MeetingStatus
  started_at: string | null
  ended_at: string | null
  created_at: string
}

export type ApiTask = {
  id: number
  title: string
  owner: string | null
  owner_email: string | null
  due_at: string | null
  status: "open" | "in_progress" | "done" | "blocked" | string
  quote: string | null
  last_update: string | null
  reminded_at: string | null
}

export type ApiRecordNote = { id: number; record_id: string; meeting_id: number; note: string; confidence: number; ts: string }

export type Mom = {
  executive_summary: string
  agenda_alignment: { item: string; status: string; notes: string }[]
  decisions: string[]
  open_questions: string[]
}

export type ApiMeetingDetail = ApiMeeting & {
  agenda: string | null
  context_text: string | null
  bot_id: string | null
  recording_url: string | null
  mom: Mom | null
  attendees: { name: string; email: string }[]
  participants: { name: string; joined_at: string | null; left_at: string | null }[]
  transcript: { speaker: string; text: string; ts: number | null; addressed: number }[]
  chat: { sender: string; text: string; ts: string; is_amber: number }[]
  tasks: ApiTask[]
  record_notes: ApiRecordNote[]
}

export type ApiRecord = {
  id: string
  kind: "procurement" | "equipment" | string
  name: string
  aliases: string
  status: string
  owner: string
  details: string
  notes: ApiRecordNote[]
}

export type OutboxItem = {
  id: number
  meeting_id: number | null
  kind: "recap" | "reminder" | string
  to_addr: string
  subject: string
  status: "sent" | "failed" | "skipped" | string
  error: string | null
  ts: string
  html?: string
  text?: string
}

export type DispatchRequest = {
  title: string
  url: string
  agenda: string
  context: string
  attendees: { name: string; email: string }[]
  series_id: string | null
  document_name?: string
  document_b64?: string
}

export type AmberEvent = { type: string; meeting_id: number | null; data: Record<string, unknown> }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? `Request failed (${response.status})`)
  }
  return response.json()
}

export const api = {
  meetings: () => call<ApiMeeting[]>("/meetings"),
  meeting: (id: number) => call<ApiMeetingDetail>(`/meetings/${id}`),
  dispatch: (body: DispatchRequest) =>
    call<{ id: number; bot_id: string; status: string }>("/meetings/dispatch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  stop: (id: number) => call<{ ok: boolean }>(`/meetings/${id}/stop`, { method: "POST" }),
  resendRecap: (id: number) => call<ApiMeetingDetail>(`/meetings/${id}/recap`, { method: "POST" }),
  records: () => call<ApiRecord[]>("/records"),
  outbox: () => call<OutboxItem[]>("/outbox"),
  outboxItem: (id: number) => call<OutboxItem>(`/outbox/${id}`),
}

/** Subscribe to the backend's live event stream. The browser's EventSource reconnects on its own. */
export function useAmberEvents(onEvent: (event: AmberEvent) => void) {
  const handler = useRef(onEvent)
  handler.current = onEvent
  useEffect(() => {
    const source = new EventSource("/api/events")
    source.onmessage = (message) => {
      try {
        handler.current(JSON.parse(message.data))
      } catch {
        // ignore a malformed frame; the next event triggers a refetch anyway
      }
    }
    return () => source.close()
  }, [])
}

export const LIVE_STATUSES = new Set([
  "queued", "joining", "joining_call", "in_waiting_room", "in_call_not_recording", "in_call_recording", "replay",
])
export const isLive = (status: MeetingStatus) => LIVE_STATUSES.has(status)

export const statusLabel = (status: MeetingStatus) =>
  ({
    queued: "Queued",
    joining: "Joining",
    joining_call: "Joining",
    in_waiting_room: "Waiting to be admitted",
    in_call_not_recording: "In call",
    in_call_recording: "Live",
    replay: "Live (replay)",
    call_ended: "Call ended",
    done: "Processing",
    ended: "Processing",
    processing: "Writing recap",
    completed: "Completed",
    failed: "Failed",
    fatal: "Failed",
  })[status] ?? status

export const timeOf = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "-"

export const toBase64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "")
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })

/** Backend meeting -> the dashboard's existing ScheduledMeet shape (ids prefixed "api-"). */
export function toScheduledMeet(m: ApiMeeting): ScheduledMeet {
  const start = m.started_at ?? m.created_at
  const minutes =
    m.ended_at && start ? Math.max(1, Math.round((Date.parse(m.ended_at) - Date.parse(start)) / 60000)) : null
  const [workspaceId, categoryId] = (m.series_id ?? "").split(":") // dashboard dispatches use "workspace:category"
  return {
    id: `api-${m.id}`,
    workspaceId: workspaceId || undefined,
    categoryId: categoryId || undefined,
    title: m.title,
    time: timeOf(m.created_at),
    duration: isLive(m.status) ? "Live" : minutes ? `${minutes} min` : "-",
    type: statusLabel(m.status),
    status: isLive(m.status) ? "upcoming" : "ended",
    link: m.url,
  }
}

export const apiDateKey = (m: ApiMeeting) => dateKey(new Date(m.created_at))

const TASK_STATUS: Record<string, "Completed" | "In progress" | "Started" | "Ongoing"> = {
  done: "Completed",
  in_progress: "In progress",
  open: "Started",
  blocked: "Ongoing",
}

/** Full backend meeting -> ScheduledMeet with `review`, for the existing MeetingDetail view. */
export function toReviewMeet(d: ApiMeetingDetail): ScheduledMeet {
  return {
    ...toScheduledMeet(d),
    review: {
      summary: d.mom?.executive_summary,
      decisions: d.mom?.decisions ?? [],
      openQuestions: d.mom?.open_questions ?? [],
      agenda: d.mom?.agenda_alignment ?? [],
      recordUpdates: d.record_notes.map((n) => `${n.record_id}: ${n.note}`),
      participants: d.participants.map((p) => ({ name: p.name, joined: timeOf(p.joined_at), left: timeOf(p.left_at) })),
      chat: d.chat.map((c) => ({ sender: c.sender, time: timeOf(c.ts), message: c.text, isAmber: Boolean(c.is_amber) })),
      tasks: d.tasks.map((t) => ({
        title: t.title,
        assignee: [t.owner, t.due_at && `due ${t.due_at}`].filter(Boolean).join(" · ") || "Unassigned",
        status: TASK_STATUS[t.status] ?? "Started",
      })),
      recordingUrl: d.recording_url ?? undefined,
    },
  }
}
