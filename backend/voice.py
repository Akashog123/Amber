"""ElevenLabs text-to-speech -> mp3 bytes (what Recall's output_audio accepts)."""
import os

import httpx

DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", a stock ElevenLabs voice


async def tts(text: str) -> bytes:
    voice = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json={"text": text, "model_id": "eleven_flash_v2_5"},  # lowest-latency model
        )
        r.raise_for_status()
        return r.content
