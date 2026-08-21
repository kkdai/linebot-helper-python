"""測試：英文版社群貼文（🇺🇸 英文貼文按鈕按需產生）

- SocialMediaPostsEN schema／prompt 只需 facebook/linkedin/threads 三個英文欄位
  （title/summary_analysis 沿用中文版初次產生的結果，不重複產生）
- 空輸入需回 fallback，且不呼叫 API
"""
import os
import pytest

from loader.langtools import (
    SocialMediaPostsEN,
    HUMANIZE_GUIDELINES_EN,
    _build_social_media_prompt_en,
    generate_social_media_posts_en,
)

SAMPLE_TEXT = "This is an article about how remote work can improve productivity, with real data and case studies."


def test_schema_has_three_platform_fields_only():
    fields = SocialMediaPostsEN.model_fields
    assert {"facebook", "linkedin", "threads"} <= set(fields.keys())
    # 不重複產生標題／摘要，那些沿用中文版初次產生的結果
    assert "title" not in fields
    assert "summary_analysis" not in fields


def test_prompt_contains_article_text():
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert SAMPLE_TEXT in prompt


def test_prompt_includes_english_humanize_guidelines():
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert HUMANIZE_GUIDELINES_EN in prompt


def test_prompt_mentions_all_three_platforms():
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert "Facebook" in prompt
    assert "LinkedIn" in prompt
    assert "Threads" in prompt


def test_empty_input_returns_fallback_without_calling_api():
    result = generate_social_media_posts_en("")
    assert {"facebook", "linkedin", "threads"} <= set(result.keys())
    for value in result.values():
        assert value


def test_whitespace_only_input_returns_fallback():
    result = generate_social_media_posts_en("   \n  ")
    assert {"facebook", "linkedin", "threads"} <= set(result.keys())


# --- 整合測試：需 Vertex AI，預設略過 ---

@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="需要 Vertex AI 憑證，設定 RUN_LIVE_TESTS=1 才執行",
)
def test_live_generation_returns_three_english_posts():
    result = generate_social_media_posts_en(SAMPLE_TEXT)
    assert {"facebook", "linkedin", "threads"} <= set(result.keys())
    for platform, value in result.items():
        assert value and value.strip(), f"{platform} post is empty"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
