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
