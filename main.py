import os
import sys
from io import BytesIO
from typing import Dict, Any
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
    MessageEvent, TextSendMessage, QuickReply, QuickReplyButton, PostbackAction, PostbackEvent, TextMessage, ImageMessage
)
from linebot.models.sources import SourceGroup, SourceRoom, SourceUser
import google.generativeai as genai
from httpx import HTTPStatusError

# local files
from loader.gh_tools import summarized_yesterday_github_issues
from loader.langtools import summarize_text, generate_twitter_post, generate_slack_post
from loader.url import load_url
from loader.utils import find_url

# Configure logging
logging.basicConfig(
    stream=sys.stdout, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
channel_secret = os.getenv('ChannelSecret')
linebot_user_id = os.getenv("LINE_USER_ID")
channel_access_token = os.getenv('ChannelAccessToken')
channel_access_token_hf = os.getenv('ChannelAccessTokenHF')
gemini_key = os.getenv('GOOGLE_API_KEY')

if not channel_secret:
    raise EnvironmentError('Specify ChannelSecret as environment variable.')
if not channel_access_token:
    raise EnvironmentError(
        'Specify ChannelAccessToken as environment variable.')
if not gemini_key:
    raise EnvironmentError('Specify GEMINI_API_KEY as environment variable.')

# Push Notification
if not linebot_user_id:
    raise EnvironmentError('Specify LINE_USER_ID as environment variable.')
if not channel_access_token_hf:
    raise EnvironmentError(
        'Specify HuggingFace ChannelAccessToken as environment variable.')


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
Describe all the information from the image in JSON format.
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
    logger.info(f"title={title}, url={url}")
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Invalid URL protocol")
    return await handle_url_push_message(title, url, linebot_user_id, channel_access_token)


@app.post("/hf")
async def huggingface_paper_summarization(request: Request):
    data = await request.json()
    logger.info(f"/hf data={data}")

    title = data.get("title")
    papertocode_url = data.get("url")
    logger.info(f"title={title}, url={papertocode_url}")

    url = replace_domain(
        papertocode_url, "paperswithcode.com", "huggingface.co")
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Invalid URL protocol")
    return await handle_url_push_message(title, url, linebot_user_id, channel_access_token_hf)


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
                await handle_url_message(event, urls[0])
            elif event.message.text == "@g":
                await handle_github_summary(event)
            else:
                await handle_text_message(event, user_id)
        elif isinstance(event.message, ImageMessage):
            await handle_image_message(event)


async def handle_url_message(event: MessageEvent, url: str):
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
    result = summarize_text(result)

    m_id = event.message.id
    msg_memory_store[m_id] = StoreMessage(result, url)
    out_text = f"{url}  \n{result}"
    reply_msg = TextSendMessage(text=out_text, quick_reply=QuickReply(
        items=[QuickReplyButton(action=PostbackAction(label="gen_tweet", data=f"action=gen_tweet&m_id={m_id}")),
               QuickReplyButton(action=PostbackAction(label="gen_slack", data=f"action=gen_slack&m_id={m_id}"))]))
    await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_github_summary(event: MessageEvent):
    result = summarized_yesterday_github_issues()
    reply_msg = TextSendMessage(text=result)
    await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_text_message(event: MessageEvent, user_id: str):
    msg = event.message.text
    reply_msg = TextSendMessage(text=f'uid: {user_id}, msg: {msg}')
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

    stored_msg = msg_memory_store[m_id]
    source_string = f"message_content={stored_msg.text}, url={stored_msg.url}"

    if action_value == "gen_tweet":
        await generate_and_reply(event, source_string, generate_twitter_post)
    elif action_value == "gen_slack":
        await generate_and_reply(event, source_string, generate_slack_post)


async def generate_and_reply(event: PostbackEvent, source_string: str, generate_func):
    result = generate_func(source_string)
    # replace [link] with url in source_string
    m_id = parse_qs(event.postback.data).get('m_id', [None])[0]
    if m_id and m_id in msg_memory_store:
        result = result.replace("[link]", msg_memory_store[m_id].url)
    reply_msg = TextSendMessage(text=result)
    await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_url_push_message(title: str, url: str, linebot_user_id: str, linebot_token: str):
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
    send_msg(linebot_user_id, linebot_token, result)


def replace_domain(url, old_domain, new_domain):
    return url.replace(old_domain, new_domain)


def send_msg(linebot_user_id, linebot_token, text):
    if linebot_user_id and linebot_token:
        line_bot_api = LineBotApi(linebot_token)
        line_bot_api.push_message(linebot_user_id, TextSendMessage(text=text))
    return "OK"


def generate_json_from_image(img: PIL.Image.Image, prompt: str) -> Any:
    model = genai.GenerativeModel(
        'gemini-1.5-flash', generation_config={"response_mime_type": "application/json"})
    response = model.generate_content([prompt, img], stream=True)
    response.resolve()

    try:
        if response.parts:
            logger.info(f">>>>{response.text}")
            return response
        else:
            logger.warning("No valid parts found in the response.")
            for candidate in response.candidates:
                logger.warning("!!!!Safety Ratings:", candidate.safety_ratings)
    except ValueError as e:
        logger.error("Error:", e)
    return response
