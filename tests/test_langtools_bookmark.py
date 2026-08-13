"""測試：社群貼文擴充（title + summary_analysis）與書籤摘要函式

- generate_social_media_posts 的 schema/prompt 需包含文章標題與摘要分析，
  讓 carousel 第一顆 bubble 與書籤候選同一次 API 呼叫取得資料
- summarize_for_bookmark 給 /save 指令用（title + summary）
"""
import pytest

from loader.langtools import (
    SocialMediaPosts,
    _build_social_media_prompt,
    generate_social_media_posts,
    summarize_for_bookmark,
)

SAMPLE_TEXT = "這是一篇關於遠端工作如何提升生產力的文章，內含實際數據與案例。"


def test_schema_includes_title_and_summary_analysis():
    fields = SocialMediaPosts.model_fields
    assert "title" in fields
    assert "summary_analysis" in fields


def test_prompt_asks_for_summary_and_analysis():
    prompt = _build_social_media_prompt(SAMPLE_TEXT)
    assert "摘要" in prompt and "分析" in prompt


def test_empty_input_fallback_has_new_keys():
    result = generate_social_media_posts("")
    assert "title" in result
    assert "summary_analysis" in result
    # 既有欄位不能少
    assert "facebook" in result and "linkedin" in result and "threads" in result


def test_summarize_for_bookmark_empty_input_returns_fallback():
    result = summarize_for_bookmark("")
    assert result["title"]
    assert result["summary"]
