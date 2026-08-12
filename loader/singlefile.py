import os
import tempfile
import asyncio
import re
from pathlib import Path
from bs4 import BeautifulSoup
import logging
from typing import Optional
from markdownify import markdownify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use system temp directory instead of hardcoded path
PERSISTENT_TEMP_DIR = tempfile.gettempdir()

# SingleFile 內部會啟動 headless Chromium，若卡住（例如頁面渲染卡死、
# Chromium 啟動失敗）子行程會永遠不回傳。這裡設定上限，逾時就 kill 掉，
# 避免整個 LINE webhook request 卡到 Cloud Run 的 request timeout 才 504。
DEFAULT_SINGLEFILE_TIMEOUT_SECONDS = 60


def get_singlefile_path_from_env() -> str:
    # 直接返回 'single-file'，因為它應該在 PATH 中
    return "single-file"


def remove_base64_image(markdown_text: str) -> str:
    pattern = r"!\[.*?\]\(data:image\/.*?;base64,.*?\)"
    cleaned_text = re.sub(pattern, "", markdown_text)
    return cleaned_text


async def singlefile_download(
    url: str,
    cookies_file: Optional[str] = None,
    timeout: float = DEFAULT_SINGLEFILE_TIMEOUT_SECONDS,
) -> str:
    logger.info("Downloading HTML by SingleFile: %s", url)

    if not os.path.exists(PERSISTENT_TEMP_DIR):
        os.makedirs(PERSISTENT_TEMP_DIR)

    filename = os.path.join(PERSISTENT_TEMP_DIR, os.path.basename(
        tempfile.mktemp(suffix=".html")))
    singlefile_path = get_singlefile_path_from_env()

    # 指定 Chromium 的可執行路徑
    chromium_path = "/usr/bin/chromium"

    cmds = [
        singlefile_path,
        "--browser-executable-path",
        chromium_path,
        "--filename-conflict-action",
        "overwrite",
        url,
        filename,
    ]

    if cookies_file is not None:
        if not Path(cookies_file).exists():
            raise FileNotFoundError("cookies file not found")

        cmds += [
            "--browser-cookies-file",
            cookies_file,
        ]

    process = await asyncio.create_subprocess_exec(
        *cmds, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        logger.error(
            "SingleFile timed out after %ss and was killed: %s", timeout, url
        )
        raise TimeoutError(f"SingleFile timed out after {timeout}s: {url}")

    if process.returncode != 0:
        logger.error("SingleFile failed with error: %s", stderr.decode())
        raise RuntimeError(f"SingleFile exited with code {process.returncode}")

    logger.info("SingleFile output: %s", stdout.decode())
    return filename


async def load_singlefile_html(url: str) -> str:
    f = await singlefile_download(url)

    # Check if SingleFile download was successful
    if not f or not os.path.exists(f):
        logger.error(f"SingleFile download failed or file not found: {f}")
        raise FileNotFoundError(f"Failed to download content from {url}")

    try:
        with open(f, "rb") as fp:
            soup = BeautifulSoup(fp, "html.parser")
            text = soup.get_text(strip=True)
        return text
    finally:
        # Always try to remove the temp file
        if os.path.exists(f):
            os.remove(f)


async def load_html_with_singlefile(url: str) -> str:
    try:
        content = await load_singlefile_html(url)
        text = markdownify(content)
        clean_text = remove_base64_image(text)
        return clean_text
    except Exception as e:
        # 重要：一定要往上 raise，讓 loader/url.py 的 fallback chain 接手換下一種
        # 抓取方式。過去這裡吞掉例外回傳 "error:..." 字串，會被誤判成爬取成功，
        # fallback 永遠不會被觸發。
        logger.error("SingleFile loading failed for %s: %s", url, e)
        raise
