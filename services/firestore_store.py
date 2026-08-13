"""Firestore key-value store

輕量的 Firestore 包裝，給 SessionManager 與 BatchService 做持久化用。
Cloud Run min-instances=0，instance 隨時可能被回收，任何需要跨請求存活的
狀態都不能只放記憶體或本機檔案。

設計原則：
- 優雅降級：沒有憑證或套件時 is_available=False，所有操作變 no-op，
  本機開發與 CI 不需要 Firestore 也能跑。
- 文件 ID 淨化：Firestore 文件 ID 不允許斜線，key 先經過 _sanitize_key。
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _create_client():
    """建立 Firestore client，抽成函式方便測試 patch。"""
    from google.cloud import firestore
    return firestore.Client()


def _sanitize_key(key: str) -> str:
    """Firestore 文件 ID 不允許 '/'（例如 batch job 的 'batches/xxx'）。"""
    return key.replace("/", "__")


class FirestoreKVStore:
    """以 collection 為單位的 key-value 儲存。"""

    def __init__(self, collection: str, client=None):
        self.collection_name = collection
        self._client = client
        if self._client is None:
            try:
                self._client = _create_client()
                logger.info(
                    f"FirestoreKVStore ready: collection={collection}")
            except Exception as e:
                logger.warning(
                    f"Firestore unavailable, persistence disabled for "
                    f"collection={collection}: {e}")
                self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _doc_ref(self, key: str):
        return self._client.collection(self.collection_name).document(
            _sanitize_key(key))

    def save(self, key: str, doc: dict) -> None:
        if not self.is_available:
            return
        try:
            self._doc_ref(key).set(doc)
        except Exception as e:
            logger.error(f"Firestore save failed ({self.collection_name}/{key}): {e}")

    def load(self, key: str) -> Optional[dict]:
        if not self.is_available:
            return None
        try:
            snapshot = self._doc_ref(key).get()
            return snapshot.to_dict() if snapshot.exists else None
        except Exception as e:
            logger.error(f"Firestore load failed ({self.collection_name}/{key}): {e}")
            return None

    def delete(self, key: str) -> None:
        if not self.is_available:
            return
        try:
            self._doc_ref(key).delete()
        except Exception as e:
            logger.error(f"Firestore delete failed ({self.collection_name}/{key}): {e}")

    def load_all(self) -> Dict[str, dict]:
        if not self.is_available:
            return {}
        try:
            return {
                doc.id: doc.to_dict()
                for doc in self._client.collection(self.collection_name).stream()
            }
        except Exception as e:
            logger.error(f"Firestore load_all failed ({self.collection_name}): {e}")
            return {}
