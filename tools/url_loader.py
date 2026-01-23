"""
ADK Tool: URL Content Loader

Provides intelligent URL content extraction with multiple fallback strategies.
Supports various websites including PTT, Medium, OpenAI, YouTube, and PDFs.
"""

import os
import re
import logging
from urllib.parse import urlparse, urlunparse
from typing import Optional

import httpx
import cloudscraper
from bs4 import BeautifulSoup
from markdownify import markdownify

logger = logging.getLogger(__name__)

# Import optional dependencies
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning("firecrawl package not installed")

# Import internal tools
from .youtube_tool import summarize_youtube_video
from .pdf_tool import load_pdf_content


def load_url_content(
    url: str,
    youtube_mode: str = "normal"
) -> dict:
    """
    Load and extract content from a URL with intelligent fallback strategy.

    This tool handles various URL types including web pages, YouTube videos,
    and PDFs. It uses multiple extraction methods with automatic fallback
    for maximum compatibility.

    Fallback priority:
    1. Domain-specific optimized loader (PTT, Medium, OpenAI, etc.)
    2. Firecrawl (if available)
    3. CloudScraper (for sites with anti-bot protection)
    4. SingleFile (browser-based rendering)
    5. Basic httpx (standard HTTP request)

    Args:
        url: The URL to load content from. Supports:
            - Regular web pages
            - YouTube videos (youtube.com, youtu.be)
            - PDF files
            - Social media (Twitter/X via fxtwitter proxy)
        youtube_mode: For YouTube URLs, the summarization mode:
            - "normal": Standard summary
            - "detail": Detailed analysis
            - "twitter": Social media format

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - content: The extracted text content (if successful)
            - url: The processed URL (may differ from input if proxied)
            - content_type: The type of content extracted (html, youtube, pdf)
            - error_message: Error description (if failed)
    """
    if not url:
        return {
            "status": "error",
            "error_message": "No URL provided"
        }

    # Apply domain replacements (Twitter → fxtwitter proxy)
    url = _replace_domain(url)

    # Check for YouTube
    if _is_youtube_url(url):
        result = summarize_youtube_video(url, mode=youtube_mode)
        if result["status"] == "success":
            return {
                "status": "success",
                "content": result["summary"],
                "url": url,
                "content_type": "youtube"
            }
        else:
            return {
                "status": "error",
                "error_message": result.get("error_message", "YouTube summarization failed"),
                "url": url
            }

    # Check for PDF
    if _is_pdf_url(url):
        result = load_pdf_content(url, is_url=True)
        if result["status"] == "success":
            return {
                "status": "success",
                "content": result["content"],
                "url": url,
                "content_type": "pdf",
                "page_count": result.get("page_count", 0)
            }
        else:
            return {
                "status": "error",
                "error_message": result.get("error_message", "PDF loading failed"),
                "url": url
            }

    # Handle Firecrawl-priority URLs (PTT, Medium, OpenAI)
    if _is_firecrawl_url(url):
        return _load_firecrawl_url(url)

    # Handle domain-specific URLs
    content = _load_domain_specific(url)
    if content:
        return {
            "status": "success",
            "content": content,
            "url": url,
            "content_type": "html"
        }

    # Default fallback chain
    return _load_with_fallback_chain(url)


def _replace_domain(url: str) -> str:
    """Replace certain domains with proxy alternatives"""
    replacements = {
        "twitter.com": "api.fxtwitter.com",
        "x.com": "api.fxtwitter.com",
    }

    parsed_url = urlparse(url)
    if parsed_url.netloc in replacements:
        new_netloc = replacements[parsed_url.netloc]
        fixed_url = parsed_url._replace(netloc=new_netloc)
        return urlunparse(fixed_url)

    return url


def _is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video"""
    return (
        url.startswith("https://www.youtube.com")
        or url.startswith("https://youtu.be")
        or url.startswith("https://m.youtube.com")
        or url.startswith("https://youtube.com")
    )


def _is_pdf_url(url: str) -> bool:
    """Check if URL points to a PDF file"""
    # Skip check for PTT URLs to avoid 403 errors
    if url.startswith("https://www.ptt.cc/bbs"):
        return False

    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        resp = httpx.head(url=url, headers=headers, follow_redirects=True, timeout=10.0)
        resp.raise_for_status()
        return resp.headers.get("content-type") == "application/pdf"
    except Exception as e:
        logger.warning(f"Error checking for PDF: {e}")
        return False


def _is_firecrawl_url(url: str) -> bool:
    """Check if URL should be processed using Firecrawl"""
    parsed_url = urlparse(url)

    return (
        url.startswith("https://www.ptt.cc/bbs")
        or url.startswith("https://medium.com")
        or parsed_url.netloc.endswith("medium.com")
        or url.startswith("https://openai.com")
    )


def _is_ptt_url(url: str) -> bool:
    """Check if URL is from PTT"""
    return url.startswith("https://www.ptt.cc/bbs")


def _load_firecrawl_url(url: str) -> dict:
    """Load URL that should prioritize Firecrawl"""
    logger.info(f"Handling URL with Firecrawl priority: {url}")

    # Try Firecrawl first if available
    if FIRECRAWL_AVAILABLE and os.environ.get('firecrawl_key'):
        try:
            content = _load_html_with_firecrawl(url)
            if content:
                return {
                    "status": "success",
                    "content": content,
                    "url": url,
                    "content_type": "html",
                    "method": "firecrawl"
                }
        except Exception as e:
            logger.warning(f"Firecrawl failed, falling back: {e}")

    # Domain-specific fallbacks
    if _is_ptt_url(url):
        fallback_methods = [
            ("cloudscraper", lambda: _load_html_with_cloudscraper(url)),
            ("httpx", lambda: _load_html_with_httpx(url)),
        ]
    elif url.startswith("https://openai.com"):
        fallback_methods = [
            ("httpx", lambda: _load_html_with_httpx(url)),
        ]
    elif "medium.com" in url:
        fallback_methods = [
            ("httpx", lambda: _load_html_with_httpx(url)),
            ("cloudscraper", lambda: _load_html_with_cloudscraper(url)),
        ]
    else:
        fallback_methods = [
            ("httpx", lambda: _load_html_with_httpx(url)),
            ("cloudscraper", lambda: _load_html_with_cloudscraper(url)),
        ]

    for method_name, method_func in fallback_methods:
        try:
            logger.info(f"Trying {method_name} for URL: {url}")
            content = method_func()
            if content:
                return {
                    "status": "success",
                    "content": content,
                    "url": url,
                    "content_type": "html",
                    "method": method_name
                }
        except Exception as e:
            logger.warning(f"{method_name} failed: {e}")
            continue

    return {
        "status": "error",
        "error_message": f"無法從網址讀取內容: {url}",
        "url": url
    }


def _load_domain_specific(url: str) -> Optional[str]:
    """Try domain-specific loaders"""
    httpx_domains = [
        "https://ncode.syosetu.com",
        "https://pubmed.ncbi.nlm.nih.gov",
        "https://www.bnext.com.tw",
        "https://github.com",
        "https://www.twreporter.org",
        "https://telegra.ph",
        "https://www.jiqizhixin.com",
    ]

    for domain in httpx_domains:
        if url.startswith(domain):
            try:
                return _load_html_with_httpx(url)
            except Exception as e:
                logger.warning(f"httpx failed for {domain}: {e}")
                return None

    cloudscraper_domains = [
        "https://blog.tripplus.cc",
    ]

    for domain in cloudscraper_domains:
        if url.startswith(domain):
            try:
                return _load_html_with_cloudscraper(url)
            except Exception as e:
                logger.warning(f"cloudscraper failed for {domain}: {e}")
                return None

    return None


def _load_with_fallback_chain(url: str) -> dict:
    """Load URL using default fallback chain"""
    logger.info(f"Using default fallback chain for: {url}")

    fallback_methods = [
        ("httpx", lambda: _load_html_with_httpx(url)),
        ("cloudscraper", lambda: _load_html_with_cloudscraper(url)),
    ]

    for method_name, method_func in fallback_methods:
        try:
            logger.info(f"Trying {method_name} for URL: {url}")
            content = method_func()
            if content:
                return {
                    "status": "success",
                    "content": content,
                    "url": url,
                    "content_type": "html",
                    "method": method_name
                }
        except Exception as e:
            logger.warning(f"{method_name} failed: {e}")
            continue

    return {
        "status": "error",
        "error_message": "無法從網址讀取內容，請確認網址是否正確或稍後再試",
        "url": url
    }


def _remove_base64_image(markdown_text: str) -> str:
    """Remove base64 encoded images from markdown"""
    pattern = r"!\[.*?\]\(data:image\/.*?;base64,.*?\)"
    return re.sub(pattern, "", markdown_text)


def _parse_html(html: str, markdown: bool = True) -> str:
    """Parse HTML and convert to markdown or plain text"""
    if markdown:
        text = markdownify(html)
        text = _remove_base64_image(text)
        return text

    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(strip=True)


def _load_html_with_httpx(url: str, markdown: bool = True) -> str:
    """Load HTML using httpx"""
    logger.info(f"Loading HTML with httpx: {url}")

    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Cookie": "over18=1",
    }

    resp = httpx.get(url=url, headers=headers, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()

    return _parse_html(resp.text, markdown=markdown)


def _load_html_with_cloudscraper(url: str, markdown: bool = True) -> str:
    """Load HTML using cloudscraper (for anti-bot protected sites)"""
    logger.info(f"Loading HTML with cloudscraper: {url}")

    scraper = cloudscraper.create_scraper()
    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Cookie": "over18=1",
    }

    resp = scraper.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    return _parse_html(resp.text, markdown=markdown)


def _load_html_with_firecrawl(url: str, markdown: bool = True) -> str:
    """Load HTML using Firecrawl API"""
    logger.info(f"Loading HTML with Firecrawl API: {url}")

    firecrawl_key = os.environ.get('firecrawl_key')
    if not firecrawl_key:
        raise ValueError("firecrawl_key environment variable not set")

    if not FIRECRAWL_AVAILABLE:
        raise ImportError("firecrawl package is not installed")

    parsed_url = urlparse(url)
    app = FirecrawlApp(api_key=firecrawl_key)

    params = {
        "formats": ["markdown"] if markdown else ["html"],
        "onlyMainContent": True,
        "removeBase64Images": True,
        "blockAds": True,
        "timeout": 30000,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    }

    # Site-specific customizations
    if url.startswith("https://www.ptt.cc/bbs"):
        params["headers"]["Cookie"] = "over18=1"
    elif parsed_url.netloc.endswith("medium.com"):
        params["headers"]["Cookie"] = "uid=lo_5f5a79a81615; sid=1:zKvtbbPVwGuLiOQjwgkt"
    elif url.startswith("https://openai.com"):
        params["headers"]["Cookie"] = "cookieConsent=true; OptanonAlertBoxClosed=true"

    result = app.scrape_url(url, params=params)

    if markdown and 'markdown' in result and result['markdown']:
        return result['markdown']
    elif 'html' in result and result['html']:
        return _parse_html(result['html'], markdown=markdown)
    else:
        raise ValueError("Firecrawl API did not return expected content format")
