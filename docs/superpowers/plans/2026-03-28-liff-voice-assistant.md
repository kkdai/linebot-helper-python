# LIFF 即時語音助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Cloud Run 的 FastAPI 上新增一個 LIFF 語音助手，讓使用者在 LINE 內開啟網頁後即可透過麥克風和 Gemini Live API 進行雙向語音對話，每輪對話結束後自動 push_message 到 LINE 聊天室。

**Architecture:** LIFF（HTML/JS）透過 WebSocket 連接後端 `/ws/voice/{session_id}`；後端開啟一個 Gemini Live session，雙向 relay PCM 音訊和 JSON 事件；每輪 turn_complete 後把問答記錄 push 到 LINE。

**Tech Stack:** FastAPI WebSocket、google-genai Live API（gemini-live-2.5-flash-native-audio）、Web Audio API（瀏覽器麥克風）、LIFF SDK（@line/liff）、line-bot-sdk push_message。

**Spec:** `docs/superpowers/specs/2026-03-28-liff-voice-assistant-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `static/liff/index.html` | LIFF UI shell：三種狀態、HTML 結構、CSS 動畫 |
| Create | `static/liff/voice.js` | 前端邏輯：LIFF init、WebSocket、Web Audio、狀態機 |
| Modify | `main.py:1-35` | 新增 FastAPI imports（StaticFiles、HTMLResponse、WebSocket） |
| Modify | `main.py:180-230` | 新增 `/liff/` route、`/ws/voice/{id}` WebSocket handler |
| Modify | `Dockerfile` | 新增 `COPY static/ ./static/` |

---

## Task 1：FastAPI 基礎建設（StaticFiles + /liff/ route + WebSocket stub）

**Files:**
- Modify: `main.py` (imports + routes)

- [ ] **Step 1: 新增 FastAPI imports**

在 `main.py` 的現有 FastAPI import 行找到：
```python
from fastapi import Request, FastAPI, HTTPException
from fastapi.responses import Response
```

改成：
```python
from fastapi import Request, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
```

- [ ] **Step 2: Mount StaticFiles + /liff/ route**

在 `main.py` 找到 `@app.get("/")` 健康檢查前，插入：

```python
# Static files for LIFF app
app.mount("/static", StaticFiles(directory="static"), name="static")

LIFF_ID = os.getenv("LIFF_ID", "")
VERTEX_PROJECT_LIVE = os.getenv("GOOGLE_CLOUD_PROJECT", "")


@app.get("/liff/")
async def serve_liff():
    """Serve the LIFF voice assistant app with LIFF_ID injected."""
    try:
        with open("static/liff/index.html", encoding="utf-8") as f:
            html = f.read().replace("{{LIFF_ID}}", LIFF_ID)
        return HTMLResponse(html)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="LIFF app not found")
```

- [ ] **Step 3: 新增 WebSocket stub（暫時 echo，讓前端可以先測試連線）**

在 `serve_liff` 後面插入：

```python
@app.websocket("/ws/voice/{session_id}")
async def voice_ws(websocket: WebSocket, session_id: str):
    """Real-time voice assistant WebSocket — relay between LIFF and Gemini Live."""
    await websocket.accept()
    logger.info(f"Voice WS connected: {session_id}")
    try:
        while True:
            data = await websocket.receive()
            if data["type"] == "websocket.disconnect":
                break
            # Stub: echo text messages back
            if "text" in data and data["text"]:
                await websocket.send_text(data["text"])
    except WebSocketDisconnect:
        pass
    finally:
        logger.info(f"Voice WS disconnected: {session_id}")
```

- [ ] **Step 4: 建立 static 目錄**

```bash
mkdir -p static/liff
```

- [ ] **Step 5: 驗證 import 不報錯**

```bash
cd /Users/al03034132/Documents/linebot-helper-python
python3 -c "import main" 2>&1 | head -20
```

Expected: 沒有 ImportError（可能有其他啟動警告，忽略即可）

- [ ] **Step 6: Commit**

```bash
git add main.py static/
git commit -m "feat(liff): add /liff/ route, /ws/voice/ stub, StaticFiles mount"
```

---

## Task 2：LIFF HTML Shell（static/liff/index.html）

**Files:**
- Create: `static/liff/index.html`

- [ ] **Step 1: 建立 index.html**

```bash
# 確認目錄存在
ls static/liff/
```

- [ ] **Step 2: 寫入 index.html**

Write `static/liff/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>AI 語音助手</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #111827;
      color: #f9fafb;
      height: 100dvh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* Header */
    #header {
      background: #1f2937;
      padding: 14px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #374151;
      flex-shrink: 0;
    }
    #header h1 { font-size: 15px; font-weight: 600; color: #f9fafb; }
    #header .subtitle { font-size: 11px; color: #9ca3af; margin-top: 2px; }

    /* Hands-free toggle */
    #handsfree-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
    }
    #handsfree-toggle span { font-size: 11px; color: #9ca3af; }
    #handsfree-switch {
      width: 36px; height: 20px;
      background: #374151;
      border-radius: 10px;
      position: relative;
      transition: background 0.2s;
    }
    #handsfree-switch.on { background: #2563eb; }
    #handsfree-switch::after {
      content: '';
      width: 16px; height: 16px;
      background: #fff;
      border-radius: 50%;
      position: absolute;
      top: 2px; left: 2px;
      transition: left 0.2s;
    }
    #handsfree-switch.on::after { left: 18px; }

    /* Chat area */
    #chat {
      flex: 1;
      overflow-y: auto;
      padding: 16px 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    #empty-hint {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 12px;
      color: #4b5563;
    }
    #empty-hint .icon { font-size: 40px; }
    #empty-hint p { font-size: 13px; }

    .bubble {
      max-width: 80%;
      padding: 10px 13px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.5;
      word-break: break-word;
    }
    .bubble.user {
      background: #374151;
      color: #f9fafb;
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }
    .bubble.user.recording {
      background: #7f1d1d;
      color: #fca5a5;
    }
    .bubble.ai {
      background: #1e3a5f;
      color: #e0f2fe;
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }
    .bubble-label {
      font-size: 10px;
      color: #6b7280;
      margin-bottom: 3px;
    }
    .bubble.user .bubble-label { text-align: right; }

    /* Waveform animation */
    .waveform {
      display: flex;
      align-items: center;
      gap: 3px;
      height: 16px;
    }
    .waveform span {
      display: block;
      width: 3px;
      background: currentColor;
      border-radius: 2px;
      animation: wave 1s ease-in-out infinite;
    }
    .waveform span:nth-child(2) { animation-delay: 0.15s; }
    .waveform span:nth-child(3) { animation-delay: 0.3s; }
    .waveform span:nth-child(4) { animation-delay: 0.45s; }
    .waveform span:nth-child(5) { animation-delay: 0.6s; }
    @keyframes wave {
      0%, 100% { height: 4px; }
      50% { height: 16px; }
    }

    /* Warning bar */
    #handsfree-warning {
      display: none;
      background: #451a03;
      color: #fbbf24;
      font-size: 11px;
      padding: 6px 16px;
      text-align: center;
      flex-shrink: 0;
    }
    #handsfree-warning.visible { display: block; }

    /* Bottom controls */
    #controls {
      background: #1f2937;
      border-top: 1px solid #374151;
      padding: 20px 16px 28px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    #status-text {
      font-size: 12px;
      color: #9ca3af;
      height: 16px;
    }
    #mic-btn {
      width: 72px; height: 72px;
      border-radius: 50%;
      border: none;
      background: #1d4ed8;
      color: #fff;
      font-size: 28px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s, box-shadow 0.15s, transform 0.1s;
      box-shadow: 0 0 0 0 rgba(29,78,216,0.4);
      -webkit-tap-highlight-color: transparent;
      touch-action: none;
    }
    #mic-btn.recording {
      background: #dc2626;
      box-shadow: 0 0 0 10px rgba(220,38,38,0.15), 0 0 0 20px rgba(220,38,38,0.07);
      animation: pulse-ring 1.5s ease-in-out infinite;
    }
    #mic-btn.speaking {
      background: #374151;
      opacity: 0.5;
      cursor: default;
    }
    @keyframes pulse-ring {
      0% { box-shadow: 0 0 0 0 rgba(220,38,38,0.4), 0 0 0 0 rgba(220,38,38,0.2); }
      70% { box-shadow: 0 0 0 12px rgba(220,38,38,0), 0 0 0 24px rgba(220,38,38,0); }
      100% { box-shadow: 0 0 0 0 rgba(220,38,38,0), 0 0 0 0 rgba(220,38,38,0); }
    }

    /* Error toast */
    #error-toast {
      display: none;
      position: fixed;
      bottom: 160px;
      left: 50%;
      transform: translateX(-50%);
      background: #7f1d1d;
      color: #fca5a5;
      padding: 10px 18px;
      border-radius: 20px;
      font-size: 13px;
      z-index: 100;
    }
    #error-toast.visible { display: block; }
  </style>
</head>
<body>

<div id="header">
  <div>
    <h1>🎤 AI 語音助手</h1>
    <div class="subtitle">Powered by Gemini Live</div>
  </div>
  <div id="handsfree-toggle" onclick="toggleHandsfree()">
    <span>免持</span>
    <div id="handsfree-switch"></div>
  </div>
</div>

<div id="handsfree-warning">⚠ 免持模式開啟中，吵雜環境可能誤觸發</div>

<div id="chat">
  <div id="empty-hint">
    <div class="icon">🎤</div>
    <p>按住麥克風按鈕開始說話</p>
  </div>
</div>

<div id="controls">
  <div id="status-text">待機中</div>
  <button id="mic-btn">🎤</button>
</div>

<div id="error-toast"></div>

<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>
  window.LIFF_ID = "{{LIFF_ID}}";
</script>
<script src="/static/liff/voice.js"></script>
</body>
</html>
```

- [ ] **Step 3: 確認檔案存在**

```bash
ls -la static/liff/
```

Expected: `index.html` 存在

- [ ] **Step 4: Commit**

```bash
git add static/liff/index.html
git commit -m "feat(liff): add LIFF HTML shell with 3 UI states"
```

---

## Task 3：voice.js — LIFF init + WebSocket 連線

**Files:**
- Create: `static/liff/voice.js`

- [ ] **Step 1: 建立 voice.js（LIFF init + WebSocket 建立）**

Write `static/liff/voice.js`:

```javascript
// ── State ─────────────────────────────────────────────────────────────────
const STATE = { IDLE: 'idle', RECORDING: 'recording', SPEAKING: 'speaking' };
let currentState = STATE.IDLE;
let ws = null;
let handsfreeEnabled = false;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let nextPlayTime = 0;
let currentAiBubble = null;
let currentUserBubble = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const micBtn = document.getElementById('mic-btn');
const statusText = document.getElementById('status-text');
const chat = document.getElementById('chat');
const emptyHint = document.getElementById('empty-hint');
const handsfreeSwitch = document.getElementById('handsfree-switch');
const handsfreeWarning = document.getElementById('handsfree-warning');
const errorToast = document.getElementById('error-toast');

// ── Entry point ────────────────────────────────────────────────────────────
window.addEventListener('load', async () => {
  try {
    await liff.init({ liffId: window.LIFF_ID });
    if (!liff.isLoggedIn()) {
      liff.login();
      return;
    }
    const profile = await liff.getProfile();
    const userId = profile.userId;
    const { lat, lng } = await getLocation();
    connectWebSocket(userId, lat, lng);
    setupMicButton();
  } catch (e) {
    showError('初始化失敗：' + e.message);
  }
});

// ── Geolocation ────────────────────────────────────────────────────────────
function getLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve({});
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => resolve({})  // GPS denied → proceed without coordinates
    );
  });
}

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWebSocket(userId, lat, lng) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws/voice/${userId}`;
  ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    const initMsg = { type: 'init', user_id: userId };
    if (lat) initMsg.lat = lat;
    if (lng) initMsg.lng = lng;
    ws.send(JSON.stringify(initMsg));
    setStatus('已連線，準備說話');
  };

  ws.onmessage = (evt) => handleServerMessage(evt);

  ws.onerror = () => showError('連線錯誤，請重新整理頁面');

  ws.onclose = () => {
    setStatus('連線已中斷');
    // Auto-reconnect after 2s (max 3 attempts handled in outer scope)
    setTimeout(() => connectWebSocket(userId, lat, lng), 2000);
  };
}

// ── Server message dispatcher ─────────────────────────────────────────────
function handleServerMessage(evt) {
  if (evt.data instanceof ArrayBuffer) {
    // Binary: PCM audio from Gemini Live
    playPCMChunk(evt.data);
    if (currentState !== STATE.SPEAKING) {
      setState(STATE.SPEAKING);
      currentAiBubble = addBubble('ai', '');
    }
  } else {
    const msg = JSON.parse(evt.data);
    if (msg.type === 'text_chunk') {
      if (!currentAiBubble) currentAiBubble = addBubble('ai', '');
      appendToBubble(currentAiBubble, msg.text);
    } else if (msg.type === 'turn_complete') {
      currentAiBubble = null;
      currentUserBubble = null;
      setState(STATE.IDLE);
    } else if (msg.type === 'error') {
      showError(msg.message || '發生錯誤');
      setState(STATE.IDLE);
    }
  }
}

// ── UI helpers ─────────────────────────────────────────────────────────────
function setState(newState) {
  currentState = newState;
  micBtn.className = '';
  if (newState === STATE.RECORDING) {
    micBtn.classList.add('recording');
    micBtn.textContent = '🎤';
    setStatus('● 錄音中，放開送出');
  } else if (newState === STATE.SPEAKING) {
    micBtn.classList.add('speaking');
    micBtn.textContent = '🔊';
    setStatus('AI 說話中，點擊打斷');
  } else {
    micBtn.textContent = '🎤';
    setStatus(handsfreeEnabled ? '🟢 免持模式' : '待機中');
  }
}

function setStatus(text) { statusText.textContent = text; }

function addBubble(type, text) {
  if (emptyHint) emptyHint.style.display = 'none';
  const wrapper = document.createElement('div');
  const label = document.createElement('div');
  label.className = 'bubble-label';
  label.textContent = type === 'ai' ? '🤖 AI' : '你';
  const bubble = document.createElement('div');
  bubble.className = `bubble ${type}`;
  bubble.textContent = text;
  wrapper.appendChild(label);
  wrapper.appendChild(bubble);
  chat.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
  return bubble;
}

function appendToBubble(bubble, text) {
  bubble.textContent += text;
  chat.scrollTop = chat.scrollHeight;
}

function showError(msg) {
  errorToast.textContent = msg;
  errorToast.classList.add('visible');
  setTimeout(() => errorToast.classList.remove('visible'), 4000);
}

function toggleHandsfree() {
  handsfreeEnabled = !handsfreeEnabled;
  handsfreeSwitch.classList.toggle('on', handsfreeEnabled);
  handsfreeWarning.classList.toggle('visible', handsfreeEnabled);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'toggle_handsfree', enabled: handsfreeEnabled }));
  }
  if (handsfreeEnabled) startHandsfreeRecording();
  else stopHandsfreeRecording();
  setState(STATE.IDLE);
}
```

- [ ] **Step 2: Commit**

```bash
git add static/liff/voice.js
git commit -m "feat(liff): add voice.js with LIFF init, WebSocket, UI helpers"
```

---

## Task 4：voice.js — 麥克風捕捉（Push-to-talk）

**Files:**
- Modify: `static/liff/voice.js`

- [ ] **Step 1: 在 voice.js 末尾追加 setupMicButton() 和 Web Audio 邏輯**

Append to `static/liff/voice.js`:

```javascript
// ── PCM conversion ────────────────────────────────────────────────────────
function float32ToInt16(float32) {
  const int16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
  }
  return int16;
}

// ── Microphone setup ──────────────────────────────────────────────────────
async function startRecording() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch {
    showError('請允許麥克風權限才能使用語音功能');
    return;
  }

  audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  const source = audioContext.createMediaStreamSource(mediaStream);

  // ScriptProcessor for PCM extraction (4096 samples @ 16kHz ≈ 256ms per chunk)
  scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  scriptProcessor.onaudioprocess = (e) => {
    if (currentState !== STATE.RECORDING) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const float32 = e.inputBuffer.getChannelData(0);
    const int16 = float32ToInt16(float32);
    ws.send(int16.buffer);
  };

  source.connect(scriptProcessor);
  scriptProcessor.connect(audioContext.destination);
}

function stopRecording() {
  if (scriptProcessor) { scriptProcessor.disconnect(); scriptProcessor = null; }
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  if (audioContext) { audioContext.close(); audioContext = null; }
}

// ── Push-to-talk button ───────────────────────────────────────────────────
function setupMicButton() {
  const onPressStart = async (e) => {
    e.preventDefault();
    if (currentState === STATE.SPEAKING) {
      // Interrupt AI
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'interrupt' }));
      }
      stopAudioPlayback();
      setState(STATE.IDLE);
      return;
    }
    if (currentState !== STATE.IDLE || handsfreeEnabled) return;
    setState(STATE.RECORDING);
    currentUserBubble = addBubble('user', '🎤 說話中...');
    await startRecording();
  };

  const onPressEnd = (e) => {
    e.preventDefault();
    if (currentState !== STATE.RECORDING) return;
    stopRecording();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'end_of_speech' }));
    }
    if (currentUserBubble) {
      currentUserBubble.textContent = '（語音輸入）';
      currentUserBubble.classList.remove('recording');
    }
    setState(STATE.SPEAKING);
  };

  micBtn.addEventListener('mousedown', onPressStart);
  micBtn.addEventListener('mouseup', onPressEnd);
  micBtn.addEventListener('touchstart', onPressStart, { passive: false });
  micBtn.addEventListener('touchend', onPressEnd, { passive: false });
}

// ── Hands-free recording ──────────────────────────────────────────────────
async function startHandsfreeRecording() {
  if (currentState !== STATE.IDLE) return;
  await startRecording();
  // In hands-free mode, VAD on Gemini side handles turn detection.
  // Keep audio flowing continuously.
}

function stopHandsfreeRecording() {
  stopRecording();
}
```

- [ ] **Step 2: Commit**

```bash
git add static/liff/voice.js
git commit -m "feat(liff): add push-to-talk mic capture and PCM streaming"
```

---

## Task 5：voice.js — 音訊播放（PCM → Web Audio）

**Files:**
- Modify: `static/liff/voice.js`

- [ ] **Step 1: 在 voice.js 末尾追加播放邏輯**

Append to `static/liff/voice.js`:

```javascript
// ── Audio playback ─────────────────────────────────────────────────────────
let playbackContext = null;

function ensurePlaybackContext() {
  if (!playbackContext || playbackContext.state === 'closed') {
    playbackContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    nextPlayTime = 0;
  }
}

function playPCMChunk(arrayBuffer) {
  ensurePlaybackContext();
  const int16 = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768.0;
  }
  const audioBuffer = playbackContext.createBuffer(1, float32.length, 16000);
  audioBuffer.getChannelData(0).set(float32);

  const source = playbackContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(playbackContext.destination);

  const startAt = Math.max(nextPlayTime, playbackContext.currentTime + 0.01);
  source.start(startAt);
  nextPlayTime = startAt + audioBuffer.duration;
}

function stopAudioPlayback() {
  if (playbackContext) {
    playbackContext.close();
    playbackContext = null;
    nextPlayTime = 0;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add static/liff/voice.js
git commit -m "feat(liff): add PCM audio playback queue via Web Audio API"
```

---

## Task 6：Backend WebSocket Handler（完整實作）

**Files:**
- Modify: `main.py` — 把 Task 1 的 stub 換成完整 handler

- [ ] **Step 1: 新增 asyncio import**

在 `main.py` 頂部找到現有 import 群組，確認有：
```python
import asyncio
```
若無，在 `import os` 後面加入 `import asyncio`。

- [ ] **Step 2: 新增 google-genai imports（voice session 用）**

在 `main.py` 找到 `from tools.tts_tool import text_to_speech`，在其後加入：

```python
from google import genai as live_genai
from google.genai import types as live_types
```

- [ ] **Step 3: 把 voice_ws stub 換成完整實作**

在 `main.py` 找到：
```python
@app.websocket("/ws/voice/{session_id}")
async def voice_ws(websocket: WebSocket, session_id: str):
    """Real-time voice assistant WebSocket — relay between LIFF and Gemini Live."""
    await websocket.accept()
    logger.info(f"Voice WS connected: {session_id}")
    try:
        while True:
            data = await websocket.receive()
            if data["type"] == "websocket.disconnect":
                break
            # Stub: echo text messages back
            if "text" in data and data["text"]:
                await websocket.send_text(data["text"])
    except WebSocketDisconnect:
        pass
    finally:
        logger.info(f"Voice WS disconnected: {session_id}")
```

Replace with:

```python
def _build_voice_system_instruction(lat: float | None, lng: float | None) -> str:
    location_info = f"使用者目前位置：緯度 {lat:.6f}，經度 {lng:.6f}" if lat and lng else "使用者未提供位置資訊，地點查詢時請請求使用者口述位置"
    return f"""你是一個整合多種工具的語音助手，透過 LINE Bot 服務使用者。

{location_info}

你可以：
- 查詢附近地點（使用 maps 工具查詢餐廳、停車場、加油站等）
- 摘要網頁、YouTube 影片或 PDF 內容
- 回答一般問題（搭配 Google Search）
- 提供天氣、交通等即時資訊

請用繁體中文回應，語氣自然口語，適合直接用語音播放。不要使用條列符號或 markdown 格式，改用自然的說話方式。每次回應控制在 50 字以內。"""


async def _browser_to_gemini(websocket: WebSocket, session, state: dict):
    """Relay PCM audio and control events from browser to Gemini Live session."""
    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break
            if data.get("bytes"):
                # PCM audio chunk from microphone
                await session.send_realtime_input(
                    audio=live_types.Blob(data=data["bytes"], mime_type="audio/pcm;rate=16000")
                )
            elif data.get("text"):
                event = json.loads(data["text"])
                etype = event.get("type")
                if etype == "end_of_speech":
                    # Push-to-talk released — signal end of user turn
                    await session.send_client_content(turn_complete=True)
                elif etype == "interrupt":
                    state["interrupted"] = True
                elif etype == "toggle_handsfree":
                    state["handsfree"] = event.get("enabled", False)
                elif etype == "init":
                    pass  # Already handled before this task starts
    except Exception as e:
        logger.debug(f"browser_to_gemini ended: {e}")


async def _gemini_to_browser(websocket: WebSocket, session, state: dict, user_id: str):
    """Relay Gemini Live responses (PCM + text) back to browser; push to LINE on turn_complete."""
    ai_text_accum = []
    user_text_accum = []
    try:
        async for msg in session.receive():
            if state.get("interrupted"):
                state["interrupted"] = False
                ai_text_accum.clear()
                continue

            if msg.server_content:
                # Input transcription (user's speech)
                if hasattr(msg.server_content, "input_transcription") and msg.server_content.input_transcription:
                    t = msg.server_content.input_transcription.text or ""
                    if t:
                        user_text_accum.append(t)

                # AI response parts (audio + text)
                if msg.server_content.model_turn:
                    for part in msg.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            await websocket.send_bytes(part.inline_data.data)
                        if part.text:
                            ai_text_accum.append(part.text)
                            await websocket.send_text(json.dumps({"type": "text_chunk", "text": part.text}))

                # Turn complete
                if msg.server_content.turn_complete:
                    await websocket.send_text(json.dumps({"type": "turn_complete"}))

                    # Push conversation to LINE
                    user_speech = "".join(user_text_accum).strip() or "（語音輸入）"
                    ai_response = "".join(ai_text_accum).strip()
                    if ai_response and user_id:
                        push_text = f"🎤 你說：{user_speech}\n\n🤖 AI：{ai_response}"
                        try:
                            await line_bot_api.push_message(user_id, [TextSendMessage(text=push_text)])
                        except Exception as e:
                            logger.error(f"push_message failed for {user_id}: {e}")

                    ai_text_accum.clear()
                    user_text_accum.clear()

    except Exception as e:
        logger.debug(f"gemini_to_browser ended: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "語音服務發生錯誤"}))
        except Exception:
            pass


@app.websocket("/ws/voice/{session_id}")
async def voice_ws(websocket: WebSocket, session_id: str):
    """Real-time voice assistant WebSocket — relay between LIFF and Gemini Live."""
    await websocket.accept()
    logger.info(f"Voice WS connected: {session_id}")

    try:
        # Step 1: Wait for init event
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
        init_data = json.loads(init_raw)
        user_id = init_data.get("user_id", session_id)
        lat = init_data.get("lat")
        lng = init_data.get("lng")
        logger.info(f"Voice WS init: user={user_id}, gps=({lat},{lng})")

        # Step 2: Build system instruction
        system_instruction = _build_voice_system_instruction(lat, lng)

        # Step 3: Open Gemini Live session
        client = live_genai.Client(vertexai=True, project=VERTEX_PROJECT_LIVE, location="us-central1")
        config = live_types.LiveConnectConfig(
            response_modalities=["AUDIO", "TEXT"],
            system_instruction=live_types.Content(
                role="system",
                parts=[live_types.Part(text=system_instruction)]
            ),
        )

        state = {"interrupted": False, "handsfree": False}

        async with client.aio.live.connect(model="gemini-live-2.5-flash-native-audio", config=config) as session:
            t1 = asyncio.create_task(_browser_to_gemini(websocket, session, state))
            t2 = asyncio.create_task(_gemini_to_browser(websocket, session, state, user_id))
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except asyncio.TimeoutError:
        logger.warning(f"Voice WS init timeout: {session_id}")
        await websocket.send_text(json.dumps({"type": "error", "message": "初始化逾時"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Voice WS error: {e}", exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "語音服務暫時無法使用"}))
        except Exception:
            pass
    finally:
        logger.info(f"Voice WS disconnected: {session_id}")
```

- [ ] **Step 4: 驗證語法**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(liff): implement full WebSocket handler with Gemini Live relay and push_message"
```

---

## Task 7：Dockerfile 更新

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: 讀取現有 Dockerfile**

Read `Dockerfile` 找到 `COPY` 相關的行。

- [ ] **Step 2: 確認 static/ 被 COPY**

找到現有的 COPY 行（通常是 `COPY . .` 或類似的）。如果是 `COPY . .`，靜態檔案已被涵蓋，不需要修改。

如果只有特定目錄被 COPY，則在現有 `COPY` 行後面加入：

```dockerfile
COPY static/ ./static/
```

- [ ] **Step 3: 驗證**

```bash
grep -n "COPY\|static" Dockerfile
```

確認 static/ 會被複製進 image。

- [ ] **Step 4: Commit（僅在有修改時）**

```bash
git add Dockerfile
git commit -m "chore(docker): ensure static/liff files are copied into image"
```

---

## Task 8：Deploy 與 LIFF 設定（手動步驟）

**Files:** 無（手動操作）

- [ ] **Step 1: 設定 LIFF_ID 環境變數**

先在 LINE Developers Console 建立 LIFF：
1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 選擇你的 Channel → LIFF → Add
3. LIFF app name：`AI 語音助手`
4. Size：`Full`
5. Endpoint URL：`https://{your-cloud-run-url}/liff/`
6. 取得 LIFF ID（格式：`1234567890-xxxxxxxx`）

- [ ] **Step 2: 把 LIFF_ID 加進 Cloud Run 環境變數**

```bash
gcloud run services update linebot-helper-python \
  --region us-central1 \
  --set-env-vars LIFF_ID=YOUR_LIFF_ID_HERE
```

- [ ] **Step 3: Push 並確認部署**

```bash
git push
```

等 Cloud Run 部署完成後：

```bash
curl https://{your-cloud-run-url}/liff/ | grep "window.LIFF_ID"
```

Expected: `window.LIFF_ID = "1234567890-xxxxxxxx";`（你的 LIFF ID）

- [ ] **Step 4: 在 LINE 設定 Rich Menu**

1. LINE Official Account Manager → Rich menu → 建立
2. 新增一個格子，Action Type：URI
3. URI 填入：`https://liff.line.me/{LIFF_ID}`
4. 發佈

---

## Task 9：手動 Smoke Test

- [ ] 在 LINE 開啟 Rich Menu → 點「🎤 語音助手」→ 確認 LIFF 開啟、顯示「已連線，準備說話」
- [ ] 點允許麥克風 → 按住按鈕說「你好，今天天氣怎樣？」→ 放開 → 確認 AI 有語音回應
- [ ] 確認 LINE 聊天室有收到推送訊息（「🎤 你說：… 🤖 AI：…」）
- [ ] 點右上角「免持」toggle → 顯示警示 → 直接說話 → 確認 VAD 自動觸發
- [ ] 說話時點麥克風按鈕打斷 AI → 確認 AI 停止說話
- [ ] 在吵雜環境測試免持模式誤觸發警示
- [ ] 拒絕 GPS → 確認 App 正常運作（AI 詢問位置）
- [ ] 關閉 LIFF 重新開啟 → 確認重新連線
