# Adjust the import as necessary
import re
import os
import logging
import requests
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain_community.document_loaders.llmsherpa import LLMSherpaFileLoader
from langchain_community.document_loaders import WebBaseLoader
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate


# Configure logging
logging.basicConfig(level=logging.DEBUG)

os.environ["USER_AGENT"] = "myagent"


def docs_to_str(docs: list[Document]) -> str:
    return "\n".join([doc.page_content for doc in docs])


def summarized_from_youtube(youtube_url: str) -> str:
    """
    Summarize a YouTube video using the YoutubeLoader and Google Generative AI model.
    """
    try:
        # get YouTube video ID from url using regex
        youtube_id = re.search(r"(?<=v=)[a-zA-Z0-9_-]+", youtube_url).group(0)
        logging.debug(
            f"Extracting YouTube video ID, url: {youtube_url} v_id: {youtube_id}")

        result = fetch_youtube_data(youtube_id)
        logging.debug(f"Result from fetch_youtube_data: {result}")
        summary = ""
        # Extract ids_data from the result
        if 'ids_data' in result:
            ids_data = result['ids_data']
            logging.debug(
                f"ids_data data: {ids_data[:50]}")
            summary = summarize_text(ids_data)
        else:
            logging.error("ids_data not found in result:", result)
            summary = "Error or ids_data not found..."
        return summary
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}", exc_info=True)
        return "error:"+str(e)


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
        print("Pages of  Docs: ", len(docs))
        # Extract the text content from the loaded documents
        text_content = docs_to_str(docs)
        print("Words: ", len(text_content.split()),
              "First 1000 chars: ", text_content[:1000])
        return text_content
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


def fetch_youtube_data(video_id):
    try:
        # Read the URL from the environment variable
        url = os.environ.get('GCP_LOADER_URL')
        if not url:
            return {"error": "Environment variable 'GCP_LOADER_URL' is not set"}

        # Define the parameters
        params = {'v_id': video_id}

        # Make the GET request
        response = requests.get(url, params=params)

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            data = response.json()
            return data
        else:
            # Handle errors
            return {"error": f"Request failed with status code {response.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def fetch_singlefile_content(url):
    # Read the URL from the environment variable
    api_url = os.environ.get('GCP_SINGLEFILE_URL')
    if not url:
        return {"error": "Environment variable 'GCP_SINGLEFILE_URL' is not set"}

    headers = {"Content-Type": "application/json"}

    # 定義請求的數據
    data = {"url": url}

    try:
        # 發送 POST 請求
        response = requests.post(api_url, json=data, headers=headers)

        # 檢查請求是否成功
        if response.status_code == 200:
            # 解析 JSON 響應
            json_response = response.json()
            # 提取 "content" 字段的值
            content = json_response.get("content", "")
            return content
        else:
            print(f"Request failed with status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None
