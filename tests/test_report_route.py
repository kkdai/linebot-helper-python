"""測試：GET /reports/{report_id} 臨時報告頁路由"""
import os

os.environ.setdefault("ChannelSecret", "test-secret")
os.environ.setdefault("ChannelAccessToken", "test-token")
os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
os.environ.setdefault("LINE_USER_ID", "U-test-user")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


def test_existing_report_is_served():
    report_id = main.report_store.put("<html><body>研究報告內容</body></html>")
    with TestClient(main.app) as client:
        resp = client.get(f"/reports/{report_id}")
    assert resp.status_code == 200
    assert "研究報告內容" in resp.text


def test_unknown_report_returns_expired_page_404():
    with TestClient(main.app) as client:
        resp = client.get("/reports/doesnotexist")
    assert resp.status_code == 404
    assert "過期" in resp.text
