"""
ADK Tool: YouTube Video Summarization

Provides YouTube video summarization using Vertex AI Gemini's video understanding.
"""

import os
import logging
import time
from typing import Literal

from config.agent_config import get_agent_config

try:
    from google import genai
    from google.genai.types import (
        HttpOptions, Part, FileData, GenerateContentConfig, ThinkingConfig,
    )
    from google.genai.errors import ClientError
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

logger = logging.getLogger(__name__)

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'global')

# 2026-09-02/03 spike + round-2 measurement (27 production-prompt calls, 0 spikes;
# 5 earlier calls, 3 spikes): thinking_tokens for agentic video is either ~0 or
# ~35,000 — nothing observed in between. No client-side lever (thinking_level
# LOW/MINIMAL, thinking_budget=0, or omitting thinking_config entirely) changes
# this; it appears to be server-side non-determinism in Vertex AI's agentic video
# path. 5000 sits well above the observed "normal" ceiling (~0-2 hundred) and well
# below the observed spike floor (~33,000+), so it cleanly separates the two
# clusters. See docs/superpowers/specs/2026-09-02-video-qa-design.md.
THINKING_TOKENS_WARN_THRESHOLD = 5000

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

# Prompt for question-answering about a specific video
ASK_PROMPT_TEMPLATE = """請用台灣用語的繁體中文回答關於這部影片的問題。

【問題】
{question}

【輸出格式要求】
1. 不要使用任何 Markdown 語法（如 #, *, **, -, 等）
2. 使用純文字格式，適合直接發送到 LINE Bot
3. 若答案出現在影片的特定時間點，務必附上時間戳，格式為 MM:SS 或 H:MM:SS
4. 影片中若沒有相關內容，直接說「影片中沒有提到這個」，不要編造

【注意事項】
- 回答簡潔，控制在 300 字以內
- 有多個相關段落時，依時間順序條列
"""


def _is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video URL"""
    return (
        url.startswith("https://www.youtube.com")
        or url.startswith("https://youtu.be")
        or url.startswith("https://m.youtube.com")
        or url.startswith("https://youtube.com")
    )


def _extract_usage(response, model: str) -> dict:
    """把 usage_metadata 攤平成純 dict，呼叫端不必碰 SDK 型別。"""
    u = getattr(response, "usage_metadata", None)
    if u is None:
        return {"model": model, "prompt_tokens": 0, "output_tokens": 0,
                "thinking_tokens": 0, "tool_use_tokens": 0, "total_tokens": 0}
    return {
        "model": model,
        "prompt_tokens": getattr(u, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(u, "candidates_token_count", 0) or 0,
        "thinking_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        "tool_use_tokens": getattr(u, "tool_use_prompt_token_count", 0) or 0,
        "total_tokens": getattr(u, "total_token_count", 0) or 0,
    }


def _generate_video(youtube_url: str, prompt: str, *, thinking_level: str) -> dict:
    """對 YouTube 影片跑一次 agentic 查詢。

    thinking_level 刻意設為必填且無預設值：thinking token 是這通呼叫的成本
    主角，而其尖峰屬伺服器端非決定性，任何單一 thinking_level 設定都管不住
    （早期單次測試量到的「未設時貴 5.5 倍」不是穩定可重現的效果）。顯式帶入
    是為了把這個參數變成一個必須被看見、寫進 code review 的決定，而不是悄悄
    繼承 SDK 預設值。詳見 docs/superpowers/specs/2026-09-02-video-qa-design.md
    結論二、三。
    """
    if not youtube_url:
        return {"status": "error", "error_message": "No YouTube URL provided"}
    if not _is_youtube_url(youtube_url):
        return {"status": "error", "error_message": f"Invalid YouTube URL: {youtube_url}"}
    if not GENAI_AVAILABLE:
        return {"status": "error", "error_message": "google-genai package not available"}
    if not VERTEX_PROJECT:
        return {"status": "error", "error_message": "GOOGLE_CLOUD_PROJECT not configured"}

    model = get_agent_config().video_model
    max_retries = 2
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            client = genai.Client(
                vertexai=True,
                project=VERTEX_PROJECT,
                location=VERTEX_LOCATION,
                # agentic video understanding 只在 v1beta1 提供；v1 會靜默退回 STATIC
                http_options=HttpOptions(api_version="v1beta1"),
            )
            contents = [
                Part(
                    file_data=FileData(file_uri=youtube_url, mime_type="video/mp4"),
                    media_processing="AGENTIC",
                ),
                prompt,
            ]
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=GenerateContentConfig(
                    labels={"client_id": "info_helper"},
                    thinking_config=ThinkingConfig(thinking_level=thinking_level),
                ),
            )
            if not response.text:
                return {"status": "error", "error_message": "No content generated"}
            usage = _extract_usage(response, model)
            if usage["thinking_tokens"] > THINKING_TOKENS_WARN_THRESHOLD:
                logger.warning(
                    "Video call burned %s thinking tokens (expected ~0 with "
                    "thinking_level=LOW). Cost for this call is far above normal "
                    "(~%sx more output-billed tokens than a clean call). This is "
                    "server-side non-determinism, not a config error — see "
                    "docs/superpowers/specs/2026-09-02-video-qa-design.md",
                    usage["thinking_tokens"],
                    round(usage["thinking_tokens"] / THINKING_TOKENS_WARN_THRESHOLD, 1),
                )
            return {
                "status": "success",
                "text": response.text,
                "usage": usage,
            }

        except ClientError as e:
            if e.code == 429 and attempt < max_retries - 1:
                logger.warning(
                    f"Rate limit hit (429), retrying in {retry_delay}s... "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            if e.code == 429:
                return {"status": "error", "rate_limited": True, "error_message": (
                    "Vertex AI 使用量已達上限，請稍後再試。建議等待 1-2 分鐘後重試。")}
            logger.error(f"Vertex AI API error: {e}", exc_info=True)
            return {"status": "error",
                    "error_message": f"Vertex AI 錯誤 ({e.code}): {str(e)[:100]}"}

        except Exception as e:
            logger.error(f"Error processing video: {e}", exc_info=True)
            return {"status": "error",
                    "error_message": f"處理影片時發生錯誤: {str(e)[:100]}"}

    return {"status": "error", "error_message": "處理影片時發生未預期的錯誤"}


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
            - usage: Token usage breakdown for this call
            - error_message: Error description (if failed)
    """
    prompt = YOUTUBE_PROMPTS.get(mode, YOUTUBE_PROMPTS["normal"])
    logger.info(f"Summarizing YouTube video: {youtube_url} (mode: {mode})")
    result = _generate_video(youtube_url, prompt, thinking_level="LOW")
    if result["status"] != "success":
        return {"status": "error", "error_message": result["error_message"], "mode": mode}
    return {
        "status": "success",
        "summary": result["text"],
        "mode": mode,
        "usage": result["usage"],
    }


def ask_youtube_video(youtube_url: str, question: str) -> dict:
    """回答關於影片的單一問題。

    刻意不帶對話歷史：Vertex AI 上無法保留影片 context
    （見 spec Spike 結論一），傳回歷史只會 400 或被完整重跑。

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - answer: The generated answer (if successful)
            - usage: Token usage breakdown for this call
            - error_message: Error description (if failed)
    """
    logger.info(f"Asking about YouTube video: {youtube_url}")
    prompt = ASK_PROMPT_TEMPLATE.format(question=question)
    result = _generate_video(youtube_url, prompt, thinking_level="LOW")
    if result["status"] != "success":
        return {"status": "error", "error_message": result["error_message"],
                "rate_limited": result.get("rate_limited", False)}
    return {"status": "success", "answer": result["text"], "usage": result["usage"]}
