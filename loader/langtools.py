# Pure Vertex AI implementation - no LangChain
import os
import logging
import PIL.Image
from io import BytesIO
from typing import Any
from pydantic import BaseModel, Field


# Use google-genai SDK for Vertex AI
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Set the user agent
os.environ["USER_AGENT"] = "myagent"

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')


def _get_vertex_client():
    """Get Vertex AI client instance"""
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai package not available")
    if not VERTEX_PROJECT:
        raise ValueError("GOOGLE_CLOUD_PROJECT not set")

    return genai.Client(
        vertexai=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,
        http_options=types.HttpOptions(api_version="v1")
    )


def summarize_text(text: str, max_tokens: int = 100, mode: str = "normal") -> str:
    '''
    Summarize a text using Vertex AI Gemini.

    Args:
        text: Text to summarize
        max_tokens: Maximum tokens for the summary (deprecated, use mode instead)
        mode: Summary mode - "short", "normal", or "detailed"

    Returns:
        Summarized text in Traditional Chinese
    '''
    return summarize_text_with_mode(text, mode)


def summarize_text_with_mode(text: str, mode: str = "normal") -> str:
    '''
    Summarize a text with different length modes using Vertex AI.

    Args:
        text: Text to summarize
        mode: Summary mode
            - "short" (短): 50-100 characters, key points only
            - "normal" (標準): 200-300 characters, balanced summary
            - "detailed" (詳細): 500-800 characters, comprehensive analysis

    Returns:
        Summarized text in Traditional Chinese
    '''
    # Define prompts for different modes
    prompts = {
        "short": """用台灣用語的繁體中文，用 1-3 個重點總結文章核心內容。務必極度簡潔。

原文： "{text}"

# 要求
- 只列出 1-3 個最關鍵重點
- 每個重點不超過 15 字
- 直接列出重點，不需要前言
- 結尾加入 2-3 個英文 hashtag

# 範例輸出：
- AI 技術快速發展
- 影響就業市場
- 需要政策規範
#AI #Technology #Policy""",

        "normal": """用台灣用語的繁體中文，簡潔地以條列式總結文章重點。在摘要後直接加入相關的英文 hashtag，以空格分隔。內容來源可以是網頁、文章、論文、影片字幕或逐字稿。

原文： "{text}"
請遵循以下步驟來完成此任務：

# 步驟
1. 從提供的內容中提取重要重點，無論來源是網頁、文章、論文、影片字幕或逐字稿。
2. 將重點整理成條列式，確保每一點為簡短且明確的句子。
3. 使用符合台灣用語的簡潔繁體中文。
4. 在摘要結尾處，加入至少三個相關的英文 hashtag，並以空格分隔。

# 輸出格式
- 重點應以條列式列出，每一點應為一個短句或片語，語言必須簡潔明瞭。
- 最後加入至少三個相關的英文 hashtag，每個 hashtag 之間用空格分隔。

# 範例
輸入：
文章內容：
台灣的報告指出，環境保護的重要性日益增加。許多人開始選擇使用可重複使用的產品。政府也實施了多項政策來降低廢物。

摘要：

輸出：
- 環境保護重要性增加
- 越來越多人使用可重複產品
- 政府實施減廢政策
#EnvironmentalProtection #Sustainability #Taiwan

reply in zh-TW""",

        "detailed": """用台灣用語的繁體中文，詳細地以條列式總結文章內容，包含背景、主要論點、細節和結論。

原文： "{text}"

# 要求
1. 提供完整的文章背景和上下文
2. 詳細列出所有重要論點和細節
3. 包含具體的數據、案例或例子（如果有）
4. 分析文章的結論和影響
5. 使用台灣用語的繁體中文
6. 結尾加入相關的英文 hashtag

# 輸出格式

【背景】
- 提供文章背景和上下文

【主要內容】
- 詳細列出所有重要論點
- 包含具體細節和數據
- 列出關鍵案例或例子

【結論與影響】
- 總結文章結論
- 分析可能的影響

#Hashtag1 #Hashtag2 #Hashtag3

reply in zh-TW"""
    }

    # Select prompt based on mode
    prompt_template = prompts.get(mode, prompts["normal"])
    prompt = prompt_template.replace("{text}", text)

    try:
        client = _get_vertex_client()

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=2048,
            )
        )

        return response.text if response.text else "無法生成摘要"

    except Exception as e:
        logging.error(f"Error summarizing text: {e}")
        raise


def generate_json_from_image(img: PIL.Image.Image, prompt: str) -> Any:
    '''
    Analyze image using Vertex AI Gemini.

    Args:
        img: PIL Image object
        prompt: Prompt for image analysis

    Returns:
        Response object with text attribute
    '''
    try:
        client = _get_vertex_client()

        # Convert PIL Image to bytes
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Create multimodal content
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_image_bytes(
                data=img_byte_arr,
                mime_type="image/png"
            )
        ]

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.5,
                max_output_tokens=2048,
            )
        )

        logging.info(f">>>>{response.text}")

        # Return a simple object with text attribute for compatibility
        class ImageResponse:
            def __init__(self, text):
                self.text = text
                self.parts = [text] if text else []
                self.candidates = []

        return ImageResponse(response.text if response.text else "")

    except Exception as e:
        logging.error(f"Error analyzing image: {e}")
        raise


# Legacy helper function for compatibility
def docs_to_str(docs: list) -> str:
    """Convert documents to string (for backward compatibility)"""
    if not docs:
        return ""

    # Handle different document types
    result = []
    for doc in docs:
        if hasattr(doc, 'page_content'):
            result.append(doc.page_content)
        elif isinstance(doc, dict) and 'page_content' in doc:
            result.append(doc['page_content'])
        elif isinstance(doc, str):
            result.append(doc)
        else:
            result.append(str(doc))

    return "\n".join(result)


class SocialMediaPosts(BaseModel):
    facebook: str = Field(description="適合 Facebook 的爆款分享貼文文案，包含吸引人的標題、Emoji、條列重點、互動問題及相關 Hashtag")
    linkedin: str = Field(description="適合 LinkedIn 的專業商務貼文文案，著重專業洞察、核心收穫、引人深思的問題及專業 Hashtag")
    threads: str = Field(description="適合 Threads 的口語化貼文文案，以脆友語氣撰寫，第一句需有強烈共鳴或槽點，段落極短，少用 Hashtag，著重引導留言討論")


def generate_social_media_posts(text: str) -> dict:
    """
    Generate viral social media posts for FB, LinkedIn, and Threads from article text.

    Args:
        text: The text content of the crawled webpage.

    Returns:
        dict: A dictionary containing:
            - facebook: FB copy
            - linkedin: LinkedIn copy
            - threads: Threads copy
    """
    if not text or not text.strip():
        return {
            "facebook": "無法取得網頁內容，無法產生文案。",
            "linkedin": "無法取得網頁內容，無法產生文案。",
            "threads": "無法取得網頁內容，無法產生文案。"
        }

    prompt = f"""請針對以下網頁內容，為三個不同的社群平台（Facebook、LinkedIn、Meta Threads）各撰寫一篇容易「爆款」（高互動、高分享、吸引眼球）的繁體中文（台灣用語）分享貼文。

網頁內容：
{text}

# 寫作指南：

## 1. Facebook 爆款貼文：
- 吸引人的 Hook：第一句話必須非常吸睛，善用好奇心、痛點或誇張的開頭。
- 版面排版：多用 Emoji，段落清晰，使用條列式（Bullet points）整理核心觀點。
- 呼籲行動（CTA）：結尾提出一個好回答的問題，引導讀者留言或分享。
- Hashtags：加入 3-5 個相關的熱門 Hashtag。
- 長度：約 200-400 字。

## 2. LinkedIn 專業貼文：
- 專業 Hook：第一句從商業洞察、職場學習、趨勢分析或個人省思出發。
- 內容結構：語氣專業、理性，分享文章的核心價值、給職場人士或企業的 3 個具體 Takeaways。
- 呼籲行動：徵求專業意見或開啟思辨討論，例如：「你怎麼看這個趨勢？」
- Hashtags：加入 3-5 個專業領域的 Hashtag。
- 長度：約 300-500 字。

## 3. Meta Threads 脆友討論：
- Threads 脆友 Hook：極度口語化、像跟朋友講話，第一句要帶有強烈共鳴、槽點、吐槽、或一針見血的觀點。
- 內容風格：段落極短（每段 1-2 句話），善用白話文、網路用語或迷因感。以分享八卦、大實話或內行人才懂的梗為佳。
- 呼籲行動：隨性引導留言，例如：「有人也是這樣嗎？」
- Hashtags：不使用或僅使用 1 個 Hashtag。
- 長度：約 150-300 字。
"""

    try:
        client = _get_vertex_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=SocialMediaPosts,
                max_output_tokens=4096,
            )
        )

        import json
        if response.text:
            return json.loads(response.text)
        else:
            raise Exception("Empty response text from Gemini")

    except Exception as e:
        logging.error(f"Error generating social media posts: {e}")
        # Fallback dictionary
        return {
            "facebook": f"生成 Facebook 文案失敗：{str(e)[:100]}",
            "linkedin": f"生成 LinkedIn 文案失敗：{str(e)[:100]}",
            "threads": f"生成 Threads 文案失敗：{str(e)[:100]}"
        }

