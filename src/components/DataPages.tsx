// Records (the mock procurement log + equipment list Amber writes to) and the email outbox.
import { useCallback, useEffect, useState } from "react"
import { Boxes, Mail, RefreshCw } from "lucide-react"
import { api, timeOf, useAmberEvents, type ApiRecord, type OutboxItem } from "../api"

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
  useAmberEvents((e) => e.type === "record.noted" && load())

  return (
    <div className="mx-auto mt-5 w-full max-w-[1240px] px-5 pb-8 md:px-8 xl:px-10">
      <PageHeader icon={Boxes} title="Records" subtitle="Procurement log and equipment list. Amber adds meeting notes here." onRefresh={load} />
      {error && <p className="mb-3 text-sm font-semibold text-[#c94848]">{error}</p>}
      <div className="space-y-3">
        {records.map((r) => (
          <div key={r.id} className={`${card} p-4`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-lg bg-[#f1f4f8] px-2 py-1 font-mono text-xs font-bold text-[#43516c]">{r.id}</span>
              <span className="font-bold text-[#19233f]">{r.name}</span>
              <span className="ml-auto rounded-full bg-[#eef4ff] px-2.5 py-1 text-xs font-semibold text-[#4974ce]">{r.status}</span>
            </div>
            <p className="mt-2 text-xs text-[#66738b]">
              {r.kind} · owner {r.owner} · {r.details}
            </p>
            {r.notes.length > 0 && (
              <div className="mt-3 space-y-1.5 border-t border-[#edf0f4] pt-3">
                {r.notes.map((n) => (
                  <p key={n.id} className="text-sm text-[#34415d]">
                    <span className="mr-2 rounded-full bg-[#edf7f1] px-2 py-0.5 text-[11px] font-bold text-[#2c8d61]">
                      meeting #{n.meeting_id} · {timeOf(n.ts)}
                    </span>
                    {n.note}
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

const statusColor: Record<string, string> = {
  sent: "bg-[#edf7f1] text-[#2c8d61]",
  failed: "bg-[#fff1f1] text-[#c04d4d]",
  skipped: "bg-[#f1f4f8] text-[#66738b]",
}

export function OutboxPage() {
  const [items, setItems] = useState<OutboxItem[]>([])
  const [open, setOpen] = useState<OutboxItem | null>(null)
  const [error, setError] = useState("")
  const load = useCallback(() => {
    api.outbox().then(setItems).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])
  useAmberEvents((e) => (e.type === "meeting.recap" || e.type === "task.reminded") && load())

  return (
    <div className="mx-auto mt-5 w-full max-w-[1240px] px-5 pb-8 md:px-8 xl:px-10">
      <PageHeader icon={Mail} title="Outbox" subtitle="Every recap and reminder Amber sent, or tried to." onRefresh={load} />
      {error && <p className="mb-3 text-sm font-semibold text-[#c94848]">{error}</p>}
      <div className="grid gap-4 lg:grid-cols-[420px_minmax(0,1fr)]">
        <div className="space-y-2">
          {items.length === 0 && <p className="text-sm text-[#7a869b]">No emails yet. Recaps go out when a meeting ends.</p>}
          {items.map((o) => (
            <button
              key={o.id}
              className={`${card} block w-full p-3.5 text-left transition hover:border-[#b9cbea] ${open?.id === o.id ? "border-[#3479f5]" : ""}`}
              type="button"
              onClick={() => api.outboxItem(o.id).then(setOpen).catch((e) => setError(e.message))}
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
          ))}
        </div>
        <div className={`${card} min-h-[420px] overflow-hidden`}>
          {open ? (
            // Sandboxed: the email HTML is rendered without scripts or same-origin access.
            <iframe className="h-[70vh] w-full" sandbox="" srcDoc={open.html} title={open.subject} />
          ) : (
            <p className="p-6 text-sm text-[#7a869b]">Select an email to preview it.</p>
          )}
        </div>
      </div>
    </div>
  )
}
