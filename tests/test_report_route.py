"""測試：GET /reports/{report_id} 研究報告頁路由（Firestore 永久保存）"""
import os
from unittest.mock import patch

os.environ.setdefault("ChannelSecret", "test-secret")
os.environ.setdefault("ChannelAccessToken", "test-token")
os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
os.environ.setdefault("LINE_USER_ID", "U-test-user")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from services.report_store import ReportStore  # noqa: E402
from tests.fakes import FakeStore  # noqa: E402


def test_existing_report_is_served():
    fake_report_store = ReportStore(store=FakeStore())
    report_id = fake_report_store.put("<html><body>研究報告內容</body></html>")
    with patch.object(main, "report_store", fake_report_store), \
         TestClient(main.app) as client:
        resp = client.get(f"/reports/{report_id}")
    assert resp.status_code == 200
    assert "研究報告內容" in resp.text


def test_unknown_report_returns_not_found_page_404():
    fake_report_store = ReportStore(store=FakeStore())
    with patch.object(main, "report_store", fake_report_store), \
         TestClient(main.app) as client:
        resp = client.get("/reports/doesnotexist")
    assert resp.status_code == 404
    assert "找不到" in resp.text
