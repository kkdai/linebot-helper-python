#!/usr/bin/env python3
"""測試：輸出語言鎖定（非中文網址也必須輸出台灣用語繁體中文）

Bug 重現：丟日文網址（例：https://www.itmedia.co.jp/news/article/2608/09/2000000463/）
時，摘要與三平台社群貼文會整包跟著原文變成日文。

Root cause（實測得出，非猜測）：
1. 所有 generate_content 呼叫都沒有 system_instruction，輸出語言從沒被釘成硬約束；
2. 沒有任何 prompt 說明「原文可能是任何語言，輸出一律翻成繁中」這條跨語言規則；
3. 決定性因素是「外語內容佔比」——實測同一篇文章：
   - 前 2000 / 6000 字輸入 -> 穩定輸出繁中
   - 完整 15263 字輸入     -> 穩定輸出日文
   該頁正文僅約 6300 字，其餘約 9000 字是日文導覽列、頁尾與推薦連結，
   這堆雜訊把語言指示壓過去。單靠加強指示（system_instruction、結尾重申語言、
   降 temperature）在完整長度下都只是機率性改善，實測仍會翻車。

修法（結構性，而非機率性）：
非中文來源先經過一道 zh-TW 正規化（壓縮式重寫成繁中重點筆記，同時濾掉導覽/頁尾雜訊），
後續產文階段就完全看不到外語，沒有可模仿的對象。
中文來源直接跳過這道，不增加延遲。system_instruction 與 prompt 內的跨語言規則保留為第二道防線。

註：實測「忠實翻譯」式的正規化會失敗（模型照抄原文語言，kana 0.53），
必須是壓縮式重寫才穩定（kana 0.000），因此正規化階段刻意寫成「重點筆記」。

執行：
    pytest tests/test_output_language.py                 # 只跑不需 API 的單元測試
    RUN_LIVE_TESTS=1 pytest tests/test_output_language.py # 額外跑 live 整合測試
"""
import json
import os

import pytest

from loader import langtools
from loader.langtools import (
    OUTPUT_LANGUAGE_INSTRUCTION,
    SocialMediaPosts,
    _build_social_media_prompt,
    _is_predominantly_chinese,
    prepare_source_text,
    generate_research_report,
    generate_social_media_posts,
    summarize_for_bookmark,
    summarize_text_with_mode,
)
from tools import summarizer as summarizer_tool
from tools import youtube_tool

JA_TEXT = "これはリモートワークの生産性に関する記事です。実際のデータと事例を含みます。"
ZH_TEXT = "這是一篇關於遠端工作如何提升生產力的文章，內含實際數據與案例，並討論台灣企業的導入經驗。"
NORMALIZED = "【正規化後的繁體中文重點筆記】遠端工作與生產力。"

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "itmedia_ja_article.txt")

SOCIAL_JSON = json.dumps({
    "title": "t", "summary_analysis": "s",
    "facebook": "f", "linkedin": "l", "threads": "th",
})
BOOKMARK_JSON = json.dumps({"title": "t", "summary": "s"})


# --- 測試替身：攔截每一次 generate_content 的 contents 與 config ---

class _FakeResponse:
    def __init__(self, text):
        self.text = text
        self.candidates = []


class _FakeModels:
    def __init__(self, calls, texts):
        self._calls = calls
        self._texts = list(texts)

    def generate_content(self, *, model, contents, config):
        self._calls.append({"contents": contents, "config": config})
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        return _FakeResponse(text)


class _FakeClient:
    def __init__(self, calls, texts):
        self.models = _FakeModels(calls, texts)


def _patch_client(monkeypatch, module, texts, attr="_get_vertex_client"):
    """把模組的 client factory 換掉，回傳被記錄下來的呼叫 list。

    重試邏輯每次都會重新取得 client，所以固定回傳同一個替身實例，
    回應序列才不會被重置。
    """
    calls = []
    client = _FakeClient(calls, texts)
    monkeypatch.setattr(module, attr, lambda *a, **kw: client)
    return calls


def _system_text(call):
    instruction = getattr(call["config"], "system_instruction", None)
    if instruction is None:
        return ""
    return instruction if isinstance(instruction, str) else str(instruction)


# --- 單元測試：共用語言指示 ---

def test_output_language_instruction_states_cross_language_rule():
    """共用指示必須明確涵蓋『原文是別的語言時要翻成繁中』，而不只是說『用繁中』。"""
    assert "繁體中文" in OUTPUT_LANGUAGE_INSTRUCTION
    assert "台灣用語" in OUTPUT_LANGUAGE_INSTRUCTION
    assert "日文" in OUTPUT_LANGUAGE_INSTRUCTION
    assert "英文" in OUTPUT_LANGUAGE_INSTRUCTION


def test_output_language_instruction_allows_proper_nouns():
    """人名、機構、產品名允許保留原文，避免硬翻造成錯誤。"""
    assert "原文" in OUTPUT_LANGUAGE_INSTRUCTION


def test_output_language_instruction_rejects_japanese_kanji_words():
    """實測殘留：輸出已是繁中，仍會混進「掲示板」這種日文漢字詞。"""
    assert "掲示板" in OUTPUT_LANGUAGE_INSTRUCTION
    assert "簡體字" in OUTPUT_LANGUAGE_INSTRUCTION


# --- 單元測試：來源語言判斷 ---

def test_chinese_source_detected_as_chinese():
    assert _is_predominantly_chinese(ZH_TEXT)


def test_japanese_source_not_detected_as_chinese():
    """日文有大量漢字，必須靠假名判別，不能只看漢字比例。"""
    assert not _is_predominantly_chinese(JA_TEXT)


def test_real_japanese_article_not_detected_as_chinese():
    with open(FIXTURE, encoding="utf-8") as f:
        assert not _is_predominantly_chinese(f.read())


def test_english_source_not_detected_as_chinese():
    assert not _is_predominantly_chinese(
        "This is an article about how remote work improves productivity, "
        "with real data and case studies from several companies."
    )


def test_chinese_with_few_japanese_proper_nouns_still_chinese():
    """中文文章引用少量日文專有名詞，不該被誤判成日文而多跑一次正規化。"""
    assert _is_predominantly_chinese(
        "這篇文章介紹日本企業的遠端工作制度，受訪者任職於サイボウズ，"
        "並分享了導入前後的生產力數據與實際案例，值得台灣企業參考。"
    )


def test_clean_output_gate_is_stricter_than_source_detection():
    """驗收自己的產出要比判斷來源嚴格：實測出現過假名佔比 0.149 的中日混雜結果，
    它通得過來源門檻（0.20）卻明顯不是可用的繁中。"""
    half_baked = (
        "這起事件顯示 AIエージェント會自行建立秘密の掲示板進行溝通，並分工協作、"
        "交換セキュリティ漏洞資訊，最終突破網路限制，對台灣的資安團隊是一記警鐘，"
        "值得所有導入自動化流程的企業重新檢視自身的權限控管與監控機制。"
    )
    foreign, han, _ = langtools._script_profile(half_baked)
    assert 0.05 < foreign < 0.20, f"這個樣本要落在兩個門檻之間，實際 {foreign}"
    assert langtools._is_predominantly_chinese(half_baked)
    assert not langtools._is_clean_zh_output(half_baked)


def test_clean_output_gate_rejects_untranslated_english():
    """英文來源若被原封照抄，假名佔比是 0，必須靠漢字比例擋下來。"""
    assert not langtools._is_clean_zh_output(
        "This is an article about how remote work improves productivity, "
        "with real data and case studies from several companies."
    )


def test_clean_output_gate_accepts_chinese_with_a_stray_proper_noun():
    assert langtools._is_clean_zh_output(
        "這起事件由 OpenAI 的研究團隊揭露，相關討論在日本媒體 ITmedia 上引發關注，"
        "台灣的資安社群也開始討論自動化防禦的必要性，並整理出幾項具體建議與作法。"
    )


def test_empty_text_treated_as_chinese():
    """空字串沒有可判斷的文字，不該觸發多餘的 API 呼叫。"""
    assert _is_predominantly_chinese("")


# --- 單元測試：正規化只在需要時發生 ---

def test_chinese_source_skips_normalization(monkeypatch):
    """中文來源不該多花一次 API 呼叫。"""
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED])

    assert prepare_source_text(ZH_TEXT) == ZH_TEXT
    assert calls == []


def test_japanese_source_is_normalized(monkeypatch):
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED])

    assert prepare_source_text(JA_TEXT) == NORMALIZED
    assert len(calls) == 1
    assert JA_TEXT in calls[0]["contents"]
    assert OUTPUT_LANGUAGE_INSTRUCTION in _system_text(calls[0])


def test_normalization_retries_when_output_still_japanese(monkeypatch):
    """實測正規化階段自己也會照抄原文語言（temp 0 仍量到假名佔比 0.40），
    所以必須驗收自己的輸出並重試。"""
    calls = _patch_client(monkeypatch, langtools, [JA_TEXT, NORMALIZED])

    assert prepare_source_text(JA_TEXT) == NORMALIZED
    assert len(calls) == 2, "第一次輸出仍是日文時要重試"
    assert "【重要】" in calls[1]["contents"], "重試時要追加強化指令"


def test_normalization_gives_up_after_retry(monkeypatch):
    """重試後仍是日文就退回原文，交給第二道防線，不要無限重試。"""
    calls = _patch_client(monkeypatch, langtools, [JA_TEXT, JA_TEXT])

    assert prepare_source_text(JA_TEXT) == JA_TEXT
    assert len(calls) == 2


def test_normalization_failure_falls_back_to_original(monkeypatch):
    """正規化失敗不能讓整個流程掛掉，退回原文由第二道防線處理。"""
    def _boom(*a, **kw):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(langtools, "_get_vertex_client", _boom)
    assert prepare_source_text(JA_TEXT) == JA_TEXT


# --- 單元測試：各進入點都吃到正規化後的繁中文字 ---

def test_social_media_posts_generates_from_normalized_text(monkeypatch):
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED, SOCIAL_JSON])

    generate_social_media_posts(JA_TEXT)

    assert len(calls) == 2, "應先正規化再產貼文"
    generation = calls[1]
    assert NORMALIZED in generation["contents"]
    assert JA_TEXT not in generation["contents"], "產文階段不該再看到日文原文"
    assert OUTPUT_LANGUAGE_INSTRUCTION in _system_text(generation)


def test_bookmark_summary_generates_from_normalized_text(monkeypatch):
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED, BOOKMARK_JSON])

    summarize_for_bookmark(JA_TEXT)

    assert len(calls) == 2
    assert NORMALIZED in calls[1]["contents"]
    assert JA_TEXT not in calls[1]["contents"]


def test_research_report_generates_from_normalized_text(monkeypatch):
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED, "## 執行摘要\n內容"])

    generate_research_report(JA_TEXT, "https://example.com/ja")

    assert len(calls) == 2
    assert NORMALIZED in calls[1]["contents"]
    assert JA_TEXT not in calls[1]["contents"]


def test_research_report_normalization_keeps_more_detail(monkeypatch):
    """研究報告需要細節，正規化階段的篇幅預算要比一般摘要大。"""
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED, "## 執行摘要"])
    generate_research_report(JA_TEXT, "https://example.com/ja")
    detailed_prompt = calls[0]["contents"]

    calls2 = _patch_client(monkeypatch, langtools, [NORMALIZED, SOCIAL_JSON])
    generate_social_media_posts(JA_TEXT)
    normal_prompt = calls2[0]["contents"]

    assert detailed_prompt != normal_prompt
    assert "詳盡" in detailed_prompt


@pytest.mark.parametrize("mode", ["short", "normal", "detailed"])
def test_summarize_text_generates_from_normalized_text(monkeypatch, mode):
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED, "- 重點"])

    summarize_text_with_mode(JA_TEXT, mode=mode)

    assert len(calls) == 2
    assert NORMALIZED in calls[1]["contents"]
    assert JA_TEXT not in calls[1]["contents"]


def test_summarizer_tool_generates_from_normalized_text(monkeypatch):
    """agents/content_agent 走的是 tools.summarizer，同一個 bug 也要修。"""
    calls = _patch_client(monkeypatch, langtools, [NORMALIZED])
    tool_calls = _patch_client(monkeypatch, summarizer_tool, ["- 重點"])

    result = summarizer_tool.summarize_text(JA_TEXT)

    assert result["status"] == "success"
    assert len(calls) == 1, "正規化仍走 langtools 的 client"
    assert NORMALIZED in tool_calls[0]["contents"]
    assert JA_TEXT not in tool_calls[0]["contents"]
    assert OUTPUT_LANGUAGE_INSTRUCTION in _system_text(tool_calls[0])


def test_youtube_tool_pins_output_language(monkeypatch):
    """影片無法先正規化文字，至少要把 system_instruction 釘上去。"""
    calls = []
    monkeypatch.setattr(youtube_tool, "VERTEX_PROJECT", "test-project")
    monkeypatch.setattr(
        youtube_tool.genai, "Client",
        lambda *a, **kw: _FakeClient(calls, ["- 重點"]),
    )

    result = youtube_tool.summarize_youtube_video(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result["status"] == "success"
    assert len(calls) == 1
    assert OUTPUT_LANGUAGE_INSTRUCTION in _system_text(calls[0])


# --- 單元測試：prompt 與 schema 的第二道防線 ---

def test_social_prompt_states_cross_language_rule():
    """prompt 內文也要寫明跨語言規則，且要放在原文之後（近因效應）。"""
    prompt = _build_social_media_prompt(ZH_TEXT)
    assert "日文" in prompt and "英文" in prompt
    assert prompt.rindex("繁體中文") > prompt.index(ZH_TEXT)


def test_social_schema_fields_require_traditional_chinese():
    """三平台欄位的 schema description 原本完全沒提語言，補上才有約束力。"""
    fields = SocialMediaPosts.model_fields
    for name in ("facebook", "linkedin", "threads"):
        assert "繁體中文" in fields[name].description, f"{name} 欄位未要求繁體中文"


# --- 整合測試：需 Vertex AI，預設略過 ---

def _kana_ratio(text: str) -> float:
    """日文假名佔比。中日文共用漢字，所以用假名當作『輸出是日文』的判準。"""
    if not text:
        return 0.0
    kana = sum(1 for ch in text if "぀" <= ch <= "ゟ" or "゠" <= ch <= "ヿ")
    return kana / len(text)


def _load_fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


live_only = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="需要 Vertex AI 憑證，設定 RUN_LIVE_TESTS=1 才執行",
)


@live_only
def test_live_full_japanese_article_produces_traditional_chinese():
    """回歸測試：用真實爬回來的完整 15k 日文頁面（含導覽/頁尾雜訊），
    這正是修復前穩定失敗的輸入。"""
    result = generate_social_media_posts(_load_fixture())
    for field, value in result.items():
        assert value and value.strip(), f"{field} 為空"
        assert _kana_ratio(value) < 0.02, f"{field} 疑似輸出日文：{value[:80]}"


@live_only
def test_live_full_japanese_article_bookmark_summary_is_traditional_chinese():
    result = summarize_for_bookmark(_load_fixture())
    for field in ("title", "summary"):
        assert _kana_ratio(result[field]) < 0.02, \
            f"{field} 疑似輸出日文：{result[field][:80]}"


@live_only
def test_live_normalization_returns_clean_zh_tw_or_falls_back():
    """正規化是盡力而為，不是保證：實測它自己偶爾也會照抄原文語言。

    它提供的契約是「要嘛給乾淨繁中，要嘛原封不動退回原文」——
    絕不能吐出半吊子的中日混雜結果。真正的語言保證由端到端測試把關。
    """
    source = _load_fixture()
    normalized = prepare_source_text(source)

    if normalized == source:
        return  # 兩次都沒過關，已退回原文交給第二道防線
    assert _kana_ratio(normalized) < 0.05, f"正規化吐出中日混雜結果：{normalized[:100]}"
    assert len(normalized) > 200


@live_only
def test_live_chinese_article_unchanged_and_no_extra_call():
    """中文來源必須原封不動通過，不多花一次 API 呼叫。"""
    assert prepare_source_text(ZH_TEXT) == ZH_TEXT


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
