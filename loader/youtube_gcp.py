import os
import logging
import httpx

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    logging.error("GOOGLE_API_KEY environment variable not set")

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

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
    Summarizes a YouTube video using the Gemini API.
    """
    if not GEMINI_API_KEY:
        return "錯誤：GOOGLE_API_KEY 未設定。"

    logging.info(f"Summarizing YouTube video: {youtube_url}")

    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    data = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {
                    "file_data": {
                        "file_uri": youtube_url
                    }
                }
            ]
        }]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, headers=headers, json=data, timeout=180)
            response.raise_for_status()

            result = response.json()

            if "candidates" in result and result["candidates"]:
                content = result["candidates"][0].get("content", {})
                if "parts" in content and content["parts"]:
                    summary = content["parts"][0].get("text", "")
                    logging.info(f"YouTube summary generated: {summary[:100]}...")
                    return summary

            logging.error(
                f"Could not extract summary from Gemini API response: {result}")
            return "無法從影片中提取摘要。"

    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        logging.error(
            f"HTTP error occurred while calling Gemini API: {error_text}")
        return f"無法處理影片，API 錯誤: {e.response.status_code}"
    except Exception as e:
        logging.error(
            f"An error occurred while summarizing YouTube video: {e}", exc_info=True)
        return f"處理影片時發生錯誤: {e}"