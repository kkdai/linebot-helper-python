// ── Constants ─────────────────────────────────────────────────────────────
const GEMINI_WS_URL = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';
const MODEL = 'models/gemini-3.1-flash-live-preview';

// ── State ─────────────────────────────────────────────────────────────────
const STATE = { IDLE: 'idle', RECORDING: 'recording', SPEAKING: 'speaking' };
let currentState = STATE.IDLE;
let geminiWs = null;
let handsfreeEnabled = false;
let audioStreamer = null;
let audioPlayer = null;
let userId = null;
let userLat = null;
let userLng = null;
let currentAiBubble = null;
let currentUserBubble = null;
let aiTextAccum = [];
let userTextAccum = [];
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
    if (!liff.isLoggedIn()) {
      liff.login();
      return;
    }
    const profile = await liff.getProfile();
    userId = profile.userId;
    const loc = await getLocation();
    userLat = loc.lat || null;
    userLng = loc.lng || null;
    audioPlayer = new AudioPlayer();
    await connectToGemini();
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

// ── Ephemeral token + Gemini WebSocket ─────────────────────────────────────
async function connectToGemini() {
  setStatus('連線中...');
  try {
    let url = `/api/liff-token?user_id=${encodeURIComponent(userId)}`;
    if (userLat != null) url += `&lat=${userLat}`;
    if (userLng != null) url += `&lng=${userLng}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Token fetch failed: ${res.status}`);
    const { access_token } = await res.json();

    geminiWs = new WebSocket(`${GEMINI_WS_URL}?access_token=${encodeURIComponent(access_token)}`);

    geminiWs.onopen = () => {
      // Send setup — model is pre-configured in ephemeral token, but setup is required
      geminiWs.send(JSON.stringify({ setup: { model: MODEL } }));
    };

    geminiWs.onmessage = (evt) => handleGeminiMessage(evt);

    geminiWs.onerror = (e) => {
      console.error('Gemini WS error', e);
    };

    geminiWs.onclose = () => {
      if (connectAttempt < 3) {
        connectAttempt++;
        setStatus(`連線中斷，重連中… (${connectAttempt}/3)`);
        setTimeout(connectToGemini, 2000);
      } else {
        setStatus('連線失敗');
        showError('連線已中斷，請重新整理頁面');
      }
    };
  } catch (e) {
    console.error('connectToGemini error:', e);
    if (connectAttempt < 3) {
      connectAttempt++;
      setStatus(`連線失敗，重試中… (${connectAttempt}/3)`);
      setTimeout(connectToGemini, 2000);
    } else {
      showError('無法連線語音服務，請重新整理頁面');
    }
  }
}

// ── Gemini message handler ─────────────────────────────────────────────────
function handleGeminiMessage(evt) {
  let msg;
  try {
    msg = JSON.parse(evt.data);
  } catch {
    return;
  }

  // Setup complete
  if (msg.setupComplete) {
    connectAttempt = 0;
    setStatus('已連線，準備說話');
    return;
  }

  // Server content
  if (msg.serverContent) {
    const sc = msg.serverContent;

    // AI audio output
    if (sc.modelTurn && sc.modelTurn.parts) {
      for (const part of sc.modelTurn.parts) {
        if (part.inlineData && part.inlineData.data) {
          if (currentState !== STATE.SPEAKING) {
            setState(STATE.SPEAKING);
            if (!currentAiBubble) currentAiBubble = addBubble('ai', '');
          }
          audioPlayer.play(part.inlineData.data).catch(console.error);
        }
      }
    }

    // AI output transcription (text version of AI speech)
    if (sc.outputTranscription && sc.outputTranscription.text) {
      const t = sc.outputTranscription.text;
      aiTextAccum.push(t);
      if (!currentAiBubble) {
        if (currentState !== STATE.SPEAKING) setState(STATE.SPEAKING);
        currentAiBubble = addBubble('ai', '');
      }
      appendToBubble(currentAiBubble, t);
    }

    // Input transcription (user's speech-to-text)
    if (sc.inputTranscription && sc.inputTranscription.text) {
      const t = sc.inputTranscription.text;
      userTextAccum.push(t);
      if (currentUserBubble) {
        currentUserBubble.textContent = userTextAccum.join('');
      }
    }

    // Turn complete
    if (sc.turnComplete || sc.generationComplete) {
      handleTurnComplete();
    }
  }
}

async function handleTurnComplete() {
  const userText = userTextAccum.join('').trim();
  const aiText = aiTextAccum.join('').trim();
  aiTextAccum = [];
  userTextAccum = [];
  currentAiBubble = null;
  currentUserBubble = null;
  setState(STATE.IDLE);

  // Push conversation to LINE
  if (aiText && userId) {
    try {
      await fetch('/api/liff-turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, user_text: userText, ai_text: aiText }),
      });
    } catch (e) {
      console.warn('LINE push failed:', e);
    }
  }
}

// ── AudioStreamer (AudioWorkletNode) ───────────────────────────────────────
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

      const float32 = event.data.data;
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
      }
      const bytes = new Uint8Array(int16.buffer);
      let binary = '';
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
      const base64 = btoa(binary);

      if (geminiWs && geminiWs.readyState === WebSocket.OPEN) {
        geminiWs.send(JSON.stringify({
          realtimeInput: {
            audio: { mimeType: 'audio/pcm;rate=16000', data: base64 },
          },
        }));
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

// ── AudioPlayer (AudioWorkletNode, 24kHz) ─────────────────────────────────
class AudioPlayer {
  constructor() {
    this.audioContext = null;
    this.workletNode = null;
    this.gainNode = null;
    this.isInitialized = false;
  }

  async init() {
    if (this.isInitialized) return;
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 24000,  // Gemini outputs 24kHz
    });
    await this.audioContext.audioWorklet.addModule(
      '/static/liff/audio-processors/playback.worklet.js'
    );
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor');
    this.gainNode = this.audioContext.createGain();
    this.gainNode.gain.value = 1.0;
    this.workletNode.connect(this.gainNode);
    this.gainNode.connect(this.audioContext.destination);
    this.isInitialized = true;
  }

  async play(base64Audio) {
    await this.init();
    if (this.audioContext.state === 'suspended') await this.audioContext.resume();

    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    this.workletNode.port.postMessage(float32);
  }

  interrupt() {
    if (this.workletNode) this.workletNode.port.postMessage('interrupt');
  }

  destroy() {
    if (this.workletNode) { this.workletNode.disconnect(); this.workletNode = null; }
    if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
    this.isInitialized = false;
  }
}

// ── Push-to-talk button ───────────────────────────────────────────────────
function setupMicButton() {
  const onPressStart = async (e) => {
    e.preventDefault();

    if (currentState === STATE.SPEAKING) {
      // Interrupt AI
      audioPlayer.interrupt();
      aiTextAccum = [];
      userTextAccum = [];
      currentAiBubble = null;
      currentUserBubble = null;
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

    // Race condition: user released before getUserMedia resolved
    if (currentState !== STATE.RECORDING) {
      audioStreamer.stop();
      audioStreamer = null;
    }
  };

  const onPressEnd = (e) => {
    e.preventDefault();
    if (currentState !== STATE.RECORDING) return;

    if (audioStreamer) { audioStreamer.stop(); audioStreamer = null; }

    // Signal end of user speech
    if (geminiWs && geminiWs.readyState === WebSocket.OPEN) {
      geminiWs.send(JSON.stringify({ clientContent: { turnComplete: true } }));
    }

    if (currentUserBubble) currentUserBubble.textContent = '（語音輸入）';
    setState(STATE.SPEAKING);
  };

  micBtn.addEventListener('mousedown', onPressStart);
  micBtn.addEventListener('mouseup', onPressEnd);
  micBtn.addEventListener('touchstart', onPressStart, { passive: false });
  micBtn.addEventListener('touchend', onPressEnd, { passive: false });
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
  setState(STATE.IDLE);
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
  }
}

function stopHandsfreeRecording() {
  if (audioStreamer) { audioStreamer.stop(); audioStreamer = null; }
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
