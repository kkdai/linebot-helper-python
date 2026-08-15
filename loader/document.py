"""文件連結轉 Markdown（Word/PowerPoint/Excel/OpenDocument/RTF/EPUB/CSV/PDF）。

用 firecrawl/anydoc 在本地轉換，不需要外部服務。anydoc 沒安裝時
ANYDOC_AVAILABLE 為 False，呼叫端（loader/url.py）會讓 PDF 走 pypdf。
"""
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

try:
    import anydoc
    ANYDOC_AVAILABLE = True
except ImportError:
    anydoc = None
    ANYDOC_AVAILABLE = False
    logger.warning(
        "anydoc package not installed - document links will fall back to pypdf/HTML")

HEAD_REQUEST_TIMEOUT = 10.0
DOWNLOAD_TIMEOUT = 30.0

REQUEST_HEADERS = {
    "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",  # noqa
}

# anydoc 支援的格式，副檔名即 format 名稱
EXTENSION_FORMATS = {
    "doc", "docx", "docm", "ppt", "pptx", "pptm",
    "xls", "xlsx", "xlsm", "odt", "ods", "odp",
    "rtf", "epub", "csv", "pdf",
}

CONTENT_TYPE_FORMATS = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-word.document.macroenabled.12": "docm",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint.presentation.macroenabled.12": "pptm",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.12": "xlsm",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "application/epub+zip": "epub",
    "text/csv": "csv",
}


def detect_document_format(url: str) -> str | None:
    """判斷 URL 是否指向文件，回傳 anydoc format 名稱或 None。

    副檔名就能認出文件時直接回傳，省下一次 HEAD request。認不出來
    （沒副檔名，或像 download.php 這種動態網址）才發 HEAD 看 content-type。
    PTT 對 HEAD 會回 403，維持既有行為直接跳過。
    """
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in EXTENSION_FORMATS:
            return ext

    if url.startswith("https://www.ptt.cc/bbs"):
        return None

    try:
        resp = httpx.head(url=url, headers=REQUEST_HEADERS,
                          follow_redirects=True, timeout=HEAD_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        # timeout、連線失敗等：當作非文件，繼續走一般 HTML 流程
        logger.warning(f"HEAD request failed checking document type: {e}")
        return None

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    return CONTENT_TYPE_FORMATS.get(content_type)


def load_document(url: str, doc_format: str | None = None) -> str:
    """下載文件並用 anydoc 轉成 Markdown。"""
    if not ANYDOC_AVAILABLE:
        raise RuntimeError("anydoc package is not installed")

    logger.info(f"Loading document ({doc_format}): {url}")

    resp = httpx.get(url=url, headers=REQUEST_HEADERS,
                     follow_redirects=True, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    try:
        markdown = anydoc.to_markdown_bytes(resp.content, doc_format)
    except Exception:
        # format 提示錯誤時（例如副檔名跟實際內容不符）改用內容自動偵測
        markdown = anydoc.to_markdown_bytes(resp.content)

    logger.info(f"Converted document to {len(markdown)} chars of markdown")
    return markdown
