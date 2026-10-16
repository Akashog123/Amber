"""Recap and reminder emails over SMTP (Gmail App Password). Every email is also kept in the outbox table."""
import asyncio
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

import db

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))


def _send_sync(to: list[str], subject: str, html: str, text: str):
    msg = EmailMessage()
    msg["From"] = f"Amber <{os.environ['SMTP_USER']}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = " ".join(subject.split())  # no newlines: a meeting title must not inject headers
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=20) as s:
        # AUTH LOGIN explicitly: on some networks Gmail drops the connection on smtplib's default AUTH PLAIN,
        # and login() never falls back. Spaces are stripped because Google displays app passwords in groups.
        s.ehlo()
        s.user, s.password = os.environ["SMTP_USER"], os.environ["SMTP_PASS"].replace(" ", "")
        s.auth("LOGIN", s.auth_login, initial_response_ok=False)
        s.send_message(msg)


async def send(mid: int | None, kind: str, to: list[str], subject: str, html: str, text: str) -> bool:
    """Send and log to the outbox. Never raises: a mail failure must not break the meeting pipeline."""
    to = [t for t in dict.fromkeys(to) if t and "@" in t]
    status, error = "skipped", "no recipients with an email address"
    if to and not os.getenv("SMTP_USER"):
        error = "SMTP_USER not configured"
    elif to:
        try:
            await asyncio.to_thread(_send_sync, to, subject, html, text)
            status, error = "sent", None
        except Exception as e:
            status, error = "failed", f"{type(e).__name__}: {e}"
    db.execute("INSERT INTO outbox (meeting_id,kind,to_addr,subject,html,text,status,error,ts) VALUES (?,?,?,?,?,?,?,?,?)",
               mid, kind, ", ".join(to), subject, html, text, status, error, db.now())
    print(f"[mail] {kind} -> {', '.join(to) or '-'}: {status}{f' ({error})' if error else ''}")
    return status == "sent"


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(i))}</li>" for i in items) + "</ul>" if items else "<p><i>None</i></p>"


def _when(ts: str | None) -> str:
    return (ts or "")[11:16] or "-"


def _table(head: list[str], rows: list[list]) -> str:
    if not rows:
        return "<p><i>None</i></p>"
    cell = 'style="text-align:left;border-bottom:1px solid #ddd;padding:4px 8px"'
    return ('<table style="border-collapse:collapse;font-size:14px"><tr>'
            + "".join(f"<th {cell}>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td {cell}>{escape(str(c or '-'))}</td>" for c in r) + "</tr>" for r in rows)
            + "</table>")


def recap(m: dict, mom: dict, tasks: list[dict], notes: list[dict], people: list[dict]) -> tuple[str, str, str]:
    """(subject, html, text) for the post-meeting recap."""
    subject = f"Recap: {m['title']}"
    agenda = _table(["Agenda item", "Status", "Notes"],
                    [[a.get("item"), a.get("status"), a.get("notes")] for a in mom.get("agenda_alignment") or []])
    actions = _table(["Task", "Owner", "Due", "Status"], [[t["title"], t["owner"], t["due_at"], t["status"]] for t in tasks])
    updates = [f"{n['record_id']}: {n['note']}" for n in notes]
    attendance = _table(["Name", "Joined (UTC)", "Left (UTC)"],
                        [[p["name"], _when(p["joined_at"]), _when(p["left_at"])] for p in people])
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:680px;color:#222">
<h2 style="color:#b45309">{escape(m['title'])}</h2>
<p style="color:#666">Minutes of meeting by Amber</p>
<h3>Executive summary</h3><p>{escape(mom.get('executive_summary') or '-')}</p>
<h3>Agenda alignment</h3>{agenda}
<h3>Decisions</h3>{_list(mom.get('decisions') or [])}
<h3>Action items</h3>{actions}
<h3>Record updates</h3>{_list(updates)}
<h3>Open questions</h3>{_list(mom.get('open_questions') or [])}
<h3>Attendance</h3>{attendance}
</div>"""
    text = "\n".join([
        m["title"], "", "SUMMARY", mom.get("executive_summary") or "-", "",
        "AGENDA", *[f"- {a.get('item')}: {a.get('status')} - {a.get('notes')}" for a in mom.get("agenda_alignment") or []], "",
        "DECISIONS", *[f"- {d}" for d in mom.get("decisions") or []], "",
        "ACTION ITEMS", *[f"- {t['title']} | {t['owner']} | due {t['due_at'] or '-'} | {t['status']}" for t in tasks], "",
        "RECORD UPDATES", *[f"- {u}" for u in updates], "",
        "OPEN QUESTIONS", *[f"- {q}" for q in mom.get("open_questions") or []], "",
        "ATTENDANCE", *[f"- {p['name']}: {_when(p['joined_at'])} - {_when(p['left_at'])} UTC" for p in people]])
    return subject, html, text


def reminder(t: dict, meeting_title: str) -> tuple[str, str, str]:
    """(subject, html, text) for a follow-up on something the owner committed to."""
    first = (t["owner"] or "there").split(" ")[0]
    due = t["due_at"] or "soon"
    subject = f"Reminder: {t['title']} (due {due})"
    # "You said" is the owner's own words from the meeting; later progress notes are shown separately.
    quote = (f"<p style='color:#555;margin:4px 0'>You said: <i>“{escape(t['quote'])}”</i></p>" if t.get("quote") else "")
    if t.get("last_update"):
        quote += f"<p style='color:#555;margin:4px 0'>Latest update: {escape(t['last_update'])}</p>"
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:600px;color:#222">
<p>Hi {escape(first)},</p>
<p>A quick check-in from Amber on what you picked up in <b>{escape(meeting_title)}</b>:</p>
<p style="font-size:16px"><b>{escape(t['title'])}</b><br>Due: {escape(due)}</p>{quote}
<p>How is it going? If it's done or blocked, just reply to this email or mention it in the next meeting.</p>
<p>Amber</p></div>"""
    text = (f"Hi {first},\n\nA quick check-in from Amber on what you picked up in {meeting_title}:\n\n"
            f"{t['title']}\nDue: {due}\n" + (f'You said: "{t["quote"]}"\n' if t.get("quote") else "")
            + (f"Latest update: {t['last_update']}\n" if t.get("last_update") else "")
            + "\nHow is it going? If it's done or blocked, reply to this email or mention it in the next meeting.\n\nAmber")
    return subject, html, text
