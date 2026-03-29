// ── State ─────────────────────────────────────────────────────────────────
const STATE = { IDLE: 'idle', RECORDING: 'recording', SPEAKING: 'speaking' };
let currentState = STATE.IDLE;
let ws = null;
let handsfreeEnabled = false;
let audioStreamer = null;
let audioPlayer = null;
let userId = null;
let userLat = null;
let userLng = null;
let currentAiBubble = null;
let currentUserBubble = null;
let aiTextAccum = [];
let connectAttempt = 0;

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
    if (!liff.isLoggedIn()) { liff.login(); return; }
    const profile = await liff.getProfile();
    userId = profile.userId;
    const loc = await getLocation();
    userLat = loc.lat || null;
    userLng = loc.lng || null;
    audioPlayer = new AudioPlayer();
    await connectWebSocket();
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
      () => resolve({})
    );
  });
}

// ── WebSocket to server ────────────────────────────────────────────────────
async function connectWebSocket() {
  setStatus('連線中...');
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${proto}://${location.host}/ws/voice/${encodeURIComponent(userId)}`;
  ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'init', user_id: userId, lat: userLat, lng: userLng }));
    setStatus('已連線，準備說話');
    connectAttempt = 0;
  };

  ws.onmessage = (evt) => handleServerMessage(evt);

  ws.onerror = () => {};

  ws.onclose = () => {
    if (connectAttempt < 3) {
      connectAttempt++;
      setStatus(`連線中斷，重連中… (${connectAttempt}/3)`);
      setTimeout(connectWebSocket, 2000);
    } else {
      setStatus('連線失敗');
      showError('連線已中斷，請重新整理頁面');
    }
  };
}

// ── Server message handler ─────────────────────────────────────────────────
function handleServerMessage(evt) {
  // Binary = PCM audio from AI
  if (evt.data instanceof ArrayBuffer) {
    if (currentState !== STATE.SPEAKING) {
      setState(STATE.SPEAKING);
      if (!currentAiBubble) currentAiBubble = addBubble('ai', '');
    }
    audioPlayer.play24kPCM(evt.data).catch(console.error);
    return;
  }

  let msg;
  try { msg = JSON.parse(evt.data); } catch { return; }

  if (msg.type === 'text_chunk') {
    aiTextAccum.push(msg.text);
    if (!currentAiBubble) {
      if (currentState !== STATE.SPEAKING) setState(STATE.SPEAKING);
      currentAiBubble = addBubble('ai', '');
    }
    appendToBubble(currentAiBubble, msg.text);

  } else if (msg.type === 'turn_complete') {
    aiTextAccum = [];
    currentAiBubble = null;
    currentUserBubble = null;
    setState(STATE.IDLE);

  } else if (msg.type === 'error') {
    showError(msg.message || '語音服務發生錯誤');
    setState(STATE.IDLE);
  }
}

// ── AudioStreamer (AudioWorkletNode, 16kHz capture) ────────────────────────
class AudioStreamer {
  constructor() {
    this.audioContext = null;
    this.workletNode = null;
    this.mediaStream = null;
    this.isStreaming = false;
  }

  async start() {
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });

    this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 16000,
    });

    await this.audioContext.audioWorklet.addModule(
      '/static/liff/audio-processors/capture.worklet.js'
    );

    this.workletNode = new AudioWorkletNode(this.audioContext, 'audio-capture-processor');
    this.workletNode.port.onmessage = (event) => {
      if (!this.isStreaming) return;
      if (event.data.type !== 'audio') return;

      // Float32 → Int16 → send as binary
      const float32 = event.data.data;
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
      }
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(int16.buffer);
      }
    };

    const source = this.audioContext.createMediaStreamSource(this.mediaStream);
    source.connect(this.workletNode);
    this.isStreaming = true;
  }

  stop() {
    this.isStreaming = false;
    if (this.workletNode) { this.workletNode.disconnect(); this.workletNode = null; }
    if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach(t => t.stop()); this.mediaStream = null; }
  }
}

// ── AudioPlayer (AudioWorkletNode, 24kHz playback) ─────────────────────────
class AudioPlayer {
  constructor() {
    this.audioContext = null;
    this.workletNode = null;
    this.isInitialized = false;
  }

  async init() {
    if (this.isInitialized) return;
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 24000,  // Gemini outputs 24kHz PCM
    });
    await this.audioContext.audioWorklet.addModule(
      '/static/liff/audio-processors/playback.worklet.js'
    );
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor');
    this.workletNode.connect(this.audioContext.destination);
    this.isInitialized = true;
  }

  async play24kPCM(arrayBuffer) {
    await this.init();
    if (this.audioContext.state === 'suspended') await this.audioContext.resume();

    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
    this.workletNode.port.postMessage(float32);
  }

  interrupt() {
    if (this.workletNode) this.workletNode.port.postMessage('interrupt');
  }
}

// ── Push-to-talk button ───────────────────────────────────────────────────
function setupMicButton() {
  const onPressStart = async (e) => {
    e.preventDefault();

    if (currentState === STATE.SPEAKING) {
      // Interrupt AI playback
      audioPlayer.interrupt();
      aiTextAccum = [];
      currentAiBubble = null;
      currentUserBubble = null;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'interrupt' }));
      }
      setState(STATE.IDLE);
      return;
    }

    if (currentState !== STATE.IDLE || handsfreeEnabled) return;

    setState(STATE.RECORDING);
    currentUserBubble = addBubble('user', '🎤 說話中...');

    try {
      audioStreamer = new AudioStreamer();
      await audioStreamer.start();
    } catch {
      showError('請允許麥克風權限才能使用語音功能');
      setState(STATE.IDLE);
      return;
    }

    // Race: user released before getUserMedia resolved
    if (currentState !== STATE.RECORDING) {
      audioStreamer.stop();
      audioStreamer = null;
    }
  };

  const onPressEnd = (e) => {
    e.preventDefault();
    if (currentState !== STATE.RECORDING) return;

    if (audioStreamer) { audioStreamer.stop(); audioStreamer = null; }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'end_of_speech' }));
    }

    if (currentUserBubble) currentUserBubble.textContent = '（語音輸入）';
    setState(STATE.SPEAKING);
  };

  micBtn.addEventListener('mousedown', onPressStart);
  micBtn.addEventListener('mouseup', onPressEnd);
  micBtn.addEventListener('touchstart', onPressStart, { passive: false });
  micBtn.addEventListener('touchend', onPressEnd, { passive: false });

  // Hands-free toggle
  handsfreeSwitch.addEventListener('click', toggleHandsfree);
}

// ── Hands-free mode ────────────────────────────────────────────────────────
function toggleHandsfree() {
  handsfreeEnabled = !handsfreeEnabled;
  handsfreeSwitch.classList.toggle('on', handsfreeEnabled);
  handsfreeWarning.classList.toggle('visible', handsfreeEnabled);
  if (handsfreeEnabled) {
    startHandsfreeRecording();
  } else {
    stopHandsfreeRecording();
  }
}

async function startHandsfreeRecording() {
  if (currentState !== STATE.IDLE) return;
  setState(STATE.RECORDING);
  try {
    audioStreamer = new AudioStreamer();
    await audioStreamer.start();
  } catch {
    showError('請允許麥克風權限才能使用語音功能');
    setState(STATE.IDLE);
    handsfreeEnabled = false;
    handsfreeSwitch.classList.remove('on');
    handsfreeWarning.classList.remove('visible');
  }
}

function stopHandsfreeRecording() {
  if (audioStreamer) { audioStreamer.stop(); audioStreamer = null; }
  setState(STATE.IDLE);
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
    setStatus('🔊 AI 說話中，點擊打斷');
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
