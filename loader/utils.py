from langchain_core.documents import Document
import re


def docs_to_str(docs: list[Document]) -> str:
    return "\n".join([doc.page_content.strip() for doc in docs])


def find_url(input_string):
    # Regular expression pattern to match URLs
    url_pattern = r'https?://[^\s]+'

    # Search for the pattern in the input string
    match = re.search(url_pattern, input_string)

    # If a match is found, return the URL, otherwise return an empty string
    if match:
        return match.group(0)
    else:
        return ''
