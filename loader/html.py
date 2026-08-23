import asyncio
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse
import cloudscraper
import httpx
from bs4 import BeautifulSoup
import logging
from markdownify import markdownify

logger = logging.getLogger(__name__)

# Import the FirecrawlApp if available
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning(
        "firecrawl package not installed - PTT pages will use alternative methods")


def remove_base64_image(markdown_text: str) -> str:
    pattern = r"!\[.*?\]\(data:image\/.*?;base64,.*?\)"
    cleaned_text = re.sub(pattern, "", markdown_text)
    return cleaned_text


# Cloudflare／WAF 人機驗證頁的常見特徵字串。singlefile 用 headless Chromium
# 渲染頁面，不像 httpx/cloudscraper 會對 4xx/5xx 呼叫 raise_for_status()，
# 抓到驗證頁也會當成「抓取成功」回傳——這裡專門攔這種情況，抓到就要當失敗，
# 讓 loader/url.py 的 fallback chain 換下一種方法，不能把驗證頁內容送去給 Gemini。
CHALLENGE_PAGE_MARKERS = (
    "Attention Required! | Cloudflare",
    "Just a moment...",
    "Checking your browser before accessing",
    "cf-browser-verification",
    "Enable JavaScript and cookies to continue",
    "DDoS protection by Cloudflare",
)


def is_challenge_page(text: str) -> bool:
    """抓回來的內容是否為 Cloudflare／WAF 人機驗證頁而非真正網頁內容。"""
    return any(marker in text for marker in CHALLENGE_PAGE_MARKERS)


def parse_html(html: str | bytes, markdown: bool = True, encoding: str = "utf-8") -> str:
    if isinstance(html, bytes):
        html = html.decode(encoding)

    if markdown:
        text = markdownify(html)
        text = remove_base64_image(text)
        return text

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(strip=True)
    return text


async def save_html_with_singlefile(url: str, cookies_file: str | None = None) -> str:
    logger.info("Downloading HTML by SingleFile: {}", url)

    filename = tempfile.mktemp(suffix=".html")

    singlefile_path = os.getenv(
        "SINGLEFILE_PATH", "/Users/narumi/.local/bin/single-file")

    cmds = [singlefile_path]

    if cookies_file is not None:
        if not Path(cookies_file).exists():
            raise FileNotFoundError("cookies file not found")

        cmds += [
            "--browser-cookies-file",
            cookies_file,
        ]

    cmds += [
        "--filename-conflict-action",
        "overwrite",
        url,
        filename,
    ]

    process = await asyncio.create_subprocess_exec(*cmds)
    await process.communicate()

    return filename


async def load_html_with_singlefile(url: str, markdown: bool = True) -> str:
    f = await save_html_with_singlefile(url)

    with open(f, encoding="utf-8") as fp:
        return parse_html(fp.read(), markdown=markdown)


def load_html_with_httpx(url: str, markdown: bool = True) -> str:
    logger.info(f"Loading HTML with httpx: {url}")

    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Cookie": "over18=1",  # PTT age verification
    }

    resp = httpx.get(url=url, headers=headers, follow_redirects=True)
    resp.raise_for_status()

    # 部分驗證頁特徵（如 cf-browser-verification）只出現在 HTML 屬性裡，
    # markdownify/get_text 抓不到，所以要在轉換前先檢查原始 HTML
    if is_challenge_page(resp.text):
        raise RuntimeError(f"httpx got a bot-challenge page instead of real content: {url}")
    return parse_html(resp.text, markdown=markdown)


def load_html_with_cloudscraper(url: str, markdown: bool = True) -> str:
    logger.info(f"Loading HTML with cloudscraper: {url}")

    scraper = cloudscraper.create_scraper()
    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Cookie": "over18=1",  # Important for PTT age verification
    }

    resp = scraper.get(url, headers=headers)
    resp.raise_for_status()

    if is_challenge_page(resp.text):
        raise RuntimeError(f"cloudscraper got a bot-challenge page instead of real content: {url}")
    return parse_html(resp.text, markdown=markdown)


def load_html_with_firecrawl(url: str, markdown: bool = True) -> str:
    """
    Load HTML using the Firecrawl API service via the firecrawl package.

    Args:
        url: The URL to crawl
        markdown: Whether to convert HTML to markdown

    Returns:
        The parsed HTML content as text or markdown
    """
    logger.info(f"Loading HTML with Firecrawl API: {url}")

    firecrawl_key = os.environ.get('firecrawl_key')
    if not firecrawl_key:
        raise ValueError("firecrawl_key environment variable not set")

    if not FIRECRAWL_AVAILABLE:
        raise ImportError(
            "firecrawl package is not installed. Install with 'pip install firecrawl'")

    parsed_url = urlparse(url)

    try:
        # Initialize the Firecrawl app with API key
        app = FirecrawlApp(api_key=firecrawl_key)

        # Base parameters for all sites
        params = {
            "url": url,  # This is redundant as we also pass url directly to scrape_url, but included for completeness
            "formats": ["markdown"] if markdown else ["html"],
            "onlyMainContent": True,  # Extract main content only
            "removeBase64Images": True,  # Remove base64 images to reduce response size
            "blockAds": True,  # Block ads
            "timeout": 30000,  # Default timeout in milliseconds
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }

        # Site-specific customizations
        if url.startswith("https://www.ptt.cc/bbs"):
            # PTT requires over18 cookie
            params["headers"]["Cookie"] = "over18=1"
            # PTT specific actions
            params["actions"] = [
                {
                    "type": "wait",
                    "selector": ".bbs-screen"  # Wait for main content
                }
            ]

        # Handle any Medium domain (including subdomains)
        elif parsed_url.netloc.endswith("medium.com"):
            # Medium has paywalls and special content
            params["headers"]["Cookie"] = "uid=lo_5f5a79a81615; sid=1:zKvtbbPVwGuLiOQjwgkt"
            # Medium specific actions to handle dynamic loading
            # params["actions"] = [
            #     {
            #         "type": "wait",
            #         "selector": "article, [data-test-id='post-content']",
            #         "milliseconds": 2000
            #     }
            # ]
            # params["timeout"] = 60000  # Longer timeout for Medium

        elif url.startswith("https://openai.com"):
            # OpenAI requires JavaScript and cookies
            params["headers"]["Cookie"] = "cookieConsent=true; OptanonAlertBoxClosed=true"
            # params["actions"] = [
            #     {
            #         "type": "wait",
            #         "selector": "main, article, .content, h1",
            #         "milliseconds": 5000
            #     }
            # ]
            # # Set location for better access
            # params["location"] = {
            #     "country": "US",
            #     "languages": ["en-US"]
            # }
            # params["timeout"] = 60000  # Longer timeout for OpenAI

        # Make the request
        result = app.scrape_url(url, params=params)

        # If we requested markdown and it's available, use it directly
        if markdown and 'markdown' in result and result['markdown']:
            markdown_content = result['markdown']
            # Check if we got a message about enabling JavaScript/cookies
            if "enable javascript" in markdown_content.lower() or "enable cookies" in markdown_content.lower():
                logger.warning(
                    "JavaScript/Cookie warning detected in response. Trying alternative approach...")

                # Fall back to single file approach for OpenAI
                if url.startswith("https://openai.com"):
                    from .singlefile import load_html_with_singlefile
                    return load_html_with_singlefile(url)

            return markdown_content

        # Otherwise parse the HTML content
        elif 'html' in result and result['html']:
            html_content = result['html']
            # Check if we got a message about enabling JavaScript/cookies
            if "enable javascript" in html_content.lower() or "enable cookies" in html_content.lower():
                logger.warning(
                    "JavaScript/Cookie warning detected in response. Trying alternative approach...")

                # Fall back to single file approach for OpenAI
                if url.startswith("https://openai.com"):
                    from .singlefile import load_html_with_singlefile
                    return load_html_with_singlefile(url)

            return parse_html(html_content, markdown=markdown)
        else:
            raise ValueError(
                "Firecrawl API did not return expected content format")
    except Exception as e:
        logger.error(f"Error using Firecrawl API: {e}")
        raise


def load_html_file(f: str) -> str:
    with open(f, encoding="utf-8") as fp:
        return parse_html(fp.read())
