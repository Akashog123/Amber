import { useRef, useState } from "react"
import { Upload, X } from "lucide-react"
import { dateKey, addDays, getToday, meetingTypes, MAX_DOCUMENT_SIZE, type NewMeetDraft } from "../types"
import { storeDocument } from "../documentUtils"

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
        : `${frequencyLabel} at ${new Date(`2026-01-01T${time}`).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })} Â· ${occurrences} meetings`

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

