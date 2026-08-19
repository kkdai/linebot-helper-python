"""書籤/稍後讀服務

規格：docs/superpowers/specs/2026-08-13-bookmark-system-design.md

兩種寫入路徑：
- /save 指令 → save_direct（saved=True）
- 社群貼文 carousel 產生時 → save_candidate（saved=False），
  使用者按「儲存書籤」postback → confirm_save 翻成 saved=True

doc id = sha1(user_id + url) 前 20 碼：同使用者同網址天然去重，
且夠短可放進 postback data（上限 300 字元）。
"""
import hashlib
import logging
import time
from typing import List, Optional

from .firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

BOOKMARKS_COLLECTION = "bookmarks"
DOC_ID_LENGTH = 20
STALE_CANDIDATE_DAYS = 7


class BookmarkService:
    def __init__(self, store=None):
        self.store = store if store is not None else FirestoreKVStore(
            BOOKMARKS_COLLECTION)

    @property
    def available(self) -> bool:
        return self.store.is_available

    @staticmethod
    def make_doc_id(user_id: str, url: str) -> str:
        digest = hashlib.sha1(f"{user_id}:{url}".encode("utf-8")).hexdigest()
        return digest[:DOC_ID_LENGTH]

    def _write(self, user_id: str, url: str, title: str, summary: str,
               saved: bool, source: str) -> str:
        doc_id = self.make_doc_id(user_id, url)
        self.store.save(doc_id, {
            "user_id": user_id,
            "url": url,
            "title": title,
            "summary": summary,
            "created_at": time.time(),
            "saved": saved,
            "source": source,
        })
        return doc_id

    def save_direct(self, user_id: str, url: str, title: str, summary: str) -> str:
        """/save 指令：直接存成已儲存書籤。"""
        return self._write(user_id, url, title, summary,
                           saved=True, source="command")

    def save_candidate(self, user_id: str, url: str, title: str, summary: str) -> str:
        """社群貼文 carousel 產生時預寫的候選，等使用者按鈕確認。"""
        self.cleanup_stale_candidates(user_id)
        return self._write(user_id, url, title, summary,
                           saved=False, source="button")

    def confirm_save(self, user_id: str, doc_id: str) -> Optional[dict]:
        """把候選翻成已儲存。驗證 doc 屬於該使用者，否則回 None。"""
        doc = self.store.load(doc_id)
        if not doc or doc.get("user_id") != user_id:
            return None
        doc["saved"] = True
        self.store.save(doc_id, doc)
        return doc

    def _user_bookmarks(self, user_id: str, saved_only: bool = True) -> List[dict]:
        """該使用者的書籤，附上 doc_id，created_at 新→舊。

        個人規模（幾百筆）直接 load_all 後在記憶體過濾，
        不建 Firestore 複合索引。
        """
        items = []
        for doc_id, doc in self.store.load_all().items():
            if doc.get("user_id") != user_id:
                continue
            if saved_only and not doc.get("saved"):
                continue
            doc["doc_id"] = doc_id
            items.append(doc)
        items.sort(key=lambda d: d.get("created_at", 0), reverse=True)
        return items

    def list_saved(self, user_id: str, limit: int = 10) -> List[dict]:
        return self._user_bookmarks(user_id)[:limit]

    def search(self, user_id: str, keyword: str, limit: int = 10) -> List[dict]:
        """對 title+summary 做不分大小寫子字串比對。"""
        needle = keyword.lower().strip()
        if not needle:
            return []
        return [
            doc for doc in self._user_bookmarks(user_id)
            if needle in doc.get("title", "").lower()
            or needle in doc.get("summary", "").lower()
        ][:limit]

    def get_bookmark(self, user_id: str, doc_id: str) -> Optional[dict]:
        """取單一書籤（含候選），驗證屬於該使用者。"""
        doc = self.store.load(doc_id)
        if not doc or doc.get("user_id") != user_id:
            return None
        doc["doc_id"] = doc_id
        return doc

    def record_report(self, doc_id: str, report_id: str) -> None:
        """記下這則書籤最新產生的研究報告 id 與產生時間，供 TTL 內重複點擊直接沿用。

        呼叫端（研究報告 postback handler）已經驗證過 doc 屬於該使用者，
        這裡不重複驗證。
        """
        doc = self.store.load(doc_id)
        if not doc:
            return
        doc["report_id"] = report_id
        doc["report_generated_at"] = time.time()
        self.store.save(doc_id, doc)

    def delete(self, user_id: str, doc_id: str) -> bool:
        doc = self.store.load(doc_id)
        if not doc or doc.get("user_id") != user_id:
            return False
        self.store.delete(doc_id)
        return True

    def cleanup_stale_candidates(
        self, user_id: str, max_age_days: int = STALE_CANDIDATE_DAYS
    ) -> int:
        """刪除該使用者超過 max_age_days 未確認的候選（saved=False）。"""
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for doc in self._user_bookmarks(user_id, saved_only=False):
            if not doc.get("saved") and doc.get("created_at", 0) <= cutoff:
                self.store.delete(doc["doc_id"])
                removed += 1
        if removed:
            logger.info(
                f"Cleaned {removed} stale bookmark candidates for {user_id}")
        return removed


# 模組層單例：main.py 的指令與 postback 共用
_bookmark_service: Optional[BookmarkService] = None


def get_bookmark_service() -> BookmarkService:
    global _bookmark_service
    if _bookmark_service is None:
        _bookmark_service = BookmarkService()
    return _bookmark_service
