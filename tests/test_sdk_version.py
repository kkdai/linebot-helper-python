"""測試：google-genai 版本下限

背景：agentic video understanding 需要 Part.media_processing 欄位，
該欄位自 google-genai 2.20.0 起才存在（逐版驗證：2.19.0 無、2.20.0 有）。

版本若被降回舊版，影片功能不會報錯——media_processing 會被當成未知欄位，
呼叫照樣送出，只是完全不走 agentic。所以要有測試擋住。
"""
from google.genai import types


def test_part_supports_media_processing():
    """Part 必須有 media_processing 欄位，否則 agentic 參數會被靜默丟棄。"""
    assert "media_processing" in types.Part.model_fields, (
        "google-genai 版本過舊：Part 沒有 media_processing 欄位，"
        "需要 >= 2.20.0"
    )


def test_media_processing_enum_has_agentic():
    values = {e.value for e in types.MediaProcessing}
    assert "AGENTIC" in values
    assert "STATIC" in values


def test_thinking_config_supports_thinking_level():
    """thinking_level 是影片查詢必帶的參數；SDK 支援與否決定能不能顯式控制
    它（早期單次觀測的「漏設變 5.5 倍」不是穩定效果，見 spec 結論二、三）。"""
    assert "thinking_level" in types.ThinkingConfig.model_fields
