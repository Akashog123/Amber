"""Thin Recall.ai client. Docs: https://docs.recall.ai"""
import base64
import os
from pathlib import Path

import httpx

EVENTS = [
    "transcript.data",
    "transcript.partial_data",  # only used to notice someone talking over Amber
    "participant_events.join",
    "participant_events.leave",
    "participant_events.chat_message",
]
# Recall only accepts output_audio calls if the bot was created with automatic_audio_output.
_SILENCE = base64.b64encode((Path(__file__).parent / "assets" / "silence.mp3").read_bytes()).decode()


def enabled() -> bool:
    return bool(os.getenv("RECALL_API_KEY"))


def _client() -> httpx.AsyncClient:
    region = os.getenv("RECALL_REGION", "us-west-2")
    return httpx.AsyncClient(
        base_url=f"https://{region}.recall.ai/api/v1",
        headers={"Authorization": os.environ["RECALL_API_KEY"]},
        timeout=20,
    )


async def create_bot(meeting_url: str, webhook_url: str) -> str:
    body = {
        "meeting_url": meeting_url,
        "bot_name": "Amber",
        "recording_config": {
            "transcript": {"provider": {"recallai_streaming": {
                "mode": "prioritize_low_latency", "language_code": "en"}}},
            "participant_events": {},
            "realtime_endpoints": [{"type": "webhook", "url": webhook_url, "events": EVENTS}],
        },
        "automatic_audio_output": {"in_call_recording": {"data": {"kind": "mp3", "b64_data": _SILENCE}}},
    }
    async with _client() as c:
        r = await c.post("/bot/", json=body)
        r.raise_for_status()
        return r.json()["id"]


async def leave(bot_id: str):
    async with _client() as c:
        (await c.post(f"/bot/{bot_id}/leave_call/")).raise_for_status()


async def output_audio(bot_id: str, mp3: bytes):
    async with _client() as c:
        r = await c.post(f"/bot/{bot_id}/output_audio/",
                         json={"kind": "mp3", "b64_data": base64.b64encode(mp3).decode()})
        r.raise_for_status()


async def stop_audio(bot_id: str):
    async with _client() as c:
        (await c.delete(f"/bot/{bot_id}/output_audio/")).raise_for_status()


async def send_chat(bot_id: str, text: str):
    async with _client() as c:
        (await c.post(f"/bot/{bot_id}/send_chat_message/", json={"message": text})).raise_for_status()
