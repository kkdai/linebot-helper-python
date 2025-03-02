import asyncio
import os
import re
import tempfile
from pathlib import Path

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

    try:
        # Initialize the Firecrawl app with API key
        app = FirecrawlApp(api_key=firecrawl_key)

        # Set parameters - for PTT we need "over18=1" cookie
        params = {
            'formats': ['markdown'] if markdown else ['html'],
            'custom_headers': {
                'Cookie': 'over18=1',  # For PTT age verification
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
            },
            'timeout': 60000,  # Longer timeout (60s) for PTT
            'wait_until': 'networkidle2'  # Wait until network is idle
        }

        # Make the request
        result = app.scrape_url(url, params=params)

        # If we requested markdown and it's available, use it directly
        if markdown and 'markdown' in result and result['markdown']:
            return result['markdown']

        # Otherwise parse the HTML content
        elif 'html' in result and result['html']:
            return parse_html(result['html'], markdown=markdown)
        else:
            raise ValueError(
                f"Firecrawl API did not return expected content format")
    except Exception as e:
        logger.error(f"Error using Firecrawl API: {e}")
        raise


def load_html_file(f: str) -> str:
    with open(f, encoding="utf-8") as fp:
        return parse_html(fp.read())
