"""測試：爬取結果快取

背景：同一個網址在一次互動裡最多被爬三次（初次社群文案、英文貼文、研究報告），
每次都重跑 SingleFile subprocess 或按次計費的 Firecrawl。快取包在 load_url
最外層，四個呼叫點自動受惠。

重點是「快取壞掉不能讓爬取壞掉」：Firestore 不可用、讀寫例外、內容過大，
都要安靜降級成直接爬。
"""
import time
from unittest.mock import AsyncMock, patch

import pytest

from services.url_cache import (
    MAX_CACHEABLE_BYTES,
    UrlCache,
)
from tests.fakes import FakeStore, UnavailableStore

URL = "https://example.com/article"
TEXT = "爬回來的文章內容"


# --- UrlCache 本身 ---

def test_miss_returns_none():
    cache = UrlCache(store=FakeStore())
    assert cache.get(URL) is None


def test_put_then_get_roundtrip():
    cache = UrlCache(store=FakeStore())
    assert cache.put(URL, TEXT) is True
    assert cache.get(URL) == TEXT


def test_expired_entry_is_treated_as_miss():
    store = FakeStore()
    cache = UrlCache(store=store, ttl_seconds=60)
    cache.put(URL, TEXT)

    # 手動把 cached_at 往前推到超過 TTL
    key = UrlCache.make_key(URL)
    doc = store.load(key)
    doc["cached_at"] = time.time() - 120
    store.save(key, doc)

    assert cache.get(URL) is None


def test_empty_text_is_not_cached():
    """空內容通常代表這次爬取失敗，存起來會讓後續每次都拿到失敗結果。"""
    cache = UrlCache(store=FakeStore())
    assert cache.put(URL, "") is False
    assert cache.put(URL, "   \n ") is False
    assert cache.get(URL) is None


def test_oversized_content_is_not_cached():
    """超過 Firestore 文件上限就別寫，而不是讓寫入失敗。"""
    cache = UrlCache(store=FakeStore())
    huge = "a" * (MAX_CACHEABLE_BYTES + 1)
    assert cache.put(URL, huge) is False
    assert cache.get(URL) is None


def test_mode_is_part_of_the_cache_key():
    """YouTube 的 normal/detail/twitter 產出的是不同內容，不能互相汙染。"""
    cache = UrlCache(store=FakeStore())
    cache.put(URL, "一般摘要", mode="normal")
    cache.put(URL, "推特文案", mode="twitter")

    assert cache.get(URL, mode="normal") == "一般摘要"
    assert cache.get(URL, mode="twitter") == "推特文案"
    assert cache.get(URL, mode="detail") is None


def test_unavailable_store_degrades_to_no_op():
    """本機無憑證／CI：不快取但也不能爆。"""
    cache = UrlCache(store=UnavailableStore())
    assert cache.available is False
    cache.put(URL, TEXT)
    assert cache.get(URL) is None


def test_store_exceptions_are_swallowed():
    """快取層的問題不該讓爬取失敗。"""
    class ExplodingStore(FakeStore):
        def load(self, key):
            raise RuntimeError("firestore down")

        def save(self, key, doc):
            raise RuntimeError("firestore down")

    cache = UrlCache(store=ExplodingStore())
    assert cache.get(URL) is None
    assert cache.put(URL, TEXT) is False


# --- load_url 的快取包裝 ---

@pytest.fixture
def fake_cache():
    return UrlCache(store=FakeStore())


@pytest.mark.asyncio
async def test_second_load_does_not_recrawl(fake_cache):
    """同一個網址第二次呼叫要吃快取，不能再跑一次爬蟲。"""
    from loader import url as url_module

    crawl = AsyncMock(return_value=TEXT)
    with patch.object(url_module, "_load_url_uncached", new=crawl), \
         patch("services.url_cache.get_url_cache", return_value=fake_cache):
        first = await url_module.load_url(URL)
        second = await url_module.load_url(URL)

    assert first == second == TEXT
    assert crawl.await_count == 1


@pytest.mark.asyncio
async def test_use_cache_false_forces_a_recrawl(fake_cache):
    from loader import url as url_module

    crawl = AsyncMock(return_value=TEXT)
    with patch.object(url_module, "_load_url_uncached", new=crawl), \
         patch("services.url_cache.get_url_cache", return_value=fake_cache):
        await url_module.load_url(URL)
        await url_module.load_url(URL, use_cache=False)

    assert crawl.await_count == 2


@pytest.mark.asyncio
async def test_failed_crawl_is_not_cached(fake_cache):
    """爬取拋例外時不能留下快取，否則下次會直接吃到壞結果。"""
    from loader import url as url_module

    crawl = AsyncMock(side_effect=Exception("all methods failed"))
    with patch.object(url_module, "_load_url_uncached", new=crawl), \
         patch("services.url_cache.get_url_cache", return_value=fake_cache):
        with pytest.raises(Exception, match="all methods failed"):
            await url_module.load_url(URL)

    assert fake_cache.get(URL) is None


@pytest.mark.asyncio
async def test_cache_init_failure_still_crawls():
    """快取初始化失敗只是沒有快取，不能讓爬取整個失敗。"""
    from loader import url as url_module

    crawl = AsyncMock(return_value=TEXT)
    with patch.object(url_module, "_load_url_uncached", new=crawl), \
         patch("services.url_cache.get_url_cache",
               side_effect=RuntimeError("no credentials")):
        result = await url_module.load_url(URL)

    assert result == TEXT
    assert crawl.await_count == 1


@pytest.mark.asyncio
async def test_youtube_mode_is_passed_through_to_the_cache(fake_cache):
    """不同 mode 要各自爬各自快取，不能互相覆蓋。"""
    from loader import url as url_module

    crawl = AsyncMock(side_effect=lambda u, m: f"content-{m}")
    with patch.object(url_module, "_load_url_uncached", new=crawl), \
         patch("services.url_cache.get_url_cache", return_value=fake_cache):
        normal = await url_module.load_url(URL, youtube_mode="normal")
        twitter = await url_module.load_url(URL, youtube_mode="twitter")
        normal_again = await url_module.load_url(URL, youtube_mode="normal")

    assert normal == "content-normal"
    assert twitter == "content-twitter"
    assert normal_again == "content-normal"
    assert crawl.await_count == 2  # 第三次吃快取


# --- 端到端：同一個網址在整條互動裡只該爬一次 ---

@pytest.mark.asyncio
async def test_url_is_crawled_once_across_social_post_and_english_post(fake_cache):
    """傳網址 → 按「英文貼文」：兩段流程共用同一份爬取結果。

    這是 P1-3 的重點：英文貼文與研究報告先前各自重爬一次同樣的網址。
    """
    import os
    os.environ.setdefault("ChannelSecret", "test-secret")
    os.environ.setdefault("ChannelAccessToken", "test-token")
    os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
    os.environ.setdefault("LINE_USER_ID", "U-test-user")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

    from linebot.models import MessageEvent, PostbackEvent, TextMessage
    from linebot.models.sources import SourceUser

    import main
    from loader import url as url_module

    crawl = AsyncMock(return_value=TEXT)
    posts = {
        "title": "標題", "summary_analysis": "摘要",
        "facebook": "FB", "linkedin": "LI", "threads": "TH", "twitter": "TW",
    }
    posts_en = {"facebook": "FB", "linkedin": "LI",
                "threads": "TH", "twitter": "TW"}

    class NoBookmarkService:
        available = False

    class StubBookmarkService:
        available = True

        def get_bookmark(self, user_id, doc_id):
            return {"url": URL, "title": "標題"}

    class FakeApi:
        def __init__(self):
            self.sent = []

        async def reply_message(self, token, messages):
            self.sent.extend(messages)

        async def push_message(self, user_id, messages):
            self.sent.extend(messages)

    fake_api = FakeApi()

    msg_event = MessageEvent()
    msg_event.reply_token = "rt-1"
    msg_event.message = TextMessage(id="m1", text=URL)
    msg_event.source = SourceUser(user_id="U-alice")

    pb_event = PostbackEvent()
    pb_event.reply_token = "rt-2"
    pb_event.source = SourceUser(user_id="U-alice")

    with patch.object(url_module, "_load_url_uncached", new=crawl), \
         patch("services.url_cache.get_url_cache", return_value=fake_cache), \
         patch.object(main, "line_bot_api", fake_api), \
         patch.object(main, "generate_social_media_posts", return_value=posts), \
         patch.object(main, "generate_social_media_posts_en", return_value=posts_en), \
         patch.object(main, "get_bookmark_service",
                      side_effect=[NoBookmarkService(), StubBookmarkService()]):
        await main.handle_url_message(msg_event, [URL])
        await main.handle_english_post_postback(
            pb_event, {"id": "doc-1"}, "U-alice")

    assert crawl.await_count == 1, "英文貼文不該重爬同一個網址"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
