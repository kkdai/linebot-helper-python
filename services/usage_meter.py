"""用量與成本記錄

每次 Gemini 呼叫的 token 數與換算後成本，按「使用者 + 日期」累加進 Firestore。

配額以實際花費計，不以影片長度計——用長度得先查影片時長（需另接 YouTube
Data API），且長度與花費非線性（10 分鐘 $0.0023、2 小時 $0.91）。

記帳失敗一律安靜降級，不影響主流程（照 services/url_cache.py 慣例）。
"""
import logging
import os
from datetime import date
from typing import Optional, Tuple

from config.agent_config import MODEL_PRICING
from services.firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

USAGE_COLLECTION = "usage_records"


class UsageMeter:
    def __init__(self, store=None):
        self._store = store if store is not None else FirestoreKVStore(USAGE_COLLECTION)

    @property
    def available(self) -> bool:
        try:
            return bool(self._store.is_available)
        except Exception:
            return False

    @staticmethod
    def _key(user_id: str, day: Optional[date] = None) -> str:
        return f"{user_id}:{(day or date.today()).isoformat()}"

    def estimate_cost(self, usage: dict) -> float:
        """把 usage dict 換算成美金。未知模型回 0.0，不拋例外。"""
        price = MODEL_PRICING.get(usage.get("model", ""))
        if price is None:
            logger.warning("No pricing for model %r; recording cost as 0",
                           usage.get("model"))
            return 0.0
        price_in, price_out = price
        tokens_in = (usage.get("prompt_tokens", 0) or 0) + \
                    (usage.get("tool_use_tokens", 0) or 0)
        tokens_out = (usage.get("output_tokens", 0) or 0) + \
                     (usage.get("thinking_tokens", 0) or 0)
        return tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out

    def record(self, user_id: str, feature: str, usage: dict) -> float:
        """累加一次呼叫的用量，回傳本次花費（美金）。

        記帳失敗不影響主流程——照樣回傳成本，只是沒存進去。
        """
        cost = self.estimate_cost(usage)
        if not self.available:
            return cost
        try:
            key = self._key(user_id)
            doc = self._store.load(key) or {}
            doc["user_id"] = user_id
            doc["date"] = date.today().isoformat()
            doc["cost_usd"] = round(doc.get("cost_usd", 0.0) + cost, 6)
            doc["calls"] = doc.get("calls", 0) + 1
            doc["total_tokens"] = doc.get("total_tokens", 0) + \
                (usage.get("total_tokens", 0) or 0)
            by_feature = doc.get("by_feature", {})
            by_feature[feature] = round(by_feature.get(feature, 0.0) + cost, 6)
            doc["by_feature"] = by_feature
            self._store.save(key, doc)
            logger.info("usage: user=%s feature=%s cost=$%.4f tokens=%s "
                        "(thinking=%s tool_use=%s) today=$%.4f",
                        user_id, feature, cost, usage.get("total_tokens"),
                        usage.get("thinking_tokens"), usage.get("tool_use_tokens"),
                        doc["cost_usd"])
        except Exception as e:
            logger.warning("Failed to record usage (degrading silently): %s", e)
        return cost

    def spent_today(self, user_id: str) -> float:
        if not self.available:
            return 0.0
        try:
            doc = self._store.load(self._key(user_id))
            return float(doc.get("cost_usd", 0.0)) if doc else 0.0
        except Exception as e:
            logger.warning("Failed to read usage (degrading silently): %s", e)
            return 0.0

    def check_budget(self, user_id: str) -> Tuple[bool, Optional[float]]:
        """回傳 (是否允許, 剩餘額度)。

        未設 VIDEO_QA_DAILY_BUDGET_USD 即不限制，剩餘額度回 None。
        這是刻意留的接縫：目前只有單一使用者，先開滿。
        """
        raw = os.getenv("VIDEO_QA_DAILY_BUDGET_USD")
        if not raw:
            return True, None
        try:
            limit = float(raw)
        except ValueError:
            logger.warning("Invalid VIDEO_QA_DAILY_BUDGET_USD=%r; treating as unlimited", raw)
            return True, None
        spent = self.spent_today(user_id)
        return (spent < limit), max(0.0, limit - spent)


_usage_meter: Optional[UsageMeter] = None


def get_usage_meter() -> UsageMeter:
    global _usage_meter
    if _usage_meter is None:
        _usage_meter = UsageMeter()
    return _usage_meter
