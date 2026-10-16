// Demo seed data — shown on first load to illustrate the recap/review view
import { addDays, dateKey, getToday, type ScheduledMeet } from "./types"

export const demoEndedMeeting: ScheduledMeet = {
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
        message: "I captured the preview reliability discussion as a follow-up.",
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

export const demoMeetingDate = dateKey(addDays(getToday(), -1))

export const initialDateDetails: Record<string, ScheduledMeet[]> = {
  [demoMeetingDate]: [demoEndedMeeting],
}
