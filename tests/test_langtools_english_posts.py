"""測試：英文版社群貼文（🇺🇸 英文貼文按鈕按需產生）

- SocialMediaPostsEN schema／prompt 只需 facebook/linkedin/threads/twitter 四個英文欄位
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


def test_schema_has_four_platform_fields_only():
    fields = SocialMediaPostsEN.model_fields
    assert {"facebook", "linkedin", "threads", "twitter"} <= set(fields.keys())
    # 不重複產生標題／摘要，那些沿用中文版初次產生的結果
    assert "title" not in fields
    assert "summary_analysis" not in fields


def test_prompt_contains_article_text():
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert SAMPLE_TEXT in prompt


def test_prompt_includes_english_humanize_guidelines():
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert HUMANIZE_GUIDELINES_EN in prompt


def test_prompt_mentions_all_four_platforms():
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert "Facebook" in prompt
    assert "LinkedIn" in prompt
    assert "Threads" in prompt
    assert "Twitter/X" in prompt


def test_threads_is_professional_and_attributes_results():
    """Threads 定位改為專業從業者，且不得冒認原文團隊的成果。"""
    prompt = _build_social_media_prompt_en(SAMPLE_TEXT)
    assert "## 3. Meta Threads professional take:" in prompt
    section = prompt.split("## 3. Meta Threads professional take:")[1].split("## 4.")[0]
    assert "experienced practitioner" in section
    assert "not a random person venting" in section
    assert "meme voice" in section
    assert "Never claim the article's results as your own" in section
    # 短段落仍是 Threads 的特性，不能一起被砍掉
    assert "short paragraphs" in section


# --- Twitter/X senior engineering director post ---

TWITTER_HEADING = "## 4. Twitter/X recommendation from a senior engineering director:"


def _twitter_section(text: str = SAMPLE_TEXT) -> str:
    prompt = _build_social_media_prompt_en(text)
    assert TWITTER_HEADING in prompt
    return prompt.split(TWITTER_HEADING)[1]


def test_twitter_persona_is_senior_engineering_director():
    """人設必須是資深軟體總監，第一人稱推薦。"""
    section = _twitter_section()
    assert "senior engineering director" in section
    assert "in the first person" in section


def test_twitter_requires_first_person_and_bans_analyst_voice():
    """至少一次 "I"，且禁分析報告句型（含 not X but Y 的變形）。"""
    section = _twitter_section()
    assert 'must use "I" at least once' in section
    assert "No analyst-report phrasing" in section
    assert "it's not about X, it's about Y" in section


def test_twitter_forbids_fabricated_experience():
    """真人化但不造假：文中數字須看得出是原文作者的。"""
    section = _twitter_section()
    assert "Do NOT invent company names" in section
    assert "never as your own team's win" in section


def test_twitter_single_tweet_constraints():
    """單則推文限制：字數、emoji、hashtag、不自己貼網址。"""
    section = _twitter_section()
    assert "30-45 words" in section
    assert "under 240 characters" in section
    assert "280 characters" in section
    assert "at most 1, or none" in section      # emoji
    assert "Hashtags: 0-2" in section
    assert "Do not paste a URL yourself" in section


def test_twitter_schema_description_carries_key_constraints():
    """structured output 會吃 field description，人設與字數也要寫在那。"""
    desc = SocialMediaPostsEN.model_fields["twitter"].description
    assert "senior engineering director" in desc
    assert "30-45 words" in desc
    assert "first-person" in desc


def test_empty_input_returns_fallback_without_calling_api():
    result = generate_social_media_posts_en("")
    assert {"facebook", "linkedin", "threads", "twitter"} <= set(result.keys())
    for value in result.values():
        assert value


def test_whitespace_only_input_returns_fallback():
    result = generate_social_media_posts_en("   \n  ")
    assert {"facebook", "linkedin", "threads", "twitter"} <= set(result.keys())


# --- 整合測試：需 Vertex AI，預設略過 ---

@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="需要 Vertex AI 憑證，設定 RUN_LIVE_TESTS=1 才執行",
)
def test_live_generation_returns_four_english_posts():
    result = generate_social_media_posts_en(SAMPLE_TEXT)
    assert {"facebook", "linkedin", "threads", "twitter"} <= set(result.keys())
    for platform, value in result.items():
        assert value and value.strip(), f"{platform} post is empty"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
