"""
Vision Agent

ADK-based agent for image analysis using Gemini multimodal capabilities.
"""

import logging
from typing import Optional
from io import BytesIO

import PIL.Image

try:
    from google.adk.agents import Agent
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False

from config.agent_config import AgentConfig, get_agent_config
from tools.summarizer import analyze_image

logger = logging.getLogger(__name__)

# Agent instruction
VISION_AGENT_INSTRUCTION = """你是圖片分析專家，專門分析和描述圖片內容。

## 工作流程
1. 接收用戶上傳的圖片
2. 使用 Gemini 視覺模型分析圖片
3. 提供詳細的圖片描述

## 回應原則
- 使用台灣用語的繁體中文
- 描述要詳細但簡潔
- 識別圖片中的文字、物品、人物、場景
- 適合在 LINE 訊息中閱讀
"""

# Default analysis prompt
DEFAULT_IMAGE_PROMPT = """請詳細描述這張圖片的內容，包括：
1. 主要物件或人物
2. 場景或背景
3. 任何可見的文字
4. 整體氛圍或情境

請使用台灣用語的繁體中文回答。"""


class VisionAgent:
    """
    ADK-based Vision Agent for image analysis.

    Uses Gemini's multimodal capabilities to:
    - Describe image content
    - Extract text from images
    - Identify objects and scenes
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize VisionAgent.

        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or get_agent_config()

        # Initialize ADK agent if available
        if ADK_AVAILABLE:
            self._init_adk_agent()
        else:
            self.adk_agent = None

        logger.info(f"VisionAgent initialized (ADK: {ADK_AVAILABLE})")

    def _init_adk_agent(self):
        """Initialize ADK agent for orchestration"""
        try:
            self.adk_agent = Agent(
                name="vision_agent",
                model=self.config.chat_model,  # Use capable model for vision
                description="圖片分析 Agent，使用 Gemini 視覺模型分析圖片內容",
                instruction=VISION_AGENT_INSTRUCTION,
                tools=[analyze_image],
            )
            logger.info("ADK Vision Agent created successfully")
        except Exception as e:
            logger.warning(f"Failed to create ADK agent: {e}")
            self.adk_agent = None

    async def analyze(
        self,
        image_data: bytes,
        prompt: Optional[str] = None
    ) -> dict:
        """
        Analyze an image.

        Args:
            image_data: Image data as bytes
            prompt: Custom analysis prompt (optional)

        Returns:
            dict with 'status', 'analysis', and optional 'error_message'
        """
        try:
            logger.info(f"Analyzing image ({len(image_data)} bytes)")

            analysis_prompt = prompt or DEFAULT_IMAGE_PROMPT

            result = analyze_image(
                image_data=image_data,
                prompt=analysis_prompt
            )

            return result

        except Exception as e:
            logger.error(f"Image analysis error: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"分析圖片時發生錯誤: {str(e)[:100]}"
            }

    async def analyze_pil_image(
        self,
        image: PIL.Image.Image,
        prompt: Optional[str] = None
    ) -> dict:
        """
        Analyze a PIL Image object.

        Args:
            image: PIL Image object
            prompt: Custom analysis prompt (optional)

        Returns:
            dict with 'status', 'analysis', and optional 'error_message'
        """
        try:
            # Convert PIL Image to bytes
            img_byte_arr = BytesIO()
            image.save(img_byte_arr, format='PNG')
            image_data = img_byte_arr.getvalue()

            return await self.analyze(image_data, prompt)

        except Exception as e:
            logger.error(f"PIL image analysis error: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"處理圖片時發生錯誤: {str(e)[:100]}"
            }


def create_vision_agent(config: Optional[AgentConfig] = None) -> VisionAgent:
    """
    Factory function to create a VisionAgent.

    Args:
        config: Optional configuration

    Returns:
        Configured VisionAgent instance
    """
    return VisionAgent(config)


def format_vision_response(result: dict) -> str:
    """
    Format vision agent response for display.

    Args:
        result: Result dict from VisionAgent

    Returns:
        Formatted response string
    """
    if result["status"] != "success":
        return f"❌ {result.get('error_message', '圖片分析失敗')}"

    analysis = result.get("analysis", "無法分析圖片")
    return f"🖼️ 圖片分析結果\n\n{analysis}"
