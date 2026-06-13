import asyncio
import os
import sys
import json  # added import for JSON conversion
import uuid
import time
import hmac
import hashlib
import base64
import jwt
import requests
from io import BytesIO
from typing import Dict, Optional, List, Any
from urllib.parse import parse_qs

import aiohttp
import PIL.Image
from fastapi import Request, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import Response, HTMLResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
import logging
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextSendMessage, ImageSendMessage, AudioSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage, AudioMessage,
    QuickReply, QuickReplyButton, PostbackAction
)
from linebot.models.sources import SourceGroup, SourceRoom, SourceUser
from httpx import HTTPStatusError

# local files
from loader.url import is_youtube_url, load_url
from loader.text_utils import extract_url_and_mode, get_mode_description
from loader.langtools import summarize_text
from loader.error_handler import FriendlyErrorMessage
from tools.audio_tool import transcribe_audio
from tools.tts_tool import text_to_speech
from google import genai as live_genai
from google.genai import types as live_types

# ADK Orchestrator and Agents
from agents import (
    # Orchestrator (Main Controller)
    Orchestrator, create_orchestrator, format_orchestrator_response,
    # Individual agents for specific handlers
    format_content_response, format_location_response,
)
from services.line_service import LineService
from services.session_manager import get_session_manager

# Configure logging
logging.basicConfig(
    stream=sys.stdout, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Get all environment variables at the top
channel_secret = os.getenv('ChannelSecret')
linebot_user_id = os.getenv("LINE_USER_ID")
channel_access_token = os.getenv('ChannelAccessToken')
channel_access_token_hf = os.getenv('ChannelAccessTokenHF')
firecrawl_key = os.getenv('firecrawl_key')

# Vertex AI configuration
vertex_project = os.getenv('GOOGLE_CLOUD_PROJECT')
vertex_location = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

# Validate required environment variables
if not channel_secret:
    raise EnvironmentError('Specify ChannelSecret as environment variable.')
if not channel_access_token:
    raise EnvironmentError(
        'Specify ChannelAccessToken as environment variable.')
if not vertex_project:
    raise EnvironmentError('Specify GOOGLE_CLOUD_PROJECT as environment variable for Vertex AI.')
if not linebot_user_id:
    raise EnvironmentError('Specify LINE_USER_ID as environment variable.')
if not channel_access_token_hf:
    raise EnvironmentError(
        'Specify HuggingFace ChannelAccessToken as environment variable.')

# Log availability of optional features
if firecrawl_key:
    logger.info(
        'Firecrawl API key detected - will use for PTT, Medium, and OpenAI URLs')
else:
    logger.info(
        'No Firecrawl API key - using standard web scraping methods for all sites')

# Log Vertex AI configuration
logger.info(f'Vertex AI configured - Project: {vertex_project}, Location: {vertex_location}')
logger.info('Text search using Vertex AI Grounding with Google Search (no Custom Search API needed)')


class StoreMessage:
    def __init__(self, text: str, url: str):
        self.text = text
        self.url = url


# Initialize the FastAPI app for LINEBot
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)
msg_memory_store: Dict[str, StoreMessage] = {}
# Temporary image store for quick reply flow (keyed by user_id)
image_temp_store: Dict[str, bytes] = {}
# Pending agentic vision mode: user_id -> True means waiting for text prompt
pending_agentic_vision: Dict[str, bool] = {}
# Temporary annotated image store for serving to LINE (keyed by UUID)
# Format: {image_id: {"data": bytes, "created_at": float}}
annotated_image_store: Dict[str, dict] = {}
ANNOTATED_IMAGE_TTL = 300  # 5 minutes
# Summary store for read-aloud QuickReply (keyed by UUID)
# Format: {summary_id: {"text": str, "created_at": float}}
summary_store: Dict[str, dict] = {}
SUMMARY_TTL = 600  # 10 minutes
# Audio store for serving generated voice messages (keyed by UUID)
# Format: {audio_id: {"data": bytes, "created_at": float}}
audio_store: Dict[str, dict] = {}
AUDIO_TTL = 300  # 5 minutes
MAX_TTS_CHARS = 250  # Truncate summaries to keep audio under ~1 minute (~250 Chinese chars)
# Base URL for serving images (auto-detected from webhook request)
app_base_url: str = ""

# Initialize ADK Orchestrator (manages all specialized agents)
orchestrator = create_orchestrator()
logger.info('ADK Orchestrator initialized with all specialized agents (A2A enabled)')

# Get session manager singleton (used by ChatAgent)
session_manager = get_session_manager()

# Initialize LINE Service wrapper
line_service = None


@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup"""
    # Start session cleanup background task
    await session_manager.start_cleanup_task()
    logger.info("Session cleanup background task started")

    # Start batch job status polling background task
    asyncio.create_task(poll_batch_jobs_loop())
    logger.info("Batch job polling background task started")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    # Stop session cleanup task
    await session_manager.stop_cleanup_task()
    logger.info("Session cleanup background task stopped")

    # Close aiohttp session
    await session.close()
    logger.info("Application shutdown complete")


image_prompt = '''
Describe all the information from the image, reply in zh_tw.
'''


@app.post("/")
async def handle_webhook_callback(request: Request):
    global app_base_url
    signature = request.headers['X-Line-Signature']
    body = (await request.body()).decode()

    # Auto-detect base URL from request for serving images
    if not app_base_url:
        forwarded_proto = request.headers.get('x-forwarded-proto', 'https')
        host = request.headers.get('x-forwarded-host') or request.headers.get('host', '')
        if host:
            app_base_url = f"{forwarded_proto}://{host}"
            logger.info(f"App base URL detected: {app_base_url}")

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent):
            await handle_message_event(event)
        elif isinstance(event, PostbackEvent):
            await handle_postback_event(event)
    return 'OK'


LIFF_ID = os.getenv("LIFF_ID", "")
if not LIFF_ID:
    logger.warning("LIFF_ID env var not set — /liff/ will serve with unsubstituted placeholder")
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
VERTEX_PROJECT_LIVE = os.getenv("GOOGLE_CLOUD_PROJECT", "")


@app.get("/liff/")
def serve_liff():
    """Serve the LIFF voice assistant app with LIFF_ID injected."""
    try:
        with open("static/liff/index.html", encoding="utf-8") as f:
            html = f.read().replace("{{LIFF_ID}}", LIFF_ID)
        return HTMLResponse(html)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="LIFF app not found")


def _build_voice_system_instruction(lat: float | None, lng: float | None) -> str:
    location_info = f"使用者目前位置：緯度 {lat:.6f}，經度 {lng:.6f}" if lat and lng else "使用者未提供位置資訊，地點查詢時請請求使用者口述位置"
    return f"""你是一個整合多種工具的語音助手，透過 LINE Bot 服務使用者。

{location_info}

你可以：
- 查詢附近地點（使用 maps 工具查詢餐廳、停車場、加油站等）
- 摘要網頁、YouTube 影片或 PDF 內容
- 回答一般問題（搭配 Google Search）
- 提供天氣、交通等即時資訊

請用繁體中文回應，語氣自然口語，適合直接用語音播放。不要使用條列符號或 markdown 格式，改用自然的說話方式。每次回應控制在 50 字以內。"""


async def _browser_to_gemini(websocket: WebSocket, session, state: dict):
    """Relay PCM audio and control events from browser to Gemini Live session."""
    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break
            if data.get("bytes"):
                # send_realtime_input uses the non-deprecated `audio` field
                await session.send_realtime_input(
                    audio=live_types.Blob(data=data["bytes"], mime_type="audio/pcm;rate=16000")
                )
            elif data.get("text"):
                event = json.loads(data["text"])
                etype = event.get("type")
                if etype == "end_of_speech":
                    await session.send_client_content(turn_complete=True)
                elif etype == "interrupt":
                    state["interrupted"] = True
                elif etype == "toggle_handsfree":
                    state["handsfree"] = event.get("enabled", False)
    except Exception as e:
        logger.error(f"browser_to_gemini error: {e}", exc_info=True)


async def _gemini_to_browser(websocket: WebSocket, session, state: dict, user_id: str):
    """Relay Gemini Live responses back to browser; push to LINE on turn_complete."""
    ai_text_accum = []
    user_text_accum = []
    try:
        while True:
            # Turn-based iteration: the for-loop ending signals turn_complete
            # (pattern from google-gemini/cookbook Get_started_LiveAPI.py)
            turn = session.receive()
            async for response in turn:
                # Audio output
                if response.data:
                    await websocket.send_bytes(response.data)

                # Text (AI speech transcription via output_audio_transcription)
                if response.text:
                    ai_text_accum.append(response.text)
                    await websocket.send_text(json.dumps({"type": "text_chunk", "text": response.text}))

                # Input transcription (user's speech-to-text)
                sc = response.server_content
                if sc and hasattr(sc, "input_transcription") and sc.input_transcription:
                    t = sc.input_transcription.text or ""
                    if t:
                        user_text_accum.append(t)

            # For-loop ended = turn_complete (or interrupt cleared the queue)
            if state.get("interrupted"):
                state["interrupted"] = False
                # Drain any remaining buffered audio per cookbook comment:
                # "For interruptions to work, we need to stop playback"
                ai_text_accum.clear()
                user_text_accum.clear()
            else:
                await websocket.send_text(json.dumps({"type": "turn_complete"}))
                user_speech = "".join(user_text_accum).strip() or "（語音輸入）"
                ai_response = "".join(ai_text_accum).strip()
                if ai_response and user_id:
                    push_text = f"🎤 你說：{user_speech}\n\n🤖 AI：{ai_response}"
                    try:
                        await line_bot_api.push_message(user_id, [TextSendMessage(text=push_text)])
                    except Exception as e:
                        logger.error(f"push_message failed for {user_id}: {e}")
                ai_text_accum.clear()
                user_text_accum.clear()

    except Exception as e:
        logger.error(f"gemini_to_browser error: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "語音服務發生錯誤"}))
        except Exception:
            pass


@app.websocket("/ws/voice/{session_id}")
async def voice_ws(websocket: WebSocket, session_id: str):
    """Real-time voice assistant WebSocket — relay between LIFF and Gemini Live."""
    await websocket.accept()
    logger.info(f"Voice WS connected: {session_id}")
    try:
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
        init_data = json.loads(init_raw)
        user_id = init_data.get("user_id", session_id)
        lat = init_data.get("lat")
        lng = init_data.get("lng")
        system_instruction = _build_voice_system_instruction(lat, lng)

        # api_version="v1beta" required for gemini-3.1-flash-live-preview per cookbook sample
        client = live_genai.Client(
            api_key=GOOGLE_AI_API_KEY,
            vertexai=False,
            http_options={"api_version": "v1beta"},
        )
        config = live_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=live_types.SpeechConfig(
                voice_config=live_types.VoiceConfig(
                    prebuilt_voice_config=live_types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
            output_audio_transcription=live_types.AudioTranscriptionConfig(),
            input_audio_transcription=live_types.AudioTranscriptionConfig(),
            system_instruction=live_types.Content(
                role="system",
                parts=[live_types.Part(text=system_instruction)]
            ),
        )
        state = {"interrupted": False, "handsfree": False}

        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
            t1 = asyncio.create_task(_browser_to_gemini(websocket, session, state))
            t2 = asyncio.create_task(_gemini_to_browser(websocket, session, state, user_id))
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except asyncio.TimeoutError:
        logger.warning(f"Voice WS init timeout: {session_id}")
        await websocket.send_text(json.dumps({"type": "error", "message": "初始化逾時"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Voice WS error: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "語音服務暫時無法使用"}))
        except Exception:
            pass
    finally:
        logger.info(f"Voice WS disconnected: {session_id}")


@app.get("/")
def health_check():
    print("Health Check! Ok!")
    return "OK"


@app.get("/images/{image_id}")
def serve_annotated_image(image_id: str):
    """Serve a temporarily stored annotated image for LINE ImageSendMessage"""
    entry = annotated_image_store.get(image_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Image not found or expired")

    # Check TTL
    if time.time() - entry["created_at"] > ANNOTATED_IMAGE_TTL:
        annotated_image_store.pop(image_id, None)
        raise HTTPException(status_code=404, detail="Image expired")

    return Response(content=entry["data"], media_type="image/png")


def store_annotated_image(image_bytes: bytes) -> str:
    """Store annotated image and return its ID"""
    # Cleanup expired images
    now = time.time()
    expired = [k for k, v in annotated_image_store.items() if now - v["created_at"] > ANNOTATED_IMAGE_TTL]
    for k in expired:
        annotated_image_store.pop(k, None)

    image_id = str(uuid.uuid4())
    annotated_image_store[image_id] = {
        "data": image_bytes,
        "created_at": now,
    }
    return image_id


@app.get("/audio/{audio_id}")
def serve_audio(audio_id: str):
    """Serve a temporarily stored TTS audio file for LINE AudioSendMessage"""
    entry = audio_store.get(audio_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    if time.time() - entry["created_at"] > AUDIO_TTL:
        audio_store.pop(audio_id, None)
        raise HTTPException(status_code=404, detail="Audio expired")
    return Response(content=entry["data"], media_type="audio/mp4")


@app.post("/hn")
async def hacker_news_summarization(request: Request):
    data = await request.json()
    logger.info(f"/hn data={data}")
    title = data.get("title")
    url = data.get("url")
    story_url = data.get("StoryUrl")
    urls = [url]
    if story_url:
        urls.append(story_url)
    await handle_url_push_message(title, urls, linebot_user_id, channel_access_token)
    return {"status": "ok"}


@app.post("/hf")
async def huggingface_paper_summarization(request: Request):
    data = await request.json()
    logger.info(f"/hf data={data}")
    title = data.get("title")
    papertocode_url = data.get("url")
    url = replace_domain(
        papertocode_url, "paperswithcode.com", "huggingface.co")
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Invalid URL protocol")
    urls = [url]
    await handle_url_push_message(title, urls, linebot_user_id, channel_access_token_hf)
    return {"status": "ok"}


@app.post("/urls")
async def multi_url_summarization(request: Request):
    data = await request.json()
    logger.info(f"/urls data={data}")

    # Get parameters
    title = data.get("title", "")
    urls = data.get("urls", [])

    # Validate URLs
    if not urls or not isinstance(urls, list):
        raise HTTPException(status_code=400, detail="urls must be a non-empty array")

    if len(urls) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 URLs allowed")

    if len(urls) < 1:
        raise HTTPException(status_code=400, detail="At least 1 URL required")

    # Process and push message
    await handle_url_push_message(title, urls, linebot_user_id, channel_access_token)

    return {"status": "ok", "processed_urls": len(urls)}


async def handle_message_event(event: MessageEvent):
    # 先判断消息来源
    source_id = "unknown"

    if isinstance(event.source, SourceGroup):
        source_id = event.source.group_id
        logger.info(f"Group ID: {source_id}")
    elif isinstance(event.source, SourceRoom):
        source_id = event.source.room_id
        logger.info(f"Room ID: {source_id}")
    elif isinstance(event.source, SourceUser):
        # 1:1 chat
        # Use Orchestrator to handle all message types
        if isinstance(event.message, TextMessage):
            user_id = event.source.user_id
            logger.info(f"UID: {user_id}")
            message_text = event.message.text

            # Check if user has a pending agentic vision request
            if user_id in pending_agentic_vision:
                await handle_agentic_vision_with_prompt(event, user_id, message_text)
                return

            # Extract URLs and mode for URL messages
            urls, mode = extract_url_and_mode(message_text)

            if urls:
                # Handle URL messages with mode
                await handle_url_message(event, urls, mode)
            else:
                # Use Orchestrator for all text messages (including commands)
                await handle_text_message_via_orchestrator(event, user_id)

        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)
        elif isinstance(event.message, AudioMessage):
            await handle_audio_message(event)
        elif isinstance(event.message, LocationMessage):
            await handle_location_message(event)


async def handle_url_message(event: MessageEvent, urls: list, mode: str = "normal"):
    """
    Handle URL messages via Orchestrator's ContentAgent

    Args:
        event: LINE message event
        urls: List of URLs to process
        mode: Summary mode - "short", "normal", or "detailed"
    """
    results = []

    # Add mode indicator if not normal
    if mode != "normal":
        mode_desc = get_mode_description(mode)
        mode_indicator = TextSendMessage(text=f"📝 {mode_desc}")
        results.append(mode_indicator)

    for url in urls:
        try:
            # Use Orchestrator's content_agent to process URL
            result = await orchestrator.content_agent.process_url(url, mode=mode)

            if result["status"] != "success":
                error_msg = result.get("error_message", "無法處理此網址")
                logger.error(f"ContentAgent failed for URL: {url} - {error_msg}")
                reply_msg = TextSendMessage(text=f"{url}\n\n⚠️ {error_msg}")
                results.append(reply_msg)
                continue

            # Format response
            formatted_result = format_content_response(result, include_url=True)
            content_type = result.get("content_type", "html")

            # Store summary for read-aloud (sweep-on-write cleanup)
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

            logger.info(f"URL processed: {url} (type: {content_type})")

            # Add Quick Reply for YouTube URLs
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
            else:
                reply_msg = TextSendMessage(
                    text=formatted_result,
                    quick_reply=QuickReply(items=[read_aloud_button])
                )

            results.append(reply_msg)

        except Exception as e:
            logger.error(f"Unexpected error processing URL: {e}", exc_info=True)
            error_msg = LineService.format_error_message(e, "處理網址")
            reply_msg = TextSendMessage(text=f"{url}\n\n{error_msg}")
            results.append(reply_msg)

    if results:
        await line_bot_api.reply_message(event.reply_token, results)


async def handle_text_message_via_orchestrator(event: MessageEvent, user_id: str, text: str = None, push_user_id: str = None):
    """
    Handle text messages using the Orchestrator for A2A routing.

    The Orchestrator automatically:
    - Detects intent (command, chat, github, etc.)
    - Routes to appropriate specialized agent
    - Handles response formatting
    """
    msg = text if text is not None else event.message.text.strip()

    try:
        logger.info(f"Processing via Orchestrator for user {user_id}: {msg[:50]}...")

        # Use Orchestrator to process text (handles commands, @g, and chat)
        result = await orchestrator.process_text(user_id=user_id, message=msg)

        # Format response using orchestrator formatter
        response_text = format_orchestrator_response(result)

        # Handle long responses
        if len(response_text) > 4500:
            logger.warning(f"Response too long ({len(response_text)} chars), truncating")
            response_text = response_text[:4400] + "\n\n... (訊息過長，已截斷)"

        # Check if restaurant search is successful and has location to add Quick Reply button
        quick_reply = None
        for resp in result.responses:
            if resp.get('intent') == 'restaurant_search' and resp.get('has_location') and resp.get('status') == 'success':
                quick_reply = QuickReply(
                    items=[
                        QuickReplyButton(
                            action=PostbackAction(
                                label="🔍 深度評論分析 (Batch)",
                                data=json.dumps({
                                    "action": "foodie_deep_analysis",
                                    "latitude": resp.get('latitude'),
                                    "longitude": resp.get('longitude')
                                }),
                                display_text="🔍 進行深度評論與招牌菜色分析"
                            )
                        )
                    ]
                )
                break

        reply_msg = TextSendMessage(text=response_text, quick_reply=quick_reply)
        if push_user_id:
            await line_bot_api.push_message(push_user_id, [reply_msg])
        else:
            await line_bot_api.reply_message(event.reply_token, [reply_msg])

        logger.info(f"Orchestrator successfully responded to user {user_id}")


    except Exception as e:
        logger.error(f"Error in Orchestrator: {e}", exc_info=True)
        error_text = LineService.format_error_message(e, "處理您的問題")
        reply_msg = TextSendMessage(text=error_text)
        if push_user_id:
            await line_bot_api.push_message(push_user_id, [reply_msg])
        else:
            await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_image_message(event: MessageEvent):
    """Handle image messages - store image and show quick reply options"""
    try:
        message_content = await line_bot_api.get_message_content(event.message.id)
        image_content = b''
        async for s in message_content.iter_content():
            image_content += s

        user_id = event.source.user_id if isinstance(event.source, SourceUser) else None
        if not user_id:
            return

        # Store image temporarily
        image_temp_store[user_id] = image_content
        logger.info(f"Stored image for user {user_id}: {len(image_content)} bytes")

        # Show quick reply options
        quick_reply_buttons = QuickReply(
            items=[
                QuickReplyButton(
                    action=PostbackAction(
                        label="識別圖片",
                        data=json.dumps({"action": "image_analyze", "mode": "recognize"}),
                        display_text="識別圖片"
                    )
                ),
                QuickReplyButton(
                    action=PostbackAction(
                        label="Agentic Vision",
                        data=json.dumps({"action": "image_analyze", "mode": "agentic_vision"}),
                        display_text="Agentic Vision"
                    )
                ),
            ]
        )

        reply_msg = TextSendMessage(
            text="📷 已收到圖片，請選擇分析方式：",
            quick_reply=quick_reply_buttons
        )
        await line_bot_api.reply_message(event.reply_token, [reply_msg])

    except Exception as e:
        logger.error(f"Image processing error: {e}", exc_info=True)
        error_msg = LineService.format_error_message(e, "處理圖片")
        reply_msg = TextSendMessage(text=error_msg)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])


def _extract_agentic_images(result) -> list:
    """Extract annotated image bytes from OrchestratorResult"""
    images = []
    if hasattr(result, 'responses'):
        for resp in result.responses:
            if isinstance(resp, dict) and 'images' in resp:
                images.extend(resp['images'])
    return images


def _create_image_send_message(image_bytes: bytes):
    """Store image and create ImageSendMessage with serving URL"""
    if not app_base_url:
        logger.warning("app_base_url not set, cannot serve annotated image")
        return None

    image_id = store_annotated_image(image_bytes)
    image_url = f"{app_base_url}/images/{image_id}"
    logger.info(f"Serving annotated image at: {image_url}")
    return ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url,
    )


async def handle_audio_message(event: MessageEvent):
    """Handle audio (voice) messages — transcribe and route through Orchestrator."""
    user_id = event.source.user_id
    replied = False
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

        # Reply #1: show transcription to user (consumes reply token)
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=f"你說的是：{transcription.strip()}")]
        )
        replied = True

        # Reply #2: run transcription through Orchestrator.
        # Must use push_user_id=user_id because the reply token was already consumed in Reply #1.
        await handle_text_message_via_orchestrator(event, user_id, text=transcription.strip(), push_user_id=user_id)

    except Exception as e:
        logger.error(f"Error handling audio message for user {user_id}: {e}", exc_info=True)
        error_text = LineService.format_error_message(e, "處理語音訊息")
        error_msg = TextSendMessage(text=error_text)
        if replied:
            # Reply token already consumed — use push_message to notify user
            await line_bot_api.push_message(user_id, [error_msg])
        else:
            await line_bot_api.reply_message(event.reply_token, [error_msg])


async def handle_agentic_vision_with_prompt(event: MessageEvent, user_id: str, prompt_text: str):
    """Handle agentic vision request after user provides text prompt"""
    try:
        # Clear pending state
        pending_agentic_vision.pop(user_id, None)
        image_data = image_temp_store.pop(user_id, None)

        if not image_data:
            error_msg = TextSendMessage(text="⚠️ 圖片已過期，請重新傳送圖片。")
            await line_bot_api.reply_message(event.reply_token, [error_msg])
            return

        # Send processing message
        processing_msg = TextSendMessage(text=f"⏳ 正在使用 Agentic Vision 分析中，請稍候...\n\n📝 指令：{prompt_text}")
        await line_bot_api.reply_message(event.reply_token, [processing_msg])

        # Process with agentic vision using user's prompt
        result = await orchestrator.process_image_agentic(image_data, prompt=prompt_text)
        response_text = format_orchestrator_response(result)

        if len(response_text) > 4500:
            response_text = response_text[:4400] + "\n\n... (訊息過長，已截斷)"

        messages = [TextSendMessage(text=response_text)]

        # Send annotated images if available
        agentic_images = _extract_agentic_images(result)
        for img_bytes in agentic_images:
            img_msg = _create_image_send_message(img_bytes)
            if img_msg:
                messages.append(img_msg)

        await line_bot_api.push_message(user_id, messages)

    except Exception as e:
        logger.error(f"Agentic vision with prompt error: {e}", exc_info=True)
        error_msg = TextSendMessage(
            text=LineService.format_error_message(e, "Agentic Vision 分析")
        )
        await line_bot_api.push_message(user_id, [error_msg])


async def handle_location_message(event: MessageEvent):
    """
    Handle location messages and provide Quick Reply options for nearby places

    Args:
        event: LINE message event containing location data
    """
    latitude = event.message.latitude
    longitude = event.message.longitude
    address = event.message.address

    logger.info(f"Received location: ({latitude}, {longitude}) - {address}")

    # Create Quick Reply buttons with PostbackAction
    # Pass location data in postback data
    quick_reply_buttons = QuickReply(
        items=[
            QuickReplyButton(
                action=PostbackAction(
                    label="⛽ 找加油站",
                    data=json.dumps({
                        "action": "search_nearby",
                        "place_type": "gas_station",
                        "latitude": latitude,
                        "longitude": longitude,
                        "address": address or ""
                    }),
                    display_text="⛽ 找加油站"
                )
            ),
            QuickReplyButton(
                action=PostbackAction(
                    label="🅿️ 找停車場",
                    data=json.dumps({
                        "action": "search_nearby",
                        "place_type": "parking",
                        "latitude": latitude,
                        "longitude": longitude,
                        "address": address or ""
                    }),
                    display_text="🅿️ 找停車場"
                )
            ),
            QuickReplyButton(
                action=PostbackAction(
                    label="🍴 找餐廳",
                    data=json.dumps({
                        "action": "search_nearby",
                        "place_type": "restaurant",
                        "latitude": latitude,
                        "longitude": longitude,
                        "address": address or ""
                    }),
                    display_text="🍴 找餐廳"
                )
            ),
        ]
    )

    # Save coordinates to user session metadata
    user_id = event.source.user_id if isinstance(event.source, SourceUser) else None
    if user_id:
        try:
            # Ensure session is created
            orchestrator.chat_agent.get_or_create_session(user_id)
            session = orchestrator.chat_agent.session_manager.get_session(user_id)
            if session:
                session.metadata["last_location"] = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "address": address or ""
                }
                logger.info(f"Saved location coordinates for user {user_id} in session metadata")
        except Exception as e:
            logger.error(f"Failed to save location in session: {e}")

    # Send reply with Quick Reply buttons
    reply_msg = TextSendMessage(
        text=f"📍 已收到你的位置\n\n{address or '位置已記錄'}\n\n請選擇要搜尋的類型：",
        quick_reply=quick_reply_buttons
    )

    await line_bot_api.reply_message(event.reply_token, [reply_msg])



async def handle_map_search_postback(event: PostbackEvent, data: dict, user_id: str):
    """
    Handle map search requests using LocationAgent

    Args:
        event: LINE postback event
        data: Parsed JSON data containing location and place_type
        user_id: LINE user ID
    """
    try:
        place_type = data.get('place_type')
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if not place_type or latitude is None or longitude is None:
            logger.error(f"Missing required data in postback: {data}")
            error_msg = TextSendMessage(text="❌ 位置資訊不完整，請重新傳送位置。")
            await line_bot_api.reply_message(event.reply_token, [error_msg])
            return

        logger.info(f"Searching for {place_type} at ({latitude}, {longitude})")

        # Send "searching" message
        searching_msg = TextSendMessage(text="🔍 搜尋中，請稍候...")
        await line_bot_api.reply_message(event.reply_token, [searching_msg])

        # Use Orchestrator's LocationAgent to search
        result = await orchestrator.location_agent.search(
            latitude=latitude,
            longitude=longitude,
            place_type=place_type
        )

        # Format and send result
        response_text = format_location_response(result)
        
        quick_reply = None
        if place_type == "restaurant" and result.get("status") == "success":
            quick_reply = QuickReply(
                items=[
                    QuickReplyButton(
                        action=PostbackAction(
                            label="🔍 深度評論分析 (Batch)",
                            data=json.dumps({
                                "action": "foodie_deep_analysis",
                                "latitude": latitude,
                                "longitude": longitude
                            }),
                            display_text="🔍 進行深度評論與招牌菜色分析"
                        )
                    )
                ]
            )
            
        result_msg = TextSendMessage(text=response_text, quick_reply=quick_reply)

        if user_id:
            await line_bot_api.push_message(user_id, [result_msg])

        else:
            logger.warning("No user_id available, cannot push result message")

    except Exception as e:
        logger.error(f"Map search error: {e}", exc_info=True)
        error_msg = TextSendMessage(
            text=LineService.format_error_message(e, "搜尋地點")
        )
        if user_id:
            await line_bot_api.push_message(user_id, [error_msg])


async def handle_foodie_deep_analysis_postback(event: PostbackEvent, data: dict, user_id: str):
    """
    Handle deep restaurant review analysis using Batch API and Webhooks
    """
    try:
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if latitude is None or longitude is None or not user_id:
            logger.error(f"Missing latitude/longitude/user_id for foodie deep analysis: {data}")
            error_msg = TextSendMessage(text="❌ 位置資訊不完整，請重新傳送位置。")
            await line_bot_api.reply_message(event.reply_token, [error_msg])
            return

        logger.info(f"Starting foodie deep analysis for user {user_id} at ({latitude}, {longitude})")

        # Reply to user immediately to prevent LINE bot timeout
        ack_msg = TextSendMessage(
            text="⏳ 正在為您搜集附近餐廳的 50+ 則最新評論，並建立 Gemini Batch API 批次大數據分析任務。\n\n本分析包含招牌菜推薦、整體口味與雷點摘要，預計需要 1~2 分鐘，分析完成後我會主動將專屬報告推播給您！"
        )
        await line_bot_api.reply_message(event.reply_token, [ack_msg])

        # Run the heavy work in background task to avoid blocking FastAPI workers
        asyncio.create_task(
            run_foodie_deep_analysis_background(user_id, latitude, longitude)
        )

    except Exception as e:
        logger.error(f"Foodie deep analysis trigger error: {e}", exc_info=True)
        if user_id:
            error_msg = TextSendMessage(text=f"❌ 啟動深度分析時發生錯誤：{str(e)[:100]}")
            await line_bot_api.push_message(user_id, [error_msg])


async def run_foodie_deep_analysis_background(user_id: str, latitude: float, longitude: float):
    try:
        from tools.maps_tool import get_nearby_restaurants_for_batch
        from services.batch_service import BatchService
        
        # 1. Fetch nearby restaurants with reviews
        logger.info(f"Background task: Fetching restaurants with reviews for {user_id}")
        search_res = get_nearby_restaurants_for_batch(latitude, longitude)
        if search_res.get("status") != "success":
            error_text = search_res.get("error_message", "搜尋餐廳失敗")
            await line_bot_api.push_message(user_id, [TextSendMessage(text=f"⚠️ {error_text}")])
            return
            
        restaurants = search_res.get("restaurants", [])
        if not restaurants:
            await line_bot_api.push_message(user_id, [TextSendMessage(text="⚠️ 附近似乎沒有找到合適的餐廳進行深度分析。")])
            return
            
        # 2. Submit Batch Job
        # Get WEBHOOK_DOMAIN from env or fallback to app_base_url domain
        webhook_domain = os.getenv("WEBHOOK_DOMAIN")
        if not webhook_domain and app_base_url:
            from urllib.parse import urlparse
            parsed_url = urlparse(app_base_url)
            webhook_domain = parsed_url.netloc
            logger.info(f"Using auto-detected webhook domain from app_base_url: {webhook_domain}")
        
        batch_service = BatchService()
        logger.info(f"Background task: Submitting Batch Job for user {user_id}")
        submit_res = await batch_service.submit_restaurant_batch_job(
            user_id=user_id,
            coordinates={"latitude": latitude, "longitude": longitude},
            restaurants=restaurants,
            webhook_domain=webhook_domain
        )
        
        if submit_res.get("status") != "success":
            error_text = submit_res.get("error_message", "建立批次分析工作失敗")
            await line_bot_api.push_message(user_id, [TextSendMessage(text=f"❌ {error_text}")])
            return
            
        # Job submitted successfully
        job_id = submit_res.get("batch_job_id")
        logger.info(f"Batch job {job_id} submitted successfully for user {user_id}")
        
    except Exception as e:
        logger.error(f"Background foodie analysis error: {e}", exc_info=True)
        await line_bot_api.push_message(user_id, [TextSendMessage(text=f"❌ 背景深度分析處理失敗：{str(e)[:100]}")])



async def handle_youtube_summary_postback(event: PostbackEvent, data: dict):
    """
    Handle YouTube summary requests using ContentAgent

    Args:
        event: LINE postback event
        data: Parsed JSON data containing YouTube URL and mode
    """
    try:
        mode = data.get('mode')
        url = data.get('url')
        user_id = event.source.user_id if isinstance(event.source, SourceUser) else None

        if not mode or not url:
            logger.error("Missing mode or url in YouTube summary postback")
            return

        logger.info(f"Generating YouTube summary: mode={mode}, url={url}")

        # Send "processing" message
        mode_text = "詳細摘要" if mode == "detail" else "Twitter 分享文案"
        processing_msg = TextSendMessage(text=f"⏳ 正在生成{mode_text}，請稍候...")
        await line_bot_api.reply_message(event.reply_token, [processing_msg])

        # Use Orchestrator's ContentAgent to summarize YouTube video
        result = await orchestrator.content_agent.summarize_youtube(url, mode=mode)

        if result["status"] != "success":
            error_msg = result.get("error_message", "無法生成影片摘要")
            logger.error(f"ContentAgent failed for YouTube URL: {url} - {error_msg}")
            result_msg = TextSendMessage(text=f"⚠️ {error_msg}")
        else:
            # Format result with URL
            formatted_result = f"{url}\n\n{result['summary']}"
            result_msg = TextSendMessage(text=formatted_result)

        # Send result using push message
        if user_id:
            await line_bot_api.push_message(user_id, [result_msg])
        else:
            logger.warning("No user_id available, cannot push result message")

    except Exception as e:
        logger.error(f"YouTube summary error: {e}", exc_info=True)
        error_msg = TextSendMessage(
            text=LineService.format_error_message(e, "生成影片摘要")
        )
        if user_id:
            await line_bot_api.push_message(user_id, [error_msg])


async def handle_image_analyze_postback(event: PostbackEvent, data: dict, user_id: str):
    """Handle image analysis postback from quick reply"""
    try:
        mode = data.get('mode')

        if not user_id or user_id not in image_temp_store:
            error_msg = TextSendMessage(text="⚠️ 圖片已過期，請重新傳送圖片。")
            await line_bot_api.reply_message(event.reply_token, [error_msg])
            return

        # Agentic Vision: ask user for text prompt first
        if mode == "agentic_vision":
            pending_agentic_vision[user_id] = True
            reply_msg = TextSendMessage(
                text="🔍 Agentic Vision 模式\n\n請輸入你想要分析的指令，例如：\n• 數一數圖片中有幾個人\n• 找出圖片中所有的文字\n• 分析圖表中的數據趨勢"
            )
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        # 識別圖片: process immediately
        image_data = image_temp_store.pop(user_id, None)

        processing_msg = TextSendMessage(text="⏳ 正在使用識別圖片分析中，請稍候...")
        await line_bot_api.reply_message(event.reply_token, [processing_msg])

        result = await orchestrator.process_image(image_data)
        response_text = format_orchestrator_response(result)

        if len(response_text) > 4500:
            response_text = response_text[:4400] + "\n\n... (訊息過長，已截斷)"

        result_msg = TextSendMessage(text=response_text)
        await line_bot_api.push_message(user_id, [result_msg])

    except Exception as e:
        logger.error(f"Image analyze postback error: {e}", exc_info=True)
        error_msg = TextSendMessage(
            text=LineService.format_error_message(e, "分析圖片")
        )
        if user_id:
            await line_bot_api.push_message(user_id, [error_msg])


async def handle_postback_event(event: PostbackEvent):
    """
    Handle postback events from Quick Reply buttons and other interactions
    Supports both query string format (legacy) and JSON format (new map search)
    """
    postback_data = event.postback.data
    user_id = event.source.user_id if isinstance(event.source, SourceUser) else None

    # Try to parse as JSON first (new format for map search)
    try:
        data = json.loads(postback_data)
        action_value = data.get('action')

        # Handle map search requests
        if action_value == "search_nearby":
            await handle_map_search_postback(event, data, user_id)
            return

        # Handle foodie deep analysis requests
        if action_value == "foodie_deep_analysis":
            await handle_foodie_deep_analysis_postback(event, data, user_id)
            return


        # Handle image analysis requests
        if action_value == "image_analyze":
            await handle_image_analyze_postback(event, data, user_id)
            return

        # Handle YouTube summary requests
        if action_value == "youtube_summary":
            await handle_youtube_summary_postback(event, data)
            return

        # Handle read aloud requests
        if action_value == "read_aloud":
            await handle_read_aloud_postback(event, data, user_id)
            return

    except json.JSONDecodeError:
        # Fall back to query string format (legacy format)
        query_params = parse_qs(postback_data)
        action_value = query_params.get('action', [None])[0]
        m_id = query_params.get('m_id', [None])[0]

        if m_id is None or m_id not in msg_memory_store:
            logger.error("Invalid message ID or message ID not found in store.")
            return

        # Remove gen_tweet and gen_slack actions
        if action_value not in ["gen_tweet", "gen_slack"]:
            logger.error("Invalid action value.")
            return


async def handle_read_aloud_postback(event: PostbackEvent, data: dict, user_id: str):
    """Handle 🔊 朗讀摘要 postback — generate TTS audio and send as AudioSendMessage."""
    summary_id = data.get("summary_id")

    if not summary_id:
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text="摘要已過期，請重新傳送網址。")]
        )
        return

    entry = summary_store.get(summary_id)

    if not entry or time.time() - entry["created_at"] > SUMMARY_TTL:
        await line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text="摘要已過期，請重新傳送網址。")]
        )
        return

    try:
        text = entry["text"][:MAX_TTS_CHARS]

        if not app_base_url:
            logger.error("app_base_url not set, cannot serve audio for user %s", user_id)
            await line_bot_api.reply_message(
                event.reply_token,
                [TextSendMessage(text="語音服務暫時無法使用，請稍後再試。")]
            )
            return

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
        await line_bot_api.push_message(user_id, [TextSendMessage(text=error_text)])


async def handle_url_push_message(title: str, urls: list, linebot_user_id: str, linebot_token: str):
    results = []
    for url in urls:
        try:
            result = await load_url(url)

            if not result:
                error_msg = "⚠️ 無法從這個網址提取內容。"
                logger.error(f"Empty result for URL: {url}")
                result_text = f"{url}\n{title}\n\n{error_msg}"
                results.append(TextSendMessage(result_text))
                continue

            try:
                result = summarize_text(result)
            except Exception as summarize_error:
                logger.error(f"Summarization failed: {summarize_error}")
                error_msg = FriendlyErrorMessage.get_message(summarize_error, url)
                result_text = f"{url}\n{title}\n\n{error_msg}"
                results.append(TextSendMessage(result_text))
                continue

            result = f"{url}\n{title}\n\n{result}"
            results.append(TextSendMessage(result))

        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            error_msg = FriendlyErrorMessage.get_message(e, url)
            result_text = f"{url}\n{title}\n\n{error_msg}"
            results.append(TextSendMessage(result_text))
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            error_msg = FriendlyErrorMessage.get_message(e, url)
            result_text = f"{url}\n{title}\n\n{error_msg}"
            results.append(TextSendMessage(result_text))

    if results and linebot_user_id and linebot_token:
        try:
            # Create async client for this specific token
            temp_async_client = AiohttpAsyncHttpClient(session)
            temp_line_bot_api = AsyncLineBotApi(linebot_token, temp_async_client)
            await temp_line_bot_api.push_message(linebot_user_id, results)
        except Exception as push_error:
            logger.error(f"Failed to push message: {push_error}")
            return "ERROR"

    return "OK"


def replace_domain(url, old_domain, new_domain):
    return url.replace(old_domain, new_domain)


# Webhook verification and handlers for Gemini Batch API and Webhooks

def verify_static_webhook(payload: str, headers: dict, secret: str) -> bool:
    webhook_id = headers.get("webhook-id") or headers.get("Webhook-Id")
    webhook_timestamp = headers.get("webhook-timestamp") or headers.get("Webhook-Timestamp")
    webhook_signature = headers.get("webhook-signature") or headers.get("Webhook-Signature")
    
    if not webhook_id or not webhook_timestamp or not webhook_signature:
        return False
        
    if "," not in webhook_signature:
        return False
    sig_version, sig_val = webhook_signature.split(",", 1)
    if sig_version != "v1":
        return False
        
    to_sign = f"{webhook_id}.{webhook_timestamp}.{payload}"
    computed_sig = hmac.new(
        secret.encode("utf-8"),
        to_sign.encode("utf-8"),
        hashlib.sha256
    ).digest()
    
    computed_sig_b64 = base64.b64encode(computed_sig).decode("utf-8")
    return hmac.compare_digest(sig_val, computed_sig_b64)


def verify_dynamic_webhook(token: str) -> Optional[dict]:
    try:
        unverified_headers = jwt.get_unverified_header(token)
        kid = unverified_headers.get("kid")
        if not kid:
            logger.error("No kid found in JWT header")
            return None
            
        JWKS_URI = "https://generativelanguage.googleapis.com/.well-known/jwks.json"
        response = requests.get(JWKS_URI)
        jwks = response.json()
        
        public_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break
                
        if not public_key:
            logger.error(f"JWK matching kid {kid} not found in JWKS")
            return None
            
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        return payload
    except Exception as e:
        logger.error(f"Dynamic Webhook JWT verification failed: {e}", exc_info=True)
        return None


@app.post("/api/gemini-callback/static")
async def gemini_static_webhook(request: Request):
    """
    Static Webhook Endpoint from Gemini.
    Verifies signature using HMAC SHA256 standard webhook signature.
    """
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")
    headers = request.headers
    
    webhook_secret = os.getenv("WEBHOOK_SIGNING_SECRET")
    if webhook_secret:
        verified = verify_static_webhook(body_str, headers, webhook_secret)
        if not verified:
            logger.error("Static Webhook signature verification failed.")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        logger.warning("WEBHOOK_SIGNING_SECRET is not configured. Signature validation skipped.")
            
    try:
        payload = json.loads(body_str)
        event_type = payload.get("type")
        event_data = payload.get("data", {})
        
        logger.info(f"Received static webhook event: {event_type}")
        
        if event_type == "batch.succeeded":
            batch_id = event_data.get("id") or event_data.get("name")
            output_file_uri = event_data.get("output_file_uri")
            if batch_id and output_file_uri:
                asyncio.create_task(
                    process_batch_completed_webhook(batch_id, output_file_uri)
                )
        elif event_type == "batch.failed":
            batch_id = event_data.get("id") or event_data.get("name")
            logger.error(f"Batch job failed: {batch_id}")
            asyncio.create_task(
                process_batch_failed_webhook(batch_id)
            )
            
    except Exception as e:
        logger.error(f"Error parsing static webhook body: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Bad Request")
        
    return {"status": "received"}


@app.post("/api/gemini-callback/dynamic")
async def gemini_dynamic_webhook(request: Request, webhook_signature: Optional[str] = Header(None)):
    """
    Dynamic Webhook Endpoint from Gemini LROs.
    Verifies signature using RS256 JWT from Google's JWKS.
    """
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")
    
    token = webhook_signature or request.headers.get("Webhook-Signature")
    if not token:
        logger.error("Missing Webhook-Signature header in dynamic webhook callback")
        raise HTTPException(status_code=400, detail="Missing signature header")
        
    jwt_payload = verify_dynamic_webhook(token)
    if not jwt_payload:
        logger.error("Dynamic Webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid JWT signature")
        
    try:
        event_type = jwt_payload.get("type")
        event_data = jwt_payload.get("data", {})
        
        logger.info(f"Received dynamic webhook event: {event_type}")
        
        if event_type == "batch.succeeded":
            batch_id = event_data.get("id") or event_data.get("name")
            output_file_uri = event_data.get("output_file_uri")
            
            user_metadata = event_data.get("user_metadata") or jwt_payload.get("user_metadata") or {}
            user_id = user_metadata.get("user_id")
            
            if batch_id and output_file_uri:
                asyncio.create_task(
                    process_batch_completed_webhook(batch_id, output_file_uri, user_id)
                )
        elif event_type == "batch.failed":
            batch_id = event_data.get("id") or event_data.get("name")
            logger.error(f"Dynamic Batch job failed: {batch_id}")
            asyncio.create_task(
                process_batch_failed_webhook(batch_id)
            )
            
    except Exception as e:
        logger.error(f"Error parsing dynamic webhook body: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Bad Request")
        
    return {"status": "received"}


async def process_batch_completed_webhook(batch_job_id: str, output_file_uri: str, user_id: Optional[str] = None):
    """
    Process completed batch job and push results to user
    """
    try:
        from services.batch_service import BatchService
        batch_service = BatchService()
        
        if not user_id:
            mapping = batch_service.get_job_mapping(batch_job_id)
            if mapping:
                user_id = mapping.get("user_id")
                
        if not user_id:
            try:
                job_info = batch_service.client.batches.get(name=batch_job_id)
                display_name = job_info.display_name or ""
                if display_name.startswith("FoodieAnalysis_"):
                    parts = display_name.split("_")
                    if len(parts) >= 2:
                        user_id = parts[1]
                        logger.info(f"Resolved user_id {user_id} from batch display_name: {display_name}")
            except Exception as ex:
                logger.error(f"Failed to fetch job info for fallback user resolution: {ex}")
                
        if not user_id:
            logger.error(f"Cannot process batch {batch_job_id}: no user_id associated")
            return
            
        results = batch_service.download_and_parse_batch_results(output_file_uri)
        if not results:
            error_msg = TextSendMessage(text="⚠️ 深度美食評論分析處理完成，但無法解析分析結果。")
            await line_bot_api.push_message(user_id, [error_msg])
            return
            
        logger.info(f"Successfully retrieved batch analysis for {len(results)} restaurants")
        
        intro_msg = TextSendMessage(text="🎉 **您的附近餐廳深度評論與菜色大數據分析已出爐！** 👇")
        
        messages = [intro_msg]
        for item in results:
            name = item["name"]
            analysis = item["analysis"]
            
            rest_text = f"🍴 **{name}**\n\n{analysis}"
            messages.append(TextSendMessage(text=rest_text))
            
        from services.line_service import LineService
        line_service = LineService(line_bot_api)
        await line_service.push_messages(user_id, messages)
        logger.info(f"Pushed deep analysis results to user {user_id}")
        
    except Exception as e:
        logger.error(f"Failed to process batch completed webhook: {e}", exc_info=True)
        if user_id:
            await line_bot_api.push_message(user_id, [TextSendMessage(text="❌ 處理批次分析結果時發生錯誤。")])


async def process_batch_failed_webhook(batch_job_id: str):
    """
    Process failed batch job
    """
    try:
        from services.batch_service import BatchService
        batch_service = BatchService()
        mapping = batch_service.get_job_mapping(batch_job_id)
        if mapping:
            user_id = mapping.get("user_id")
            if user_id:
                error_msg = TextSendMessage(text="❌ 很抱歉，您的美食深度評論分析任務執行失敗，請稍後重試。")
                await line_bot_api.push_message(user_id, [error_msg])
    except Exception as e:
        logger.error(f"Failed to process batch failed webhook: {e}", exc_info=True)


async def poll_batch_jobs_loop():
    """
    Periodically polls Gemini Batch API for completed jobs.
    Acts as a fallback if the webhooks are not delivered.
    """
    logger.info("Starting batch job status polling loop...")
    while True:
        try:
            # Sleep for 60 seconds between polls
            await asyncio.sleep(60)
            
            from services.batch_service import BatchService
            batch_service = BatchService()
            
            if not batch_service.api_key:
                continue
                
            jobs = list(batch_service.client.batches.list())
            if not jobs:
                continue
                
            for job in jobs:
                display_name = job.display_name or ""
                if not display_name.startswith("FoodieAnalysis_"):
                    continue
                    
                # Split by underscore: FoodieAnalysis_{user_id}_{timestamp}
                parts = display_name.split("_")
                if len(parts) < 3:
                    continue
                    
                user_id = parts[1]
                
                state_str = str(job.state)
                is_succeeded = "JOB_STATE_SUCCEEDED" in state_str or getattr(job.state, "name", None) == "JOB_STATE_SUCCEEDED"
                is_failed = "JOB_STATE_FAILED" in state_str or getattr(job.state, "name", None) == "JOB_STATE_FAILED"
                
                if is_succeeded:
                    dest_file = getattr(job.dest, "file_name", None)
                    if not dest_file:
                        dest_file = f"files/batch-{job.name.split('/')[-1]}"
                    
                    logger.info(f"Polling found succeeded batch job {job.name} for user {user_id}. Processing...")
                    await process_batch_completed_webhook(job.name, dest_file, user_id)
                    
                    batch_service.client.batches.delete(name=job.name)
                    logger.info(f"Deleted batch job {job.name} after successful processing.")
                    
                elif is_failed:
                    logger.error(f"Polling found failed batch job {job.name} for user {user_id}. Processing failure...")
                    await process_batch_failed_webhook(job.name)
                    
                    batch_service.client.batches.delete(name=job.name)
                    logger.info(f"Deleted failed batch job {job.name}.")
                    
        except Exception as e:
            logger.error(f"Error in poll_batch_jobs_loop: {e}", exc_info=True)


