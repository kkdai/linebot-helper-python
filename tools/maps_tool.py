"""
ADK Tool: Google Maps Location Search

Provides location-based search using Google Maps Grounding via Vertex AI.
"""

import os
import logging
from typing import Literal, Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.warning("google-genai package not available. Maps grounding features will be disabled.")

logger = logging.getLogger(__name__)

# Query templates for different place types
QUERY_TEMPLATES = {
    "gas_station": "請幫我找出附近的加油站，並列出名稱、距離和地址。",
    "parking": "請幫我找出附近的停車場，並列出名稱、收費方式（如果有）和地址。",
    "restaurant": "請幫我找出附近評價不錯的餐廳，並列出名稱、類型和地址。",
}

PLACE_TYPE_NAMES = {
    "gas_station": "加油站",
    "parking": "停車場",
    "restaurant": "餐廳"
}

PLACE_TYPE_EMOJIS = {
    "gas_station": "⛽",
    "parking": "🅿️",
    "restaurant": "🍴"
}


def search_nearby_places(
    latitude: float,
    longitude: float,
    place_type: Literal["gas_station", "parking", "restaurant"] = "restaurant",
    custom_query: Optional[str] = None,
    language_code: str = "zh-TW"
) -> dict:
    """
    Search for nearby places using Google Maps Grounding via Vertex AI.

    This tool performs location-based searches using Google Maps data
    through Vertex AI's Maps Grounding feature. Returns recommendations
    in Traditional Chinese.

    Args:
        latitude: The latitude coordinate of the search center point.
        longitude: The longitude coordinate of the search center point.
        place_type: Type of place to search for:
            - "gas_station": Nearby gas stations
            - "parking": Nearby parking lots
            - "restaurant": Nearby restaurants (default)
        custom_query: Custom search query. If provided, overrides the default
                      template for the place_type.
        language_code: Language for results (default: "zh-TW" for Traditional Chinese)

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - places: The search results with place recommendations (if successful)
            - place_type: The type of places searched
            - coordinates: The search center coordinates
            - error_message: Error description (if failed)
    """
    if not GENAI_AVAILABLE:
        return {
            "status": "error",
            "error_message": "Maps 搜尋功能目前無法使用 (google-genai 未安裝)"
        }

    project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
    location = os.getenv('GOOGLE_CLOUD_LOCATION', 'global')

    if not project_id:
        return {
            "status": "error",
            "error_message": "Google Cloud 專案未設定。Maps 搜尋需要 Vertex AI 配置。"
        }

    # Build query
    query = custom_query if custom_query else QUERY_TEMPLATES.get(
        place_type,
        QUERY_TEMPLATES["restaurant"]
    )

    logger.info(f"Searching for {place_type} at ({latitude}, {longitude}) using Vertex AI")

    try:
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            http_options=types.HttpOptions(api_version="v1")
        )

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

        # Format response with emoji
        emoji = PLACE_TYPE_EMOJIS.get(place_type, "📍")
        place_name = PLACE_TYPE_NAMES.get(place_type, "地點")
        formatted_result = f"{emoji} 附近的{place_name}：\n\n{result}"

        return {
            "status": "success",
            "places": formatted_result,
            "place_type": place_type,
            "coordinates": {
                "latitude": latitude,
                "longitude": longitude
            }
        }

    except Exception as e:
        logger.error(f"Maps Grounding API error: {e}", exc_info=True)
        return {
            "status": "error",
            "error_message": f"無法取得附近地點資訊: {str(e)[:100]}"
        }
