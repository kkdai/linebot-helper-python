"""研究報告的 Firestore 持久化儲存

沿用書籤的 FirestoreKVStore 模式：報告產生後永久保存，不會因
Cloud Run instance 休眠/回收而失效。Firestore 不可用（本機無憑證）時
優雅降級為 no-op，與其他 store 一致。

規格：docs/superpowers/specs/2026-08-15-research-report-design.md
（原規格「刻意只存記憶體」，2026-08-19 決定改為 Firestore 永久保存，見文件更新記錄）
"""
import time
import uuid
from typing import Optional

from .firestore_store import FirestoreKVStore

REPORTS_COLLECTION = "reports"


class ReportStore:
    def __init__(self, store=None):
        self.store = store if store is not None else FirestoreKVStore(
            REPORTS_COLLECTION)

    def put(self, html: str) -> str:
        report_id = uuid.uuid4().hex
        self.store.save(report_id, {
            "html": html,
            "created_at": time.time(),
        })
        return report_id

    def get(self, report_id: str) -> Optional[str]:
        doc = self.store.load(report_id)
        return doc["html"] if doc else None
