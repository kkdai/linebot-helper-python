import os
import sys
import json  # added import for JSON conversion
from io import BytesIO
from typing import Dict
from urllib.parse import parse_qs

import aiohttp
import PIL.Image
from fastapi import Request, FastAPI, HTTPException
import logging
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage,
    QuickReply, QuickReplyButton, PostbackAction
)
from linebot.models.sources import SourceGroup, SourceRoom, SourceUser
from httpx import HTTPStatusError

# local files
from loader.url import is_youtube_url
from loader.text_utils import extract_url_and_mode, get_mode_description

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
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)
msg_memory_store: Dict[str, StoreMessage] = {}
# Temporary image store for quick reply flow (keyed by user_id)
image_temp_store: Dict[str, bytes] = {}
# Pending agentic vision mode: user_id -> True means waiting for text prompt
pending_agentic_vision: Dict[str, bool] = {}

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
    signature = request.headers['X-Line-Signature']
    body = (await request.body()).decode()

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


@app.get("/")
def health_check():
    print("Health Check! Ok!")
    return "OK"


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
                    ]
                )
                reply_msg = TextSendMessage(text=formatted_result, quick_reply=quick_reply_buttons)
            else:
                reply_msg = TextSendMessage(text=formatted_result)

            results.append(reply_msg)

        except Exception as e:
            logger.error(f"Unexpected error processing URL: {e}", exc_info=True)
            error_msg = LineService.format_error_message(e, "處理網址")
            reply_msg = TextSendMessage(text=f"{url}\n\n{error_msg}")
            results.append(reply_msg)

    if results:
        await line_bot_api.reply_message(event.reply_token, results)


async def handle_text_message_via_orchestrator(event: MessageEvent, user_id: str):
    """
    Handle text messages using the Orchestrator for A2A routing.

    The Orchestrator automatically:
    - Detects intent (command, chat, github, etc.)
    - Routes to appropriate specialized agent
    - Handles response formatting
    """
    msg = event.message.text.strip()

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

        reply_msg = TextSendMessage(text=response_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])

        logger.info(f"Orchestrator successfully responded to user {user_id}")

    except Exception as e:
        logger.error(f"Error in Orchestrator: {e}", exc_info=True)
        error_text = LineService.format_error_message(e, "處理您的問題")
        reply_msg = TextSendMessage(text=error_text)
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

        result_msg = TextSendMessage(text=response_text)
        await line_bot_api.push_message(user_id, [result_msg])

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
        result_msg = TextSendMessage(text=response_text)

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

        # Handle image analysis requests
        if action_value == "image_analyze":
            await handle_image_analyze_postback(event, data, user_id)
            return

        # Handle YouTube summary requests
        if action_value == "youtube_summary":
            await handle_youtube_summary_postback(event, data)
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
