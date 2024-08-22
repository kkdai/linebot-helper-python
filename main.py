from loguru import logger
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

from langtools import summarize_with_sherpa, summarize_text, generate_twitter_post, generate_slack_post
from gh_tools import summarized_yesterday_github_issues
from urllib.parse import parse_qs
import sys
import re

# Configure logging
logger.add(
    sys.stdout, format="{time} - {name} - {level} - {message}", level="INFO")


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

imgage_prompt = '''
Describe all the information from the image in JSON format.
'''


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

    url = find_url(event.message.text)
    logger.info(f"URL: {url}")
    if find_url(event.message.text) != '':
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
    result = generate_json_from_image(img, imgage_prompt)
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

    stored_message = msg_memory_store[m_id]
    source_string = f"message_content={stored_message.text}, url={stored_message.url}"

    if action_value == "gen_tweet":
        await generate_and_reply(event, source_string, generate_twitter_post)
    elif action_value == "gen_slack":
        await generate_and_reply(event, source_string, generate_slack_post)


async def generate_and_reply(event: PostbackEvent, source_string: str, generate_func):
    result = generate_func(source_string)
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


def find_url(input_string):
    # Regular expression pattern to match URLs
    url_pattern = r'https?://[^\s]+'

    # Search for the pattern in the input string
    match = re.search(url_pattern, input_string)

    # If a match is found, return the URL, otherwise return an empty string
    if match:
        return match.group(0)
    else:
        return ''
