import os
import requests
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain_community.document_loaders.llmsherpa import LLMSherpaFileLoader
from langchain_community.document_loaders import WebBaseLoader
from langchain_google_genai import ChatGoogleGenerativeAI

os.environ["USER_AGENT"] = "myagent"


def summarize_with_sherpa(url: str) -> str:
    response = requests.head(url)
    content_type = response.headers.get("content-type")
    allowed_types = [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/html",
        "text/plain",
        "application/xml",
        "application/pdf",
    ]
    loader = LLMSherpaFileLoader(
        file_path=url,
        new_indent_parser=True,
        apply_ocr=True,
        strategy="text",
        llmsherpa_api_url="https://readers.llmsherpa.com/api/document/developer/parseDocument?renderFormat=all",
    ) if content_type in allowed_types else WebBaseLoader(url)
    docs = loader.load()
    return docs[0].page_content


def summarize_text(text: str, max_tokens: int = 100) -> str:
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    summarize_chain = load_summarize_chain(llm=llm)
    document = Document(page_content=text)
    summary = summarize_chain.invoke([document])
    return summary["output_text"]
