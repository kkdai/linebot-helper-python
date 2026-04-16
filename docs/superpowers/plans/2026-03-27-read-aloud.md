# 朗讀摘要 (Read Aloud) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "🔊 朗讀摘要" QuickReply button to all URL/YouTube/PDF summaries; when pressed, Gemini 3.1 Flash TTS generates a voice message that the bot sends back as a LINE AudioSendMessage.

**Architecture:** New `tools/tts_tool.py` wraps the Gemini 3.1 Flash TTS API (`generate_content_stream`) and converts to m4a via ffmpeg temp files. `main.py` stores summaries by UUID, adds a QuickReply button to all summaries, serves audio via `/audio/{id}`, and routes the postback to a new `handle_read_aloud_postback()` handler.

**Tech Stack:** `google-genai` TTS API (`client.aio.models.generate_content_stream`), `ffmpeg` (subprocess, temp files), `linebot` SDK `AudioSendMessage`, FastAPI.

**Spec:** `docs/superpowers/specs/2026-03-27-read-aloud-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `tools/tts_tool.py` | `text_to_speech()` — Gemini Live TTS + PCM→m4a |
| Modify | `tools/__init__.py` | export `text_to_speech` |
| Modify | `main.py:18-28` | Add `AudioSendMessage` import + `tts_tool` import |
| Modify | `main.py:95-105` | Add `summary_store`, `audio_store`, TTL constants |
| Modify | `main.py:176` | Add `GET /audio/{audio_id}` endpoint (after `/images/`) |
| Modify | `main.py:302-378` | `handle_url_message()` — store summary + add QuickReply |
| Modify | `main.py:798-839` | `handle_postback_event()` — add `read_aloud` routing |
| Modify | `main.py` (after line ~839) | New `handle_read_aloud_postback()` function |
| Modify | `Dockerfile:21-28` | Add `ffmpeg` to `apt-get install` |

---

## Task 1: Create `tools/tts_tool.py`

**Files:**
- Create: `tools/tts_tool.py`

- [ ] **Step 1: Create the file**

```python
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
VERTEX_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")


async def text_to_speech(text: str) -> tuple[bytes, int]:
    """
    Convert text to speech using Gemini Live API.

    Args:
        text: Text to synthesize. Keep under ~1000 chars to stay under 1 minute.

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

    # PCM: 16kHz × 16-bit mono = 32000 bytes/sec
    duration_ms = int(len(pcm_bytes) / 32000 * 1000)

    # Convert PCM → m4a via ffmpeg (temp file mode avoids moov atom issues)
    pcm_path = None
    m4a_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as pcm_file:
            pcm_file.write(pcm_bytes)
            pcm_path = pcm_file.name

        m4a_path = pcm_path.replace(".pcm", ".m4a")

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

        with open(m4a_path, "rb") as f:
            m4a_bytes = f.read()

    finally:
        if pcm_path and os.path.exists(pcm_path):
            os.unlink(pcm_path)
        if m4a_path and os.path.exists(m4a_path):
            os.unlink(m4a_path)

    logger.info(f"TTS complete: {len(m4a_bytes)} bytes, {duration_ms}ms")
    return m4a_bytes, duration_ms
```

- [ ] **Step 2: Commit**

```bash
git add tools/tts_tool.py
git commit -m "feat(tts): add text_to_speech tool using Gemini Live API"
```

---

## Task 2: Export `text_to_speech` from `tools/__init__.py`

**Files:**
- Modify: `tools/__init__.py`

Current last line of imports:
```python
from .audio_tool import transcribe_audio
```

- [ ] **Step 1: Add export**

Add after the `transcribe_audio` import:
```python
from .tts_tool import text_to_speech
```

And add to `__all__`:
```python
    # TTS tools
    "text_to_speech",
```

- [ ] **Step 2: Commit**

```bash
git add tools/__init__.py
git commit -m "feat(tts): export text_to_speech from tools package"
```

---

## Task 3: Add infrastructure to `main.py` (imports, stores, `/audio` endpoint)

**Files:**
- Modify: `main.py:18-28` (imports)
- Modify: `main.py:95-105` (module-level stores)
- Modify: `main.py:176-204` (after existing `/images/` endpoint)

- [ ] **Step 1: Add `AudioSendMessage` to LINE SDK imports**

Current line 18-21:
```python
from linebot.models import (
    MessageEvent, TextSendMessage, ImageSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage, AudioMessage,
    QuickReply, QuickReplyButton, PostbackAction
)
```

Change to:
```python
from linebot.models import (
    MessageEvent, TextSendMessage, ImageSendMessage, AudioSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage, AudioMessage,
    QuickReply, QuickReplyButton, PostbackAction
)
```

- [ ] **Step 2: Add `text_to_speech` to local imports**

Current line 28:
```python
from tools.audio_tool import transcribe_audio
```

Change to:
```python
from tools.audio_tool import transcribe_audio
from tools.tts_tool import text_to_speech
```

- [ ] **Step 3: Add stores and constants at module level**

Find the block around line 100-105 that ends with:
```python
ANNOTATED_IMAGE_TTL = 300  # 5 minutes
# Base URL for serving images (auto-detected from webhook request)
app_base_url: str = ""
```

Add after `ANNOTATED_IMAGE_TTL`:
```python
# Summary store for read-aloud QuickReply (keyed by UUID)
# Format: {summary_id: {"text": str, "created_at": float}}
summary_store: Dict[str, dict] = {}
SUMMARY_TTL = 600  # 10 minutes
# Audio store for serving generated voice messages (keyed by UUID)
# Format: {audio_id: {"data": bytes, "created_at": float}}
audio_store: Dict[str, dict] = {}
AUDIO_TTL = 300  # 5 minutes
MAX_TTS_CHARS = 1000  # Truncate summaries to keep audio under ~1 minute
```

- [ ] **Step 4: Add `/audio/{audio_id}` endpoint**

Find the `store_annotated_image` function (around line 191). Add this block immediately after it (before `@app.post("/hn")`):

```python
@app.get("/audio/{audio_id}")
def serve_audio(audio_id: str):
    """Serve a temporarily stored TTS audio file for LINE AudioSendMessage"""
    entry = audio_store.get(audio_id)
    if not entry or time.time() - entry["created_at"] > AUDIO_TTL:
        audio_store.pop(audio_id, None)
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    return Response(content=entry["data"], media_type="audio/mp4")
```

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(tts): add audio store, /audio endpoint, and imports to main.py"
```

---

## Task 4: Add QuickReply to `handle_url_message()`

**Files:**
- Modify: `main.py:319-378` (`handle_url_message` for loop body)

The key change: after `formatted_result` is ready (line ~332), store the summary and build a QuickReply button. For YouTube, append to existing items; for all others, create a new QuickReply.

- [ ] **Step 1: Add summary storage + button builder inside the for loop**

Read lines 319-378 of main.py first to confirm exact current code.

**Critical:** The following code must go **inside the existing `try:` block** (12-space indentation), immediately after the line `formatted_result = format_content_response(result, include_url=True)`. Do NOT place it after the `except` clause.

```python
            # Store summary for read-aloud (inside try: block, 12-space indent)
            now = time.time()
            expired_summaries = [k for k, v in summary_store.items() if now - v["created_at"] > SUMMARY_TTL]
            for k in expired_summaries:
                summary_store.pop(k, None)
            summary_id = str(uuid.uuid4())
            summary_store[summary_id] = {"text": formatted_result, "created_at": now}

            read_aloud_button = QuickReplyButton(
                action=PostbackAction(
                    label="🔊 朗讀",
                    data=json.dumps({"action": "read_aloud", "summary_id": summary_id}),
                    display_text="🔊 朗讀摘要"
                )
            )
```

Note: `pdf` content type falls through to the `else` branch — no separate PDF handling needed.

- [ ] **Step 2: Update YouTube branch to include read_aloud_button**

Current YouTube block builds `quick_reply_buttons` with two items (Detail + Post on X). Find it and add `read_aloud_button` as a third item:

```python
            if content_type == "youtube":
                quick_reply_buttons = QuickReply(
                    items=[
                        QuickReplyButton(
                            action=PostbackAction(
                                label="📄 Detail",
                                data=json.dumps({
                                    "action": "youtube_summary",
                                    "mode": "detail",
                                    "url": url
                                }),
                                display_text="📄 詳細摘要"
                            )
                        ),
                        QuickReplyButton(
                            action=PostbackAction(
                                label="🐦 Post on X",
                                data=json.dumps({
                                    "action": "youtube_summary",
                                    "mode": "twitter",
                                    "url": url
                                }),
                                display_text="🐦 Twitter 分享文案"
                            )
                        ),
                        read_aloud_button,
                    ]
                )
                reply_msg = TextSendMessage(text=formatted_result, quick_reply=quick_reply_buttons)
```

- [ ] **Step 3: Update non-YouTube branch to add QuickReply**

Current `else` branch:
```python
            else:
                reply_msg = TextSendMessage(text=formatted_result)
```

Change to:
```python
            else:
                reply_msg = TextSendMessage(
                    text=formatted_result,
                    quick_reply=QuickReply(items=[read_aloud_button])
                )
```

- [ ] **Step 4: Read back modified section to verify**

Read `main.py` lines 319-378 to confirm the changes look correct.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(tts): add 🔊 朗讀摘要 QuickReply to all URL/YouTube/PDF summaries"
```

---

## Task 5: Add `handle_read_aloud_postback()` and routing

**Files:**
- Modify: `main.py:808-824` (`handle_postback_event` routing block)
- Modify: `main.py` (new function after `handle_postback_event`)

- [ ] **Step 1: Add routing in `handle_postback_event()`**

Find this block (around line 816-824):
```python
        # Handle image analysis requests
        if action_value == "image_analyze":
            await handle_image_analyze_postback(event, data, user_id)
            return

        # Handle YouTube summary requests
        if action_value == "youtube_summary":
            await handle_youtube_summary_postback(event, data)
            return
```

Add after `youtube_summary` block:
```python
        # Handle read aloud requests
        if action_value == "read_aloud":
            await handle_read_aloud_postback(event, data, user_id)
            return
```

- [ ] **Step 2: Add `handle_read_aloud_postback()` function**

Add this function after `handle_postback_event()` (before `handle_url_push_message` at line ~842):

```python
async def handle_read_aloud_postback(event: PostbackEvent, data: dict, user_id: str):
    """Handle 🔊 朗讀摘要 postback — generate TTS audio and send as AudioSendMessage."""
    summary_id = data.get("summary_id")
    entry = summary_store.get(summary_id)

    if not entry or time.time() - entry["created_at"] > SUMMARY_TTL:
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text="摘要已過期，請重新傳送網址。")]
        )
        return

    try:
        text = entry["text"][:MAX_TTS_CHARS]
        m4a_bytes, duration_ms = await text_to_speech(text)

        # Cleanup expired audio (sweep-on-write)
        now = time.time()
        expired = [k for k, v in audio_store.items() if now - v["created_at"] > AUDIO_TTL]
        for k in expired:
            audio_store.pop(k, None)

        audio_id = str(uuid.uuid4())
        audio_store[audio_id] = {"data": m4a_bytes, "created_at": now}

        audio_url = f"{app_base_url}/audio/{audio_id}"
        await line_bot_api.reply_message(
            event.reply_token,
            [AudioSendMessage(original_content_url=audio_url, duration=duration_ms)]
        )
        logger.info(f"Read aloud sent to user {user_id}: {duration_ms}ms")

    except Exception as e:
        logger.error(f"Read aloud error for user {user_id}: {e}", exc_info=True)
        error_text = LineService.format_error_message(e, "產生語音")
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=error_text)]
        )
```

- [ ] **Step 3: Read back to verify both changes look correct**

Read `main.py` around line 808-850 to confirm routing and new function.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(tts): add handle_read_aloud_postback and routing"
```

---

## Task 6: Add ffmpeg to Dockerfile

**Files:**
- Modify: `Dockerfile:21-28`

- [ ] **Step 1: Add ffmpeg to apt-get install**

Current block:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        git \
        chromium \
    && npm install -g single-file-cli \
```

Change to:
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        git \
        chromium \
        ffmpeg \
    && npm install -g single-file-cli \
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "chore(docker): add ffmpeg for PCM to m4a audio conversion"
```

---

## Task 7: Manual Smoke Test

No automated test suite. Test manually after deploying:

- [ ] Send a URL (e.g. a news article) in 1:1 LINE chat → confirm summary appears with "🔊 朗讀" QuickReply button
- [ ] Send a YouTube URL → confirm summary has 3 QuickReply buttons (📄 Detail, 🐦 Post on X, 🔊 朗讀)
- [ ] Press "🔊 朗讀摘要" → confirm a voice message arrives within ~10 seconds
- [ ] Press "🔊 朗讀摘要" again after 10 minutes → confirm "摘要已過期" reply
- [ ] Send a text message after → confirm existing text flow unaffected
- [ ] Send an image → confirm image flow unaffected
- [ ] Send a voice message → confirm transcription flow unaffected
