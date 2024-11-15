from langchain_core.documents import Document
import re


def docs_to_str(docs: list[Document]) -> str:
    return "\n".join([doc.page_content.strip() for doc in docs])


def find_url(input_string):
    # Regular expression pattern to match URLs
    url_pattern = r'https?://[^\s]+'

    # Find all matches in the input string
    matches = re.findall(url_pattern, input_string)

    # Return the list of URLs
    return matches
