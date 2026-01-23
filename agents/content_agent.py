"""
Content Agent

ADK-based agent for URL content extraction and summarization.
Handles web pages, YouTube videos, and PDF documents.
"""

import logging
from typing import Optional, Literal

try:
    from google.adk.agents import Agent
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False

from config.agent_config import AgentConfig, get_agent_config
from tools.url_loader import load_url_content
from tools.summarizer import summarize_text
from tools.youtube_tool import summarize_youtube_video

logger = logging.getLogger(__name__)

# Agent instruction
CONTENT_AGENT_INSTRUCTION = """你是內容摘要專家，專門處理網頁、影片和文件的摘要。

## 工作流程
1. 接收 URL 後，判斷內容類型（網頁、YouTube、PDF）
2. 使用適當的工具載入內容
3. 生成繁體中文摘要
4. 回傳格式化的結果

## 回應原則
- 使用台灣用語的繁體中文
- 摘要要簡潔但完整
- 包含關鍵重點和 hashtag
- 適合在 LINE 訊息中閱讀
"""


class ContentAgent:
    """
    ADK-based Content Agent for URL summarization.

    Handles:
    - Web pages (with multi-fallback extraction)
    - YouTube videos (with multiple summary modes)
    - PDF documents
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize ContentAgent.

        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or get_agent_config()

        # Initialize ADK agent if available
        if ADK_AVAILABLE:
            self._init_adk_agent()
        else:
            self.adk_agent = None

        logger.info(f"ContentAgent initialized (ADK: {ADK_AVAILABLE})")

    def _init_adk_agent(self):
        """Initialize ADK agent for orchestration"""
        try:
            self.adk_agent = Agent(
                name="content_agent",
                model=self.config.fast_model,
                description="內容摘要 Agent，處理網頁、YouTube 和 PDF 的摘要",
                instruction=CONTENT_AGENT_INSTRUCTION,
                tools=[load_url_content, summarize_text, summarize_youtube_video],
            )
            logger.info("ADK Content Agent created successfully")
        except Exception as e:
            logger.warning(f"Failed to create ADK agent: {e}")
            self.adk_agent = None

    async def process_url(
        self,
        url: str,
        mode: Literal["short", "normal", "detailed"] = "normal",
        youtube_mode: Literal["normal", "detail", "twitter"] = "normal"
    ) -> dict:
        """
        Process a URL and return summarized content.

        Args:
            url: The URL to process
            mode: Summary mode for web pages (short/normal/detailed)
            youtube_mode: Summary mode for YouTube (normal/detail/twitter)

        Returns:
            dict with 'status', 'content', 'content_type', and optional 'error_message'
        """
        try:
            logger.info(f"Processing URL: {url} (mode: {mode}, youtube_mode: {youtube_mode})")

            # Load URL content
            result = load_url_content(url, youtube_mode=youtube_mode)

            if result["status"] != "success":
                return result

            content = result["content"]
            content_type = result.get("content_type", "html")

            # YouTube content is already summarized by the tool
            if content_type == "youtube":
                return {
                    "status": "success",
                    "content": content,
                    "content_type": "youtube",
                    "url": url,
                    "mode": youtube_mode
                }

            # Summarize web/PDF content
            summary_result = summarize_text(content, mode=mode)

            if summary_result["status"] != "success":
                return {
                    "status": "error",
                    "error_message": summary_result.get("error_message", "Summarization failed"),
                    "url": url
                }

            return {
                "status": "success",
                "content": summary_result["summary"],
                "content_type": content_type,
                "url": url,
                "mode": mode
            }

        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"處理 URL 時發生錯誤: {str(e)[:100]}",
                "url": url
            }

    async def summarize_youtube(
        self,
        url: str,
        mode: Literal["normal", "detail", "twitter"] = "normal"
    ) -> dict:
        """
        Summarize a YouTube video.

        Args:
            url: YouTube video URL
            mode: Summary mode (normal/detail/twitter)

        Returns:
            dict with 'status', 'summary', and optional 'error_message'
        """
        return summarize_youtube_video(url, mode=mode)


def create_content_agent(config: Optional[AgentConfig] = None) -> ContentAgent:
    """
    Factory function to create a ContentAgent.

    Args:
        config: Optional configuration

    Returns:
        Configured ContentAgent instance
    """
    return ContentAgent(config)


def format_content_response(result: dict, include_url: bool = True) -> str:
    """
    Format content agent response for display.

    Args:
        result: Result dict from ContentAgent
        include_url: Whether to include the URL in output

    Returns:
        Formatted response string
    """
    if result["status"] != "success":
        return f"❌ {result.get('error_message', '處理失敗')}"

    text = result["content"]

    if include_url and result.get("url"):
        text = f"{result['url']}\n\n{text}"

    return text
