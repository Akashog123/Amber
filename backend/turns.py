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

WAKE = re.compile(r"\b(amber|ember|amba|ambar|umber)\b|अंबर|अम्बर|एम्बर|ऐम्बर|एंबर|ऐंबर", re.I)
QUESTION = re.compile(r"\b(can you|could you|would you|tell me|what|what's|who|whose|when|where|how|which|"
                      r"why|is there|are there|do we|did we|have we|has it|status|update|please|give me|check)\b", re.I)
# Hindi as Deepgram's multilingual model writes it: Devanagari, or romanised Hinglish.
HINDI = re.compile(r"[ऀ-ॿ]|\b(kya|kaun|kab|kahan|kitna|kitne|kaise|kyun|kyon|batao|bataiye|bataye|hai|hain|karo|"
                   r"kijiye|chahiye|mein|nahi|haan)\b", re.I)
# Hindi puts the question word anywhere ("PO-1041 ka status kya hai"), so any of these marks a question.
HINDI_ASKS = re.compile(r"\b(kya|kab|kaun|kitna|kitne|kahan|kaise|kyun|kyon|batao|bataiye|bataye)\b|"
                        r"क्या|कब|कौन|कितन|कहाँ|कहां|कैसे|क्यों|बताओ|बताइए|बताइये|बताएं", re.I)
# Talking ABOUT her, not to her (live: "Now Amber has a question about the recording." got "I'm ready...").
ABOUT_HER = re.compile(r"\bamber\s+(has|had|was|will|would|should|does|did|said|says|raised|asked|wants|thought|"
                       r"thinks|knows|needs|can't|cannot|won't)\b|\b(tell|ask)\s+amber\b", re.I)
CORRECTION = re.compile(r"\b(actually|i mean|sorry|instead|rather|wait|matlab|nahi nahi)\b|मतलब|नहीं नहीं", re.I)
CANCEL = re.compile(r"\b(never ?mind|forget (it|about (it|that)|that)|cancel that|scratch that|no worries|chhodo|chodo|"
                    r"rehne do|jaane do)\b|छोड़ो|छोड़िए|रहने दो|जाने दो", re.I)
_NOISE = {"hey", "hi", "hello", "ok", "okay", "so", "um", "uh", "yo", "and", "amber"}


_OPENERS = {"and", "so", "okay", "ok", "also", "then", "but", "hey", "amber", "um", "uh", "acha", "accha", "toh",
            "haan", "अच्छा", "तो", "हाँ"}
_ASKS = {"what", "what's", "whats", "when", "where", "who", "whose", "which", "how", "why", "is", "are", "was",
         "were", "can", "could", "would", "will", "do", "does", "did", "have", "has", "should", "any", "kya", "kab",
         "kaun", "kitna", "kahan"}


def ends_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!", "।"))


def clear_question(text: str) -> bool:
    """Unmistakably a question: ends with "?" or starts with a question word ("and when does it arrive").
    Words like "check" or "status" alone don't count: "wait, let me check the PO" is not a question."""
    if text.rstrip().endswith("?") or HINDI_ASKS.search(text):
        return True
    words = [w.strip(",.!") for w in text.lower().split()]
    while words and words[0] in _OPENERS:
        words = words[1:]
    return bool(words) and words[0] in _ASKS


def has_content(text: str) -> bool:
    """False for a bare "Amber" / "hey Amber": the actual question is probably still coming."""
    words = re.sub(r"[^a-z'ऀ-ॿ ]", " ", WAKE.sub(" ", text.lower())).split()  # keep Devanagari words
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
    # speaker -> when their current line began (first partial transcript). Finals land seconds late, and a window
    # counts from when they started speaking, not from when the ASR delivered it.
    talking_since: dict[str, float] = field(default_factory=dict)
    # The ASR here punctuates finished sentences (seen on a real line), so an unpunctuated one was cut mid-way.
    # Typed / replayed lines often carry no punctuation at all: then "no full stop" means nothing.
    punctuated: bool = False


@dataclass
class Route:
    action: str  # ignore | start | append | merge | queue | classify
    why: str
    text: str
    cancel: bool = False  # withdraw the speaker's pending question first


def route(conv: Conversation, speaker: str, text: str, addressed: bool, names_other: bool, now: float,
          judged: bool = False) -> Route:
    """`judged`: the model already said this unclear line is for Amber."""
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

    if q and names_other and not addressed:  # "Amit, you follow up with the vendor" is for Amit, not more question
        return Route("ignore", "addressed to someone else", text, cancel)
    if q and not q.get("generating"):
        if addressed and opens and has_content(" ".join(q["parts"])):
            # "Amber, who owns the boiler?" ... "Amber, what's the VFD status?": a second question, not more words
            return Route("queue", "a second question while the first was still being asked", text, cancel)
        return Route("append", "still asking", text, cancel)
    if q:  # her answer is being prepared
        if judged:  # live: "Like, let me see the..." + "Chat or your data." got two answers
            return Route("merge", "the model joined it to the question being answered", text, cancel)
        if CORRECTION.search(text):
            return Route("merge", "correction while the answer was being prepared", text, cancel)
        if question_pending(" ".join(q["parts"])):
            return Route("merge", 'the question after just "Amber,"', text, cancel)
        if (conv.punctuated and not opens and not names_other and has_content(text) and not question_pending(text)
                and not ends_sentence(q["parts"][-1])):  # (a bare "Amber" starts a new question, never ends one)
            # The ASR punctuates finished sentences, so this one was cut mid-way (live: "Amber, the Grundfos pump
            # shipment got" + "out by three weeks." was judged as two lines). The next line finishes it.
            return Route("merge", "finishing the sentence she was waiting on", text, cancel)
        if asks and not addressed and not opens:
            return Route("merge", "rest of the same question", text, cancel)
        if addressed or opens:
            return Route("queue", "a second question while the first is answered", text, cancel)
        return Route("classify", "unclear line while her answer was being prepared", text, cancel)
    if addressed and not judged and ABOUT_HER.search(text):
        return Route("classify", "talked about Amber, maybe not to her", text, cancel)
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
    if now < conv.spoke_until and (standalone or CORRECTION.search(text)) and not names_other:
        # "and the booster pump?" / "actually, I mean the centrifugal pump" from another person, just after she spoke
        return Route("classify", "someone else's question or correction right after Amber spoke", text, cancel)
    return Route("ignore", "no name, nothing open", text, cancel)


if __name__ == "__main__":
    c = Conversation()
    assert route(c, "A", "nice weather", False, False, 0).action == "ignore"
    assert route(c, "A", "Amber, what's up", True, False, 0).action == "start"
    assert route(c, "A", "Now Amber has a question about the recording.", True, False, 0).action == "classify"
    assert route(c, "A", "Amber has a question?", True, False, 0, judged=True).action == "start"  # model said yes
    assert route(c, "A", "Amber can you check PO-1041", True, False, 0).action == "start"
    assert route(c, "A", "What about Amber? Who owns it?", True, False, 0).action == "start"
    assert route(c, "A", "we both are talking and Amber thought, hey", True, False, 0).action == "classify"
    c.pending["A"] = {"parts": ["Amber,"], "generating": True}
    assert route(c, "A", "have we ordered the PPE kits", False, False, 0).why == 'the question after just "Amber,"'
    c.pending["A"] = {"parts": ["Amber, check if the vendor sent the tracking ID"]}
    assert route(c, "A", "Amit, you follow up with the vendor", False, True, 0).action == "ignore"  # not "still asking"
    c.pending["A"] = {"parts": ["Amber, who owns the chiller service"], "generating": True}
    assert route(c, "A", "contract?", False, False, 0).action == "merge"
    assert route(c, "A", "and when does it arrive?", False, False, 0).action == "queue"
    assert route(c, "A", "yeah do that one", False, False, 0).action == "classify"
    assert route(c, "A", "yeah do that one", True, False, 0, judged=True).action == "merge"  # one question, one answer
    c.pending["A"] = {"parts": ["Amber, the Grundfos pump shipment got"], "generating": True}
    assert route(c, "A", "out by three weeks.", False, False, 0).action != "merge"  # no punctuation seen yet
    c.punctuated = True
    assert route(c, "A", "out by three weeks.", False, False, 0).action == "merge"  # sentence cut mid-way
    assert route(c, "A", "Amit, you follow up with the vendor", False, True, 0).action != "merge"  # for Amit
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
    # Hindi / Hinglish as Deepgram multi writes it
    assert has_content("अंबर, पंप कब आएगा") and not has_content("अंबर,")
    assert clear_question("PO-1041 ka status kya hai") and clear_question("तो पंप कब आएगा")
    assert CANCEL.search("अच्छा छोड़ो") and CANCEL.search("chhodo yaar") and CORRECTION.search("matlab booster pump")
    assert WAKE.search("एंबर, बताओ") and HINDI.search("budget kitna hai")
    print("ok")
