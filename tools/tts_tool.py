"""
Tool: Text-to-Speech

Converts text to m4a audio using Gemini 3.1 Flash Live API.
"""

import logging
import os
import subprocess
import tempfile

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
VERTEX_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"


async def text_to_speech(text: str) -> tuple[bytes, int]:
    """
    Convert text to speech using Gemini Live API.

    Args:
        text: Text to synthesize. Keep under ~250 Chinese chars (~1 minute of speech).

    Returns:
        (m4a_bytes, duration_ms) — duration_ms is an int

    Raises:
        RuntimeError: If Gemini returns no audio
        subprocess.CalledProcessError: If ffmpeg conversion fails
        Exception: On any other failure
    """
    client = genai.Client(
        vertexai=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,
    )

    config = {"response_modalities": ["AUDIO"]}

    async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )

        pcm_chunks = []
        async for message in session.receive():
            if message.server_content and message.server_content.model_turn:
                for part in message.server_content.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        pcm_chunks.append(part.inline_data.data)
            if message.server_content and message.server_content.turn_complete:
                break

    pcm_bytes = b"".join(pcm_chunks)

    if not pcm_bytes:
        raise RuntimeError("No audio received from Gemini Live")

    # PCM: 16kHz x 16-bit mono = 32000 bytes/sec
    duration_ms = int(len(pcm_bytes) / 32000 * 1000)

    # Convert PCM -> m4a via ffmpeg (temp file mode avoids moov atom issues)
    pcm_path = None
    m4a_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as pcm_file:
            pcm_file.write(pcm_bytes)
            pcm_path = pcm_file.name

        m4a_path = pcm_path.replace(".pcm", ".m4a")

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "s16le", "-ar", "16000", "-ac", "1",
                    "-i", pcm_path,
                    "-c:a", "aac",
                    m4a_path,
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg conversion failed: {e.stderr.decode(errors='replace')}")
            raise

        with open(m4a_path, "rb") as f:
            m4a_bytes = f.read()

    finally:
        if pcm_path and os.path.exists(pcm_path):
            os.unlink(pcm_path)
        if m4a_path and os.path.exists(m4a_path):
            os.unlink(m4a_path)

    logger.info(f"TTS complete: {len(m4a_bytes)} bytes, {duration_ms}ms")
    return m4a_bytes, duration_ms
