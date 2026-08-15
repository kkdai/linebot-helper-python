"""LIFF 語音助手 — Gemini Live API 協定層

從 main.py 抽出，讓 WebSocket relay 邏輯可以獨立測試。

協定重點（gemini-3.1-flash-live）：
- send_client_content 只能用於連線初期塞入歷史，不可在對話中使用
- PTT 模式：停用自動 VAD，由瀏覽器送 activity_start / activity_end
- 免持模式：保留自動 VAD，由 Gemini 偵測說話結束（此時不可送 activity 信號）
"""
import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from google.genai import types as live_types

from tools.maps_tool import search_nearby_places

logger = logging.getLogger(__name__)

VOICE_MODEL = "gemini-3.1-flash-live-preview"
VOICE_NAME = "Aoede"


def build_voice_tools() -> list:
    """語音助手可用的工具：Google Search grounding + 附近地點查詢。

    Google Search 與 function declarations 需放在不同的 Tool 物件。
    座標由後端注入（make_tool_handler），不讓模型自行猜測。
    """
    return [
        live_types.Tool(google_search=live_types.GoogleSearch()),
        live_types.Tool(function_declarations=[
            live_types.FunctionDeclaration(
                name="search_nearby_places",
                description=(
                    "查詢使用者目前位置附近的地點（餐廳、停車場、加油站）。"
                    "使用者的座標由系統自動帶入，不需要提供。"
                ),
                parameters=live_types.Schema(
                    type=live_types.Type.OBJECT,
                    properties={
                        "place_type": live_types.Schema(
                            type=live_types.Type.STRING,
                            enum=["restaurant", "parking", "gas_station"],
                            description="地點類型",
                        ),
                        "custom_query": live_types.Schema(
                            type=live_types.Type.STRING,
                            description="自訂查詢語句（例如「附近的日式拉麵店」），可省略",
                        ),
                    },
                ),
            ),
        ]),
    ]


def make_tool_handler(
    lat: Optional[float], lng: Optional[float]
) -> Callable[[str, dict], Awaitable[dict]]:
    """建立 tool_call 執行器，注入使用者座標。"""

    async def handler(name: str, args: dict) -> dict:
        if name == "search_nearby_places":
            if lat is None or lng is None:
                return {
                    "status": "error",
                    "error_message": "沒有使用者座標，請改用 Google Search 或請使用者口述位置",
                }
            # search_nearby_places 是同步函式（內部呼叫 Vertex AI），丟到 thread 避免卡住 relay
            return await asyncio.to_thread(
                search_nearby_places,
                latitude=lat,
                longitude=lng,
                place_type=args.get("place_type", "restaurant"),
                custom_query=args.get("custom_query"),
            )
        return {"status": "error", "error_message": f"未知的工具：{name}"}

    return handler


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


def build_live_config(
    system_instruction: str,
    handsfree: bool,
    tools: Optional[list] = None,
) -> live_types.LiveConnectConfig:
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
    if tools:
        kwargs["tools"] = tools
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
    tool_handler: Optional[Callable[[str, dict], Awaitable[dict]]] = None,
) -> None:
    """Relay Gemini Live responses back to browser; push to LINE on turn_complete.

    push_fn(user_speech, ai_response)：每輪完成時回報 LINE 的 callback。
    tool_handler(name, args) -> dict：執行 Live function calling 的工具。
    """
    ai_text_accum = []
    user_text_accum = []
    try:
        while True:
            # Turn-based iteration: the for-loop ending signals turn_complete
            turn = session.receive()
            turn_interrupted = False
            saw_tool_call = False
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

                # Input transcription (user's speech-to-text) — 即時回傳前端顯示
                sc = response.server_content
                if sc and getattr(sc, "input_transcription", None):
                    t = sc.input_transcription.text or ""
                    if t:
                        user_text_accum.append(t)
                        await websocket.send_text(
                            json.dumps({
                                "type": "user_transcript",
                                "text": "".join(user_text_accum),
                            })
                        )

                # 免持 barge-in：Gemini 偵測到使用者插話，通知前端清 playback queue
                if sc and getattr(sc, "interrupted", None):
                    turn_interrupted = True
                    await websocket.send_text(json.dumps({"type": "interrupted"}))

                # Function calling（同步）：執行工具並回傳結果，模型收到後才會繼續說話
                tc = getattr(response, "tool_call", None)
                if tc and tool_handler and getattr(tc, "function_calls", None):
                    saw_tool_call = True
                    function_responses = []
                    for fc in tc.function_calls:
                        try:
                            result = await tool_handler(fc.name, dict(fc.args or {}))
                        except Exception as e:
                            logger.error(f"tool {fc.name} failed: {e}", exc_info=True)
                            result = {"status": "error", "error_message": str(e)[:200]}
                        function_responses.append(
                            live_types.FunctionResponse(
                                id=fc.id, name=fc.name, response=result
                            )
                        )
                    await session.send_tool_response(function_responses=function_responses)

            # tool_call 造成的 turn 結束不算一輪完成（模型拿到結果後會接著說）
            if saw_tool_call and not ai_text_accum:
                continue

            # For-loop ended = turn_complete (or interrupt cleared the queue)
            if turn_interrupted or state.get("interrupted"):
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
