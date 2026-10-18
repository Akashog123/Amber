// Records (the mock procurement log + equipment list Amber writes to) and the per-meeting email outbox.
import { useCallback, useEffect, useState } from "react"
import { Boxes, Mail, PencilLine, RefreshCw, Trash2 } from "lucide-react"
import { api, timeOf, useAmberEvents, type ApiRecord, type ApiRecordNote, type OutboxItem } from "../api"

const card = "rounded-2xl border border-[#dce5f2] bg-white shadow-[0_8px_24px_rgba(43,67,114,0.05)]"

function PageHeader({ icon: Icon, title, subtitle, onRefresh }: {
  icon: typeof Boxes
  title: string
  subtitle: string
  onRefresh: () => void
}) {
  return (
    <div className="mb-5 flex items-end justify-between gap-4 pt-4">
      <div className="flex items-center gap-3">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-[#eaf2ff] text-[#3479f5]">
          <Icon className="h-6 w-6" />
        </span>
        <div>
          <h2 className="text-2xl font-extrabold tracking-[-0.03em]">{title}</h2>
          <p className="mt-0.5 text-sm text-[#758199]">{subtitle}</p>
        </div>
      </div>
      <button
        className="flex items-center gap-2 rounded-full border border-[#bfd0e7] px-4 py-2 text-sm font-bold text-[#3479f5] hover:bg-[#eef4ff]"
        type="button"
        onClick={onRefresh}
      >
        <RefreshCw className="h-4 w-4" /> Refresh
      </button>
    </div>
  )
}

export function RecordsPage() {
  const [records, setRecords] = useState<ApiRecord[]>([])
  const [error, setError] = useState("")
  const load = useCallback(() => {
    api.records().then(setRecords).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])
  useAmberEvents((e) => e.type.startsWith("record.") && load())

  return (
    <div className="mx-auto mt-5 w-full max-w-[1240px] px-5 pb-8 md:px-8 xl:px-10">
      <PageHeader icon={Boxes} title="Records" subtitle="Procurement log and equipment list. Amber adds meeting notes here and reads them in later meetings." onRefresh={load} />
      {error && <p className="mb-3 text-sm font-semibold text-[#c94848]">{error}</p>}
      <div className="space-y-3">
        {records.map((r) => (
          <RecordCard key={r.id} record={r} onChanged={load} />
        ))}
      </div>
    </div>
  )
}

type RecordFields = Pick<ApiRecord, "name" | "status" | "owner" | "details" | "aliases">

// label, field, required, max length (same caps as the backend), multi-line, hint
const RECORD_INPUTS: [string, keyof RecordFields, boolean, number, boolean, string?][] = [
  ["Name", "name", true, 200, false],
  ["Status", "status", true, 200, false],
  ["Owner", "owner", false, 100, false],
  ["Details", "details", false, 2000, true],
  ["Other names", "aliases", false, 500, false, "Comma-separated names people say in meetings, so Amber can match them"],
]

/** A record with its meeting notes. The record's own fields edit in place; its id never changes. */
function RecordCard({ record: r, onChanged }: { record: ApiRecord; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<RecordFields>(r)
  const [base, setBase] = useState<RecordFields>(r) // what the form opened with
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const missing = RECORD_INPUTS.find(([, key, required]) => required && !draft[key]?.trim())

  const save = async () => {
    setBusy(true)
    setError("")
    try {
      // Only fields the operator changed, so a status Amber set meanwhile isn't overwritten with the old one.
      const changed = RECORD_INPUTS.map(([, key]) => key).filter((key) => (draft[key] ?? "") !== (base[key] ?? ""))
      if (changed.length) await api.editRecord(r.id, Object.fromEntries(changed.map((key) => [key, draft[key] ?? ""])))
      setEditing(false)
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`${card} p-4`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-lg bg-[#f1f4f8] px-2 py-1 font-mono text-xs font-bold text-[#43516c]">{r.id}</span>
        {!editing && (
          <>
            <span className="font-bold text-[#19233f]">{r.name}</span>
            <span className="ml-auto rounded-full bg-[#eef4ff] px-2.5 py-1 text-xs font-semibold text-[#4974ce]">{r.status}</span>
            <button
              className="grid h-7 w-7 place-items-center rounded-lg text-[#8a96aa] transition hover:bg-[#f1f4f8] hover:text-[#3479f5]"
              type="button"
              title="Edit record"
              aria-label={`Edit ${r.id}`}
              onClick={() => {
                setDraft(r)
                setBase(r)
                setError("")
                setEditing(true)
              }}
            >
              <PencilLine className="h-4 w-4" />
            </button>
          </>
        )}
      </div>
      {editing ? (
        <div
          className="mt-3 grid gap-3 sm:grid-cols-2"
          onKeyDown={(e) => {
            if (e.key === "Escape") setEditing(false)
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !missing) void save()
          }}
        >
          {RECORD_INPUTS.map(([label, key, required, max, multiline, hint]) => {
            const props = {
              className:
                "mt-1.5 w-full rounded-lg border border-[#cbd6e6] bg-white px-3 py-2 text-sm outline-none focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10",
              value: draft[key] ?? "",
              maxLength: max,
              onChange: (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value })),
            }
            return (
              <label key={key} className={multiline || hint ? "sm:col-span-2" : ""}>
                <span className="text-xs font-bold text-[#34415d]">
                  {label}
                  {!required && <span className="font-normal text-[#8792a8]"> (optional)</span>}
                </span>
                {multiline ? <textarea {...props} rows={3} /> : <input {...props} autoFocus={key === "name"} />}
                {hint && <span className="mt-1 block text-xs text-[#8792a8]">{hint}</span>}
              </label>
            )
          })}
          <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
            <span className="text-xs font-semibold text-[#c94848]">
              {error || (missing ? `${missing[0]} can't be empty.` : "")}
            </span>
            <button
              className="ml-auto rounded-full bg-[#eff3fa] px-4 py-1.5 text-xs font-bold text-[#43516c]"
              type="button"
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              className="rounded-full bg-[#3479f5] px-4 py-1.5 text-xs font-bold text-white disabled:opacity-50"
              type="button"
              onClick={() => void save()}
              disabled={busy || Boolean(missing)}
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-xs text-[#66738b]">
          {r.kind}
          {r.owner && <> · owner {r.owner}</>}
          {r.details && <> · {r.details}</>}
        </p>
      )}
      {r.notes.length > 0 && (
        <div className="mt-3 space-y-1.5 border-t border-[#edf0f4] pt-3">
          {r.notes.map((n) => (
            <NoteRow key={n.id} note={n} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  )
}

const NOTE_MAX = 2000 // same cap as the backend

/** One meeting note on a record: view, edit in place, or delete after an inline confirm. */
function NoteRow({ note: n, onChanged }: { note: ApiRecordNote; onChanged: () => void }) {
  const [mode, setMode] = useState<"view" | "edit" | "confirm">("view")
  const [draft, setDraft] = useState(n.note)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const text = draft.trim()

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError("")
    try {
      await action()
      setMode("view")
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const save = () => {
    if (text === n.note) return setMode("view")
    if (text) void run(() => api.editNote(n.record_id, n.id, text))
  }

  const tag = (
    <span className="mr-2 rounded-full bg-[#edf7f1] px-2 py-0.5 text-[11px] font-bold text-[#2c8d61]">
      meeting #{n.meeting_id} · {timeOf(n.ts)}
      {n.edited_at && <span className="font-semibold text-[#6f8f80]"> · edited</span>}
    </span>
  )
  const iconButton = "grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[#8a96aa] transition hover:bg-[#f1f4f8]"

  if (mode === "edit")
    return (
      <div className="rounded-xl border border-[#cfdcf0] bg-[#f8fbff] p-3">
        <div className="mb-2">{tag}</div>
        <textarea
          className="min-h-[72px] w-full resize-y rounded-lg border border-[#cbd6e6] bg-white px-3 py-2 text-sm outline-none focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
          value={draft}
          maxLength={NOTE_MAX}
          autoFocus
          aria-label={`Edit note on ${n.record_id}`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setMode("view")
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save()
          }}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-xs text-[#8792a8]">
            {text ? "Ctrl+Enter to save · Esc to cancel" : "A note can't be empty. Delete it instead."}
          </span>
          {error && <span className="text-xs font-semibold text-[#c94848]">{error}</span>}
          <button
            className="ml-auto rounded-full bg-[#eff3fa] px-4 py-1.5 text-xs font-bold text-[#43516c]"
            type="button"
            onClick={() => setMode("view")}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            className="rounded-full bg-[#3479f5] px-4 py-1.5 text-xs font-bold text-white disabled:opacity-50"
            type="button"
            onClick={save}
            disabled={busy || !text}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    )

  return (
    <div className="group flex items-start gap-2">
      <p className="min-w-0 flex-1 text-sm text-[#34415d]">
        {tag}
        {n.note}
      </p>
      {mode === "confirm" ? (
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs font-semibold text-[#c04d4d]">{error || "Delete this note?"}</span>
          <button
            className="rounded-full bg-[#c94848] px-3 py-1 text-xs font-bold text-white disabled:opacity-50"
            type="button"
            onClick={() => void run(() => api.deleteNote(n.record_id, n.id))}
            disabled={busy}
          >
            {busy ? "Deleting…" : "Delete"}
          </button>
          <button
            className="rounded-full bg-[#eff3fa] px-3 py-1 text-xs font-bold text-[#43516c]"
            type="button"
            onClick={() => setMode("view")}
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex shrink-0 gap-1 opacity-60 transition group-hover:opacity-100 focus-within:opacity-100">
          <button
            className={`${iconButton} hover:text-[#3479f5]`}
            type="button"
            title="Edit note"
            aria-label={`Edit note on ${n.record_id}`}
            onClick={() => {
              setDraft(n.note)
              setError("")
              setMode("edit")
            }}
          >
            <PencilLine className="h-3.5 w-3.5" />
          </button>
          <button
            className={`${iconButton} hover:text-[#c94848]`}
            type="button"
            title="Delete note"
            aria-label={`Delete note on ${n.record_id}`}
            onClick={() => {
              setError("")
              setMode("confirm")
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}

const statusColor: Record<string, string> = {
  sent: "bg-[#edf7f1] text-[#2c8d61]",
  failed: "bg-[#fff1f1] text-[#c04d4d]",
  skipped: "bg-[#f1f4f8] text-[#66738b]",
}

function OutboxRow({ item: o, active, onOpen }: { item: OutboxItem; active: boolean; onOpen: () => void }) {
  return (
    <button
      className={`${card} block w-full p-3.5 text-left transition hover:border-[#b9cbea] ${active ? "border-[#3479f5]" : ""}`}
      type="button"
      onClick={onOpen}
    >
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-[#eef4ff] px-2 py-0.5 text-[11px] font-bold uppercase text-[#4974ce]">{o.kind}</span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${statusColor[o.status] ?? ""}`}>{o.status}</span>
        <span className="ml-auto text-[11px] text-[#9aa5b7]">{timeOf(o.ts)}</span>
      </div>
      <p className="mt-2 truncate text-sm font-bold text-[#19233f]">{o.subject}</p>
      <p className="mt-0.5 truncate text-xs text-[#7a869b]">to {o.to_addr || "nobody"}</p>
      {o.error && <p className="mt-1 truncate text-xs text-[#c04d4d]">{o.error}</p>}
    </button>
  )
}

/** The follow-ups (recap, reminders) Amber sent for one meeting; click one to preview it inline. */
export function MeetingOutbox({ meetingId }: { meetingId: number }) {
  const [items, setItems] = useState<OutboxItem[]>([])
  const [open, setOpen] = useState<OutboxItem | null>(null)
  const [error, setError] = useState("")
  const load = useCallback(() => {
    api.outbox(meetingId).then(setItems).catch((e) => setError(e.message))
  }, [meetingId])
  useEffect(load, [load])
  useAmberEvents((e) => e.meeting_id === meetingId && (e.type === "meeting.recap" || e.type === "task.reminded") && load())

  return (
    <div className="space-y-2">
      {error && <p className="text-sm font-semibold text-[#c94848]">{error}</p>}
      {items.length === 0 && (
        <p className="rounded-2xl bg-[#f5f7fa] px-4 py-6 text-center text-sm text-[#7a869b]">No follow-ups sent yet.</p>
      )}
      {items.map((o) => (
        <div key={o.id}>
          <OutboxRow item={o} active={open?.id === o.id}
            onOpen={() => open?.id === o.id ? setOpen(null) : api.outboxItem(o.id).then(setOpen).catch((e) => setError(e.message))} />
          {open?.id === o.id && (
            <iframe className={`${card} mt-2 h-[420px] w-full`} sandbox="" srcDoc={open.html} title={open.subject} />
          )}
        </div>
      ))}
    </div>
  )
}
