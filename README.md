# LINE Bot Information Helper

A Python application that provides LINE bot functionality with tools for searching, summarizing content from URLs, and processing images.

## ✨ Features

### Core Features
- **🤖 Intelligent Conversation with Memory** - Ask questions and get AI-powered answers with automatic web search (NEW!)
- **💬 Multi-turn Dialogue Support** - Remembers conversation context for 30 minutes
- **URL Content Extraction & Summarization** - Extract and summarize web content with AI
- **Flexible Summary Modes** - Choose between short, normal, or detailed summaries
- **Image Processing** - Analyze images with Gemini AI
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
- `GOOGLE_CLOUD_PROJECT`: Google Cloud project ID for Vertex AI (required)
- `GOOGLE_CLOUD_LOCATION`: Region for Vertex AI (optional, defaults to `us-central1`)

### Optional Environment Variables

These environment variables enable additional features:

- `firecrawl_key`: Firecrawl API key for enhanced web scraping of PTT, Medium, and OpenAI websites
- `SINGLEFILE_PATH`: Path to SingleFile executable (defaults to `/Users/narumi/.local/bin/single-file`)
- `GITHUB_TOKEN`: GitHub personal access token for accessing private repositories (optional)

### Vertex AI Setup (Required for All AI Features)

**IMPORTANT:** This application now uses Google Vertex AI for all AI features including:
- Text summarization
- Image analysis
- YouTube video transcription
- Web search keyword extraction
- GitHub issues summary
- Maps Grounding (location-based search)

**Setup Steps:**

1. **Enable Vertex AI API** in your Google Cloud project:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the "Vertex AI API"

2. **Set up Authentication** using Application Default Credentials (ADC):
   ```bash
   gcloud auth application-default login
   ```

   Or use a service account key file:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

3. **Configure Environment Variables:**
   - `GOOGLE_CLOUD_PROJECT`: Your Google Cloud project ID (required)
   - `GOOGLE_CLOUD_LOCATION`: Region for Vertex AI (optional, defaults to `us-central1`)

**Note:** For Maps Grounding specifically, `global` location is recommended.

**Migration from Gemini API Key:**
- `GOOGLE_API_KEY` is **no longer used** - all features now use Vertex AI
- This provides higher rate limits and better quota management
- Vertex AI is a paid service - see [pricing](https://cloud.google.com/vertex-ai/pricing)

**Google Search Grounding:**
- The intelligent chat feature uses **Vertex AI Grounding with Google Search**
- This is Google's official RAG (Retrieval-Augmented Generation) solution
- Automatically searches the web when needed and cites sources
- No separate Google Custom Search API required for chat feature

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

### 🤖 Intelligent Chat with Memory (NEW!)

Send any question and the bot will automatically search the web and provide detailed answers with sources.

**Features:**
- 💬 **Continuous Conversation** - The bot remembers your conversation for 30 minutes
- 🔍 **Auto Web Search** - Automatically searches when needed using Google Search Grounding
- 📚 **Source Citations** - Provides references for information
- 🇹🇼 **Traditional Chinese** - All responses in Traditional Chinese

**Examples:**
```
You: Python 是什麼？
Bot: Python 是一種高階、直譯式的程式語言...
     📚 參考來源：
     1. Python 官方網站
        https://www.python.org/

You: 它有什麼優點？  ✅ Bot remembers "它" = Python
Bot: 💬 [對話中]
     Python 的主要優點包括：...
```

**Special Commands:**
- `/clear` or `/清除` - Clear conversation memory
- `/status` or `/狀態` - Check conversation status
- `/help` or `/幫助` - Show help message

**Note:** Conversations automatically expire after 30 minutes of inactivity.

---

### 📝 URL Summarization with Modes

Send a URL to the bot and it will extract and summarize the content. You can choose different summary lengths:

- **Standard Summary** (default): `https://example.com`
- **Short Summary** (1-3 key points): `https://example.com [短]` or `https://example.com [short]`
- **Detailed Summary** (comprehensive analysis): `https://example.com [詳]` or `https://example.com [detailed]`

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
- `google-genai` - Vertex AI SDK (no LangChain)
- `tenacity` - Retry logic
- `pypdf` - PDF processing
- `beautifulsoup4` - HTML parsing

## License

This project is licensed under the MIT License.
