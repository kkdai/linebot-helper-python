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
from ..loader.utils import find_url

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


def summarize_url_with_sherpa(url: str) -> str:
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
              "First 50 chars: ", text_content[:50])
        return text_content
    except Exception as e:
        # Log the exception if needed
        print(f"An error occurred: {e}, calling singlefile API")
        # Fallback to SingleFile API
        return "error:"+str(e)


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
    Remove all markdown.
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
    Remove all markdown.
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

    prompt_template = """用台灣用語的繁體中文，簡潔地以條列式總結文章重點。在摘要後直接加入相關的英文 hashtag，以空格分隔。內容來源可以是網頁、文章、論文、影片字幕或逐字稿。

    原文： "{text}"
    請遵循以下步驟來完成此任務：

    # 步驟
    1. 從提供的內容中提取重要重點，無論來源是網頁、文章、論文、影片字幕或逐字稿。
    2. 將重點整理成條列式，確保每一點為簡短且明確的句子。
    3. 使用符合台灣用語的簡潔繁體中文。
    4. 在摘要結尾處，加入至少三個相關的英文 hashtag，並以空格分隔。

    # 輸出格式
    - 重點應以條列式列出，每一點應為一個短句或片語，語言必須簡潔明瞭。
    - 最後加入至少三個相關的英文 hashtag，每個 hashtag 之間用空格分隔。

    # 範例
    輸入：
    文章內容：
    台灣的報告指出，環境保護的重要性日益增加。許多人開始選擇使用可重複使用的產品。政府也實施了多項政策來降低廢物。

    摘要：

    輸出：
    - 環境保護重要性增加
    - 越來越多人使用可重複產品
    - 政府實施減廢政策
    #EnvironmentalProtection #Sustainability #Taiwan
    """

    prompt = PromptTemplate.from_template(prompt_template)

    summarize_chain = load_summarize_chain(
        llm=llm, chain_type="stuff", prompt=prompt)
    document = Document(page_content=text)
    summary = summarize_chain.invoke([document])
    return summary["output_text"]


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
