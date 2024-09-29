# Adjust the import as necessary
import os
import re
import requests
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain_community.document_loaders.llmsherpa import LLMSherpaFileLoader
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.document_loaders import YoutubeLoader
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate


os.environ["USER_AGENT"] = "myagent"


def summarized_from_youtube(youtube_url: str) -> str:
    """
    Summarize a YouTube video using the YoutubeLoader and Google Generative AI model.
    """
    try:
        # Load the video content using YoutubeLoader
        loader = YoutubeLoader.from_youtube_url(
            youtube_url, add_video_info=True, language=["zh-Hant", "zh-Hans", "ja", "en"])
        docs = loader.load()

        # Extract the text content from the loaded documents
        text_content = docs[0].page_content

        # Summarize the extracted text
        summary = summarize_text(text_content)

        return summary
    except Exception as e:
        # Log the exception if needed
        print(f"An error occurred: {e}")
        return ""


def summarize_with_sherpa(url: str) -> str:
    '''
    Summarize a document from a URL using the LLM Sherpa API.
    '''
    try:
        url = find_url(url)
        response = requests.head(url)
        response.raise_for_status()  # Raise an HTTPError for bad responses
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
    except Exception as e:
        # Log the exception if needed
        print(f"An error occurred: {e}")
        return ""


def generate_twitter_post(input_text: str) -> str:
    '''
    Generate a Twitter post using the Google Generative AI model.
    '''
    model = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.5,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    prompt_template = """
    Provide a tweet base on provided text.
    自動加上一些 hastags, 然後口氣輕鬆一點的推廣:
    "{text}"
    Reply in ZH-TW"""
    prompt = PromptTemplate.from_template(prompt_template)

    chain = prompt | model
    tweet = chain.invoke(
        {"text": input_text})
    return tweet.content


def generate_slack_post(input_text: str) -> str:
    '''
    Generate a Slack post using the Google Generative AI model.
    '''
    model = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.5,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    prompt_template = """
    Provide a slack post base on provided text.
    多一點條例式，然後多一些 slack emoji:
    "{text}"
    Reply in ZH-TW"""
    prompt = PromptTemplate.from_template(prompt_template)

    chain = prompt | model
    tweet = chain.invoke(
        {"text": input_text})
    return tweet.content


def summarize_text(text: str, max_tokens: int = 100) -> str:
    '''
    Summarize a text using the Google Generative AI model.
    '''
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

    prompt_template = """
    "{text}"
    CONCISE SUMMARY:
    Reply in ZH-TW"""
    prompt = PromptTemplate.from_template(prompt_template)

    summarize_chain = load_summarize_chain(
        llm=llm, chain_type="stuff", prompt=prompt)
    document = Document(page_content=text)
    summary = summarize_chain.invoke([document])
    return summary["output_text"]


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
