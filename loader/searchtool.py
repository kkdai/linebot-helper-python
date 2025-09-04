import requests
import google.generativeai as genai
import os
import logging

logger = logging.getLogger(__name__)


def extract_keywords_with_gemini(text, gemini_api_key, num_keywords=5):
    """
    使用 Gemini API 從文字中提取關鍵字。

    :param text: 使用者輸入的文字
    :param gemini_api_key: Gemini API 的 API 金鑰
    :param num_keywords: 要提取的關鍵字數量，預設為 5
    :return: 提取的關鍵字列表
    """
    try:
        # 設定 API 金鑰
        current_key = genai.get_api_key()

        # Only configure if needed (prevent reconfiguring when already set correctly)
        if current_key != gemini_api_key:
            genai.configure(api_key=gemini_api_key)

        # 建立 Gemini 模型
        model = genai.GenerativeModel("gemini-2.0-flash-lite")

        # 準備提示詞，要求模型提取關鍵字
        prompt = f"""從以下文字中提取 {num_keywords} 個最重要的關鍵字或短語，只需返回關鍵字列表，不要有額外文字：

{text}

關鍵字："""

        # 生成回應
        response = model.generate_content(prompt)

        # 處理回應，將文字分割成關鍵字列表
        if response.text:
            # 清理結果，移除數字、破折號和多餘空白
            keywords_text = response.text.strip()
            # 分割文字得到關鍵字列表
            keywords = [kw.strip() for kw in keywords_text.split("\n")]
            # 移除可能的數字前綴、破折號或其他標點符號
            keywords = [kw.strip("0123456789. -\"'") for kw in keywords]
            # 移除空項
            keywords = [kw for kw in keywords if kw]
            return keywords[:num_keywords]  # 確保只返回指定數量的關鍵字
        return []
    except Exception as e:
        logger.error(f"Gemini API 提取關鍵字失敗：{e}")
        # If direct text contains useful terms, use it directly
        if len(text) < 100:  # If the text is short, it might be a good search query already
            return [text]
        return []


def search_with_google_custom_search(keywords, search_api_key, cx, num_results=10):
    """
    使用 Google Custom Search API 根據關鍵字進行搜尋。

    :param keywords: 關鍵字列表
    :param search_api_key: Google Custom Search API 的 API 金鑰
    :param cx: 搜尋引擎 ID
    :param num_results: 要返回的搜尋結果數量，預設為 10
    :return: 搜尋結果列表，每個結果包含標題、連結和摘要
    """
    query = " ".join(keywords)  # 將關鍵字組合成搜尋查詢
    url = f"https://www.googleapis.com/customsearch/v1?key={search_api_key}&cx={cx}&q={query}&num={num_results}"

    try:
        logger.info(f"Searching for: {query}")
        response = requests.get(url)
        response.raise_for_status()  # 如果請求失敗，拋出異常
        result_data = response.json()

        # Check if there are search results
        if "items" not in result_data:
            logger.warning(f"No search results for query: {query}")
            return []

        results = result_data.get("items", [])
        formatted_results = []
        for item in results:
            formatted_results.append(
                {
                    "title": item.get("title", "No title"),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", "No description available"),
                }
            )
        return formatted_results
    except requests.exceptions.RequestException as e:
        logger.error(f"Google Custom Search API 請求失敗：{e}")
        return []


def search_from_text(
    text, gemini_api_key, search_api_key, cx, num_keywords=5, num_results=10
):
    """
    從文字中提取關鍵字並使用 Google Custom Search API 進行搜尋。

    :param text: 使用者輸入的文字
    :param gemini_api_key: Gemini API 的 API 金鑰
    :param search_api_key: Google Custom Search API 的 API 金鑰
    :param cx: 搜尋引擎 ID
    :param num_keywords: 要提取的關鍵字數量，預設為 5
    :param num_results: 要返回的搜尋結果數量，預設為 10
    :return: 搜尋結果列表
    """
    # Short direct queries can be used directly
    if len(text.split()) <= 10:
        logger.info(f"Using direct text as search query: {text}")
        return search_with_google_custom_search([text], search_api_key, cx, num_results)

    # For longer text, use Gemini API to extract keywords
    keywords = extract_keywords_with_gemini(text, gemini_api_key, num_keywords)

    if not keywords:
        logger.warning("無法提取關鍵字，使用原始文本進行搜索。")
        # Truncate very long texts
        words = text.split()[:15]  # Limit to first 15 words
        search_text = " ".join(words)
        return search_with_google_custom_search([search_text], search_api_key, cx, num_results)

    # 使用 Google Custom Search API 進行搜尋
    logger.info(f"Extracted keywords for search: {keywords}")
    results = search_with_google_custom_search(
        keywords, search_api_key, cx, num_results
    )
    return results
