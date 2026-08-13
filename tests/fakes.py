"""測試共用的假物件"""
from typing import Dict, Optional


class FakeStore:
    """記憶體版 store，模擬 services.firestore_store.FirestoreKVStore 介面。"""

    def __init__(self):
        self.data: Dict[str, dict] = {}

    @property
    def is_available(self) -> bool:
        return True

    def save(self, key: str, doc: dict) -> None:
        self.data[key] = dict(doc)

    def load(self, key: str) -> Optional[dict]:
        doc = self.data.get(key)
        return dict(doc) if doc is not None else None

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def load_all(self) -> Dict[str, dict]:
        return {k: dict(v) for k, v in self.data.items()}


class UnavailableStore(FakeStore):
    """模擬 Firestore 降級（無憑證）狀態。"""

    @property
    def is_available(self) -> bool:
        return False
