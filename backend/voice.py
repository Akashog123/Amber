"""ElevenLabs text-to-speech -> mp3 bytes (what Recall's output_audio accepts)."""
import os

import httpx

DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", a stock ElevenLabs voice
# One kept-alive client: a fresh TLS connection per reply cost ~1.4s in testing.
_client: httpx.AsyncClient | None = None


async def tts(text: str) -> bytes:
    global _client
    _client = _client or httpx.AsyncClient(base_url="https://api.elevenlabs.io/v1", timeout=20)
    voice = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    r = await _client.post(
        f"/text-to-speech/{voice}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": "eleven_flash_v2_5"},  # lowest-latency model
    )
    r.raise_for_status()
    return r.content
