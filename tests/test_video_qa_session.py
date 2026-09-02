"""測試：影片問答模式的狀態

背景：spec 原本規劃包一層 services/session_manager.py，實作前檢視其內部後改為
直接用 FirestoreKVStore——SessionManager 是繞著「一個 Gemini chat 物件 +
會裁切的對話歷史」設計的，有兩個會實際出錯的摩擦點：
_persist_session() 不持久化 metadata（網址重啟後消失）、
add_to_history() 會裁掉舊訊息（網址放 history[0] 會在第 N 次提問後被裁掉）。

脫離條件刻意用啟發式而非 LLM 判斷意圖：後者要多打一次 Gemini，
而誤判代價很低（使用者再問一次即可）。
"""
import time

import pytest

from services.video_qa import VideoQASessions, should_exit_video_mode
from tests.fakes import FakeStore, UnavailableStore

USER = "U-test-user"
VIDEO = "https://www.youtube.com/watch?v=o8NiE3XMPrM"


# --- session 生命週期 ---

def test_enter_then_get_returns_video_url():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    assert s.get(USER)["url"] == VIDEO


def test_get_returns_none_when_not_in_mode():
    assert VideoQASessions(store=FakeStore()).get(USER) is None


def test_exit_clears_session():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    assert s.exit(USER) is True
    assert s.get(USER) is None


def test_exit_when_not_in_mode_returns_false():
    assert VideoQASessions(store=FakeStore()).exit(USER) is False


def test_session_expires_after_ttl():
    s = VideoQASessions(store=FakeStore(), ttl_seconds=0)
    s.enter(USER, VIDEO)
    time.sleep(0.01)
    assert s.get(USER) is None


def test_session_is_per_user():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    assert s.get("U-someone-else") is None


def test_video_url_survives_restart():
    """網址必須撐過 instance 重啟——這正是不用 SessionManager 的原因之一。"""
    store = FakeStore()
    VideoQASessions(store=store).enter(USER, VIDEO)
    assert VideoQASessions(store=store).get(USER)["url"] == VIDEO


def test_bump_increments_ask_count_and_renews_ttl():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    s.bump(USER)
    s.bump(USER)
    assert s.get(USER)["asked"] == 2


def test_entering_a_new_video_replaces_the_old_one():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    s.bump(USER)
    other = "https://www.youtube.com/watch?v=LxvErFkBXPk"
    s.enter(USER, other)
    assert s.get(USER)["url"] == other
    assert s.get(USER)["asked"] == 0


def test_bump_renews_ttl():
    """bump() must update last_active to extend the TTL, not just increment asked.

    Without this renewal, a user asking many questions about one video would have
    the session expire mid-conversation. This test verifies the renewal happens.
    """
    ttl = 0.15  # 150ms — large enough for reliable timing
    s = VideoQASessions(store=FakeStore(), ttl_seconds=ttl)
    s.enter(USER, VIDEO)

    # Wait partway through TTL
    time.sleep(0.08)

    # Bump should renew the session (set last_active to now)
    s.bump(USER)

    # Wait past the original TTL from enter(), but not past the new TTL from bump()
    # Original enter was at t=0, would expire at t=0.15
    # But bump renewed at t=0.08, so now expires at t=0.08+0.15=0.23
    # Total elapsed is 0.08 + 0.1 = 0.18, which is < 0.23
    time.sleep(0.10)

    # Session should still be active (wouldn't be without the renewal)
    assert s.get(USER) is not None


def test_store_unavailable_degrades_to_not_in_mode():
    """Firestore 掛掉時退化成「不在影片模式」，訊息照原路走，不會壞掉。"""
    s = VideoQASessions(store=UnavailableStore())
    s.enter(USER, VIDEO)
    assert s.get(USER) is None


# --- 脫離判斷（啟發式） ---

@pytest.mark.parametrize("text", [
    "https://example.com/article",
    "看看這個 https://www.youtube.com/watch?v=abc",
    "/list",
    "/save",
])
def test_messages_that_exit_video_mode(text):
    assert should_exit_video_mode(text) is True


@pytest.mark.parametrize("text", [
    "他有講到定價嗎？",
    "XR 眼鏡那段在哪裡？",
    "第三點再說詳細一點",
    "1:24:40 那邊在講什麼",
])
def test_messages_that_stay_in_video_mode(text):
    assert should_exit_video_mode(text) is False


def test_empty_message_stays_in_mode():
    assert should_exit_video_mode("") is False
