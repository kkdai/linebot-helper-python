# LINE Bot Information Helper

A Python application that provides LINE bot functionality with tools for searching, summarizing content from URLs, and processing images.

## ✨ Features

### Core Features
- **🎬 Video Q&A** - Ask follow-up questions about any YouTube video and get
  answers with precise timestamps (agentic video understanding)
- **🤖 Intelligent Conversation with Memory** - Ask questions and get AI-powered answers with automatic web search
- **💬 Multi-turn Dialogue Support** - Remembers conversation context for 30 minutes
- **URL Content Extraction & Summarization** - Extract and summarize web content with AI.
  URLs without a scheme (`www.youtube.com/watch?v=...`) are recognised too
- **📣 Social Media Posts** - Every URL also becomes ready-to-post copy for Facebook,
  LinkedIn, Threads and Twitter/X in Traditional Chinese, with an English version on demand
- **🔖 Bookmarks & 📄 Research Reports** - Save summaries to Firestore, or generate a
  grounded deep-dive report served as a web page
- **🎤 Voice In and Out** - Send a LINE voice message and the answer comes back with a
  "🔊 用語音聽" button that reads it aloud (Gemini TTS)
- **🗣️ LIFF Live Voice Assistant** - Real-time voice conversation in a LIFF page over
  WebSocket (Gemini Live), push-to-talk or hands-free
- **📍 Location & Restaurant Search** - Share a location for nearby recommendations
  (Maps Grounding), with an optional Batch API deep-dive on reviews and signature dishes
- **Flexible Summary Modes** - Choose between short, normal, or detailed summaries
- **Image Processing** - Analyze images with Gemini AI, including agentic vision driven
  by your own prompt
- **GitHub Issues Summary** - Daily digest of GitHub activity
- **💰 Usage & Cost Tracking** - Per-user token and cost records in Firestore, with an
  optional daily budget cap for video Q&A
- **⚡ Crawl Cache** - Crawled pages are cached for 24 hours, so the follow-up buttons
  (English post, research report) don't pay to crawl the same page again
- **Enhanced Error Handling** - Friendly Chinese error messages with automatic retry

### Special Website Support
- Special handling for PTT, Medium, and OpenAI websites using Firecrawl
- YouTube transcript extraction with Gemini API
- Document links converted to clean Markdown via anydoc - Word, PowerPoint,
  Excel, OpenDocument, RTF, EPUB, CSV, and PDF (PDF falls back to pypdf)
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
- `CHAT_MODEL` / `FAST_MODEL` / `ORCHESTRATOR_MODEL` / `VIDEO_MODEL`: Override the
  models in `config/agent_config.py`. Preview models are rejected by tests. Model
  pricing lives alongside the model IDs in `config/agent_config.py`
  (`MODEL_PRICING`) - adding a new model means adding its pricing row there too,
  or `services/usage_meter.py` cost tracking silently misses it.
- `VIDEO_QA_DAILY_BUDGET_USD`: Daily spend cap for video Q&A. Unset means unlimited.
- `GOOGLE_AI_API_KEY` (or `GEMINI_API_KEY`): Google AI Studio key. Required for the
  three features that do **not** run on Vertex AI - read-aloud TTS
  (`tools/tts_tool.py`), the LIFF live voice assistant (`/ws/voice/...`), and the
  Batch API restaurant analysis (`services/batch_service.py`).
- `LIFF_ID`: LIFF app ID injected into the voice assistant page. Without it `/liff/`
  is served with the placeholder unsubstituted and the page won't initialise.
- `WEBHOOK_DOMAIN`: Public domain used as the callback base for Batch API jobs.
  Falls back to the domain of the incoming request.
- `WEBHOOK_SIGNING_SECRET`: Shared secret for validating Batch API callbacks. If it is
  unset, signature validation is **skipped** (a warning is logged) - set it in production.
- `ENABLE_GROUNDING` / `ENABLE_MAPS_GROUNDING`: Turn Google Search / Maps grounding off
  (both default to `true`).
- `SESSION_TIMEOUT_MINUTES` (30), `MAX_HISTORY_LENGTH` (20), `MAX_OUTPUT_TOKENS` (2048),
  `AGENT_TEMPERATURE` (0.7): Conversation tuning, see `config/agent_config.py`.

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
- `GOOGLE_API_KEY` is **no longer used** - summarization, chat, vision, video and
  grounding all run on Vertex AI
- This provides higher rate limits and better quota management
- Vertex AI is a paid service - see [pricing](https://cloud.google.com/vertex-ai/pricing)
- Three features still need a Google AI Studio key (`GOOGLE_AI_API_KEY` /
  `GEMINI_API_KEY`) because they use APIs Vertex AI doesn't expose the same way:
  read-aloud TTS, the LIFF live voice assistant, and Batch API restaurant analysis

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

### 📄 Research Reports (Temporary Pages)

The summary bubble also has a "📄 詳細研究報告" button: it deep-dives
the article with Google Search Grounding (background, counterpoints,
evidence review) and serves the report as a styled web page at
`/reports/{id}`. Reports are persisted to Firestore and kept
indefinitely.

**Note:** Conversations automatically expire after 30 minutes of inactivity.

---

### 🎬 Video Q&A

Send a YouTube link and the summary carousel includes a "🎬 問這部影片" button.
Tap it to enter video Q&A mode - ask follow-up questions about the video and
get answers in Traditional Chinese with precise timestamps (e.g. "定價在
1:24:40"), powered by Gemini agentic video understanding. Each answer has a
"🚪 結束問影片" button; the mode also exits automatically on a new URL, a `/`
command, a non-text message, or after 30 minutes idle. See
[video-qa design](docs/superpowers/specs/2026-09-02-video-qa-design.md) for
how the cost profile (and its non-determinism) works.

---

### 📣 Social Media Posts

Send any URL and the reply is a Flex carousel: a "📌 摘要與分析" bubble followed by
ready-to-post copy for Facebook, LinkedIn, Threads and Twitter/X in Traditional
Chinese (each with a copy button), plus the same four as plain text messages for
desktop copy-paste. The summary bubble carries four buttons - "🔗 開啟原文",
"📄 詳細研究報告", "🇺🇸 英文貼文" (generates the English versions on demand) and
"🔖 儲存書籤".

Sending several URLs in one message works too - the first 5 messages go out as a
reply and the rest are pushed in batches, so nothing gets dropped at LINE's 5-message
limit.

### 🎤 Voice Messages and Read Aloud

- Send a **LINE voice message**: it is transcribed, answered through the same
  Orchestrator as text, and the reply carries a "🔊 用語音聽" button.
- Tap that button to get the same answer back as an audio message
  (Gemini TTS, `tools/tts_tool.py`). The button is offered on replies to voice
  messages - text conversations stay text-only.

### 🗣️ LIFF Live Voice Assistant

`/liff/` serves a LIFF page that talks to Gemini Live over a WebSocket
(`/ws/voice/{session_id}`) for real-time voice conversation, with nearby-place search
available as a tool mid-conversation. Two modes: push-to-talk (browser sends
activity signals, automatic VAD disabled) and hands-free (Gemini's own VAD).
Requires `LIFF_ID` and `GOOGLE_AI_API_KEY`. See
[design](docs/superpowers/specs/2026-03-28-liff-voice-assistant-design.md).

### 📍 Location and Restaurant Search

Share a location and the bot suggests nearby places using Maps Grounding, with a
"🔍 深度評論分析 (Batch)" button. That kicks off a Gemini Batch API job which analyses
reviews and signature dishes in the background and pushes the result back when done
(callbacks land on `/api/gemini-callback/*`). You can also ask in text, e.g.
`幫我查一下 <店名> 的菜色`.

### 💰 Usage and Cost Tracking

Every Gemini call's token counts and converted cost are accumulated per user per day
in Firestore (`services/usage_meter.py`), priced from `MODEL_PRICING` in
`config/agent_config.py`. Video Q&A honours `VIDEO_QA_DAILY_BUDGET_USD` as a daily
spend cap - the budget is enforced on actual spend, not video length, because the
cost of a single call varies by more than an order of magnitude. Metering failures
degrade silently and never block a reply.

---

### 📝 URL Summarization with Modes

Send a URL to the bot and it will extract and summarize the content. You can choose different summary lengths:

- **Standard Summary** (default): `https://example.com`
- **Short Summary** (1-3 key points): `https://example.com [短]` or `https://example.com [short]`
- **Detailed Summary** (comprehensive analysis): `https://example.com [詳]` or `https://example.com [detailed]`

The scheme is optional - `www.example.com/a` and `youtu.be/xxxx` are recognised and
normalised to `https://`. Punctuation stuck to the end of a URL (`...com/a，很讚`)
is stripped, while genuinely balanced brackets (Wikipedia's `/wiki/Foo_(bar)`) are kept.

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

### Other Endpoints
- `GET /reports/{report_id}`: Rendered research report page
- `GET /liff/`: LIFF voice assistant page (`LIFF_ID` is injected into the template)
- `WS /ws/voice/{session_id}`: Gemini Live relay for the voice assistant
- `GET /images/{image_id}`, `GET /audio/{audio_id}`: Temporary media served back to LINE
- `POST /api/gemini-callback/static`, `POST /api/gemini-callback/dynamic`: Batch API
  job callbacks (validated with `WEBHOOK_SIGNING_SECRET`)

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

- **Project Roadmap** (current status, what's next): [project-roadmap.md](docs/01_plan/project-roadmap.md)
- **Feature Designs**: [docs/superpowers/specs/](docs/superpowers/specs/)
- **Blog Post**: [Gemini Batch API & Webhook 實戰記](docs/blog/2026-06-13-gemini-batch-webhook.md) - how the restaurant deep-analysis flow was built
- **Quick Start Guide**: [QUICK_START.md](docs/QUICK_START.md)
- **Technical Documentation**: [IMPROVEMENTS.md](docs/IMPROVEMENTS.md)
- **N8N Workflow**: [n8n.json](n8n.json)

## Dependencies

See `requirements.txt` for a complete list of dependencies.

Key dependencies:
- `fastapi` - Web framework
- `line-bot-sdk` - LINE Bot SDK
- `google-genai` - Vertex AI SDK (no LangChain)
- `google-cloud-firestore` - Persistence for sessions, bookmarks, reports, usage records
- `tenacity` - Retry logic
- `pypdf` - PDF processing (fallback)
- `firecrawl-anydoc` - Document to Markdown conversion (Office, OpenDocument, EPUB, PDF)
- `beautifulsoup4` - HTML parsing

## License

This project is licensed under the MIT License.
