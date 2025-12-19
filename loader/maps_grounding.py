"""
Google Maps Grounding API integration module
Uses Gemini with Google Maps grounding for location-based queries via Vertex AI
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Check if new google-genai SDK is available
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    logger.warning("google-genai package not available. Maps grounding features will be disabled.")
    GENAI_AVAILABLE = False


# Query templates for different place types
QUERY_TEMPLATES = {
    "gas_station": "請幫我找出附近的加油站，並列出名稱、距離和地址。",
    "parking": "請幫我找出附近的停車場，並列出名稱、收費方式（如果有）和地址。",
    "restaurant": "請幫我找出附近評價不錯的餐廳，並列出名稱、類型和地址。",
}


async def search_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "restaurant",
    custom_query: Optional[str] = None,
    language_code: str = "zh-TW"
) -> str:
    """
    使用 Google Maps Vertex AI Grounding API 搜尋附近地點

    Args:
        latitude: 緯度
        longitude: 經度
        place_type: 地點類型 - "gas_station", "parking", "restaurant"
        custom_query: 自訂查詢（如果提供，會覆蓋預設模板）
        language_code: 語言代碼（預設：zh-TW 繁體中文）

    Returns:
        str: AI 生成的附近地點推薦

    Note:
        需要設定以下環境變數來使用 Vertex AI：
        - GOOGLE_CLOUD_PROJECT: 你的 GCP 專案 ID
        - GOOGLE_CLOUD_LOCATION: 區域（建議：global）
        - GOOGLE_GENAI_USE_VERTEXAI: 設為 True
        或者使用 Application Default Credentials (ADC)
    """
    if not GENAI_AVAILABLE:
        return "❌ 抱歉，Maps 搜尋功能目前無法使用。請聯繫管理員。"

    try:
        # Check for Vertex AI configuration
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        location = os.getenv('GOOGLE_CLOUD_LOCATION', 'global')

        if not project_id:
            logger.error("GOOGLE_CLOUD_PROJECT not found. Maps Grounding requires Vertex AI.")
            return "❌ 抱歉，Google Cloud 專案未設定。Maps 搜尋需要 Vertex AI 配置。"

        # Build query
        query = custom_query if custom_query else QUERY_TEMPLATES.get(
            place_type,
            QUERY_TEMPLATES["restaurant"]
        )

        logger.info(f"Searching for {place_type} at ({latitude}, {longitude}) using Vertex AI")

        # Initialize Vertex AI client
        # The client will automatically use Application Default Credentials (ADC)
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            http_options=types.HttpOptions(api_version="v1")
        )

        # Call API with Maps grounding
        # Using gemini-2.5-flash which supports Maps Grounding
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=query,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(google_maps=types.GoogleMaps(
                        enable_widget=False
                    ))
                ],
                tool_config=types.ToolConfig(
                    retrieval_config=types.RetrievalConfig(
                        lat_lng=types.LatLng(
                            latitude=latitude,
                            longitude=longitude
                        ),
                        language_code=language_code,
                    ),
                ),
            ),
        )

        result = response.text
        logger.info(f"Maps Grounding API returned {len(result)} characters")

        # Add emoji based on place type
        emoji_map = {
            "gas_station": "⛽",
            "parking": "🅿️",
            "restaurant": "🍴"
        }
        emoji = emoji_map.get(place_type, "📍")

        return f"{emoji} 附近的{get_place_type_name(place_type)}：\n\n{result}"

    except Exception as e:
        logger.error(f"Maps Grounding API error: {e}", exc_info=True)
        return f"❌ 抱歉，無法取得附近地點資訊。\n\n錯誤訊息：{str(e)[:100]}"


def get_place_type_name(place_type: str) -> str:
    """Get Chinese name for place type"""
    names = {
        "gas_station": "加油站",
        "parking": "停車場",
        "restaurant": "餐廳"
    }
    return names.get(place_type, "地點")
