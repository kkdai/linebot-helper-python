"""測試：聊天 session 使用的模型必須是 stable 模型

背景：2026-09-02 實測發現 `loader/chat_session.py` 寫死的 `gemini-3-pro-preview`
已經從 Vertex AI 下架，真實路徑（chats.create + send_message + Google Search
grounding）回 404 NOT_FOUND，而該檔的例外處理是直接 raise。

結果是 README 首項功能「Intelligent Conversation with Memory」整個無法使用，
而且沒有任何測試會發現——因為沒有任何測試碰過這個模組。

這裡守的是 bug class 而不是單一字串：**preview 模型會無預警下架**。
所以測試斷言的是「不准用 preview 模型」，而不是「等於某個特定字串」——
後者只會在下次有人換模型時被順手改掉，擋不住同一個坑再踩一次。

不打網路：只讀模組層級的常數。
"""
import re

import pytest

from loader.chat_session import CHAT_MODEL


# 2026-09-02 於 line-vertex 專案實測可用，且走 Google Search grounding 正常。
# 新增模型前請先實測，不要憑文件加。
VERIFIED_STABLE_MODELS = {
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
}


def test_chat_model_is_not_a_preview_model():
    """preview 模型會無預警下架，聊天是招牌功能，不能押在上面。

    這個測試若失敗，代表有人把 chat 換回了 preview 模型——
    gemini-3-pro-preview 就是這樣把功能弄壞了整段時間都沒人發現。
    """
    assert not re.search(r"-(preview|exp|experimental)\b", CHAT_MODEL), (
        f"聊天不可使用 preview／實驗模型，目前為 {CHAT_MODEL!r}。"
        "preview 模型會無預警下架（見 gemini-3-pro-preview 404）。"
    )


def test_chat_model_is_a_verified_available_model():
    """模型必須是實測過確實存在、且支援 grounding 的那幾個之一。"""
    assert CHAT_MODEL in VERIFIED_STABLE_MODELS, (
        f"{CHAT_MODEL!r} 不在實測可用清單中：{sorted(VERIFIED_STABLE_MODELS)}。"
        "換模型前請先對 Vertex AI 實測 chats.create + send_message + grounding。"
    )


def test_dead_model_is_not_reintroduced():
    """明確擋掉已知已下架的模型 ID。"""
    known_dead = {"gemini-3-pro-preview"}
    assert CHAT_MODEL not in known_dead, (
        f"{CHAT_MODEL!r} 已從 Vertex AI 下架（404 NOT_FOUND），不可使用。"
    )


def test_chat_session_uses_the_module_constant():
    """確保常數真的有被 create 路徑用到，而不是宣告了卻沒接上。

    只驗證原始碼裡沒有殘留的模型字面值——不建立 client（那需要憑證）。
    """
    import inspect

    import loader.chat_session as mod

    source = inspect.getsource(mod)
    hardcoded = re.findall(r'model\s*=\s*["\']gemini-[^"\']+["\']', source)
    assert not hardcoded, (
        f"chats.create 應使用 CHAT_MODEL 常數，發現寫死的模型字串：{hardcoded}"
    )
