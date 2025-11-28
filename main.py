import os
import sys
import json  # added import for JSON conversion
from io import BytesIO
from typing import Dict
from urllib.parse import parse_qs

import aiohttp
import PIL.Image
from fastapi import Request, FastAPI, HTTPException
from fastapi.responses import JSONResponse
import logging
from linebot import LineBotApi
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextSendMessage, PostbackEvent, TextMessage, ImageMessage, LocationMessage,
    QuickReply, QuickReplyButton, MessageAction
)
from linebot.models.sources import SourceGroup, SourceRoom, SourceUser
import google.generativeai as genai
from httpx import HTTPStatusError

# local files
from loader.gh_tools import summarized_yesterday_github_issues
from loader.langtools import summarize_text, generate_json_from_image
from loader.url import load_url, is_youtube_url
from loader.utils import find_url
from loader.searchtool import search_from_text  # Import the search function
from loader.error_handler import FriendlyErrorMessage
from loader.text_utils import extract_url_and_mode, get_mode_description
from loader.maps_grounding import search_nearby_places  # Import maps grounding
import database  # Import database module

# Configure logging
logging.basicConfig(
    stream=sys.stdout, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Get all environment variables at the top
channel_secret = os.getenv('ChannelSecret')
linebot_user_id = os.getenv("LINE_USER_ID")
channel_access_token = os.getenv('ChannelAccessToken')
channel_access_token_hf = os.getenv('ChannelAccessTokenHF')
gemini_key = os.getenv('GOOGLE_API_KEY')
firecrawl_key = os.getenv('firecrawl_key')
search_api_key = os.getenv('SEARCH_API_KEY')
search_engine_id = os.getenv('SEARCH_ENGINE_ID')

# Validate required environment variables
if not channel_secret:
    raise EnvironmentError('Specify ChannelSecret as environment variable.')
if not channel_access_token:
    raise EnvironmentError(
        'Specify ChannelAccessToken as environment variable.')
if not gemini_key:
    raise EnvironmentError('Specify GOOGLE_API_KEY as environment variable.')
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

if search_api_key and search_engine_id:
    logger.info('Search API keys detected - search functionality is available')
else:
    logger.warning(
        'Search API keys missing - search functionality will be limited')


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

# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on application startup"""
    await database.init_db()
    logger.info("Database initialized successfully")

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

            # Check for bookmark commands
            if message_text.startswith("/bookmarks") or message_text.startswith("/書籤"):
                await handle_bookmarks_command(event, user_id)
            elif message_text.startswith("/search") or message_text.startswith("/搜尋"):
                await handle_search_bookmarks_command(event, user_id, message_text)
            elif message_text == "@g":
                await handle_github_summary(event)
            elif message_text.startswith("🗺️"):
                # Handle map search requests from Quick Reply
                await handle_map_search_request(event, user_id, message_text)
            else:
                # Extract URLs and summary mode from message
                urls, mode = extract_url_and_mode(message_text)
                logger.info(f"URLs: >{urls}< Mode: {mode}")

                # Check if user wants to bookmark (🔖 emoji present)
                should_bookmark = "🔖" in message_text

                if urls:
                    await handle_url_message(event, urls, mode, should_bookmark=should_bookmark)
                else:
                    await handle_text_message(event, user_id)
        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)
        elif isinstance(event.message, LocationMessage):
            await handle_location_message(event)


async def handle_url_message(event: MessageEvent, urls: list, mode: str = "normal", should_bookmark: bool = False):
    """
    Handle URL messages with optional summary mode and bookmarking

    Args:
        event: LINE message event
        urls: List of URLs to process
        mode: Summary mode - "short", "normal", or "detailed"
        should_bookmark: Whether to save URLs as bookmarks
    """
    results = []
    user_id = event.source.user_id if isinstance(event.source, SourceUser) else None

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

            # Save to bookmarks if requested
            if should_bookmark and user_id:
                try:
                    # Extract title from first line of summary or use URL
                    title = summary.split('\n')[0][:100] if summary else url
                    await database.create_bookmark(
                        user_id=user_id,
                        url=url,
                        title=title,
                        summary=summary,
                        summary_mode=mode
                    )
                    result = f"🔖 已儲存書籤\n\n{url}\n\n{result}"
                except Exception as bookmark_error:
                    logger.error(f"Failed to save bookmark: {bookmark_error}")
                    result = f"{url}\n\n{result}"
            else:
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
    msg = event.message.text

    # Use text as search query for all text messages
    # Check if required API keys are available
    if not search_api_key or not search_engine_id:
        reply_msg = TextSendMessage(
            text="❌ 搜尋功能暫時無法使用（缺少 API 金鑰）。")
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    try:
        # Perform search
        logger.info(f"Performing search for query: {msg}")
        search_results = search_from_text(
            msg, gemini_key, search_api_key, search_engine_id)

        if not search_results:
            reply_msg = TextSendMessage(
                text=f"🔍 沒有找到「{msg}」的相關結果，請嘗試其他關鍵字。")
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        # Format search results
        # Add a header with the search query
        result_text = f"🔍 搜尋結果：{msg}\n\n"

        # Include top 5 results (or fewer if less are available)
        for i, result in enumerate(search_results[:5], 1):
            result_text += f"{i}. {result['title']}\n"
            result_text += f"   {result['link']}\n"
            result_text += f"   {result['snippet']}\n\n"

        try:
            summary = summarize_text(result_text, 300)
            summary_msg = TextSendMessage(text=summary)
            reply_msg = TextSendMessage(text=result_text)
            await line_bot_api.reply_message(event.reply_token, [summary_msg, reply_msg])
        except Exception as summarize_error:
            logger.error(f"Summarization failed, sending raw results: {summarize_error}")
            # If summarization fails, just send the raw results
            reply_msg = TextSendMessage(text=result_text)
            await line_bot_api.reply_message(event.reply_token, [reply_msg])

    except Exception as e:
        logger.error(f"Error in search: {e}")
        error_msg = FriendlyErrorMessage.get_message(e)
        reply_msg = TextSendMessage(text=error_msg)
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

    # Get user_id
    user_id = event.source.user_id if isinstance(event.source, SourceUser) else "unknown"

    # Store location in memory for later use
    msg_memory_store[user_id] = StoreMessage(
        text=json.dumps({
            "latitude": latitude,
            "longitude": longitude,
            "address": address
        }),
        url=f"location:{latitude},{longitude}"
    )

    logger.info(f"Received location from {user_id}: ({latitude}, {longitude}) - {address}")

    # Create Quick Reply buttons
    quick_reply_buttons = QuickReply(
        items=[
            QuickReplyButton(
                action=MessageAction(
                    label="⛽ 找加油站",
                    text="🗺️ 找加油站"
                )
            ),
            QuickReplyButton(
                action=MessageAction(
                    label="🅿️ 找停車場",
                    text="🗺️ 找停車場"
                )
            ),
            QuickReplyButton(
                action=MessageAction(
                    label="🍴 找餐廳",
                    text="🗺️ 找餐廳"
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


async def handle_map_search_request(event: MessageEvent, user_id: str, message_text: str):
    """
    Handle map search requests from Quick Reply buttons

    Args:
        event: LINE message event
        user_id: LINE user ID
        message_text: Message text containing the search type
    """
    # Check if we have stored location for this user
    if user_id not in msg_memory_store:
        reply_msg = TextSendMessage(
            text="❌ 找不到位置資訊\n\n請先傳送你的位置，然後再選擇搜尋類型。"
        )
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    # Get stored location
    try:
        location_data = json.loads(msg_memory_store[user_id].text)
        latitude = location_data["latitude"]
        longitude = location_data["longitude"]
        address = location_data.get("address", "")
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse stored location: {e}")
        reply_msg = TextSendMessage(
            text="❌ 位置資訊格式錯誤\n\n請重新傳送你的位置。"
        )
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    # Determine place type from message
    place_type_map = {
        "🗺️ 找加油站": "gas_station",
        "🗺️ 找停車場": "parking",
        "🗺️ 找餐廳": "restaurant"
    }

    place_type = place_type_map.get(message_text, "restaurant")
    logger.info(f"Searching for {place_type} at ({latitude}, {longitude})")

    # Send "searching" message
    searching_msg = TextSendMessage(text="🔍 搜尋中，請稍候...")
    await line_bot_api.reply_message(event.reply_token, [searching_msg])

    # Call Maps Grounding API
    try:
        result = await search_nearby_places(
            latitude=latitude,
            longitude=longitude,
            place_type=place_type,
            language_code="zh-TW"
        )

        # Send result
        result_msg = TextSendMessage(text=result)
        await line_bot_api.push_message(user_id, [result_msg])

    except Exception as e:
        logger.error(f"Map search error: {e}", exc_info=True)
        error_msg = TextSendMessage(
            text=f"❌ 搜尋時發生錯誤\n\n{FriendlyErrorMessage.get_message(e)}"
        )
        await line_bot_api.push_message(user_id, [error_msg])


async def handle_bookmarks_command(event: MessageEvent, user_id: str):
    """
    Handle /bookmarks command to list user's bookmarks

    Args:
        event: LINE message event
        user_id: LINE user ID
    """
    try:
        bookmarks = await database.get_user_bookmarks(user_id, limit=10)

        if not bookmarks:
            reply_msg = TextSendMessage(
                text="📚 你還沒有任何書籤\n\n使用方式：發送網址並加上 🔖 即可儲存書籤\n例如：https://example.com 🔖")
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        # Format bookmarks list
        result_text = f"📚 你的書籤（最近 {len(bookmarks)} 筆）\n\n"

        for i, bookmark in enumerate(bookmarks, 1):
            title = bookmark.title[:40] + "..." if bookmark.title and len(bookmark.title) > 40 else bookmark.title
            result_text += f"{i}. {title or bookmark.url}\n"
            result_text += f"   {bookmark.url}\n"
            if bookmark.created_at:
                result_text += f"   📅 {bookmark.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            result_text += "\n"

        result_text += "💡 使用 /search [關鍵字] 搜尋書籤"

        reply_msg = TextSendMessage(text=result_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])

    except Exception as e:
        logger.error(f"Error handling bookmarks command: {e}")
        error_msg = FriendlyErrorMessage.get_message(e)
        reply_msg = TextSendMessage(text=error_msg)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_search_bookmarks_command(event: MessageEvent, user_id: str, message_text: str):
    """
    Handle /search command to search bookmarks

    Args:
        event: LINE message event
        user_id: LINE user ID
        message_text: Full message text
    """
    try:
        # Extract search keyword
        if message_text.startswith("/search"):
            keyword = message_text.replace("/search", "", 1).strip()
        else:
            keyword = message_text.replace("/搜尋", "", 1).strip()

        if not keyword:
            reply_msg = TextSendMessage(
                text="🔍 請輸入搜尋關鍵字\n\n使用方式：/search [關鍵字]\n例如：/search Python")
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        bookmarks = await database.search_bookmarks(user_id, keyword, limit=10)

        if not bookmarks:
            reply_msg = TextSendMessage(
                text=f"🔍 找不到包含「{keyword}」的書籤")
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        # Format search results
        result_text = f"🔍 搜尋結果：「{keyword}」（{len(bookmarks)} 筆）\n\n"

        for i, bookmark in enumerate(bookmarks, 1):
            title = bookmark.title[:40] + "..." if bookmark.title and len(bookmark.title) > 40 else bookmark.title
            result_text += f"{i}. {title or bookmark.url}\n"
            result_text += f"   {bookmark.url}\n"
            if bookmark.created_at:
                result_text += f"   📅 {bookmark.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            result_text += "\n"

        reply_msg = TextSendMessage(text=result_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])

    except Exception as e:
        logger.error(f"Error handling search bookmarks command: {e}")
        error_msg = FriendlyErrorMessage.get_message(e)
        reply_msg = TextSendMessage(text=error_msg)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_postback_event(event: PostbackEvent):
    query_params = parse_qs(event.postback.data)
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
            line_bot_api = LineBotApi(linebot_token)
            line_bot_api.push_message(linebot_user_id, results)
        except Exception as push_error:
            logger.error(f"Failed to push message: {push_error}")
            return "ERROR"

    return "OK"


def replace_domain(url, old_domain, new_domain):
    return url.replace(old_domain, new_domain)


# =====================================
# Bookmark System API Endpoints
# =====================================

@app.post("/bookmarks/create")
async def create_bookmark_endpoint(request: Request):
    """
    Create a new bookmark

    Request body:
    {
        "user_id": "LINE_USER_ID",
        "url": "https://example.com",
        "title": "Page Title" (optional),
        "summary": "Summary text" (optional),
        "summary_mode": "normal" (optional),
        "tags": "tag1,tag2" (optional)
    }
    """
    try:
        data = await request.json()
        logger.info(f"/bookmarks/create data={data}")

        user_id = data.get("user_id")
        url = data.get("url")

        if not user_id or not url:
            raise HTTPException(status_code=400, detail="user_id and url are required")

        bookmark = await database.create_bookmark(
            user_id=user_id,
            url=url,
            title=data.get("title"),
            summary=data.get("summary"),
            summary_mode=data.get("summary_mode", "normal"),
            tags=data.get("tags")
        )

        return JSONResponse(content={
            "status": "success",
            "bookmark": bookmark.to_dict()
        })

    except Exception as e:
        logger.error(f"Error creating bookmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bookmarks/list/{user_id}")
async def list_bookmarks_endpoint(user_id: str, limit: int = 10, offset: int = 0):
    """
    Get user's bookmarks

    Query parameters:
    - limit: Maximum number of bookmarks to return (default: 10)
    - offset: Offset for pagination (default: 0)
    """
    try:
        bookmarks = await database.get_user_bookmarks(user_id, limit, offset)
        return JSONResponse(content={
            "status": "success",
            "bookmarks": [b.to_dict() for b in bookmarks],
            "count": len(bookmarks)
        })
    except Exception as e:
        logger.error(f"Error listing bookmarks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bookmarks/search/{user_id}")
async def search_bookmarks_endpoint(user_id: str, q: str, limit: int = 10):
    """
    Search bookmarks by keyword

    Query parameters:
    - q: Search keyword
    - limit: Maximum number of results (default: 10)
    """
    try:
        if not q:
            raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

        bookmarks = await database.search_bookmarks(user_id, q, limit)
        return JSONResponse(content={
            "status": "success",
            "keyword": q,
            "bookmarks": [b.to_dict() for b in bookmarks],
            "count": len(bookmarks)
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching bookmarks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/bookmarks/delete/{bookmark_id}")
async def delete_bookmark_endpoint(bookmark_id: int, request: Request):
    """
    Delete a bookmark

    Request body:
    {
        "user_id": "LINE_USER_ID"
    }
    """
    try:
        data = await request.json()
        user_id = data.get("user_id")

        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        success = await database.delete_bookmark(bookmark_id, user_id)

        if success:
            return JSONResponse(content={
                "status": "success",
                "message": "Bookmark deleted successfully"
            })
        else:
            raise HTTPException(status_code=404, detail="Bookmark not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting bookmark: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bookmarks/stats/{user_id}")
async def get_bookmark_stats_endpoint(user_id: str):
    """Get user's bookmark statistics"""
    try:
        stats = await database.get_bookmark_stats(user_id)
        return JSONResponse(content={
            "status": "success",
            "stats": stats
        })
    except Exception as e:
        logger.error(f"Error getting bookmark stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
