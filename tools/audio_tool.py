"""
Tool: Audio Transcription

Transcribes audio bytes using Gemini multimodal API.
"""

import logging
import os
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

TRANSCRIPTION_MODEL = "gemini-3.1-flash-lite-preview"
VERTEX_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/mp4") -> str:
    """
    Transcribe audio bytes to text using Gemini.

    Args:
        audio_bytes: Raw audio file content (m4a from LINE)
        mime_type: MIME type of the audio (LINE audio is always audio/mp4)

    Returns:
        Transcribed text string

    Raises:
        Exception: If transcription fails
    """
    client = genai.Client(
        vertexai=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,
    )

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    response = await client.aio.models.generate_content(
        model=TRANSCRIPTION_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    audio_part,
                    types.Part(text="請將以上語音內容完整轉錄成文字，保留原語言，不要加任何說明或前綴。"),
                ],
            )
        ],
    )

    transcription = response.text or ""
    logger.info(f"Transcription result ({len(transcription)} chars): {transcription[:80]}...")
    return transcription
