import re
import os
import logging
import requests


async def load_transcript_from_youtube(youtube_url: str) -> str:
    """
    Summarize a YouTube video using the YoutubeLoader and Google Generative AI model.
    """
    try:
        # get YouTube video ID from url using regex
        match = re.search(r"(?<=v=)[a-zA-Z0-9_-]+", youtube_url)
        if not match:
            raise ValueError("Invalid YouTube URL")
        youtube_id = match.group(0)
        logging.debug(
            f"Extracting YouTube video ID, url: {youtube_url} v_id: {youtube_id}")

        result = await fetch_youtube_data_from_gcp(youtube_id)
        logging.debug(f"Result from fetch_youtube_data: {result}")
        summary = ""
        # Extract ids_data from the result
        if 'ids_data' in result:
            ids_data = result['ids_data']
            logging.debug(
                f"ids_data data: {ids_data[:50]}")
            summary = ids_data
        else:
            logging.error("ids_data not found in result:", result)
            summary = "Error or ids_data not found..."
        return summary
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}", exc_info=True)
        return "error:"+str(e)


async def fetch_youtube_data_from_gcp(video_id):
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
