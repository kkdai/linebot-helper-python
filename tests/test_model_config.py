"""測試：模型設定的單一來源與選用規則

背景：2026-09-02 發現 loader/chat_session.py 寫死的 gemini-3-pro-preview
已從 Vertex AI 下架，聊天功能整段時間壞掉沒人發現（PR #17）。
根因不只是那一行——全 repo 有 28 處硬寫的模型字面值，換模型要全域掃描，
而且沒有任何地方記錄「哪些模型可以用」。

這裡守三件事：
1. 模型 ID 只能出現在 config/agent_config.py（兩個必要例外除外）
2. 不得使用 preview／實驗模型（會無預警下架）
3. 影片模型必須在 agentic 支援名單內
"""
import re
from pathlib import Path

import pytest

from config.agent_config import get_agent_config

REPO_ROOT = Path(__file__).resolve().parent.parent

# Live API 僅支援 gemini-3.1-flash-live-preview；TTS 是獨立模型家族。
# 這兩處必須維持 preview 模型，不在守衛範圍內。
EXEMPT_FILES = {"services/voice_live.py", "tools/tts_tool.py"}

# 2026-09-02 於 Vertex AI 實測可用。新增前請先實測，不要憑文件加。
VERIFIED_MODELS = {
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
}

# agentic video understanding 支援名單（其餘模型會靜默降級為 STATIC）
AGENTIC_CAPABLE = {"gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"}


def _source_files():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        # Exclude tests, docs, gitignored scratch dirs, and cache
        if rel.startswith(("tests/", "docs/", ".superpowers/")) or "__pycache__" in rel:
            continue
        yield rel, path


def test_no_hardcoded_model_ids_outside_config():
    """模型 ID 只能出現在 config/agent_config.py。

    這個測試存在的理由：這次要掃 27 處才能換一個模型。收斂之後，
    換模型是改一個環境變數，而這個測試防止它再度散開。
    """
    offenders = []
    for rel, path in _source_files():
        if rel in EXEMPT_FILES or rel == "config/agent_config.py":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r'["\']gemini-[0-9]', line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "模型 ID 只能定義在 config/agent_config.py，發現硬寫：\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("field", ["chat_model", "fast_model",
                                   "orchestrator_model", "video_model"])
def test_configured_models_are_not_preview(field):
    """preview 模型會無預警下架（gemini-3-pro-preview 就是這樣）。"""
    model = getattr(get_agent_config(), field)
    assert not re.search(r"-(preview|exp|experimental)\b", model), (
        f"{field} 不可使用 preview／實驗模型，目前為 {model!r}"
    )


@pytest.mark.parametrize("field", ["chat_model", "fast_model",
                                   "orchestrator_model", "video_model"])
def test_configured_models_are_verified_available(field):
    model = getattr(get_agent_config(), field)
    assert model in VERIFIED_MODELS, (
        f"{field}={model!r} 不在實測可用清單：{sorted(VERIFIED_MODELS)}"
    )


def test_video_model_supports_agentic():
    """影片模型若不在支援名單，media_processing='AGENTIC' 會被靜默降級為 STATIC。"""
    model = get_agent_config().video_model
    assert model in AGENTIC_CAPABLE, (
        f"video_model={model!r} 不支援 agentic，會靜默降級為 STATIC。"
        f"可用：{sorted(AGENTIC_CAPABLE)}"
    )


def test_video_model_is_flash_lite():
    """gemini-3.7-flash 在 agentic 影片會忽略 thinking_level，成本是 3.5-flash-lite 的 60 倍。"""
    assert get_agent_config().video_model == "gemini-3.5-flash-lite"


# --- 反向守衛：這兩處必須維持 preview 模型 ---
# 這次要掃 27 處模型字面值，下次掃的人不會記得這兩個例外。
# 用測試記住，比用註解記住可靠。

def test_voice_live_model_unchanged():
    """Live API 只支援 gemini-3.1-flash-live-preview，換掉會讓語音助理整個壞掉。"""
    from services.voice_live import VOICE_MODEL
    assert VOICE_MODEL == "gemini-3.1-flash-live-preview", (
        f"voice_live 的模型不可更動（目前 {VOICE_MODEL!r}）——"
        "Live API 僅支援 gemini-3.1-flash-live-preview，3.7-flash 不支援 Live API"
    )


def test_tts_model_unchanged():
    """TTS 是獨立模型家族，一般文字模型不會產生音訊。"""
    from tools.tts_tool import TTS_MODEL
    assert TTS_MODEL == "gemini-3.1-flash-tts-preview", (
        f"tts_tool 的模型不可更動（目前 {TTS_MODEL!r}）——TTS 為獨立模型家族"
    )
