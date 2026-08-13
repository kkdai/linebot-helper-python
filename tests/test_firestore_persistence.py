"""測試：對話 session 與 batch job mapping 的 Firestore 持久化

背景：Cloud Run min-instances=0，instance 隨時可能被回收。
過去 SessionManager 的對話記憶放在記憶體、batch job mapping 寫本機檔案，
重啟後全部遺失。改為透過可注入的 store 持久化，並在 Firestore
不可用時優雅降級（本機開發/測試不需要憑證）。
"""
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from unittest.mock import patch

os.environ.setdefault("GOOGLE_AI_API_KEY", "fake-key-for-test")

from services.session_manager import SessionManager  # noqa: E402


class FakeStore:
    """記憶體版 store，模擬 FirestoreKVStore 介面。"""

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


class FakeChat:
    def __init__(self, history=None):
        self.restored_history = history


def make_chat_factory(created_chats: list):
    def factory(history=None):
        chat = FakeChat(history=history)
        created_chats.append(chat)
        return chat
    return factory


# --- SessionManager 持久化 ---

def test_session_history_survives_manager_restart():
    """新的 SessionManager（模擬 instance 重啟）要能從 store 還原對話歷史。"""
    store = FakeStore()
    created = []

    m1 = SessionManager(timeout_minutes=30, store=store)
    m1.get_or_create_session("U123", make_chat_factory(created))
    m1.add_to_history("U123", "user", "Python 是什麼？")
    m1.add_to_history("U123", "assistant", "Python 是一種程式語言。")

    # 模擬 instance 回收後重啟：全新 manager、同一個 store
    m2 = SessionManager(timeout_minutes=30, store=store)
    session = m2.get_or_create_session("U123", make_chat_factory(created))

    contents = [msg["content"] for msg in session.history]
    assert "Python 是什麼？" in contents
    assert "Python 是一種程式語言。" in contents


def test_restored_chat_factory_receives_history():
    """重建 chat 時必須把還原的歷史傳給 chat_factory，讓模型接續上下文。"""
    store = FakeStore()

    m1 = SessionManager(timeout_minutes=30, store=store)
    m1.get_or_create_session("U123", make_chat_factory([]))
    m1.add_to_history("U123", "user", "hello")

    created = []
    m2 = SessionManager(timeout_minutes=30, store=store)
    m2.get_or_create_session("U123", make_chat_factory(created))

    assert len(created) == 1
    assert created[0].restored_history, "chat_factory 應收到還原的歷史"
    assert created[0].restored_history[0]["content"] == "hello"


def test_expired_stored_session_is_not_restored():
    store = FakeStore()

    m1 = SessionManager(timeout_minutes=30, store=store)
    m1.get_or_create_session("U123", make_chat_factory([]))
    m1.add_to_history("U123", "user", "old message")

    # 把儲存的 last_active 改成很久以前
    doc = store.load("U123")
    doc["last_active"] = time.time() - 3600  # 一小時前
    store.save("U123", doc)

    created = []
    m2 = SessionManager(timeout_minutes=30, store=store)
    session = m2.get_or_create_session("U123", make_chat_factory(created))

    assert session.history == [], "過期 session 不應還原歷史"


def test_clear_session_deletes_from_store():
    store = FakeStore()
    m = SessionManager(timeout_minutes=30, store=store)
    m.get_or_create_session("U123", make_chat_factory([]))
    assert store.load("U123") is not None

    m.clear_session("U123")
    assert store.load("U123") is None


def test_legacy_chat_factory_without_history_param_still_works():
    """既有的零參數 chat_factory（不收 history）不能壞掉。"""
    store = FakeStore()

    m1 = SessionManager(timeout_minutes=30, store=store)
    m1.get_or_create_session("U123", lambda: FakeChat())
    m1.add_to_history("U123", "user", "hi")

    m2 = SessionManager(timeout_minutes=30, store=store)
    session = m2.get_or_create_session("U123", lambda: FakeChat())
    assert [msg["content"] for msg in session.history] == ["hi"]


# --- BatchService 持久化 ---

def test_batch_job_mapping_roundtrip_via_store():
    from services.batch_service import BatchService

    store = FakeStore()
    svc = BatchService(store=store)
    svc.save_job_mapping("batches/abc-123", "U456", {"kind": "restaurant"})

    # 模擬重啟：新的 service、同一個 store
    svc2 = BatchService(store=store)
    mapping = svc2.get_job_mapping("batches/abc-123")

    assert mapping is not None
    assert mapping["user_id"] == "U456"
    assert mapping["metadata"] == {"kind": "restaurant"}


def test_batch_job_id_with_slash_is_stored_safely():
    """Firestore 文件 ID 不允許斜線，batches/xxx 這種 ID 必須被安全轉換。"""
    from services.batch_service import BatchService

    store = FakeStore()
    svc = BatchService(store=store)
    svc.save_job_mapping("batches/xyz", "U1", {})

    for key in store.data:
        assert "/" not in key, f"store key 不應含斜線：{key}"

    assert svc.get_job_mapping("batches/xyz")["user_id"] == "U1"


# --- FirestoreKVStore 優雅降級 ---

def test_firestore_store_degrades_gracefully_without_credentials():
    from services import firestore_store

    with patch.object(firestore_store, "_create_client",
                      side_effect=RuntimeError("no credentials")):
        store = firestore_store.FirestoreKVStore("test_collection")
        assert store.is_available is False
        # 所有操作都不能 crash
        store.save("k", {"a": 1})
        assert store.load("k") is None
        store.delete("k")
        assert store.load_all() == {}
