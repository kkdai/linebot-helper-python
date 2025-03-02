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


def is_pdf_url(url: str) -> bool:
    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",  # noqa
    }

    resp = httpx.head(url=url, headers=headers, follow_redirects=True)
    resp.raise_for_status()
    return resp.headers.get("content-type") == "application/pdf"


def is_youtube_url(url: str) -> bool:
    return (
        url.startswith("https://www.youtube.com")
        or url.startswith("https://youtu.be")
        or url.startswith("https://m.youtube.com")
        or url.startswith("https://youtube.com")
    )


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

    try:
        if is_pdf_url(url):
            return load_pdf(url)
    except httpx.HTTPStatusError as e:
        logger.error("Unable to load PDF: {} ({})", url, e)

    # Special case for PTT using Firecrawl
    if url.startswith("https://www.ptt.cc/bbs") and FIRECRAWL_AVAILABLE:
        firecrawl_key = os.environ.get('firecrawl_key')
        if firecrawl_key:
            try:
                logger.info(f"Using Firecrawl for PTT URL: {url}")
                return load_html_with_firecrawl(url)
            except Exception as e:
                logger.error(f"Error using Firecrawl for PTT: {e}")
                # Fall back to standard methods

    # Continue with existing domain-specific handling
    httpx_domains = [
        "https://www.ptt.cc/bbs",  # Keep this as fallback if Firecrawl fails
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

    text = await load_html_with_singlefile(url)
    return text
