"""測試：SingleFile 子行程逾時保護

驗證 singlefile_download 在子行程卡住不回應時，不會無限期等待，
而是在逾時後 kill 掉子行程並丟出例外，讓上層的 fallback chain 能接手。

背景：production 曾發生 SingleFile（內部啟動 headless Chromium）卡死，
導致整個 LINE webhook request 卡到 Cloud Run 的 5 分鐘 request timeout
才被砍斷回 504，使用者完全收不到任何回覆。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loader.singlefile import singlefile_download, load_html_with_singlefile


class _HangingProcess:
    """模擬一個 communicate() 永遠不會回傳的子行程。"""

    def __init__(self):
        self.returncode = None
        self.killed = False
        self.waited = False

    async def communicate(self):
        await asyncio.Future()  # 永遠不會 resolve

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.waited = True
        return self.returncode


@pytest.mark.asyncio
async def test_singlefile_download_times_out_instead_of_hanging():
    hanging_process = _HangingProcess()

    with patch(
        "loader.singlefile.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=hanging_process),
    ):
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                singlefile_download("https://example.com", timeout=0.05),
                timeout=2,
            )

    assert hanging_process.killed, "逾時後應該 kill 掉卡住的子行程"


@pytest.mark.asyncio
async def test_load_html_with_singlefile_reraises_instead_of_returning_error_string():
    """singlefile 失敗時必須讓例外往上傳，讓 url.py 的 fallback chain 能接手，
    而不是回傳看起來像正常內容的 "error:..." 字串（會被誤判成爬取成功）。"""
    with patch(
        "loader.singlefile.load_singlefile_html",
        new=AsyncMock(side_effect=TimeoutError("SingleFile timed out")),
    ):
        with pytest.raises(Exception):
            await load_html_with_singlefile("https://example.com")
