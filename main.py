from linebot.models import FlexSendMessage
from linebot.models import (
    MessageEvent, TextSendMessage
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot import (
    AsyncLineBotApi, WebhookParser
)
from fastapi import Request, FastAPI, HTTPException
import google.generativeai as genai
import os
import sys
from io import BytesIO
import json

import aiohttp
import PIL.Image
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)
gemini_key = os.getenv('GEMINI_API_KEY')

imgage_prompt = '''
這是一張名片，你是一個名片秘書。請將以下資訊整理成 json 給我。
如果看不出來的，幫我填寫 N/A
只好 json 就好:
name, title, address, email, phone, company.
其中 phone 的內容格式為 #886-0123-456-789,1234. 沒有分機就忽略 ,1234
'''

query_prompt = '''
這是所有的名片資料，請根據輸入文字來查詢相關的名片資料 {all_cards}，
例如: 名字, 職稱, 公司名稱。 查詢問句為： {msg}, 只要回覆我找到的 JSON Data 就好。
'''

# firebase URL
firebase_url = os.environ['FIREBASE_URL']
# 从环境变量中读取服务账户密钥 JSON 内容
# service_account_info = json.loads(os.environ['GOOGLE_CREDENTIALS'])
# 使用服务账户密钥 JSON 内容初始化 Firebase Admin SDK
# cred = credentials.Certificate(service_account_info)
cred = credentials.ApplicationDefault()

firebase_admin.initialize_app(
    cred, {'databaseURL': firebase_url})

print('Firebase Admin SDK initialized successfully.')

if channel_secret is None:
    print('Specify ChannelSecret as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify ChannelAccessToken as environment variable.')
    sys.exit(1)
if gemini_key is None:
    print('Specify GEMINI_API_KEY as environment variable.')
    sys.exit(1)

# Initialize the FastAPI app for LINEBot
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)

namecard_path = "namecard"

# Initialize the Gemini Pro API
genai.configure(api_key=gemini_key)


@ app.post("/")
async def handle_callback(request: Request):
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue

        user_id = event.source.user_id
        if event.message.type == "text":
            msg = event.message.text
            reply_msg = TextSendMessage(text=f'uid: {user_id}, msg: {msg}')
            await line_bot_api.reply_message(
                event.reply_token,
                [reply_msg],
            )
        elif event.message.type == "image":
            message_content = await line_bot_api.get_message_content(
                event.message.id)
            image_content = b''
            async for s in message_content.iter_content():
                image_content += s
            img = PIL.Image.open(BytesIO(image_content))
            result = generate_json_from_image(img, imgage_prompt)
            print("------------IMAGE---------------")
            print(result.text)
            reply_msg = TextSendMessage(text=result.text)
            await line_bot_api.reply_message(
                event.reply_token,
                [reply_msg])
            return 'OK'
        else:
            continue

    return 'OK'


def generate_gemini_text_complete(prompt):
    """
    Generate a text completion using the generative model.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    return response


def generate_json_from_image(img, prompt):
    model = genai.GenerativeModel(
        'gemini-1.5-flash', generation_config={"response_mime_type": "application/json"})
    response = model.generate_content([prompt, img], stream=True)
    response.resolve()

    try:
        if response.parts:
            print(f">>>>{response.text}")
            return response
        else:
            print("No valid parts found in the response.")
            for candidate in response.candidates:
                print("!!!!Safety Ratings:", candidate.safety_ratings)
    except ValueError as e:
        print("Error:", e)
    return response
