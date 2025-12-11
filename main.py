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
from loader.gh_tools import summarized_yesterday_github_issues
from loader.langtools import summarize_text, generate_json_from_image
from loader.url import load_url, is_youtube_url
from loader.error_handler import FriendlyErrorMessage
from loader.text_utils import extract_url_and_mode, get_mode_description
from loader.maps_grounding import search_nearby_places  # Import maps grounding
from loader.chat_session import (  # Import chat session with Grounding
    ChatSessionManager,
    search_and_answer_with_grounding,
    format_grounding_response,
    get_session_status_message
)

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

# Initialize Chat Session Manager for Grounding
chat_session_manager = ChatSessionManager(session_timeout_minutes=30)
logger.info('Chat Session Manager initialized with 30min timeout')


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
        # separate handle TextMessage and ImageMessage
        if isinstance(event.message, TextMessage):
            user_id = event.source.user_id
            logger.info(f"UID: {user_id}")
            message_text = event.message.text

            # Check for special commands
            if message_text == "@g":
                await handle_github_summary(event)
            else:
                # Extract URLs and summary mode from message
                urls, mode = extract_url_and_mode(message_text)
                logger.info(f"URLs: >{urls}< Mode: {mode}")

                if urls:
                    await handle_url_message(event, urls, mode)
                else:
                    await handle_text_message(event, user_id)
        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)
        elif isinstance(event.message, LocationMessage):
            await handle_location_message(event)


async def handle_url_message(event: MessageEvent, urls: list, mode: str = "normal"):
    """
    Handle URL messages with optional summary mode

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
            result = await load_url(url)

            if not result:
                error_msg = "⚠️ 無法從這個網址提取內容，請確認網址是否正確或稍後再試。"
                logger.error(f"Empty result for URL: {url}")
                reply_msg = TextSendMessage(text=f"{url}\n\n{error_msg}")
                results.append(reply_msg)
                continue

            logger.info(f"URL: content: >{result[:50]}<")
            summary = None
            if not is_youtube_url(url):
                try:
                    summary = summarize_text(result, mode=mode)
                    result = summary
                except Exception as summarize_error:
                    logger.error(f"Summarization failed: {summarize_error}")
                    error_msg = FriendlyErrorMessage.get_message(summarize_error, url)
                    reply_msg = TextSendMessage(text=error_msg)
                    results.append(reply_msg)
                    continue
            else:
                summary = result

            # Format result with URL
            result = f"{url}\n\n{result}"
            reply_msg = TextSendMessage(text=result)
            results.append(reply_msg)

        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            error_msg = FriendlyErrorMessage.get_message(e, url)
            reply_msg = TextSendMessage(text=error_msg)
            results.append(reply_msg)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            error_msg = FriendlyErrorMessage.get_message(e, url)
            reply_msg = TextSendMessage(text=error_msg)
            results.append(reply_msg)

    if results:
        await line_bot_api.reply_message(event.reply_token, results)


async def handle_github_summary(event: MessageEvent):
    result = summarized_yesterday_github_issues()
    reply_msg = TextSendMessage(text=result)
    await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_text_message(event: MessageEvent, user_id: str):
    """
    處理純文字訊息 - 使用 Vertex AI Grounding with Google Search

    支援對話記憶和自動網路搜尋
    """
    msg = event.message.text.strip()

    # 處理特殊指令
    if msg.lower() in ['/clear', '/清除', '/reset', '/重置']:
        # 清除對話記憶
        success = chat_session_manager.clear_session(user_id)
        if success:
            reply_text = "✅ 對話已重置\n\n你可以開始新的對話了！"
        else:
            reply_text = "📊 目前沒有進行中的對話。\n\n發送任何訊息開始新對話！"
        reply_msg = TextSendMessage(text=reply_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    if msg.lower() in ['/status', '/狀態', '/info']:
        # 顯示對話狀態
        status_text = get_session_status_message(chat_session_manager, user_id)
        reply_msg = TextSendMessage(text=status_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    if msg.lower() in ['/help', '/幫助', '/說明']:
        # 顯示說明訊息
        help_text = """🤖 智能搜尋助手

💬 **對話功能**
發送任何問題，我會自動搜尋網路並提供詳細回答。
支援連續對話，我會記住我們的對話內容！

⚡ **特殊指令**
/clear - 清除對話記憶，開始新對話
/status - 查看目前對話狀態
/help - 顯示此說明

📚 **其他功能**
• 發送網址 - 摘要網頁內容
• 發送圖片 - AI 圖片分析
• @g - GitHub issues 摘要

提示：對話會在 30 分鐘無互動後自動過期。"""
        reply_msg = TextSendMessage(text=help_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    # 使用 Vertex AI Grounding 進行搜尋和回答
    try:
        logger.info(f"Processing text message with Grounding for user {user_id}: {msg[:50]}...")

        # 使用 Grounding 搜尋並回答
        result = await search_and_answer_with_grounding(
            query=msg,
            user_id=user_id,
            session_manager=chat_session_manager
        )

        # 格式化回應
        response_text = format_grounding_response(result, include_sources=True)

        # 檢查回應長度（LINE 訊息最多 5000 字元）
        if len(response_text) > 4500:
            # 分割成多則訊息
            logger.warning(f"Response too long ({len(response_text)} chars), splitting")
            # 先發送答案（不含來源）
            answer_only = format_grounding_response(
                {'answer': result['answer'], 'sources': [], 'has_history': result['has_history']},
                include_sources=False
            )
            msg1 = TextSendMessage(text=answer_only[:4500])

            # 再發送來源
            if result['sources']:
                sources_text = "📚 參考來源：\n"
                for i, source in enumerate(result['sources'][:3], 1):
                    sources_text += f"{i}. {source['title']}\n   {source['uri']}\n"
                msg2 = TextSendMessage(text=sources_text)
                await line_bot_api.reply_message(event.reply_token, [msg1, msg2])
            else:
                await line_bot_api.reply_message(event.reply_token, [msg1])
        else:
            # 正常長度，直接發送
            reply_msg = TextSendMessage(text=response_text)
            await line_bot_api.reply_message(event.reply_token, [reply_msg])

        logger.info(f"Successfully responded to user {user_id}")

    except Exception as e:
        logger.error(f"Error in Grounding search: {e}", exc_info=True)

        # 提供友善的錯誤訊息
        error_text = f"❌ 抱歉，處理您的問題時發生錯誤。\n\n"

        # 根據錯誤類型提供不同建議
        if "quota" in str(e).lower():
            error_text += "可能原因：API 配額已用完\n建議：請稍後再試"
        elif "not found" in str(e).lower() or "404" in str(e):
            error_text += "可能原因：找不到相關資訊\n建議：嘗試用不同的問法"
        elif "timeout" in str(e).lower():
            error_text += "可能原因：網路連線逾時\n建議：請稍後再試"
        else:
            error_text += "請稍後再試，或使用 /clear 清除對話記憶後重新開始。"

        reply_msg = TextSendMessage(text=error_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_image_message(event: MessageEvent):
    message_content = await line_bot_api.get_message_content(event.message.id)
    image_content = b''
    async for s in message_content.iter_content():
        image_content += s
    img = PIL.Image.open(BytesIO(image_content))
    result = generate_json_from_image(img, image_prompt)
    logger.info("------------IMAGE---------------")
    logger.info(result.text)
    reply_msg = TextSendMessage(text=result.text)
    await line_bot_api.reply_message(event.reply_token, [reply_msg])


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
    Handle map search requests from PostbackEvent (Quick Reply buttons)

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

        # Call Maps Grounding API
        result = await search_nearby_places(
            latitude=latitude,
            longitude=longitude,
            place_type=place_type,
            language_code="zh-TW"
        )

        # Send result
        result_msg = TextSendMessage(text=result)
        if user_id:
            await line_bot_api.push_message(user_id, [result_msg])
        else:
            logger.warning("No user_id available, cannot push result message")

    except Exception as e:
        logger.error(f"Map search error: {e}", exc_info=True)
        error_msg = TextSendMessage(
            text=f"❌ 搜尋時發生錯誤\n\n{FriendlyErrorMessage.get_message(e)}"
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
