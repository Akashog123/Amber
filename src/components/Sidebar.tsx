import { useEffect, useRef, useState } from "react"
import { Check, ChevronDown, ChevronLeft, ChevronRight, PencilLine, Plus, Settings, X } from "lucide-react"
import { sameDay, dateKey, calendarDays, addDays, type ScheduledMeet, type Workspace, type UserProfile } from "../types"
import { AmberLogo } from "./AmberLogo"

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

