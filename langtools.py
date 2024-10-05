# Adjust the import as necessary
import re
import os
import tempfile
import logging
import requests
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain_community.document_loaders.llmsherpa import LLMSherpaFileLoader
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.document_loaders import GoogleApiClient, GoogleApiYoutubeLoader
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from pathlib import Path
from google.cloud import secretmanager


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

        logging.debug("Init Google API Client")
        google_api_client = init_google_api_client()

        # Use Youtube Ids
        youtube_loader_ids = GoogleApiYoutubeLoader(
            google_api_client=google_api_client,
            video_ids=[youtube_id],
            add_video_info=True,
        )

        # Load data
        logging.debug("Loading data from video IDs")
        ids_data = youtube_loader_ids.load()
        logging.debug("Data loaded successfully")
        # Summarize the extracted text
        summary = summarize_text(str(ids_data))
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


def get_secret(secret_id):
    logging.debug(f"Fetching secret for: {secret_id}")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{os.environ['PROJECT_ID']}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    secret_data = response.payload.data.decode("UTF-8")
    logging.debug(
        f"Secret fetched successfully for: {secret_id}, {secret_data[:50]}")
    return secret_data


def init_google_api_client():
    logging.debug("Initializing GoogleApiClient")
    creds_content = get_secret("youtube_api_credentials")

    # Create a temporary file to store the credentials
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_creds_file:
        logging.debug("Writing credentials to temporary file")
        temp_creds_file.write(creds_content.encode("utf-8"))
        temp_creds_file.flush()
        temp_creds_file_path = temp_creds_file.name

    logging.debug(
        f"Temporary credentials file created at: {temp_creds_file_path}")

    # Convert the file path to a Path object
    temp_creds_file_path = Path(temp_creds_file_path)

    # Initialize GoogleApiClient with the path to the temporary credentials file
    google_api_client = GoogleApiClient(
        service_account_path=temp_creds_file_path)

    # Clean up the temporary file after use
    os.unlink(temp_creds_file_path)
    logging.debug("Temporary credentials file deleted")

    return google_api_client
