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
            if event.message.text == "test":
                test_namecard = generate_sample_namecard()
                reply_card_msg = get_namecard_flex_msg(test_namecard)
                await line_bot_api.reply_message(
                    event.reply_token,
                    [reply_card_msg]
                )
                return 'OK'
            elif event.message.text == "list":
                all_cards = get_all_cards(user_id)
                total_cards = len(all_cards)
                await line_bot_api.reply_message(
                    event.reply_token,
                    [TextSendMessage(
                        text=f"總共有  {total_cards} 張名片資料。")]

                )
                return 'OK'
            elif event.message.text == "remove":
                remove_redundant_data(user_id)
                await line_bot_api.reply_message(
                    event.reply_token,
                    [TextSendMessage(
                        text="Redundant data removal complete.")]
                )
                return 'OK'
            else:
                print(f"User ID: {user_id}")

                # 讀取 'users' 集合中的所有文件
                all_cards = get_all_cards(user_id)
                # Provide a default value for reply_msg
                reply_msg = TextSendMessage(text='No message to reply with')

                msg = event.message.text
                # fmt: off
                prompt_msg = query_prompt.format(
                    all_cards=all_cards,
                    msg=msg
                )

                # fmt: on
                messages = []
                messages.append(
                    {"role": "user", "parts": prompt_msg})
                response = generate_gemini_text_complete(messages)
                card_obj = load_json_string_to_object(response.text)
                reply_card_msg = get_namecard_flex_msg(card_obj)
                await line_bot_api.reply_message(
                    event.reply_token,
                    [reply_card_msg],
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
            card_obj = parse_gemini_result_to_json(result.text)
            # check card_obj is json obj
            if card_obj is None:
                await line_bot_api.reply_message(
                    event.reply_token,
                    [TextSendMessage(
                        text=f"無法解析這張名片，請再試一次。 錯誤資訊: {result.text}")]
                )
                return 'OK'

            print(card_obj)
            card_obj = {k.lower(): v for k, v in card_obj.items()}
            print(card_obj)

            # Check if receipt exists, skip if it does
            exist = check_if_card_exists(card_obj, user_id)
            if exist:
                reply_msg = get_namecard_flex_msg(card_obj)
                await line_bot_api.reply_message(
                    event.reply_token,
                    [TextSendMessage(
                        text="這個名片已經存在資料庫中。"), reply_msg]
                )
                return 'OK'

            add_namecard(card_obj, user_id)
            reply_msg = get_namecard_flex_msg(card_obj)
            chinese_reply_msg = TextSendMessage(
                text="名片資料已經成功加入資料庫。")

            await line_bot_api.reply_message(
                event.reply_token,
                [reply_msg, chinese_reply_msg])
            return 'OK'
        else:
            continue

    return 'OK'


def get_all_cards(u_id):
    try:
        # 引用 "namecard" 路径
        ref = db.reference(f'{namecard_path}/{u_id}')

        # 获取数据
        namecard_data = ref.get()
        if namecard_data:
            for key, value in namecard_data.items():
                print(f'{key}: {value}')
            return namecard_data
    except Exception as e:
        print(f"Error fetching namecards: {e}")


def load_json_string_to_object(json_str):
    """
    Load a JSON string into a Python object.
    """
    try:
        json_str = json_str.replace("'", '"')
        json_obj = json.loads(json_str)
        json_obj = {k.lower(): v for k, v in json_obj.items()}
        return json_obj
    except json.JSONDecodeError as e:
        print(f"Error loading JSON string: {e}")
        return None


def generate_sample_namecard():
    return {
        "name": "Kevin Dai",
        "title": "Software Engineer",
        "address": "Taipei, Taiwan",
        "email": "aa@bbb.cc",
        "phone": "+886-123-456-789",
        "company": "LINE Taiwan"
    }


def generate_gemini_text_complete(prompt):
    """
    Generate a text completion using the generative model.
    """
    model = genai.GenerativeModel('gemini-pro')
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


def add_namecard(namecard_obj, u_id):
    """
    将名片数据添加到 Firebase Realtime Database 的 "namecard" 路径下。

    :param namecard_obj: 包含名片信息的字典对象
    """
    try:
        # 引用 "namecard" 路径
        ref = db.reference(f'{namecard_path}/{u_id}')

        # 推送新的名片数据
        new_ref = ref.push(namecard_obj)

        print(f'Namecard added with key: {new_ref.key}')
    except Exception as e:
        print(f'Error adding namecard: {e}')


def remove_redundant_data(u_id):
    """
    删除 "namecard" 路径下具有相同电子邮件地址的冗余数据。
    """
    try:
        # 引用 "namecard" 路径
        ref = db.reference(f'{namecard_path}/{u_id}')

        # 获取所有名片数据
        namecard_data = ref.get()

        if namecard_data:
            email_map = {}
            for key, value in namecard_data.items():
                email = value.get('email')
                if email:
                    if email in email_map:
                        # 如果电子邮件已经存在于 email_map 中，则删除该名片数据
                        ref.child(key).delete()
                        print(f'Deleted redundant namecard with key: {key}')
                    else:
                        # 如果电子邮件不存在于 email_map 中，则添加到 email_map
                        email_map[email] = key
        else:
            print('No data found in "namecard"')
    except Exception as e:
        print(f'Error removing redundant data: {e}')


def parse_gemini_result_to_json(card_json_str):
    '''
    Parse the Gemini Image JSON string from the receipt data.
    '''
    try:
        receipt_data = json.loads(card_json_str)
        return receipt_data
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None


def check_if_card_exists(namecard_obj, u_id):
    """
    检查名片数据是否已经存在于 "namecard" 路径下。

    :param namecard_obj: 包含名片信息的字典对象
    :return: 如果名片存在返回 True, 否则返回 False
    """
    try:
        # 获取名片对象中的电子邮件地址
        email = namecard_obj.get('email')
        if not email:
            print('No email provided in the namecard object.')
            return False

        # 引用 "namecard" 路径
        ref = db.reference(f'{namecard_path}/{u_id}')

        # 获取所有名片数据
        namecard_data = ref.get()

        if namecard_data:
            for key, value in namecard_data.items():
                if value.get('email') == email:
                    print(
                        f'Namecard with email {email} already exists: {key}')
                    return True
        print(f'Namecard with email {email} does not exist.')
        return False
    except Exception as e:
        print(f'Error checking if namecard exists: {e}')
        return False


def get_namecard_flex_msg(card_data):
    # Using Template

    flex_msg = {
        "type": "bubble",
        "size": "giga",
        "body": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "md",
            "contents": [
                {
                    "type": "image",
                    "aspectMode": "cover",
                    "aspectRatio": "1:1",
                    "flex": 1,
                    "size": "full",
                    "url": "https://raw.githubusercontent.com/kkdai/linebot-smart-namecard/main/img/logo.jpeg"
                },
                {
                    "type": "box",
                    "flex": 4,
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "align": "end",
                            "size": "xxl",
                            "text": f"{card_data.get('name')}",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "align": "end",
                            "size": "sm",
                            "text": f"{card_data.get('title')}",
                        },
                        {
                            "type": "text",
                            "align": "end",
                            "margin": "xxl",
                            "size": "lg",
                            "text":  f"{card_data.get('company')}",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "align": "end",
                            "size": "sm",
                            "text": f"{card_data.get('address')}",
                        },
                        {
                            "type": "text",
                            "align": "end",
                            "margin": "xxl",
                            "text": f"{card_data.get('phone')}",
                        },
                        {
                            "type": "text",
                            "align": "end",
                            "text": f"{card_data.get('email')}",
                        },
                        {
                            "type": "text",
                            "align": "end",
                            "text": "更多資訊",
                            "action": {
                                "type": "uri",
                                "uri": "https://github.com/kkdai/linebot-namecard-python"
                            }
                        }
                    ]
                }
            ]
        },
        "styles": {
            "footer": {
                "separator": True,
            }
        }
    }

    print("flex:", flex_msg)
    return FlexSendMessage(
        alt_text="Receipt Data", contents=flex_msg)
