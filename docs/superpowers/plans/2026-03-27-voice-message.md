# Voice Message Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to send LINE voice messages (m4a) in 1:1 chat; bot transcribes via Gemini, shows transcription, then runs it through the existing Orchestrator.

**Architecture:** New `tools/audio_tool.py` handles Gemini transcription. `main.py` adds `handle_audio_message()` handler and a one-line patch to `handle_text_message_via_orchestrator()` to accept an optional `text` parameter so audio-sourced text flows through the same orchestrator path as typed text.

**Tech Stack:** `google-genai` (already in project), `linebot` SDK `AudioMessage`, Gemini `gemini-3.1-flash-lite-preview` with inline audio bytes.

**Spec:** `docs/superpowers/specs/2026-03-27-voice-message-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `tools/audio_tool.py` | `transcribe_audio()` — download audio bytes → Gemini → text |
| Modify | `main.py` line 19 | Add `AudioMessage` to LINE SDK imports |
| Modify | `main.py` line 378 | Patch `handle_text_message_via_orchestrator()` to accept optional `text` |
| Modify | `main.py` line ~296 | Add `AudioMessage` branch in `handle_message_event()` |
| Modify | `main.py` after line 413 | Add `handle_audio_message()` function |

---

## Task 1: Create `tools/audio_tool.py`

**Files:**
- Create: `tools/audio_tool.py`

- [ ] **Step 1: Create the file**

```python
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
                    types.Part.from_text(
                        "請將以上語音內容完整轉錄成文字，保留原語言，不要加任何說明或前綴。"
                    ),
                ],
            )
        ],
    )

    transcription = response.text or ""
    logger.info(f"Transcription result ({len(transcription)} chars): {transcription[:80]}...")
    return transcription
```

- [ ] **Step 2: Commit**

```bash
git add tools/audio_tool.py
git commit -m "feat(audio): add transcribe_audio tool using Gemini multimodal API"
```

---

## Task 2: Patch `handle_text_message_via_orchestrator()` in `main.py`

**Files:**
- Modify: `main.py:378-413`

Current code at line 378-412:
```python
async def handle_text_message_via_orchestrator(event: MessageEvent, user_id: str):
    msg = event.message.text.strip()
    try:
        ...
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
    except Exception as e:
        ...
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
```

- [ ] **Step 1: Add optional `text` and `push_user_id` parameters**

Change the function signature and update the two `reply_message` calls to support push mode:

```python
async def handle_text_message_via_orchestrator(
    event: MessageEvent, user_id: str, text: str = None, push_user_id: str = None
):
    msg = text if text is not None else event.message.text.strip()
    try:
        ...
        reply_msg = TextSendMessage(text=response_text)
        if push_user_id:
            await line_bot_api.push_message(push_user_id, [reply_msg])
        else:
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
        ...
    except Exception as e:
        ...
        error_msg = TextSendMessage(text=error_text)
        if push_user_id:
            await line_bot_api.push_message(push_user_id, [error_msg])
        else:
            await line_bot_api.reply_message(event.reply_token, [error_msg])
```

> **Why `push_user_id`:** LINE reply tokens are single-use. When `handle_audio_message` already consumed the token for Reply #1 (transcription), Reply #2 (orchestrator) must use `push_message` instead. Passing `push_user_id` tells this function to switch modes. Normal text message calls pass nothing and continue using `reply_message` as before.

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "refactor: add optional text and push_user_id params to handle_text_message_via_orchestrator"
```

---

## Task 3: Add `AudioMessage` support in `main.py`

**Files:**
- Modify: `main.py:19` (imports)
- Modify: `main.py:293-296` (handle_message_event dispatch)
- Modify: `main.py` (new handle_audio_message function, after handle_image_message)

- [ ] **Step 1: Add `AudioMessage` to LINE SDK imports**

Find line 19:
```python
    MessageEvent, TextSendMessage, ImageSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage,
```

Change to:
```python
    MessageEvent, TextSendMessage, ImageSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage, AudioMessage,
```

- [ ] **Step 2: Add import for `transcribe_audio` at top of local imports**

After the existing local imports (around line 26-27), add:
```python
from tools.audio_tool import transcribe_audio
```

- [ ] **Step 3: Add `AudioMessage` branch in `handle_message_event()`**

Find this block (around line 293-296):
```python
        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)
        elif isinstance(event.message, LocationMessage):
            await handle_location_message(event)
```

Add one branch after `ImageMessage`:
```python
        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)
        elif isinstance(event.message, AudioMessage):
            await handle_audio_message(event)
        elif isinstance(event.message, LocationMessage):
            await handle_location_message(event)
```

- [ ] **Step 4: Add `handle_audio_message()` function**

Add this function after `handle_image_message()` (around line 490, before `handle_agentic_vision_with_prompt`):

```python
async def handle_audio_message(event: MessageEvent):
    """Handle audio (voice) messages — transcribe and route through Orchestrator."""
    user_id = event.source.user_id
    try:
        # Download audio from LINE
        message_content = await line_bot_api.get_message_content(event.message.id)
        audio_bytes = b""
        async for chunk in message_content.iter_content():
            audio_bytes += chunk
        logger.info(f"Downloaded audio for user {user_id}: {len(audio_bytes)} bytes")

        # Transcribe via Gemini
        transcription = await transcribe_audio(audio_bytes)

        # Guard: empty transcription
        if not transcription.strip():
            await line_bot_api.reply_message(
                event.reply_token,
                [TextSendMessage(text="無法辨識語音內容，請重新錄製。")]
            )
            return

        # Reply #1: show transcription to user
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=f"你說的是：{transcription.strip()}")]
        )

        # Reply #2: run transcription through Orchestrator.
        # Must use push_user_id=user_id because the reply token was already consumed in Reply #1.
        await handle_text_message_via_orchestrator(event, user_id, text=transcription.strip(), push_user_id=user_id)

    except Exception as e:
        logger.error(f"Error handling audio message for user {user_id}: {e}", exc_info=True)
        error_text = LineService.format_error_message(e, "處理語音訊息")
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=error_text)]
        )

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat(audio): handle LINE AudioMessage — transcribe and route via Orchestrator"
```

---

## Task 4: Manual Smoke Test

No automated test suite exists in this project. Test manually via LINE app:

- [ ] Send a voice message (繁中) in 1:1 chat → expect Reply #1 "你說的是：..." + Reply #2 orchestrator response
- [ ] Send a voice message (English) → expect transcription in English, orchestrator responds
- [ ] Send a very short/silent voice message → expect "無法辨識語音內容，請重新錄製。"
- [ ] Send a text message after the voice test → confirm existing text flow still works (no regression)
- [ ] Send a URL → confirm URL handling unaffected
- [ ] Send an image → confirm image handling unaffected
