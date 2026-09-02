"""測試：影片問答模式的判斷順序與狀態機

背景：影片模式攔截在 main.py 既有的訊息路由之前。攔截錯了會讓一般訊息
被當成影片提問（使用者收到「影片中沒有提到這個」這種莫名其妙的回覆），
或反過來讓影片提問掉回一般路徑。

最重要的一條是判斷順序：**脫離判斷必須在配額判斷之前**。
使用者貼新網址想換主題，不該因為影片配額用完就被擋下來——那是兩件不相干的事。
這是行為契約，不是實作細節。
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 必須在 import main 之前設好必要環境變數
os.environ.setdefault("ChannelSecret", "test-secret")
os.environ.setdefault("ChannelAccessToken", "test-token")
os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
os.environ.setdefault("LINE_USER_ID", "U-test-user")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

import main  # noqa: E402
from services.video_qa import VideoQASessions  # noqa: E402
from tests.fakes import FakeStore  # noqa: E402

USER = "U-test-user"
VIDEO = "https://www.youtube.com/watch?v=o8NiE3XMPrM"


@pytest.fixture(autouse=True)
def _fake_line_bot_api(monkeypatch):
    """main.line_bot_api 是模組層級的全域，只在 FastAPI startup 時被賦值一次，
    之後不會重置。誰先跑（例如 test_report_route.py 觸發過 TestClient startup）
    會讓它變成真物件，這支檔案不該依賴那個順序——不管其他檔案跑了什麼，
    一律換成假物件；monkeypatch 保證測試結束後自動還原成原本的值。
    """
    fake = MagicMock(reply_message=AsyncMock(), push_message=AsyncMock())
    monkeypatch.setattr(main, "line_bot_api", fake)
    yield fake


@pytest.fixture
def sessions():
    s = VideoQASessions(store=FakeStore())
    with patch.object(main, "get_video_qa_sessions", return_value=s):
        yield s


@pytest.fixture
def fake_event():
    event = MagicMock()
    event.reply_token = "reply-token"
    return event


@pytest.fixture
def no_network():
    """擋掉所有外呼：LINE、Gemini、用量記錄。"""
    with patch.object(main, "ask_youtube_video") as ask, \
         patch.object(main.LineService, "show_loading_animation", new=AsyncMock()), \
         patch.object(main, "_reply_with_overflow", new=AsyncMock()) as reply:
        ask.return_value = {
            "status": "success",
            "answer": "有的，在 1:24:40 提到定價。",
            "usage": {"model": "gemini-3.5-flash-lite", "prompt_tokens": 53,
                      "output_tokens": 638, "thinking_tokens": 0,
                      "tool_use_tokens": 2163, "total_tokens": 2854},
        }
        yield {"ask": ask, "reply": reply}


# --- 進入模式 ---

@pytest.mark.asyncio
async def test_enter_does_not_call_gemini(sessions, fake_event, no_network):
    """按下按鈕只寫 session，不該花錢。"""
    with patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        await main.handle_video_qa_enter_postback(
            fake_event, {"action": "video_qa", "url": VIDEO}, USER)
    assert sessions.get(USER)["url"] == VIDEO
    no_network["ask"].assert_not_called()


# --- 模式中的訊息路由 ---

@pytest.mark.asyncio
async def test_normal_text_is_handled_as_video_question(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is True
    no_network["ask"].assert_called_once()
    assert no_network["ask"].call_args[0][1] == "他有講到定價嗎？"


@pytest.mark.asyncio
async def test_not_in_mode_returns_false(fake_event, sessions, no_network):
    handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is False
    no_network["ask"].assert_not_called()


@pytest.mark.asyncio
async def test_url_message_exits_mode_and_returns_false(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    handled = await main.handle_video_qa_message(
        fake_event, USER, "https://example.com/article")
    assert handled is False, "貼網址應交還原路處理"
    assert sessions.get(USER) is None, "貼網址應離開影片模式"
    no_network["ask"].assert_not_called()


@pytest.mark.asyncio
async def test_slash_command_exits_mode_and_returns_false(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    handled = await main.handle_video_qa_message(fake_event, USER, "/list")
    assert handled is False
    assert sessions.get(USER) is None


@pytest.mark.asyncio
async def test_asking_bumps_the_counter(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    await main.handle_video_qa_message(fake_event, USER, "問題一")
    await main.handle_video_qa_message(fake_event, USER, "問題二")
    assert sessions.get(USER)["asked"] == 2


# --- 判斷順序（行為契約） ---

@pytest.mark.asyncio
async def test_exit_check_runs_before_budget_check(sessions, fake_event, no_network,
                                                   monkeypatch):
    """配額用完時，貼新網址仍必須能換主題。

    脫離與配額是兩件不相干的事。順序寫反的話，使用者會卡在一個
    每則訊息都被拒絕、又離不開的模式裡。
    """
    monkeypatch.setenv("VIDEO_QA_DAILY_BUDGET_USD", "0.0001")
    sessions.enter(USER, VIDEO)
    meter = MagicMock()
    meter.check_budget.return_value = (False, 0.0)
    with patch.object(main, "get_usage_meter", return_value=meter):
        handled = await main.handle_video_qa_message(
            fake_event, USER, "https://example.com/other")
    assert handled is False, "貼網址應交還原路，不該被配額擋住"
    assert sessions.get(USER) is None
    meter.check_budget.assert_not_called()


@pytest.mark.asyncio
async def test_over_budget_blocks_and_exits_mode(sessions, fake_event, no_network):
    """配額用完時不打 Gemini，並把使用者踢出模式。

    讓人卡在一個每則訊息都被拒絕的模式裡，比直接踢出去更糟。
    """
    sessions.enter(USER, VIDEO)
    meter = MagicMock()
    meter.check_budget.return_value = (False, 0.0)
    meter.spent_today.return_value = 0.30
    with patch.object(main, "get_usage_meter", return_value=meter), \
         patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is True
    no_network["ask"].assert_not_called()
    assert sessions.get(USER) is None


@pytest.mark.asyncio
async def test_usage_is_recorded_after_a_successful_answer(sessions, fake_event,
                                                           no_network):
    sessions.enter(USER, VIDEO)
    meter = MagicMock()
    meter.check_budget.return_value = (True, None)
    with patch.object(main, "get_usage_meter", return_value=meter):
        await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    meter.record.assert_called_once()
    assert meter.record.call_args[0][1] == "video_qa"


# --- 影片壞掉時的錯誤處理 ---

@pytest.mark.asyncio
async def test_non_429_error_exits_video_mode(sessions, fake_event, no_network):
    """影片下架／變私人這類不會自己好的錯誤必須清掉 session，否則接下來
    30 分鐘每則訊息都會被攔截、重試、再花一次 Vertex 呼叫卻注定失敗。"""
    sessions.enter(USER, VIDEO)
    no_network["ask"].return_value = {
        "status": "error", "error_message": "影片為私人或已移除，無法存取",
    }
    with patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is True
    assert sessions.get(USER) is None, "非 429 錯誤必須讓使用者離開影片問答模式"


@pytest.mark.asyncio
async def test_429_error_does_not_exit_video_mode(sessions, fake_event, no_network):
    """429 是暫時性的用量上限，值得重試——不該把使用者踢出模式，逼他重新
    按一次入口按鈕。"""
    sessions.enter(USER, VIDEO)
    no_network["ask"].return_value = {
        "status": "error", "rate_limited": True,
        "error_message": "Vertex AI 使用量已達上限，請稍後再試。建議等待 1-2 分鐘後重試。",
    }
    with patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is True
    assert sessions.get(USER) is not None, "429 是暫時性的，不該清掉 session"


# --- 離開模式 ---

@pytest.mark.asyncio
async def test_exit_postback_clears_session(sessions, fake_event):
    sessions.enter(USER, VIDEO)
    with patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        await main.handle_video_qa_exit_postback(fake_event, USER)
    assert sessions.get(USER) is None
