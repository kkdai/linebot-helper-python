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

LIVE_MODEL = "gemini-3.1-flash-live-preview"
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY")

# Zephyr: bright, upbeat female voice — suitable for lively read-aloud
TTS_VOICE = "Zephyr"
# gemini-3.1-flash-live-preview outputs 24kHz PCM (24000 * 2 bytes = 48000 bytes/sec)
PCM_SAMPLE_RATE = 24000


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
        api_key=GOOGLE_AI_API_KEY,
        vertexai=False,
        http_options={"api_version": "v1beta"},
    )

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
            )
        ),
    )

    async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
        # Use session.send() per cookbook pattern (send_client_content causes 1007)
        await session.send(input=text, end_of_turn=True)

        pcm_chunks = []
        # Turn-based receive: for-loop ending = turn complete
        async for response in session.receive():
            if response.data:
                pcm_chunks.append(response.data)

    pcm_bytes = b"".join(pcm_chunks)

    if not pcm_bytes:
        raise RuntimeError("No audio received from Gemini Live")

    # PCM: 24kHz x 16-bit mono = 48000 bytes/sec
    duration_ms = int(len(pcm_bytes) / (PCM_SAMPLE_RATE * 2) * 1000)

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
                    "-f", "s16le", "-ar", str(PCM_SAMPLE_RATE), "-ac", "1",
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
