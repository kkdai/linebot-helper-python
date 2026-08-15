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
    build_voice_tools,
    gemini_to_browser,
    make_tool_handler,
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

class FakeFunctionCall:
    def __init__(self, id, name, args):
        self.id = id
        self.name = name
        self.args = args


class FakeResponse:
    """模擬 Gemini Live 的單一 server event。"""

    def __init__(self, data=None, text=None, input_transcription=None,
                 interrupted=None, function_calls=None,
                 new_handle=None, go_away=False):
        self.data = data
        self.text = text
        if new_handle is not None:
            sru = type("SRU", (), {})()
            sru.resumable = True
            sru.new_handle = new_handle
            self.session_resumption_update = sru
        else:
            self.session_resumption_update = None
        if go_away:
            ga = type("GA", (), {})()
            ga.time_left = "10s"
            self.go_away = ga
        else:
            self.go_away = None
        if function_calls is not None:
            tc = type("TC", (), {})()
            tc.function_calls = function_calls
            self.tool_call = tc
        else:
            self.tool_call = None
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
        self.tool_responses = []

    async def send_tool_response(self, function_responses):
        self.tool_responses.append(function_responses)

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


# ── Live 工具測試 ──────────────────────────────────────────────────────────

def test_voice_tools_include_google_search_and_maps():
    tools = build_voice_tools()
    assert any(getattr(t, "google_search", None) is not None for t in tools), \
        "應包含 Google Search grounding"
    fn_names = [
        fd.name
        for t in tools
        for fd in (getattr(t, "function_declarations", None) or [])
    ]
    assert "search_nearby_places" in fn_names


def test_live_config_carries_tools():
    tools = build_voice_tools()
    cfg = build_live_config(build_system_instruction(None, None),
                            handsfree=False, tools=tools)
    assert cfg.tools == tools


@pytest.mark.asyncio
async def test_tool_call_executes_handler_and_sends_response():
    ws = FakeClientWS()
    handled = []

    async def tool_handler(name, args):
        handled.append((name, args))
        return {"status": "success", "places": "好吃餐廳"}

    session = FakeTurnSession([
        [FakeResponse(function_calls=[
            FakeFunctionCall(id="fc-1", name="search_nearby_places",
                             args={"place_type": "restaurant"}),
        ])],
    ])
    await gemini_to_browser(ws, session, {"interrupted": False},
                            push_fn=None, tool_handler=tool_handler)

    assert handled == [("search_nearby_places", {"place_type": "restaurant"})]
    assert len(session.tool_responses) == 1
    fr = session.tool_responses[0][0]
    assert fr.id == "fc-1"
    assert fr.name == "search_nearby_places"
    assert fr.response["status"] == "success"


@pytest.mark.asyncio
async def test_tool_call_only_turn_does_not_emit_turn_complete():
    """tool_call 造成的 turn 中斷不算一輪完成，不應讓前端回到待機。"""
    ws = FakeClientWS()

    async def tool_handler(name, args):
        return {"status": "success"}

    session = FakeTurnSession([
        [FakeResponse(function_calls=[
            FakeFunctionCall(id="fc-1", name="search_nearby_places", args={}),
        ])],
    ])
    await gemini_to_browser(ws, session, {"interrupted": False},
                            push_fn=None, tool_handler=tool_handler)
    assert not ws.messages_of_type("turn_complete")


@pytest.mark.asyncio
async def test_make_tool_handler_maps_requires_coordinates(monkeypatch):
    handler = make_tool_handler(lat=None, lng=None)
    result = await handler("search_nearby_places", {"place_type": "restaurant"})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_make_tool_handler_maps_calls_search(monkeypatch):
    captured = {}

    def fake_search(latitude, longitude, place_type="restaurant", custom_query=None, **kw):
        captured.update(latitude=latitude, longitude=longitude, place_type=place_type)
        return {"status": "success", "places": "測試結果"}

    monkeypatch.setattr("services.voice_live.search_nearby_places", fake_search)
    handler = make_tool_handler(lat=25.03, lng=121.56)
    result = await handler("search_nearby_places", {"place_type": "parking"})

    assert result["status"] == "success"
    assert captured == {"latitude": 25.03, "longitude": 121.56, "place_type": "parking"}


@pytest.mark.asyncio
async def test_make_tool_handler_unknown_function():
    handler = make_tool_handler(lat=25.03, lng=121.56)
    result = await handler("not_a_tool", {})
    assert result["status"] == "error"


# ── Session 管理測試 ───────────────────────────────────────────────────────

def test_config_enables_resumption_and_compression():
    cfg = build_live_config(build_system_instruction(None, None), handsfree=False)
    assert cfg.session_resumption is not None
    assert cfg.context_window_compression is not None
    assert cfg.context_window_compression.sliding_window is not None


def test_config_carries_resume_handle():
    cfg = build_live_config(build_system_instruction(None, None),
                            handsfree=False, resume_handle="handle-123")
    assert cfg.session_resumption.handle == "handle-123"


@pytest.mark.asyncio
async def test_resumption_handle_captured_into_state():
    ws = FakeClientWS()
    state = {"interrupted": False}
    session = FakeTurnSession([
        [FakeResponse(new_handle="h-42"), FakeResponse(text="嗨")],
    ])
    await gemini_to_browser(ws, session, state, push_fn=None)
    assert state["resume_handle"] == "h-42"


@pytest.mark.asyncio
async def test_go_away_sets_flag_and_stops_relay():
    """收到 GoAway 要結束 relay 讓外層用 handle 重連，不能等連線被硬斷。"""
    ws = FakeClientWS()
    state = {"interrupted": False}
    session = FakeTurnSession([
        [FakeResponse(go_away=True)],
        [FakeResponse(text="這輪不該被讀到")],
    ])
    await gemini_to_browser(ws, session, state, push_fn=None)

    assert state.get("go_away") is True
    assert len(session._turns) == 1, "GoAway 後應立即返回，不再讀下一輪"
    assert not ws.messages_of_type("error")


# ── system instruction ────────────────────────────────────────────────────

def test_system_instruction_includes_location_when_given():
    text = build_system_instruction(25.033, 121.565)
    assert "25.033" in text and "121.565" in text


def test_system_instruction_without_location():
    text = build_system_instruction(None, None)
    assert "未提供位置" in text
