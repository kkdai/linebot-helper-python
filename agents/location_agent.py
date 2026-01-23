"""
Location Agent

ADK-based agent for location-based searches using Google Maps Grounding.
"""

import logging
from typing import Optional, Literal

try:
    from google.adk.agents import Agent
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False

from config.agent_config import AgentConfig, get_agent_config
from tools.maps_tool import search_nearby_places

logger = logging.getLogger(__name__)

# Agent instruction
LOCATION_AGENT_INSTRUCTION = """你是地點搜尋專家，專門協助用戶找到附近的地點。

## 工作流程
1. 接收用戶的位置（經緯度）
2. 根據用戶需求搜尋附近地點（加油站、停車場、餐廳等）
3. 使用 Google Maps Grounding 取得最新資訊
4. 回傳格式化的搜尋結果

## 回應原則
- 使用台灣用語的繁體中文
- 提供實用的地點資訊（名稱、地址、距離）
- 適合在 LINE 訊息中閱讀
"""


class LocationAgent:
    """
    ADK-based Location Agent for nearby place searches.

    Uses Google Maps Grounding to find:
    - Gas stations
    - Parking lots
    - Restaurants
    - Custom queries
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize LocationAgent.

        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or get_agent_config()

        if not self.config.enable_maps_grounding:
            logger.warning("Maps grounding is disabled in configuration")

        # Initialize ADK agent if available
        if ADK_AVAILABLE:
            self._init_adk_agent()
        else:
            self.adk_agent = None

        logger.info(f"LocationAgent initialized (ADK: {ADK_AVAILABLE})")

    def _init_adk_agent(self):
        """Initialize ADK agent for orchestration"""
        try:
            self.adk_agent = Agent(
                name="location_agent",
                model=self.config.fast_model,
                description="地點搜尋 Agent，使用 Google Maps Grounding 搜尋附近地點",
                instruction=LOCATION_AGENT_INSTRUCTION,
                tools=[search_nearby_places],
            )
            logger.info("ADK Location Agent created successfully")
        except Exception as e:
            logger.warning(f"Failed to create ADK agent: {e}")
            self.adk_agent = None

    async def search(
        self,
        latitude: float,
        longitude: float,
        place_type: Literal["gas_station", "parking", "restaurant"] = "restaurant",
        custom_query: Optional[str] = None
    ) -> dict:
        """
        Search for nearby places.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            place_type: Type of place to search
            custom_query: Custom search query (overrides place_type)

        Returns:
            dict with 'status', 'places', and optional 'error_message'
        """
        if not self.config.enable_maps_grounding:
            return {
                "status": "error",
                "error_message": "Maps 搜尋功能已停用"
            }

        try:
            logger.info(f"Searching {place_type} at ({latitude}, {longitude})")

            result = search_nearby_places(
                latitude=latitude,
                longitude=longitude,
                place_type=place_type,
                custom_query=custom_query,
                language_code="zh-TW"
            )

            return result

        except Exception as e:
            logger.error(f"Location search error: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"搜尋地點時發生錯誤: {str(e)[:100]}"
            }


def create_location_agent(config: Optional[AgentConfig] = None) -> LocationAgent:
    """
    Factory function to create a LocationAgent.

    Args:
        config: Optional configuration

    Returns:
        Configured LocationAgent instance
    """
    return LocationAgent(config)


def format_location_response(result: dict) -> str:
    """
    Format location agent response for display.

    Args:
        result: Result dict from LocationAgent

    Returns:
        Formatted response string
    """
    if result["status"] != "success":
        return f"❌ {result.get('error_message', '搜尋失敗')}"

    return result.get("places", "找不到附近地點")
