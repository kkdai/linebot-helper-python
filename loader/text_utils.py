"""
Utility functions for text processing
"""
import re
from typing import Tuple, Optional


def parse_summary_mode(text: str) -> Tuple[str, str]:
    """
    Parse summary mode from user text

    Supports following formats:
    - URL [短]
    - URL [詳]
    - URL (short)
    - URL (detailed)

    Args:
        text: User input text

    Returns:
        Tuple of (cleaned_text, mode)
        - cleaned_text: Text with mode indicator removed
        - mode: "short", "normal", or "detailed"
    """
    # Define mode mappings
    mode_patterns = {
        r'\[短\]|\(短\)|\[short\]|\(short\)': 'short',
        r'\[詳\]|\(詳\)|\[detailed\]|\(detailed\)|\[detail\]|\(detail\)': 'detailed',
        r'\[標準\]|\(標準\)|\[normal\]|\(normal\)': 'normal',
    }

    # Check for mode indicators
    for pattern, mode in mode_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Remove the mode indicator from text
            cleaned_text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
            return cleaned_text, mode

    # Default to normal mode
    return text, 'normal'


def extract_url_and_mode(message_text: str) -> Tuple[list[str], str]:
    """
    Extract URLs and summary mode from message text

    Args:
        message_text: User message text

    Returns:
        Tuple of (urls, mode)
    """
    # Parse mode first
    cleaned_text, mode = parse_summary_mode(message_text)

    # Import here to avoid circular dependency
    from .utils import find_url

    # Extract URLs from cleaned text
    urls = find_url(cleaned_text)

    return urls, mode


def get_mode_description(mode: str) -> str:
    """
    Get user-friendly description for summary mode

    Args:
        mode: Summary mode ("short", "normal", or "detailed")

    Returns:
        Description in Traditional Chinese
    """
    descriptions = {
        'short': '簡短摘要（1-3 個重點）',
        'normal': '標準摘要（平衡詳細度）',
        'detailed': '詳細摘要（完整分析）'
    }
    return descriptions.get(mode, descriptions['normal'])
