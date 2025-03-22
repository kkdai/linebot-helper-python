# LINE Bot Information Helper

A Python application that provides LINE bot functionality with tools for searching, summarizing content from URLs, and processing images.

## Features

- URL content extraction and summarization
- Image processing with Gemini AI
- Web search capabilities
- GitHub issues summary
- Special handling for PTT, Medium, and OpenAI websites using Firecrawl

## Environment Variables

The application requires several environment variables to be set:

### Required Environment Variables

These environment variables must be set for the application to work:

- `ChannelSecret`: LINE Bot channel secret
- `ChannelAccessToken`: LINE Bot channel access token
- `LINE_USER_ID`: LINE user ID to send push notifications to
- `ChannelAccessTokenHF`: Hugging Face channel access token
- `GOOGLE_API_KEY`: Google API key for Gemini AI

### Optional Environment Variables

These environment variables enable additional features:

- `firecrawl_key`: Firecrawl API key for enhanced web scraping of PTT, Medium, and OpenAI websites
- `SEARCH_API_KEY`: Google Custom Search API key for web search functionality
- `SEARCH_ENGINE_ID`: Google Custom Search Engine ID for web search functionality
- `SINGLEFILE_PATH`: Path to SingleFile executable (defaults to `/Users/narumi/.local/bin/single-file`)

## Installation

1. Clone this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set up environment variables
4. Run the application:

```bash
uvicorn main:app --reload
```

## Usage

### Web Search

Any text message sent to the bot will be treated as a search query and return relevant search results.

### URL Summarization

Send a URL to the bot and it will extract and summarize the content.

### GitHub Summary

Send the message "@g" to get a summary of yesterday's GitHub issues.

### Image Processing

Send an image to the bot and it will analyze and describe the content.

## API Endpoints

- `/`: Main webhook endpoint for LINE Bot
- `/hn`: Endpoint for Hacker News summarization
- `/hf`: Endpoint for Hugging Face paper summarization

## Deployment to Google Cloud Platform

### 1. Prepare for Deployment

1. Install Google Cloud SDK
2. Initialize a Google Cloud project:

```bash
gcloud init
```

3. Create a `app.yaml` file in the project root:

```yaml
runtime: python310
instance_class: F1
entrypoint: uvicorn main:app --host=0.0.0.0 --port=$PORT

env_variables:
  ChannelSecret: "your_channel_secret"
  ChannelAccessToken: "your_channel_access_token" 
  LINE_USER_ID: "your_line_user_id"
  ChannelAccessTokenHF: "your_huggingface_channel_token"
  GOOGLE_API_KEY: "your_gemini_api_key"
  firecrawl_key: "your_firecrawl_key"
  SEARCH_API_KEY: "your_search_api_key"
  SEARCH_ENGINE_ID: "your_search_engine_id"
```

### 2. Deploy to Google App Engine

Run the following command to deploy:

```bash
gcloud app deploy
```

This will upload your application to Google App Engine and provide a URL where your application is running.

### 3. Set Up LINE Webhook

1. Go to the [LINE Developers Console](https://developers.line.biz/console/)
2. Select your bot and navigate to the Messaging API settings
3. Set the Webhook URL to your Google App Engine URL + `/` (e.g., `https://your-project.appspot.com/`)
4. Verify that the webhook works by sending a message to your LINE bot

### 4. Using Cloud Scheduler for Cron Jobs (Optional)

If you need scheduled tasks:

1. Create a `cron.yaml` file:

```yaml
cron:
- description: "Daily GitHub summary"
  url: /daily_summary
  schedule: every 24 hours
```

2. Deploy the cron jobs:

```bash
gcloud app deploy cron.yaml
```

### 5. Monitor Your Application

Monitor your application using the Google Cloud Console:

- View logs: `https://console.cloud.google.com/logs`
- Monitor instance usage: `https://console.cloud.google.com/appengine`

## Dependencies

See `requirements.txt` for a complete list of dependencies.

## License

This project is licensed under the MIT License.
