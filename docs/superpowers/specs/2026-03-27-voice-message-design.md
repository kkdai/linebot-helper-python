# Voice Message Handling Design

**Date:** 2026-03-27
**Status:** Approved

## Overview

Add support for LINE audio messages (m4a) in 1:1 chat. When a user sends a voice message, the bot transcribes it using the standard Gemini API, shows the transcription to the user, then passes the text through the existing Orchestrator pipeline for a full AI response.

## Requirements

- Scope: 1:1 chat only (group/room chats ignored)
- API: Standard Gemini API (inline audio bytes), not Gemini Flash Live
- UX: Two-message design — reply transcription first ("你說的是：...") so user sees it immediately while orchestrator processes; then send Orchestrator response as a second message

## Data Flow

```
User sends AudioMessage (m4a)
  → handle_audio_message() in main.py
    → LINE SDK: get_message_content(message_id) → audio bytes
      → tools/audio_tool.py: transcribe_audio() → transcription text
        → LINE reply #1: "你說的是：{transcription}"
          → handle_text_message_via_orchestrator(event, user_id, text=transcription)
            → Orchestrator → appropriate Agent → LINE reply #2
```

## Components

### New: `tools/audio_tool.py`

Single async function:

```python
async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/mp4") -> str
```

- `mime_type` defaults to `"audio/mp4"` — LINE audio messages are always m4a which maps to this MIME type; no runtime detection needed
- Sends audio as inline data to `gemini-3.1-flash-lite-preview` via `google-genai`
- Prompt: transcribe speech to text, preserve original language
- Returns transcription string
- Raises exception on failure (caller handles error display)

### Modified: `main.py`

**1. Imports**

Add `AudioMessage` to LINE SDK imports.

**2. `handle_message_event()`**

Add branch in the 1:1 (SourceUser) section:
```python
elif isinstance(event.message, AudioMessage):
    await handle_audio_message(event)
```

**3. `handle_text_message_via_orchestrator()` — signature change**

Refactor to accept optional `text` and `push_user_id` parameters:
```python
async def handle_text_message_via_orchestrator(
    event: MessageEvent, user_id: str, text: str = None, push_user_id: str = None
):
    message_text = text if text is not None else event.message.text.strip()
    ...
    # Use push_message when push_user_id is provided (reply token already consumed)
    if push_user_id:
        await line_bot_api.push_message(push_user_id, [reply_msg])
    else:
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
```

**Why `push_user_id`:** LINE reply tokens are single-use. `handle_audio_message` consumes the token for Reply #1 (transcription text). Reply #2 (orchestrator response) must use `push_message` instead. Passing `push_user_id` switches the function to push mode. Normal text message calls pass nothing and continue using `reply_message` unchanged.

**4. New: `handle_audio_message(event: MessageEvent)`**

```
1. user_id = event.source.user_id
2. Try:
   a. Download: audio_bytes = line_bot_api.get_message_content(event.message.id)
   b. Transcribe: transcription = await transcribe_audio(audio_bytes)
   c. Check: if not transcription.strip() → reply "無法辨識語音內容，請重新錄製" and return
   d. Reply #1: "你說的是：{transcription}"
   e. Call: handle_text_message_via_orchestrator(event, user_id, text=transcription, push_user_id=user_id)
3. Except: reply via error_handler.py in Traditional Chinese
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| LINE content download fails | Catch exception → error_handler reply |
| Gemini transcription fails | Catch exception → error_handler reply |
| Empty/whitespace transcription (`not transcription.strip()`) | Reply "無法辨識語音內容，請重新錄製" |
| Orchestrator failure | Existing error handling in orchestrator path |

## Model

- `gemini-3.1-flash-lite-preview` — supports multimodal audio input via inline bytes
- Vertex AI client already initialized in `main.py`; `audio_tool.py` receives or initializes same client

## Out of Scope

- Group/room chat audio messages
- Real-time streaming (Gemini Flash Live)
- Voice reply (text-to-speech output)
- Audio language detection UI
- Unit tests (existing project has no test suite)
