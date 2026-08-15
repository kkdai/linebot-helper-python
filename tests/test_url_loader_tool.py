"""測試：tools/url_loader.py 的文件連結處理

agent 工具路徑（load_url_content）與 loader/url.py 走同一套文件偵測，
文件連結要用 anydoc 轉 Markdown，PDF 失敗時 fallback 到既有的 pypdf 工具。
"""
from unittest.mock import patch

import tools.url_loader as tool_module
from tools.url_loader import load_url_content


class TestDocumentHandling:
    def test_docx_url_returns_markdown(self):
        with patch.object(tool_module, "detect_document_format",
                          new=lambda url: "docx"), \
             patch.object(tool_module, "load_document",
                          new=lambda url, doc_format=None: "# converted"):
            result = load_url_content("https://example.com/report.docx")

        assert result["status"] == "success"
        assert result["content"] == "# converted"
        assert result["content_type"] == "document"
        assert result["document_format"] == "docx"

    def test_pdf_falls_back_to_pypdf_when_anydoc_fails(self):
        def anydoc_fails(url, doc_format=None):
            raise RuntimeError("anydoc boom")

        with patch.object(tool_module, "detect_document_format",
                          new=lambda url: "pdf"), \
             patch.object(tool_module, "load_document", new=anydoc_fails), \
             patch.object(tool_module, "load_pdf_content",
                          new=lambda url, is_url=True: {
                              "status": "success", "content": "pypdf text",
                              "page_count": 3}):
            result = load_url_content("https://example.com/paper.pdf")

        assert result["status"] == "success"
        assert result["content"] == "pypdf text"
        assert result["content_type"] == "pdf"

    def test_non_pdf_document_failure_returns_error(self):
        def anydoc_fails(url, doc_format=None):
            raise RuntimeError("anydoc boom")

        with patch.object(tool_module, "detect_document_format",
                          new=lambda url: "pptx"), \
             patch.object(tool_module, "load_document", new=anydoc_fails):
            result = load_url_content("https://example.com/slides.pptx")

        assert result["status"] == "error"
        assert "無法讀取文件內容" in result["error_message"]

    def test_non_document_url_skips_document_branch(self):
        def should_not_run(url, doc_format=None):
            raise AssertionError("不該呼叫 load_document")

        with patch.object(tool_module, "detect_document_format",
                          new=lambda url: None), \
             patch.object(tool_module, "load_document", new=should_not_run), \
             patch.object(tool_module, "_load_html_with_httpx",
                          new=lambda url, markdown=True: "html content"):
            result = load_url_content("https://unknown.example.com/page")

        assert result["status"] == "success"
        assert result["content"] == "html content"
