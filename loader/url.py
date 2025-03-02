from urllib.parse import urlparse, urlunparse
import httpx
import logging
import os

from .html import (
    load_html_with_cloudscraper,
    load_html_with_httpx,
    load_html_with_firecrawl,
    FIRECRAWL_AVAILABLE
)
from .singlefile import load_html_with_singlefile
from .pdf import load_pdf
from .youtube_gcp import load_transcript_from_youtube

logger = logging.getLogger(__name__)


def is_ptt_url(url: str) -> bool:
    """Check if the URL is from PTT"""
    return url.startswith("https://www.ptt.cc/bbs")


def is_pdf_url(url: str) -> bool:
    """
    Check if URL points to a PDF.
    Skip check for PTT URLs to avoid 403 errors.
    """
    # Skip PDF check for PTT URLs
    if is_ptt_url(url):
        return False

    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",  # noqa
    }

    try:
        resp = httpx.head(url=url, headers=headers, follow_redirects=True)
        resp.raise_for_status()
        return resp.headers.get("content-type") == "application/pdf"
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error checking for PDF: {e}")
        return False


def is_youtube_url(url: str) -> bool:
    return (
        url.startswith("https://www.youtube.com")
        or url.startswith("https://youtu.be")
        or url.startswith("https://m.youtube.com")
        or url.startswith("https://youtube.com")
    )


def is_firecrawl_url(url: str) -> bool:
    """Check if the URL should be processed using Firecrawl"""
    return (url.startswith("https://www.ptt.cc/bbs") or
            url.startswith("https://medium.com") or
            url.startswith("https://openai.com"))


def replace_domain(url: str) -> str:
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


async def load_url(url: str) -> str:
    url = replace_domain(url)

    if is_youtube_url(url):
        return await load_transcript_from_youtube(url)

    # Handle URLs that should use Firecrawl
    if is_firecrawl_url(url):
        logger.info(f"Handling URL with Firecrawl: {url}")

        # Try Firecrawl first if available
        if FIRECRAWL_AVAILABLE and os.environ.get('firecrawl_key'):
            try:
                logger.info(f"Using Firecrawl for URL: {url}")
                return load_html_with_firecrawl(url)
            except Exception as e:
                logger.warning(f"Firecrawl failed, falling back: {e}")

        # For PTT, use cloudscraper as the first fallback
        if url.startswith("https://www.ptt.cc/bbs"):
            try:
                logger.info(f"Using cloudscraper for PTT URL: {url}")
                return load_html_with_cloudscraper(url)
            except Exception as e:
                logger.warning(
                    f"Cloudscraper failed for PTT, trying httpx: {e}")

            # Last resort for PTT - try httpx with proper cookies
            try:
                return load_html_with_httpx(url)
            except Exception as e:
                logger.error(f"All methods failed for PTT URL: {e}")
                raise

    # Handle non-Firecrawl URLs
    try:
        if is_pdf_url(url):
            return load_pdf(url)
    except Exception as e:
        logger.error(f"Error checking/loading PDF: {e}")

    # Domain-specific handling for other URLs
    httpx_domains = [
        "https://ncode.syosetu.com",
        "https://pubmed.ncbi.nlm.nih.gov",
        "https://www.bnext.com.tw",
        "https://github.com",
        "https://www.twreporter.org",
        "https://telegra.ph",
    ]
    for domain in httpx_domains:
        if url.startswith(domain):
            return load_html_with_httpx(url)

    cloudscraper_domains = [
        "https://blog.tripplus.cc",
    ]
    for domain in cloudscraper_domains:
        if url.startswith(domain):
            return load_html_with_cloudscraper(url)

    # Default to singlefile for complex sites
    text = await load_html_with_singlefile(url)
    return text
