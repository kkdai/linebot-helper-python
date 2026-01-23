"""
ADK Tool: PDF Content Extraction

Provides PDF content extraction from URLs or file paths.
"""

import os
import tempfile
import logging

import httpx
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def load_pdf_content(
    source: str,
    is_url: bool = True
) -> dict:
    """
    Extract text content from a PDF file.

    This tool extracts text from PDF documents, either from a URL or
    a local file path. Useful for summarizing PDF documents.

    Args:
        source: The PDF source - either a URL or a local file path.
        is_url: If True (default), treats source as a URL and downloads the PDF.
                If False, treats source as a local file path.

    Returns:
        dict: A dictionary containing:
            - status: "success" or "error"
            - content: The extracted text content (if successful)
            - page_count: Number of pages processed
            - source: The original source path/URL
            - error_message: Error description (if failed)
    """
    if not source:
        return {
            "status": "error",
            "error_message": "No PDF source provided"
        }

    try:
        if is_url:
            # Download PDF from URL
            pdf_path = _download_pdf(source)
            if not pdf_path:
                return {
                    "status": "error",
                    "error_message": f"Failed to download PDF from: {source}"
                }
            cleanup_file = True
        else:
            # Use local file path
            if not os.path.exists(source):
                return {
                    "status": "error",
                    "error_message": f"PDF file not found: {source}"
                }
            pdf_path = source
            cleanup_file = False

        # Extract text from PDF
        text_content, page_count = _extract_text_from_pdf(pdf_path)

        # Cleanup downloaded file
        if cleanup_file and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file: {e}")

        if text_content:
            return {
                "status": "success",
                "content": text_content,
                "page_count": page_count,
                "source": source
            }
        else:
            return {
                "status": "error",
                "error_message": "No text content extracted from PDF"
            }

    except Exception as e:
        logger.error(f"Error loading PDF: {e}", exc_info=True)
        return {
            "status": "error",
            "error_message": f"PDF extraction failed: {str(e)[:100]}"
        }


def _download_pdf(url: str) -> str:
    """Download PDF from URL and return temp file path"""
    logger.info(f"Downloading PDF: {url}")

    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Cookie": "over18=1",
    }

    try:
        resp = httpx.get(url=url, headers=headers, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()

        suffix = ".pdf" if resp.headers.get("content-type") == "application/pdf" else None

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fp:
            fp.write(resp.content)
            return fp.name

    except Exception as e:
        logger.error(f"Error downloading PDF: {e}")
        return ""


def _extract_text_from_pdf(pdf_path: str) -> tuple[str, int]:
    """Extract text from PDF file using pypdf"""
    try:
        reader = PdfReader(pdf_path)
        text_content = []

        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                text_content.append(text.strip())

        page_count = len(reader.pages)
        logger.info(f"Extracted text from {page_count} pages")

        return "\n\n".join(text_content), page_count

    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise
