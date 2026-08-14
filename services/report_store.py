"""研究報告的臨時記憶體儲存

刻意只存記憶體：報告是「短暫開啟」的內容，Cloud Run instance
休眠/回收後自然消失（規格要求），不做持久化。
TTL 到期的報告在存取與寫入時順手清除。
"""
import time
import uuid
from threading import Lock
from typing import Dict, Optional

DEFAULT_REPORT_TTL_SECONDS = 24 * 3600


class ReportStore:
    def __init__(self, ttl_seconds: float = DEFAULT_REPORT_TTL_SECONDS):
        self.ttl = ttl_seconds
        self._reports: Dict[str, dict] = {}
        self._lock = Lock()

    def _purge_expired(self) -> None:
        """呼叫端必須已持有 self._lock。"""
        now = time.time()
        expired = [
            rid for rid, entry in self._reports.items()
            if now - entry["created_at"] > self.ttl
        ]
        for rid in expired:
            del self._reports[rid]

    def put(self, html: str) -> str:
        report_id = uuid.uuid4().hex
        with self._lock:
            self._purge_expired()
            self._reports[report_id] = {
                "html": html,
                "created_at": time.time(),
            }
        return report_id

    def get(self, report_id: str) -> Optional[str]:
        with self._lock:
            self._purge_expired()
            entry = self._reports.get(report_id)
            return entry["html"] if entry else None
