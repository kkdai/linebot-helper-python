"""測試：LIFF 語音助手 Live API 協定（services/voice_live.py）

背景：push-to-talk 原本在 end_of_speech 時呼叫 send_client_content(turn_complete=True)，
但 gemini-3.1-flash-live 規範中 send_client_content 只能用於連線初期塞入歷史，
不能在對話中送新訊息。正確作法：
- PTT 模式：停用自動 VAD，按下/放開分別送 activity_start / activity_end
- 免持模式：保留自動 VAD，由 Gemini 偵測說話結束
"""
import json

import pytest
from google.genai import types as live_types

from services.voice_live import (
    browser_to_gemini,
    build_live_config,
    build_system_instruction,
    gemini_to_browser,
)


# ── 假物件 ─────────────────────────────────────────────────────────────────

class FakeLiveSession:
    """記錄所有送往 Gemini Live 的呼叫。"""

    def __init__(self):
        self.calls = []

    async def send_realtime_input(self, **kwargs):
        self.calls.append(("send_realtime_input", kwargs))

    async def send_client_content(self, **kwargs):
        self.calls.append(("send_client_content", kwargs))

    def calls_named(self, name):
        return [kwargs for n, kwargs in self.calls if n == name]


class FakeBrowserWS:
    """模擬 FastAPI WebSocket：依序回傳排定的事件，之後回傳 disconnect。"""

    def __init__(self, events):
        self._events = list(events)

    async def receive(self):
        if self._events:
            return self._events.pop(0)
        return {"type": "websocket.disconnect"}


def _text_event(payload: dict) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def _audio_event(data: bytes) -> dict:
    return {"type": "websocket.receive", "bytes": data}


# ── 設定檔測試 ─────────────────────────────────────────────────────────────

def test_ptt_config_disables_automatic_vad():
    cfg = build_live_config(build_system_instruction(None, None), handsfree=False)
    assert cfg.realtime_input_config is not None
    assert cfg.realtime_input_config.automatic_activity_detection.disabled is True


def test_handsfree_config_keeps_automatic_vad():
    cfg = build_live_config(build_system_instruction(None, None), handsfree=True)
    ric = cfg.realtime_input_config
    assert ric is None or not (
        ric.automatic_activity_detection
        and ric.automatic_activity_detection.disabled
    )


def test_config_has_transcriptions_and_audio_modality():
    cfg = build_live_config(build_system_instruction(25.03, 121.56), handsfree=False)
    assert cfg.response_modalities == ["AUDIO"]
    assert cfg.input_audio_transcription is not None
    assert cfg.output_audio_transcription is not None


# ── browser_to_gemini 協定測試 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audio_bytes_forwarded_as_pcm():
    session = FakeLiveSession()
    ws = FakeBrowserWS([_audio_event(b"\x01\x02")])
    await browser_to_gemini(ws, session, {"handsfree": False, "interrupted": False})

    audio_calls = [
        k for k in session.calls_named("send_realtime_input") if "audio" in k
    ]
    assert len(audio_calls) == 1
    blob = audio_calls[0]["audio"]
    assert blob.data == b"\x01\x02"
    assert blob.mime_type == "audio/pcm;rate=16000"


@pytest.mark.asyncio
async def test_ptt_sends_activity_start_and_end():
    session = FakeLiveSession()
    ws = FakeBrowserWS([
        _text_event({"type": "start_of_speech"}),
        _audio_event(b"\x00\x00"),
        _text_event({"type": "end_of_speech"}),
    ])
    await browser_to_gemini(ws, session, {"handsfree": False, "interrupted": False})

    rt_calls = session.calls_named("send_realtime_input")
    assert any(
        isinstance(k.get("activity_start"), live_types.ActivityStart) for k in rt_calls
    ), "PTT 按下時應送出 activity_start"
    assert any(
        isinstance(k.get("activity_end"), live_types.ActivityEnd) for k in rt_calls
    ), "PTT 放開時應送出 activity_end"


@pytest.mark.asyncio
async def test_ptt_never_uses_send_client_content():
    """send_client_content 在 3.1 live 只能用於初始歷史，不可用於對話中。"""
    session = FakeLiveSession()
    ws = FakeBrowserWS([
        _text_event({"type": "start_of_speech"}),
        _text_event({"type": "end_of_speech"}),
    ])
    await browser_to_gemini(ws, session, {"handsfree": False, "interrupted": False})
    assert session.calls_named("send_client_content") == []


@pytest.mark.asyncio
async def test_handsfree_ignores_activity_events():
    """免持模式用自動 VAD，activity 信號不可送出（API 會報錯）。"""
    session = FakeLiveSession()
    ws = FakeBrowserWS([
        _text_event({"type": "start_of_speech"}),
        _text_event({"type": "end_of_speech"}),
    ])
    await browser_to_gemini(ws, session, {"handsfree": True, "interrupted": False})

    rt_calls = session.calls_named("send_realtime_input")
    assert all("activity_start" not in k and "activity_end" not in k for k in rt_calls)


# ── gemini_to_browser 下行測試 ─────────────────────────────────────────────

class FakeResponse:
    """模擬 Gemini Live 的單一 server event。"""

    def __init__(self, data=None, text=None, input_transcription=None, interrupted=None):
        self.data = data
        self.text = text
        if input_transcription is not None or interrupted is not None:
            sc = type("SC", (), {})()
            sc.interrupted = interrupted
            if input_transcription is not None:
                it = type("IT", (), {})()
                it.text = input_transcription
                sc.input_transcription = it
            else:
                sc.input_transcription = None
            self.server_content = sc
        else:
            self.server_content = None


class FakeTurnSession:
    """receive() 依序回傳排定的 turn（每個 turn 是 response list）；用完即結束。"""

    def __init__(self, turns):
        self._turns = list(turns)

    def receive(self):
        if not self._turns:
            raise RuntimeError("no more turns")  # 讓 relay loop 結束
        responses = self._turns.pop(0)

        async def gen():
            for r in responses:
                yield r
        return gen()


class FakeClientWS:
    """記錄送往瀏覽器的訊息。"""

    def __init__(self):
        self.sent_text = []
        self.sent_bytes = []

    async def send_text(self, text):
        self.sent_text.append(json.loads(text))

    async def send_bytes(self, data):
        self.sent_bytes.append(data)

    def messages_of_type(self, mtype):
        return [m for m in self.sent_text if m.get("type") == mtype]


@pytest.mark.asyncio
async def test_user_transcript_forwarded_to_browser():
    """使用者語音轉錄（input_transcription）要即時回傳前端顯示。"""
    ws = FakeClientWS()
    session = FakeTurnSession([
        [
            FakeResponse(input_transcription="今天天氣"),
            FakeResponse(input_transcription="如何"),
            FakeResponse(text="今天晴朗"),
        ],
    ])
    await gemini_to_browser(ws, session, {"interrupted": False}, push_fn=None)

    transcripts = ws.messages_of_type("user_transcript")
    assert transcripts, "應送出 user_transcript 事件"
    # 送累積全文，前端直接取代氣泡內容
    assert transcripts[-1]["text"] == "今天天氣如何"


@pytest.mark.asyncio
async def test_turn_complete_and_push_fn_called():
    ws = FakeClientWS()
    pushed = []

    async def push_fn(user_speech, ai_response):
        pushed.append((user_speech, ai_response))

    session = FakeTurnSession([
        [FakeResponse(input_transcription="你好"), FakeResponse(text="嗨，你好")],
    ])
    await gemini_to_browser(ws, session, {"interrupted": False}, push_fn=push_fn)

    assert ws.messages_of_type("turn_complete")
    assert pushed == [("你好", "嗨，你好")]


@pytest.mark.asyncio
async def test_gemini_interrupted_signal_forwarded_and_turn_discarded():
    """免持 barge-in：Gemini 送 interrupted 時要通知前端清 playback queue，
    且該輪不算完成（不送 turn_complete、不 push LINE）。"""
    ws = FakeClientWS()
    pushed = []

    async def push_fn(user_speech, ai_response):
        pushed.append((user_speech, ai_response))

    session = FakeTurnSession([
        [FakeResponse(text="我來回答"), FakeResponse(interrupted=True)],
    ])
    await gemini_to_browser(ws, session, {"interrupted": False}, push_fn=push_fn)

    assert ws.messages_of_type("interrupted"), "應送出 interrupted 事件給前端"
    assert not ws.messages_of_type("turn_complete")
    assert pushed == []


# ── system instruction ────────────────────────────────────────────────────

def test_system_instruction_includes_location_when_given():
    text = build_system_instruction(25.033, 121.565)
    assert "25.033" in text and "121.565" in text


def test_system_instruction_without_location():
    text = build_system_instruction(None, None)
    assert "未提供位置" in text
