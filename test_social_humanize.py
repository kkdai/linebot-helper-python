#!/usr/bin/env python3
"""測試：社群貼文人性化（方案 A - 單一 Pass 注入）

驗證 humanizer 的人性化守則已正確注入 prompt，且不破壞既有結構。

- 單元測試（不需 API）：prompt 組裝、守則注入、per-platform 調整、空輸入 fallback
- 整合測試（需 Vertex AI）：實際呼叫 Gemini，僅在設定 RUN_LIVE_TESTS=1 時執行

執行：
    pytest test_social_humanize.py                 # 只跑不需 API 的單元測試
    RUN_LIVE_TESTS=1 pytest test_social_humanize.py # 額外跑 live 整合測試
"""
import os
import pytest

from loader.langtools import (
    HUMANIZE_GUIDELINES,
    _build_social_media_prompt,
    generate_social_media_posts,
)

SAMPLE_TEXT = "這是一篇關於遠端工作如何提升生產力的文章，內含實際數據與案例。"


# --- 單元測試：不需 API ---

def test_prompt_includes_humanize_guidelines():
    """人性化守則必須整段注入 prompt。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    assert HUMANIZE_GUIDELINES in prompt


def test_guidelines_placed_before_writing_guide():
    """守則須放在排版技巧「之前」，以確保衝突時人味優先。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    assert prompt.index("人性化守則") < prompt.index("# 寫作指南")


def test_prompt_contains_article_text():
    """網頁內容必須被帶入 prompt。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    assert SAMPLE_TEXT in prompt


def test_key_humanize_rules_present():
    """抽查幾條關鍵人性化規則確實存在。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    assert "先保事實" in prompt
    assert "AI 開場定型句" in prompt
    assert "具體 ＞ 抽象" in prompt


def test_taiwan_localization_rules_present():
    """speak-human-tw 的台灣在地化規則（中國用語替換、全形標點、語氣詞）必須注入。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    # 中國用語替換表抽查
    assert "視頻→影片" in prompt
    assert "質量→品質" in prompt
    # 全形標點與台灣語氣詞
    assert "全形標點" in prompt
    assert "台灣語氣詞" in prompt


def test_per_platform_tuning_present():
    """三平台的人性化微調文字都要在 prompt 內。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    # Facebook：開場改真實痛點、禁假掰誇張
    assert "禁止假掰誇張詞" in prompt
    # LinkedIn：守則權重高、禁 buzzword 空堆、禁 AI 正式腔套語
    assert "buzzword 空堆" in prompt
    assert "人性化守則權重高" in prompt
    assert "禁 AI 正式腔套語" in prompt or "嚴禁 AI 正式腔套語" in prompt
    # Threads：人性化守則權重最高
    assert "人性化守則權重最高" in prompt


def test_viral_energy_preserved():
    """人性化不應犧牲爆款目標，『爆款』框架仍在。"""
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    assert "爆款" in prompt
    assert "Hashtag" in prompt


def test_empty_input_returns_fallback():
    """空輸入應回傳含三鍵的 fallback，且不呼叫 API。"""
    result = generate_social_media_posts("")
    assert set(result.keys()) == {"facebook", "linkedin", "threads"}
    for value in result.values():
        assert "無法" in value


def test_whitespace_only_input_returns_fallback():
    """只有空白的輸入也走 fallback。"""
    result = generate_social_media_posts("   \n  ")
    assert set(result.keys()) == {"facebook", "linkedin", "threads"}


# --- 整合測試：需 Vertex AI，預設略過 ---

@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="需要 Vertex AI 憑證，設定 RUN_LIVE_TESTS=1 才執行",
)
def test_live_generation_returns_three_posts():
    """實際呼叫 Gemini，回傳三平台文案且非空。"""
    result = generate_social_media_posts(SAMPLE_TEXT)
    assert set(result.keys()) == {"facebook", "linkedin", "threads"}
    for platform, value in result.items():
        assert value and value.strip(), f"{platform} 文案為空"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
