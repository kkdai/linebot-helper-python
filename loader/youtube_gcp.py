

def load_from_youtube(youtube_url: str) -> str:
    """
    Summarize a YouTube video using the YoutubeLoader and Google Generative AI model.
    """
    try:
        # get YouTube video ID from url using regex
        youtube_id = re.search(r"(?<=v=)[a-zA-Z0-9_-]+", youtube_url).group(0)
        logging.debug(
            f"Extracting YouTube video ID, url: {youtube_url} v_id: {youtube_id}")

        result = fetch_youtube_data_from_gcp(youtube_id)
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
