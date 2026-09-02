"""測試：影片呼叫的四項必要參數

背景：2026-09-02 spike 實測發現，agentic video understanding 有四個參數
缺一不可，而缺任何一個都**不會報錯**——程式照跑、答案照出，只有成本默默改變：

1. api_version="v1beta1"      → v1 不支援 agentic，靜默退回 STATIC
2. media_processing="AGENTIC" → 不設就是 STATIC
3. 模型在支援名單內           → 否則靜默降級為 STATIC
4. thinking_level="LOW"       → 漏設時 thinking token 暴增，成本變 5.5 倍
                                （10 分鐘影片：$0.0946 vs $0.0023）

這種 bug 靠 code review 抓不到，只有帳單會告訴你。所以這四項各有一個測試。

不打網路：mock 掉 genai.Client 後斷言呼叫參數。
"""
from unittest.mock import MagicMock, patch

import pytest

from tools import youtube_tool

VIDEO_URL = "https://www.youtube.com/watch?v=o8NiE3XMPrM"


def _fake_response(text="摘要內容"):
    resp = MagicMock()
    resp.text = text
    usage = MagicMock()
    usage.prompt_token_count = 260
    usage.candidates_token_count = 638
    usage.thoughts_token_count = 0
    usage.tool_use_prompt_token_count = 2163
    usage.total_token_count = 2854
    resp.usage_metadata = usage
    return resp


@pytest.fixture
def captured():
    """攔截 genai.Client 的建構與 generate_content 呼叫參數。"""
    holder = {}

    def fake_client(**client_kwargs):
        holder["client_kwargs"] = client_kwargs
        client = MagicMock()

        def generate_content(**call_kwargs):
            holder["call_kwargs"] = call_kwargs
            return _fake_response()

        client.models.generate_content.side_effect = generate_content
        return client

    with patch.object(youtube_tool.genai, "Client", side_effect=fake_client):
        yield holder


def test_uses_v1beta1_api_version(captured):
    """v1 不支援 agentic，會靜默退回 STATIC。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    http_options = captured["client_kwargs"]["http_options"]
    assert http_options.api_version == "v1beta1"


def test_video_part_sets_agentic_media_processing(captured):
    """不設 media_processing 就是 STATIC，等於這個功能沒開。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    video_part = captured["call_kwargs"]["contents"][0]
    assert str(video_part.media_processing).upper().endswith("AGENTIC")


def test_thinking_level_is_low(captured):
    """漏設 thinking_level，10 分鐘影片成本從 $0.0023 變 $0.0946。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    config = captured["call_kwargs"]["config"]
    assert config.thinking_config is not None, "必須設 thinking_config"
    assert str(config.thinking_config.thinking_level).upper().endswith("LOW")


def test_model_supports_agentic(captured):
    """不在支援名單的模型會靜默降級為 STATIC。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    assert captured["call_kwargs"]["model"] in {
        "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
    }


def test_generate_video_requires_explicit_thinking_level():
    """thinking_level 必須是必填參數——有預設值就會有人漏掉。"""
    with pytest.raises(TypeError):
        youtube_tool._generate_video(VIDEO_URL, "prompt")  # type: ignore[call-arg]


def test_summarize_returns_usage(captured):
    result = youtube_tool.summarize_youtube_video(VIDEO_URL)
    assert result["status"] == "success"
    assert result["usage"]["tool_use_tokens"] == 2163
    assert result["usage"]["total_tokens"] == 2854
    assert result["usage"]["model"] in {"gemini-3.5-flash-lite"}


def test_ask_youtube_video_returns_answer(captured):
    result = youtube_tool.ask_youtube_video(VIDEO_URL, "他有講到定價嗎？")
    assert result["status"] == "success"
    assert result["answer"] == "摘要內容"
    assert "usage" in result


def test_ask_rejects_non_youtube_url():
    result = youtube_tool.ask_youtube_video("https://example.com", "問題")
    assert result["status"] == "error"


def test_ask_includes_question_in_prompt(captured):
    youtube_tool.ask_youtube_video(VIDEO_URL, "XR 眼鏡那段在哪？")
    prompt = captured["call_kwargs"]["contents"][1]
    assert "XR 眼鏡那段在哪？" in prompt


def _fake_response_with_thinking(thinking_tokens):
    resp = MagicMock()
    resp.text = "摘要內容"
    usage = MagicMock()
    usage.prompt_token_count = 234
    usage.candidates_token_count = 300
    usage.thoughts_token_count = thinking_tokens
    usage.tool_use_prompt_token_count = 2165
    usage.total_token_count = 234 + 300 + thinking_tokens + 2165
    resp.usage_metadata = usage
    return resp


def test_warns_when_thinking_tokens_exceed_threshold(caplog):
    """thinking_level 沒有客戶端保證——超過門檻時要留下可 grep 的紀錄。"""
    with patch.object(
        youtube_tool.genai, "Client",
        side_effect=lambda **kw: MagicMock(models=MagicMock(
            generate_content=MagicMock(
                return_value=_fake_response_with_thinking(35000)
            )
        )),
    ):
        with caplog.at_level("WARNING", logger=youtube_tool.logger.name):
            youtube_tool.summarize_youtube_video(VIDEO_URL)
    assert any("thinking tokens" in r.message for r in caplog.records)


def test_no_warning_when_thinking_tokens_are_zero(caplog):
    with patch.object(
        youtube_tool.genai, "Client",
        side_effect=lambda **kw: MagicMock(models=MagicMock(
            generate_content=MagicMock(
                return_value=_fake_response_with_thinking(0)
            )
        )),
    ):
        with caplog.at_level("WARNING", logger=youtube_tool.logger.name):
            youtube_tool.summarize_youtube_video(VIDEO_URL)
    assert not any("thinking tokens" in r.message for r in caplog.records)
