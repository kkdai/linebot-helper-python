"""測試：研究報告的臨時儲存與網頁渲染

規格：docs/superpowers/specs/2026-08-15-research-report-design.md
- ReportStore：記憶體 + TTL，instance 回收即消失（刻意設計）
- report_page：Markdown 轉 HTML 閱讀版型；過期頁
"""
import time

from services.report_store import ReportStore
from services.report_page import render_report_page, render_expired_page


# --- ReportStore ---

def test_put_get_roundtrip():
    store = ReportStore()
    report_id = store.put("<html>report</html>")
    assert store.get(report_id) == "<html>report</html>"


def test_report_id_is_unguessable_and_url_safe():
    store = ReportStore()
    report_id = store.put("x")
    assert len(report_id) >= 16
    assert report_id.isalnum()


def test_unknown_id_returns_none():
    store = ReportStore()
    assert store.get("nonexistent") is None


def test_expired_report_returns_none_and_is_purged():
    store = ReportStore(ttl_seconds=0.05)
    report_id = store.put("x")
    time.sleep(0.1)
    assert store.get(report_id) is None
    assert report_id not in store._reports


def test_put_purges_other_expired_reports():
    store = ReportStore(ttl_seconds=0.05)
    old_id = store.put("old")
    time.sleep(0.1)
    store.put("new")
    assert old_id not in store._reports


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


def test_report_page_mentions_temporary_nature():
    html = render_report_page("t", "內文", "https://example.com", [])
    assert "臨時" in html


def test_report_page_without_sources_omits_source_section():
    html = render_report_page("t", "內文", "https://example.com", [])
    assert "參考來源" not in html


def test_expired_page_is_friendly():
    html = render_expired_page()
    assert "過期" in html
