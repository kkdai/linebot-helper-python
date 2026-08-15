"""測試：loader/url.py 統一逾時策略

驗證 fallback chain 對每種抓取方法都套用時間預算：
- 同步 loader（httpx/cloudscraper）卡住時，逾時後換下一種方法，不會卡死 event loop
- 所有方法都失敗時，丟出帶有中文錯誤訊息的例外
"""
import time
from unittest.mock import AsyncMock, patch

import pytest

import loader.url as url_module
from loader.url import load_url


TEST_URL = "https://unknown-domain.example.com/article"


@pytest.mark.asyncio
async def test_hanging_sync_loader_times_out_and_falls_back():
    """httpx loader 卡住時，應在預算時間內放棄並 fallback 到 cloudscraper。"""

    def hanging_httpx(url, markdown=True):
        # 模擬卡住的同步呼叫（遠超過 0.2s 預算即可；
        # to_thread 的 thread 在 loop 關閉時會被 join，所以不要 sleep 太久）
        time.sleep(3)
        return "should never get here"

    with patch.object(url_module, "load_html_with_singlefile",
                      new=AsyncMock(side_effect=RuntimeError("singlefile down"))), \
         patch.object(url_module, "load_html_with_httpx", new=hanging_httpx), \
         patch.object(url_module, "load_html_with_cloudscraper",
                      new=lambda url, markdown=True: "cloudscraper content"), \
         patch.object(url_module, "detect_document_format", new=lambda url: None), \
         patch.dict(url_module.LOADER_TIMEOUTS, {"httpx": 0.2}):
        start = time.monotonic()
        result = await load_url(TEST_URL)
        elapsed = time.monotonic() - start

    assert result == "cloudscraper content"
    assert elapsed < 5, f"逾時後應立即 fallback，實際花了 {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_all_methods_failing_raises_chinese_error():
    with patch.object(url_module, "load_html_with_singlefile",
                      new=AsyncMock(side_effect=RuntimeError("boom"))), \
         patch.object(url_module, "load_html_with_httpx",
                      new=lambda url, markdown=True: (_ for _ in ()).throw(RuntimeError("boom"))), \
         patch.object(url_module, "load_html_with_cloudscraper",
                      new=lambda url, markdown=True: (_ for _ in ()).throw(RuntimeError("boom"))), \
         patch.object(url_module, "detect_document_format", new=lambda url: None):
        with pytest.raises(Exception, match="無法從網址讀取內容"):
            await load_url(TEST_URL)


@pytest.mark.asyncio
async def test_document_conversion_timeout_raises_chinese_error():
    """anydoc 轉換卡住時，應在預算時間內放棄並丟出中文錯誤訊息。"""

    def hanging_document(url, doc_format=None):
        time.sleep(3)
        return "should never get here"

    with patch.object(url_module, "detect_document_format", new=lambda url: "docx"), \
         patch.object(url_module, "load_document", new=hanging_document), \
         patch.dict(url_module.LOADER_TIMEOUTS, {"document": 0.2}):
        start = time.monotonic()
        with pytest.raises(Exception, match="無法讀取文件內容"):
            await load_url("https://example.com/report.docx")
        elapsed = time.monotonic() - start

    assert elapsed < 5, f"逾時後應立即放棄，實際花了 {elapsed:.1f}s"
