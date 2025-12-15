import os
import logging

# Use new google-genai SDK with Vertex AI
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

if not VERTEX_PROJECT:
    logging.error("GOOGLE_CLOUD_PROJECT environment variable not set")

PROMPT = """請用台灣用語的繁體中文，簡潔地以條列式總結這部影片的重點。

請遵循以下步驟來完成此任務：

# 步驟
1. 從影片內容中提取重要重點。
2. 將重點整理成條列式，確保每一點為簡短且明確的句子。
3. 使用符合台灣用語的簡潔繁體中文。

# 輸出格式
- 重點應以條列式列出，每一點應為一個短句或片語，語言必須簡潔明瞭。
"""


async def load_transcript_from_youtube(youtube_url: str) -> str:
    """
    Summarizes a YouTube video using Vertex AI.
    """
    if not GENAI_AVAILABLE:
        return "錯誤：google-genai 套件未安裝。"

    if not VERTEX_PROJECT:
        return "錯誤：GOOGLE_CLOUD_PROJECT 未設定。"

    logging.info(f"Summarizing YouTube video: {youtube_url}")

    try:
        # Initialize Vertex AI client
        client = genai.Client(
            vertexai=True,
            project=VERTEX_PROJECT,
            location=VERTEX_LOCATION,
            http_options=types.HttpOptions(api_version="v1beta")
        )

        # Prepare content with prompt and YouTube URL
        contents = [
            types.Part.from_text(text=PROMPT),
            types.Part.from_uri(
                file_uri=youtube_url,
                mime_type="video/*"
            )
        ]

        # Generate content
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=contents,
        )

        if response.text:
            summary = response.text
            logging.info(f"YouTube summary generated: {summary[:100]}...")
            return summary
        else:
            logging.error("No text content in Vertex AI response")
            return "無法從影片中提取摘要。"

    except Exception as e:
        logging.error(
            f"An error occurred while summarizing YouTube video: {e}", exc_info=True)
        return f"處理影片時發生錯誤: {str(e)[:100]}"
