"""Replay a scripted meeting through the real webhook handler, no bot needed.

  uv run python replay.py                 # dispatch a new replay meeting and play the script
  uv run python replay.py --speed 0       # no delays (tests)
  uv run python replay.py --bot <bot_id>  # feed an existing meeting

Payloads mirror Recall's real-time webhook shapes (docs.recall.ai/docs/real-time-event-payloads).
"""
import argparse
import os
import time
from datetime import datetime, timezone

import httpx

ATTENDEES = [
    {"name": "Akash", "email": ""},
    {"name": "Rahul", "email": ""},
    {"name": "Priya", "email": ""},
]
AGENDA = "1. Pump order status (PO-1041)\n2. Chiller #2 vibration and service contract\n3. PPE kit ordering"

# (seconds into meeting, event, speaker, text)
SCRIPT = [
    (0, "join", "Akash", None),
    (1, "join", "Rahul", None),
    (2, "join", "Priya", None),
    (4, "say", "Akash", "Okay let's start. First item is the chiller, it's been vibrating a lot this week."),
    (9, "say", "Priya", "Yes, Chiller two flagged high vibration again on Tuesday. We should get the service contract renewed."),
    (15, "say", "Akash", "Agreed. Amber, what's the status of the pump order?"),
    (22, "say", "Rahul", "Amber, what was last quarter's marketing spend?"),
    (28, "say", "Akash", "Rahul, can you get the final vendor quote for the pump by Friday?"),
    (32, "say", "Rahul", "Yes, I'll send the vendor quote by Friday."),
    (36, "say", "Priya", "Also the pump delivery slipped by two weeks, vendor told me yesterday."),
    (41, "chat", "Priya", "Amber, who owns the chiller service contract?"),
    (45, "say", "Akash", "Priya, please close the PPE kit order by next Wednesday."),
    (49, "say", "Priya", "Sure, I'll place the PPE order by Wednesday."),
    (53, "say", "Akash", "We still haven't decided whether to replace or repair the compressor. Let's take that next week."),
    # Ambiguous on purpose: two Grundfos pump orders exist (PO-1041, PO-1046), so Amber asks in chat first.
    (55, "say", "Rahul", "One more thing, the Grundfos shipment is delayed to next month."),
    (57, "say", "Akash", "Okay, noted. Let's wrap up."),
    (66, "chat", "Rahul", "2"),
    (68, "leave", "Rahul", None),
    (69, "leave", "Priya", None),
    (70, "leave", "Akash", None),
    (71, "bot", None, "done"),
]

PIDS = {name: i + 100 for i, name in enumerate(a["name"] for a in ATTENDEES)}


def payload(bot_id: str, t: float, kind: str, who: str | None, text: str | None) -> dict:
    if kind == "bot":
        return {"event": f"bot.{text}", "data": {"data": {"code": text}, "bot": {"id": bot_id}}}
    participant = {"id": PIDS[who], "name": who, "is_host": who == "Akash", "platform": "desktop",
                   "extra_data": {}, "email": None}
    bot = {"id": bot_id, "metadata": {}}
    if kind == "say":
        words = [{"text": w, "start_timestamp": {"relative": t + i * 0.3},
                  "end_timestamp": {"relative": t + i * 0.3 + 0.25}} for i, w in enumerate(text.split())]
        return {"event": "transcript.data",
                "data": {"data": {"words": words, "language_code": "en", "participant": participant}, "bot": bot}}
    ts = {"absolute": datetime.now(timezone.utc).isoformat(), "relative": t}
    event = {"join": "participant_events.join", "leave": "participant_events.leave",
             "chat": "participant_events.chat_message"}[kind]
    return {"event": event, "data": {"data": {"participant": participant, "timestamp": ts,
                                              "data": {"text": text, "to": "everyone"} if text else None},
                                     "bot": bot}}


def run(client: httpx.Client, bot_id: str | None = None, speed: float = 1.0) -> int:
    if not bot_id:
        r = client.post("/api/meetings/dispatch", json={
            "title": "Weekly Procurement Sync (replay)", "url": "https://meet.google.com/abc-defg-hij",
            "agenda": AGENDA, "attendees": ATTENDEES, "series_id": "weekly-procurement", "replay": True})
        r.raise_for_status()
        bot_id = r.json()["bot_id"]
    token = os.getenv("WEBHOOK_TOKEN", "")
    prev = 0
    for t, kind, who, text in SCRIPT:
        if speed:
            time.sleep((t - prev) / speed)
        prev = t
        client.post(f"/webhooks/recall?token={token}", json=payload(bot_id, t, kind, who, text)).raise_for_status()
        print(f"{t:>3}s {kind:<5} {who or '':<6} {text or ''}")
    return client.get("/api/meetings").json()[0]["id"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--bot")
    ap.add_argument("--speed", type=float, default=4.0, help="1 = real time, 0 = no delay")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    with httpx.Client(base_url=a.base, timeout=60) as c:
        print("meeting", run(c, a.bot, a.speed))
