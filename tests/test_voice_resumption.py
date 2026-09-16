"""測試：Live session 的 resume handle 保存與作廢（services/voice_live.py）

背景（2026-09-16 事故）：gemini-3.8-live 在 PTT 流程回 1007 Precondition check
failed，但在 session 死掉「之前」就先送出 session_resumption_update。舊的
main.py 迴圈不分青紅皂白把 handle 存起來，之後 15 分鐘（VOICE_RESUME_TTL）
內每次連線都帶著這個指向死 session 的 handle，全部回 1011 Internal error，
使用者被鎖在外面，而且每次重試成功連上又踩到 1007 時會再度毒化。
舊模型 gemini-3.1-flash-live-preview 在 1007 之前不發 handle，所以這個
潛伏的 bug 從來沒被踩到。

這裡守的是 bug class：
- 以錯誤結束的 session，其 handle 不得保存，已存的也要作廢
- 帶 handle 連不上時，丟掉 handle 不帶 handle 重試一次（且只重試一次）
- 正常結束（使用者掛斷）與 GoAway 仍要保存 handle，不能因為修 bug 把
  瀏覽器重連跟 10 分鐘回收重連一起弄壞
"""
import asyncio
import contextlib
import json
import re
from pathlib import Path

import pytest

from services.voice_live import (
    browser_to_gemini,
    gemini_to_browser,
    run_relay_with_resumption,
)
from tests.test_voice_live import FakeResponse

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── 假物件 ─────────────────────────────────────────────────────────────────

class FakeWS:
    """同時扮演瀏覽器輸入端與輸出端（正式環境是同一個 WebSocket 物件）。

    disconnect_after_events=False 時，事件用完後 receive() 永遠阻塞，
    模擬使用者頁面還開著——這樣 Gemini 端的錯誤才會「先」結束 relay。
    """

    def __init__(self, events=(), disconnect_after_events=False):
        self._events = list(events)
        self._disconnect = disconnect_after_events
        self.sent_text = []

    async def receive(self):
        if self._events:
            return self._events.pop(0)
        if self._disconnect:
            return {"type": "websocket.disconnect"}
        await asyncio.Event().wait()

    async def send_text(self, text):
        self.sent_text.append(json.loads(text))

    async def send_bytes(self, data):
        pass


class ScriptedLiveSession:
    """Gemini 端：送完排定的 responses 後，依 ending 決定行為。

    ending="error"：丟例外，模擬 1007 在 receive 階段殺掉 session
    ending="block"：永遠阻塞，等瀏覽器端先結束後被取消
    """

    def __init__(self, responses=(), ending="block"):
        self._responses = list(responses)
        self._ending = ending
        self.realtime_inputs = []

    async def send_realtime_input(self, **kwargs):
        self.realtime_inputs.append(kwargs)

    async def send_tool_response(self, **kwargs):
        pass

    def receive(self):
        responses, self._responses = self._responses, []
        ending = self._ending

        async def gen():
            for r in responses:
                yield r
            if ending == "error":
                raise RuntimeError("1007 None. Precondition check failed.")
            await asyncio.Event().wait()

        return gen()


class FakeConnector:
    """取代 client.aio.live.connect：記錄每次帶的 resume_handle。

    plan 依序是「連線成功時交出的 session」或「連線時要丟的例外」。
    """

    def __init__(self, plan):
        self._plan = list(plan)
        self.calls = []

    def __call__(self, resume_handle):
        self.calls.append(resume_handle)
        item = self._plan.pop(0)

        @contextlib.asynccontextmanager
        async def cm():
            if isinstance(item, BaseException):
                raise item
            yield item

        return cm()


def _run(connector, ws, state, store, user_id="U1"):
    return run_relay_with_resumption(
        connect=connector, websocket=ws, state=state,
        handle_store=store, user_id=user_id, now=lambda: 1000.0,
    )


def _state(**extra):
    base = {"interrupted": False, "handsfree": False, "turns": []}
    base.update(extra)
    return base


# ── relay 函式要標記失敗 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gemini_to_browser_marks_session_failed_on_receive_error():
    """1007 在 receive 階段發生時，必須留下失敗標記給上層判斷。"""
    state = _state()
    session = ScriptedLiveSession([FakeResponse(new_handle="H-dead")], ending="error")
    await gemini_to_browser(FakeWS(), session, state)
    assert state.get("session_failed") is True


@pytest.mark.asyncio
async def test_browser_to_gemini_marks_session_failed_on_send_error():
    """往已死的 session 送資料會失敗，同樣代表 session 不可恢復。"""

    class DeadSession:
        async def send_realtime_input(self, **kwargs):
            raise RuntimeError("1011 None. Internal error encountered.")

    state = _state()
    ws = FakeWS([{"type": "websocket.receive", "bytes": b"\x00\x01"}],
                disconnect_after_events=True)
    await browser_to_gemini(ws, DeadSession(), state)
    assert state.get("session_failed") is True


# ── 事故本身：以錯誤結束的 session 不得保存 handle ─────────────────────────

@pytest.mark.asyncio
async def test_handle_from_failed_session_is_not_persisted():
    """2026-09-16 事故的直接回歸測試。

    session 先收到 handle、接著被 1007 殺掉。舊迴圈會把這個 handle 存起來，
    之後每次連線都 1011。修正後不得保存。
    """
    store = {}
    connector = FakeConnector([
        ScriptedLiveSession([FakeResponse(new_handle="H-dead")], ending="error"),
    ])
    await _run(connector, FakeWS(), _state(), store)

    assert "U1" not in store, f"死掉的 session 的 handle 被保存了：{store}"


@pytest.mark.asyncio
async def test_failed_session_also_evicts_previously_stored_handle():
    """已經存著的舊 handle 也要一起作廢，否則下一次連線仍會帶著它。"""
    store = {"U1": {"handle": "H-old", "ts": 999.0}}
    state = _state(resume_handle="H-old")
    connector = FakeConnector([
        ScriptedLiveSession([FakeResponse(new_handle="H-dead")], ending="error"),
    ])
    await _run(connector, FakeWS(), state, store)

    assert "U1" not in store
    assert "resume_handle" not in state


# ── 帶 handle 連不上：丟掉 handle 重試一次 ─────────────────────────────────

@pytest.mark.asyncio
async def test_connect_failure_with_handle_retries_once_without_handle():
    """被毒化的 handle 讓連線直接 1011：丟掉它，不帶 handle 重連。"""
    store = {"U1": {"handle": "H-poisoned", "ts": 999.0}}
    state = _state(resume_handle="H-poisoned")
    connector = FakeConnector([
        RuntimeError("1011 None. Internal error encountered."),
        ScriptedLiveSession([], ending="block"),
    ])
    ws = FakeWS([], disconnect_after_events=True)
    await _run(connector, ws, state, store)

    assert connector.calls == ["H-poisoned", None], (
        f"應先帶 handle、失敗後不帶 handle 重試，實際：{connector.calls}"
    )


@pytest.mark.asyncio
async def test_connect_failure_without_handle_raises_immediately():
    """沒帶 handle 還連不上，代表不是 handle 的問題，不重試、直接往上拋。"""
    connector = FakeConnector([RuntimeError("1011 None. Internal error encountered.")])
    with pytest.raises(RuntimeError):
        await _run(connector, FakeWS(), _state(), {})
    assert connector.calls == [None]


@pytest.mark.asyncio
async def test_connect_retry_happens_only_once():
    """帶 handle 失敗、不帶 handle 也失敗：只試兩次就放棄，不能無限迴圈。"""
    store = {"U1": {"handle": "H-poisoned", "ts": 999.0}}
    connector = FakeConnector([
        RuntimeError("1011 None. Internal error encountered."),
        RuntimeError("1011 None. Internal error encountered."),
    ])
    with pytest.raises(RuntimeError):
        await _run(connector, FakeWS(), _state(resume_handle="H-poisoned"), store)

    assert connector.calls == ["H-poisoned", None]
    assert "U1" not in store


# ── 不能弄壞的既有行為 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_persisted_when_user_hangs_up_normally():
    """使用者正常掛斷：不算失敗，handle 要存起來。

    瀏覽器端先結束，Gemini 端被取消（CancelledError 不是 Exception，
    不會走進 except）。若誤判成失敗，15 分鐘內重開頁面接回對話的功能
    就會被這次修正一起弄壞。
    """

    class SlowDisconnectWS(FakeWS):
        async def receive(self):
            await asyncio.sleep(0.05)   # 讓 Gemini 端先把 handle 交出來
            return {"type": "websocket.disconnect"}

    store, state = {}, _state()
    session = ScriptedLiveSession([FakeResponse(new_handle="H-good")], ending="block")
    await _run(FakeConnector([session]), SlowDisconnectWS(), state, store)

    assert not state.get("session_failed")
    assert store.get("U1") == {"handle": "H-good", "ts": 1000.0}


@pytest.mark.asyncio
async def test_go_away_reconnects_with_new_handle():
    """GoAway（約 10 分鐘回收）時要帶新 handle 重連，這是 resumption 的本意。"""
    store = {}
    connector = FakeConnector([
        ScriptedLiveSession(
            [FakeResponse(new_handle="H-fresh"), FakeResponse(go_away=True)],
            ending="block",
        ),
        ScriptedLiveSession([], ending="error"),   # 第二段隨便結束即可
    ])
    await _run(connector, FakeWS(), _state(), store)

    assert connector.calls == [None, "H-fresh"]


# ── 結構守衛 ───────────────────────────────────────────────────────────────

def test_main_does_not_write_resume_handles_directly():
    """handle 的存取只能經過 run_relay_with_resumption。

    這次的 bug 就藏在 main.py 那段沒有測試的黏合程式碼裡。這條防止有人
    把迴圈搬回 main.py，讓保存邏輯再度脫離測試。
    """
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    offenders = [
        f"main.py:{i}: {line.strip()}"
        for i, line in enumerate(source.splitlines(), 1)
        if re.search(r"voice_resume_handles\s*\[[^\]]+\]\s*=", line)
    ]
    assert not offenders, "main.py 不可直接寫入 voice_resume_handles：\n" + "\n".join(offenders)
    assert "run_relay_with_resumption" in source
