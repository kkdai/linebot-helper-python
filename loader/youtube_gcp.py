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

PROMPTS = {
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


async def load_transcript_from_youtube(youtube_url: str, mode: str = "normal") -> str:
    """
    Summarizes a YouTube video using Vertex AI.

    Args:
        youtube_url: YouTube video URL
        mode: Summary mode - "normal", "detail", or "twitter"

    Returns:
        Formatted summary text
    """
    if not GENAI_AVAILABLE:
        return "錯誤：google-genai 套件未安裝。"

    if not VERTEX_PROJECT:
        return "錯誤：GOOGLE_CLOUD_PROJECT 未設定。"

    # Get the appropriate prompt based on mode
    prompt = PROMPTS.get(mode, PROMPTS["normal"])

    logging.info(f"Summarizing YouTube video: {youtube_url} (mode: {mode})")

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
            prompt
        ]

        # Generate content
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
        )

        if response.text:
            summary = response.text
            logging.info(f"YouTube summary generated ({mode}): {summary[:100]}...")
            return summary
        else:
            logging.error("No text content in Vertex AI response")
            return "無法從影片中提取摘要。"

    except Exception as e:
        logging.error(
            f"An error occurred while summarizing YouTube video: {e}", exc_info=True)
        return f"處理影片時發生錯誤: {str(e)[:100]}"
