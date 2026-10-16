// Live view of one Amber session: status, transcript, what Amber is doing, tasks and record notes as they appear.
import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowLeft, Bot, CircleStop, ClipboardList, FileText, MessageSquareText, UsersRound } from "lucide-react"
import { api, isLive, statusLabel, timeOf, useAmberEvents, type AmberEvent, type ApiMeetingDetail } from "../api"

type Activity = { id: number; at: string; kind: string; text: string; detail?: string }

const card = "rounded-2xl border border-[#dce5f2] bg-white p-4 shadow-[0_8px_24px_rgba(43,67,114,0.05)]"

function describe(event: AmberEvent): Omit<Activity, "id" | "at"> | null {
  const d = event.data as Record<string, any>
  switch (event.type) {
    case "amber.filler":
      return { kind: "filler", text: `“${d.text}”`, detail: "instant acknowledgement" }
    case "amber.reply": {
      const l = d.latency ?? {}
      return {
        kind: "reply",
        text: d.text,
        detail: `to ${d.to} · ${d.via} · model ${l.llm}s + voice ${l.tts}s`,
      }
    }
    case "amber.yielded":
      return { kind: "yield", text: "Stopped talking: someone started speaking" }
    case "amber.cancelled":
      return { kind: "yield", text: `${d.speaker} withdrew the question` }
    case "amber.error":
      return { kind: "error", text: "Couldn't answer", detail: String(d.error ?? "") }
    case "confirmation.asked":
      return { kind: "ask", text: String(d.question), detail: "waiting for a reply in chat" }
    case "confirmation.resolved":
      return { kind: "note", text: d.chosen ? `Confirmed by ${d.by}: ${d.chosen}` : `${d.by}: no record update` }
    case "record.noted":
      return { kind: "note", text: `${d.record_id}: ${d.note}`, detail: `confidence ${Number(d.confidence).toFixed(2)}` }
    case "task.created":
      return { kind: "task", text: `${d.owner ?? "Someone"}: ${d.title}`, detail: d.due ? `due ${d.due}` : undefined }
    case "task.updated":
      return { kind: "task", text: `Task #${d.task_id} → ${d.status}`, detail: d.note ?? undefined }
    default:
      return null
  }
}

const badge: Record<string, string> = {
  filler: "bg-[#f1f4f8] text-[#53617a]",
  reply: "bg-[#e9f1ff] text-[#3479f5]",
  ask: "bg-[#fff4db] text-[#ad7300]",
  note: "bg-[#edf7f1] text-[#2c8d61]",
  task: "bg-[#f0edff] text-[#6a62e8]",
  yield: "bg-[#f1f4f8] text-[#53617a]",
  error: "bg-[#fff1f1] text-[#c04d4d]",
}

export default function LiveMeeting({
  meetingId,
  onBack,
  onOpenRecap,
}: {
  meetingId: number
  onBack: () => void
  onOpenRecap: (meeting: ApiMeetingDetail) => void
}) {
  const [meeting, setMeeting] = useState<ApiMeetingDetail | null>(null)
  const [activity, setActivity] = useState<Activity[]>([])
  const [error, setError] = useState("")
  const [stopping, setStopping] = useState(false)
  const refetchTimer = useRef<number | undefined>(undefined)
  const transcriptEnd = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    api.meeting(meetingId).then(setMeeting).catch((e) => setError(e.message))
  }, [meetingId])

  useEffect(load, [load])

  useAmberEvents((event) => {
    if (event.meeting_id !== meetingId) return
    const item = describe(event)
    if (item) setActivity((current) => [{ ...item, id: Date.now() + Math.random(), at: new Date().toISOString() }, ...current].slice(0, 60))
    window.clearTimeout(refetchTimer.current)
    refetchTimer.current = window.setTimeout(load, 250) // coalesce bursts of events into one refetch
  })

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: "end" })
  }, [meeting?.transcript.length])

  const stop = async () => {
    setStopping(true)
    try {
      await api.stop(meetingId)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setStopping(false)
    }
  }

  if (!meeting) {
    return (
      <div className="mx-auto mt-10 w-full max-w-[1240px] px-5 text-sm text-[#7a869b]">
        {error || "Loading Amber's session…"}
      </div>
    )
  }

  const live = isLive(meeting.status)
  const done = meeting.status === "completed"

  return (
    <div className="mx-auto mt-5 flex w-full max-w-[1240px] flex-1 flex-col gap-4 px-5 pb-8 md:px-8 xl:px-10">
      <div className={`${card} flex flex-wrap items-center gap-3`}>
        <button
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#f1f4f8] text-[#53617a] hover:bg-[#e5eaf1]"
          type="button"
          onClick={onBack}
          aria-label="Back to meetings"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-xl font-extrabold tracking-[-0.025em] md:text-2xl">{meeting.title}</h2>
          <p className="mt-0.5 truncate text-xs text-[#7a869b]">
            {meeting.platform.replace("_", " ")} · {meeting.url}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold ${
            live ? "bg-[#edf7f1] text-[#2c8d61]" : done ? "bg-[#eef4ff] text-[#4974ce]" : "bg-[#fff4db] text-[#ad7300]"
          }`}
        >
          {live && <span className="h-2 w-2 animate-pulse rounded-full bg-[#2c8d61]" />}
          {statusLabel(meeting.status)}
        </span>
        {live ? (
          <button
            className="flex items-center gap-2 rounded-full border border-[#f0c4c4] px-4 py-2 text-sm font-bold text-[#c04d4d] hover:bg-[#fff5f5] disabled:opacity-50"
            type="button"
            onClick={stop}
            disabled={stopping}
          >
            <CircleStop className="h-4 w-4" /> {stopping ? "Stopping…" : "Stop Amber"}
          </button>
        ) : done ? (
          <button
            className="flex items-center gap-2 rounded-full bg-[#3479f5] px-4 py-2 text-sm font-bold text-white hover:bg-[#2068e7]"
            type="button"
            onClick={() => onOpenRecap(meeting)}
          >
            <FileText className="h-4 w-4" /> View recap
          </button>
        ) : null}
      </div>
      {error && <p className="text-sm font-semibold text-[#c94848]">{error}</p>}

      <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section className={`${card} flex max-h-[70vh] min-h-[420px] flex-col`}>
          <h3 className="flex items-center gap-2 text-sm font-extrabold text-[#34415d]">
            <MessageSquareText className="h-4 w-4 text-[#3479f5]" /> Live transcript
          </h3>
          <div className="mt-3 min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
            {meeting.transcript.length === 0 && (
              <p className="rounded-xl bg-[#f5f7fa] px-4 py-6 text-center text-sm text-[#7a869b]">
                {live ? "Waiting for someone to speak…" : "No transcript."}
              </p>
            )}
            {meeting.transcript.map((line, index) => {
              const amber = line.speaker === "Amber"
              return (
                <div key={index} className={`flex gap-3 ${amber ? "flex-row-reverse" : ""}`}>
                  <span
                    className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-[11px] font-extrabold ${
                      amber ? "bg-[#3479f5] text-white" : "bg-[#e8edf4] text-[#526079]"
                    }`}
                  >
                    {amber ? "A" : line.speaker.split(" ").map((p) => p[0]).join("").slice(0, 2)}
                  </span>
                  <div className={`max-w-[85%] ${amber ? "text-right" : ""}`}>
                    <p className="text-[11px] font-bold text-[#7a869b]">
                      {line.speaker}
                      {line.addressed ? <span className="ml-2 text-[#3479f5]">asked Amber</span> : null}
                    </p>
                    <p
                      className={`mt-1 rounded-2xl px-3.5 py-2.5 text-left text-sm leading-5 ${
                        amber ? "rounded-tr-md bg-[#e9f1ff] text-[#273653]" : "rounded-tl-md bg-[#f1f4f8] text-[#43516c]"
                      }`}
                    >
                      {line.text}
                    </p>
                  </div>
                </div>
              )
            })}
            <div ref={transcriptEnd} />
          </div>
        </section>

        <div className="flex min-w-0 flex-col gap-4">
          <section className={card}>
            <h3 className="flex items-center gap-2 text-sm font-extrabold text-[#34415d]">
              <Bot className="h-4 w-4 text-[#3479f5]" /> Amber activity
            </h3>
            <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
              {activity.length === 0 && <p className="text-xs text-[#8792a8]">Amber's replies, notes and questions appear here.</p>}
              {activity.map((a) => (
                <div key={a.id} className="rounded-xl border border-[#edf0f4] p-2.5">
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-extrabold uppercase ${badge[a.kind]}`}>{a.kind}</span>
                    <span className="text-[10px] text-[#9aa5b7]">{timeOf(a.at)}</span>
                  </div>
                  <p className="mt-1.5 text-xs leading-5 text-[#34415d]">{a.text}</p>
                  {a.detail && <p className="mt-0.5 text-[11px] text-[#8792a8]">{a.detail}</p>}
                </div>
              ))}
            </div>
          </section>

          <section className={card}>
            <h3 className="flex items-center gap-2 text-sm font-extrabold text-[#34415d]">
              <ClipboardList className="h-4 w-4 text-[#6a62e8]" /> Tasks & record notes
            </h3>
            <div className="mt-3 space-y-2">
              {meeting.tasks.map((t) => (
                <div key={t.id} className="rounded-xl bg-[#f7f6ff] px-3 py-2 text-xs">
                  <p className="font-bold text-[#273653]">{t.title}</p>
                  <p className="mt-0.5 text-[#6b7690]">
                    {t.owner ?? "Unassigned"} {t.due_at && `· due ${t.due_at}`} · {t.status.replace("_", " ")}
                  </p>
                </div>
              ))}
              {meeting.record_notes.map((n) => (
                <div key={n.id} className="rounded-xl bg-[#f2faf5] px-3 py-2 text-xs">
                  <p className="font-bold text-[#27815a]">{n.record_id}</p>
                  <p className="mt-0.5 text-[#43516c]">{n.note}</p>
                </div>
              ))}
              {meeting.tasks.length + meeting.record_notes.length === 0 && (
                <p className="text-xs text-[#8792a8]">Commitments and record updates are picked up every few lines.</p>
              )}
            </div>
          </section>

          <section className={card}>
            <h3 className="flex items-center gap-2 text-sm font-extrabold text-[#34415d]">
              <UsersRound className="h-4 w-4 text-[#3479f5]" /> In the call ({meeting.participants.filter((p) => !p.left_at).length})
            </h3>
            <div className="mt-3 space-y-1.5 text-xs">
              {meeting.participants.map((p, i) => (
                <p key={i} className="flex justify-between gap-2 text-[#43516c]">
                  <span className="truncate font-semibold">{p.name}</span>
                  <span className="shrink-0 text-[#8792a8]">
                    {timeOf(p.joined_at)} – {p.left_at ? timeOf(p.left_at) : "now"}
                  </span>
                </p>
              ))}
              {meeting.participants.length === 0 && <p className="text-[#8792a8]">Nobody has joined yet.</p>}
            </div>
            {meeting.chat.length > 0 && (
              <div className="mt-4 space-y-1.5 border-t border-[#edf0f4] pt-3 text-xs">
                {meeting.chat.slice(-6).map((c, i) => (
                  <p key={i} className="text-[#43516c]">
                    <span className={`font-bold ${c.is_amber ? "text-[#3479f5]" : ""}`}>{c.sender}:</span> {c.text}
                  </p>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
