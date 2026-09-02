"""影片問答模式的狀態

只記「這個使用者現在在問哪支影片」。因為 Vertex AI 上無法保留影片 context
（見 docs/superpowers/specs/2026-09-02-video-qa-design.md Spike 結論一），
每次提問都是獨立的重新查詢，所以這裡不存任何對話歷史——存了也沒用。

直接用 FirestoreKVStore 而非 SessionManager：後者繞著「Gemini chat 物件 +
會裁切的歷史」設計，metadata 不持久化、history 會被裁掉，兩者都會讓影片網址
在使用中消失。
"""
import logging
import time
from typing import Optional

from loader.utils import find_url
from services.firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

VIDEO_QA_COLLECTION = "video_qa_sessions"
DEFAULT_TTL_SECONDS = 30 * 60   # 與聊天 session 一致


def should_exit_video_mode(message_text: str) -> bool:
    """判斷這則訊息代表使用者想離開影片模式。

    刻意用啟發式而不是 LLM 判斷意圖：後者每則訊息都要多打一次 Gemini，
    而誤判的代價很低（使用者再問一次就好），不值得那個成本與延遲。

    涵蓋「換主題」的實際訊號：貼了新網址、打了指令。
    非文字訊息（圖片／語音／位置）由呼叫端處理，不走這個函式。

    使用同一個 find_url() 作為主流程，確保 URL 偵測邏輯不會分歧。
    """
    if not message_text:
        return False
    text = message_text.strip()
    if text.startswith("/"):
        return True
    return bool(find_url(text))


class VideoQASessions:
    def __init__(self, store=None, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._store = store if store is not None else FirestoreKVStore(VIDEO_QA_COLLECTION)
        self._ttl = ttl_seconds

    @property
    def available(self) -> bool:
        try:
            return bool(self._store.is_available)
        except Exception:
            return False

    def enter(self, user_id: str, video_url: str) -> None:
        """進入影片模式。重複進入會換成新影片並把提問次數歸零。"""
        if not self.available:
            return
        try:
            self._store.save(user_id, {
                "url": video_url,
                "entered_at": time.time(),
                "last_active": time.time(),
                "asked": 0,
            })
            logger.info("video_qa: user %s entered mode for %s", user_id, video_url)
        except Exception as e:
            logger.warning("Failed to enter video mode (degrading silently): %s", e)

    def get(self, user_id: str) -> Optional[dict]:
        """回傳目前的影片 session；不在模式中或已過期回 None。"""
        if not self.available:
            return None
        try:
            doc = self._store.load(user_id)
        except Exception as e:
            logger.warning("Failed to read video session (degrading silently): %s", e)
            return None
        if not doc:
            return None
        if time.time() - doc.get("last_active", 0) >= self._ttl:
            self.exit(user_id)
            return None
        return doc

    def bump(self, user_id: str) -> None:
        """提問次數 +1 並續期。"""
        doc = self.get(user_id)
        if doc is None:
            return
        try:
            doc["asked"] = doc.get("asked", 0) + 1
            doc["last_active"] = time.time()
            self._store.save(user_id, doc)
        except Exception as e:
            logger.warning("Failed to bump video session (degrading silently): %s", e)

    def exit(self, user_id: str) -> bool:
        """離開影片模式。回傳是否原本在模式中。"""
        if not self.available:
            return False
        try:
            existed = self._store.load(user_id) is not None
            self._store.delete(user_id)
            if existed:
                logger.info("video_qa: user %s exited mode", user_id)
            return existed
        except Exception as e:
            logger.warning("Failed to exit video mode (degrading silently): %s", e)
            return False


_sessions: Optional[VideoQASessions] = None


def get_video_qa_sessions() -> VideoQASessions:
    global _sessions
    if _sessions is None:
        _sessions = VideoQASessions()
    return _sessions
