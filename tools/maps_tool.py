"""
ADK Tool: Google Maps Location Search

Provides location-based search using Google Maps Grounding via Vertex AI.
"""

import os
import json
import logging
from typing import Literal, Optional
from pydantic import BaseModel, Field


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


class RestaurantDetail(BaseModel):
    name: str = Field(description="餐廳名稱")
    address: str = Field(description="餐廳地址")
    rating: str = Field(description="Google 地圖評分（如 4.5）")
    reviews: list[str] = Field(description="此餐廳的 5 到 10 則熱門或最新用戶評論")


class RestaurantList(BaseModel):
    restaurants: list[RestaurantDetail]


def get_nearby_restaurants_for_batch(
    latitude: float,
    longitude: float,
    language_code: str = "zh-TW"
) -> dict:
    """
    Search for nearby restaurants and get details including reviews in JSON format
    for Batch API processing.
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

    query = """請幫我搜尋此座標附近的 3 家評價不錯的熱門餐廳，並擷取每家餐廳的 5 到 10 則最新用戶評論。
請務必以 JSON 格式返回，格式必須符合以下 JSON 結構：
{
  "restaurants": [
    {
      "name": "餐廳名稱",
      "address": "餐廳地址",
      "rating": "綜合評分",
      "reviews": [
        "評論內容1",
        "評論內容2"
      ]
    }
  ]
}
請直接輸出 JSON，不要包含任何額外的說明文字。"""

    logger.info(f"Retrieving nearby restaurants with reviews for batch at ({latitude}, {longitude}) using Vertex AI")

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

        # Parse JSON output robustly
        text = response.text.strip() if response.text else ""
        logger.info(f"get_nearby_restaurants_for_batch raw response text: {repr(text)}")
        
        if not text:
            # Diagnostics for empty response
            try:
                candidates_info = []
                if response.candidates:
                    for i, c in enumerate(response.candidates):
                        candidates_info.append(f"Candidate {i}: finish_reason={c.finish_reason}, safety_ratings={c.safety_ratings}")
                logger.error(f"Response text is empty. Candidates: {candidates_info}")
            except Exception as e_diag:
                logger.error(f"Failed to log diagnostics: {e_diag}")
            raise ValueError("Vertex AI returned an empty response. It might have been blocked or Maps grounding returned nothing.")
            
        # 1. Try regex to find content inside ```json ... ``` or ``` ... ```
        import re
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
        else:
            # 2. Fallback: find the first '{' and last '}'
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                text = text[start_idx:end_idx + 1].strip()

        try:
            result_json = json.loads(text)
        except Exception as json_err:
            logger.error(f"JSON parsing failed. Extracted text was: {repr(text)}")
            raise json_err

        return {
            "status": "success",
            "restaurants": result_json.get("restaurants", []),
            "coordinates": {
                "latitude": latitude,
                "longitude": longitude
            }
        }

    except Exception as e:
        logger.error(f"get_nearby_restaurants_for_batch error: {e}", exc_info=True)
        return {
            "status": "error",
            "error_message": f"搜尋餐廳與評論失敗: {str(e)[:100]}"
        }

