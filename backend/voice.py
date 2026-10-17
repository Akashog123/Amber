"""ElevenLabs text-to-speech -> mp3 bytes (what Recall's output_audio accepts)."""
import hashlib
import os
import random
import re
from pathlib import Path

import httpx

DEFAULT_VOICE = "Cvv0EXhC1Zv7b4a2QfWl"  # "Monika Sogam - Energetic and Polished" (female, Indian English, multilingual)
# Live replies need speed: flash/turbo v2.5 ~0.5s, multilingual v2 / v3 conversational ~1.5s, v3 / v4 ~3s+.
MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
# Fillers are synthesized once and cached, so they can use a slower, more natural model.
FILLER_MODEL = os.getenv("ELEVENLABS_FILLER_MODEL") or MODEL
FILLER_DIR = Path(__file__).parent / "assets" / "fillers"
# Short acknowledgements, played only when an answer is slow (main.filler_kind / FILLER_AFTER decide). English only:
# a Hindi filler followed by a reply in the other language, or a stock Hindi phrase, sounded wrong live.
# Neutral on purpose: no "good question" (the line may be a statement, or garbled), nothing that promises a result.
FILLERS = {
    "lookup": ["Let me check.", "One moment, checking.", "Let me look that up.", "Checking the records."],
    "think": ["One moment.", "Let me think.", "Give me a second."],
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


PCM_RATE = 16000  # streaming voice (Output Media page): raw 16-bit mono PCM, 32 KB per second of speech


async def tts_stream(text: str, model: str = MODEL):
    """Yield raw PCM chunks as ElevenLabs produces them: the first audio arrives in ~0.4 s instead of ~1.1 s."""
    global _client
    _client = _client or httpx.AsyncClient(base_url="https://api.elevenlabs.io/v1", timeout=20)
    async with _client.stream("POST", f"/text-to-speech/{_voice()}/stream", params={"output_format": "pcm_16000"},
                              headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                              json={"text": text, "model_id": model}) as r:
        r.raise_for_status()
        async for chunk in r.aiter_bytes(4096):
            yield chunk


async def filler_pcm(text: str) -> bytes:
    """Fillers for the streaming page: cached like the mp3 ones, as PCM."""
    slug = re.sub(r"[^a-z]+", "-", text.lower()).strip("-") or "x"
    path = FILLER_DIR / f"{_voice()}-{FILLER_MODEL}-{slug}-{hashlib.md5(text.encode()).hexdigest()[:6]}.pcm"
    if not path.exists():
        FILLER_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join([c async for c in tts_stream(text, FILLER_MODEL)]))
    return path.read_bytes()


async def filler_mp3(text: str) -> bytes:
    """Fillers are synthesized once per voice and cached on disk, so playing one costs no TTS time."""
    slug = re.sub(r"[^a-z]+", "-", text.lower()).strip("-") or "x"  # md5: Hindi lines have no ascii to slug
    path = FILLER_DIR / f"{_voice()}-{FILLER_MODEL}-{slug}-{hashlib.md5(text.encode()).hexdigest()[:6]}.mp3"
    if not path.exists():
        FILLER_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(await tts(text, FILLER_MODEL))
    return path.read_bytes()


async def warm_fillers(pcm: bool = False):
    """pcm=True: the streaming page plays raw PCM, so warm those copies instead of the mp3 ones."""
    try:  # a voice's first request can take 10-20s (cold start); pay it at dispatch, not on the first answer
        await tts("Hi.")
    except Exception as e:
        print(f"[voice] reply voice warm-up failed: {e!r}")
    for text in (t for pool in FILLERS.values() for t in pool):
        try:
            await (filler_pcm(text) if pcm else filler_mp3(text))
        except Exception as e:
            print(f"[voice] filler warm-up failed for {text!r}: {e!r}")
            return


def pick_filler(kind: str) -> str:
    """Random phrase from the pool, never the same one twice in a row."""
    global _last
    _last = random.choice([t for t in FILLERS[kind] if t != _last])
    return _last
