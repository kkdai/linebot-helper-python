# Pure pypdf implementation - no LangChain
import tempfile
import httpx
import logging
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def load_pdf(url: str) -> str:
    """
    Load PDF from URL and extract text using pypdf (no LangChain)

    Args:
        url: URL of the PDF file

    Returns:
        Extracted text from PDF
    """
    logger.info(f"Loading PDF: {url}")

    headers = {
        "Accept-Language": "zh-TW,zh;q=0.9,ja;q=0.8,en-US;q=0.7,en;q=0.6",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Cookie": "over18=1",  # ptt
    }

    resp = httpx.get(url=url, headers=headers, follow_redirects=True)
    resp.raise_for_status()

    suffix = ".pdf" if resp.headers.get(
        "content-type") == "application/pdf" else None

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fp:
        fp.write(resp.content)
        temp_path = fp.name

    return _extract_text_from_pdf(temp_path)


def load_pdf_file(f: str) -> str:
    """
    Load PDF from file path and extract text using pypdf (no LangChain)

    Args:
        f: Path to PDF file

    Returns:
        Extracted text from PDF
    """
    return _extract_text_from_pdf(f)


def _extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from PDF file using pypdf

    Args:
        pdf_path: Path to PDF file

    Returns:
        Extracted text from all pages
    """
    try:
        reader = PdfReader(pdf_path)
        text_content = []

        for page_num, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            if text.strip():
                text_content.append(text.strip())

        logger.info(f"Extracted text from {len(reader.pages)} pages")
        return "\n\n".join(text_content)

    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise
