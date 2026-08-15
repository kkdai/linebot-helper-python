"""LIFF 語音助手 — Gemini Live API 協定層

從 main.py 抽出，讓 WebSocket relay 邏輯可以獨立測試。

協定重點（gemini-3.1-flash-live）：
- send_client_content 只能用於連線初期塞入歷史，不可在對話中使用
- PTT 模式：停用自動 VAD，由瀏覽器送 activity_start / activity_end
- 免持模式：保留自動 VAD，由 Gemini 偵測說話結束（此時不可送 activity 信號）
"""
import json
import logging
from typing import Awaitable, Callable, Optional

from google.genai import types as live_types

logger = logging.getLogger(__name__)

VOICE_MODEL = "gemini-3.1-flash-live-preview"
VOICE_NAME = "Aoede"


def build_system_instruction(lat: Optional[float], lng: Optional[float]) -> str:
    location_info = (
        f"使用者目前位置：緯度 {lat:.6f}，經度 {lng:.6f}"
        if lat and lng
        else "使用者未提供位置資訊，地點查詢時請請求使用者口述位置"
    )
    return f"""你是一個整合多種工具的語音助手，透過 LINE Bot 服務使用者。

{location_info}

你可以：
- 查詢附近地點（使用 maps 工具查詢餐廳、停車場、加油站等）
- 摘要網頁、YouTube 影片或 PDF 內容
- 回答一般問題（搭配 Google Search）
- 提供天氣、交通等即時資訊

請用繁體中文回應，語氣自然口語，適合直接用語音播放。不要使用條列符號或 markdown 格式，改用自然的說話方式。每次回應控制在 50 字以內。"""


def build_live_config(system_instruction: str, handsfree: bool) -> live_types.LiveConnectConfig:
    """組出 LiveConnectConfig。PTT 模式停用自動 VAD，改用顯式 activity 信號。"""
    kwargs = dict(
        response_modalities=["AUDIO"],
        speech_config=live_types.SpeechConfig(
            voice_config=live_types.VoiceConfig(
                prebuilt_voice_config=live_types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
            )
        ),
        output_audio_transcription=live_types.AudioTranscriptionConfig(),
        input_audio_transcription=live_types.AudioTranscriptionConfig(),
        system_instruction=live_types.Content(
            role="system",
            parts=[live_types.Part(text=system_instruction)],
        ),
    )
    if not handsfree:
        kwargs["realtime_input_config"] = live_types.RealtimeInputConfig(
            automatic_activity_detection=live_types.AutomaticActivityDetection(disabled=True)
        )
    return live_types.LiveConnectConfig(**kwargs)


async def browser_to_gemini(websocket, session, state: dict) -> None:
    """Relay PCM audio and control events from browser to Gemini Live session."""
    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break
            if data.get("bytes"):
                await session.send_realtime_input(
                    audio=live_types.Blob(data=data["bytes"], mime_type="audio/pcm;rate=16000")
                )
            elif data.get("text"):
                event = json.loads(data["text"])
                etype = event.get("type")
                if etype == "start_of_speech":
                    # PTT 按下：顯式標記說話開始（自動 VAD 已停用）
                    if not state.get("handsfree"):
                        await session.send_realtime_input(
                            activity_start=live_types.ActivityStart()
                        )
                elif etype == "end_of_speech":
                    # PTT 放開：顯式標記說話結束。免持模式交給自動 VAD，不可送 activity。
                    if not state.get("handsfree"):
                        await session.send_realtime_input(
                            activity_end=live_types.ActivityEnd()
                        )
                elif etype == "interrupt":
                    state["interrupted"] = True
    except Exception as e:
        logger.error(f"browser_to_gemini error: {e}", exc_info=True)


async def gemini_to_browser(
    websocket,
    session,
    state: dict,
    push_fn: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> None:
    """Relay Gemini Live responses back to browser; push to LINE on turn_complete.

    push_fn(user_speech, ai_response)：每輪完成時回報 LINE 的 callback。
    """
    ai_text_accum = []
    user_text_accum = []
    try:
        while True:
            # Turn-based iteration: the for-loop ending signals turn_complete
            turn = session.receive()
            async for response in turn:
                # Audio output
                if response.data:
                    await websocket.send_bytes(response.data)

                # Text (AI speech transcription via output_audio_transcription)
                if response.text:
                    ai_text_accum.append(response.text)
                    await websocket.send_text(
                        json.dumps({"type": "text_chunk", "text": response.text})
                    )

                # Input transcription (user's speech-to-text)
                sc = response.server_content
                if sc and getattr(sc, "input_transcription", None):
                    t = sc.input_transcription.text or ""
                    if t:
                        user_text_accum.append(t)

            # For-loop ended = turn_complete (or interrupt cleared the queue)
            if state.get("interrupted"):
                state["interrupted"] = False
                ai_text_accum.clear()
                user_text_accum.clear()
            else:
                await websocket.send_text(json.dumps({"type": "turn_complete"}))
                user_speech = "".join(user_text_accum).strip() or "（語音輸入）"
                ai_response = "".join(ai_text_accum).strip()
                if ai_response and push_fn:
                    try:
                        await push_fn(user_speech, ai_response)
                    except Exception as e:
                        logger.error(f"voice push_fn failed: {e}")
                ai_text_accum.clear()
                user_text_accum.clear()

    except Exception as e:
        logger.error(f"gemini_to_browser error: {e}", exc_info=True)
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "message": "語音服務發生錯誤"})
            )
        except Exception:
            pass
