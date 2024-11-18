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

PERSISTENT_TEMP_DIR = "/path/to/persistent/temp/dir"


def get_singlefile_path_from_env() -> str:
    # 直接返回 'single-file'，因為它應該在 PATH 中
    return "single-file"


def remove_base64_image(markdown_text: str) -> str:
    pattern = r"!\[.*?\]\(data:image\/.*?;base64,.*?\)"
    cleaned_text = re.sub(pattern, "", markdown_text)
    return cleaned_text


async def singlefile_download(url: str, cookies_file: Optional[str] = None) -> str:
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

    try:
        process = await asyncio.create_subprocess_exec(
            *cmds, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error("SingleFile failed with error: %s", stderr.decode())
            return ""

        logger.info("SingleFile output: %s", stdout.decode())
        return filename
    except Exception as e:
        logger.error("Failed to execute SingleFile: %s", e)
        return ""


async def load_singlefile_html(url: str) -> str:
    f = await singlefile_download(url)

    with open(f, "rb") as fp:
        soup = BeautifulSoup(fp, "html.parser")
        text = soup.get_text(strip=True)
    os.remove(f)
    return text


async def load_html_with_singlefile(url: str) -> str:
    try:
        content = await load_singlefile_html(url)
        text = markdownify(content)
        clean_text = remove_base64_image(text)
        return clean_text
    except Exception as e:
        logger.error("An error occurred: %s", str(e))
        return "error:" + str(e)
