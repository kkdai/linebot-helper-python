"""測試：LINE 單次訊息上限的溢位處理

背景：LINE 的 reply/push 單次都最多帶 5 則訊息。handle_url_message 原本結尾寫
`results[:5]`，每個網址剛好產生 5 則（carousel + 4 則平台文案），所以使用者
一次傳兩個網址時，第二個網址的爬取與 Gemini 呼叫都已經花掉了，產出的訊息卻被
直接截掉，什麼都收不到。

正確行為：前 5 則走 reply（不計 push 額度），其餘用 push 補送，一則都不能少。
"""
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("ChannelSecret", "test-secret")
os.environ.setdefault("ChannelAccessToken", "test-token")
os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
os.environ.setdefault("LINE_USER_ID", "U-test-user")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

from linebot.models import MessageEvent, TextMessage  # noqa: E402
from linebot.models.sources import SourceUser  # noqa: E402

import main  # noqa: E402


class FakeLineBotApi:
    def __init__(self, push_fails_on=()):
        self.replies = []
        self.pushes = []
        self._push_fails_on = set(push_fails_on)
        self._push_calls = 0

    async def reply_message(self, reply_token, messages):
        self.replies.append((reply_token, list(messages)))

    async def push_message(self, user_id, messages):
        self._push_calls += 1
        if self._push_calls in self._push_fails_on:
            raise RuntimeError("simulated push failure")
        self.pushes.append((user_id, list(messages)))

    # --- 測試輔助 ---
    @property
    def replied_messages(self):
        return [m for _, msgs in self.replies for m in msgs]

    @property
    def pushed_messages(self):
        return [m for _, msgs in self.pushes for m in msgs]

    @property
    def delivered(self):
        return self.replied_messages + self.pushed_messages


def _url_event(text):
    event = MessageEvent()
    event.reply_token = "rt-1"
    event.message = TextMessage(id="msg-1", text=text)
    event.source = SourceUser(user_id="U-alice")
    return event


# --- _chunk_messages ---

def test_chunk_messages_splits_by_line_limit():
    assert main._chunk_messages(list(range(12))) == [
        [0, 1, 2, 3, 4], [5, 6, 7, 8, 9], [10, 11]]


def test_chunk_messages_empty_and_exact_limit():
    assert main._chunk_messages([]) == []
    assert main._chunk_messages([1, 2, 3, 4, 5]) == [[1, 2, 3, 4, 5]]


# --- _reply_with_overflow ---

@pytest.mark.asyncio
async def test_within_limit_uses_reply_only_and_no_push():
    """單一網址剛好 5 則，必須全部走 reply，不能動用 push 額度。"""
    fake = FakeLineBotApi()
    msgs = [f"m{i}" for i in range(5)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", msgs, "test")

    assert fake.replied_messages == msgs
    assert fake.pushes == []


@pytest.mark.asyncio
async def test_overflow_goes_to_push_and_nothing_is_dropped():
    """兩個網址份量（10 則）：5 則 reply + 5 則 push，順序與內容都不能少。"""
    fake = FakeLineBotApi()
    msgs = [f"m{i}" for i in range(10)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", msgs, "test")

    assert fake.replied_messages == msgs[:5]
    assert fake.pushed_messages == msgs[5:]
    assert fake.delivered == msgs


@pytest.mark.asyncio
async def test_large_overflow_is_pushed_in_batches_of_five():
    fake = FakeLineBotApi()
    msgs = [f"m{i}" for i in range(13)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", msgs, "test")

    assert [len(batch) for _, batch in fake.pushes] == [5, 3]
    assert fake.delivered == msgs


@pytest.mark.asyncio
async def test_empty_messages_sends_nothing():
    fake = FakeLineBotApi()
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", [], "test")

    assert fake.replies == []
    assert fake.pushes == []


@pytest.mark.asyncio
async def test_missing_user_id_still_replies_and_warns(caplog):
    """沒有 user_id 就補不了 push，但 reply 仍要送出，且溢位要留下紀錄。"""
    fake = FakeLineBotApi()
    msgs = [f"m{i}" for i in range(8)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), None, msgs, "test")

    assert fake.replied_messages == msgs[:5]
    assert fake.pushes == []
    assert "Dropped 3 overflow message(s)" in caplog.text


@pytest.mark.asyncio
async def test_one_failed_push_batch_does_not_block_the_rest():
    """單批 push 失敗不能讓後面的批次一起消失。"""
    fake = FakeLineBotApi(push_fails_on=(1,))
    msgs = [f"m{i}" for i in range(15)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", msgs, "test")

    assert fake.replied_messages == msgs[:5]
    # 第一批 push（m5-m9）失敗，第二批（m10-m14）仍要送達
    assert fake.pushed_messages == msgs[10:]


@pytest.mark.asyncio
async def test_reply_failure_falls_back_to_push_when_user_id_present():
    """reply token 過期（影片問答常見，答案算 26–53 秒）不能讓已經算好的答案
    人間蒸發——花的錢跟算出的結果都還在，改用 push 補送，一則都不能少。"""
    class FailingReplyApi(FakeLineBotApi):
        async def reply_message(self, reply_token, messages):
            raise RuntimeError("reply token expired")

    fake = FailingReplyApi()
    msgs = [f"m{i}" for i in range(3)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", msgs, "test")

    assert fake.replies == []
    assert fake.pushed_messages == msgs


@pytest.mark.asyncio
async def test_reply_failure_with_overflow_pushes_everything():
    """reply 失敗時要退回去補送的是全部訊息，不是只有本來要走 reply 的前 5 則。"""
    class FailingReplyApi(FakeLineBotApi):
        async def reply_message(self, reply_token, messages):
            raise RuntimeError("reply token expired")

    fake = FailingReplyApi()
    msgs = [f"m{i}" for i in range(8)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), "U-alice", msgs, "test")

    assert fake.replies == []
    assert fake.pushed_messages == msgs


@pytest.mark.asyncio
async def test_reply_failure_without_user_id_is_logged_not_crashed(caplog):
    """沒有 user_id 就補不了 push，但不能讓例外往外炸——留紀錄就好。"""
    class FailingReplyApi(FakeLineBotApi):
        async def reply_message(self, reply_token, messages):
            raise RuntimeError("reply token expired")

    fake = FailingReplyApi()
    msgs = [f"m{i}" for i in range(3)]
    with patch.object(main, "line_bot_api", fake):
        await main._reply_with_overflow(_url_event("x"), None, msgs, "test")

    assert fake.pushes == []
    assert "reply token expired" in caplog.text


@pytest.mark.asyncio
async def test_push_in_chunks_uses_supplied_api_client():
    """/hn /hf 各自帶不同的 channel token，要能指定 client 而不是走全域那顆。"""
    default_api = FakeLineBotApi()
    other_api = FakeLineBotApi()
    msgs = [f"m{i}" for i in range(7)]

    with patch.object(main, "line_bot_api", default_api):
        await main._push_in_chunks("U-alice", msgs, "test", api=other_api)

    assert default_api.pushes == []
    assert other_api.pushed_messages == msgs
    assert [len(batch) for _, batch in other_api.pushes] == [5, 2]


# --- handle_url_message 端到端 ---

@pytest.mark.asyncio
async def test_two_urls_deliver_both_carousels():
    """回歸測試：兩個網址時，第二個網址的內容不能被截掉。"""
    fake = FakeLineBotApi()
    posts = {
        "title": "標題", "summary_analysis": "摘要",
        "facebook": "FB", "linkedin": "LI", "threads": "TH", "twitter": "TW",
    }

    class NoBookmarkService:
        available = False

    with patch.object(main, "line_bot_api", fake), \
         patch.object(main, "load_url", new=AsyncMock(return_value="內容")), \
         patch.object(main, "generate_social_media_posts", return_value=posts), \
         patch.object(main, "get_bookmark_service", return_value=NoBookmarkService()):
        await main.handle_url_message(
            _url_event("x"),
            ["https://a.example.com/1", "https://b.example.com/2"])

    # 每個網址 5 則（carousel + 4 則平台文案），兩個網址共 10 則，一則都不能少
    assert len(fake.delivered) == 10
    alt_texts = [getattr(m, "alt_text", None) for m in fake.delivered]
    assert alt_texts.count("📝 社群爆款文案摘要") == 2

    delivered_text = "\n".join(
        m.text for m in fake.delivered if hasattr(m, "text"))
    for url in ("https://a.example.com/1", "https://b.example.com/2"):
        assert url in delivered_text


@pytest.mark.asyncio
async def test_single_url_still_fits_in_one_reply():
    """常見的單一網址情境不能因為這個修法開始消耗 push 額度。"""
    fake = FakeLineBotApi()
    posts = {
        "title": "標題", "summary_analysis": "摘要",
        "facebook": "FB", "linkedin": "LI", "threads": "TH", "twitter": "TW",
    }

    class NoBookmarkService:
        available = False

    with patch.object(main, "line_bot_api", fake), \
         patch.object(main, "load_url", new=AsyncMock(return_value="內容")), \
         patch.object(main, "generate_social_media_posts", return_value=posts), \
         patch.object(main, "get_bookmark_service", return_value=NoBookmarkService()):
        await main.handle_url_message(_url_event("x"), ["https://a.example.com/1"])

    assert len(fake.replied_messages) == 5
    assert fake.pushes == []


# --- 影片問答入口按鈕（quickReply 只從 reply 陣列最後一則渲染） ---

@pytest.mark.asyncio
async def test_youtube_url_quick_reply_is_on_the_last_message():
    """LINE 只從 reply 陣列的『最後一則』渲染 quickReply。掛在 carousel（第一則）
    上會被後面 4 則文字訊息蓋掉，整個入口按鈕就形同不存在。"""
    fake = FakeLineBotApi()
    posts = {
        "title": "標題", "summary_analysis": "摘要",
        "facebook": "FB", "linkedin": "LI", "threads": "TH", "twitter": "TW",
    }
    youtube_url = "https://www.youtube.com/watch?v=abc12345678"

    class NoBookmarkService:
        available = False

    with patch.object(main, "line_bot_api", fake), \
         patch.object(main, "load_url", new=AsyncMock(return_value="內容")), \
         patch.object(main, "generate_social_media_posts", return_value=posts), \
         patch.object(main, "get_bookmark_service", return_value=NoBookmarkService()):
        await main.handle_url_message(_url_event("x"), [youtube_url])

    delivered = fake.delivered
    assert len(delivered) == 5
    quick_replies = [getattr(m, "quick_reply", None) for m in delivered]
    assert quick_replies[:-1] == [None, None, None, None], \
        "只有最後一則能帶 quickReply，前面幾則帶了也不會被 LINE 渲染"
    assert quick_replies[-1] is not None, "最後一則必須帶 quickReply，不然按鈕整個不會出現"
    data = json.loads(quick_replies[-1].items[0].action.data)
    assert data == {"action": "video_qa", "url": youtube_url}


@pytest.mark.asyncio
async def test_non_youtube_url_has_no_quick_reply_anywhere():
    """非 YouTube 網址不該出現「問這部影片」入口。"""
    fake = FakeLineBotApi()
    posts = {
        "title": "標題", "summary_analysis": "摘要",
        "facebook": "FB", "linkedin": "LI", "threads": "TH", "twitter": "TW",
    }

    class NoBookmarkService:
        available = False

    with patch.object(main, "line_bot_api", fake), \
         patch.object(main, "load_url", new=AsyncMock(return_value="內容")), \
         patch.object(main, "generate_social_media_posts", return_value=posts), \
         patch.object(main, "get_bookmark_service", return_value=NoBookmarkService()):
        await main.handle_url_message(_url_event("x"), ["https://a.example.com/1"])

    delivered = fake.delivered
    assert len(delivered) == 5
    assert all(getattr(m, "quick_reply", None) is None for m in delivered)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
