"""測試：研究報告的 Firestore 持久化儲存與網頁渲染

規格：docs/superpowers/specs/2026-08-15-research-report-design.md
- ReportStore：透過 FirestoreKVStore 永久保存（2026-08-19 更新，見文件更新記錄）
- report_page：Markdown 轉 HTML 閱讀版型；找不到報告頁
"""
from unittest.mock import patch

from services.report_store import ReportStore
from services.report_page import render_report_page, render_expired_page
from tests.fakes import FakeStore


# --- ReportStore ---

def test_put_get_roundtrip():
    store = ReportStore(store=FakeStore())
    report_id = store.put("<html>report</html>")
    assert store.get(report_id) == "<html>report</html>"


def test_report_id_is_unguessable_and_url_safe():
    store = ReportStore(store=FakeStore())
    report_id = store.put("x")
    assert len(report_id) >= 16
    assert report_id.isalnum()


def test_unknown_id_returns_none():
    store = ReportStore(store=FakeStore())
    assert store.get("nonexistent") is None


def test_report_persists_across_new_store_instances():
    """模擬 instance 回收後重啟：新的 ReportStore、同一個底層 store，報告仍在。"""
    fake = FakeStore()
    s1 = ReportStore(store=fake)
    report_id = s1.put("<html>survives restart</html>")

    s2 = ReportStore(store=fake)
    assert s2.get(report_id) == "<html>survives restart</html>"


def test_degrades_gracefully_when_firestore_unavailable():
    """無憑證時（本機開發/CI）：save/load 變 no-op，不能 crash。"""
    from services import firestore_store

    with patch.object(firestore_store, "_create_client",
                      side_effect=RuntimeError("no credentials")):
        store = ReportStore()
        report_id = store.put("x")
        assert store.get(report_id) is None


# --- 報告頁渲染 ---

def test_report_page_renders_markdown_structure():
    html = render_report_page(
        title="測試報告",
        markdown_text="## 執行摘要\n\n重點內容\n\n- 項目一\n- 項目二",
        url="https://example.com/article",
        sources=[{"title": "來源A", "uri": "https://source-a.example.com"}],
    )
    assert "<h2" in html and "執行摘要" in html
    assert "<li>項目一</li>" in html
    assert "https://example.com/article" in html
    assert "來源A" in html and "https://source-a.example.com" in html
    assert "測試報告" in html


def test_report_page_without_sources_omits_source_section():
    html = render_report_page("t", "內文", "https://example.com", [])
    assert "參考來源" not in html


def test_expired_page_is_friendly():
    html = render_expired_page()
    assert "找不到" in html
