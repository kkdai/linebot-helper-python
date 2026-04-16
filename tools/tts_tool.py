"""
Tool: Text-to-Speech

Converts text to m4a audio using Gemini 3.1 Flash TTS API.
"""

import logging
import os
import subprocess
import tempfile
import struct

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# New model for native TTS
TTS_MODEL = "gemini-3.1-flash-tts-preview"
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")

# Zephyr: bright, upbeat female voice — suitable for lively read-aloud
TTS_VOICE = "Zephyr"
# Default sample rate if not specified in mime type
DEFAULT_SAMPLE_RATE = 24000


def parse_audio_mime_type(mime_type: str) -> dict:
    """Parses bits per sample and rate from an audio MIME type string."""
    bits_per_sample = 16
    rate = DEFAULT_SAMPLE_RATE

    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass

    return {"bits_per_sample": bits_per_sample, "rate": rate}


async def text_to_speech(text: str) -> tuple[bytes, int]:
    """
    Convert text to speech using Gemini 3.1 Flash TTS API.

    Args:
        text: Text to synthesize.

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

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=f"## Transcript:\n{text}"),
            ],
        ),
    ]

    config = types.GenerateContentConfig(
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
            )
        ),
    )

    pcm_chunks = []
    sample_rate = DEFAULT_SAMPLE_RATE

    try:
        response_stream = await client.aio.models.generate_content_stream(
            model=TTS_MODEL,
            contents=contents,
            config=config,
        )
        async for chunk in response_stream:
            if not chunk.parts:
                continue

            for part in chunk.parts:
                if part.inline_data and part.inline_data.data:
                    inline_data = part.inline_data
                    pcm_chunks.append(inline_data.data)

                    # Extract sample rate from first chunk with mime_type
                    if inline_data.mime_type:
                        params = parse_audio_mime_type(inline_data.mime_type)
                        sample_rate = params["rate"]
                elif part.text:
                    logger.debug(f"Gemini TTS text part: {part.text}")

    except Exception as e:
        logger.error(f"Error calling Gemini TTS: {e}")
        raise

    pcm_bytes = b"".join(pcm_chunks)

    if not pcm_bytes:
        raise RuntimeError("No audio received from Gemini TTS")

    # s16le = 2 bytes per sample
    duration_ms = int(len(pcm_bytes) / (sample_rate * 2) * 1000)

    # Convert PCM -> m4a via ffmpeg
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
                    "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
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

    logger.info(f"TTS complete: {len(m4a_bytes)} bytes, {duration_ms}ms, SR={sample_rate}")
    return m4a_bytes, duration_ms

