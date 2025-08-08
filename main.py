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
from linebot import LineBotApi
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextSendMessage, PostbackEvent, TextMessage, ImageMessage
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
            urls = find_url(event.message.text)
            logger.info(f"URLs: >{urls}<")
            if urls:
                await handle_url_message(event, urls)
            elif event.message.text == "@g":
                await handle_github_summary(event)
            else:
                await handle_text_message(event, user_id)
        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)


async def handle_url_message(event: MessageEvent, urls: list):
    results = []
    for url in urls:
        try:
            result = await load_url(url)
        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            result = "An error occurred while summarizing the document."

        if not result:
            result = "An error occurred while summarizing the document."
            logger.error(result)
            reply_msg = TextSendMessage(text=result)
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        logger.info(f"URL: content: >{result[:50]}<")
        if not is_youtube_url(url):
            result = summarize_text(result)
        result = f"{url}\n{result}"
        reply_msg = TextSendMessage(text=result)
        results.append(reply_msg)
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
            text="Search is not available. Missing API keys.")
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    try:
        # Perform search
        logger.info(f"Performing search for query: {msg}")
        search_results = search_from_text(
            msg, gemini_key, search_api_key, search_engine_id)

        if not search_results:
            reply_msg = TextSendMessage(
                text=f"No search results found for: {msg}")
            await line_bot_api.reply_message(event.reply_token, [reply_msg])
            return

        # Format search results
        # Add a header with the search query
        result_text = f"🔍 Search results for: {msg}\n\n"

        # Include top 3 results (or fewer if less are available)
        for i, result in enumerate(search_results[:5], 1):
            result_text += f"{i}. {result['title']}\n"
            result_text += f"   {result['link']}\n"
            result_text += f"   {result['snippet']}\n\n"

        summary = summarize_text(result_text, 300)
        summary_msg = TextSendMessage(text=summary)
        reply_msg = TextSendMessage(text=result_text)
        await line_bot_api.reply_message(event.reply_token, [summary_msg, reply_msg])

    except Exception as e:
        logger.error(f"Error in search: {e}")
        reply_msg = TextSendMessage(
            text=f"An error occurred during search: {str(e)}")
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
        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            result = "An error occurred while fetching HTML data."

        if not result:
            result = "An error occurred while fetching HTML data."
            logger.error(result)
            return
        result = summarize_text(result)
        result = f"{url}\n{title} \n\n{result}"
        result = TextSendMessage(result)
        results.append(result)

    if linebot_user_id and linebot_token:
        line_bot_api = LineBotApi(linebot_token)
        line_bot_api.push_message(linebot_user_id, results)
    return "OK"


def replace_domain(url, old_domain, new_domain):
    return url.replace(old_domain, new_domain)
