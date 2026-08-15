"""測試：LINE 語音訊息（路徑 A）的 UX 改善

背景：原本語音訊息會先回一則「你說的是：…」（消耗 reply token），
Orchestrator 的結果再用 push 送第二則。改為：
- 收到語音先打 chat loading animation（不消耗 reply token、不佔訊息額度）
- 轉錄 + Orchestrator 結果合併成單一 reply，前綴顯示轉錄
- 回覆掛「🔊 用語音聽」quick reply，複用既有 read_aloud postback / TTS
"""
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("ChannelSecret", "test-secret")
os.environ.setdefault("ChannelAccessToken", "test-token")
os.environ.setdefault("ChannelAccessTokenHF", "test-token-hf")
os.environ.setdefault("LINE_USER_ID", "U-test-user")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

from linebot.models import AudioMessage, MessageEvent  # noqa: E402
from linebot.models.sources import SourceUser  # noqa: E402

import main  # noqa: E402
from services.line_service import LineService  # noqa: E402


class FakeMessageContent:
    async def iter_content(self):
        yield b"fake-audio-bytes"


class FakeLineBotApi:
    def __init__(self):
        self.replies = []
        self.pushes = []

    async def get_message_content(self, message_id):
        return FakeMessageContent()

    async def reply_message(self, reply_token, messages):
        self.replies.append((reply_token, messages))

    async def push_message(self, user_id, messages):
        self.pushes.append((user_id, messages))


def _audio_event():
    event = MessageEvent()
    event.reply_token = "rt-1"
    event.message = AudioMessage(id="msg-1", duration=1200)
    event.source = SourceUser(user_id="U-alice")
    return event


class FakeOrchestratorResult:
    responses = []


@pytest.mark.asyncio
async def test_audio_message_single_combined_reply_with_tts_quick_reply():
    fake_api = FakeLineBotApi()
    loading_mock = AsyncMock()

    async def fake_process_text(user_id, message):
        assert message == "今天天氣如何"
        return FakeOrchestratorResult()

    with patch.object(main, "line_bot_api", fake_api), \
         patch.object(main, "transcribe_audio", AsyncMock(return_value="今天天氣如何")), \
         patch.object(main.orchestrator, "process_text", side_effect=fake_process_text), \
         patch.object(main, "format_orchestrator_response", return_value="今天晴朗，30 度"), \
         patch.object(LineService, "show_loading_animation", loading_mock):
        await main.handle_audio_message(_audio_event())

    # loading animation 打給正確的 chat
    assert loading_mock.await_count == 1
    assert loading_mock.await_args.args[0] == "U-alice"

    # 單一 reply：轉錄前綴 + 結果，不再有第二則 push
    assert len(fake_api.replies) == 1
    assert fake_api.pushes == []
    reply_token, messages = fake_api.replies[0]
    assert reply_token == "rt-1"
    text = messages[0].text
    assert text.startswith("🎤 你說的是：今天天氣如何")
    assert "今天晴朗，30 度" in text

    # 掛上「用語音聽」quick reply（read_aloud postback）
    qr = messages[0].quick_reply
    assert qr is not None
    labels = [item.action.label for item in qr.items]
    assert any("語音" in label for label in labels)


@pytest.mark.asyncio
async def test_audio_message_empty_transcription_replies_error():
    fake_api = FakeLineBotApi()
    with patch.object(main, "line_bot_api", fake_api), \
         patch.object(main, "transcribe_audio", AsyncMock(return_value="   ")), \
         patch.object(LineService, "show_loading_animation", AsyncMock()):
        await main.handle_audio_message(_audio_event())

    assert len(fake_api.replies) == 1
    assert "無法辨識" in fake_api.replies[0][1][0].text


@pytest.mark.asyncio
async def test_show_loading_animation_posts_to_line_api(monkeypatch):
    """LineService.show_loading_animation 應呼叫 LINE chat loading API。"""
    captured = {}

    class FakeResp:
        status = 202

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured.update(url=url, json=json, headers=headers)
            return FakeResp()

    monkeypatch.setattr("services.line_service.aiohttp.ClientSession", FakeSession)
    await LineService.show_loading_animation("U-alice", access_token="tok-123")

    assert captured["url"].endswith("/v2/bot/chat/loading/start")
    assert captured["json"] == {"chatId": "U-alice", "loadingSeconds": 60}
    assert captured["headers"]["Authorization"] == "Bearer tok-123"
