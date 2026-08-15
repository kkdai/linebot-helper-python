import asyncio
from urllib.parse import urlparse, urlunparse
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
from .document import detect_document_format, load_document
from .youtube_gcp import load_transcript_from_youtube

logger = logging.getLogger(__name__)

# 每種抓取方法的時間預算（秒）。任何一種方法卡住都不能拖垮整個 webhook request，
# 逾時就立刻換 fallback chain 的下一種方法。
DEFAULT_LOADER_TIMEOUT = 30.0
LOADER_TIMEOUTS = {
    "singlefile": 60.0,   # 要啟動 headless Chromium，給最長
    "httpx": 20.0,
    "cloudscraper": 30.0,
    "document": 60.0,     # 下載文件 + anydoc 轉換
}


async def _call_loader(method_name: str, method_func) -> str:
    """以統一的時間預算執行單一抓取方法。

    同步 loader（httpx/cloudscraper）丟進 thread 執行，一方面不會卡住
    event loop，一方面才能套 asyncio.wait_for。逾時時 thread 本身不會被
    中斷，但呼叫端會立即放棄並換下一種方法。
    """
    timeout = LOADER_TIMEOUTS.get(method_name, DEFAULT_LOADER_TIMEOUT)
    if method_name == "singlefile":
        return await asyncio.wait_for(method_func(), timeout=timeout)
    return await asyncio.wait_for(asyncio.to_thread(method_func), timeout=timeout)


async def _try_fallback_chain(url: str, methods, error_message: str) -> str:
    """依序嘗試 methods，每種方法各自有時間預算，全數失敗才丟例外。"""
    for method_name, method_func in methods:
        try:
            logger.info(f"Trying {method_name} for URL: {url}")
            return await _call_loader(method_name, method_func)
        except asyncio.TimeoutError:
            logger.warning(
                f"{method_name} timed out after "
                f"{LOADER_TIMEOUTS.get(method_name, DEFAULT_LOADER_TIMEOUT)}s for {url}")
        except Exception as e:
            logger.warning(f"{method_name} failed for {url}: {e}")

    logger.error(f"All methods failed for URL: {url}")
    raise Exception(error_message)


def is_ptt_url(url: str) -> bool:
    """Check if the URL is from PTT"""
    return url.startswith("https://www.ptt.cc/bbs")


def is_youtube_url(url: str) -> bool:
    return (
        url.startswith("https://www.youtube.com")
        or url.startswith("https://youtu.be")
        or url.startswith("https://m.youtube.com")
        or url.startswith("https://youtube.com")
    )


def is_firecrawl_url(url: str) -> bool:
    """Check if the URL should be processed using Firecrawl"""
    parsed_url = urlparse(url)

    return (url.startswith("https://www.ptt.cc/bbs") or
            url.startswith("https://medium.com") or
            parsed_url.netloc.endswith("medium.com") or
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


async def load_url(url: str, youtube_mode: str = "normal") -> str:
    """
    Load content from URL with intelligent fallback strategy

    Fallback priority:
    1. Domain-specific optimized loader
    2. Documents (Word/PowerPoint/Excel/OpenDocument/RTF/EPUB/CSV/PDF) via anydoc
    3. Firecrawl (if available)
    4. CloudScraper
    5. SingleFile
    6. Basic httpx

    Args:
        url: URL to load
        youtube_mode: Summary mode for YouTube videos - "normal", "detail", or "twitter"

    Returns:
        Extracted text content

    Raises:
        Exception: If all methods fail
    """
    url = replace_domain(url)

    if is_youtube_url(url):
        return await load_transcript_from_youtube(url, mode=youtube_mode)

    # Handle URLs that should use Firecrawl
    if is_firecrawl_url(url):
        logger.info(f"Handling URL with Firecrawl priority: {url}")

        # Try Firecrawl first if available
        if FIRECRAWL_AVAILABLE and os.environ.get('firecrawl_key'):
            try:
                logger.info(f"Using Firecrawl for URL: {url}")
                return load_html_with_firecrawl(url)
            except Exception as e:
                logger.warning(f"Firecrawl failed, falling back: {e}")

        # For PTT, use cloudscraper as the first fallback
        if url.startswith("https://www.ptt.cc/bbs"):
            return await _try_fallback_chain(url, [
                ("cloudscraper", lambda: load_html_with_cloudscraper(url)),
                ("httpx", lambda: load_html_with_httpx(url)),
                ("singlefile", lambda: load_html_with_singlefile(url)),
            ], "無法從 PTT 讀取內容，請稍後再試")

        # For OpenAI, try SingleFile then httpx as fallback
        elif url.startswith("https://openai.com"):
            return await _try_fallback_chain(url, [
                ("singlefile", lambda: load_html_with_singlefile(url)),
                ("httpx", lambda: load_html_with_httpx(url)),
            ], "無法從 OpenAI 讀取內容，請稍後再試")

        # For Medium, try multiple fallbacks
        elif "medium.com" in url:
            return await _try_fallback_chain(url, [
                ("httpx", lambda: load_html_with_httpx(url)),
                ("cloudscraper", lambda: load_html_with_cloudscraper(url)),
                ("singlefile", lambda: load_html_with_singlefile(url)),
            ], "無法從 Medium 讀取內容，請稍後再試")

    # 文件連結（Word/PowerPoint/Excel/OpenDocument/RTF/EPUB/CSV/PDF）
    # 用 anydoc 轉成 Markdown；PDF 轉換失敗時 fallback 到 pypdf
    doc_format = await asyncio.to_thread(detect_document_format, url)
    if doc_format:
        doc_timeout = LOADER_TIMEOUTS.get("document", DEFAULT_LOADER_TIMEOUT)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(load_document, url, doc_format),
                timeout=doc_timeout)
        except Exception as e:
            logger.warning(f"anydoc failed for {url} ({doc_format}): {e}")
            if doc_format == "pdf":
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(load_pdf, url), timeout=doc_timeout)
                except Exception as e2:
                    logger.error(f"pypdf fallback failed for {url}: {e2}")
            raise Exception("無法讀取文件內容，請確認網址是否正確或稍後再試")

    # Domain-specific handling for other URLs with retry
    httpx_domains = [
        "https://ncode.syosetu.com",
        "https://pubmed.ncbi.nlm.nih.gov",
        "https://www.bnext.com.tw",
        "https://github.com",
        "https://www.twreporter.org",
        "https://telegra.ph",
        "https://www.jiqizhixin.com",  # 機器之心
    ]
    for domain in httpx_domains:
        if url.startswith(domain):
            return await _try_fallback_chain(url, [
                ("httpx", lambda: load_html_with_httpx(url)),
                ("singlefile", lambda: load_html_with_singlefile(url)),
            ], "無法從網址讀取內容，請確認網址是否正確或稍後再試")

    cloudscraper_domains = [
        "https://blog.tripplus.cc",
    ]
    for domain in cloudscraper_domains:
        if url.startswith(domain):
            return await _try_fallback_chain(url, [
                ("cloudscraper", lambda: load_html_with_cloudscraper(url)),
                ("singlefile", lambda: load_html_with_singlefile(url)),
            ], "無法從網址讀取內容，請確認網址是否正確或稍後再試")

    # Default fallback chain for unknown domains
    logger.info(f"Using default fallback chain for: {url}")
    return await _try_fallback_chain(url, [
        ("singlefile", lambda: load_html_with_singlefile(url)),
        ("httpx", lambda: load_html_with_httpx(url)),
        ("cloudscraper", lambda: load_html_with_cloudscraper(url)),
    ], "無法從網址讀取內容，請確認網址是否正確或稍後再試")
