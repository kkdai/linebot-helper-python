"""測試：loader/document.py anydoc 文件轉 Markdown

驗證文件連結的偵測與轉換：
- 副檔名優先偵測（零網路成本），沒副檔名才發 HEAD 看 content-type
- load_document 下載 bytes 後用 anydoc 轉成 Markdown
- load_url 整合：文件連結走 anydoc，PDF 失敗 fallback 到 pypdf
"""
from unittest.mock import patch

import httpx
import pytest

import loader.document as doc_module
from loader.document import detect_document_format, load_document


def _fail_head(*args, **kwargs):
    raise AssertionError("不該發出 HEAD request")


class TestDetectByExtension:
    def test_docx_extension(self):
        with patch.object(doc_module.httpx, "head", new=_fail_head):
            fmt = detect_document_format("https://example.com/report.docx")
        assert fmt == "docx"

    def test_extension_with_query_string(self):
        with patch.object(doc_module.httpx, "head", new=_fail_head):
            fmt = detect_document_format("https://example.com/slides.pptx?dl=1")
        assert fmt == "pptx"

    def test_uppercase_extension(self):
        with patch.object(doc_module.httpx, "head", new=_fail_head):
            fmt = detect_document_format("https://example.com/DATA.CSV")
        assert fmt == "csv"

    def test_all_supported_extensions_map_to_formats(self):
        for ext in ["doc", "docx", "docm", "ppt", "pptx", "pptm",
                    "xls", "xlsx", "xlsm", "odt", "ods", "odp",
                    "rtf", "epub", "csv", "pdf"]:
            with patch.object(doc_module.httpx, "head", new=_fail_head):
                fmt = detect_document_format(f"https://example.com/f.{ext}")
            assert fmt == ext, f".{ext} 應被偵測為文件"

    def test_non_document_extension_falls_through_to_content_type(self):
        # 動態網址（download.php）可能實際回傳 PDF，副檔名不是文件格式時
        # 仍要靠 content-type 判斷，不能直接放棄
        with patch.object(doc_module.httpx, "head",
                          return_value=_head_response("application/pdf")):
            fmt = detect_document_format("https://example.com/download.php?id=5")
        assert fmt == "pdf"

    def test_html_extension_serving_html_is_not_document(self):
        with patch.object(doc_module.httpx, "head",
                          return_value=_head_response("text/html; charset=utf-8")):
            fmt = detect_document_format("https://example.com/page.html")
        assert fmt is None


def _head_response(content_type: str) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": content_type},
        request=httpx.Request("HEAD", "https://example.com/x"))


class TestDetectByContentType:
    def test_pdf_content_type(self):
        with patch.object(doc_module.httpx, "head",
                          return_value=_head_response("application/pdf")):
            fmt = detect_document_format("https://example.com/download/123")
        assert fmt == "pdf"

    def test_docx_content_type(self):
        ct = ("application/vnd.openxmlformats-officedocument"
              ".wordprocessingml.document")
        with patch.object(doc_module.httpx, "head",
                          return_value=_head_response(ct)):
            fmt = detect_document_format("https://example.com/download/123")
        assert fmt == "docx"

    def test_content_type_with_charset(self):
        with patch.object(doc_module.httpx, "head",
                          return_value=_head_response("text/csv; charset=utf-8")):
            fmt = detect_document_format("https://example.com/export")
        assert fmt == "csv"

    def test_html_content_type_is_not_document(self):
        with patch.object(doc_module.httpx, "head",
                          return_value=_head_response("text/html; charset=utf-8")):
            fmt = detect_document_format("https://example.com/article")
        assert fmt is None

    def test_head_failure_returns_none(self):
        def boom(*args, **kwargs):
            raise httpx.ConnectTimeout("timeout")

        with patch.object(doc_module.httpx, "head", new=boom):
            fmt = detect_document_format("https://example.com/article")
        assert fmt is None

    def test_head_request_has_explicit_timeout(self):
        """HEAD request 必須帶明確 timeout，避免慢速伺服器卡住整個流程。"""
        captured = {}

        def fake_head(url=None, headers=None, follow_redirects=None,
                      timeout=None, **kwargs):
            captured["timeout"] = timeout
            raise httpx.ConnectTimeout("stop here")

        with patch.object(doc_module.httpx, "head", new=fake_head):
            detect_document_format("https://example.com/download/123")

        assert captured.get("timeout"), "httpx.head 必須帶明確 timeout 參數"

    def test_ptt_url_skips_head_request(self):
        # PTT 對 HEAD 會回 403，維持既有行為：不發 HEAD
        with patch.object(doc_module.httpx, "head", new=_fail_head):
            fmt = detect_document_format("https://www.ptt.cc/bbs/Gossiping/M.1.html")
        assert fmt is None


def _get_response(content: bytes) -> httpx.Response:
    return httpx.Response(
        200, content=content,
        request=httpx.Request("GET", "https://example.com/x"))


class TestLoadDocument:
    def test_converts_csv_to_markdown(self):
        # 用真的 anydoc 轉換，驗證整條路徑
        with patch.object(doc_module.httpx, "get",
                          return_value=_get_response(b"a,b\n1,2")):
            md = load_document("https://example.com/data.csv", "csv")
        assert "| a | b |" in md

    def test_bad_bytes_raises(self):
        with patch.object(doc_module.httpx, "get",
                          return_value=_get_response(b"\x00\x01 not a docx")):
            with pytest.raises(Exception):
                load_document("https://example.com/report.docx", "docx")


@pytest.mark.asyncio
class TestLoadUrlIntegration:
    async def test_document_url_uses_anydoc(self):
        import loader.url as url_module

        with patch.object(url_module, "detect_document_format",
                          new=lambda url: "docx"), \
             patch.object(url_module, "load_document",
                          new=lambda url, fmt=None: "# converted markdown"):
            result = await url_module.load_url("https://example.com/report.docx")
        assert result == "# converted markdown"

    async def test_pdf_falls_back_to_pypdf_when_anydoc_fails(self):
        import loader.url as url_module

        def anydoc_fails(url, fmt=None):
            raise RuntimeError("anydoc boom")

        with patch.object(url_module, "detect_document_format",
                          new=lambda url: "pdf"), \
             patch.object(url_module, "load_document", new=anydoc_fails), \
             patch.object(url_module, "load_pdf",
                          new=lambda url: "pypdf text"):
            result = await url_module.load_url("https://example.com/paper.pdf")
        assert result == "pypdf text"

    async def test_non_pdf_document_failure_raises_chinese_error(self):
        import loader.url as url_module

        def anydoc_fails(url, fmt=None):
            raise RuntimeError("anydoc boom")

        with patch.object(url_module, "detect_document_format",
                          new=lambda url: "docx"), \
             patch.object(url_module, "load_document", new=anydoc_fails):
            with pytest.raises(Exception, match="無法讀取文件內容"):
                await url_module.load_url("https://example.com/report.docx")

    async def test_non_document_url_skips_document_branch(self):
        import loader.url as url_module

        with patch.object(url_module, "detect_document_format",
                          new=lambda url: None), \
             patch.object(url_module, "load_document",
                          new=lambda url, fmt=None: (_ for _ in ()).throw(
                              AssertionError("不該呼叫 load_document"))), \
             patch.object(url_module, "load_html_with_singlefile",
                          side_effect=RuntimeError("down")), \
             patch.object(url_module, "load_html_with_httpx",
                          new=lambda url, markdown=True: "html content"), \
             patch.object(url_module, "load_html_with_cloudscraper",
                          new=lambda url, markdown=True: "cs content"):
            result = await url_module.load_url("https://unknown.example.com/page")
        assert result == "html content"
