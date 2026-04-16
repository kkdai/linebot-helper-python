# 朗讀摘要 (Read Aloud) Design

**Date:** 2026-03-27
**Status:** Approved

## Overview

After the bot returns a URL/YouTube/PDF summary, a "🔊 朗讀摘要" QuickReply button appears. When the user presses it, the bot generates a voice message using Gemini 3.1 Flash Live API (TTS) and sends it back as a LINE AudioSendMessage.

## Requirements

- Trigger: all content types (URL, YouTube, PDF) — whenever `handle_url_message()` produces a successful summary
- TTS engine: Gemini 3.1 Flash TTS API (`response_modalities: ["audio"]`)
- Model: `gemini-3.1-flash-tts-preview`
- Audio conversion: PCM (16-bit, 24kHz, mono) → m4a via ffmpeg temp-file mode
- Summary storage: UUID-keyed `summary_store` dict with 10-minute TTL + sweep-on-write cleanup
- Audio storage: UUID-keyed `audio_store` dict with 5-minute TTL
- Scope: 1:1 chat only (consistent with other message handlers)
- Multi-URL: if user sends 3 URLs, each summary gets its own QuickReply button and `summary_id` — this is intentional

## Data Flow

```
User sends URL/YouTube/PDF
  → handle_url_message() → ContentAgent → summary text
    → summary_id = UUID; summary_store[summary_id] = {text, created_at}
      → TextSendMessage(text=summary, quick_reply=QuickReply([🔊 朗讀摘要]))
        postback data: {"action": "read_aloud", "summary_id": summary_id}

User presses 🔊 朗讀摘要
  → PostbackEvent → handle_postback_event() → handle_read_aloud_postback()
    → summary_store[summary_id] → summary text (max 1000 chars, truncated if longer)
      → tools/tts_tool.py: text_to_speech(text) → (m4a_bytes, duration_ms)
        → audio_id = UUID; audio_store[audio_id] = {data, created_at}
          → AudioSendMessage(
                original_content_url=/audio/{audio_id},
                duration=duration_ms  # int, milliseconds
            )
```

## Components

### New: `tools/tts_tool.py`

```python
async def text_to_speech(text: str) -> tuple[bytes, int]:
    """
    Convert text to speech using Gemini Live API.

    Returns:
        (m4a_bytes, duration_ms)  — duration_ms is int

    Raises:
        Exception on failure (including empty audio)
    """
```

Implementation steps:

**Step 1 — Connect and send text**

Use `send_client_content` (NOT `send_realtime_input` — that is for streaming VAD audio input):

```python
client = genai.Client(vertexai=True, project=VERTEX_PROJECT, location=VERTEX_LOCATION)

config = {"response_modalities": ["AUDIO"]}
async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
    await session.send_client_content(
        turns=types.Content(role="user", parts=[types.Part(text=text)]),
        turn_complete=True,
    )
```

**Step 2 — Collect PCM chunks until turn_complete**

```python
    pcm_chunks = []
    async for message in session.receive():
        if message.server_content and message.server_content.model_turn:
            for part in message.server_content.model_turn.parts:
                if part.inline_data and part.inline_data.data:
                    pcm_chunks.append(part.inline_data.data)
        if message.server_content and message.server_content.turn_complete:
            break

pcm_bytes = b"".join(pcm_chunks)
```

**Step 3 — Guard against empty audio**

```python
if not pcm_bytes:
    raise RuntimeError("No audio received from Gemini Live")
```

**Step 4 — Compute duration**

PCM is 16kHz × 16-bit mono = 32000 bytes/sec:

```python
duration_ms = int(len(pcm_bytes) / 32000 * 1000)
```

**Step 5 — Convert PCM → m4a via ffmpeg (temp file mode)**

Use temp files to avoid `moov` atom issues with pipe mode:

```python
import subprocess, tempfile, os

with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as pcm_file:
    pcm_file.write(pcm_bytes)
    pcm_path = pcm_file.name

m4a_path = pcm_path.replace(".pcm", ".m4a")
try:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "s16le", "-ar", "16000", "-ac", "1",
         "-i", pcm_path, "-c:a", "aac", m4a_path],
        check=True, capture_output=True,
    )
    with open(m4a_path, "rb") as f:
        m4a_bytes = f.read()
finally:
    os.unlink(pcm_path)
    if os.path.exists(m4a_path):
        os.unlink(m4a_path)

return m4a_bytes, duration_ms
```

**Model name:** Use `gemini-3.1-flash-live-preview` (same naming convention as other models in this project). Validate at runtime; if unavailable, the exception propagates to the error handler.

### Modified: `Dockerfile`

Add `ffmpeg` to existing `apt-get install` line:

```dockerfile
apt-get install -y --no-install-recommends \
    nodejs npm git chromium ffmpeg
```

### Modified: `main.py`

**1. New stores and TTL constants (module level)**

```python
summary_store: dict = {}   # {summary_id: {"text": str, "created_at": float}}
audio_store: dict = {}     # {audio_id: {"data": bytes, "created_at": float}}
SUMMARY_TTL = 600          # 10 minutes
AUDIO_TTL = 300            # 5 minutes
MAX_TTS_CHARS = 1000       # Truncate summaries to keep audio under ~1 minute
```

**2. New `/audio/{audio_id}` endpoint**

Mirrors existing `/images/{image_id}` pattern:

```python
@app.get("/audio/{audio_id}")
def serve_audio(audio_id: str):
    entry = audio_store.get(audio_id)
    if not entry or time.time() - entry["created_at"] > AUDIO_TTL:
        audio_store.pop(audio_id, None)
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    return Response(content=entry["data"], media_type="audio/mp4")
```

**3. `handle_url_message()` — add QuickReply to all successful summaries**

After `formatted_result` is ready, before building `TextSendMessage`:

```python
# Cleanup expired summaries (sweep-on-write, mirrors annotated_image_store pattern)
now = time.time()
expired = [k for k, v in summary_store.items() if now - v["created_at"] > SUMMARY_TTL]
for k in expired:
    summary_store.pop(k, None)

# Store summary for read-aloud
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

For YouTube: append `read_aloud_button` to the existing `items` list.
For others (URL, PDF): wrap in `QuickReply(items=[read_aloud_button])` on the `TextSendMessage`.

**4. `handle_postback_event()` — add routing**

```python
if action_value == "read_aloud":
    await handle_read_aloud_postback(event, data, user_id)
    return
```

**5. New `handle_read_aloud_postback(event, data, user_id)`**

```python
async def handle_read_aloud_postback(event: PostbackEvent, data: dict, user_id: str):
    summary_id = data.get("summary_id")
    entry = summary_store.get(summary_id)

    if not entry or time.time() - entry["created_at"] > SUMMARY_TTL:
        await line_bot_api.reply_message(event.reply_token,
            [TextSendMessage(text="摘要已過期，請重新傳送網址。")])
        return

    try:
        text = entry["text"][:MAX_TTS_CHARS]  # truncate to stay under ~1 min
        m4a_bytes, duration_ms = await text_to_speech(text)

        # Cleanup expired audio (sweep-on-write)
        now = time.time()
        expired = [k for k, v in audio_store.items() if now - v["created_at"] > AUDIO_TTL]
        for k in expired:
            audio_store.pop(k, None)

        audio_id = str(uuid.uuid4())
        audio_store[audio_id] = {"data": m4a_bytes, "created_at": now}

        audio_url = f"{app_base_url}/audio/{audio_id}"
        await line_bot_api.reply_message(event.reply_token, [
            AudioSendMessage(
                original_content_url=audio_url,
                duration=duration_ms
            )
        ])
    except Exception as e:
        logger.error(f"Read aloud error for user {user_id}: {e}", exc_info=True)
        error_text = LineService.format_error_message(e, "產生語音")
        await line_bot_api.reply_message(event.reply_token,
            [TextSendMessage(text=error_text)])
```

**6. New imports**

- LINE SDK: add `AudioSendMessage` to linebot.models import
- Local: `from tools.tts_tool import text_to_speech`

## Error Handling

| Scenario | Handling |
|----------|----------|
| summary_id not found / expired | reply "摘要已過期，請重新傳送網址。" |
| Gemini Live returns no audio | `RuntimeError` propagates → `format_error_message` reply |
| Gemini Live TTS failure | exception propagates → `format_error_message` reply |
| ffmpeg conversion failure | `subprocess.CalledProcessError` propagates → same |
| audio_id not found / expired | HTTP 404 from `/audio/{id}` endpoint |

## Out of Scope

- Group chat support
- Voice selection / language configuration
- Caching TTS results for identical text
- Persistent audio storage (Cloud Storage)
