import os
import logging

# Use new google-genai SDK with Vertex AI
try:
    from google import genai
    from google.genai.types import HttpOptions, Part
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

if not VERTEX_PROJECT:
    logging.error("GOOGLE_CLOUD_PROJECT environment variable not set")

PROMPT = """請用台灣用語的繁體中文總結這部影片。

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
            http_options=HttpOptions(api_version="v1")
        )

        # Prepare content with YouTube URL and prompt
        # Note: Can mix Part objects and strings directly in contents list
        contents = [
            Part.from_uri(
                file_uri=youtube_url,
                mime_type="video/mp4"
            ),
            PROMPT
        ]

        # Generate content
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
