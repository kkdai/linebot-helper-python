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


# ── system instruction ────────────────────────────────────────────────────

def test_system_instruction_includes_location_when_given():
    text = build_system_instruction(25.033, 121.565)
    assert "25.033" in text and "121.565" in text


def test_system_instruction_without_location():
    text = build_system_instruction(None, None)
    assert "未提供位置" in text
