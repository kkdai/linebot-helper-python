# Pure Vertex AI implementation - no LangChain
import os
import logging
from datetime import datetime, timedelta, timezone
import requests

# Use google-genai SDK for Vertex AI
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

logger = logging.getLogger(__name__)


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


def _fetch_github_issues(repo: str, access_token: str = None, since: str = None) -> list:
    """
    Fetch GitHub issues using GitHub API directly (no LangChain)

    Args:
        repo: Repository in format "owner/repo"
        access_token: GitHub access token
        since: ISO 8601 timestamp to fetch issues since

    Returns:
        List of issues as dictionaries
    """
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }

    if access_token:
        headers["Authorization"] = f"token {access_token}"

    params = {
        "state": "all",
        "per_page": 100,
    }

    if since:
        params["since"] = since

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        issues = response.json()

        # Filter out pull requests (they appear in issues API)
        issues = [issue for issue in issues if 'pull_request' not in issue]

        logger.info(f"Fetched {len(issues)} issues from {repo}")
        return issues

    except Exception as e:
        logger.error(f"Error fetching GitHub issues: {e}")
        return []


def _format_issues_for_summary(issues: list) -> str:
    """Format GitHub issues into text for summarization"""
    if not issues:
        return "沒有找到任何 GitHub issues"

    formatted = []
    for issue in issues:
        title = issue.get('title', 'No title')
        body = issue.get('body', 'No description')
        url = issue.get('html_url', '')
        labels = [label['name'] for label in issue.get('labels', [])]

        formatted.append(f"""
標題: {title}
URL: {url}
標籤: {', '.join(labels) if labels else 'None'}
內容: {body[:500]}...
---
""")

    return "\n".join(formatted)


def summarized_yesterday_github_issues() -> str:
    """
    Fetch and summarize GitHub issues from yesterday using pure Vertex AI (no LangChain)

    Returns:
        Summarized text of GitHub issues
    """
    GH_ACCESS_TOKEN = os.getenv("GITHUB_TOKEN")

    total_github_issues = 0
    past_days = 1
    issues = []

    # 擷取至少五個 issues
    while total_github_issues <= 5 and past_days < 30:  # Max 30 days lookback
        since_day = (datetime.now(timezone.utc) - timedelta(days=past_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        issues = _fetch_github_issues(
            repo="kkdai/bookmarks",
            access_token=GH_ACCESS_TOKEN,
            since=since_day
        )

        total_github_issues = len(issues)
        print(f"總共有: {len(issues)} 筆資料 (past {past_days} days)")
        past_days += 1

    if not issues:
        return "最近沒有新的 GitHub issues"

    # Format issues into text
    issues_text = _format_issues_for_summary(issues)

    # Create prompt
    prompt = f"""這些資料是我昨天搜集的文章，我想要總結這些資料，請幫我總結一下。 寫成一篇短文來分享我昨天有學到哪些內容，
幫我在每一段最後加上原有的 URL 連結(url 不要使用 markdown, 直接給 url)，這樣我可以隨時回去查看原文。
請去除掉所有的 tags, links, 和其他不必要的資訊，只保留文章的主要內容，我的角色是 Evan ，喜歡 LLM 跟 AI 相關的技術。:

{issues_text}

請用繁體中文總結以上內容。
"""

    try:
        client = _get_vertex_client()

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=2048,
            )
        )

        return response.text if response.text else "無法生成摘要"

    except Exception as e:
        logger.error(f"Error summarizing GitHub issues: {e}")
        return f"摘要 GitHub issues 時發生錯誤: {str(e)}"
