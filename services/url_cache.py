"""爬取結果快取

同一個網址在一次互動裡最多會被爬三次：初次產生社群文案、按「英文貼文」、
按「詳細研究報告」。爬取是整條鏈最慢也最脆弱的一段（SingleFile 要啟動
headless Chromium、Firecrawl 按次計費），重爬純粹是浪費時間與錢。

沿用 ReportStore 的 FirestoreKVStore 模式：Firestore 不可用（本機無憑證、CI）
時整層降級為 no-op，行為與沒有快取時完全一致。

TTL 用 24 小時而不是比照報告的 7 天：報告是產出物，內容過期沒關係；
這裡存的是網頁當下的內容，新聞或會更新的頁面放太久會拿到舊資料。
24 小時已經足以涵蓋「傳網址 → 按按鈕」這個主要情境。
"""
import hashlib
import logging
import time
from typing import Optional

from .firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

URL_CACHE_COLLECTION = "url_cache"
CACHE_TTL_SECONDS = 24 * 60 * 60
DOC_ID_LENGTH = 20

# Firestore 單一文件上限 1 MiB。留足夠餘裕給其他欄位與編碼膨脹，
# 超過就不要快取（直接重爬），而不是讓寫入失敗。
MAX_CACHEABLE_BYTES = 700_000


class UrlCache:
    def __init__(self, store=None, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.store = store if store is not None else FirestoreKVStore(
            URL_CACHE_COLLECTION)
        self.ttl_seconds = ttl_seconds

    @property
    def available(self) -> bool:
        return self.store.is_available

    @staticmethod
    def make_key(url: str, mode: str = "normal") -> str:
        digest = hashlib.sha1(f"{url}:{mode}".encode("utf-8")).hexdigest()
        return digest[:DOC_ID_LENGTH]

    def get(self, url: str, mode: str = "normal") -> Optional[str]:
        """回傳未過期的快取內容，沒有或過期就回 None。

        快取層的任何問題都不該讓爬取失敗，所以這裡吞掉例外只記 log。
        """
        if not self.available:
            return None

        try:
            doc = self.store.load(self.make_key(url, mode))
        except Exception as e:
            logger.warning(f"URL cache read failed for {url}: {e}")
            return None

        if not doc:
            return None

        age = time.time() - doc.get("cached_at", 0)
        if age > self.ttl_seconds:
            logger.info(f"URL cache expired ({age:.0f}s) for {url}")
            return None

        text = doc.get("text")
        if not text:
            return None

        logger.info(f"URL cache hit ({age:.0f}s old) for {url}")
        return text

    def put(self, url: str, text: str, mode: str = "normal") -> bool:
        """寫入快取。回傳是否真的寫進去了（測試與 log 用）。

        空內容不快取——那通常代表這次爬取失敗，存起來會讓後續每次都拿到失敗結果。
        """
        if not self.available:
            return False

        if not text or not text.strip():
            return False

        size = len(text.encode("utf-8"))
        if size > MAX_CACHEABLE_BYTES:
            logger.info(
                f"URL content too large to cache ({size} bytes) for {url}")
            return False

        try:
            self.store.save(self.make_key(url, mode), {
                "url": url,
                "mode": mode,
                "text": text,
                "cached_at": time.time(),
            })
            return True
        except Exception as e:
            logger.warning(f"URL cache write failed for {url}: {e}")
            return False


# 模組層單例：loader.url 的每次爬取共用
_url_cache: Optional[UrlCache] = None


def get_url_cache() -> UrlCache:
    global _url_cache
    if _url_cache is None:
        _url_cache = UrlCache()
    return _url_cache
