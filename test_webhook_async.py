"""測試：LINE webhook 先回 200，事件處理丟背景執行

背景：過去 / handler 同步 await 整個訊息處理流程（爬網頁 + 呼叫 Gemini），
只要任何一步變慢，LINE 平台等不到 webhook 回應就放棄，使用者收不到任何回覆。
正確行為：驗完簽章、解析出 events 後立即回 200，實際處理在背景完成。
"""
import os
import threading
import time
from unittest.mock import patch

# 必須在 import main 之前設好必要環境變數
os.environ.setdefault("ChannelSecret", "test-secret")
os.environ.setdefault("ChannelAccessToken", "test-token")
os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
os.environ.setdefault("LINE_USER_ID", "U-test-user")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

from fastapi.testclient import TestClient  # noqa: E402
from linebot.models import MessageEvent  # noqa: E402

import main  # noqa: E402


HANDLER_DELAY_SECONDS = 2.0


def test_webhook_returns_immediately_and_processes_in_background():
    handler_done = threading.Event()

    async def slow_handler(event):
        import asyncio
        await asyncio.sleep(HANDLER_DELAY_SECONDS)
        handler_done.set()

    fake_event = MessageEvent()

    with patch.object(main.parser, "parse", return_value=[fake_event]), \
         patch.object(main, "handle_message_event", new=slow_handler):
        with TestClient(main.app) as client:
            start = time.monotonic()
            resp = client.post(
                "/",
                content=b"{}",
                headers={"X-Line-Signature": "dummy"},
            )
            elapsed = time.monotonic() - start

            assert resp.status_code == 200
            assert elapsed < HANDLER_DELAY_SECONDS, (
                f"webhook 應立即回應，不該等 handler 跑完（花了 {elapsed:.1f}s）"
            )
            # handler 應在背景繼續執行完畢
            assert handler_done.wait(timeout=10), "背景 handler 沒有被執行完成"


def test_webhook_invalid_signature_still_returns_400():
    from linebot.exceptions import InvalidSignatureError

    with patch.object(main.parser, "parse",
                      side_effect=InvalidSignatureError("bad signature")):
        with TestClient(main.app) as client:
            resp = client.post(
                "/",
                content=b"{}",
                headers={"X-Line-Signature": "bad"},
            )
            assert resp.status_code == 400
