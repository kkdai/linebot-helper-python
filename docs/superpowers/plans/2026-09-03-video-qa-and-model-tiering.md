# 影片問答與模型分級升級 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 LINE bot 支援「問這部影片」——使用者可連續追問 YouTube 影片內容並取得精準時間戳；同時把全 repo 27 處模型字面值分三級升級並收斂進單一設定檔。

**Architecture:** 影片問答採 **stateless 重新查詢**（Vertex AI 無法保留影片 context，見 spec Spike 結論一），`services/video_qa.py` 只記「使用者 → 影片」的對應，`services/usage_meter.py` 記錄每次呼叫的 token 與成本，`tools/youtube_tool.py` 是唯一與 Gemini 影片 API 溝通的地方。`main.py` 只增加兩個接點。

**Tech Stack:** Python 3.12、google-genai 2.21.0（Vertex AI，`v1beta1`）、FastAPI、line-bot-sdk 3.14.0、Firestore、pytest

**Spec:** `docs/superpowers/specs/2026-09-02-video-qa-design.md`

## Global Constraints

- **SDK 版本下限**：`google-genai>=2.20.0`。`media_processing` 欄位自 2.20.0 起才存在（逐版驗證：2.19.0 無、2.20.0 有）。`requirements-lock.txt` 鎖 `2.21.0`。
- **影片呼叫必須同時滿足四項**，缺一則靜默降級或成本暴增，且**都不會報錯**：
  - `http_options=HttpOptions(api_version="v1beta1")`（`v1` 不支援 agentic）
  - `media_processing="AGENTIC"`
  - 模型為 `gemini-3.7-flash` / `gemini-3.6-flash` / `gemini-3.5-flash-lite` 之一
  - `thinking_config=types.ThinkingConfig(thinking_level="LOW")`（漏設成本變 5.5 倍）
- **影片模型固定 `gemini-3.5-flash-lite`**。`gemini-3.7-flash` 在 agentic 影片會忽略 `thinking_level`，10 分鐘影片成本是前者的 60 倍，且易觸發 429。
- **禁止使用 preview／實驗模型**，例外僅兩處：`services/voice_live.py`（Live API 僅支援 `gemini-3.1-flash-live-preview`）與 `tools/tts_tool.py`（TTS 獨立家族）。
- **模型定價**（USD / 1M tokens，用於 `usage_meter`）：`gemini-3.5-flash-lite` = in $0.30 / out $2.50；`gemini-3.7-flash` = in $0.75 / out $3.75。thinking token 計入 output。
- **測試門檻**：全套 `pytest -q` 必須通過，基準為 `196 passed / 2 skipped`（PR #17 後）。不得有回歸。
- **測試不得打網路**：一律 mock genai client 後斷言呼叫參數。
- **git**：每個 Task 結束時 commit。不得加入任何 AI/Claude 署名。

---

## File Structure

| 檔案 | 責任 | 動作 |
|---|---|---|
| `requirements.txt` / `requirements-lock.txt` | 相依版本 | 修改（Task 1） |
| `config/agent_config.py` | **所有模型 ID 的唯一來源** | 修改（Task 2） |
| `tests/test_model_config.py` | 守住模型選用規則 | 新增（Task 2） |
| `tools/*.py`、`loader/*.py`、`services/batch_service.py` | 改讀 config，不再寫死模型 | 修改（Task 3） |
| `tools/youtube_tool.py` | 唯一與 Gemini 影片 API 溝通處 | 修改（Task 4） |
| `tests/test_youtube_agentic.py` | 守住四項影片參數 | 新增（Task 4） |
| `services/usage_meter.py` | 記錄 token／成本、配額接縫 | 新增（Task 5） |
| `tests/test_usage_meter.py` | — | 新增（Task 5） |
| `services/video_qa.py` | 記住「使用者 → 影片」 | 新增（Task 6） |
| `tests/test_video_qa_session.py` | — | 新增（Task 6） |
| `main.py` | webhook 接點（僅 2 處） | 修改（Task 7） |
| `tests/test_video_qa_flow.py` | 模式狀態機與判斷順序 | 新增（Task 7） |
| `docs/01_plan/project-roadmap.md`、`README.md` | 文件 | 修改（Task 8） |

---

## Task 1: 升級 google-genai 至 2.21.0

風險最高的一步，且與 agentic 無關。跳 14 個 minor 版本，`services/voice_live.py`（Live API，零測試覆蓋）最可能受影響。**必須先獨立完成並驗證。**

**Files:**
- Modify: `requirements.txt:2`
- Modify: `requirements-lock.txt:7`
- Test: `tests/test_sdk_version.py`（新增）

**Interfaces:**
- Consumes: 無
- Produces: `google.genai.types.Part` 具備 `media_processing` 欄位；`types.MediaProcessing` enum（`STATIC` / `AGENTIC`）；`types.ThinkingConfig(thinking_level=...)`。後續所有 Task 依賴這些。

- [ ] **Step 1: 寫下失敗的測試**

建立 `tests/test_sdk_version.py`：

```python
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
    """thinking_level 是控制影片成本的關鍵參數（漏設成本變 5.5 倍）。"""
    assert "thinking_level" in types.ThinkingConfig.model_fields
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_sdk_version.py -v`
Expected: FAIL — `AssertionError: google-genai 版本過舊：Part 沒有 media_processing 欄位`（目前環境為 1.75.0）

- [ ] **Step 3: 升級相依版本**

`requirements.txt` 第 2 行：

```
google-genai>=2.20.0
```

`requirements-lock.txt` 第 7 行：

```
google-genai==2.21.0
```

- [ ] **Step 4: 安裝並執行測試，確認通過**

```bash
pip install -r requirements-lock.txt
python3 -m pytest tests/test_sdk_version.py -v
```

Expected: 3 passed

- [ ] **Step 5: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `199 passed, 2 skipped`（196 + 本 Task 新增 3）

若有任何測試失敗，**先修好再繼續**，不要帶著紅燈進 Task 2。

- [ ] **Step 6: 人工驗證三個高風險模組**

這三個模組零測試或測試不足，SDK 升版最可能咬到它們。逐一確認 import 與物件建構沒有壞：

```bash
GOOGLE_CLOUD_PROJECT=line-vertex GOOGLE_CLOUD_LOCATION=global python3 - <<'PY'
# Live API：介面在這些版本間最易變動
from services.voice_live import VOICE_MODEL
import services.voice_live as vl
print("voice_live import OK, model =", VOICE_MODEL)

# TTS
from tools.tts_tool import TTS_MODEL
print("tts_tool import OK, model =", TTS_MODEL)

# Batch
import services.batch_service as bs
print("batch_service import OK")

# 實際打一次 Vertex，確認 client 建構與呼叫路徑正常
from google import genai
from google.genai import types
c = genai.Client(vertexai=True, project="line-vertex", location="global",
                 http_options=types.HttpOptions(api_version="v1"))
r = c.models.generate_content(model="gemini-3.1-flash-lite", contents="回答一個字：好")
print("vertex call OK:", (r.text or "").strip())
PY
```

Expected: 四行皆印出、無例外。

- [ ] **Step 7: Commit**

```bash
git add requirements.txt requirements-lock.txt tests/test_sdk_version.py
git commit -m "chore: upgrade google-genai to 2.21.0 for agentic video support

media_processing 欄位自 2.20.0 起才有（逐版驗證：2.19.0 無、2.20.0 有），
影片問答需要它。跳 14 個 minor 版本，已驗證 voice_live / tts_tool /
batch_service 三個高風險模組與實際 Vertex 呼叫路徑皆正常。

新增 tests/test_sdk_version.py 擋住降版——版本掉回舊版時 media_processing
會被靜默丟棄，功能不報錯但完全不走 agentic。"
```

---

## Task 2: 建立模型設定的單一來源

**Files:**
- Modify: `config/agent_config.py:18-23`（dataclass 預設值）、`config/agent_config.py:54-62`（env 讀取）
- Test: `tests/test_model_config.py`（新增）

**Interfaces:**
- Consumes: 無
- Produces:
  - `config.agent_config.AgentConfig` 新增欄位 `video_model: str`
  - `AgentConfig` 既有欄位 `chat_model` / `fast_model` / `orchestrator_model` 的新預設值
  - 模組層級常數 `EXEMPT_PREVIEW_FILES: set[str]`（守衛測試用）
  - Task 3 的所有呼叫點都會 import `get_agent_config()` 取用這些欄位

- [ ] **Step 1: 寫下失敗的測試**

建立 `tests/test_model_config.py`：

```python
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
        if rel.startswith(("tests/", "docs/")) or "__pycache__" in rel:
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
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_model_config.py -v`
Expected: FAIL — `AttributeError: 'AgentConfig' object has no attribute 'video_model'`，且 `test_no_hardcoded_model_ids_outside_config` 列出 24 處硬寫位置

- [ ] **Step 3: 修改 `config/agent_config.py`**

dataclass 預設值（第 18-23 行區塊）改為：

```python
    # Model settings
    # 分級原則：維持既有能力層級，只做現代化。
    # 禁止 preview／實驗模型——會無預警下架（見 gemini-3-pro-preview 404）。
    # 例外僅 services/voice_live.py 與 tools/tts_tool.py，見 tests/test_model_config.py。
    chat_model: str = "gemini-3.5-flash-lite"
    orchestrator_model: str = "gemini-3.7-flash"
    fast_model: str = "gemini-3.5-flash-lite"
    # 影片必須用 3.5-flash-lite：3.7-flash 在 agentic 會忽略 thinking_level，
    # 10 分鐘影片成本是前者的 60 倍，且易觸發 429。
    video_model: str = "gemini-3.5-flash-lite"
```

env 讀取（第 54-62 行區塊）改為：

```python
        chat_model=os.getenv('CHAT_MODEL', 'gemini-3.5-flash-lite'),
        orchestrator_model=os.getenv('ORCHESTRATOR_MODEL', 'gemini-3.7-flash'),
        fast_model=os.getenv('FAST_MODEL', 'gemini-3.5-flash-lite'),
        video_model=os.getenv('VIDEO_MODEL', 'gemini-3.5-flash-lite'),
```

- [ ] **Step 4: 執行測試，確認只剩硬寫那一項失敗**

Run: `python3 -m pytest tests/test_model_config.py -v`
Expected: 除 `test_no_hardcoded_model_ids_outside_config` 外全部 PASS。該項仍失敗是預期的——Task 3 才會把呼叫點遷移過來。

- [ ] **Step 5: 暫時標記硬寫測試為 xfail**

在 `test_no_hardcoded_model_ids_outside_config` 上方加：

```python
@pytest.mark.xfail(reason="呼叫點遷移在 Task 3 完成", strict=True)
```

Run: `python3 -m pytest tests/test_model_config.py -q`
Expected: `12 passed, 1 xfailed`

- [ ] **Step 6: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `211 passed, 1 xfailed, 2 skipped`

- [ ] **Step 7: Commit**

```bash
git add config/agent_config.py tests/test_model_config.py
git commit -m "refactor: make agent_config the single source of truth for model IDs

新增 video_model 欄位與 VIDEO_MODEL 環境變數，並依用途分級調整預設值：
orchestrator 由 gemini-2.5-pro 升為 gemini-3.7-flash，chat/fast 由
gemini-3.1-flash-lite 升為 gemini-3.5-flash-lite。

tests/test_model_config.py 守三件事：模型 ID 不得散落在 config 之外、
不得使用 preview 模型、影片模型必須支援 agentic。硬寫守衛先標 xfail，
呼叫點遷移在下一個 commit。"
```

---

## Task 3: 遷移 27 處呼叫點改讀 config

**Files:**
- Modify: `loader/langtools.py:161,206,491,550,634,686`
- Modify: `tools/maps_tool.py:109,144,247,314,379`
- Modify: `tools/summarizer.py:159,227,322`
- Modify: `loader/searchtool.py:67`、`loader/gh_tools.py:154`、`loader/maps_grounding.py:88`、`loader/youtube_gcp.py:162`、`tools/audio_tool.py:14`、`services/batch_service.py:229`
- Modify: `tools/youtube_tool.py:204`（改讀 `video_model`；agentic 參數在 Task 4）
- Test: `tests/test_model_config.py`（移除 xfail）

**Interfaces:**
- Consumes: Task 2 的 `get_agent_config()` 與其 `chat_model` / `fast_model` / `orchestrator_model` / `video_model` 欄位
- Produces: 全 repo 除兩個例外檔外，不再有 `"gemini-*"` 字面值

- [ ] **Step 1: 移除 xfail，讓測試轉紅**

刪掉 Task 2 Step 5 加上的 `@pytest.mark.xfail(...)` 那一行。

Run: `python3 -m pytest tests/test_model_config.py::test_no_hardcoded_model_ids_outside_config -v`
Expected: FAIL，並列出所有仍硬寫的位置

- [ ] **Step 2: 逐檔遷移**

每個檔案加入 import（若尚未有）：

```python
from config.agent_config import get_agent_config
```

然後把模型字面值換成對應的 config 欄位。**分級對照**：

| 檔案與行號 | 原值 | 改為 |
|---|---|---|
| `loader/langtools.py:161,206,491,550,634,686` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `tools/maps_tool.py:109,144,247,314,379` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `tools/summarizer.py:159,322` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `tools/summarizer.py:227` | `"gemini-3-flash-preview"` | `get_agent_config().orchestrator_model` |
| `loader/searchtool.py:67` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `loader/gh_tools.py:154` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `loader/maps_grounding.py:88` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `loader/youtube_gcp.py:162` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `services/batch_service.py:229` | `"gemini-3.1-flash-lite"` | `get_agent_config().fast_model` |
| `tools/youtube_tool.py:204` | `"gemini-3.1-flash-lite"` | `get_agent_config().video_model` |

`tools/audio_tool.py:14` 是模組層級常數，改為在函式內取值以免 import 時就固定：

```python
# 原本：TRANSCRIPTION_MODEL = "gemini-3.1-flash-lite"
# 刪除該常數，改在 transcribe_audio() 內取用：
from config.agent_config import get_agent_config
...
    model = get_agent_config().fast_model
```

`tools/summarizer.py:227` 註解同步更新——原本寫 "Agentic Vision (gemini-3-flash-preview)"，`agents/orchestrator.py:494` 與 `agents/vision_agent.py:131` 的 docstring 也有同樣字串，一併改為不提及具體模型：

```python
        Process an image using Agentic Vision (see config.agent_config.orchestrator_model)
```

- [ ] **Step 3: 執行守衛測試，確認轉綠**

Run: `python3 -m pytest tests/test_model_config.py -v`
Expected: 13 passed（xfail 已移除）

若仍列出殘留位置，照 Step 2 表格補上——測試訊息會直接指出檔名與行號。

- [ ] **Step 4: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `212 passed, 2 skipped`

- [ ] **Step 5: 人工冒煙測試三條主要路徑**

模型換了 27 處，單元測試都是 mock，必須實際打一次確認新模型在真實路徑上可用：

```bash
GOOGLE_CLOUD_PROJECT=line-vertex GOOGLE_CLOUD_LOCATION=global python3 - <<'PY'
from loader.langtools import summarize_text
print("summarize:", summarize_text("Google 發表了新的 AI 模型，強調效率與成本。")[:60])

from loader.searchtool import *  # noqa
from config.agent_config import get_agent_config
cfg = get_agent_config()
print("models:", cfg.chat_model, cfg.fast_model, cfg.orchestrator_model, cfg.video_model)

from tools.summarizer import analyze_image_agentic
print("agentic vision model wired OK")
PY
```

Expected: 摘要有輸出、四個模型名稱正確印出、無例外。

- [ ] **Step 6: Commit**

```bash
git add loader/ tools/ services/batch_service.py agents/ tests/test_model_config.py
git commit -m "refactor: read model IDs from agent_config across all call sites

27 處硬寫的模型字面值改讀 config/agent_config.py，完成分級升級：
- Tier 1 (gemini-3.7-flash)：orchestrator、agentic vision
- Tier 2 (gemini-3.5-flash-lite)：langtools 6 處、maps_tool 5 處、
  summarizer 2 處、searchtool、gh_tools、maps_grounding、youtube_gcp、
  audio_tool、batch_service
- Tier 3 (video_model)：youtube_tool

voice_live 與 tts_tool 不動——Live API 與 TTS 各自只支援專用的 preview 模型。

之後換模型只需改環境變數。test_no_hardcoded_model_ids_outside_config
防止它再度散開。"
```

---

## Task 4: youtube_tool 改用 agentic 並開放問答

**Files:**
- Modify: `tools/youtube_tool.py`（全檔重構呼叫路徑，保留既有 prompts）
- Test: `tests/test_youtube_agentic.py`（新增）

**Interfaces:**
- Consumes: Task 2/3 的 `get_agent_config().video_model`
- Produces:
  - `tools.youtube_tool._generate_video(youtube_url: str, prompt: str, *, thinking_level: str) -> dict`
    回傳 `{"status": "success"|"error", "text": str, "usage": dict, "error_message": str}`
  - `tools.youtube_tool.summarize_youtube_video(youtube_url: str, mode: str = "normal") -> dict`
    回傳新增 `usage` 鍵，其餘鍵（`status` / `summary` / `mode` / `error_message`）不變
  - `tools.youtube_tool.ask_youtube_video(youtube_url: str, question: str) -> dict`
    回傳 `{"status", "answer", "usage", "error_message"}`
  - `usage` dict 形狀：`{"model": str, "prompt_tokens": int, "output_tokens": int, "thinking_tokens": int, "tool_use_tokens": int, "total_tokens": int}`
  - Task 5 的 `usage_meter.record()` 與 Task 7 的 handler 依賴這些

- [ ] **Step 1: 寫下失敗的測試**

建立 `tests/test_youtube_agentic.py`：

```python
"""測試：影片呼叫的四項必要參數

背景：2026-09-02 spike 實測發現，agentic video understanding 有四個參數
缺一不可，而缺任何一個都**不會報錯**——程式照跑、答案照出，只有成本默默改變：

1. api_version="v1beta1"      → v1 不支援 agentic，靜默退回 STATIC
2. media_processing="AGENTIC" → 不設就是 STATIC
3. 模型在支援名單內           → 否則靜默降級為 STATIC
4. thinking_level="LOW"       → 漏設時 thinking token 暴增，成本變 5.5 倍
                                （10 分鐘影片：$0.0946 vs $0.0023）

這種 bug 靠 code review 抓不到，只有帳單會告訴你。所以這四項各有一個測試。

不打網路：mock 掉 genai.Client 後斷言呼叫參數。
"""
from unittest.mock import MagicMock, patch

import pytest

from tools import youtube_tool

VIDEO_URL = "https://www.youtube.com/watch?v=o8NiE3XMPrM"


def _fake_response(text="摘要內容"):
    resp = MagicMock()
    resp.text = text
    usage = MagicMock()
    usage.prompt_token_count = 260
    usage.candidates_token_count = 638
    usage.thoughts_token_count = 0
    usage.tool_use_prompt_token_count = 2163
    usage.total_token_count = 2854
    resp.usage_metadata = usage
    return resp


@pytest.fixture
def captured():
    """攔截 genai.Client 的建構與 generate_content 呼叫參數。"""
    holder = {}

    def fake_client(**client_kwargs):
        holder["client_kwargs"] = client_kwargs
        client = MagicMock()

        def generate_content(**call_kwargs):
            holder["call_kwargs"] = call_kwargs
            return _fake_response()

        client.models.generate_content.side_effect = generate_content
        return client

    with patch.object(youtube_tool.genai, "Client", side_effect=fake_client):
        yield holder


def test_uses_v1beta1_api_version(captured):
    """v1 不支援 agentic，會靜默退回 STATIC。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    http_options = captured["client_kwargs"]["http_options"]
    assert http_options.api_version == "v1beta1"


def test_video_part_sets_agentic_media_processing(captured):
    """不設 media_processing 就是 STATIC，等於這個功能沒開。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    video_part = captured["call_kwargs"]["contents"][0]
    assert str(video_part.media_processing).upper().endswith("AGENTIC")


def test_thinking_level_is_low(captured):
    """漏設 thinking_level，10 分鐘影片成本從 $0.0023 變 $0.0946。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    config = captured["call_kwargs"]["config"]
    assert config.thinking_config is not None, "必須設 thinking_config"
    assert str(config.thinking_config.thinking_level).upper().endswith("LOW")


def test_model_supports_agentic(captured):
    """不在支援名單的模型會靜默降級為 STATIC。"""
    youtube_tool.summarize_youtube_video(VIDEO_URL)
    assert captured["call_kwargs"]["model"] in {
        "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
    }


def test_generate_video_requires_explicit_thinking_level():
    """thinking_level 必須是必填參數——有預設值就會有人漏掉。"""
    with pytest.raises(TypeError):
        youtube_tool._generate_video(VIDEO_URL, "prompt")  # type: ignore[call-arg]


def test_summarize_returns_usage(captured):
    result = youtube_tool.summarize_youtube_video(VIDEO_URL)
    assert result["status"] == "success"
    assert result["usage"]["tool_use_tokens"] == 2163
    assert result["usage"]["total_tokens"] == 2854
    assert result["usage"]["model"] in {"gemini-3.5-flash-lite"}


def test_ask_youtube_video_returns_answer(captured):
    result = youtube_tool.ask_youtube_video(VIDEO_URL, "他有講到定價嗎？")
    assert result["status"] == "success"
    assert result["answer"] == "摘要內容"
    assert "usage" in result


def test_ask_rejects_non_youtube_url():
    result = youtube_tool.ask_youtube_video("https://example.com", "問題")
    assert result["status"] == "error"


def test_ask_includes_question_in_prompt(captured):
    youtube_tool.ask_youtube_video(VIDEO_URL, "XR 眼鏡那段在哪？")
    prompt = captured["call_kwargs"]["contents"][1]
    assert "XR 眼鏡那段在哪？" in prompt
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_youtube_agentic.py -v`
Expected: FAIL — `AttributeError: module 'tools.youtube_tool' has no attribute '_generate_video'`

- [ ] **Step 3: 重構 `tools/youtube_tool.py`**

保留檔頭既有的 `YOUTUBE_PROMPTS` 與 `_is_youtube_url()` 不動。新增問答用的 prompt：

```python
ASK_PROMPT_TEMPLATE = """請用台灣用語的繁體中文回答關於這部影片的問題。

【問題】
{question}

【輸出格式要求】
1. 不要使用任何 Markdown 語法（如 #, *, **, -, 等）
2. 使用純文字格式，適合直接發送到 LINE Bot
3. 若答案出現在影片的特定時間點，務必附上時間戳，格式為 MM:SS 或 H:MM:SS
4. 影片中若沒有相關內容，直接說「影片中沒有提到這個」，不要編造

【注意事項】
- 回答簡潔，控制在 300 字以內
- 有多個相關段落時，依時間順序條列
"""
```

把 `summarize_youtube_video()` 內部整段呼叫邏輯抽成 `_generate_video()`：

```python
def _extract_usage(response, model: str) -> dict:
    """把 usage_metadata 攤平成純 dict，呼叫端不必碰 SDK 型別。"""
    u = getattr(response, "usage_metadata", None)
    if u is None:
        return {"model": model, "prompt_tokens": 0, "output_tokens": 0,
                "thinking_tokens": 0, "tool_use_tokens": 0, "total_tokens": 0}
    return {
        "model": model,
        "prompt_tokens": getattr(u, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(u, "candidates_token_count", 0) or 0,
        "thinking_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        "tool_use_tokens": getattr(u, "tool_use_prompt_token_count", 0) or 0,
        "total_tokens": getattr(u, "total_token_count", 0) or 0,
    }


def _generate_video(youtube_url: str, prompt: str, *, thinking_level: str) -> dict:
    """對 YouTube 影片跑一次 agentic 查詢。

    thinking_level 刻意設為必填且無預設值：2026-09-02 spike 實測，
    漏設時 10 分鐘影片成本從 $0.0023 變成 $0.0946（5.5 倍），
    而且不會報錯、不會有任何徵兆。給它預設值就是給人漏掉的機會。
    """
    if not youtube_url:
        return {"status": "error", "error_message": "No YouTube URL provided"}
    if not _is_youtube_url(youtube_url):
        return {"status": "error", "error_message": f"Invalid YouTube URL: {youtube_url}"}
    if not GENAI_AVAILABLE:
        return {"status": "error", "error_message": "google-genai package not available"}
    if not VERTEX_PROJECT:
        return {"status": "error", "error_message": "GOOGLE_CLOUD_PROJECT not configured"}

    model = get_agent_config().video_model
    max_retries = 2
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            client = genai.Client(
                vertexai=True,
                project=VERTEX_PROJECT,
                location=VERTEX_LOCATION,
                # agentic video understanding 只在 v1beta1 提供；v1 會靜默退回 STATIC
                http_options=HttpOptions(api_version="v1beta1"),
            )
            contents = [
                Part(
                    file_data=FileData(file_uri=youtube_url, mime_type="video/mp4"),
                    media_processing="AGENTIC",
                ),
                prompt,
            ]
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=GenerateContentConfig(
                    labels={"client_id": "info_helper"},
                    thinking_config=ThinkingConfig(thinking_level=thinking_level),
                ),
            )
            if not response.text:
                return {"status": "error", "error_message": "No content generated"}
            return {
                "status": "success",
                "text": response.text,
                "usage": _extract_usage(response, model),
            }

        except ClientError as e:
            if e.code == 429 and attempt < max_retries - 1:
                logger.warning(
                    f"Rate limit hit (429), retrying in {retry_delay}s... "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            if e.code == 429:
                return {"status": "error", "error_message": (
                    "Vertex AI 使用量已達上限，請稍後再試。建議等待 1-2 分鐘後重試。")}
            logger.error(f"Vertex AI API error: {e}", exc_info=True)
            return {"status": "error",
                    "error_message": f"Vertex AI 錯誤 ({e.code}): {str(e)[:100]}"}

        except Exception as e:
            logger.error(f"Error processing video: {e}", exc_info=True)
            return {"status": "error",
                    "error_message": f"處理影片時發生錯誤: {str(e)[:100]}"}

    return {"status": "error", "error_message": "處理影片時發生未預期的錯誤"}
```

兩個公開函式改為薄包裝：

```python
def summarize_youtube_video(
    youtube_url: str,
    mode: Literal["normal", "detail", "twitter"] = "normal"
) -> dict:
    """既有介面，回傳鍵不變（新增 usage）。"""
    prompt = YOUTUBE_PROMPTS.get(mode, YOUTUBE_PROMPTS["normal"])
    logger.info(f"Summarizing YouTube video: {youtube_url} (mode: {mode})")
    result = _generate_video(youtube_url, prompt, thinking_level="LOW")
    if result["status"] != "success":
        return {"status": "error", "error_message": result["error_message"], "mode": mode}
    return {
        "status": "success",
        "summary": result["text"],
        "mode": mode,
        "usage": result["usage"],
    }


def ask_youtube_video(youtube_url: str, question: str) -> dict:
    """回答關於影片的單一問題。

    刻意不帶對話歷史：Vertex AI 上無法保留影片 context
    （見 spec Spike 結論一），傳回歷史只會 400 或被完整重跑。
    """
    logger.info(f"Asking about YouTube video: {youtube_url}")
    prompt = ASK_PROMPT_TEMPLATE.format(question=question)
    result = _generate_video(youtube_url, prompt, thinking_level="LOW")
    if result["status"] != "success":
        return {"status": "error", "error_message": result["error_message"]}
    return {"status": "success", "answer": result["text"], "usage": result["usage"]}
```

檔頭的 import 補上新用到的型別與設定：

```python
from google.genai.types import (
    HttpOptions, Part, FileData, GenerateContentConfig, ThinkingConfig,
)
from config.agent_config import get_agent_config
```

- [ ] **Step 4: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_youtube_agentic.py -v`
Expected: 9 passed

- [ ] **Step 5: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `221 passed, 2 skipped`

- [ ] **Step 6: 人工驗證真實影片並記錄成本**

單元測試全是 mock，證明不了 agentic 真的生效。實際跑一次並確認 `tool_use_tokens > 0`（那是 agentic 有在動態載入影片的證據）：

```bash
GOOGLE_CLOUD_PROJECT=line-vertex GOOGLE_CLOUD_LOCATION=global python3 - <<'PY'
from tools.youtube_tool import summarize_youtube_video, ask_youtube_video
SHORT = "https://www.youtube.com/watch?v=LxvErFkBXPk"

r = summarize_youtube_video(SHORT)
u = r["usage"]
print("summary:", r["summary"][:80])
print("usage:", u)
assert u["tool_use_tokens"] > 0, "tool_use_tokens 為 0 → agentic 沒有生效！"
assert u["thinking_tokens"] < 5000, f"thinking 過高（{u['thinking_tokens']}）→ thinking_level 沒生效"

a = ask_youtube_video(SHORT, "他有提到 Gemini 嗎？在幾分幾秒？")
print("answer:", a["answer"][:150])
print("usage:", a["usage"])
PY
```

Expected: 兩個 assert 都通過、答案帶時間戳。10 分鐘影片的 `total_tokens` 應在 3,000 上下；若看到 3 萬以上，代表 `thinking_level` 沒有生效，**停下來查清楚再繼續**。

- [ ] **Step 7: Commit**

```bash
git add tools/youtube_tool.py tests/test_youtube_agentic.py
git commit -m "feat: use agentic video understanding and add video Q&A tool

summarize_youtube_video 改走 agentic（v1beta1 + media_processing=AGENTIC +
thinking_level=LOW），並新增 ask_youtube_video 支援針對影片提問、回傳時間戳。

呼叫邏輯收斂到 _generate_video 一處，thinking_level 設為必填無預設值——
spike 實測漏設它 10 分鐘影片成本從 \$0.0023 變 \$0.0946，且完全不會報錯。

tests/test_youtube_agentic.py 對四項必要參數各有一個測試，因為缺任何一項
都是靜默失敗，只有帳單會反映。"
```

---

## Task 5: usage_meter 記錄 token 與成本

同時完成 roadmap P1-4「用量與成本觀測」。

**Files:**
- Create: `services/usage_meter.py`
- Test: `tests/test_usage_meter.py`

**Interfaces:**
- Consumes: `services.firestore_store.FirestoreKVStore`；Task 4 的 `usage` dict 形狀
- Produces:
  - `services.usage_meter.UsageMeter(store=None)`
  - `UsageMeter.estimate_cost(usage: dict) -> float`
  - `UsageMeter.record(user_id: str, feature: str, usage: dict) -> float`（回傳本次花費）
  - `UsageMeter.spent_today(user_id: str) -> float`
  - `UsageMeter.check_budget(user_id: str) -> tuple[bool, float | None]`
  - `services.usage_meter.get_usage_meter() -> UsageMeter`（單例）
  - Task 7 的 handler 依賴 `record()` 與 `check_budget()`

- [ ] **Step 1: 寫下失敗的測試**

建立 `tests/test_usage_meter.py`：

```python
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
    assert meter.spent_today(USER) == pytest.approx(2 * meter.estimate_cost(USAGE_SHORT))


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
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_usage_meter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.usage_meter'`

- [ ] **Step 3: 建立 `services/usage_meter.py`**

```python
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

from services.firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

USAGE_COLLECTION = "usage_records"

# USD per 1M tokens。thinking token 計入 output。
# 價目更新時一併更新 tests/test_usage_meter.py 的對照數字。
MODEL_PRICING = {
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
}


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
```

- [ ] **Step 4: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_usage_meter.py -v`
Expected: 12 passed

- [ ] **Step 5: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `233 passed, 2 skipped`

- [ ] **Step 6: Commit**

```bash
git add services/usage_meter.py tests/test_usage_meter.py
git commit -m "feat: record per-user token usage and cost (roadmap P1-4)

每次 Gemini 呼叫的 token 與換算成本按「使用者 + 日期」累加進 Firestore。
配額以實際花費計而非影片長度——長度與花費非線性（10 分鐘 \$0.0023、
2 小時 \$0.91），且用長度得另接 YouTube Data API。

本階段只做記錄不做強制：未設 VIDEO_QA_DAILY_BUDGET_USD 即不限制，
接縫先放好。記帳失敗一律安靜降級，不影響主流程。"
```

---

## Task 6: video_qa 記住使用者正在問哪支影片

**Files:**
- Create: `services/video_qa.py`
- Test: `tests/test_video_qa_session.py`

**Interfaces:**
- Consumes: `services.firestore_store.FirestoreKVStore`
- Produces:
  - `services.video_qa.VideoQASessions(store=None, ttl_seconds=1800)`
  - `VideoQASessions.enter(user_id: str, video_url: str) -> None`
  - `VideoQASessions.get(user_id: str) -> Optional[dict]`（`{"url", "entered_at", "asked"}`，過期回 None）
  - `VideoQASessions.bump(user_id: str) -> None`（提問次數 +1 並續期）
  - `VideoQASessions.exit(user_id: str) -> bool`
  - `services.video_qa.should_exit_video_mode(message_text: str) -> bool`
  - `services.video_qa.get_video_qa_sessions() -> VideoQASessions`（單例）
  - Task 7 的 handler 依賴以上全部

- [ ] **Step 1: 寫下失敗的測試**

建立 `tests/test_video_qa_session.py`：

```python
"""測試：影片問答模式的狀態

背景：spec 原本規劃包一層 services/session_manager.py，實作前檢視其內部後改為
直接用 FirestoreKVStore——SessionManager 是繞著「一個 Gemini chat 物件 +
會裁切的對話歷史」設計的，有兩個會實際出錯的摩擦點：
_persist_session() 不持久化 metadata（網址重啟後消失）、
add_to_history() 會裁掉舊訊息（網址放 history[0] 會在第 N 次提問後被裁掉）。

脫離條件刻意用啟發式而非 LLM 判斷意圖：後者要多打一次 Gemini，
而誤判代價很低（使用者再問一次即可）。
"""
import time

import pytest

from services.video_qa import VideoQASessions, should_exit_video_mode
from tests.fakes import FakeStore, UnavailableStore

USER = "U-test-user"
VIDEO = "https://www.youtube.com/watch?v=o8NiE3XMPrM"


# --- session 生命週期 ---

def test_enter_then_get_returns_video_url():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    assert s.get(USER)["url"] == VIDEO


def test_get_returns_none_when_not_in_mode():
    assert VideoQASessions(store=FakeStore()).get(USER) is None


def test_exit_clears_session():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    assert s.exit(USER) is True
    assert s.get(USER) is None


def test_exit_when_not_in_mode_returns_false():
    assert VideoQASessions(store=FakeStore()).exit(USER) is False


def test_session_expires_after_ttl():
    s = VideoQASessions(store=FakeStore(), ttl_seconds=0)
    s.enter(USER, VIDEO)
    time.sleep(0.01)
    assert s.get(USER) is None


def test_session_is_per_user():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    assert s.get("U-someone-else") is None


def test_video_url_survives_restart():
    """網址必須撐過 instance 重啟——這正是不用 SessionManager 的原因之一。"""
    store = FakeStore()
    VideoQASessions(store=store).enter(USER, VIDEO)
    assert VideoQASessions(store=store).get(USER)["url"] == VIDEO


def test_bump_increments_ask_count_and_renews_ttl():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    s.bump(USER)
    s.bump(USER)
    assert s.get(USER)["asked"] == 2


def test_entering_a_new_video_replaces_the_old_one():
    s = VideoQASessions(store=FakeStore())
    s.enter(USER, VIDEO)
    s.bump(USER)
    other = "https://www.youtube.com/watch?v=LxvErFkBXPk"
    s.enter(USER, other)
    assert s.get(USER)["url"] == other
    assert s.get(USER)["asked"] == 0


def test_store_unavailable_degrades_to_not_in_mode():
    """Firestore 掛掉時退化成「不在影片模式」，訊息照原路走，不會壞掉。"""
    s = VideoQASessions(store=UnavailableStore())
    s.enter(USER, VIDEO)
    assert s.get(USER) is None


# --- 脫離判斷（啟發式） ---

@pytest.mark.parametrize("text", [
    "https://example.com/article",
    "看看這個 https://www.youtube.com/watch?v=abc",
    "/list",
    "/save",
])
def test_messages_that_exit_video_mode(text):
    assert should_exit_video_mode(text) is True


@pytest.mark.parametrize("text", [
    "他有講到定價嗎？",
    "XR 眼鏡那段在哪裡？",
    "第三點再說詳細一點",
    "1:24:40 那邊在講什麼",
])
def test_messages_that_stay_in_video_mode(text):
    assert should_exit_video_mode(text) is False


def test_empty_message_stays_in_mode():
    assert should_exit_video_mode("") is False
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_video_qa_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.video_qa'`

- [ ] **Step 3: 建立 `services/video_qa.py`**

```python
"""影片問答模式的狀態

只記「這個使用者現在在問哪支影片」。因為 Vertex AI 上無法保留影片 context
（見 docs/superpowers/specs/2026-09-02-video-qa-design.md Spike 結論一），
每次提問都是獨立的重新查詢，所以這裡不存任何對話歷史——存了也沒用。

直接用 FirestoreKVStore 而非 SessionManager：後者繞著「Gemini chat 物件 +
會裁切的歷史」設計，metadata 不持久化、history 會被裁掉，兩者都會讓影片網址
在使用中消失。
"""
import logging
import re
import time
from typing import Optional

from services.firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

VIDEO_QA_COLLECTION = "video_qa_sessions"
DEFAULT_TTL_SECONDS = 30 * 60   # 與聊天 session 一致

_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


def should_exit_video_mode(message_text: str) -> bool:
    """判斷這則訊息代表使用者想離開影片模式。

    刻意用啟發式而不是 LLM 判斷意圖：後者每則訊息都要多打一次 Gemini，
    而誤判的代價很低（使用者再問一次就好），不值得那個成本與延遲。

    涵蓋「換主題」的實際訊號：貼了新網址、打了指令。
    非文字訊息（圖片／語音／位置）由呼叫端處理，不走這個函式。
    """
    if not message_text:
        return False
    text = message_text.strip()
    if text.startswith("/"):
        return True
    return bool(_URL_PATTERN.search(text))


class VideoQASessions:
    def __init__(self, store=None, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._store = store if store is not None else FirestoreKVStore(VIDEO_QA_COLLECTION)
        self._ttl = ttl_seconds

    @property
    def available(self) -> bool:
        try:
            return bool(self._store.is_available)
        except Exception:
            return False

    def enter(self, user_id: str, video_url: str) -> None:
        """進入影片模式。重複進入會換成新影片並把提問次數歸零。"""
        if not self.available:
            return
        try:
            self._store.save(user_id, {
                "url": video_url,
                "entered_at": time.time(),
                "last_active": time.time(),
                "asked": 0,
            })
            logger.info("video_qa: user %s entered mode for %s", user_id, video_url)
        except Exception as e:
            logger.warning("Failed to enter video mode (degrading silently): %s", e)

    def get(self, user_id: str) -> Optional[dict]:
        """回傳目前的影片 session；不在模式中或已過期回 None。"""
        if not self.available:
            return None
        try:
            doc = self._store.load(user_id)
        except Exception as e:
            logger.warning("Failed to read video session (degrading silently): %s", e)
            return None
        if not doc:
            return None
        if time.time() - doc.get("last_active", 0) >= self._ttl:
            self.exit(user_id)
            return None
        return doc

    def bump(self, user_id: str) -> None:
        """提問次數 +1 並續期。"""
        doc = self.get(user_id)
        if doc is None:
            return
        try:
            doc["asked"] = doc.get("asked", 0) + 1
            doc["last_active"] = time.time()
            self._store.save(user_id, doc)
        except Exception as e:
            logger.warning("Failed to bump video session (degrading silently): %s", e)

    def exit(self, user_id: str) -> bool:
        """離開影片模式。回傳是否原本在模式中。"""
        if not self.available:
            return False
        try:
            existed = self._store.load(user_id) is not None
            self._store.delete(user_id)
            if existed:
                logger.info("video_qa: user %s exited mode", user_id)
            return existed
        except Exception as e:
            logger.warning("Failed to exit video mode (degrading silently): %s", e)
            return False


_sessions: Optional[VideoQASessions] = None


def get_video_qa_sessions() -> VideoQASessions:
    global _sessions
    if _sessions is None:
        _sessions = VideoQASessions()
    return _sessions
```

- [ ] **Step 4: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_video_qa_session.py -v`
Expected: 19 passed

- [ ] **Step 5: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `252 passed, 2 skipped`

- [ ] **Step 6: Commit**

```bash
git add services/video_qa.py tests/test_video_qa_session.py
git commit -m "feat: track which video each user is asking about

只記「使用者 → 影片」的對應，不存對話歷史——Vertex AI 上無法保留影片
context，存了也沒用（見 spec Spike 結論一）。

改用 FirestoreKVStore 而非原設計的 SessionManager：後者的
_persist_session() 不持久化 metadata、add_to_history() 會裁掉舊訊息，
兩者都會讓影片網址在使用中消失。spec 已同步更新。

脫離判斷用啟發式（網址／斜線指令）而非 LLM 判斷意圖——後者每則訊息
都要多打一次 Gemini，而誤判代價很低。"
```

---

## Task 7: main.py 接上影片問答

**Files:**
- Modify: `main.py`（import 區、`main.py:596` 前插入攔截、`main.py:1442` 附近新增 postback 分支、YouTube 摘要按鈕組加 quick reply）
- Test: `tests/test_video_qa_flow.py`

**Interfaces:**
- Consumes: Task 4 的 `ask_youtube_video()`、Task 5 的 `get_usage_meter()`、Task 6 的 `get_video_qa_sessions()` 與 `should_exit_video_mode()`
- Produces:
  - `main.handle_video_qa_enter_postback(event, data, user_id)`
  - `main.handle_video_qa_exit_postback(event, user_id)`
  - `main.handle_video_qa_message(event, user_id, text) -> bool`（回傳是否已處理；False 代表交還原路）
  - `main.build_video_qa_quick_reply() -> QuickReply`

- [ ] **Step 1: 寫下失敗的測試**

建立 `tests/test_video_qa_flow.py`：

```python
"""測試：影片問答模式的判斷順序與狀態機

背景：影片模式攔截在 main.py 既有的訊息路由之前。攔截錯了會讓一般訊息
被當成影片提問（使用者收到「影片中沒有提到這個」這種莫名其妙的回覆），
或反過來讓影片提問掉回一般路徑。

最重要的一條是判斷順序：**脫離判斷必須在配額判斷之前**。
使用者貼新網址想換主題，不該因為影片配額用完就被擋下來——那是兩件不相干的事。
這是行為契約，不是實作細節。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
from services.video_qa import VideoQASessions
from tests.fakes import FakeStore

USER = "U-test-user"
VIDEO = "https://www.youtube.com/watch?v=o8NiE3XMPrM"


@pytest.fixture
def sessions():
    s = VideoQASessions(store=FakeStore())
    with patch.object(main, "get_video_qa_sessions", return_value=s):
        yield s


@pytest.fixture
def fake_event():
    event = MagicMock()
    event.reply_token = "reply-token"
    return event


@pytest.fixture
def no_network():
    """擋掉所有外呼：LINE、Gemini、用量記錄。"""
    with patch.object(main, "ask_youtube_video") as ask, \
         patch.object(main.LineService, "show_loading_animation", new=AsyncMock()), \
         patch.object(main, "_reply_with_overflow", new=AsyncMock()) as reply:
        ask.return_value = {
            "status": "success",
            "answer": "有的，在 1:24:40 提到定價。",
            "usage": {"model": "gemini-3.5-flash-lite", "prompt_tokens": 53,
                      "output_tokens": 638, "thinking_tokens": 0,
                      "tool_use_tokens": 2163, "total_tokens": 2854},
        }
        yield {"ask": ask, "reply": reply}


# --- 進入模式 ---

@pytest.mark.asyncio
async def test_enter_does_not_call_gemini(sessions, fake_event, no_network):
    """按下按鈕只寫 session，不該花錢。"""
    with patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        await main.handle_video_qa_enter_postback(
            fake_event, {"action": "video_qa", "url": VIDEO}, USER)
    assert sessions.get(USER)["url"] == VIDEO
    no_network["ask"].assert_not_called()


# --- 模式中的訊息路由 ---

@pytest.mark.asyncio
async def test_normal_text_is_handled_as_video_question(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is True
    no_network["ask"].assert_called_once()
    assert no_network["ask"].call_args[0][1] == "他有講到定價嗎？"


@pytest.mark.asyncio
async def test_not_in_mode_returns_false(fake_event, sessions, no_network):
    handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is False
    no_network["ask"].assert_not_called()


@pytest.mark.asyncio
async def test_url_message_exits_mode_and_returns_false(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    handled = await main.handle_video_qa_message(
        fake_event, USER, "https://example.com/article")
    assert handled is False, "貼網址應交還原路處理"
    assert sessions.get(USER) is None, "貼網址應離開影片模式"
    no_network["ask"].assert_not_called()


@pytest.mark.asyncio
async def test_slash_command_exits_mode_and_returns_false(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    handled = await main.handle_video_qa_message(fake_event, USER, "/list")
    assert handled is False
    assert sessions.get(USER) is None


@pytest.mark.asyncio
async def test_asking_bumps_the_counter(sessions, fake_event, no_network):
    sessions.enter(USER, VIDEO)
    await main.handle_video_qa_message(fake_event, USER, "問題一")
    await main.handle_video_qa_message(fake_event, USER, "問題二")
    assert sessions.get(USER)["asked"] == 2


# --- 判斷順序（行為契約） ---

@pytest.mark.asyncio
async def test_exit_check_runs_before_budget_check(sessions, fake_event, no_network,
                                                   monkeypatch):
    """配額用完時，貼新網址仍必須能換主題。

    脫離與配額是兩件不相干的事。順序寫反的話，使用者會卡在一個
    每則訊息都被拒絕、又離不開的模式裡。
    """
    monkeypatch.setenv("VIDEO_QA_DAILY_BUDGET_USD", "0.0001")
    sessions.enter(USER, VIDEO)
    meter = MagicMock()
    meter.check_budget.return_value = (False, 0.0)
    with patch.object(main, "get_usage_meter", return_value=meter):
        handled = await main.handle_video_qa_message(
            fake_event, USER, "https://example.com/other")
    assert handled is False, "貼網址應交還原路，不該被配額擋住"
    assert sessions.get(USER) is None
    meter.check_budget.assert_not_called()


@pytest.mark.asyncio
async def test_over_budget_blocks_and_exits_mode(sessions, fake_event, no_network):
    """配額用完時不打 Gemini，並把使用者踢出模式。

    讓人卡在一個每則訊息都被拒絕的模式裡，比直接踢出去更糟。
    """
    sessions.enter(USER, VIDEO)
    meter = MagicMock()
    meter.check_budget.return_value = (False, 0.0)
    with patch.object(main, "get_usage_meter", return_value=meter), \
         patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        handled = await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    assert handled is True
    no_network["ask"].assert_not_called()
    assert sessions.get(USER) is None


@pytest.mark.asyncio
async def test_usage_is_recorded_after_a_successful_answer(sessions, fake_event,
                                                           no_network):
    sessions.enter(USER, VIDEO)
    meter = MagicMock()
    meter.check_budget.return_value = (True, None)
    with patch.object(main, "get_usage_meter", return_value=meter):
        await main.handle_video_qa_message(fake_event, USER, "他有講到定價嗎？")
    meter.record.assert_called_once()
    assert meter.record.call_args[0][1] == "video_qa"


# --- 離開模式 ---

@pytest.mark.asyncio
async def test_exit_postback_clears_session(sessions, fake_event):
    sessions.enter(USER, VIDEO)
    with patch.object(main.line_bot_api, "reply_message", new=AsyncMock()):
        await main.handle_video_qa_exit_postback(fake_event, USER)
    assert sessions.get(USER) is None
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_video_qa_flow.py -v`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'handle_video_qa_enter_postback'`

- [ ] **Step 3: 在 `main.py` 加入 import**

在既有的 local imports 區（`main.py:34` 附近）加：

```python
from tools.youtube_tool import ask_youtube_video
from services.usage_meter import get_usage_meter
from services.video_qa import get_video_qa_sessions, should_exit_video_mode
```

- [ ] **Step 4: 加入三個 handler 與 quick reply builder**

放在 `handle_youtube_summary_postback`（`main.py:1313`）後面：

```python
def build_video_qa_quick_reply() -> QuickReply:
    """影片問答模式的「結束」按鈕。

    每則答案都掛著它——手動脫離比任何自動判斷都可靠。
    """
    return QuickReply(items=[
        QuickReplyButton(
            action=PostbackAction(
                label="🚪 結束問影片",
                data=json.dumps({"action": "video_qa_exit"}),
                display_text="🚪 結束問影片",
            )
        )
    ])


async def handle_video_qa_enter_postback(event: PostbackEvent, data: dict, user_id: str):
    """進入影片問答模式。刻意不呼叫 Gemini——按個按鈕不該花錢。"""
    url = data.get("url")
    if not url or not user_id:
        logger.error("Missing url or user_id in video_qa postback")
        return

    get_video_qa_sessions().enter(user_id, url)
    await line_bot_api.reply_message(event.reply_token, [TextSendMessage(
        text=("🎬 已進入影片問答模式\n"
              "接下來直接打字問我這部影片的內容就好，例如\n"
              "「他有講到定價嗎？」「XR 眼鏡那段在哪裡？」\n\n"
              "貼新網址或打指令會自動離開。"),
        quick_reply=build_video_qa_quick_reply(),
    )])


async def handle_video_qa_exit_postback(event: PostbackEvent, user_id: str):
    """手動離開影片問答模式。"""
    get_video_qa_sessions().exit(user_id)
    await line_bot_api.reply_message(event.reply_token, [TextSendMessage(
        text="🚪 已結束影片問答。有需要隨時再貼影片連結給我。"
    )])


async def handle_video_qa_message(event: MessageEvent, user_id: str, text: str) -> bool:
    """處理影片模式中的文字訊息。

    回傳 True 表示已處理，False 表示交還給原本的訊息路由。

    判斷順序是刻意的——脫離檢查在配額檢查之前。使用者貼新網址想換主題，
    不該因為影片配額用完就被擋下來，那是兩件不相干的事。
    """
    sessions = get_video_qa_sessions()
    session = sessions.get(user_id)
    if session is None:
        return False

    # 1) 脫離檢查優先
    if should_exit_video_mode(text):
        sessions.exit(user_id)
        return False

    # 2) 配額檢查
    meter = get_usage_meter()
    allowed, remaining = meter.check_budget(user_id)
    if not allowed:
        sessions.exit(user_id)
        await line_bot_api.reply_message(event.reply_token, [TextSendMessage(
            text=(f"📊 今日影片問答用量已達上限（已用 "
                  f"${meter.spent_today(user_id):.2f}）。\n"
                  "明天會重置。影片摘要不受影響，還是可以用。")
        )])
        return True

    # 3) 提問。長片實測 26–53 秒，先開 loading 動畫（不消耗 reply token）
    await LineService.show_loading_animation(user_id)
    result = ask_youtube_video(session["url"], text)

    if result["status"] != "success":
        await line_bot_api.reply_message(event.reply_token, [TextSendMessage(
            text=f"⚠️ {result.get('error_message', '無法回答這個問題')}",
            quick_reply=build_video_qa_quick_reply(),
        )])
        return True

    meter.record(user_id, "video_qa", result["usage"])
    sessions.bump(user_id)

    await _reply_with_overflow(
        event, user_id,
        [TextSendMessage(text=result["answer"],
                         quick_reply=build_video_qa_quick_reply())],
        "video_qa",
    )
    return True
```

- [ ] **Step 5: 接上 postback 路由**

在 `main.py:1442` 的 `action_value` 判斷串中，`youtube_summary` 分支後面加：

```python
        if action_value == "video_qa":
            await handle_video_qa_enter_postback(event, data, user_id)
            return

        if action_value == "video_qa_exit":
            await handle_video_qa_exit_postback(event, user_id)
            return
```

- [ ] **Step 6: 接上訊息攔截**

在 `main.py:596` 的 `isinstance(event.message, TextMessage)` 分支內、既有網址判斷**之前**插入。攔截只針對文字訊息——圖片／語音／位置訊息走各自的分支，並在那裡順手清掉影片模式：

```python
        if isinstance(event.message, TextMessage):
            text = event.message.text

            # 影片問答模式：已處理就結束，未處理（脫離）則交還原路
            if user_id and await handle_video_qa_message(event, user_id, text):
                return

            urls, mode = extract_url_and_mode(text)
            ...  # 既有邏輯不動
```

圖片／語音／位置三個分支各自開頭加一行（非文字訊息代表換主題）：

```python
        elif isinstance(event.message, ImageMessage):
            if user_id:
                get_video_qa_sessions().exit(user_id)
            await handle_image_message(event)
```

`AudioMessage` 與 `LocationMessage` 兩個分支同樣處理。

- [ ] **Step 7: 在 YouTube 摘要按鈕組加入入口**

找到產生 YouTube 摘要 quick reply 的位置（`handle_url_message` 內，`youtube_summary` postback 產生處），在既有按鈕後追加：

```python
                QuickReplyButton(
                    action=PostbackAction(
                        label="🎬 問這部影片",
                        data=json.dumps({"action": "video_qa", "url": url}),
                        display_text="🎬 問這部影片",
                    )
                ),
```

- [ ] **Step 8: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_video_qa_flow.py -v`
Expected: 10 passed

- [ ] **Step 9: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `262 passed, 2 skipped`

特別確認 `tests/test_line_message_overflow.py` 與 `tests/test_webhook_async.py` 沒有因為攔截插入而失敗——那兩支守著 P0 修好的訊息路由。

- [ ] **Step 10: Commit**

```bash
git add main.py tests/test_video_qa_flow.py
git commit -m "feat: add video Q&A mode to the LINE webhook

YouTube 摘要按鈕組新增「🎬 問這部影片」，進入後直接打字即可追問影片內容，
答案帶時間戳。三種脫離方式：手動按鈕、貼網址／打指令自動脫離、30 分鐘逾時。

判斷順序是行為契約：脫離檢查在配額檢查之前。使用者貼新網址想換主題，
不該因影片配額用完被擋——那是兩件不相干的事，且會讓人卡在一個
每則訊息都被拒絕又離不開的模式裡。

長片實測 26–53 秒，先開 loading 動畫（不消耗 reply token），
再走 _reply_with_overflow（reply 成功不動用 push 額度）。"
```

---

## Task 8: 更新文件

**Files:**
- Modify: `docs/01_plan/project-roadmap.md`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: 前面所有 Task 的成果
- Produces: 無程式介面

- [ ] **Step 1: 更新 `.env.example`**

在既有變數後加入：

```bash
# 模型設定（留空則用 config/agent_config.py 的預設值）
# 禁止填 preview／實驗模型——會無預警下架
CHAT_MODEL=
FAST_MODEL=
ORCHESTRATOR_MODEL=
# 影片模型必須支援 agentic：gemini-3.7-flash / 3.6-flash / 3.5-flash-lite
# 建議維持 3.5-flash-lite——3.7-flash 在 agentic 會忽略 thinking_level，成本高 60 倍
VIDEO_MODEL=

# 影片問答每日花費上限（美金）。留空 = 不限制
VIDEO_QA_DAILY_BUDGET_USD=
```

- [ ] **Step 2: 更新 `README.md`**

在 Core Features 清單加入：

```markdown
- **🎬 Video Q&A** - Ask follow-up questions about any YouTube video and get
  answers with precise timestamps (agentic video understanding)
```

在 Environment Variables 的 Optional 區塊加入：

```markdown
- `CHAT_MODEL` / `FAST_MODEL` / `ORCHESTRATOR_MODEL` / `VIDEO_MODEL`: Override the
  models in `config/agent_config.py`. Preview models are rejected by tests.
- `VIDEO_QA_DAILY_BUDGET_USD`: Daily spend cap for video Q&A. Unset means unlimited.
```

- [ ] **Step 3: 更新 `docs/01_plan/project-roadmap.md`**

- 「最後更新」改為完成當日日期
- 測試數字改為 `255 passed / 2 skipped`
- 「模型」列改為：`3.7-flash（推理）／3.5-flash-lite（高頻、影片），見 config/agent_config.py`
- 「目前焦點」改為下一項待辦（P2 測試安全網）
- P1-4「用量與成本觀測」狀態改為 `Completed`，並註明由 `services/usage_meter.py` 完成
- 「已完成的能力」表格加一列：

```markdown
| 影片問答 | 針對 YouTube 影片連續提問，答案帶時間戳（agentic video understanding） | [video-qa](../superpowers/specs/2026-09-02-video-qa-design.md) |
```

- 決策紀錄加兩列：

```markdown
| YYYY-MM-DD | 影片問答採 stateless 重新查詢，不保留 context | Vertex AI 不回傳 tool_call/tool_response parts，history 重播會 400 或被完整重跑 |
| YYYY-MM-DD | 影片一律 thinking_level=LOW，且固定用 3.5-flash-lite | 漏設成本變 5.5 倍且無徵兆；3.7-flash 在 agentic 會忽略此參數，成本高 60 倍 |
```

- [ ] **Step 4: 執行完整測試套件**

Run: `python3 -m pytest -q`
Expected: `262 passed, 2 skipped`

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example docs/01_plan/project-roadmap.md
git commit -m "docs: document video Q&A and the model config surface

README 加入影片問答功能與四個模型環境變數；.env.example 補上
VIDEO_QA_DAILY_BUDGET_USD；roadmap 更新測試數字、標記 P1-4 完成
（由 usage_meter 一併達成），並記錄兩項設計決策。"
```

---

## 驗收

全部完成後應滿足：

- `python3 -m pytest -q` → `262 passed, 2 skipped`
- `grep -rn '"gemini-[0-9]' --include='*.py' .` 只在 `config/agent_config.py`、`services/voice_live.py`、`tools/tts_tool.py`、`tests/` 命中
- 實機測試：貼 YouTube 連結 → 收到摘要 → 按「🎬 問這部影片」→ 提問 → 收到帶時間戳的答案 → 貼另一個網址 → 自動離開模式並正常處理新網址
- Firestore `usage_records` collection 有當日記錄，`cost_usd` 與 log 中的數字相符
