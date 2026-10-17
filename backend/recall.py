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


def transcript_provider(keyterms: list[str]) -> dict:
    """Deepgram nova-3 (Indian English + boosted names) when enabled, else Recall's own English-only ASR.
    Deepgram's key lives in the Recall dashboard (Transcription settings), not here."""
    if os.getenv("RECALL_TRANSCRIBER", "recall") != "deepgram":
        return {"recallai_streaming": {"mode": "prioritize_low_latency", "language_code": "en"}}
    return {"deepgram_streaming": {
        "model": "nova-3",
        "language": os.getenv("DEEPGRAM_LANGUAGE", "en-IN"),
        "keyterm": keyterms[:50],  # boosts "Amber" and record names; Deepgram caps the keyterm prompt size
        "smart_format": True,
        "endpointing": int(os.getenv("DEEPGRAM_ENDPOINTING_MS", "300")),  # silence before a segment is final
        "mip_opt_out": True,  # don't let Deepgram train on meeting audio
    }}


def recording_config(webhook_url: str, keyterms: list[str], ws_url: str | None = None) -> dict:
    cfg = {
        "transcript": {"provider": transcript_provider(list(keyterms))},
        "participant_events": {},
        "realtime_endpoints": [{"type": "webhook", "url": webhook_url, "events": EVENTS}],
    }
    if ws_url:  # screen-share frames (2 fps PNG, every video stream) only go to websockets
        cfg["video_mixed_layout"] = "gallery_view_v2"
        cfg["video_separate_png"] = {}
        cfg["realtime_endpoints"].append({"type": "websocket", "url": ws_url, "events": ["video_separate_png.data"]})
    return cfg


async def create_bot(meeting_url: str, webhook_url: str, keyterms: list[str] = (), ws_url: str | None = None,
                     join_at: str | None = None) -> str:
    body = {
        "meeting_url": meeting_url,
        "bot_name": "Amber",
        "recording_config": recording_config(webhook_url, list(keyterms), ws_url),
        "automatic_audio_output": {"in_call_recording": {"data": {"kind": "mp3", "b64_data": _SILENCE}}},
        **({"join_at": join_at} if join_at else {}),  # scheduled meeting: Recall sends the bot at that time
    }
    async with _client() as c:
        r = await c.post("/bot/", json=body)
        r.raise_for_status()
        return r.json()["id"]


async def delete_bot(bot_id: str):
    """Cancel a scheduled bot that hasn't joined yet."""
    async with _client() as c:
        (await c.delete(f"/bot/{bot_id}/")).raise_for_status()


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


async def pause_recording(bot_id: str):
    """Pauses audio/video capture (and with it the live transcript); participant and chat events keep coming."""
    async with _client() as c:
        (await c.post(f"/bot/{bot_id}/pause_recording/")).raise_for_status()


async def resume_recording(bot_id: str):
    async with _client() as c:
        (await c.post(f"/bot/{bot_id}/resume_recording/")).raise_for_status()


async def recording_url(bot_id: str) -> str | None:
    """Fresh (pre-signed, short-lived) download link for the mixed video, once Recall has finished it."""
    async with _client() as c:
        r = await c.get(f"/bot/{bot_id}/")
        r.raise_for_status()
    for rec in reversed(r.json().get("recordings") or []):
        url = (((rec.get("media_shortcuts") or {}).get("video_mixed") or {}).get("data") or {}).get("download_url")
        if url:
            return url
    return None


async def send_chat(bot_id: str, text: str):
    async with _client() as c:
        (await c.post(f"/bot/{bot_id}/send_chat_message/", json={"message": text})).raise_for_status()


async def bot_status(bot_id: str) -> str:
    """Latest status code (joining_call, in_call_recording, call_ended, done, fatal...)."""
    async with _client() as c:
        r = await c.get(f"/bot/{bot_id}/")
        r.raise_for_status()
        changes = r.json().get("status_changes") or [{}]
        return changes[-1].get("code") or ""
