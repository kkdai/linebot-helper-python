"""
ADK Tool: YouTube Video Summarization

Provides YouTube video summarization using Vertex AI Gemini's video understanding.
"""

import os
import logging
import time
from typing import Literal

try:
    from google import genai
    from google.genai.types import HttpOptions, Part
    from google.genai.errors import ClientError
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

logger = logging.getLogger(__name__)

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

# YouTube summarization prompts
YOUTUBE_PROMPTS = {
    "normal": """請用台灣用語的繁體中文總結這部影片。

【輸出格式要求】
1. 不要使用任何 Markdown 語法（如 #, *, **, -, 等）
2. 使用純文字格式，適合直接發送到 LINE Bot
3. 條列式重點使用數字編號（1. 2. 3. ...）
4. 最後附上 3-5 個相關的 hashtag，使用半形 # 符號

【輸出結構】
📹 影片摘要

1. [第一個重點]
2. [第二個重點]
3. [第三個重點]
（依影片內容調整重點數量，建議 3-6 點）

🏷️ 標籤
#關鍵字1 #關鍵字2 #關鍵字3

【注意事項】
- 每個重點簡短有力，一行為限
- 標籤要符合台灣常用習慣
- 不要使用任何 markdown 格式符號
""",

    "detail": """請用台灣用語的繁體中文提供這部影片的詳細摘要（至少 300 字）。

【輸出格式要求】
1. 不要使用任何 Markdown 語法（如 #, *, **, -, 等）
2. 使用純文字格式，適合直接發送到 LINE Bot
3. 針對影片的每個主要段落進行整理

【輸出結構】
📹 影片詳細分析

▶️ 開場/前言
[整理開場內容，說明影片的主旨和背景]

▶️ 主要內容
[針對影片的核心內容進行段落式整理，每個重點段落都要詳細說明]

▶️ 結論/收尾
[整理影片的結論或總結]

💡 我的觀察
[從整體來看這部影片的價值、特色、適合觀眾等]

🏷️ 標籤
#關鍵字1 #關鍵字2 #關鍵字3

【注意事項】
- 內容要超過 300 字
- 段落間要有適當的分隔
- 不要使用任何 markdown 格式符號
""",

    "twitter": """請用台灣用語的繁體中文，將這部影片改寫成適合在 Twitter/X 發布的宣傳文案。

【輸出格式要求】
1. 不要使用任何 Markdown 語法（如 #, *, **, -, 等）
2. 使用純文字格式
3. 內容要吸引人點擊觀看
4. 字數控制在 200 字以內（不含 hashtag）
5. 語氣要輕鬆有趣，能引起共鳴

【輸出結構】
🐦 推薦分享

[用 2-3 句話說明為什麼要看這部影片]

💬 我的想法
[用 1-2 句話分享你的觀點或感想]

📺 影片重點
• [重點 1]
• [重點 2]
• [重點 3]

🔗 值得一看！

#關鍵字1 #關鍵字2 #關鍵字3 #關鍵字4 #關鍵字5

【注意事項】
- 語氣要親切有趣
- 重點要簡潔有力
- hashtag 要選擇熱門且相關的
- 不要使用任何 markdown 格式符號
"""
}


def _is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video URL"""
    return (
        url.startswith("https://www.youtube.com")
        or url.startswith("https://youtu.be")
        or url.startswith("https://m.youtube.com")
        or url.startswith("https://youtube.com")
    )


def summarize_youtube_video(
    youtube_url: str,
    mode: Literal["normal", "detail", "twitter"] = "normal"
) -> dict:
    """
    Summarize a YouTube video using Vertex AI Gemini's video understanding.

    This tool takes a YouTube URL and generates a summary in Traditional Chinese
    using Taiwan-specific terminology. Supports multiple summary formats.

    Args:
        youtube_url: The YouTube video URL to summarize.
                     Supports youtube.com, youtu.be, and m.youtube.com URLs.
        mode: Summary style:
            - "normal": Standard summary with 3-6 bullet points
            - "detail": Detailed analysis with sections (300+ characters)
            - "twitter": Social media friendly format for sharing

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - summary: The generated video summary (if successful)
            - mode: The summarization mode used
            - error_message: Error description (if failed)
    """
    if not youtube_url:
        return {
            "status": "error",
            "error_message": "No YouTube URL provided"
        }

    if not _is_youtube_url(youtube_url):
        return {
            "status": "error",
            "error_message": f"Invalid YouTube URL: {youtube_url}"
        }

    if not GENAI_AVAILABLE:
        return {
            "status": "error",
            "error_message": "google-genai package not available"
        }

    if not VERTEX_PROJECT:
        return {
            "status": "error",
            "error_message": "GOOGLE_CLOUD_PROJECT not configured"
        }

    prompt = YOUTUBE_PROMPTS.get(mode, YOUTUBE_PROMPTS["normal"])
    logger.info(f"Summarizing YouTube video: {youtube_url} (mode: {mode})")

    # Retry logic for rate limiting
    max_retries = 2
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            client = genai.Client(
                vertexai=True,
                project=VERTEX_PROJECT,
                location=VERTEX_LOCATION,
                http_options=HttpOptions(api_version="v1")
            )

            contents = [
                Part.from_uri(
                    file_uri=youtube_url,
                    mime_type="video/mp4"
                ),
                prompt
            ]

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
            )

            if response.text:
                logger.info(f"YouTube summary generated ({mode}): {response.text[:100]}...")
                return {
                    "status": "success",
                    "summary": response.text,
                    "mode": mode
                }
            else:
                return {
                    "status": "error",
                    "error_message": "No summary content generated"
                }

        except ClientError as e:
            if e.code == 429:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Rate limit hit (429), retrying in {retry_delay}s... "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    return {
                        "status": "error",
                        "error_message": (
                            "Vertex AI 使用量已達上限，請稍後再試。"
                            "建議等待 1-2 分鐘後重試。"
                        )
                    }
            else:
                logger.error(f"Vertex AI API error: {e}", exc_info=True)
                return {
                    "status": "error",
                    "error_message": f"Vertex AI 錯誤 ({e.code}): {str(e)[:100]}"
                }

        except Exception as e:
            logger.error(f"Error summarizing YouTube video: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"處理影片時發生錯誤: {str(e)[:100]}"
            }

    return {
        "status": "error",
        "error_message": "處理影片時發生未預期的錯誤"
    }
