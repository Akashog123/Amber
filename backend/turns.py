"""Turn-taking: who Amber is talking with and what she is waiting for, one Conversation per meeting.

Every final transcript line goes through route(), which only reads the state and the words and says what to do
and why. No I/O here, so the whole policy is readable (and testable) in one place:

  - nothing open, no "Amber"            -> ignore
  - "Amber, ..."                        -> start a question
  - the asker keeps talking             -> append (wait restarts)
  - while her answer is being prepared  -> merge (correction / rest of the same question / the question after a
                                           bare "Amber,"), queue (a new question of its own), or classify
  - shortly after she answered someone  -> their follow-up needs no name; a line naming someone else is for them;
                                           anything unclear -> classify
  - classify = ask the model "is this said to Amber?" (only ever inside an open state, so it stays rare)
"""
import re
from dataclasses import dataclass, field

WAKE = re.compile(r"\b(amber|ember|amba|ambar|umber)\b|अंबर|अम्बर|एम्बर|ऐम्बर", re.I)
QUESTION = re.compile(r"\b(can you|could you|would you|tell me|what|what's|who|whose|when|where|how|which|"
                      r"why|is there|are there|do we|did we|have we|has it|status|update|please|give me|check)\b", re.I)
HINDI = re.compile(r"[ऀ-ॿ]|\b(kya|kaun|kab|kahan|kitna|kitne|batao|bataiye|hai|hain|karo|kijiye)\b", re.I)
CORRECTION = re.compile(r"\b(actually|i mean|sorry|instead|rather|wait)\b", re.I)
CANCEL = re.compile(r"\b(never ?mind|forget (it|about (it|that)|that)|cancel that|scratch that|no worries)\b", re.I)
_NOISE = {"hey", "hi", "hello", "ok", "okay", "so", "um", "uh", "yo", "and", "amber"}


_OPENERS = {"and", "so", "okay", "ok", "also", "then", "but", "hey", "amber", "um", "uh", "acha", "accha"}
_ASKS = {"what", "what's", "whats", "when", "where", "who", "whose", "which", "how", "why", "is", "are", "was",
         "were", "can", "could", "would", "will", "do", "does", "did", "have", "has", "should", "any", "kya", "kab",
         "kaun", "kitna", "kahan"}


def clear_question(text: str) -> bool:
    """Unmistakably a question: ends with "?" or starts with a question word ("and when does it arrive").
    Words like "check" or "status" alone don't count: "wait, let me check the PO" is not a question."""
    if text.rstrip().endswith("?"):
        return True
    words = [w.strip(",.!") for w in text.lower().split()]
    while words and words[0] in _OPENERS:
        words = words[1:]
    return bool(words) and words[0] in _ASKS


def has_content(text: str) -> bool:
    """False for a bare "Amber" / "hey Amber": the actual question is probably still coming."""
    words = re.sub(r"[^a-z' ]", " ", WAKE.sub(" ", text.lower())).split()
    return any(w not in _NOISE for w in words)


_ENDS_WITH_NAME = re.compile(rf"(?:{WAKE.pattern})\W*$", re.I)


def question_pending(text: str) -> bool:
    """Her name with nothing after it: "Amber," or "Listen, we can't wait. Amber," -> the question is coming next."""
    return not has_content(text) or bool(_ENDS_WITH_NAME.search(text.strip()))


@dataclass
class Conversation:
    # speaker -> the question they're asking: {"parts": [...], "task", "generating", "committed", "filler"}
    pending: dict[str, dict] = field(default_factory=dict)
    # speaker -> (until, prompted): they can follow up without her name until then; prompted = she just said
    # "yes?" to a bare "Amber", so their next line is the question even without a question word
    followups: dict[str, tuple[float, bool]] = field(default_factory=dict)
    record_answer_until: float = 0.0  # her record question was asked aloud: a bare "it's 2" counts as the answer
    spoke_until: float = 0.0  # shortly after she speaks, anyone's clear question may be for her (the model decides)


@dataclass
class Route:
    action: str  # ignore | start | append | merge | queue | classify
    why: str
    text: str
    cancel: bool = False  # withdraw the speaker's pending question first


def route(conv: Conversation, speaker: str, text: str, addressed: bool, names_other: bool, now: float) -> Route:
    q = conv.pending.get(speaker)
    cancel = False
    if m := CANCEL.search(text):
        rest = text[m.end():].strip(" ,.!?")
        if not (has_content(rest) and (WAKE.search(rest) or QUESTION.search(rest))):
            return Route("ignore", "withdrew the question" if q else "cancel phrase, nothing pending", text, bool(q))
        # "Forget that. Amber, have we ordered the PPE kits?": drop the old question, keep the new one
        text, addressed, cancel, q = rest, addressed or bool(WAKE.search(rest)), bool(q), None
    answering = bool(q and q.get("committed"))  # her answer to them is being spoken
    if answering:
        q = None
    asks = text.rstrip().endswith("?")
    opens = clear_question(text.rstrip(" ?.!")) and not names_other  # starts like a question of its own
    standalone = (asks or opens) and not names_other

    if q and not q.get("generating"):
        return Route("append", "still asking", text, cancel)
    if q:  # her answer is being prepared
        if CORRECTION.search(text):
            return Route("merge", "correction while the answer was being prepared", text, cancel)
        if question_pending(" ".join(q["parts"])):
            return Route("merge", 'the question after just "Amber,"', text, cancel)
        if asks and not addressed and not opens:
            return Route("merge", "rest of the same question", text, cancel)
        if addressed or opens:
            return Route("queue", "a second question while the first is answered", text, cancel)
        return Route("classify", "unclear line while her answer was being prepared", text, cancel)
    if addressed:
        return Route("start", "said her name", text, cancel)
    until, prompted = conv.followups.get(speaker, (0.0, False))
    if answering or now < until:
        if names_other:
            return Route("ignore", "addressed to someone else", text, cancel)
        if prompted:
            return Route("start", 'the question after she said "yes?"', text, cancel)
        if standalone:
            return Route("start", "follow-up, no name needed", text, cancel)
        return Route("classify", "unclear line right after she answered them", text, cancel)
    if now < conv.spoke_until and standalone:
        return Route("classify", "someone else's question right after Amber spoke", text, cancel)
    return Route("ignore", "no name, nothing open", text, cancel)


if __name__ == "__main__":
    c = Conversation()
    assert route(c, "A", "nice weather", False, False, 0).action == "ignore"
    assert route(c, "A", "Amber, what's up", True, False, 0).action == "start"
    c.pending["A"] = {"parts": ["Amber,"], "generating": True}
    assert route(c, "A", "have we ordered the PPE kits", False, False, 0).why == 'the question after just "Amber,"'
    c.pending["A"] = {"parts": ["Amber, who owns the chiller service"], "generating": True}
    assert route(c, "A", "contract?", False, False, 0).action == "merge"
    assert route(c, "A", "and when does it arrive?", False, False, 0).action == "queue"
    assert route(c, "A", "yeah do that one", False, False, 0).action == "classify"
    c.pending.clear()
    c.followups["A"] = (10.0, False)
    assert route(c, "A", "Rahul, please send it", False, True, 5).action == "ignore"
    assert route(c, "A", "and the boiler?", False, False, 5).action == "start"
    assert route(c, "A", "hmm okay that one", False, False, 5).action == "classify"
    assert route(c, "A", "hmm okay that one", False, False, 11).action == "ignore"
    assert route(c, "A", "oh forget it", False, False, 5).action == "ignore"
    assert route(c, "A", "Wait, let me check the PO first", False, False, 5).action == "classify"  # not a fast "yes"
    assert route(c, "B", "and the booster pump?", False, False, 5).action == "ignore"  # B never asked Amber
    c.spoke_until = 8.0
    assert route(c, "B", "and the booster pump?", False, False, 5).action == "classify"  # just after she spoke
    assert route(c, "B", "let's move on", False, False, 5).action == "ignore"
    assert question_pending("Amber,") and question_pending("Listen, we can't wait. Amber,")
    assert not question_pending("Amber, what's the ETA") and not question_pending("thanks Amber, that helps.")
    assert clear_question("and when does it arrive") and clear_question("okay, is it delivered")
    assert not clear_question("wait, let me check the PO") and not clear_question("status looks fine")
    print("ok")
