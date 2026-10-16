# Amber live test script

Say each line **exactly** as written, in the Meet with Amber present. Wait for Amber to finish
(or ~6 s of silence) before the next one. Note the ID of anything that fails and tell Claude,
e.g. "B3 failed: she said X". Claude checks `backend/logs/` and the server log for that moment.

Tips: say "Amber" clearly with a tiny pause after it ("Amber… what's…"). One person speaking at a time
unless the test says otherwise.

Expected answers come from the mock records in `backend/seed.py`.

---

## A. Wake word and staying quiet

| ID | Say | Pass if |
|---|---|---|
| A1 | "Amber, are you there?" | She answers briefly (yes / ready to help). |
| A2 | "Okay team, let's look at the chiller first." | **Silence.** She was not addressed. |
| A3 | "I am very sure the vendor will be late." | **Silence.** (Sounds like "Amber" but isn't a request.) |
| A4 | "Hey Amber, can you hear me?" | She answers. |
| A5 | "The number of pumps on line three is two." | **Silence.** |
| A6 | "Amber what's the status of the VFD drives" (no pause, fast) | She answers: delivered 10 Oct, installation pending. |

## B. Grounded answers from records

| ID | Say | Pass if the answer contains |
|---|---|---|
| B1 | "Amber, what's the status of the pump order?" | PO-1041, awaiting vendor quote (may add: Rahul, 2 units, 4.2 lakh). |
| B2 | "Amber, when are the pump seals arriving?" | 24 October (PO-1042, ordered). |
| B3 | "Amber, who owns the chiller service contract?" | Ankit (PO-1043, under review, renewal 1 Nov). |
| B4 | "Amber, what's the status of chiller two?" | Running, high vibration flagged. |
| B5 | "Amber, have we ordered the PPE kits?" | Approved but not ordered yet (50 kits, Sneha). |
| B6 | "Amber, why is the air compressor down?" | Maintenance, waiting on a filter kit. |
| B7 | "Amber, when is the boiler inspection?" | 15 December. |
| B8 | "Amber, what's on the agenda today?" | Pump order, chiller vibration / service contract, PPE kits. |

## C. Honest "I don't know"

| ID | Say | Pass if |
|---|---|---|
| C1 | "Amber, what was last quarter's marketing spend?" | Exactly: "I don't have that information in my current records." |
| C2 | "Amber, what's the phone number of the seal vendor?" | Fallback line (vendor name is known, phone isn't). Must **not** invent a number. |
| C3 | "Amber, what's our revenue this year?" | Fallback line. |
| C4 | "Amber, when was the pump order placed?" | Fallback or "no date in records". Must **not** invent a date. |

## D. General knowledge (allowed)

| ID | Say | Pass if |
|---|---|---|
| D1 | "Amber, what is a VFD drive?" | A short, correct general explanation (not the fallback line). |
| D2 | "Amber, what causes vibration in a chiller?" | Short general answer. |

## E. Uses what was said in the meeting

| ID | Say | Pass if |
|---|---|---|
| E1 | First: "The pump vendor told me delivery will slip by two weeks." Then: "Amber, what did I just say about the pump?" | Mentions the two-week slip. |
| E2 | "Amber, what have we discussed so far?" | A brief, accurate summary of the call so far. |

## F. Follow-ups, rephrasing, cancelling

| ID | Say | Pass if |
|---|---|---|
| F1 | "Amber, who owns the boiler?" → after she answers, within 10 s: "And when is its next inspection?" | Answers the follow-up (15 Dec) **without** you saying "Amber" again. |
| F2 | "Amber, what's the status of the pump… actually no, the PPE kits?" (one breath) | Answers about **PPE kits**, not the pump. |
| F3 | "Amber, how many PPE kits… never mind." | **Silence.** |
| F4 | "Amber, who owns the boiler?" → wait 20 s → "And who owns the compressor?" | **Silence** for the second line (follow-up window has expired). |

## G. Interruptions and cross-talk

| ID | Do | Pass if |
|---|---|---|
| G1 | "Amber, give me the status of every procurement order." → start talking ("okay okay, thanks") **while she speaks**. | She stops within ~1–2 s. |
| G2 | Person 1: "Amber, who owns the PPE order?" Person 2 talks immediately after ("I think it's Sneha"). | She still answers Person 1 (Sneha). |
| G3 | Two people talk to each other for 30 s without saying "Amber". | **Silence** the whole time. |

## H. Chat

| ID | Type in Meet chat | Pass if |
|---|---|---|
| H1 | "Amber, who owns the boiler?" | Chat reply: Priya. |
| H2 | "Amber, what was last quarter's marketing spend?" | Chat reply with the fallback line. |
| H3 | "hello everyone" | **No** reply. |

## I. Latency (watch, don't say)

| ID | Check | Pass if |
|---|---|---|
| I1 | Time from the end of your question to Amber's first word, over B1–B8. | Usually under ~5 s. Claude reads the exact numbers from the server log. |

---

## Not built yet (don't test these today)
Task extraction ("I'll do X by Friday"), writing notes onto records and the confirmation question,
recap email, follow-up reminder emails, attendance in a recap, recordings dashboard.

## Known issues from the first live runs
- The transcriber sometimes mishears "Amber" ("i'm very", "hamburger"). Sound-alikes are matched only
  near the start of a line and only when the line is a request.
- When asked who made her, she said "Google". Fixed: her instructions now say she was built by this team. Re-check with "Amber, who made you?"
- Gemini free-tier latency spikes (seen 4.6–6.8 s for the model call alone on some replies).
