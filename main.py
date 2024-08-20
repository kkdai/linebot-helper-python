import logging
from typing import Dict, Any

from linebot.models import (
    MessageEvent, TextSendMessage, QuickReply, QuickReplyButton, PostbackAction, PostbackEvent
)
from linebot.exceptions import InvalidSignatureError
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot import AsyncLineBotApi, WebhookParser
from fastapi import Request, FastAPI, HTTPException
import google.generativeai as genai
import os
from io import BytesIO

import aiohttp
import PIL.Image

from langtools import summarize_with_sherpa, summarize_text, generate_twitter_post
from gh_tools import summarized_yesterday_github_issues
from urllib.parse import parse_qs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
channel_secret = os.getenv('ChannelSecret')
channel_access_token = os.getenv('ChannelAccessToken')
gemini_key = os.getenv('GOOGLE_API_KEY')

if not channel_secret:
    raise EnvironmentError('Specify ChannelSecret as environment variable.')
if not channel_access_token:
    raise EnvironmentError(
        'Specify ChannelAccessToken as environment variable.')
if not gemini_key:
    raise EnvironmentError('Specify GEMINI_API_KEY as environment variable.')


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

namecard_path = "namecard"
msg_memory_store: Dict[str, StoreMessage] = {}
# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


@app.on_event("shutdown")
async def shutdown_event():
    await session.close()


@app.post("/")
async def handle_callback(request: Request):
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


async def handle_message_event(event: MessageEvent):
    user_id = event.source.user_id

    if event.message.text.startswith("http"):
        await handle_url_message(event)
    elif event.message.text == "@g":
        await handle_github_summary(event)
    elif event.message.type == "image":
        await handle_image_message(event)
    else:
        await handle_text_message(event, user_id)


async def handle_url_message(event: MessageEvent):
    url = event.message.text
    result = summarize_with_sherpa(url)
    if len(result) > 2000:
        result = summarize_text(result)
    m_id = event.message.id
    msg_memory_store[m_id] = StoreMessage(result, url)
    reply_msg = TextSendMessage(text=result, quick_reply=QuickReply(
        items=[QuickReplyButton(action=PostbackAction(label="gen_tweet", data=f"action=gen_tweet&m_id={m_id}"))]))
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
    result = generate_json_from_image(img, imgage_prompt)
    logger.info("------------IMAGE---------------")
    logger.info(result.text)
    reply_msg = TextSendMessage(text=result.text)
    await line_bot_api.reply_message(event.reply_token, [reply_msg])


async def handle_postback_event(event: PostbackEvent):
    query_params = parse_qs(event.postback.data)
    action_value = query_params.get('action', [None])[0]
    if action_value == "gen_tweet":
        m_id = query_params.get('m_id', [None])[0]
        stored_message = msg_memory_store[m_id]
        source_string = f"message_content={stored_message.text}, url={stored_message.url}"
        result = generate_twitter_post(source_string)
        reply_msg = TextSendMessage(text=result)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])


def generate_gemini_text_complete(prompt: str) -> Any:
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    return response


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
