"""ElevenLabs text-to-speech -> mp3 bytes (what Recall's output_audio accepts)."""
import os
import random
import re
from pathlib import Path

import httpx

DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", a stock ElevenLabs voice
# Live replies need speed: flash/turbo v2.5 ~0.5s, multilingual v2 / v3 conversational ~1.5s, v3 / v4 ~3s+.
MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
# Fillers are synthesized once and cached, so they can use a slower, more natural model.
FILLER_MODEL = os.getenv("ELEVENLABS_FILLER_MODEL") or MODEL
FILLER_DIR = Path(__file__).parent / "assets" / "fillers"
# Short acknowledgements played the moment Amber is asked something, while the answer is generated.
FILLERS = {
    "lookup": ["Let me check.", "One sec, pulling that up.", "Let me look that up.", "Checking the records.",
               "Give me a second.", "Sure, let me see."],
    "think": ["Hmm, good question.", "Let me think.", "Sure, one moment.", "Right, let me see.", "Okay, let me think."],
}
# One kept-alive client: a fresh TLS connection per reply cost ~1.4s in testing.
_client: httpx.AsyncClient | None = None
_last: str | None = None


def _voice() -> str:
    return os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE


async def tts(text: str, model: str = MODEL) -> bytes:
    global _client
    _client = _client or httpx.AsyncClient(base_url="https://api.elevenlabs.io/v1", timeout=20)
    r = await _client.post(
        f"/text-to-speech/{_voice()}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": model},
    )
    r.raise_for_status()
    return r.content


async def filler_mp3(text: str) -> bytes:
    """Fillers are synthesized once per voice and cached on disk, so playing one costs no TTS time."""
    path = FILLER_DIR / f"{_voice()}-{FILLER_MODEL}-{re.sub(r'[^a-z]+', '-', text.lower()).strip('-')}.mp3"
    if not path.exists():
        FILLER_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(await tts(text, FILLER_MODEL))
    return path.read_bytes()


async def warm_fillers():
    for text in (t for pool in FILLERS.values() for t in pool):
        try:
            await filler_mp3(text)
        except Exception as e:
            print(f"[voice] filler warm-up failed for {text!r}: {e!r}")
            return


def pick_filler(kind: str) -> str:
    """Random phrase from the pool, never the same one twice in a row."""
    global _last
    _last = random.choice([t for t in FILLERS[kind] if t != _last])
    return _last
