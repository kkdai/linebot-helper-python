"""測試：用量與成本記錄

背景：這個專案原本沒有任何 token／成本統計（roadmap P1-4）。影片問答讓這件事
從「想做」變成「必須做」——spike 實測 2 小時影片單次提問要 $0.91，
沒有記錄就完全不知道錢花到哪去。

配額以實際花費計，不以影片長度計：用長度得先查影片時長（需另接 YouTube
Data API），而且長度與花費非線性（10 分鐘 $0.0023、2 小時 $0.91）。

本階段只做記錄不做強制——未設 VIDEO_QA_DAILY_BUDGET_USD 即不限制。

記帳壞掉不能讓功能壞掉：Firestore 不可用時安靜降級（照 url_cache 慣例）。
"""
from unittest.mock import patch

import pytest

from services.usage_meter import UsageMeter
from tests.fakes import FakeStore, UnavailableStore

USER = "U-test-user"

# 對應 gemini-3.5-flash-lite：in $0.30 / out $2.50 每 1M tokens
USAGE_SHORT = {
    "model": "gemini-3.5-flash-lite",
    "prompt_tokens": 53, "output_tokens": 638, "thinking_tokens": 0,
    "tool_use_tokens": 2163, "total_tokens": 2854,
}
USAGE_LONG = {
    "model": "gemini-3.5-flash-lite",
    "prompt_tokens": 63, "output_tokens": 1376, "thinking_tokens": 359961,
    "tool_use_tokens": 22511, "total_tokens": 384254,
}


# --- 成本換算 ---

def test_estimate_cost_matches_spike_measurement():
    """對照 spike 實測：10 分鐘影片 agentic + thinking LOW 約 $0.0023。"""
    cost = UsageMeter(store=FakeStore()).estimate_cost(USAGE_SHORT)
    assert cost == pytest.approx(0.0023, abs=0.0005)


def test_thinking_tokens_are_billed_as_output():
    """thinking token 按 output 計價——這正是漏設 thinking_level 會爆成本的原因。"""
    meter = UsageMeter(store=FakeStore())
    cost = meter.estimate_cost(USAGE_LONG)
    assert cost == pytest.approx(0.9067, abs=0.01)


def test_unknown_model_does_not_crash():
    """模型換了但價目表沒更新時，記帳不能炸掉主流程。"""
    meter = UsageMeter(store=FakeStore())
    assert meter.estimate_cost({**USAGE_SHORT, "model": "gemini-9-unknown"}) == 0.0


# --- 累加 ---

def test_record_accumulates_daily_spend():
    meter = UsageMeter(store=FakeStore())
    meter.record(USER, "video_qa", USAGE_SHORT)
    meter.record(USER, "video_qa", USAGE_SHORT)
    # Stored costs are rounded to 6 decimal places, so accumulation is exact only to that precision.
    assert meter.spent_today(USER) == pytest.approx(2 * meter.estimate_cost(USAGE_SHORT), abs=1e-6)


def test_spend_is_per_user():
    meter = UsageMeter(store=FakeStore())
    meter.record(USER, "video_qa", USAGE_LONG)
    assert meter.spent_today("U-someone-else") == 0.0


def test_usage_survives_store_roundtrip():
    """instance 重啟後今日用量不歸零。"""
    store = FakeStore()
    UsageMeter(store=store).record(USER, "video_qa", USAGE_SHORT)
    assert UsageMeter(store=store).spent_today(USER) > 0


def test_record_returns_cost_of_this_call():
    meter = UsageMeter(store=FakeStore())
    assert meter.record(USER, "video_qa", USAGE_SHORT) == pytest.approx(
        meter.estimate_cost(USAGE_SHORT))


# --- 降級 ---

def test_firestore_unavailable_degrades_silently():
    """記帳壞掉不能讓影片問答壞掉（照 url_cache 慣例）。"""
    meter = UsageMeter(store=UnavailableStore())
    meter.record(USER, "video_qa", USAGE_SHORT)   # 不可拋例外
    assert meter.spent_today(USER) == 0.0


def test_store_exception_degrades_silently():
    store = FakeStore()
    meter = UsageMeter(store=store)
    with patch.object(store, "save", side_effect=RuntimeError("firestore down")):
        meter.record(USER, "video_qa", USAGE_SHORT)  # 不可拋例外


# --- 配額接縫 ---

def test_budget_unset_means_unlimited(monkeypatch):
    """本階段刻意不設上限（單一使用者）。接縫先放好，日後設環境變數即可開啟。"""
    monkeypatch.delenv("VIDEO_QA_DAILY_BUDGET_USD", raising=False)
    meter = UsageMeter(store=FakeStore())
    meter.record(USER, "video_qa", USAGE_LONG)
    allowed, remaining = meter.check_budget(USER)
    assert allowed is True
    assert remaining is None


def test_budget_blocks_when_exceeded(monkeypatch):
    monkeypatch.setenv("VIDEO_QA_DAILY_BUDGET_USD", "0.50")
    meter = UsageMeter(store=FakeStore())
    meter.record(USER, "video_qa", USAGE_LONG)   # $0.91 > $0.50
    allowed, remaining = meter.check_budget(USER)
    assert allowed is False
    assert remaining == pytest.approx(0.0)


def test_budget_allows_when_under(monkeypatch):
    monkeypatch.setenv("VIDEO_QA_DAILY_BUDGET_USD", "10.0")
    meter = UsageMeter(store=FakeStore())
    meter.record(USER, "video_qa", USAGE_SHORT)
    allowed, remaining = meter.check_budget(USER)
    assert allowed is True
    assert remaining == pytest.approx(10.0 - meter.estimate_cost(USAGE_SHORT))
