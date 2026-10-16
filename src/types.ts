// Shared types and constants used across the Amber dashboard
import {
  BriefcaseBusiness,
  Code2,
  FileText,
  ListChecks,
  MoreHorizontal,
  Palette,
  UserRound,
  UsersRound,
} from "lucide-react"

export const meetingTypes = [
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

export const getToday = () => {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

export const dateKey = (date: Date) =>
  [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-")

export const sameDay = (first: Date, second: Date) =>
  dateKey(first) === dateKey(second)

export const addDays = (date: Date, amount: number) => {
  const next = new Date(date)
  next.setDate(next.getDate() + amount)
  return next
}

export const startOfWeek = (date: Date) => addDays(date, -date.getDay())

export const calendarDays = (month: Date) => {
  const first = new Date(month.getFullYear(), month.getMonth(), 1)
  const start = addDays(first, -first.getDay())
  return Array.from({ length: 42 }, (_, index) => addDays(start, index))
}

export type ScheduledMeet = {
  id?: string
  title: string
  time: string
  duration: string
  type: string
  status?: "upcoming" | "ended"
  workspaceId?: string
  categoryId?: string
  link?: string
  context?: string
  fileName?: string
  fileId?: string
  fileSize?: number
  fileType?: string
  review?: {
    summary?: string
    takeaways?: string[]
    decision?: string
    participants?: { name: string; joined: string; left: string }[]
    chat?: { sender: string; time: string; message: string; isAmber?: boolean }[]
    tasks?: { title: string; assignee: string; status: "Completed" | "In progress" | "Started" | "Ongoing" }[]
    recordingUrl?: string
    // From the backend MOM
    decisions?: string[]
    openQuestions?: string[]
    agenda?: { item: string; status: string; notes: string }[]
    recordUpdates?: string[]
  }
}

export type ScheduleDraft = {
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

export type Workspace = {
  id: string
  name: string
  categories: { id: string; name: string; agenda?: string }[]
}

export type StoredMeeting = {
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

export type UserProfile = {
  name: string
  email: string
  personality: string
  timezone: string
  defaultWorkspaceId: string
  emailSummaries: boolean
}

export type NewMeetDraft = {
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

export const MAX_DOCUMENT_SIZE = 10 * 1024 * 1024

export const formatFileSize = (bytes?: number) => {
  if (!bytes) return ""
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
