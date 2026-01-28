"""
ADK Tool: Text Summarization and Image Analysis

Provides summarization and image analysis capabilities using Vertex AI Gemini.
"""

import os
import logging
from typing import Literal
import PIL.Image
from io import BytesIO

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

logger = logging.getLogger(__name__)

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

# Summarization prompts for different modes
SUMMARIZE_PROMPTS = {
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


def summarize_text(
    text: str,
    mode: Literal["short", "normal", "detailed"] = "normal"
) -> dict:
    """
    Summarize text content using Vertex AI Gemini.

    This tool takes a text input and generates a summary in Traditional Chinese
    using Taiwan-specific terminology. The summary includes relevant hashtags.

    Args:
        text: The text content to summarize. Can be from articles, web pages,
              papers, video transcripts, or any text source.
        mode: Summary length mode:
            - "short": 1-3 key points, very concise (50-100 chars)
            - "normal": Balanced summary with bullet points (200-300 chars)
            - "detailed": Comprehensive analysis with background and conclusion (500-800 chars)

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - summary: The generated summary text (if successful)
            - error_message: Error description (if failed)
    """
    if not text or not text.strip():
        return {
            "status": "error",
            "error_message": "No text content provided for summarization"
        }

    prompt_template = SUMMARIZE_PROMPTS.get(mode, SUMMARIZE_PROMPTS["normal"])
    prompt = prompt_template.replace("{text}", text)

    try:
        client = _get_vertex_client()

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=2048,
            )
        )

        if response.text:
            return {
                "status": "success",
                "summary": response.text
            }
        else:
            return {
                "status": "error",
                "error_message": "No summary generated"
            }

    except Exception as e:
        logger.error(f"Error summarizing text: {e}")
        return {
            "status": "error",
            "error_message": f"Summarization failed: {str(e)[:100]}"
        }


def analyze_image_agentic(
    image_data: bytes,
    prompt: str = "請仔細分析這張圖片，使用 agentic vision 能力來深入檢視細節，包括放大、裁切、標註等。使用繁體中文回答。"
) -> dict:
    """
    Analyze an image using Gemini 3 Flash Agentic Vision with code execution.

    The model can write and execute Python code to zoom, crop, annotate,
    and perform detailed visual analysis on the image. Returns both text
    analysis and any generated/annotated images.

    Args:
        image_data: The image data as bytes (PNG, JPEG, etc.)
        prompt: The analysis prompt for agentic vision.

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - analysis: The text analysis result (if successful)
            - images: List of annotated image bytes (if any generated)
            - error_message: Error description (if failed)
    """
    if not image_data:
        return {
            "status": "error",
            "error_message": "No image data provided"
        }

    try:
        client = _get_vertex_client()

        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(
                data=image_data,
                mime_type="image/png"
            )
        ]

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.5,
                max_output_tokens=4096,
                tools=[types.Tool(code_execution=types.ToolCodeExecution)],
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MEDIUM
                ),
            )
        )

        # Extract text, code execution results, and generated images
        result_parts = []
        generated_images = []

        for part in response.candidates[0].content.parts:
            # Skip thinking parts
            if hasattr(part, 'thought') and part.thought:
                continue
            if part.text is not None:
                result_parts.append(part.text)
            if part.code_execution_result is not None:
                result_parts.append(f"[Code Output]: {part.code_execution_result.output}")
            # Extract generated/annotated images
            img = part.as_image()
            if img is not None:
                generated_images.append(img.image_bytes)
                logger.info(f"Extracted annotated image: {len(img.image_bytes)} bytes")

        analysis = "\n".join(result_parts) if result_parts else None

        if analysis or generated_images:
            result = {
                "status": "success",
                "analysis": analysis or "（圖片已標註完成）"
            }
            if generated_images:
                result["images"] = generated_images
            return result
        else:
            return {
                "status": "error",
                "error_message": "No analysis generated"
            }

    except Exception as e:
        logger.error(f"Error in agentic vision analysis: {e}")
        return {
            "status": "error",
            "error_message": f"Agentic Vision failed: {str(e)[:100]}"
        }


def analyze_image(
    image_data: bytes,
    prompt: str = "請描述這張圖片的內容，使用繁體中文回答。"
) -> dict:
    """
    Analyze an image using Vertex AI Gemini multimodal capabilities.

    This tool takes image data and a prompt, then uses Gemini's vision
    capabilities to analyze the image content.

    Args:
        image_data: The image data as bytes (PNG, JPEG, etc.)
        prompt: The analysis prompt describing what to analyze in the image.
                Defaults to asking for a general description in Traditional Chinese.

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - analysis: The image analysis result (if successful)
            - error_message: Error description (if failed)
    """
    if not image_data:
        return {
            "status": "error",
            "error_message": "No image data provided"
        }

    try:
        client = _get_vertex_client()

        # Create multimodal content
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(
                data=image_data,
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

        if response.text:
            return {
                "status": "success",
                "analysis": response.text
            }
        else:
            return {
                "status": "error",
                "error_message": "No analysis generated"
            }

    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        return {
            "status": "error",
            "error_message": f"Image analysis failed: {str(e)[:100]}"
        }
