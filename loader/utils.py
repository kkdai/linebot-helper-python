# Pure Python implementation - no LangChain
import re


def docs_to_str(docs: list) -> str:
    """
    Convert documents to string (no LangChain dependency)

    Args:
        docs: List of documents (can be dicts, objects with page_content, or strings)

    Returns:
        Concatenated string of all document contents
    """
    if not docs:
        return ""

    result = []
    for doc in docs:
        # Handle dict with 'page_content' key
        if isinstance(doc, dict) and 'page_content' in doc:
            result.append(doc['page_content'].strip())
        # Handle object with page_content attribute
        elif hasattr(doc, 'page_content'):
            result.append(doc.page_content.strip())
        # Handle plain strings
        elif isinstance(doc, str):
            result.append(doc.strip())
        # Fallback: convert to string
        else:
            result.append(str(doc).strip())

    return "\n".join(result)


def find_url(input_string: str) -> list:
    """
    Find all URLs in a string using regex

    Args:
        input_string: String to search for URLs

    Returns:
        List of URLs found in the string
    """
    # Regular expression pattern to match URLs
    url_pattern = r'https?://[^\s]+'

    # Find all matches in the input string
    matches = re.findall(url_pattern, input_string)

    # Return the list of URLs
    return matches
