# LINE Bot Information Helper

A Python application that provides LINE bot functionality with tools for searching, summarizing content from URLs, processing images, and managing personal bookmarks.

## ✨ Features

### Core Features
- **URL Content Extraction & Summarization** - Extract and summarize web content with AI
- **Flexible Summary Modes** - Choose between short, normal, or detailed summaries
- **Bookmark System** - Save and organize your favorite articles
- **Image Processing** - Analyze images with Gemini AI
- **Web Search** - Intelligent keyword extraction and search
- **GitHub Issues Summary** - Daily digest of GitHub activity
- **Enhanced Error Handling** - Friendly Chinese error messages with automatic retry

### Special Website Support
- Special handling for PTT, Medium, and OpenAI websites using Firecrawl
- YouTube transcript extraction with Gemini API
- PDF document processing
- Multiple fallback strategies for reliable content extraction

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
- `DATABASE_URL`: Database connection URL (defaults to `sqlite+aiosqlite:///./linebot_bookmarks.db`)

## Installation

1. Clone this repository

2. Install dependencies:

```bash
# Recommended: Use locked versions for production
pip install -r requirements-lock.txt

# Or: Use version constraints for development
pip install -r requirements.txt
```

**⚠️ Troubleshooting Dependencies:**

If you encounter `ModuleNotFoundError: No module named 'langchain_core.pydantic_v1'`, use the fix script:

```bash
# Linux/macOS
bash fix_dependencies.sh

# Windows PowerShell
.\fix_dependencies.ps1
```

See [FIX_SUMMARY.md](FIX_SUMMARY.md) for details.

3. Set up environment variables

4. Run the application:

```bash
uvicorn main:app --reload
```

## Usage

### 📝 URL Summarization with Modes

Send a URL to the bot and it will extract and summarize the content. You can choose different summary lengths:

- **Standard Summary** (default): `https://example.com`
- **Short Summary** (1-3 key points): `https://example.com [短]` or `https://example.com [short]`
- **Detailed Summary** (comprehensive analysis): `https://example.com [詳]` or `https://example.com [detailed]`

### 🔖 Bookmark System

Save and manage your favorite articles:

- **Save Bookmark**: `https://example.com 🔖`
- **View Bookmarks**: `/bookmarks` or `/書籤`
- **Search Bookmarks**: `/search Python` or `/搜尋 AI`
- **Combine with Summary Mode**: `https://example.com [詳] 🔖`

### 🔍 Web Search

Any text message (without URL) sent to the bot will be treated as a search query and return relevant search results with AI-generated summary.

### 🐙 GitHub Summary

Send the message `@g` to get a summary of yesterday's GitHub issues from the configured repository.

### 🖼️ Image Processing

Send an image to the bot and it will analyze and describe the content in Traditional Chinese.

## API Endpoints

### LINE Bot Endpoints
- `POST /`: Main webhook endpoint for LINE Bot
- `POST /hn`: Endpoint for Hacker News summarization
- `POST /hf`: Endpoint for Hugging Face paper summarization
- `POST /urls`: Multi-URL batch processing (up to 5 URLs)

### Bookmark System API
- `POST /bookmarks/create`: Create a new bookmark
- `GET /bookmarks/list/{user_id}`: List user's bookmarks (supports pagination)
- `GET /bookmarks/search/{user_id}?q=keyword`: Search bookmarks by keyword
- `DELETE /bookmarks/delete/{bookmark_id}`: Delete a bookmark
- `GET /bookmarks/stats/{user_id}`: Get bookmark statistics

For detailed API documentation, see [IMPROVEMENTS.md](IMPROVEMENTS.md).

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

## 🎯 Recent Improvements (v2.0)

### 1. Enhanced Error Handling
- Automatic retry with exponential backoff (up to 3 attempts)
- Circuit breaker pattern to prevent cascading failures
- User-friendly Traditional Chinese error messages
- Multiple fallback strategies for content extraction

### 2. Flexible Summary Modes
- **Short Mode**: 1-3 key points for quick scanning
- **Normal Mode**: Balanced 200-300 character summary
- **Detailed Mode**: Comprehensive 500-800 character analysis

### 3. Bookmark System
- Save and organize favorite articles
- Full-text search across titles, summaries, and URLs
- SQLite database with async support
- Track access patterns and usage statistics

For detailed documentation, see:
- [IMPROVEMENTS.md](IMPROVEMENTS.md) - Technical details and deployment guide
- [QUICK_START.md](QUICK_START.md) - User guide and examples

## 📚 Documentation

- **Quick Start Guide**: [QUICK_START.md](QUICK_START.md)
- **Technical Documentation**: [IMPROVEMENTS.md](IMPROVEMENTS.md)
- **N8N Workflow**: [n8n.json](n8n.json)

## Dependencies

See `requirements.txt` for a complete list of dependencies.

Key dependencies:
- `fastapi` - Web framework
- `line-bot-sdk` - LINE Bot SDK
- `google.generativeai` - Gemini AI
- `langchain` - LLM framework
- `sqlalchemy` - Database ORM
- `tenacity` - Retry logic
- `aiosqlite` - Async SQLite

## License

This project is licensed under the MIT License.
