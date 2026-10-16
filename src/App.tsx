import { useEffect, useRef, useState } from "react"
import {
  api,
  apiDateKey,
  isLive,
  statusLabel,
  toBase64,
  toReviewMeet,
  toScheduledMeet,
  useAmberEvents,
  type ApiMeeting,
} from "./api"
import LiveMeeting from "./components/LiveMeeting"
import { OutboxPage, RecordsPage } from "./components/DataPages"
import type { ScheduledMeet } from "./types"
import {
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Code2,
  FileText,
  FileCheck2,
  ExternalLink,
  Link2,
  ListChecks,
  Maximize2,
  Menu,
  MessageSquareText,
  Minimize2,
  MoreHorizontal,
  Palette,
  PencilLine,
  Plus,
  Save,
  Settings,
  Trash2,
  Upload,
  UserRound,
  UsersRound,
  Video,
  X,
} from "lucide-react"

const meetingTypes = [
  { name: "Physical AI Meet", icon: UsersRound },
  { name: "Documentation Meet", icon: FileText },
  { name: "Developer Meet", icon: Code2 },
  { name: "Design Review", icon: Palette },
  { name: "Product Meeting", icon: ListChecks },
  { name: "Client Meeting", icon: UserRound },
  { name: "Team Sync", icon: UsersRound },
  { name: "Interview / Hiring", icon: BriefcaseBusiness },
  { name: "Custom", icon: MoreHorizontal },
]

const getToday = () => {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

const dateKey = (date: Date) =>
  [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-")

const sameDay = (first: Date, second: Date) =>
  dateKey(first) === dateKey(second)

const addDays = (date: Date, amount: number) => {
  const next = new Date(date)
  next.setDate(next.getDate() + amount)
  return next
}

const startOfWeek = (date: Date) => addDays(date, -date.getDay())

const calendarDays = (month: Date) => {
  const first = new Date(month.getFullYear(), month.getMonth(), 1)
  const start = addDays(first, -first.getDay())
  return Array.from({ length: 42 }, (_, index) => addDays(start, index))
}

type ScheduleDraft = {
  title: string
  workspaceId: string
  categoryId: string
  link: string
  startDate: string
  time: string
  duration: string
  recurrence: "once" | "daily" | "weekdays" | "weekly" | "monthly"
  occurrences: number
}

type Workspace = {
  id: string
  name: string
  categories: {
    id: string
    name: string
    agenda?: string
  }[]
}

type StoredMeeting = {
  id: string
  workspaceId: string
  categoryId: string
  name: string
  link: string
  agenda: string
  fileName: string
  fileId?: string
  fileSize?: number
  fileType?: string
  createdAt: string
}

type UserProfile = {
  name: string
  email: string
  personality: string
  timezone: string
  defaultWorkspaceId: string
  emailSummaries: boolean
}

type NewMeetDraft = {
  title: string
  company: string
  context: string
  timing: "today" | "schedule" | "recurring"
  startDate: string
  time: string
  timezone: string
  duration: string
  frequency: "daily" | "weekdays" | "weekly" | "monthly"
  occurrences: number
}

const initialWorkspaces: Workspace[] = []

const demoEndedMeeting: ScheduledMeet = {
  id: "amber-demo-ended-meeting",
  title: "Amber product review",
  time: "3:00 PM",
  duration: "45 min",
  type: "Product Meeting",
  status: "ended",
  review: {
    summary:
      "The team reviewed the latest Amber meeting workflow, aligned on a simpler agenda experience, and agreed to prioritize reliability and clear next actions.",
    takeaways: [
      "Keep meeting preparation focused on one daily agenda.",
      "Make uploaded context easy to preview and reopen.",
      "Use clear ownership for every follow-up task.",
    ],
    decision:
      "Ship the refined agenda and document-preview flow in the next product iteration.",
    participants: [
      { name: "Alex Morgan", joined: "3:00 PM", left: "3:45 PM" },
      { name: "Maya Chen", joined: "3:01 PM", left: "3:44 PM" },
      { name: "Noah Williams", joined: "3:03 PM", left: "3:45 PM" },
    ],
    chat: [
      {
        sender: "Maya Chen",
        time: "3:12 PM",
        message: "The simplified agenda flow feels much easier to understand.",
      },
      {
        sender: "Amber",
        time: "3:31 PM",
        message:
          "I captured the preview reliability discussion as a follow-up.",
        isAmber: true,
      },
    ],
    tasks: [
      {
        title: "Review document preview behavior on mobile",
        assignee: "Alex Morgan",
        status: "In progress",
      },
      {
        title: "Finalize agenda empty-state copy",
        assignee: "Maya Chen",
        status: "Completed",
      },
      {
        title: "Validate the completed-meeting review flow",
        assignee: "Noah Williams",
        status: "Started",
      },
    ],
  },
}

const demoMeetingDate = dateKey(addDays(getToday(), -1))
const dateDetails: Record<string, ScheduledMeet[]> = {
  [demoMeetingDate]: [demoEndedMeeting],
}

const MAX_DOCUMENT_SIZE = 10 * 1024 * 1024

const formatFileSize = (bytes?: number) => {
  if (!bytes) return ""
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const openDocumentDatabase = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("amber-documents", 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("files")) {
        request.result.createObjectStore("files")
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })

const storeDocument = async (file: File) => {
  const id = `document-${Date.now()}-${crypto.randomUUID()}`
  const database = await openDocumentDatabase()
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction("files", "readwrite")
    transaction.objectStore("files").put(file, id)
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
  })
  database.close()
  return id
}

const getStoredDocument = async (fileId: string) => {
  const database = await openDocumentDatabase()
  const file = await new Promise<File | undefined>((resolve, reject) => {
    const request = database
      .transaction("files", "readonly")
      .objectStore("files")
      .get(fileId)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  database.close()
  return file
}

const openStoredDocument = async (fileId: string) => {
  const preview = window.open("about:blank", "_blank")
  if (preview) {
    preview.opener = null
    preview.document.title = "Opening document…"
    preview.document.body.textContent = "Opening your Amber document…"
  }
  const file = await getStoredDocument(fileId)
  if (!file) {
    preview?.close()
    throw new Error("Document not found")
  }
  const url = URL.createObjectURL(file)
  if (preview) preview.location.href = url
  else window.open(url, "_blank", "noopener,noreferrer")
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

function PdfPreview({
  fileId,
  name,
  onRemove,
}: {
  fileId?: string
  name: string
  onRemove: () => void
}) {
  const [url, setUrl] = useState("")
  const [unavailable, setUnavailable] = useState(false)
  const isPdf = name.toLowerCase().endsWith(".pdf")

  useEffect(() => {
    if (!fileId || !isPdf) return
    let objectUrl = ""
    let active = true
    void getStoredDocument(fileId)
      .then((file) => {
        if (!active || !file) {
          if (active) setUnavailable(true)
          return
        }
        objectUrl = URL.createObjectURL(file)
        setUrl(objectUrl)
        setUnavailable(false)
      })
      .catch(() => {
        if (active) setUnavailable(true)
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [fileId, isPdf])

  if (!isPdf) return null
  if (unavailable)
    return (
      <p className="rounded-xl bg-[#fff5f5] px-4 py-3 text-center text-xs font-semibold text-[#bd4545]">
        Preview unavailable. Re-upload the PDF to view it here.
      </p>
    )
  if (!url)
    return (
      <div className="grid h-full place-items-center bg-[#f1f4f8] text-sm font-semibold text-[#74819a]">
        Preparing PDF preview…
      </div>
    )

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#eef2f7]">
      <div className="flex items-center gap-3 border-b border-[#d8e1ee] bg-white px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-left text-sm font-bold text-[#526079]">
          {name}
        </span>
        <button
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#bfd1eb] px-3 py-1.5 text-xs font-bold text-[#3479f5] hover:border-[#3479f5]"
          type="button"
          onClick={() => fileId && void openStoredDocument(fileId)}
        >
          <ExternalLink className="h-3.5 w-3.5" /> Open
        </button>
        <button
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#7b879c] hover:bg-[#fff0f0] hover:text-[#c94848]"
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${name}`}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <object
        className="min-h-0 w-full flex-1 bg-white"
        data={url}
        type="application/pdf"
        aria-label={`Preview of ${name}`}
      >
        <div className="grid h-72 place-items-center px-6 text-center">
          <div>
            <p className="text-sm font-semibold text-[#526079]">
              Your browser cannot display this PDF inline.
            </p>
            <button
              className="mt-3 rounded-full bg-[#3479f5] px-5 py-2.5 text-sm font-bold text-white"
              type="button"
              onClick={() => fileId && void openStoredDocument(fileId)}
            >
              Open PDF
            </button>
          </div>
        </div>
      </object>
    </div>
  )
}

function UploadedDocument({
  name,
  fileId,
  size,
  type,
  onRemove,
}: {
  name: string
  fileId?: string
  size?: number
  type?: string
  onRemove?: () => void
}) {
  const [message, setMessage] = useState("")
  const openFile = async () => {
    if (!fileId) {
      setMessage("Re-upload this document to open it.")
      return
    }
    try {
      await openStoredDocument(fileId)
      setMessage("")
    } catch {
      setMessage("This document is no longer available. Please re-upload it.")
    }
  }

  return (
    <div>
      <div className="flex items-center gap-3 rounded-xl border border-[#cfe0f6] bg-[#f5f9ff] p-3 text-left">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-[#3479f5] shadow-sm">
          <FileCheck2 className="h-5 w-5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-bold text-[#263653]">
            {name}
          </span>
          <span className="mt-0.5 block text-xs text-[#74819a]">
            {[
              type?.split("/").pop()?.toUpperCase(),
              formatFileSize(size),
              "Uploaded",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
        <button
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#bfd1eb] bg-white px-3 py-2 text-xs font-bold text-[#3479f5] hover:border-[#3479f5]"
          type="button"
          onClick={openFile}
        >
          <ExternalLink className="h-3.5 w-3.5" /> Open
        </button>
        {onRemove && (
          <button
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#7b879c] hover:bg-white hover:text-[#c94848]"
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${name}`}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {message && (
        <p className="mt-2 text-xs font-semibold text-[#c94848]" role="status">
          {message}
        </p>
      )}
    </div>
  )
}

function AmberLogo({ compact = false }: { compact?: boolean }) {
  return (
    <img
      className={
        compact
          ? "h-14 w-auto max-w-[170px] object-contain object-left"
          : "h-16 w-auto max-w-[205px] object-contain object-left"
      }
      src="/assets/amber-logo.svg"
      alt="Amber"
    />
  )
}

function LandingPage({ onContinue }: { onContinue: () => void }) {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#fbfdff] text-[#101a3a]">
      <div className="pointer-events-none absolute -left-48 top-24 h-[420px] w-[420px] rounded-full bg-[#eaf2ff] blur-3xl" />
      <div className="pointer-events-none absolute -right-36 bottom-0 h-[480px] w-[480px] rounded-full bg-[#eef4ff] blur-3xl" />

      <nav className="relative z-40 mx-auto flex max-w-[1220px] items-center justify-between px-6 py-5 lg:px-10">
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          aria-label="Amber home"
        >
          <AmberLogo compact />
        </button>
        <button
          className="rounded-full border border-[#c9d8ed] bg-white/80 px-5 py-2.5 text-sm font-bold text-[#2f65bd] shadow-[0_8px_22px_rgba(49,79,132,0.07)] backdrop-blur-sm transition hover:-translate-y-0.5 hover:border-[#7ca3e7]"
          type="button"
          onClick={onContinue}
        >
          Open dashboard
        </button>
      </nav>

      <section className="relative z-10 mx-auto grid min-h-[calc(100dvh-96px)] max-w-[1220px] items-center gap-4 px-6 pb-10 pt-8 lg:grid-cols-[0.92fr_1.08fr] lg:gap-10 lg:px-10 lg:pb-14 lg:pt-4">
        <div className="relative z-30 max-w-[610px]">
          {/* <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[#d6e3f7] bg-white/80 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-[#5471a5] shadow-[0_8px_24px_rgba(55,83,133,0.06)] backdrop-blur-sm">
            <span className="h-2 w-2 rounded-full bg-[#3479f5] shadow-[0_0_0_4px_rgba(52,121,245,0.12)]" />
            Your AI meeting agent
          </div> */}
          <h1 className="text-[50px] font-extrabold leading-[1.02] tracking-[-0.055em] sm:text-[66px] lg:text-[74px]">
            Stay present,{" "}
            <span className="block bg-gradient-to-r from-[#246fdc] via-[#3479f5] to-[#79a7ff] bg-clip-text text-transparent">
              remember everything.
            </span>
          </h1>
          <p className="mt-6 max-w-[560px] text-base leading-7 text-[#66738d] sm:text-lg sm:leading-8">
            Schedule Amber or paste a meeting link. Amber joins your Google
            Meet, Zoom, or Microsoft Teams call, then captures the notes,
            decisions, and next steps for you.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <button
              className="group inline-flex items-center gap-3 rounded-full bg-[#3479f5] px-7 py-4 text-base font-bold text-white shadow-[0_16px_34px_rgba(52,121,245,0.28)] transition hover:-translate-y-0.5 hover:bg-[#246cdf]"
              type="button"
              onClick={onContinue}
            >
              Start with Amber
              <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
            </button>
            {/* <span className="text-sm font-semibold text-[#7a879d]">
              You manage. Amber joins.
            </span> */}
          </div>
          <div className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm font-semibold text-[#53617a]">
            {["Google Meet", "Zoom", "Microsoft Teams"].map((platform) => (
              <span key={platform} className="inline-flex items-center gap-1.5">
                <span className="grid h-4 w-4 place-items-center rounded-full bg-[#e6f4ec] text-[#25815a]">
                  <Check className="h-2.5 w-2.5" strokeWidth={3} />
                </span>
                {platform}
              </span>
            ))}
          </div>
        </div>

        <div
          className="relative mx-auto h-[430px] w-full max-w-[680px] sm:h-[520px] lg:-mr-8 lg:h-[570px]"
          role="img"
          aria-label="Amber joins an online meeting for the operator"
        >
          <div className="absolute left-[12%] top-[7%] aspect-square w-[78%] rounded-full border border-white/80 bg-gradient-to-br from-[#dceaff] via-[#f1f6ff] to-white shadow-[0_34px_90px_rgba(59,101,174,0.18)]" />
          <div className="absolute left-[20%] top-[16%] h-[60%] w-[64%] rounded-full bg-[#cfe0ff]/50 blur-3xl" />

          <img
            className="absolute left-0 top-[8%] z-10 w-[61%] object-contain drop-shadow-[0_22px_36px_rgba(44,78,137,0.2)] sm:left-[1%] sm:top-[10%] sm:w-[59%]"
            src="/assets/meet.svg"
            alt=""
          />

          <div className="amber-hero-agent absolute bottom-[1%] left-[34%] z-20 w-[62%] sm:left-[35%] sm:w-[58%]">
            <div className="absolute bottom-1 left-1/2 h-12 w-[80%] -translate-x-1/2 rounded-[50%] bg-[#3d70c4]/30 blur-xl sm:h-14" />
            <img
              className="relative w-full object-contain drop-shadow-[0_26px_26px_rgba(36,69,126,0.3)]"
              src="/assets/amber-home-agent.svg"
              alt=""
            />
          </div>

          <div className="absolute right-0 top-[4%] z-30 flex items-center gap-3 rounded-2xl border border-white bg-white/90 px-4 py-3 shadow-[0_16px_40px_rgba(49,79,132,0.14)] backdrop-blur-md sm:right-[1%] sm:top-[8%]">
            <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-[#e8f7ef]">
              <span className="absolute h-2.5 w-2.5 animate-ping rounded-full bg-[#35a873]/40" />
              <span className="relative h-2.5 w-2.5 rounded-full bg-[#35a873]" />
            </span>
            <span>
              <span className="block text-xs font-extrabold text-[#263653]">
                Amber is ready
              </span>
              <span className="mt-0.5 block text-[11px] font-semibold text-[#8490a5]">
                Send now or schedule
              </span>
            </span>
          </div>
        </div>
      </section>
    </main>
  )
}

function Sidebar({
  onNewWorkspace,
  onNewCategory,
  selectedDate,
  onSelectDate,
  meetingsByDate,
  workspaces,
  selectedWorkspaceId,
  selectedCategoryId,
  onSelectCategory,
  onEditWorkspace,
  onEditCategory,
  onOpenProfile,
  profile,
  meetingCounts,
  today,
  mobile = false,
  onClose,
}: {
  onNewWorkspace: () => void
  onNewCategory: (workspaceId: string) => void
  selectedDate: Date
  onSelectDate: (date: Date) => void
  meetingsByDate: Record<string, ScheduledMeet[]>
  workspaces: Workspace[]
  selectedWorkspaceId: string
  selectedCategoryId: string
  onSelectCategory: (workspaceId: string, categoryId: string) => void
  onEditWorkspace: (workspaceId: string) => void
  onEditCategory: (workspaceId: string, categoryId: string) => void
  onOpenProfile: () => void
  profile: UserProfile
  meetingCounts: Record<string, number>
  today: Date
  mobile?: boolean
  onClose?: () => void
}) {
  const [viewMonth, setViewMonth] = useState(
    new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1),
  )
  const [calendarOpen, setCalendarOpen] = useState(true)
  const [openWorkspaces, setOpenWorkspaces] = useState<Record<string, boolean>>(
    { amber: true },
  )
  const [scrolling, setScrolling] = useState(false)
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setViewMonth(
      new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1),
    )
  }, [selectedDate])

  const changeMonth = (amount: number) => {
    setViewMonth(
      (current) =>
        new Date(current.getFullYear(), current.getMonth() + amount, 1),
    )
  }

  const handleScroll = () => {
    setScrolling(true)
    if (scrollTimer.current) clearTimeout(scrollTimer.current)
    scrollTimer.current = setTimeout(() => setScrolling(false), 700)
  }

  return (
    <aside
      className={`sidebar-shell h-[100dvh] w-[min(88vw,320px)] shrink-0 flex-col overflow-hidden border-r border-[#e5ecf8] bg-[#f7faff] px-5 pb-5 sm:px-6 ${
        mobile ? "flex" : "hidden w-[300px] lg:flex"
      }`}
    >
      <div
        className={`sidebar-scroll min-h-0 flex-1 overflow-y-auto ${
          scrolling ? "is-scrolling" : ""
        }`}
        onScroll={handleScroll}
      >
        <div className="sticky top-0 z-20 -mx-1 bg-[#f7faff]/95 px-1 pb-3 pt-5 backdrop-blur-sm">
          <div className="flex items-center justify-between gap-3">
            <AmberLogo compact />
            {mobile && (
              <button
                className="grid h-10 w-10 place-items-center rounded-full bg-white text-[#526079] shadow-sm"
                type="button"
                onClick={onClose}
                aria-label="Close navigation"
              >
                <X className="h-5 w-5" />
              </button>
            )}
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <button
            className="flex items-center gap-2 rounded-lg py-1 text-left hover:text-[#3479f5]"
            type="button"
            onClick={() => setCalendarOpen((open) => !open)}
            aria-expanded={calendarOpen}
          >
            <h2 className="text-lg font-bold">
              {viewMonth.toLocaleDateString("en-US", {
                month: "long",
                year: "numeric",
              })}
            </h2>
            <ChevronDown
              className={`h-4 w-4 transition-transform ${
                calendarOpen ? "rotate-180" : ""
              }`}
            />
          </button>
          <div className="flex gap-2 text-[#60708e]">
            <button
              className="rounded-lg p-1.5 hover:bg-white"
              type="button"
              aria-label="Previous month"
              onClick={() => changeMonth(-1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              className="rounded-lg p-1.5 hover:bg-white"
              type="button"
              aria-label="Next month"
              onClick={() => changeMonth(1)}
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
        {calendarOpen && (
          <div className="mt-4 grid grid-cols-7 gap-y-2 text-center text-xs font-semibold">
            {["S", "M", "T", "W", "T", "F", "S"].map((day, index) => (
              <span key={`${day}-${index}`} className="pb-1 text-[#7a86a0]">
                {day}
              </span>
            ))}
            {calendarDays(viewMonth).map((date) => {
              const active = sameDay(date, selectedDate)
              const isToday = sameDay(date, today)
              const muted = date.getMonth() !== viewMonth.getMonth()
              const hasMeetings =
                (meetingsByDate[dateKey(date)] ?? []).length > 0
              return (
                <button
                  key={dateKey(date)}
                  className={`relative mx-auto grid h-8 w-8 place-items-center rounded-full transition ${
                    active
                      ? "bg-[#3479f5] text-white"
                      : muted
                        ? "text-[#b0b8c8] hover:bg-white"
                        : "text-[#26324c] hover:bg-white"
                  } ${
                    isToday && !active
                      ? "ring-1 ring-[#3479f5] text-[#3479f5]"
                      : ""
                  }`}
                  type="button"
                  onClick={() => onSelectDate(date)}
                  aria-label={date.toLocaleDateString("en-US", {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })}
                  aria-pressed={active}
                >
                  {date.getDate()}
                  {hasMeetings && (
                    <span
                      className={`absolute bottom-0.5 h-1 w-1 rounded-full ${
                        active ? "bg-white" : "bg-[#6f91d0]"
                      }`}
                    />
                  )}
                </button>
              )
            })}
          </div>
        )}
        <button
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-2xl bg-[#dfeaff] py-3 font-bold text-[#253653] transition hover:bg-[#d4e3ff]"
          type="button"
          onClick={onNewWorkspace}
        >
          <Plus className="h-5 w-5 rounded-full bg-[#3479f5] p-0.5 text-white" />{" "}
          New workspace
        </button>
        <div className="mt-6 space-y-3">
          {workspaces.map((workspace) => {
            const isOpen = openWorkspaces[workspace.id] ?? true
            return (
              <div key={workspace.id}>
                <div className="group flex items-center gap-1">
                  <button
                    className="min-w-0 flex-1 rounded-lg py-1 text-left"
                    type="button"
                    onClick={() =>
                      setOpenWorkspaces((current) => ({
                        ...current,
                        [workspace.id]: !isOpen,
                      }))
                    }
                    aria-expanded={isOpen}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-bold">
                        {workspace.name}
                      </span>
                    </span>
                  </button>
                  <button
                    className="rounded-lg p-2 text-[#64728d] transition hover:bg-white hover:text-[#3479f5]"
                    type="button"
                    onClick={() => onEditWorkspace(workspace.id)}
                    aria-label={`Edit ${workspace.name}`}
                  >
                    <PencilLine className="h-4 w-4" />
                  </button>
                  <button
                    className="rounded-lg p-2 text-[#64728d] hover:bg-white hover:text-[#3479f5]"
                    type="button"
                    onClick={() => onNewCategory(workspace.id)}
                    aria-label={`Add Meet type to ${workspace.name}`}
                  >
                    <Plus className="h-4 w-4" />
                  </button>
                  <button
                    className="rounded-lg p-2 text-[#64728d] hover:bg-white hover:text-[#3479f5]"
                    type="button"
                    onClick={() =>
                      setOpenWorkspaces((current) => ({
                        ...current,
                        [workspace.id]: !isOpen,
                      }))
                    }
                    aria-label={`${
                      isOpen ? "Collapse" : "Expand"
                    } ${workspace.name}`}
                    aria-expanded={isOpen}
                  >
                    <ChevronDown
                      className={`h-4 w-4 shrink-0 transition-transform ${
                        isOpen ? "rotate-180" : ""
                      }`}
                    />
                  </button>
                </div>
                {isOpen && (
                  <div className="mt-2 space-y-1">
                    {workspace.categories.length === 0 && (
                      <p className="px-2 py-2 text-xs text-[#8a95a9]">
                        Create your first category.
                      </p>
                    )}
                    {workspace.categories.map((category) => {
                      const active =
                        workspace.id === selectedWorkspaceId &&
                        category.id === selectedCategoryId
                      const count =
                        meetingCounts[`${workspace.id}:${category.id}`] ?? 0
                      return (
                        <div
                          key={category.id}
                          className={`group/category flex items-center rounded-xl pr-1 transition ${
                            active
                              ? "bg-[#eaf1ff] text-[#172547]"
                              : "text-[#35425e] hover:bg-white"
                          }`}
                        >
                          <button
                            className="flex min-w-0 flex-1 items-center gap-3 px-2 py-2 text-left text-sm font-medium"
                            type="button"
                            onClick={() => {
                              onSelectCategory(
                                workspace.id,
                                active ? "" : category.id,
                              )
                              if (!active) onClose?.()
                            }}
                            aria-pressed={active}
                          >
                            <span className="min-w-0 flex-1 truncate">
                              {category.name}
                            </span>
                            {count > 0 && (
                              <span className="text-xs text-[#7a87a0]">
                                {count}
                              </span>
                            )}
                            <span
                              className={`grid h-5 w-5 shrink-0 place-items-center rounded border ${
                                active
                                  ? "border-[#3479f5] bg-[#3479f5] text-white"
                                  : "border-[#aab9d2] bg-white"
                              }`}
                            >
                              {active && <Check className="h-3.5 w-3.5" />}
                            </span>
                          </button>
                          <button
                            className="rounded-lg p-1.5 text-[#71809a] opacity-0 transition hover:bg-white hover:text-[#3479f5] focus:opacity-100 group-hover/category:opacity-100"
                            type="button"
                            onClick={() =>
                              onEditCategory(workspace.id, category.id)
                            }
                            aria-label={`Edit ${category.name} context`}
                          >
                            <PencilLine className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
      <button
        className="mt-4 flex w-full shrink-0 items-center gap-3 border-t border-[#e1e8f2] bg-[#f7faff] px-1 pt-5 text-left"
        type="button"
        onClick={onOpenProfile}
      >
        <span className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-full bg-[#dfeaff]">
          <img
            className="h-full w-full object-contain p-0.5"
            src="/assets/amber-profile.svg"
            alt=""
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-bold">
            Amber Meet Agent
          </span>
          <span className="block truncate text-xs text-[#8390a6]">
            {profile.email || "AI meeting assistant"}
          </span>
        </span>
        <Settings className="h-4 w-4 text-[#8390a6]" />
      </button>
    </aside>
  )
}

function NewMeetModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (draft: NewMeetDraft) => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [meetName, setMeetName] = useState("")
  const [companyName, setCompanyName] = useState("")
  const [timing, setTiming] = useState<NewMeetDraft["timing"]>("today")
  const [startDate, setStartDate] = useState(dateKey(addDays(getToday(), 1)))
  const [time, setTime] = useState("09:00")
  const detectedTimezone =
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  const [timezone, setTimezone] = useState(detectedTimezone)
  const [duration, setDuration] = useState("30")
  const [frequency, setFrequency] =
    useState<NewMeetDraft["frequency"]>("weekly")
  const [occurrences, setOccurrences] = useState(8)
  const [smartSchedule, setSmartSchedule] = useState("")
  const [context, setContext] = useState("")
  const [contextMode, setContextMode] = useState<"write" | "upload">("write")
  const [fileName, setFileName] = useState("")
  const [dragging, setDragging] = useState(false)

  const saveMeeting = () => {
    onSave({
      title: meetName.trim(),
      company: companyName.trim(),
      context,
      timing,
      startDate,
      time,
      timezone,
      duration,
      frequency,
      occurrences,
    })
    onClose()
  }

  const applySmartSchedule = () => {
    const value = smartSchedule.toLowerCase()
    if (value.includes("weekday")) {
      setTiming("recurring")
      setFrequency("weekdays")
    } else if (value.includes("daily") || value.includes("every day")) {
      setTiming("recurring")
      setFrequency("daily")
    } else if (value.includes("monthly")) {
      setTiming("recurring")
      setFrequency("monthly")
    } else if (value.includes("weekly") || value.includes("every ")) {
      setTiming("recurring")
      setFrequency("weekly")
    } else {
      setTiming("schedule")
    }

    if (value.includes("tomorrow"))
      setStartDate(dateKey(addDays(getToday(), 1)))
    const timeMatch = value.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)/)
    if (timeMatch) {
      let hour = Number(timeMatch[1])
      if (timeMatch[3] === "pm" && hour < 12) hour += 12
      if (timeMatch[3] === "am" && hour === 12) hour = 0
      setTime(`${String(hour).padStart(2, "0")}:${timeMatch[2] ?? "00"}`)
    }
  }

  const frequencyLabel = {
    daily: "Every day",
    weekdays: "Every weekday",
    weekly: "Every week",
    monthly: "Every month",
  }[frequency]
  const scheduleSummary =
    timing === "today"
      ? `Today at ${new Date(`2026-01-01T${time}`).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`
      : timing === "schedule"
        ? `${new Date(`${startDate}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} at ${new Date(`2026-01-01T${time}`).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`
        : `${frequencyLabel} at ${new Date(`2026-01-01T${time}`).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })} · ${occurrences} meetings`

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-[#111b3c]/55 px-4 py-8 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="flex max-h-[86vh] w-full max-w-[680px] flex-col overflow-hidden rounded-[24px] bg-white shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-meet-title"
      >
        <div className="overflow-y-auto px-6 pb-6 pt-7 sm:px-8">
          <div className="flex items-start justify-between gap-5">
            <div>
              <h2
                id="new-meet-title"
                className="text-2xl font-extrabold tracking-[-0.03em] text-[#111b3c] sm:text-3xl"
              >
                Create a New Meet
              </h2>
              <p className="mt-1.5 text-sm text-[#6a7690]">
                Add a name and any useful context.
              </p>
            </div>
            <button
              className="rounded-full p-2 text-[#273451] transition hover:bg-[#f0f4fa]"
              type="button"
              onClick={onClose}
              aria-label="Close new meeting dialog"
            >
              <X className="h-6 w-6" />
            </button>
          </div>

          <div className="mt-6 space-y-5">
            <div>
              <label
                className="font-bold text-[#17213e]"
                htmlFor="new-meet-name"
              >
                Meet name
              </label>
              <div className="mt-2 rounded-xl border border-[#cbd6e6] px-4 py-3.5 focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10">
                <input
                  id="new-meet-name"
                  className="w-full bg-transparent outline-none placeholder:text-[#8792a8]"
                  value={meetName}
                  onChange={(event) => setMeetName(event.target.value)}
                  placeholder="e.g. Weekly product sync"
                  autoFocus
                />
              </div>
            </div>

            <div>
              <label
                className="font-bold text-[#17213e]"
                htmlFor="company-name"
              >
                Company name
              </label>
              <div className="mt-2 rounded-xl border border-[#cbd6e6] px-4 py-3.5 focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10">
                <input
                  id="company-name"
                  className="w-full bg-transparent outline-none placeholder:text-[#8792a8]"
                  value={companyName}
                  onChange={(event) => setCompanyName(event.target.value)}
                  placeholder="e.g. Acme Inc."
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-4">
                <span className="font-bold text-[#17213e]">When</span>
                <div className="flex rounded-full bg-[#eef2f8] p-1 text-xs font-semibold">
                  {(["today", "schedule", "recurring"] as const).map(
                    (option) => (
                      <button
                        key={option}
                        className={`rounded-full px-3 py-1.5 capitalize transition ${
                          timing === option
                            ? "bg-white text-[#3479f5] shadow-sm"
                            : "text-[#68758f]"
                        }`}
                        type="button"
                        onClick={() => setTiming(option)}
                      >
                        {option}
                      </button>
                    ),
                  )}
                </div>
              </div>

              <div className="mt-3 flex gap-2">
                <input
                  className="min-w-0 flex-1 rounded-xl border border-[#cbd6e6] px-4 py-3 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
                  value={smartSchedule}
                  onChange={(event) => setSmartSchedule(event.target.value)}
                  placeholder='Try "every weekday at 9 AM"'
                />
                <button
                  className="rounded-xl border border-[#c7d3e6] px-4 text-sm font-bold text-[#3479f5] disabled:opacity-40"
                  type="button"
                  onClick={applySmartSchedule}
                  disabled={!smartSchedule.trim()}
                >
                  Apply
                </button>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {timing !== "today" && (
                  <input
                    className="col-span-2 rounded-xl border border-[#cbd6e6] px-3 py-3 outline-none focus:border-[#3479f5]"
                    type="date"
                    min={dateKey(getToday())}
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                    aria-label="Start date"
                  />
                )}
                <input
                  className="rounded-xl border border-[#cbd6e6] px-3 py-3 outline-none focus:border-[#3479f5]"
                  type="time"
                  value={time}
                  onChange={(event) => setTime(event.target.value)}
                  aria-label="Meeting time"
                />
                <select
                  className="rounded-xl border border-[#cbd6e6] bg-white px-3 py-3 outline-none focus:border-[#3479f5]"
                  value={duration}
                  onChange={(event) => setDuration(event.target.value)}
                  aria-label="Duration"
                >
                  <option value="15">15 min</option>
                  <option value="30">30 min</option>
                  <option value="45">45 min</option>
                  <option value="60">1 hour</option>
                </select>
                {timing === "recurring" && (
                  <>
                    <select
                      className="rounded-xl border border-[#cbd6e6] bg-white px-3 py-3 outline-none focus:border-[#3479f5]"
                      value={frequency}
                      onChange={(event) =>
                        setFrequency(
                          event.target.value as NewMeetDraft["frequency"],
                        )
                      }
                      aria-label="Frequency"
                    >
                      <option value="daily">Daily</option>
                      <option value="weekdays">Weekdays</option>
                      <option value="weekly">Weekly</option>
                      <option value="monthly">Monthly</option>
                    </select>
                    <label className="flex items-center rounded-xl border border-[#cbd6e6] px-3 text-sm text-[#68758f]">
                      <input
                        className="mr-2 w-12 bg-transparent outline-none"
                        type="number"
                        min="2"
                        max="52"
                        value={occurrences}
                        onChange={(event) =>
                          setOccurrences(
                            Math.max(2, Number(event.target.value)),
                          )
                        }
                      />
                      times
                    </label>
                  </>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-[#4974ce]">
                  {scheduleSummary}
                </p>
                <select
                  className="max-w-[210px] rounded-lg border border-[#d6dfec] bg-white px-2 py-1.5 text-xs text-[#68758f] outline-none"
                  value={timezone}
                  onChange={(event) => setTimezone(event.target.value)}
                  aria-label="Time zone"
                >
                  <option value={detectedTimezone}>
                    {detectedTimezone} (detected)
                  </option>
                  {detectedTimezone !== "UTC" && (
                    <option value="UTC">UTC</option>
                  )}
                  {detectedTimezone !== "America/New_York" && (
                    <option value="America/New_York">America/New_York</option>
                  )}
                  {detectedTimezone !== "Asia/Kolkata" && (
                    <option value="Asia/Kolkata">Asia/Kolkata</option>
                  )}
                </select>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-4">
                <label
                  className="font-bold text-[#17213e]"
                  htmlFor="meeting-context"
                >
                  Context{" "}
                  <span className="font-normal text-[#8390a6]">(optional)</span>
                </label>
                <div className="flex rounded-full bg-[#eef2f8] p-1 text-xs font-semibold">
                  <button
                    className={`rounded-full px-3 py-1.5 transition ${
                      contextMode === "write"
                        ? "bg-white text-[#3479f5] shadow-sm"
                        : "text-[#68758f]"
                    }`}
                    type="button"
                    onClick={() => setContextMode("write")}
                  >
                    Write
                  </button>
                  <button
                    className={`rounded-full px-3 py-1.5 transition ${
                      contextMode === "upload"
                        ? "bg-white text-[#3479f5] shadow-sm"
                        : "text-[#68758f]"
                    }`}
                    type="button"
                    onClick={() => setContextMode("upload")}
                  >
                    Upload
                  </button>
                </div>
              </div>

              {contextMode === "write" ? (
                <div className="relative mt-2 h-[180px] rounded-xl border border-[#cbd6e6] px-4 py-3.5 focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10">
                  <textarea
                    id="meeting-context"
                    className="h-full w-full resize-none bg-transparent pb-5 outline-none placeholder:text-[#8792a8]"
                    maxLength={1000}
                    value={context}
                    onChange={(event) => setContext(event.target.value)}
                    placeholder="Write the agenda, goals, or anything Amber should know..."
                  />
                  <span className="absolute bottom-3 right-4 text-xs text-[#7d899e]">
                    {context.length}/1000
                  </span>
                </div>
              ) : (
                <div
                  className={`mt-2 flex h-[180px] flex-col items-center justify-center rounded-xl border border-dashed px-5 py-5 text-center transition ${
                    dragging
                      ? "border-[#3479f5] bg-[#f5f8ff]"
                      : "border-[#cbd6e6] bg-[#fbfcfe]"
                  }`}
                  onDragEnter={(event) => {
                    event.preventDefault()
                    setDragging(true)
                  }}
                  onDragOver={(event) => event.preventDefault()}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault()
                    setDragging(false)
                    const file = event.dataTransfer.files[0]
                    if (file) setFileName(file.name)
                  }}
                >
                  <Upload className="mx-auto mb-2 h-6 w-6 text-[#3479f5]" />
                  <p className="font-semibold text-[#34415d]">
                    {fileName || "Drop a context file here"}
                  </p>
                  <p className="mt-1 text-xs text-[#8390a6]">
                    {fileName ? "Ready to attach" : "PDF, DOC, or TXT"}
                  </p>
                  <button
                    className="mt-3 rounded-full border border-[#c7d3e6] bg-white px-5 py-2 text-sm font-semibold text-[#3479f5] hover:border-[#3479f5]"
                    type="button"
                    onClick={() => fileInput.current?.click()}
                  >
                    {fileName ? "Choose another file" : "Choose file"}
                  </button>
                  <input
                    ref={fileInput}
                    className="hidden"
                    type="file"
                    accept=".pdf,.doc,.docx,.txt"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) setFileName(file.name)
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-3 border-t border-[#e7ecf4] px-6 py-4 sm:px-8">
          <button
            className="rounded-full bg-[#eff3fa] px-8 py-3 font-bold text-[#17213e] transition hover:bg-[#e5ebf5]"
            type="button"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-full bg-[#3479f5] px-10 py-3 font-bold text-white shadow-[0_10px_24px_rgba(52,121,245,0.22)] transition hover:bg-[#2068e7] disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            onClick={saveMeeting}
            disabled={!meetName.trim()}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

function WorkspaceModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (name: string, category: string, agenda: string) => void
}) {
  const [name, setName] = useState("")
  const [category, setCategory] = useState("")
  const [agenda, setAgenda] = useState("")

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[#111b3c]/55 px-4 py-8 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-[680px] rounded-[24px] bg-white p-7 shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workspace-title"
      >
        <div className="flex items-start justify-between gap-5">
          <div>
            <h2
              id="workspace-title"
              className="text-2xl font-extrabold tracking-[-0.03em]"
            >
              Create workspace
            </h2>
            <p className="mt-1.5 text-sm text-[#6a7690]">
              Add a company and its first meeting category.
            </p>
          </div>
          <button
            className="rounded-full p-2 hover:bg-[#f0f4fa]"
            type="button"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="mt-6 space-y-4">
          <label className="block">
            <span className="font-bold">Workspace name</span>
            <input
              className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Kaya"
              autoFocus
            />
          </label>
          <label className="block">
            <span className="font-bold">First Meet type</span>
            <input
              className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="e.g. Developer Meet"
            />
          </label>
          <label className="block">
            <span className="font-bold">
              Overall Meet context{" "}
              <span className="font-normal text-[#8390a6]">(optional)</span>
            </span>
            <textarea
              className="mt-2 min-h-[100px] w-full resize-none rounded-xl border border-[#cbd6e6] px-4 py-3 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5]"
              value={agenda}
              onChange={(event) => setAgenda(event.target.value)}
              placeholder="Purpose, recurring goals, participants, or standard talking points..."
            />
          </label>
        </div>
        <div className="mt-7 flex justify-end gap-3">
          <button
            className="rounded-full bg-[#eff3fa] px-7 py-3 font-bold"
            type="button"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-full bg-[#3479f5] px-8 py-3 font-bold text-white disabled:opacity-50"
            type="button"
            disabled={!name.trim() || !category.trim()}
            onClick={() => onSave(name.trim(), category.trim(), agenda.trim())}
          >
            Create workspace
          </button>
        </div>
      </div>
    </div>
  )
}

function CategoryModal({
  workspaceName,
  category,
  onClose,
  onSave,
  onDelete,
}: {
  workspaceName: string
  category?: {
    name: string
    agenda?: string
  }
  onClose: () => void
  onSave: (name: string, agenda: string) => void
  onDelete?: () => void
}) {
  const [name, setName] = useState(category?.name ?? "")
  const [agenda, setAgenda] = useState(category?.agenda ?? "")

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[#111b3c]/55 px-4 py-8 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-[680px] rounded-[24px] bg-white p-7 shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="category-title"
      >
        <div className="flex items-start justify-between gap-5">
          <div>
            <h2
              id="category-title"
              className="text-2xl font-extrabold tracking-[-0.03em]"
            >
              {category ? "Edit Meet type" : "Create Meet type"}
            </h2>
            <p className="mt-1.5 text-sm text-[#6a7690]">
              Set the reusable context for every {name || "Meet"} in{" "}
              {workspaceName}.
            </p>
          </div>
          <button
            className="rounded-full p-2 hover:bg-[#f0f4fa]"
            type="button"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <label className="mt-6 block">
          <span className="font-bold">Meet type name</span>
          <input
            className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Supplier Meet"
            autoFocus
          />
        </label>
        <label className="mt-4 block">
          <span className="font-bold">
            Overall context{" "}
            <span className="font-normal text-[#8390a6]">(optional)</span>
          </span>
          <textarea
            className="mt-2 min-h-[140px] w-full resize-none rounded-xl border border-[#cbd6e6] px-4 py-3 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5]"
            maxLength={1500}
            value={agenda}
            onChange={(event) => setAgenda(event.target.value)}
            placeholder="Describe the purpose, recurring agenda, expected outcomes, and anything Amber should always know."
          />
          <span className="mt-1 block text-right text-xs text-[#8390a6]">
            {agenda.length}/1500
          </span>
        </label>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          {category && onDelete && (
            <button
              className="mr-auto flex items-center gap-2 rounded-full border border-[#f0caca] bg-[#fff7f7] px-5 py-3 text-sm font-bold text-[#bd4545] transition hover:border-[#e7aaaa] hover:bg-[#fff0f0]"
              type="button"
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4" /> Delete Meet type
            </button>
          )}
          {category ? (
            <button
              className="rounded-full bg-[#3479f5] px-8 py-3 font-bold text-white disabled:opacity-50"
              type="button"
              disabled={!name.trim()}
              onClick={() => onSave(name.trim(), agenda.trim())}
            >
              Save
            </button>
          ) : (
            <>
              <button
                className="rounded-full bg-[#eff3fa] px-7 py-3 font-bold"
                type="button"
                onClick={onClose}
              >
                Cancel
              </button>
              <button
                className="rounded-full bg-[#3479f5] px-8 py-3 font-bold text-white disabled:opacity-50"
                type="button"
                disabled={!name.trim()}
                onClick={() => onSave(name.trim(), agenda.trim())}
              >
                Create Meet type
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function RenameWorkspaceModal({
  workspace,
  onClose,
  onSave,
  onDelete,
}: {
  workspace: Workspace
  onClose: () => void
  onSave: (name: string) => void
  onDelete: () => void
}) {
  const [name, setName] = useState(workspace.name)
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[#111b3c]/55 px-4 py-8 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-[680px] rounded-[24px] bg-white p-7 shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rename-workspace-title"
      >
        <div className="flex items-start justify-between gap-5">
          <div>
            <h2
              id="rename-workspace-title"
              className="text-2xl font-extrabold tracking-[-0.03em]"
            >
              Rename workspace
            </h2>
            <p className="mt-1.5 text-sm text-[#6a7690]">
              Use the real team, client, or company name.
            </p>
          </div>
          <button
            className="rounded-full p-2 hover:bg-[#f0f4fa]"
            type="button"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <label className="mt-6 block">
          <span className="font-bold">Workspace name</span>
          <input
            className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none focus:border-[#3479f5]"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
        </label>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <button
            className="mr-auto flex items-center gap-2 rounded-full border border-[#f0caca] bg-[#fff7f7] px-5 py-3 text-sm font-bold text-[#bd4545] transition hover:border-[#e7aaaa] hover:bg-[#fff0f0]"
            type="button"
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" /> Delete workspace
          </button>
          <button
            className="rounded-full bg-[#3479f5] px-8 py-3 font-bold text-white disabled:opacity-50"
            type="button"
            disabled={!name.trim()}
            onClick={() => onSave(name.trim())}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

function ScheduleMeetModal({
  workspaces,
  initialWorkspaceId,
  initialCategoryId,
  initialMeeting,
  initialDate,
  onClose,
  onSave,
}: {
  workspaces: Workspace[]
  initialWorkspaceId: string
  initialCategoryId: string
  initialMeeting?: ScheduledMeet | null
  initialDate: string
  onClose: () => void
  onSave: (draft: ScheduleDraft) => void
}) {
  const defaultWorkspaceId = initialWorkspaceId || workspaces[0]?.id || ""
  const defaultCategoryId =
    initialCategoryId ||
    workspaces.find(({ id }) => id === defaultWorkspaceId)?.categories[0]?.id ||
    ""
  const [title, setTitle] = useState(initialMeeting?.title ?? "")
  const [workspaceId, setWorkspaceId] = useState(defaultWorkspaceId)
  const [categoryId, setCategoryId] = useState(defaultCategoryId)
  const [link, setLink] = useState(initialMeeting?.link ?? "")
  const [startDate, setStartDate] = useState(initialDate)
  const [time, setTime] = useState("09:00")
  const [duration, setDuration] = useState("30")
  const [recurrence, setRecurrence] =
    useState<ScheduleDraft["recurrence"]>("once")
  const [occurrences, setOccurrences] = useState(8)
  const [overallContextExpanded, setOverallContextExpanded] = useState(false)
  const selectedWorkspace = workspaces.find(({ id }) => id === workspaceId)
  const selectedCategory = selectedWorkspace?.categories.find(
    ({ id }) => id === categoryId,
  )
  const longOverallContext = Boolean(
    selectedCategory?.agenda && selectedCategory.agenda.length > 180,
  )
  const recurring = recurrence !== "once"
  const recurrenceLabels: Record<ScheduleDraft["recurrence"], string> = {
    once: "One time",
    daily: "Every day",
    weekdays: "Weekdays",
    weekly: "Every week",
    monthly: "Every month",
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[#111b3c]/55 px-4 py-8 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-[680px] flex-col overflow-hidden rounded-[26px] bg-white shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="schedule-title"
      >
        <div className="overflow-y-auto px-6 pb-6 pt-7 sm:px-8">
          <div className="flex items-start justify-between gap-5">
            <div>
              <h2
                id="schedule-title"
                className="text-2xl font-extrabold tracking-[-0.03em]"
              >
                Schedule a meet
              </h2>
              <p className="mt-1.5 text-sm text-[#6a7690]">
                Choose where it belongs, then set the time.
              </p>
            </div>
            <button
              className="rounded-full p-2 hover:bg-[#f0f4fa]"
              type="button"
              onClick={onClose}
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="mt-6 space-y-5">
            <div>
              <div className="grid grid-cols-2 gap-3">
                <label>
                  <span className="mb-2 block text-sm font-bold">
                    Workspace
                  </span>
                  <select
                    className="w-full rounded-xl border border-[#cbd6e6] bg-white px-3 py-3 outline-none focus:border-[#3479f5]"
                    value={workspaceId}
                    onChange={(event) => {
                      const nextWorkspaceId = event.target.value
                      setWorkspaceId(nextWorkspaceId)
                      setCategoryId(
                        workspaces.find(({ id }) => id === nextWorkspaceId)
                          ?.categories[0]?.id ?? "",
                      )
                      setOverallContextExpanded(false)
                    }}
                  >
                    {workspaces.map((workspace) => (
                      <option key={workspace.id} value={workspace.id}>
                        {workspace.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="mb-2 block text-sm font-bold">
                    Meet type
                  </span>
                  <select
                    className="w-full rounded-xl border border-[#cbd6e6] bg-white px-3 py-3 outline-none focus:border-[#3479f5]"
                    value={categoryId}
                    onChange={(event) => {
                      setCategoryId(event.target.value)
                      setOverallContextExpanded(false)
                    }}
                    disabled={!selectedWorkspace}
                  >
                    {selectedWorkspace?.categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <label className="block">
              <span className="font-bold">Meet name</span>
              <input
                className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="e.g. Weekly developer sync"
                autoFocus
              />
            </label>
            <label className="block">
              <span className="font-bold">Meeting link</span>
              <input
                className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
                type="url"
                value={link}
                onChange={(event) => setLink(event.target.value)}
                placeholder="Google Meet, Zoom, or Microsoft Teams link"
              />
            </label>

            <div>
              <span className="font-bold">Repeat</span>
              <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
                {(Object.keys(
                  recurrenceLabels,
                ) as ScheduleDraft["recurrence"][]).map((option) => (
                  <button
                    key={option}
                    className={`rounded-xl border px-2 py-2.5 text-xs font-semibold transition ${
                      recurrence === option
                        ? "border-[#3479f5] bg-[#edf4ff] text-[#3479f5]"
                        : "border-[#d7dfec] text-[#68758f] hover:border-[#aebfdb]"
                    }`}
                    type="button"
                    onClick={() => setRecurrence(option)}
                  >
                    {recurrenceLabels[option]}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <label className="col-span-2">
                <span className="mb-2 block text-sm font-semibold text-[#526079]">
                  {recurring ? "Starts on" : "Date"}
                </span>
                <input
                  className="w-full rounded-xl border border-[#cbd6e6] px-3 py-3 outline-none focus:border-[#3479f5]"
                  type="date"
                  min={dateKey(getToday())}
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                />
              </label>
              <label>
                <span className="mb-2 block text-sm font-semibold text-[#526079]">
                  Time
                </span>
                <input
                  className="w-full rounded-xl border border-[#cbd6e6] px-3 py-3 outline-none focus:border-[#3479f5]"
                  type="time"
                  value={time}
                  onChange={(event) => setTime(event.target.value)}
                />
              </label>
              <label>
                <span className="mb-2 block text-sm font-semibold text-[#526079]">
                  Duration
                </span>
                <select
                  className="w-full rounded-xl border border-[#cbd6e6] bg-white px-3 py-3 outline-none focus:border-[#3479f5]"
                  value={duration}
                  onChange={(event) => setDuration(event.target.value)}
                >
                  <option value="15">15 min</option>
                  <option value="30">30 min</option>
                  <option value="45">45 min</option>
                  <option value="60">1 hour</option>
                </select>
              </label>
            </div>

            {recurring && (
              <div className="flex items-center justify-between rounded-xl bg-[#f5f8fd] px-4 py-3">
                <div>
                  <p className="text-sm font-bold">
                    {recurrenceLabels[recurrence]}
                  </p>
                  <p className="mt-0.5 text-xs text-[#7b879d]">
                    Set each day&apos;s agenda from that date on the calendar
                    after scheduling.
                  </p>
                </div>
                <label className="flex items-center gap-2 text-sm text-[#64718a]">
                  <input
                    className="w-14 rounded-lg border border-[#cbd6e6] bg-white px-2 py-2 text-center outline-none"
                    type="number"
                    min="2"
                    max="52"
                    value={occurrences}
                    onChange={(event) =>
                      setOccurrences(
                        Math.min(52, Math.max(2, Number(event.target.value))),
                      )
                    }
                  />
                  meetings
                </label>
              </div>
            )}

            {selectedCategory?.agenda && (
              <div
                className={`rounded-xl border border-[#d9e4f4] bg-[#f6f9fe] px-4 py-3.5 transition-all ${
                  overallContextExpanded ? "" : "h-[142px]"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-xs font-bold uppercase tracking-[0.08em] text-[#657693]">
                    {selectedCategory.name} · Overall context
                  </p>
                  {longOverallContext && (
                    <button
                      className="flex shrink-0 items-center gap-1 text-xs font-bold text-[#4974ce]"
                      type="button"
                      onClick={() =>
                        setOverallContextExpanded((expanded) => !expanded)
                      }
                      aria-expanded={overallContextExpanded}
                    >
                      {overallContextExpanded ? "Collapse" : "Show full"}
                      <ChevronDown
                        className={`h-3.5 w-3.5 transition-transform ${
                          overallContextExpanded ? "rotate-180" : ""
                        }`}
                      />
                    </button>
                  )}
                </div>
                <p
                  className={`mt-1.5 whitespace-pre-wrap pr-2 text-sm leading-6 text-[#526079] ${
                    overallContextExpanded ? "" : "h-[82px] overflow-y-auto"
                  }`}
                >
                  {selectedCategory.agenda}
                </p>
              </div>
            )}

            <div className="flex items-start gap-3 rounded-xl border border-[#d9e4f4] bg-[#f6f9fe] px-4 py-3">
              <CalendarDays className="mt-0.5 h-5 w-5 shrink-0 text-[#4974ce]" />
              <div>
                <p className="text-sm font-bold text-[#34415d]">
                  Daily agendas are added after scheduling
                </p>
                <p className="mt-1 text-xs leading-5 text-[#6f7d95]">
                  Open each scheduled date in the calendar and use “Edit
                  agenda.” This keeps every day&apos;s topics separate from the
                  Meet type&apos;s overall context.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-3 border-t border-[#e7ecf4] px-6 py-4 sm:px-8">
          <button
            className="rounded-full bg-[#eff3fa] px-7 py-3 font-bold"
            type="button"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-full bg-[#3479f5] px-8 py-3 font-bold text-white disabled:opacity-50"
            type="button"
            disabled={
              !title.trim() || !workspaceId || !categoryId || !link.trim()
            }
            onClick={() =>
              onSave({
                title: title.trim(),
                workspaceId,
                categoryId,
                link: link.trim(),
                startDate,
                time,
                duration,
                recurrence,
                occurrences,
              })
            }
          >
            Schedule
          </button>
        </div>
      </div>
    </div>
  )
}

function EditAgendaModal({
  meeting,
  overallAgenda,
  onClose,
  onSave,
}: {
  meeting: ScheduledMeet
  overallAgenda?: string
  onClose: () => void
  onSave: (
    context: string,
    fileName: string,
    fileId?: string,
    fileSize?: number,
    fileType?: string,
  ) => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<"write" | "upload">(
    meeting.fileName ? "upload" : "write",
  )
  const [context, setContext] = useState(meeting.context ?? "")
  const [fileName, setFileName] = useState(meeting.fileName ?? "")
  const [fileId, setFileId] = useState(meeting.fileId)
  const [fileSize, setFileSize] = useState(meeting.fileSize)
  const [fileType, setFileType] = useState(meeting.fileType)
  const [dragging, setDragging] = useState(false)
  const [fileMessage, setFileMessage] = useState("")
  const [overallExpanded, setOverallExpanded] = useState(false)
  const hasWrittenAgenda = Boolean(context.trim())
  const hasUploadedAgenda = Boolean(fileName)
  const longOverallAgenda = Boolean(overallAgenda && overallAgenda.length > 180)

  const acceptFile = async (file?: File) => {
    if (!file) return
    if (file.size > MAX_DOCUMENT_SIZE) {
      setFileMessage("Choose a document smaller than 10 MB.")
      return
    }
    try {
      const id = await storeDocument(file)
      setFileName(file.name)
      setFileId(id)
      setFileSize(file.size)
      setFileType(file.type)
      setFileMessage("")
    } catch {
      setFileMessage("Amber could not save this document. Please try again.")
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-[#111b3c]/55 px-4 py-8 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-[680px] flex-col overflow-hidden rounded-[24px] bg-white shadow-[0_28px_90px_rgba(12,26,58,0.28)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agenda-title"
      >
        <div className="min-h-0 overflow-y-auto px-6 pb-6 pt-7">
          <div className="flex items-start justify-between gap-5">
            <div>
              <h2
                id="agenda-title"
                className="text-2xl font-extrabold tracking-[-0.03em]"
              >
                Set today&apos;s agenda
              </h2>
              <p className="mt-1.5 text-sm leading-6 text-[#6a7690]">
                Add the topics or preparation that are unique to today.
              </p>
            </div>
            <button
              className="rounded-full p-2 hover:bg-[#f0f4fa]"
              type="button"
              onClick={onClose}
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {overallAgenda && (
            <div
              className={`mt-5 rounded-2xl border border-[#d9e4f4] bg-[#f6f9fe] px-4 py-3.5 transition-[height] duration-200 ${
                overallExpanded ? "h-[260px]" : "h-[142px]"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-bold uppercase tracking-[0.08em] text-[#657693]">
                  Overall Meet agenda
                </p>
                {longOverallAgenda && (
                  <button
                    className="flex items-center gap-1 text-xs font-bold text-[#4974ce]"
                    type="button"
                    onClick={() => setOverallExpanded((expanded) => !expanded)}
                    aria-expanded={overallExpanded}
                  >
                    {overallExpanded ? "Collapse" : "Show full"}
                    <ChevronDown
                      className={`h-3.5 w-3.5 transition-transform ${
                        overallExpanded ? "rotate-180" : ""
                      }`}
                    />
                  </button>
                )}
              </div>
              <p
                className={`mt-1.5 overflow-y-auto whitespace-pre-wrap pr-2 text-sm leading-6 text-[#526079] transition-[height] duration-200 ${
                  overallExpanded ? "h-[200px]" : "h-[82px]"
                }`}
              >
                {overallAgenda}
              </p>
            </div>
          )}

          <div className="mt-5 flex items-center justify-between gap-4">
            <span>
              <span className="block text-sm font-bold text-[#263653]">
                Today&apos;s agenda
              </span>
              <span className="mt-0.5 block text-xs text-[#7a869c]">
                Choose one format for this meeting.
              </span>
            </span>
            <div
              className="flex rounded-full bg-[#eef2f8] p-1 text-xs font-semibold"
              role="group"
              aria-label="Agenda input method"
            >
              <button
                className={`rounded-full px-4 py-1.5 transition ${
                  mode === "write"
                    ? "bg-white text-[#3479f5] shadow-sm"
                    : "text-[#68758f]"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                type="button"
                onClick={() => setMode("write")}
                aria-pressed={mode === "write"}
                disabled={hasUploadedAgenda}
              >
                Write
              </button>
              <button
                className={`rounded-full px-4 py-1.5 transition ${
                  mode === "upload"
                    ? "bg-white text-[#3479f5] shadow-sm"
                    : "text-[#68758f]"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                type="button"
                onClick={() => setMode("upload")}
                aria-pressed={mode === "upload"}
                disabled={hasWrittenAgenda}
              >
                Upload
              </button>
            </div>
          </div>

          {mode === "write" ? (
            <div
              className={`relative mt-3 rounded-xl border border-[#cbd6e6] p-4 transition-[height] duration-200 focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10 ${
                overallExpanded ? "h-[302px]" : "h-[420px]"
              }`}
            >
              <textarea
                className="h-full w-full resize-none bg-transparent pb-12 outline-none placeholder:text-[#8792a8]"
                maxLength={1500}
                value={context}
                onChange={(event) => setContext(event.target.value)}
                placeholder="What should Amber know for today’s conversation?"
                autoFocus
              />
              <div className="absolute bottom-0 left-4 right-4 flex h-12 items-center justify-between gap-3 border-t border-[#edf0f5] bg-white">
                {hasWrittenAgenda ? (
                  <button
                    className="text-xs font-bold text-[#bd4545] hover:underline"
                    type="button"
                    onClick={() => setContext("")}
                  >
                    Clear to upload instead
                  </button>
                ) : (
                  <span />
                )}
                <span className="text-xs text-[#8490a5]">
                  {context.length}/1500
                </span>
              </div>
            </div>
          ) : (
            <div
              className={`mt-3 overflow-hidden rounded-xl border text-center transition-[height] duration-200 ${
                overallExpanded ? "h-[302px]" : "h-[420px]"
              } ${
                dragging
                  ? "border-[#3479f5] bg-[#f5f8ff]"
                  : fileName
                    ? "border-[#d8e1ee] bg-white"
                    : "border-dashed border-[#cbd6e6] bg-[#fbfcfe]"
              }`}
              onDragEnter={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                void acceptFile(event.dataTransfer.files[0])
              }}
            >
              {fileName ? (
                fileName.toLowerCase().endsWith(".pdf") ? (
                  <PdfPreview
                    fileId={fileId}
                    name={fileName}
                    onRemove={() => {
                      setFileName("")
                      setFileId(undefined)
                      setFileSize(undefined)
                      setFileType(undefined)
                    }}
                  />
                ) : (
                  <div className="p-5">
                    <UploadedDocument
                      name={fileName}
                      fileId={fileId}
                      size={fileSize}
                      type={fileType}
                      onRemove={() => {
                        setFileName("")
                        setFileId(undefined)
                        setFileSize(undefined)
                        setFileType(undefined)
                      }}
                    />
                  </div>
                )
              ) : (
                <div className="flex h-full flex-col items-center justify-center p-5">
                  <Upload className="mx-auto mb-2 h-7 w-7 text-[#3479f5]" />
                  <p className="font-semibold text-[#34415d]">
                    Drop an agenda file here
                  </p>
                  <p className="mt-1 text-xs text-[#8490a5]">
                    PDF, DOC, DOCX, or TXT · up to 10 MB
                  </p>
                  <button
                    className="mt-3 rounded-full border border-[#c7d3e6] bg-white px-5 py-2 text-sm font-bold text-[#3479f5]"
                    type="button"
                    onClick={() => fileInput.current?.click()}
                  >
                    Choose file
                  </button>
                </div>
              )}
              <input
                ref={fileInput}
                className="hidden"
                type="file"
                accept=".pdf,.doc,.docx,.txt"
                onChange={(event) => void acceptFile(event.target.files?.[0])}
              />
              {fileMessage && (
                <p
                  className="p-3 text-xs font-semibold text-[#c94848]"
                  role="status"
                >
                  {fileMessage}
                </p>
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end border-t border-[#e7ecf4] px-6 py-4">
          <button
            className="rounded-full bg-[#3479f5] px-8 py-3 font-bold text-white"
            type="button"
            onClick={() =>
              onSave(
                mode === "write" ? context : "",
                mode === "upload" ? fileName : "",
                mode === "upload" ? fileId : undefined,
                mode === "upload" ? fileSize : undefined,
                mode === "upload" ? fileType : undefined,
              )
            }
          >
            Save agenda
          </button>
        </div>
      </div>
    </div>
  )
}

function MeetActionModal({
  meeting,
  onClose,
  onSchedule,
}: {
  meeting: ScheduledMeet
  onClose: () => void
  onSchedule: () => void
}) {
  const [link, setLink] = useState(meeting.link ?? "")
  const [message, setMessage] = useState("")

  const joinMeeting = () => {
    if (!link.trim()) {
      setMessage("Add the meeting link before joining.")
      return
    }
    window.open(link.trim(), "_blank", "noopener,noreferrer")
  }

  return (
    <div
      className="fixed inset-0 z-[55] grid place-items-center bg-[#111b3c]/55 px-4 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-[680px] rounded-[26px] bg-white p-7 shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="join-meet-title"
      >
        <div className="flex items-start justify-between gap-5">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-[#72809a]">
              {meeting.status === "ended"
                ? "Ended meeting"
                : "Upcoming meeting"}
            </p>
            <h2
              id="join-meet-title"
              className="mt-1 text-2xl font-extrabold tracking-[-0.03em]"
            >
              {meeting.title}
            </h2>
            <p className="mt-2 text-sm text-[#6a7690]">
              {meeting.time} · {meeting.duration} · {meeting.type}
            </p>
          </div>
          <button
            className="rounded-full p-2 hover:bg-[#f0f4fa]"
            type="button"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {!meeting.link && (
          <label className="mt-6 block">
            <span className="text-sm font-bold">Meeting link</span>
            <input
              className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5]"
              value={link}
              onChange={(event) => {
                setLink(event.target.value)
                setMessage("")
              }}
              placeholder="Google Meet, Zoom, or Microsoft Teams link"
              autoFocus
            />
          </label>
        )}
        {meeting.context && (
          <div className="mt-5 rounded-xl bg-[#f5f8fd] px-4 py-3 text-sm leading-6 text-[#5f6d86]">
            {meeting.context}
          </div>
        )}
        {message && (
          <p className="mt-3 text-sm font-semibold text-[#c94848]">{message}</p>
        )}

        <div className="mt-7 grid gap-3 sm:grid-cols-2">
          <button
            className="rounded-full border border-[#cbd6e6] px-5 py-3.5 font-bold text-[#3479f5] transition hover:border-[#3479f5]"
            type="button"
            onClick={onSchedule}
          >
            Schedule this meet
          </button>
          <button
            className="flex items-center justify-center gap-2 rounded-full bg-[#3479f5] px-5 py-3.5 font-bold text-white shadow-[0_10px_24px_rgba(52,121,245,0.2)] hover:bg-[#2068e7]"
            type="button"
            onClick={joinMeeting}
          >
            <Video className="h-5 w-5" />
            {meeting.status === "ended" ? "Rejoin meet" : "Join now"}
          </button>
        </div>
      </div>
    </div>
  )
}

function TodayMeetList({
  meetings,
  onJoin,
  onSchedule,
}: {
  meetings: ScheduledMeet[]
  onJoin: (meeting: ScheduledMeet) => void
  onSchedule: () => void
}) {
  const upcoming = meetings.filter(({ status }) => status !== "ended")
  const ended = meetings.filter(({ status }) => status === "ended")

  const renderMeeting = (meeting: ScheduledMeet, index: number) => (
    <div
      key={`${meeting.title}-${meeting.time}-${index}`}
      className={`flex items-center gap-4 rounded-2xl border p-4 shadow-[0_8px_24px_rgba(43,67,114,0.04)] md:p-5 ${
        meeting.status === "ended"
          ? "border-[#e4e8ef] bg-[#f8f9fb]"
          : "border-[#d9e4f4] bg-white"
      }`}
    >
      <span
        className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${
          meeting.status === "ended"
            ? "bg-[#e9edf3] text-[#778399]"
            : "bg-[#e8f0ff] text-[#3479f5]"
        }`}
      >
        <Video className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={`block truncate text-base font-bold md:text-lg ${
            meeting.status === "ended" ? "text-[#657087]" : "text-[#19233f]"
          }`}
        >
          {meeting.title}
        </span>
        <span className="mt-1 block text-sm text-[#7a869c]">
          {meeting.time} · {meeting.duration} · {meeting.type}
        </span>
      </span>
      <button
        className={`shrink-0 rounded-full px-5 py-2.5 text-sm font-bold transition ${
          meeting.status === "ended"
            ? "border border-[#ccd4e0] text-[#5f6c82] hover:border-[#8795ab]"
            : "bg-[#3479f5] text-white hover:bg-[#2068e7]"
        }`}
        type="button"
        onClick={() => onJoin(meeting)}
      >
        {meeting.status === "ended" ? "Rejoin" : "Join"}
      </button>
    </div>
  )

  return (
    <div className="mx-auto w-full max-w-[940px] py-4">
      <div className="mb-7 flex items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.12em] text-[#7a87a0]">
            Today
          </p>
          <h2 className="mt-1 text-3xl font-extrabold tracking-[-0.035em]">
            Your meetings
          </h2>
          <p className="mt-1 text-sm text-[#758199]">
            {upcoming.length} upcoming · {ended.length} ended
          </p>
        </div>
        <button
          className="flex items-center gap-2 rounded-full border border-[#bfd0e7] bg-[#f7faff] px-5 py-3 text-sm font-bold text-[#3479f5] transition hover:border-[#3479f5] hover:bg-[#eef4ff]"
          type="button"
          onClick={onSchedule}
        >
          <CalendarDays className="h-4 w-4" /> Schedule meet
        </button>
      </div>

      <section>
        <h3 className="mb-3 text-sm font-bold uppercase tracking-[0.1em] text-[#53617b]">
          Upcoming
        </h3>
        <div className="space-y-3">
          {upcoming.length ? (
            upcoming.map(renderMeeting)
          ) : (
            <p className="rounded-2xl border border-dashed border-[#d8e1ef] py-8 text-center text-sm text-[#8490a5]">
              No upcoming meetings today.
            </p>
          )}
        </div>
      </section>
      {ended.length > 0 && (
        <section className="mt-7">
          <h3 className="mb-3 text-sm font-bold uppercase tracking-[0.1em] text-[#7b879c]">
            Ended
          </h3>
          <div className="space-y-3">{ended.map(renderMeeting)}</div>
        </section>
      )}
    </div>
  )
}

function DeleteDialog({
  title,
  message,
  onClose,
  onConfirm,
}: {
  title: string
  message: string
  onClose: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-[#111b3c]/55 px-4 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-[680px] rounded-[24px] bg-white p-7 shadow-[0_28px_90px_rgba(12,26,58,0.3)]"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-title"
      >
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#fff0f0] text-[#c94848]">
          <Trash2 className="h-5 w-5" />
        </div>
        <h2
          id="delete-title"
          className="mt-4 text-center text-2xl font-extrabold tracking-[-0.03em]"
        >
          {title}
        </h2>
        <p className="mx-auto mt-2 max-w-sm text-center text-sm leading-6 text-[#6a7690]">
          {message}
        </p>
        <div className="mt-7 flex justify-center gap-3">
          <button
            className="rounded-full bg-[#eff3fa] px-7 py-3 font-bold"
            type="button"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-full bg-[#d94b4b] px-7 py-3 font-bold text-white hover:bg-[#c53d3d]"
            type="button"
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

function JoinMeetPanel({
  workspace,
  category,
  todayMeetings,
  onStore,
  onSchedule,
}: {
  workspace?: Workspace
  category?: {
    id: string
    name: string
  }
  todayMeetings: ScheduledMeet[]
  onStore: (
    meeting: Omit<StoredMeeting, "id" | "createdAt" | "workspaceId" | "categoryId">,
  ) => void
  onSchedule: () => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState("")
  const [meetName, setMeetName] = useState("")
  const [meetLink, setMeetLink] = useState("")
  const [agenda, setAgenda] = useState("")
  const [agendaMode, setAgendaMode] = useState<"write" | "upload">("write")
  const [dragging, setDragging] = useState(false)
  const [formMessage, setFormMessage] = useState("")
  const [todayOpen, setTodayOpen] = useState(false)
  const upcomingMeetings = todayMeetings.filter(
    ({ status }) => status !== "ended",
  )
  const endedMeetings = todayMeetings.filter(({ status }) => status === "ended")

  const acceptFile = (file?: File) => {
    if (file) setFileName(file.name)
  }

  const joinMeeting = () => {
    if (!workspace || !category) {
      setFormMessage("Select a workspace and meeting category before joining.")
      return
    }

    if (!meetName.trim() || !meetLink.trim()) {
      setFormMessage("Add a meet name and meeting link before joining.")
      return
    }

    onStore({
      name: meetName.trim(),
      link: meetLink.trim(),
      agenda,
      fileName,
    })
    setFormMessage(
      `Saved to ${workspace.name} / ${category.name}. Amber is ready to join.`,
    )
  }

  return (
    <div className="relative flex flex-1 flex-col items-center overflow-hidden rounded-[28px] border border-[#e3eaf6] bg-[radial-gradient(circle_at_top,#fbfdff_0%,#ffffff_48%)] px-5 py-9 shadow-[0_18px_60px_rgba(45,72,125,0.06)] md:px-10 md:py-12">
      <div className="relative z-10 w-full max-w-[760px] text-center">
        <h2 className="text-3xl font-extrabold tracking-[-0.035em] md:text-4xl">
          Join your meeting with <span className="text-[#3479f5]">Amber</span>
        </h2>
        <p className="mx-auto mt-3 max-w-[650px] text-base leading-7 text-[#65718d] md:text-lg">
          Paste the meeting link, add your agenda, and let Amber join, listen,
          take notes and help you in real time.
        </p>
        <div
          className={`mx-auto mt-4 inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold ${
            workspace && category
              ? "bg-[#eef4ff] text-[#4974ce]"
              : "bg-[#fff1f1] text-[#c04d4d]"
          }`}
        >
          {workspace && category ? (
            <>
              {workspace.name} <span className="text-[#9aabc8]">/</span>{" "}
              {category.name}
            </>
          ) : (
            "Select workspace and category"
          )}
        </div>
        <button
          className="ml-2 inline-flex items-center gap-2 rounded-full border border-[#cbd8ec] bg-white px-4 py-2 text-sm font-bold text-[#3479f5] transition hover:border-[#3479f5]"
          type="button"
          onClick={onSchedule}
        >
          <CalendarDays className="h-4 w-4" /> Schedule
        </button>
      </div>

      <div className="relative z-10 mt-6 w-full max-w-[760px]">
        <div className="mb-5 overflow-hidden rounded-2xl border border-[#dce5f2] bg-white shadow-[0_8px_24px_rgba(43,67,114,0.04)]">
          <button
            className="flex w-full items-center gap-3 px-5 py-4 text-left"
            type="button"
            onClick={() => setTodayOpen((open) => !open)}
            aria-expanded={todayOpen}
          >
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#edf4ff] text-[#3479f5]">
              <CalendarDays className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-bold">Today&apos;s meetings</span>
              <span className="mt-0.5 block text-xs text-[#7b879d]">
                {upcomingMeetings.length} upcoming · {endedMeetings.length}{" "}
                ended
              </span>
            </span>
            <ChevronDown
              className={`h-5 w-5 text-[#74819a] transition-transform ${
                todayOpen ? "rotate-180" : ""
              }`}
            />
          </button>
          {todayOpen && (
            <div className="border-t border-[#edf0f5] px-5 py-3">
              {todayMeetings.length === 0 ? (
                <p className="py-3 text-center text-sm text-[#7b879d]">
                  Nothing scheduled for today.
                </p>
              ) : (
                <div className="space-y-2">
                  {[...upcomingMeetings, ...endedMeetings].map(
                    (meeting, index) => (
                      <div
                        key={`${meeting.title}-${meeting.time}-${index}`}
                        className={`flex items-center gap-3 rounded-xl px-3 py-3 ${
                          meeting.status === "ended"
                            ? "bg-[#f7f8fa] opacity-70"
                            : "bg-[#f5f8ff]"
                        }`}
                      >
                        <span
                          className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${
                            meeting.status === "ended"
                              ? "bg-[#e9edf3] text-[#7d899d]"
                              : "bg-[#e5eeff] text-[#3479f5]"
                          }`}
                        >
                          <Video className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 flex-1 text-left">
                          <span className="block truncate text-sm font-bold">
                            {meeting.title}
                          </span>
                          <span className="mt-0.5 block text-xs text-[#7b879d]">
                            {meeting.time} · {meeting.duration} · {meeting.type}
                          </span>
                        </span>
                        <span
                          className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                            meeting.status === "ended"
                              ? "bg-[#e8ebf0] text-[#707c90]"
                              : "bg-[#e5f5ed] text-[#27815a]"
                          }`}
                        >
                          {meeting.status === "ended" ? "Ended" : "Upcoming"}
                        </span>
                      </div>
                    ),
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <label className="mb-4 flex items-center gap-3 rounded-2xl border border-[#cdd8e9] bg-white px-5 py-4 transition focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10">
          <input
            className="w-full bg-transparent text-lg outline-none placeholder:text-[#8792a8]"
            type="text"
            value={meetName}
            onChange={(event) => {
              setMeetName(event.target.value)
              setFormMessage("")
            }}
            placeholder="Enter meet name"
            aria-label="Meet name"
          />
        </label>
        <label className="flex items-center gap-3 rounded-2xl border border-[#cdd8e9] bg-white px-5 py-4 transition focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10">
          <input
            className="w-full bg-transparent text-lg outline-none placeholder:text-[#8792a8]"
            type="url"
            value={meetLink}
            onChange={(event) => {
              setMeetLink(event.target.value)
              setFormMessage("")
            }}
            placeholder="Paste Google Meet, Zoom, or Microsoft Teams link"
            aria-label="Meeting link"
          />
        </label>

        <div className="mt-5 rounded-2xl border border-[#cbd7e8] bg-white p-5">
          <div className="flex items-center justify-between gap-4">
            <div className="font-bold">
              Meeting agenda{" "}
              <span className="font-normal text-[#8390a6]">(optional)</span>
            </div>
            <div className="flex rounded-full bg-[#eef2f8] p-1 text-xs font-semibold">
              <button
                className={`rounded-full px-3 py-1.5 transition ${
                  agendaMode === "write"
                    ? "bg-white text-[#3479f5] shadow-sm"
                    : "text-[#68758f]"
                }`}
                type="button"
                onClick={() => setAgendaMode("write")}
              >
                Write
              </button>
              <button
                className={`rounded-full px-3 py-1.5 transition ${
                  agendaMode === "upload"
                    ? "bg-white text-[#3479f5] shadow-sm"
                    : "text-[#68758f]"
                }`}
                type="button"
                onClick={() => setAgendaMode("upload")}
              >
                Upload
              </button>
            </div>
          </div>

          {agendaMode === "write" ? (
            <div className="relative mt-4 h-[178px] rounded-xl bg-[#f2f5fa] px-4 py-3.5 focus-within:ring-2 focus-within:ring-[#3479f5]/20">
              <textarea
                className="h-full w-full resize-none bg-transparent pb-5 outline-none placeholder:text-[#8a95aa]"
                maxLength={1000}
                value={agenda}
                onChange={(event) => setAgenda(event.target.value)}
                placeholder="Write the agenda, talking points, or meeting goals..."
                aria-label="Meeting agenda"
              />
              <span className="absolute bottom-3 right-4 text-xs text-[#7d899e]">
                {agenda.length}/1000
              </span>
            </div>
          ) : (
            <div
              className={`mt-4 flex h-[178px] flex-col items-center justify-center rounded-xl border border-dashed px-5 py-5 text-center transition ${
                dragging
                  ? "border-[#3479f5] bg-[#f5f8ff]"
                  : "border-[#cbd7e8] bg-[#fbfcfe]"
              }`}
              onDragEnter={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                acceptFile(event.dataTransfer.files[0])
              }}
            >
              <Upload className="mx-auto mb-2 h-6 w-6 text-[#3479f5]" />
              <p className="font-semibold text-[#34415d]">
                {fileName || "Drop an agenda file here"}
              </p>
              <p className="mt-1 text-xs text-[#8390a6]">
                {fileName ? "Ready to attach" : "PDF, DOC, or TXT"}
              </p>
              <button
                className="mt-3 rounded-full border border-[#c7d3e6] bg-white px-5 py-2 text-sm font-semibold text-[#3479f5] hover:border-[#3479f5]"
                type="button"
                onClick={() => fileInput.current?.click()}
              >
                {fileName ? "Choose another file" : "Choose file"}
              </button>
              <input
                ref={fileInput}
                className="hidden"
                type="file"
                accept=".pdf,.doc,.docx,.txt"
                onChange={(event) => acceptFile(event.target.files?.[0])}
              />
            </div>
          )}
        </div>
      </div>

      <button
        className="relative z-10 mt-7 flex w-full max-w-[350px] items-center justify-center gap-3 rounded-full bg-[#3479f5] px-8 py-4 text-lg font-bold text-white shadow-[0_14px_30px_rgba(52,121,245,0.25)] transition hover:-translate-y-0.5 hover:bg-[#2068e7]"
        type="button"
        onClick={joinMeeting}
      >
        <Video className="h-6 w-6 fill-current" /> Join Meet
      </button>
      <p
        className={`relative z-10 mt-3 min-h-5 text-center text-sm font-semibold ${
          formMessage.startsWith("Saved") ? "text-[#16966a]" : "text-[#d14d4d]"
        }`}
        role="status"
      >
        {formMessage}
      </p>

      <div
        className="pointer-events-none absolute bottom-0 left-0 hidden h-52 w-60 items-end justify-start bg-[radial-gradient(circle_at_bottom_left,#eef5ff_0%,transparent_68%)] min-[1280px]:flex"
        aria-hidden="true"
      >
        <img
          className="ml-3 w-[190px] object-contain object-bottom"
          src="/assets/amber-assistant.svg"
          alt=""
        />
      </div>
      <div
        className="pointer-events-none absolute bottom-0 right-0 hidden h-56 w-52 items-end justify-end bg-[radial-gradient(circle_at_bottom_right,#eef5ff_0%,transparent_68%)] min-[1280px]:flex"
        aria-hidden="true"
      >
        <img
          className="mr-4 w-[145px] object-contain object-bottom"
          src="/assets/meeting-checklist.svg"
          alt=""
        />
      </div>
    </div>
  )
}

// "Name, email" per line (email optional) -> attendees for the recap and reminders.
const parseAttendees = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const email = line.match(/[^\s<>,;]+@[^\s<>,;]+/)?.[0] ?? ""
      const name = line.replace(email, "").replace(/[<>,;]/g, " ").trim() || email.split("@")[0]
      return { name, email }
    })

function QuickJoinCard({
  workspace,
  category,
  onDispatched,
}: {
  workspace?: Workspace
  category?: {
    id: string
    name: string
    agenda?: string
  }
  onDispatched: (meetingId: number) => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [meetName, setMeetName] = useState("")
  const [meetLink, setMeetLink] = useState("")
  const [attendees, setAttendees] = useState("")
  const [file, setFile] = useState<File>()
  const [sending, setSending] = useState(false)
  const [context, setContext] = useState("")
  const [fileName, setFileName] = useState("")
  const [fileId, setFileId] = useState<string>()
  const [fileSize, setFileSize] = useState<number>()
  const [fileType, setFileType] = useState<string>()
  const [mode, setMode] = useState<"write" | "upload">("write")
  const [dragging, setDragging] = useState(false)
  const [message, setMessage] = useState("")
  const hasWrittenContext = Boolean(context.trim())
  const hasUploadedContext = Boolean(fileName)
  const canJoin = Boolean(
    workspace && category && meetName.trim() && meetLink.trim(),
  )

  const acceptFile = async (file?: File) => {
    if (!file) return
    if (file.size > MAX_DOCUMENT_SIZE) {
      setMessage("Choose a document smaller than 10 MB.")
      return
    }
    try {
      const id = await storeDocument(file)
      setFile(file)
      setFileName(file.name)
      setFileId(id)
      setFileSize(file.size)
      setFileType(file.type)
      setMessage("")
    } catch {
      setMessage("Amber could not save this document. Please try again.")
    }
  }

  // Amber joins the call; the operator never does.
  const join = async () => {
    if (!workspace || !category) {
      setMessage("Select a workspace and meet type before sending Amber.")
      return
    }
    if (!meetName.trim() || !meetLink.trim()) {
      setMessage("Add the meet name and meeting link.")
      return
    }
    setSending(true)
    setMessage("")
    try {
      const doc = fileName && file ? { document_name: file.name, document_b64: await toBase64(file) } : {}
      const result = await api.dispatch({
        title: meetName.trim(),
        url: meetLink.trim(),
        agenda: context.trim(),
        context: category.agenda?.trim() ?? "",
        attendees: parseAttendees(attendees),
        series_id: `${workspace.id}:${category.id}`, // same meet type = same series, so Amber remembers past meetings
        ...doc,
      })
      setMessage(`Sent. Amber is ${result.status === "replay" ? "ready for a replay" : "joining the call"}…`)
      onDispatched(result.id)
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-[24px] border border-[#dce5f2] bg-white shadow-[0_12px_32px_rgba(43,67,114,0.06)]">
      <div className="border-b border-[#e8edf5] bg-gradient-to-r from-[#f7faff] to-white p-5 md:p-6">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3">
            <span
              className="grid h-14 w-12 shrink-0 place-items-end overflow-hidden"
              aria-hidden="true"
            >
              <img
                className="amber-join-peek h-14 w-auto object-contain"
                src="/assets/amber-bot-peek.svg"
                alt=""
              />
            </span>
            <div>
              <h2 className="text-xl font-extrabold tracking-[-0.025em]">
                Amber join meet.
              </h2>
              <p className="mt-1 text-sm text-[#758199]">
                Add a Google Meet, Zoom, or Microsoft Teams link and Amber will
                join right now.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {workspace && (
              <span className="inline-flex items-center rounded-full bg-white px-3 py-1.5 text-xs font-bold text-[#53617a] shadow-sm">
                {workspace.name}
              </span>
            )}
            {category && (
              <span className="inline-flex items-center rounded-full bg-[#eaf2ff] px-3 py-1.5 text-xs font-bold text-[#4974ce]">
                {category.name}
              </span>
            )}
            {(!workspace || !category) && (
              <span className="rounded-full bg-[#fff1f1] px-3 py-1.5 text-xs font-bold text-[#c04d4d]">
                Select a workspace and Meet type
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="p-5 md:p-6">
        <div className="grid gap-4 md:grid-cols-2">
          <label>
            <span className="mb-2 block text-sm font-bold text-[#34415d]">
              Meet name
            </span>
            <input
              className="w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
              value={meetName}
              onChange={(event) => {
                setMeetName(event.target.value)
                setMessage("")
              }}
              placeholder="e.g. Client check-in"
            />
          </label>
          <label>
            <span className="mb-2 block text-sm font-bold text-[#34415d]">
              Meeting link
            </span>
            <input
              className="w-full rounded-xl border border-[#cbd6e6] px-4 py-3.5 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
              type="url"
              value={meetLink}
              onChange={(event) => {
                setMeetLink(event.target.value)
                setMessage("")
              }}
              placeholder="Google Meet, Zoom, or Microsoft Teams link"
            />
          </label>
        </div>

        <label className="mt-4 block">
          <span className="mb-2 block text-sm font-bold text-[#34415d]">
            Attendees{" "}
            <span className="font-normal text-[#8792a8]">
              (one per line: Name, email — they get the recap and task reminders)
            </span>
          </span>
          <textarea
            className="h-24 w-full resize-y rounded-xl border border-[#cbd6e6] px-4 py-3 outline-none placeholder:text-[#8792a8] focus:border-[#3479f5] focus:ring-4 focus:ring-[#3479f5]/10"
            value={attendees}
            onChange={(event) => setAttendees(event.target.value)}
            placeholder={"Rahul Mehta, rahul@company.com\nPriya, priya@company.com"}
          />
        </label>

        <div className="mt-5 rounded-2xl border border-[#d7dfeb] p-4">
          <div className="flex items-center justify-between gap-3">
            <span>
              <span className="block text-sm font-bold">
                Meet context{" "}
                <span className="font-normal text-[#8792a8]">(optional)</span>
              </span>
              <span className="mt-0.5 block text-xs text-[#8792a8]">
                Choose writing or one document.
              </span>
            </span>
            <div className="flex rounded-full bg-[#eef2f8] p-1 text-xs font-semibold">
              <button
                className={`rounded-full px-3 py-1.5 ${
                  mode === "write"
                    ? "bg-white text-[#3479f5] shadow-sm"
                    : "text-[#68758f]"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                type="button"
                onClick={() => setMode("write")}
                disabled={hasUploadedContext}
              >
                Write
              </button>
              <button
                className={`rounded-full px-3 py-1.5 ${
                  mode === "upload"
                    ? "bg-white text-[#3479f5] shadow-sm"
                    : "text-[#68758f]"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                type="button"
                onClick={() => setMode("upload")}
                disabled={hasWrittenContext}
              >
                Upload
              </button>
            </div>
          </div>
          {mode === "write" ? (
            <div className="relative mt-3 h-[260px] overflow-hidden rounded-xl border border-[#d7dfeb] bg-[#f8fafd] focus-within:border-[#3479f5] focus-within:ring-4 focus-within:ring-[#3479f5]/10">
              <textarea
                className="h-full w-full resize-none bg-transparent px-4 pb-14 pt-4 outline-none placeholder:text-[#8a95a9]"
                value={context}
                onChange={(event) => setContext(event.target.value)}
                placeholder="Agenda, goals, or notes for Amber..."
              />
              <div className="absolute bottom-0 left-4 right-4 flex h-12 items-center border-t border-[#e4e9f1] bg-[#f8fafd]">
                {hasWrittenContext && (
                  <button
                    className="text-xs font-bold text-[#bd4545] hover:underline"
                    type="button"
                    onClick={() => setContext("")}
                  >
                    Clear to upload instead
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div
              className={`mt-3 h-[260px] overflow-hidden rounded-xl border text-center ${
                dragging
                  ? "border-[#3479f5] bg-[#f5f8ff]"
                  : fileName
                    ? "border-[#d8e1ee] bg-white"
                    : "border-dashed border-[#cbd6e6] bg-[#fbfcfe]"
              }`}
              onDragEnter={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                void acceptFile(event.dataTransfer.files[0])
              }}
            >
              {fileName ? (
                fileName.toLowerCase().endsWith(".pdf") ? (
                  <PdfPreview
                    fileId={fileId}
                    name={fileName}
                    onRemove={() => {
                      setFileName("")
                      setFileId(undefined)
                      setFileSize(undefined)
                      setFileType(undefined)
                    }}
                  />
                ) : (
                  <div className="p-4">
                    <UploadedDocument
                      name={fileName}
                      fileId={fileId}
                      size={fileSize}
                      type={fileType}
                      onRemove={() => {
                        setFileName("")
                        setFileId(undefined)
                        setFileSize(undefined)
                        setFileType(undefined)
                      }}
                    />
                  </div>
                )
              ) : (
                <div className="flex h-full flex-col items-center justify-center p-4">
                  <Upload className="mx-auto mb-2 h-6 w-6 text-[#3479f5]" />
                  <p className="text-sm font-semibold">
                    Drop PDF, DOC, DOCX, or TXT here
                  </p>
                  <p className="mt-1 text-xs text-[#8390a6]">
                    Maximum file size: 10 MB
                  </p>
                  <button
                    className="mt-3 text-sm font-bold text-[#3479f5]"
                    type="button"
                    onClick={() => fileInput.current?.click()}
                  >
                    Choose file
                  </button>
                </div>
              )}
              <input
                ref={fileInput}
                className="hidden"
                type="file"
                accept=".pdf,.doc,.docx,.txt"
                onChange={(event) => void acceptFile(event.target.files?.[0])}
              />
            </div>
          )}
        </div>

        <div className="mt-4 flex flex-col-reverse items-start justify-between gap-3 sm:flex-row sm:items-center">
          <p
            className={`text-sm font-semibold ${
              message.startsWith("Sent") ? "text-[#27815a]" : "text-[#c94848]"
            }`}
            role="status"
          >
            {message}
          </p>
          <button
            className="flex w-full items-center justify-center gap-2 rounded-full bg-[#3479f5] px-7 py-3 font-bold text-white hover:bg-[#2068e7] disabled:cursor-not-allowed disabled:opacity-45 sm:w-auto"
            type="button"
            onClick={() => void join()}
            disabled={!canJoin || sending}
          >
            <Video className="h-5 w-5" /> {sending ? "Sending…" : "Send Amber"}
          </button>
        </div>
      </div>
    </section>
  )
}

function EmptyDateState({
  variant,
  onAction,
}: {
  variant: "past" | "future"
  onAction: () => void
}) {
  const past = variant === "past"

  return (
    <section className="flex flex-1 flex-col items-center justify-center rounded-[28px] border border-[#e1e8f3] bg-[radial-gradient(circle_at_center,#f8fbff_0%,#ffffff_68%)] px-6 py-10 text-center shadow-[0_14px_42px_rgba(45,72,125,0.05)]">
      <div className="relative h-52 w-full max-w-[360px]" aria-hidden="true">
        <div className="absolute bottom-3 left-1/2 h-20 w-64 -translate-x-1/2 rounded-[50%] bg-[#edf3ff] blur-sm" />
        <img
          className={`absolute bottom-5 h-44 w-auto max-w-[280px] -translate-x-1/2 object-contain drop-shadow-[0_14px_24px_rgba(47,83,132,0.16)] ${
            past ? "left-1/2" : "left-[calc(50%+32px)] amber-future-jump"
          }`}
          src={
            past ? "/assets/amber-past-day.svg" : "/assets/amber-future-day.svg"
          }
          alt=""
        />
      </div>
      <h2 className="mt-3 text-3xl font-extrabold tracking-[-0.035em] md:text-4xl">
        {past ? "A quiet day" : "A little room in your day"}
      </h2>
      <p className="mt-3 max-w-[560px] text-base leading-7 text-[#68758f] md:text-lg">
        {past
          ? "No meetings were scheduled or recorded on this day."
          : "Nothing is scheduled yet. Plan ahead whenever you are ready."}
      </p>
      <button
        className="mt-7 flex min-w-[230px] items-center justify-center gap-2 rounded-full bg-[#3479f5] px-7 py-3.5 font-bold text-white shadow-[0_12px_28px_rgba(52,121,245,0.22)] hover:bg-[#2068e7]"
        type="button"
        onClick={onAction}
      >
        {past ? (
          "Go to today"
        ) : (
          <>
            <Plus className="h-5 w-5" /> Schedule a meet
          </>
        )}
      </button>
    </section>
  )
}

function MeetingDetail({
  meeting,
  meetingDate,
  workspaceName,
  onBack,
}: {
  meeting: ScheduledMeet
  meetingDate: Date
  workspaceName: string
  onBack: () => void
}) {
  const [tab, setTab] = useState<"summary" | "people" | "chat" | "tasks">(
    "summary",
  )
  const [isFullscreen, setIsFullscreen] = useState(false)
  const videoRef = useRef<HTMLDivElement>(null)
  const people = meeting.review?.participants ?? []
  const tasks = meeting.review?.tasks ?? []
  const chat = meeting.review?.chat ?? []
  const formattedDate = meetingDate.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  })

  useEffect(() => {
    const handleFullscreen = () =>
      setIsFullscreen(document.fullscreenElement === videoRef.current)
    document.addEventListener("fullscreenchange", handleFullscreen)
    return () =>
      document.removeEventListener("fullscreenchange", handleFullscreen)
  }, [])

  const toggleFullscreen = async () => {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await videoRef.current?.requestFullscreen()
  }

  const tabs = [
    { id: "summary" as const, label: "Summary", icon: FileText },
    {
      id: "people" as const,
      label: "People",
      icon: UsersRound,
      count: people.length,
    },
    { id: "chat" as const, label: "Chat", icon: MessageSquareText },
    { id: "tasks" as const, label: "Tasks", icon: ListChecks },
  ]
  const taskColors = {
    Completed: "bg-[#e5f5ed] text-[#27815a]",
    "In progress": "bg-[#fff4db] text-[#ad7300]",
    Started: "bg-[#e9f1ff] text-[#4974ce]",
    Ongoing: "bg-[#f0edff] text-[#6a62e8]",
  }

  return (
    <div className="fixed inset-0 z-[80] flex h-screen w-screen overflow-hidden bg-[#f4f7fb] text-[#111b3c]">
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(390px,58vh)_minmax(0,1fr)] overflow-hidden lg:grid-cols-[minmax(0,1fr)_420px] lg:grid-rows-1">
        <section className="flex min-h-0 min-w-0 flex-col p-4 md:p-6">
          <div className="mb-4 rounded-2xl border border-[#dde5f0] bg-white p-4 shadow-[0_8px_24px_rgba(42,61,97,0.05)]">
            <div className="flex items-center gap-3">
              <button
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#f1f4f8] text-[#53617a] transition hover:bg-[#e5eaf1] hover:text-[#273653]"
                type="button"
                onClick={onBack}
                aria-label="Back to meetings"
                title="Back to meetings"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <h2 className="min-w-0 flex-1 truncate text-xl font-extrabold tracking-[-0.025em] md:text-2xl">
                {meeting.title}
              </h2>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3 text-sm sm:grid-cols-3 xl:grid-cols-5">
              {[
                ["Date", formattedDate],
                ["Time", meeting.time],
                ["Duration", meeting.duration],
                ["Workspace", workspaceName],
                ["Meet type", meeting.type],
              ].map(([label, value]) => (
                <div key={label} className="min-w-0">
                  <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#8a96aa]">
                    {label}
                  </p>
                  <p
                    className="mt-1 truncate font-bold text-[#34415d]"
                    title={value}
                  >
                    {value}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div
            ref={videoRef}
            className="group relative mx-auto flex min-h-0 w-full flex-1 overflow-hidden rounded-[20px] bg-[#171e2c] shadow-[0_18px_48px_rgba(19,30,50,0.18)]"
          >
            {meeting.review?.recordingUrl ? (
              <video
                className="absolute inset-0 h-full w-full object-contain"
                src={meeting.review.recordingUrl}
                controls
              />
            ) : (
              <div className="absolute inset-0 grid place-items-center bg-[radial-gradient(circle_at_center,#303b50_0%,#171e2c_72%)] px-6 text-center text-white">
                <div>
                  <span className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-white/10 backdrop-blur-sm">
                    <Video className="h-7 w-7" />
                  </span>
                  <p className="mt-5 font-bold">Video is being prepared</p>
                  <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-white/60">
                    The meeting insights are ready. The video will appear here
                    when processing is complete.
                  </p>
                </div>
              </div>
            )}
            <button
              className="absolute bottom-4 right-4 grid h-11 w-11 place-items-center rounded-full bg-black/55 text-white backdrop-blur-md transition hover:bg-black/75"
              type="button"
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
            >
              {isFullscreen ? (
                <Minimize2 className="h-5 w-5" />
              ) : (
                <Maximize2 className="h-5 w-5" />
              )}
            </button>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col border-t border-[#dce4ef] bg-white shadow-[-8px_0_28px_rgba(42,61,97,0.06)] lg:border-l lg:border-t-0">
          <div className="grid grid-cols-4 border-b border-[#e6ebf2] px-2">
            {tabs.map(({ id, label, icon: Icon, count }) => (
              <button
                key={id}
                className={`flex items-center justify-center gap-2 border-b-2 px-2 py-4 text-xs font-bold transition ${
                  tab === id
                    ? "border-[#3479f5] text-[#3479f5]"
                    : "border-transparent text-[#7a869b] hover:text-[#43516c]"
                }`}
                type="button"
                onClick={() => setTab(id)}
              >
                <span className="relative">
                  <Icon className="h-4.5 w-4.5" />
                  {typeof count === "number" && (
                    <span className="absolute -right-2.5 -top-2 grid h-4 min-w-4 place-items-center rounded-full bg-[#3479f5] px-1 text-[9px] font-extrabold text-white">
                      {count}
                    </span>
                  )}
                </span>
                <span className="hidden sm:inline lg:inline">{label}</span>
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-5 md:p-6">
            {tab === "summary" && (
              <div>
                <div className="border-b border-[#e8edf4] pb-4">
                  <h3 className="text-xl font-extrabold tracking-[-0.025em]">
                    Summary
                  </h3>
                  <p className="mt-1 text-sm text-[#7a869b]">
                    The essential points from this Meet.
                  </p>
                </div>
                {meeting.review?.summary ? (
                  <div className="mt-5 rounded-2xl bg-[#f6f8fb] p-4">
                    <p className="text-sm leading-6 text-[#526079]">
                      {meeting.review.summary}
                    </p>
                  </div>
                ) : (
                  <p className="mt-5 rounded-2xl bg-[#f5f7fa] px-4 py-6 text-center text-sm text-[#7a869b]">
                    Summary is not available yet.
                  </p>
                )}
                {(meeting.review?.takeaways?.length ?? 0) > 0 && (
                  <div className="mt-6">
                    <h4 className="text-sm font-extrabold text-[#34415d]">
                      Key takeaways
                    </h4>
                    <ul className="mt-3 space-y-2.5">
                      {meeting.review?.takeaways?.map((item) => (
                        <li
                          key={item}
                          className="flex gap-3 rounded-xl border border-[#e5eaf1] bg-white p-3 text-sm leading-5 text-[#526079]"
                        >
                          <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[#eaf2ff] text-[#3479f5]">
                            <Check className="h-3 w-3" />
                          </span>
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {meeting.review?.decision && (
                  <div className="mt-6 rounded-2xl border border-[#d7e4f8] bg-[#f3f7ff] p-4">
                    <p className="text-xs font-bold uppercase tracking-[0.1em] text-[#6680b4]">
                      Decision
                    </p>
                    <p className="mt-2 text-sm font-bold leading-6 text-[#273653]">
                      {meeting.review.decision}
                    </p>
                  </div>
                )}
                {(meeting.review?.agenda?.length ?? 0) > 0 && (
                  <div className="mt-6">
                    <h4 className="text-sm font-extrabold text-[#34415d]">Agenda alignment</h4>
                    <ul className="mt-3 space-y-2">
                      {meeting.review?.agenda?.map((a) => (
                        <li key={a.item} className="rounded-xl border border-[#e5eaf1] p-3 text-sm">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-bold text-[#273653]">{a.item}</span>
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold ${
                                a.status === "covered"
                                  ? "bg-[#e5f5ed] text-[#27815a]"
                                  : a.status === "not covered"
                                    ? "bg-[#fff1f1] text-[#c04d4d]"
                                    : "bg-[#fff4db] text-[#ad7300]"
                              }`}
                            >
                              {a.status}
                            </span>
                          </div>
                          {a.notes && <p className="mt-1.5 leading-5 text-[#526079]">{a.notes}</p>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(
                  [
                    ["Decisions", meeting.review?.decisions, "bg-[#f3f7ff] border-[#d7e4f8]"],
                    ["Open questions", meeting.review?.openQuestions, "bg-[#fffaf0] border-[#f3e2bd]"],
                    ["Record updates", meeting.review?.recordUpdates, "bg-[#f2faf5] border-[#cfe9db]"],
                  ] as const
                ).map(
                  ([title, items, tone]) =>
                    (items?.length ?? 0) > 0 && (
                      <div key={title} className={`mt-6 rounded-2xl border p-4 ${tone}`}>
                        <p className="text-xs font-bold uppercase tracking-[0.1em] text-[#6680b4]">{title}</p>
                        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-[#273653]">
                          {items?.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                    ),
                )}
              </div>
            )}

            {tab === "people" && (
              <div>
                <div className="border-b border-[#e8edf4] pb-4">
                  <h3 className="text-xl font-extrabold tracking-[-0.025em]">
                    People
                  </h3>
                  <p className="mt-1 text-sm text-[#7a869b]">
                    {people.length} {people.length === 1 ? "person" : "people"}{" "}
                    joined this Meet.
                  </p>
                </div>
                <div className="mt-4 divide-y divide-[#e8edf4]">
                  {people.length ? (
                    people.map((person) => (
                      <div
                        key={person.name}
                        className="flex items-center gap-3 py-4 first:pt-0"
                      >
                        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[#e8f0ff] text-xs font-extrabold text-[#4974ce]">
                          {person.name
                            .split(" ")
                            .map((part) => part[0])
                            .join("")
                            .slice(0, 2)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-bold text-[#273653]">
                            {person.name}
                          </p>
                          <p className="mt-1 text-xs text-[#7a869b]">
                            Joined {person.joined}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-[#9aa5b7]">
                            Left
                          </p>
                          <p className="mt-1 text-xs font-bold text-[#53617a]">
                            {person.left}
                          </p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="rounded-2xl bg-[#f5f7fa] px-4 py-6 text-center text-sm text-[#7a869b]">
                      No participant data yet.
                    </p>
                  )}
                </div>
              </div>
            )}

            {tab === "chat" && (
              <div>
                <div className="border-b border-[#e8edf4] pb-4">
                  <h3 className="text-xl font-extrabold tracking-[-0.025em]">
                    Chat
                  </h3>
                  <p className="mt-1 text-sm text-[#7a869b]">
                    {chat.length} recorded{" "}
                    {chat.length === 1 ? "message" : "messages"}.
                  </p>
                </div>
                <div className="mt-5 space-y-5">
                  {chat.length ? (
                    chat.map((message, index) => (
                      <div
                        key={`${message.time}-${index}`}
                        className={`flex gap-3 ${
                          message.isAmber ? "flex-row-reverse" : ""
                        }`}
                      >
                        <span
                          className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-[11px] font-extrabold ${
                            message.isAmber
                              ? "bg-[#3479f5] text-white"
                              : "bg-[#e8edf4] text-[#526079]"
                          }`}
                        >
                          {message.isAmber
                            ? "A"
                            : message.sender
                                .split(" ")
                                .map((part) => part[0])
                                .join("")
                                .slice(0, 2)}
                        </span>
                        <div
                          className={`min-w-0 max-w-[82%] ${
                            message.isAmber ? "text-right" : ""
                          }`}
                        >
                          <div
                            className={`flex items-center gap-2 ${
                              message.isAmber ? "justify-end" : ""
                            }`}
                          >
                            <span className="text-xs font-bold text-[#34415d]">
                              {message.sender}
                            </span>
                            <span className="text-[11px] text-[#9aa5b7]">
                              {message.time}
                            </span>
                          </div>
                          <p
                            className={`mt-1.5 rounded-2xl px-4 py-3 text-left text-sm leading-5 text-[#526079] ${
                              message.isAmber
                                ? "rounded-tr-md bg-[#e9f1ff]"
                                : "rounded-tl-md bg-[#f1f4f8]"
                            }`}
                          >
                            {message.message}
                          </p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="rounded-2xl bg-[#f5f7fa] px-4 py-6 text-center text-sm text-[#7a869b]">
                      No chat messages were recorded.
                    </p>
                  )}
                </div>
              </div>
            )}

            {tab === "tasks" && (
              <div>
                <div className="border-b border-[#e8edf4] pb-4">
                  <h3 className="text-xl font-extrabold tracking-[-0.025em]">
                    Tasks
                  </h3>
                  <p className="mt-1 text-sm text-[#7a869b]">
                    {tasks.length} action{" "}
                    {tasks.length === 1 ? "item" : "items"} from this Meet.
                  </p>
                </div>
                <div className="mt-4 space-y-3">
                  {tasks.length ? (
                    tasks.map((task) => (
                      <div
                        key={task.title}
                        className="rounded-2xl border border-[#e3e9f1] bg-white p-4 shadow-[0_4px_14px_rgba(42,61,97,0.035)]"
                      >
                        <div className="flex items-start gap-3">
                          <span
                            className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border ${
                              task.status === "Completed"
                                ? "border-[#75bd98] bg-[#e5f5ed] text-[#27815a]"
                                : "border-[#b8c6da] text-transparent"
                            }`}
                          >
                            <Check className="h-3 w-3" />
                          </span>
                          <p className="text-sm font-bold leading-5 text-[#273653]">
                            {task.title}
                          </p>
                        </div>
                        <div className="mt-4 flex items-center justify-between gap-3 border-t border-[#edf0f4] pt-3">
                          <span className="text-xs font-semibold text-[#748098]">
                            {task.assignee}
                          </span>
                          <span
                            className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${taskColors[task.status]}`}
                          >
                            {task.status}
                          </span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="rounded-2xl bg-[#f5f7fa] px-4 py-6 text-center text-sm text-[#7a869b]">
                      No tasks were created.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

function ProfilePage({
  profile,
  workspaces,
  onBack,
  onSave,
}: {
  profile: UserProfile
  workspaces: Workspace[]
  onBack: () => void
  onSave: (profile: UserProfile) => void
}) {
  const [draft, setDraft] = useState(profile)
  const [saved, setSaved] = useState(false)

  const update = <Key extends keyof UserProfile,>(
    key: Key,
    value: UserProfile[Key],
  ) => {
    setDraft((current) => ({ ...current, [key]: value }))
    setSaved(false)
  }

  return (
    <div className="fixed inset-0 z-[45] overflow-y-auto bg-[#f6f8fc] lg:left-[300px]">
      <header className="sticky top-0 z-10 flex min-h-[88px] items-center justify-between border-b border-[#e1e7f0] bg-white/95 px-5 shadow-[0_2px_8px_rgba(34,53,91,0.06)] backdrop-blur-md md:px-8">
        <div className="flex items-center gap-3">
          <button
            className="grid h-10 w-10 place-items-center rounded-full border border-[#d6dfec] text-[#53617b] hover:border-[#9db1d3]"
            type="button"
            onClick={onBack}
            aria-label="Back"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <h1 className="text-xl font-extrabold tracking-[-0.025em]">
              Amber Meet Agent
            </h1>
            <p className="mt-0.5 text-xs text-[#7a869c]">
              Personality and meeting defaults
            </p>
          </div>
        </div>
        <button
          className="flex items-center gap-2 rounded-full bg-[#3479f5] px-5 py-2.5 text-sm font-bold text-white hover:bg-[#2068e7]"
          type="button"
          onClick={() => {
            onSave(draft)
            setSaved(true)
          }}
        >
          <Save className="h-4 w-4" /> {saved ? "Saved" : "Save"}
        </button>
      </header>

      <main className="mx-auto max-w-[820px] px-5 py-8 md:px-8">
        <section className="overflow-hidden rounded-[24px] border border-[#dfe6f0] bg-white p-6 shadow-[0_10px_30px_rgba(45,67,108,0.05)]">
          <div className="flex items-center gap-4">
            <span className="grid h-20 w-20 shrink-0 place-items-center overflow-hidden rounded-full bg-[#dfeaff] ring-4 ring-[#f3f7ff]">
              <img
                className="h-full w-full object-contain p-1"
                src="/assets/amber-profile.svg"
                alt="Amber Meet Agent"
              />
            </span>
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.1em] text-[#6e83aa]">
                Your meeting assistant
              </p>
              <h2 className="mt-1 text-xl font-extrabold">Amber Meet Agent</h2>
              <p className="mt-1 text-sm text-[#7a869c]">
                Joins Google Meet, Zoom, and Microsoft Teams calls, then
                prepares useful follow-ups.
              </p>
            </div>
          </div>
          <div className="mt-6 space-y-4">
            <label className="block">
              <span className="text-sm font-bold">Summary email</span>
              <span className="mt-1 block text-xs text-[#7a869c]">
                Where Amber should send meeting summaries and task reminders.
              </span>
              <input
                className="mt-2 w-full rounded-xl border border-[#cbd6e6] px-4 py-3 outline-none placeholder:text-[#98a3b5] focus:border-[#3479f5]"
                type="email"
                value={draft.email}
                onChange={(event) => update("email", event.target.value)}
                placeholder="you@company.com"
              />
            </label>
            <label className="block">
              <span className="text-sm font-bold">
                Amber&apos;s personality
              </span>
              <span className="mt-1 block text-xs text-[#7a869c]">
                Describe the tone and behavior Amber should use in summaries,
                chat, and follow-ups.
              </span>
              <div className="relative mt-2 rounded-xl border border-[#cbd6e6] px-4 py-3 focus-within:border-[#3479f5]">
                <textarea
                  className="min-h-[120px] w-full resize-none bg-transparent pb-5 outline-none placeholder:text-[#98a3b5]"
                  maxLength={300}
                  value={draft.personality}
                  onChange={(event) =>
                    update("personality", event.target.value)
                  }
                  placeholder="e.g. Concise, warm, proactive, and direct about decisions and next steps."
                />
                <span className="absolute bottom-3 right-4 text-xs text-[#8b96a9]">
                  {draft.personality.length}/300
                </span>
              </div>
            </label>
          </div>
        </section>

        <section className="mt-5 rounded-[24px] border border-[#dfe6f0] bg-white p-6 shadow-[0_10px_30px_rgba(45,67,108,0.05)]">
          <h2 className="text-lg font-extrabold">Meeting defaults</h2>
          <p className="mt-1 text-sm text-[#7a869c]">
            Applied when scheduling a new meet.
          </p>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <label>
              <span className="text-sm font-bold">Time zone</span>
              <select
                className="mt-2 w-full rounded-xl border border-[#cbd6e6] bg-white px-4 py-3 outline-none"
                value={draft.timezone}
                onChange={(event) => update("timezone", event.target.value)}
              >
                <option value="UTC">UTC</option>
                <option value="America/New_York">America/New_York</option>
                <option value="Europe/London">Europe/London</option>
                <option value="Asia/Kolkata">Asia/Kolkata</option>
              </select>
            </label>
            <label>
              <span className="text-sm font-bold">Default workspace</span>
              <select
                className="mt-2 w-full rounded-xl border border-[#cbd6e6] bg-white px-4 py-3 outline-none"
                value={draft.defaultWorkspaceId}
                onChange={(event) =>
                  update("defaultWorkspaceId", event.target.value)
                }
              >
                <option value="">No default</option>
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            className="mt-5 flex w-full items-center justify-between rounded-xl bg-[#f5f8fc] px-4 py-3.5 text-left"
            type="button"
            onClick={() => update("emailSummaries", !draft.emailSummaries)}
            aria-pressed={draft.emailSummaries}
          >
            <span>
              <span className="block text-sm font-bold">
                Email meeting summaries
              </span>
              <span className="mt-1 block text-xs text-[#7a869c]">
                Send a concise summary after completed meetings.
              </span>
            </span>
            <span
              className={`relative h-6 w-11 rounded-full transition ${
                draft.emailSummaries ? "bg-[#3479f5]" : "bg-[#cbd3df]"
              }`}
            >
              <span
                className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${
                  draft.emailSummaries ? "left-6" : "left-1"
                }`}
              />
            </span>
          </button>
        </section>
      </main>
    </div>
  )
}

function Dashboard() {
  const [today, setToday] = useState(getToday)
  const [workspaceModalOpen, setWorkspaceModalOpen] = useState(false)
  const [editWorkspaceId, setEditWorkspaceId] = useState<string | null>(null)
  const [editCategoryTarget, setEditCategoryTarget] = useState<{
    workspaceId: string
    categoryId: string
  } | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false)
  const [schedulePreset, setSchedulePreset] = useState<ScheduledMeet | null>(
    null,
  )
  const [actionMeeting, setActionMeeting] = useState<ScheduledMeet | null>(null)
  const [detailMeeting, setDetailMeeting] = useState<ScheduledMeet | null>(null)
  const [agendaTarget, setAgendaTarget] = useState<{
    date: string
    index: number
  } | null>(null)
  const [categoryWorkspaceId, setCategoryWorkspaceId] = useState<string | null>(
    null,
  )
  const [deleteTarget, setDeleteTarget] = useState<{
    kind: "workspace"
    workspaceId: string
  } | {
    kind: "category"
    workspaceId: string
    categoryId: string
  } | null>(null)
  const [selectedDate, setSelectedDate] = useState(getToday)
  const [meetingsByDate, setMeetingsByDate] =
    useState<Record<string, ScheduledMeet[]>>(() => {
      try {
        const saved = JSON.parse(
          localStorage.getItem("amber-scheduled-meetings-v2") ?? "null",
        )
        if (!saved) return dateDetails
        const demoAlreadyExists = Object.values(
          saved as Record<string, ScheduledMeet[]>,
        ).some((meetings) =>
          meetings.some(({ id }) => id === demoEndedMeeting.id),
        )
        if (demoAlreadyExists) return saved
        return {
          ...saved,
          [demoMeetingDate]: [
            ...(saved[demoMeetingDate] ?? []),
            demoEndedMeeting,
          ],
        }
      } catch {
        return dateDetails
      }
    })
  const [workspaces, setWorkspaces] = useState<Workspace[]>(() => {
    try {
      const saved = localStorage.getItem("amber-workspaces-v2")
      return saved ? JSON.parse(saved) : initialWorkspaces
    } catch {
      return initialWorkspaces
    }
  })
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState("")
  const [selectedCategoryId, setSelectedCategoryId] = useState("")
  const [storedMeetings, setStoredMeetings] = useState<StoredMeeting[]>(() => {
    try {
      return JSON.parse(
        localStorage.getItem("amber-tagged-meetings-v2") ?? "[]",
      )
    } catch {
      return []
    }
  })
  const [profile, setProfile] = useState<UserProfile>(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem("amber-profile-v2") ?? "null",
      ) as Partial<UserProfile> | null
      return {
        name: "Amber Meet Agent",
        email: saved?.email ?? "",
        personality: saved?.personality ?? "",
        timezone:
          saved?.timezone ??
          Intl.DateTimeFormat().resolvedOptions().timeZone ??
          "UTC",
        defaultWorkspaceId: saved?.defaultWorkspaceId ?? "",
        emailSummaries: saved?.emailSummaries ?? true,
      }
    } catch {
      return {
        name: "Amber Meet Agent",
        email: "",
        personality: "",
        timezone: "UTC",
        defaultWorkspaceId: "",
        emailSummaries: true,
      }
    }
  })
  // Backend meetings (dispatched Amber sessions) merged into the calendar's date-keyed map.
  const [apiMeetings, setApiMeetings] = useState<ApiMeeting[]>([])
  const [view, setView] = useState<"meetings" | "records" | "outbox">("meetings")
  const [liveMeetingId, setLiveMeetingId] = useState<number | null>(null)
  const [backendError, setBackendError] = useState("")
  const loadApiMeetings = () =>
    api
      .meetings()
      .then((list) => {
        setApiMeetings(list)
        setBackendError("")
      })
      .catch(() => setBackendError("Amber's backend isn't reachable. Start it on port 8000."))
  useEffect(() => {
    void loadApiMeetings()
  }, [])
  useAmberEvents((event) => {
    if (event.type === "meeting.status" || event.type === "meeting.recap") void loadApiMeetings()
  })
  // Show the meet type (category) name like local meetings do; the status goes in the badge.
  const withMeetType = (meet: ScheduledMeet): ScheduledMeet => {
    const category = workspaces
      .find(({ id }) => id === meet.workspaceId)
      ?.categories.find(({ id }) => id === meet.categoryId)
    return category ? { ...meet, type: category.name } : meet
  }
  const displayByDate: Record<string, ScheduledMeet[]> = { ...meetingsByDate }
  for (const m of [...apiMeetings].reverse()) {
    const key = apiDateKey(m)
    displayByDate[key] = [...(displayByDate[key] ?? []), withMeetType(toScheduledMeet(m))]
  }
  const openApiMeeting = async (apiId: number) => {
    const m = apiMeetings.find(({ id }) => id === apiId)
    if (m && isLive(m.status)) {
      setLiveMeetingId(apiId)
      return
    }
    try {
      setDetailMeeting(withMeetType(toReviewMeet(await api.meeting(apiId))))
    } catch (e) {
      setBackendError((e as Error).message)
    }
  }
  const selectedMeetings = displayByDate[dateKey(selectedDate)] ?? []
  const weekDates = Array.from({ length: 7 }, (_, index) =>
    addDays(startOfWeek(selectedDate), index),
  )
  const isPastDate = selectedDate < today && !sameDay(selectedDate, today)
  const heading = selectedDate.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  })
  const selectedWorkspace = workspaces.find(
    ({ id }) => id === selectedWorkspaceId,
  )
  const selectedCategory = selectedWorkspace?.categories.find(
    ({ id }) => id === selectedCategoryId,
  )
  const categoryWorkspace = workspaces.find(
    ({ id }) => id === categoryWorkspaceId,
  )
  const editWorkspace = workspaces.find(({ id }) => id === editWorkspaceId)
  const editCategoryWorkspace = workspaces.find(
    ({ id }) => id === editCategoryTarget?.workspaceId,
  )
  const editCategory = editCategoryWorkspace?.categories.find(
    ({ id }) => id === editCategoryTarget?.categoryId,
  )
  const deleteWorkspace = deleteTarget
    ? workspaces.find(({ id }) => id === deleteTarget.workspaceId)
    : undefined
  const deleteCategory =
    deleteTarget?.kind === "category"
      ? deleteWorkspace?.categories.find(
          ({ id }) => id === deleteTarget.categoryId,
        )
      : undefined
  const meetingCounts = storedMeetings.reduce<Record<string, number>>(
    (counts, meeting) => {
      const key = `${meeting.workspaceId}:${meeting.categoryId}`
      counts[key] = (counts[key] ?? 0) + 1
      return counts
    },
    {},
  )

  const saveLocal = (key: string, value: unknown) => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // IndexedDB stores document contents; localStorage only keeps lightweight references.
    }
  }

  useEffect(() => {
    saveLocal("amber-workspaces-v2", workspaces)
  }, [workspaces])

  useEffect(() => {
    saveLocal("amber-tagged-meetings-v2", storedMeetings)
  }, [storedMeetings])

  useEffect(() => {
    saveLocal("amber-scheduled-meetings-v2", meetingsByDate)
  }, [meetingsByDate])

  useEffect(() => {
    saveLocal("amber-profile-v2", profile)
  }, [profile])

  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = getToday()
      setToday((previous) => (sameDay(previous, current) ? previous : current))
    }, 60_000)
    return () => window.clearInterval(timer)
  }, [])

  const createWorkspace = (
    name: string,
    categoryName: string,
    agenda: string,
  ) => {
    const id = `workspace-${Date.now()}`
    const categoryId = `${categoryName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now()}`
    setWorkspaces((current) => [
      ...current,
      {
        id,
        name,
        categories: [{ id: categoryId, name: categoryName, agenda }],
      },
    ])
    setSelectedWorkspaceId(id)
    setSelectedCategoryId(categoryId)
    setWorkspaceModalOpen(false)
  }

  const createCategory = (name: string, agenda: string) => {
    if (!categoryWorkspaceId) return
    const id = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now()}`
    setWorkspaces((current) =>
      current.map((workspace) =>
        workspace.id === categoryWorkspaceId
          ? {
              ...workspace,
              categories: [...workspace.categories, { id, name, agenda }],
            }
          : workspace,
      ),
    )
    setSelectedWorkspaceId(categoryWorkspaceId)
    setSelectedCategoryId(id)
    setCategoryWorkspaceId(null)
  }

  const scheduleMeeting = (draft: ScheduleDraft) => {
    const workspace = workspaces.find(({ id }) => id === draft.workspaceId)
    const category = workspace?.categories.find(
      ({ id }) => id === draft.categoryId,
    )
    if (!workspace || !category) return
    const firstDate = new Date(`${draft.startDate}T12:00:00`)
    const dates: Date[] = []
    const total = draft.recurrence === "once" ? 1 : draft.occurrences
    let current = firstDate

    for (let index = 0; index < total; index += 1) {
      dates.push(new Date(current))
      if (draft.recurrence === "daily") {
        current = addDays(current, 1)
      } else if (draft.recurrence === "weekdays") {
        do current = addDays(current, 1)
        while (current.getDay() === 0 || current.getDay() === 6)
      } else if (draft.recurrence === "monthly") {
        current = new Date(
          current.getFullYear(),
          current.getMonth() + 1,
          current.getDate(),
        )
      } else {
        current = addDays(current, 7)
      }
    }

    const displayTime = new Date(`2026-01-01T${draft.time}`).toLocaleTimeString(
      "en-US",
      { hour: "numeric", minute: "2-digit" },
    )
    const meeting: ScheduledMeet = {
      title: draft.title,
      time: displayTime,
      duration: draft.duration === "60" ? "1 hr" : `${draft.duration} min`,
      type: category.name,
      status: "upcoming",
      workspaceId: workspace.id,
      categoryId: category.id,
      link: draft.link,
    }
    setMeetingsByDate((currentMeetings) => {
      const next = { ...currentMeetings }
      dates.forEach((date, index) => {
        const key = dateKey(date)
        next[key] = [
          ...(next[key] ?? []),
          { ...meeting, id: `scheduled-${Date.now()}-${key}-${index}` },
        ]
      })
      return next
    })
    setScheduleModalOpen(false)
    setSchedulePreset(null)
    setSelectedDate(firstDate)
  }

  const confirmDelete = () => {
    if (!deleteTarget) return

    if (deleteTarget.kind === "workspace") {
      setWorkspaces((current) =>
        current.filter(({ id }) => id !== deleteTarget.workspaceId),
      )
      setStoredMeetings((current) =>
        current.filter(
          ({ workspaceId }) => workspaceId !== deleteTarget.workspaceId,
        ),
      )
      if (selectedWorkspaceId === deleteTarget.workspaceId) {
        setSelectedWorkspaceId("")
        setSelectedCategoryId("")
      }
    } else {
      setWorkspaces((current) =>
        current.map((workspace) =>
          workspace.id === deleteTarget.workspaceId
            ? {
                ...workspace,
                categories: workspace.categories.filter(
                  ({ id }) => id !== deleteTarget.categoryId,
                ),
              }
            : workspace,
        ),
      )
      setStoredMeetings((current) =>
        current.filter(
          ({ workspaceId, categoryId }) =>
            !(
              workspaceId === deleteTarget.workspaceId &&
              categoryId === deleteTarget.categoryId
            ),
        ),
      )
      if (
        selectedWorkspaceId === deleteTarget.workspaceId &&
        selectedCategoryId === deleteTarget.categoryId
      ) {
        setSelectedCategoryId("")
      }
    }

    setDeleteTarget(null)
  }

  const saveAgenda = (
    context: string,
    fileName: string,
    fileId?: string,
    fileSize?: number,
    fileType?: string,
  ) => {
    if (!agendaTarget) return
    setMeetingsByDate((current) => ({
      ...current,
      [agendaTarget.date]: (current[agendaTarget.date] ?? []).map(
        (meeting, index) =>
          index === agendaTarget.index
            ? { ...meeting, context, fileName, fileId, fileSize, fileType }
            : meeting,
      ),
    }))
    setAgendaTarget(null)
  }

  const saveCategory = (name: string, agenda: string) => {
    if (!editCategoryTarget) return
    setWorkspaces((current) =>
      current.map((workspace) =>
        workspace.id === editCategoryTarget.workspaceId
          ? {
              ...workspace,
              categories: workspace.categories.map((category) =>
                category.id === editCategoryTarget.categoryId
                  ? { ...category, name, agenda }
                  : category,
              ),
            }
          : workspace,
      ),
    )
    setEditCategoryTarget(null)
  }

  const goToToday = () => setSelectedDate(new Date(today))
  const sidebarProps = {
    onNewWorkspace: () => setWorkspaceModalOpen(true),
    onNewCategory: setCategoryWorkspaceId,
    selectedDate,
    onSelectDate: setSelectedDate,
    meetingsByDate: displayByDate,
    workspaces,
    selectedWorkspaceId,
    selectedCategoryId,
    onSelectCategory: (workspaceId: string, categoryId: string) => {
      setSelectedWorkspaceId(workspaceId)
      setSelectedCategoryId(categoryId)
    },
    onEditWorkspace: setEditWorkspaceId,
    onEditCategory: (workspaceId: string, categoryId: string) =>
      setEditCategoryTarget({ workspaceId, categoryId }),
    onOpenProfile: () => setProfileOpen(true),
    profile,
    meetingCounts,
    today,
  }

  return (
    <main className="flex h-screen overflow-hidden bg-white text-[#111b3c]">
      <Sidebar {...sidebarProps} />
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-[70] flex bg-[#111b3c]/45 backdrop-blur-sm lg:hidden"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setMobileNavOpen(false)
          }}
        >
          <Sidebar
            {...sidebarProps}
            mobile
            onClose={() => setMobileNavOpen(false)}
            onOpenProfile={() => {
              setMobileNavOpen(false)
              setProfileOpen(true)
            }}
          />
        </div>
      )}
      <section className="stable-scrollbar flex min-w-0 flex-1 flex-col overflow-y-auto">
        <div className="flex items-center justify-between border-b border-[#e8edf5] px-5 py-4 lg:hidden">
          <button
            className="grid h-11 w-11 place-items-center rounded-full border border-[#d7e0ed] bg-white text-[#43516c]"
            type="button"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open calendar and workspaces"
          >
            <Menu className="h-5 w-5" />
          </button>
          <AmberLogo compact />
          <button
            className="grid h-11 w-11 place-items-center rounded-full bg-[#3479f5] text-white"
            type="button"
            onClick={() => {
              setSchedulePreset(null)
              setScheduleModalOpen(true)
            }}
            aria-label="Schedule a meet"
          >
            <Plus className="h-5 w-5" />
          </button>
        </div>
        <header className="sticky-date-header sticky top-0 z-30 flex min-h-[88px] w-full flex-col justify-between gap-5 bg-white/95 px-5 backdrop-blur-md md:grid md:grid-cols-[240px_minmax(0,1fr)] md:items-center md:px-8 xl:px-10">
          <div className="flex min-w-0 items-center gap-4">
            <div>
              <h1 className="mt-0.5 truncate text-3xl font-extrabold tabular-nums tracking-[-0.04em]">
                {heading}
              </h1>
            </div>
            {sameDay(selectedDate, today) && (
              <span className="rounded-full border border-[#d7e0ef] px-5 py-2 text-sm font-semibold">
                Today
              </span>
            )}
          </div>
          <div className="flex items-center justify-end gap-1 overflow-x-auto">
            <button
              className="shrink-0 rounded-lg p-2 hover:bg-[#f5f7fb]"
              type="button"
              aria-label="Previous week"
              onClick={() => setSelectedDate((date) => addDays(date, -7))}
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            {weekDates.map((date) => {
              const active = sameDay(date, selectedDate)
              const hasMeetings =
                (displayByDate[dateKey(date)] ?? []).length > 0
              const label = date
                .toLocaleDateString("en-US", { weekday: "short" })
                .toUpperCase()
              return (
                <button
                  key={dateKey(date)}
                  className={`relative flex min-w-14 flex-col items-center rounded-2xl px-3 py-2 text-xs font-semibold transition ${
                    active
                      ? "bg-[#e8f0ff] text-[#3479f5]"
                      : "text-[#34415d] hover:bg-[#f7f9fc]"
                  }`}
                  type="button"
                  onClick={() => setSelectedDate(date)}
                  aria-pressed={active}
                >
                  <span>{label}</span>
                  <span className="mt-1 text-base font-bold tabular-nums">
                    {date.getDate()}
                  </span>
                  {hasMeetings && (
                    <span
                      className={`absolute bottom-1 h-1 w-1 rounded-full ${
                        active ? "bg-[#3479f5]" : "bg-[#8ea7d0]"
                      }`}
                    />
                  )}
                </button>
              )
            })}
            <button
              className="shrink-0 rounded-lg p-2 hover:bg-[#f5f7fb]"
              type="button"
              aria-label="Next week"
              onClick={() => setSelectedDate((date) => addDays(date, 7))}
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>
        </header>

        <nav className="mx-auto flex w-full max-w-[1240px] gap-2 px-5 pt-3 md:px-8 xl:px-10" aria-label="Sections">
          {(
            [
              ["meetings", "Meetings"],
              ["records", "Records"],
              ["outbox", "Outbox"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              className={`rounded-full px-4 py-2 text-sm font-bold transition ${
                view === id && liveMeetingId === null
                  ? "bg-[#e8f0ff] text-[#3479f5]"
                  : "text-[#53617a] hover:bg-[#f5f7fb]"
              }`}
              type="button"
              aria-current={view === id ? "page" : undefined}
              onClick={() => {
                setView(id)
                setLiveMeetingId(null)
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        {backendError && (
          <p className="mx-auto mt-3 w-full max-w-[940px] rounded-xl bg-[#fff1f1] px-4 py-2.5 text-sm font-semibold text-[#c04d4d]">
            {backendError}
          </p>
        )}

        {detailMeeting ? (
          <MeetingDetail
            meeting={detailMeeting}
            meetingDate={selectedDate}
            workspaceName={
              workspaces.find(({ id }) => id === detailMeeting.workspaceId)
                ?.name ?? "Amber"
            }
            onBack={() => setDetailMeeting(null)}
          />
        ) : liveMeetingId !== null ? (
          <LiveMeeting
            meetingId={liveMeetingId}
            onBack={() => setLiveMeetingId(null)}
            onOpenRecap={(m) => {
              setLiveMeetingId(null)
              setDetailMeeting(withMeetType(toReviewMeet(m)))
            }}
          />
        ) : view === "records" ? (
          <RecordsPage />
        ) : view === "outbox" ? (
          <OutboxPage />
        ) : (
          <div className="relative mx-auto mt-5 flex w-full max-w-[1240px] flex-1 flex-col gap-6 px-5 pb-8 md:px-8 xl:px-10">
            {sameDay(selectedDate, today) && (
              <>
                <div
                  className="pointer-events-none absolute left-0 top-[42%] hidden -translate-y-1/2 min-[1680px]:block"
                  aria-hidden="true"
                >
                  <div className="h-40 w-32 rounded-full bg-[radial-gradient(circle,#eef5ff_0%,transparent_68%)]" />
                  <img
                    className="absolute left-0 top-1/2 w-32 -translate-y-1/2 object-contain"
                    src="/assets/amber-assistant.svg"
                    alt=""
                  />
                </div>
                <div
                  className="pointer-events-none absolute bottom-4 right-0 hidden min-[1680px]:block"
                  aria-hidden="true"
                >
                  <div className="absolute bottom-0 right-0 h-44 w-32 rounded-full bg-[radial-gradient(circle_at_bottom,#eef5ff_0%,transparent_70%)]" />
                  <img
                    className="relative w-28 object-contain"
                    src="/assets/meeting-checklist.svg"
                    alt=""
                  />
                </div>
              </>
            )}
            {selectedMeetings.length === 0 ? (
              sameDay(selectedDate, today) ? (
                <>
                  <div className="mx-auto flex w-full max-w-[940px] flex-col justify-between gap-4 rounded-[24px] border border-[#dce5f2] bg-gradient-to-r from-[#f8fbff] to-white px-6 py-5 sm:flex-row sm:items-center">
                    <div className="flex items-center gap-4">
                      <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-[#eaf2ff] text-[#3479f5]">
                        <CalendarDays className="h-6 w-6" />
                      </span>
                      <div>
                        <h2 className="text-lg font-extrabold">
                          No meetings scheduled today
                        </h2>
                        <p className="mt-1 text-sm text-[#758199]">
                          Join an unscheduled Meet below or plan one for later.
                        </p>
                      </div>
                    </div>
                    <button
                      className="flex shrink-0 items-center justify-center gap-2 rounded-full border border-[#bfcde3] bg-white px-5 py-2.5 text-sm font-bold text-[#3479f5] hover:border-[#3479f5]"
                      type="button"
                      onClick={() => {
                        setSchedulePreset(null)
                        setScheduleModalOpen(true)
                      }}
                    >
                      <CalendarDays className="h-4 w-4" /> Schedule meet
                    </button>
                  </div>
                  <div className="mx-auto w-full max-w-[940px]">
                    <QuickJoinCard
                      workspace={selectedWorkspace}
                      category={selectedCategory}
                      onDispatched={(id) => {
                        void loadApiMeetings()
                        setLiveMeetingId(id)
                      }}
                    />
                  </div>
                </>
              ) : (
                <EmptyDateState
                  variant={isPastDate ? "past" : "future"}
                  onAction={
                    isPastDate
                      ? goToToday
                      : () => {
                          setSchedulePreset(null)
                          setScheduleModalOpen(true)
                        }
                  }
                />
              )
            ) : (
              <>
                <div className="mx-auto w-full max-w-[940px] pt-4">
                  <div className="mb-5 flex items-end justify-between gap-4">
                    <div>
                      <p className="text-sm font-semibold uppercase tracking-[0.12em] text-[#7a87a0]">
                        {sameDay(selectedDate, today)
                          ? "Today"
                          : isPastDate
                            ? "Meeting history"
                            : "Your schedule"}
                      </p>
                      <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.03em] md:text-3xl">
                        {selectedMeetings.length}{" "}
                        {selectedMeetings.length === 1 ? "meeting" : "meetings"}{" "}
                        {sameDay(selectedDate, today)
                          ? "today"
                          : isPastDate
                            ? "completed"
                            : "scheduled"}
                      </h2>
                    </div>
                    {!isPastDate && (
                      <button
                        className="hidden items-center gap-2 rounded-full border border-[#bfd0e7] bg-[#f7faff] px-5 py-2.5 text-sm font-bold text-[#3479f5] transition hover:border-[#3479f5] hover:bg-[#eef4ff] sm:flex"
                        type="button"
                        onClick={() => {
                          setSchedulePreset(null)
                          setScheduleModalOpen(true)
                        }}
                      >
                        <CalendarDays className="h-4 w-4" /> Schedule meet
                      </button>
                    )}
                  </div>
                  <div className="space-y-3">
                    {selectedMeetings.map((meeting, index) => {
                      const apiId = meeting.id?.startsWith("api-")
                        ? Number(meeting.id.slice(4))
                        : null
                      const completed =
                        meeting.status === "ended" || (apiId === null && isPastDate)
                      const clickable = completed || apiId !== null
                      const open = () =>
                        apiId !== null
                          ? void openApiMeeting(apiId)
                          : completed && setDetailMeeting(meeting)
                      const meetingWorkspace = workspaces.find(
                        ({ id }) => id === meeting.workspaceId,
                      )
                      const hasDailyAgenda = Boolean(
                        meeting.context?.trim() || meeting.fileName,
                      )
                      return (
                        <div
                          key={meeting.id ?? `${meeting.title}-${meeting.time}`}
                          className={`flex w-full items-center gap-4 rounded-2xl border border-[#dce5f2] bg-white p-4 text-left shadow-[0_8px_24px_rgba(43,67,114,0.05)] md:p-5 ${
                            clickable
                              ? "cursor-pointer transition hover:-translate-y-0.5 hover:border-[#b9cbea] hover:shadow-[0_12px_28px_rgba(43,67,114,0.09)]"
                              : ""
                          }`}
                          role={clickable ? "button" : undefined}
                          tabIndex={clickable ? 0 : undefined}
                          onClick={open}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") open()
                          }}
                        >
                          <span
                            className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${
                              index % 2 === 0
                                ? "bg-[#eeebff] text-[#6a62e8]"
                                : "bg-[#e9f3ff] text-[#3479f5]"
                            }`}
                          >
                            <Video className="h-6 w-6" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-base font-bold text-[#19233f] md:text-lg">
                              {meeting.title}
                            </span>
                            <span className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-[#66738b]">
                              <span className="inline-flex items-center gap-1.5">
                                <Clock3 className="h-3.5 w-3.5" />
                                {meeting.time}
                                <span className="text-[#a1acc0]">·</span>
                                {meeting.duration}
                              </span>
                              {meetingWorkspace && (
                                <span className="inline-flex items-center rounded-full bg-[#f1f4f8] px-2.5 py-1 text-[#53617a]">
                                  {meetingWorkspace.name}
                                </span>
                              )}
                              <span className="inline-flex items-center rounded-full bg-[#eef4ff] px-2.5 py-1 text-[#4974ce]">
                                {meeting.type}
                              </span>
                            </span>
                          </span>
                          {!completed && apiId === null && (
                            <button
                              className={`flex shrink-0 items-center gap-1.5 rounded-full px-3 py-2 text-xs font-bold transition sm:px-4 sm:py-2.5 ${
                                hasDailyAgenda
                                  ? "border border-[#c9d5e7] text-[#4974ce] hover:border-[#3479f5] hover:bg-[#f7faff]"
                                  : "bg-[#3479f5] text-white shadow-[0_6px_16px_rgba(52,121,245,0.2)] hover:bg-[#2068e7]"
                              }`}
                              type="button"
                              onClick={() =>
                                setAgendaTarget({
                                  date: dateKey(selectedDate),
                                  index,
                                })
                              }
                            >
                              {hasDailyAgenda ? (
                                <PencilLine className="h-3.5 w-3.5" />
                              ) : (
                                <Plus className="h-3.5 w-3.5" />
                              )}
                              <span className="hidden sm:inline">
                                {hasDailyAgenda
                                  ? "Edit agenda"
                                  : "Today’s agenda"}
                              </span>
                              <span className="sm:hidden">
                                {hasDailyAgenda ? "Edit" : "Agenda"}
                              </span>
                            </button>
                          )}
                          <span
                            className={`hidden rounded-full px-3 py-1.5 text-xs font-semibold sm:inline-flex ${
                              completed
                                ? "bg-[#edf7f1] text-[#2c8d61]"
                                : "bg-[#eef4ff] text-[#4974ce]"
                            }`}
                          >
                            {apiId !== null
                              ? statusLabel(apiMeetings.find(({ id }) => id === apiId)?.status ?? "")
                              : completed
                                ? "Completed"
                                : "Upcoming"}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
                {sameDay(selectedDate, today) && (
                  <div className="mx-auto w-full max-w-[940px]">
                    <QuickJoinCard
                      workspace={selectedWorkspace}
                      category={selectedCategory}
                      onDispatched={(id) => {
                        void loadApiMeetings()
                        setLiveMeetingId(id)
                      }}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </section>
      {workspaceModalOpen && (
        <WorkspaceModal
          onClose={() => setWorkspaceModalOpen(false)}
          onSave={createWorkspace}
        />
      )}
      {categoryWorkspace && (
        <CategoryModal
          workspaceName={categoryWorkspace.name}
          onClose={() => setCategoryWorkspaceId(null)}
          onSave={createCategory}
        />
      )}
      {editWorkspace && (
        <RenameWorkspaceModal
          workspace={editWorkspace}
          onClose={() => setEditWorkspaceId(null)}
          onDelete={() => {
            setEditWorkspaceId(null)
            setDeleteTarget({
              kind: "workspace",
              workspaceId: editWorkspace.id,
            })
          }}
          onSave={(name) => {
            setWorkspaces((current) =>
              current.map((workspace) =>
                workspace.id === editWorkspace.id
                  ? { ...workspace, name }
                  : workspace,
              ),
            )
            setEditWorkspaceId(null)
          }}
        />
      )}
      {editCategoryWorkspace && editCategory && (
        <CategoryModal
          workspaceName={editCategoryWorkspace.name}
          category={editCategory}
          onClose={() => setEditCategoryTarget(null)}
          onDelete={() => {
            setEditCategoryTarget(null)
            setDeleteTarget({
              kind: "category",
              workspaceId: editCategoryWorkspace.id,
              categoryId: editCategory.id,
            })
          }}
          onSave={saveCategory}
        />
      )}
      {agendaTarget &&
        meetingsByDate[agendaTarget.date]?.[agendaTarget.index] && (
          <EditAgendaModal
            meeting={meetingsByDate[agendaTarget.date][agendaTarget.index]}
            overallAgenda={
              workspaces
                .find(
                  ({ id }) =>
                    id ===
                    meetingsByDate[agendaTarget.date][agendaTarget.index]
                      .workspaceId,
                )
                ?.categories.find(
                  ({ id }) =>
                    id ===
                    meetingsByDate[agendaTarget.date][agendaTarget.index]
                      .categoryId,
                )?.agenda
            }
            onClose={() => setAgendaTarget(null)}
            onSave={saveAgenda}
          />
        )}
      {scheduleModalOpen && (
        <ScheduleMeetModal
          workspaces={workspaces}
          initialWorkspaceId={
            schedulePreset?.workspaceId ?? selectedWorkspaceId
          }
          initialCategoryId={schedulePreset?.categoryId ?? selectedCategoryId}
          initialMeeting={schedulePreset}
          initialDate={dateKey(selectedDate)}
          onClose={() => {
            setScheduleModalOpen(false)
            setSchedulePreset(null)
          }}
          onSave={scheduleMeeting}
        />
      )}
      {actionMeeting && (
        <MeetActionModal
          meeting={actionMeeting}
          onClose={() => setActionMeeting(null)}
          onSchedule={() => {
            setSchedulePreset(actionMeeting)
            setActionMeeting(null)
            setScheduleModalOpen(true)
          }}
        />
      )}
      {deleteTarget && deleteWorkspace && (
        <DeleteDialog
          title={
            deleteTarget.kind === "workspace"
              ? `Delete ${deleteWorkspace.name}?`
              : `Delete ${deleteCategory?.name ?? "category"}?`
          }
          message={
            deleteTarget.kind === "workspace"
              ? `This removes the workspace, all ${deleteWorkspace.categories.length} categories, and every meeting stored inside it. This cannot be undone.`
              : `This removes the category and its ${meetingCounts[`${deleteTarget.workspaceId}:${deleteTarget.categoryId}`] ?? 0} stored meetings. This cannot be undone.`
          }
          onClose={() => setDeleteTarget(null)}
          onConfirm={confirmDelete}
        />
      )}
      {profileOpen && (
        <ProfilePage
          profile={profile}
          workspaces={workspaces}
          onBack={() => setProfileOpen(false)}
          onSave={setProfile}
        />
      )}
    </main>
  )
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(false)

  useEffect(() => {
    const timers = new Map<Element, ReturnType<typeof setTimeout>>()
    const handleScroll = (event: Event) => {
      const target =
        event.target instanceof Document
          ? document.documentElement
          : event.target instanceof Element
            ? event.target
            : document.documentElement
      target.classList.add("is-scrolling")
      const currentTimer = timers.get(target)
      if (currentTimer) clearTimeout(currentTimer)
      timers.set(
        target,
        setTimeout(() => {
          target.classList.remove("is-scrolling")
          timers.delete(target)
        }, 700),
      )
    }

    window.addEventListener("scroll", handleScroll, true)
    return () => {
      window.removeEventListener("scroll", handleScroll, true)
      timers.forEach((timer) => clearTimeout(timer))
    }
  }, [])

  return authenticated ? (
    <Dashboard />
  ) : (
    <LandingPage onContinue={() => setAuthenticated(true)} />
  )
}
