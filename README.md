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
- `GOOGLE_CLOUD_LOCATION`: Region for Vertex AI (optional, defaults to `global`; `global` is required for Gemini 3.x models like `gemini-3.1-flash-lite`)

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
   - `GOOGLE_CLOUD_LOCATION`: Region for Vertex AI (optional, defaults to `global`; `global` is required for Gemini 3.x models like `gemini-3.1-flash-lite`)

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

### 🔖 Bookmarks (Read Later)

Save summarized articles to Firestore and browse them later:

- `/save <url>` - Crawl the page, generate a title + summary, and save it
- `/list` - Show your 10 most recent bookmarks as a Flex carousel
- `/search <keyword>` - Search bookmark titles and summaries

When you send a URL, the social-post carousel now starts with a
"📌 摘要與分析" bubble (summary + analysis) that has a "🔖 儲存書籤"
button - tap it to save that article without any command. Each bookmark
card has open-link and delete buttons.

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

For detailed API documentation, see [IMPROVEMENTS.md](docs/IMPROVEMENTS.md).

## Deployment to Google Cloud Run

This service deploys as a container (see `Dockerfile`) to Cloud Run.
Pushes to `main` are built and deployed automatically by a Cloud Build trigger.

### Manual Deployment

```bash
gcloud run deploy linebot-helper-python \
  --source . \
  --region us-central1 \
  --no-cpu-throttling
```

**Important:** `--no-cpu-throttling` (CPU always allocated) is required.
The webhook acks LINE immediately and processes events in background
asyncio tasks; with the default request-based CPU allocation those tasks
would be frozen after the response is sent. The same applies to the
batch-job polling loop and session cleanup task.

Set the environment variables listed above on the service
(`gcloud run services update linebot-helper-python --set-env-vars ...`
or via the console). Conversation sessions and batch job mappings
persist to Firestore, so the service account needs the
`roles/datastore.user` role.

### Set Up LINE Webhook

1. Go to the [LINE Developers Console](https://developers.line.biz/console/)
2. Select your bot and navigate to the Messaging API settings
3. Set the Webhook URL to the Cloud Run service URL + `/`
4. Verify that the webhook works by sending a message to your LINE bot

### Monitoring

```bash
# Tail recent logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="linebot-helper-python"' --freshness=1h --limit=50

# Check for errors (e.g. request timeouts)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="linebot-helper-python" AND severity>=WARNING' --freshness=1d
```

### Testing

```bash
pytest            # unit tests (no credentials needed)
RUN_LIVE_TESTS=1 pytest   # additionally run live Vertex AI tests
```

Unit tests also run automatically on every push via GitHub Actions
(`.github/workflows/test.yml`).

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
- [IMPROVEMENTS.md](docs/IMPROVEMENTS.md) - Technical details and deployment guide
- [QUICK_START.md](docs/QUICK_START.md) - User guide and examples

## 📚 Documentation

- **Quick Start Guide**: [QUICK_START.md](docs/QUICK_START.md)
- **Technical Documentation**: [IMPROVEMENTS.md](docs/IMPROVEMENTS.md)
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
