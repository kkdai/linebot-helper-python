# 影片問答與模型分級升級設計

日期：2026-09-02
狀態：已核准（對話確認：分級升級、模式+啟發式脫離、stateless 重新查詢、配額先開滿）

## 目標

兩件綁在一起的事：

1. **影片問答**：YouTube 摘要之外，新增「問這部影片」——使用者可以連續追問影片內容，
   模型回答並給出精準時間戳（例如「定價在 1:24:40」）。基於 Gemini 的
   agentic video understanding（`media_processing="AGENTIC"`）。
2. **模型分級升級**：repo 內 28 處模型字面值依用途分三級升到現行 stable 模型，
   並收斂進 `config/agent_config.py`。

---

## Spike 結論（2026-09-02，實測於 line-vertex 專案）

設計建立在這些實測數字上，不是文件描述。**改動這塊設計前請先讀完本節。**

### 一、Vertex AI 上無法保留影片 context

官方文件描述的多輪機制（回傳 `tool_call` / `tool_response` parts，原樣傳回即可
延續影片 context）**在 Vertex AI 上拿不到**：

- 回應只有光禿禿的 `thought_signature` parts，沒有 `tool_call` / `tool_response`。
- 預設 thinking 下把 history 傳回 → `400 INVALID_ARGUMENT: Invalid thought signature.`
  三種序列化方式都失敗，**連完全不序列化、直接傳回 response 物件也失敗**
  → 不是序列化問題，是平台問題。
- `thinking_level="LOW"` 下不報錯，但第二輪 `tool_use_prompt_token_count` 與第一輪
  完全相同（2,163 vs 2,163）→ 影片被完整重跑，context 沒有保留。

該多輪機制是寫給 Gemini Developer API 的，Vertex 這條路上走不通。

**設計後果**：改用 stateless 重新查詢。不存 API history，每次提問重新查詢影片。

### 二、thinking token 是成本主角，且按 output 計價

同一支 10 分鐘影片，`gemini-3.5-flash-lite`：

| 模式 | in | out（含 thinking） | 成本 |
|---|---|---|---|
| STATIC | 54,546 | 291 | $0.0171 |
| AGENTIC，**未設** thinking_level | 2,216 | 37,574 | $0.0946（比 static 貴 5.5 倍） |
| AGENTIC + `thinking_level="LOW"` | 2,216 | 638 | $0.0023（比 static 便宜 7.4 倍） |

agentic 把影片從 input 移除（54,546 → 2,216），但改用「思考」導航，而
thinking token 按 output 計價（$2.50/M，是 input 的 8.3 倍）。

**漏設 `thinking_level` 不會報錯、不會有任何徵兆，只有帳單會變。**
這是測試策略①存在的唯一理由。

### 三、長片上 thinking_level 會被忽略

2 小時影片（Google I/O '25 keynote），同樣設 `thinking_level="LOW"`：

| 影片長度 | thinking tokens | 每次成本 | 延遲 |
|---|---|---|---|
| 10 分鐘 | 0 | $0.0023 | ~10s |
| 2 小時 | 359,961 | **$0.9067** | 26–53s |
| （static 估算，2h） | — | ~$0.196 | — |

長片上 agentic 比 static 貴約 4.6 倍。公告宣稱的「成本降 66%」在 Vertex 的
價格結構下，長片不成立（token 總數確實降約 40%，但貴的那部分變多了）。

### 四、模型可用性（實測）

| 模型 | 結果 |
|---|---|
| `gemini-3.7-flash` | OK。但 agentic 影片會忽略 `thinking_level`（設 LOW 仍燒 36,354 thinking tokens，10 分鐘影片 $0.1389，是 3.5-flash-lite 的 60 倍），且易觸發 429 |
| `gemini-3.6-flash` | OK |
| `gemini-3.5-flash-lite` | OK。影片唯一划算的選擇 |
| `gemini-3.1-flash-lite` | OK，但不在 agentic 支援名單，設 AGENTIC 會靜默降級為 STATIC |
| `gemini-3-pro-preview` | **404 NOT_FOUND，已下架** |
| `gemini-2.5-pro` | OK，但回一個字燒 1,066 tokens |

### 五、附帶發現：聊天功能目前是壞的

`loader/chat_session.py:104` 使用 `gemini-3-pro-preview`，實測真實路徑
（`chats.create` + `send_message` + Google Search grounding）回 404，
而該檔 118 行的例外處理是直接 `raise`。

README 首項功能「🤖 Intelligent Conversation with Memory」目前無法使用。
3.7-flash / 3.6-flash 走同一條路徑（含 grounding）實測正常。

### 六、序列化體積不是問題

history 序列化後僅 1.5–7 KiB，Firestore 1 MiB 上限有 99.3% 未使用。
原本擔心的體積限制完全不成立。

---

## 架構

四個單元，各自獨立可測：

### ① `tools/youtube_tool.py`（改）

唯一與 Gemini 影片 API 溝通的地方。內部收斂成一個 `_generate_video()`：

```
_generate_video(url, prompt, *, thinking_level) -> {"text": str, "usage": dict}
summarize_youtube_video(url, mode)   # 既有，行為不變
ask_youtube_video(url, question)     # 新增
```

`media_processing="AGENTIC"`、`api_version="v1beta1"`、模型、`thinking_level`
全部集中在 `_generate_video` 一處。

**`thinking_level` 是必填參數，無預設值。** 見 Spike 結論二。

回傳一律帶 `usage`（從 `usage_metadata` 抽出的 dict），呼叫端不需碰 SDK 型別。

### ② `services/usage_meter.py`（新）

```
record(user_id, feature, usage) -> None
spent_today(user_id) -> float
check_budget(user_id) -> (bool, remaining)
```

配額以**實際花費**計，不以影片長度計——用長度就得先查影片時長（需另接
YouTube Data API），且長度與花費非線性（10 分鐘 $0.0023、2 小時 $0.91）。

同時完成 roadmap P1-4「用量與成本觀測」。

**本次只做記錄，不做強制**：`check_budget` 讀 `VIDEO_QA_DAILY_BUDGET_USD`，
未設即不限制。呼叫點先放好，日後開啟只需設環境變數。

### ③ `services/video_qa.py`（新）

記住使用者目前在問哪支影片。因 context 保不住，**不存 API history**，只存：
影片網址、進入時間、提問次數。TTL 30 分鐘。

**直接使用 `services/firestore_store.py` 的 `FirestoreKVStore("video_qa_sessions")`**，
不包 `SessionManager`。

原設計為「包一層 `SessionManager`」，實作前檢視其內部後改為此作法。
`SessionManager` 是繞著「一個 Gemini chat 物件 + 會裁切的對話歷史」設計的，
與本用途有四個摩擦點，前兩點會實際出錯：

1. `_persist_session()` 不持久化 `metadata`（只存 `user_id` / `history` /
   `created_at` / `last_active`）→ 影片網址放 `metadata` 會在 instance 重啟後消失。
2. `add_to_history()` 超過 `max_history_length` 會保留最後 N 則 → 網址放
   `history[0]` 會在第 N 次提問後被裁掉。
3. `get_or_create_session()` 必填 `chat_factory`，但影片問答沒有 chat 物件。
4. `get_session_manager()` 是單例，與聊天共用 `chat_sessions` collection 及
   同一個 `_sessions` dict → 同一個 user_id 會相互覆蓋。

`FirestoreKVStore` 同樣是現成且有測試覆蓋（`tests/test_firestore_persistence.py`）
的元件，且形狀相符——影片模式要存的就是「使用者 → 影片」的 KV 對應。

### ④ `main.py`（改）

僅兩個接點：

- `main.py:596` 的 `isinstance` 判斷**之前**插入攔截。
- `main.py:1442` 的 `action_value` 新增 `video_qa` / `video_qa_exit` 分支。

### 明確不做

- 不碰 `loader/chat_session.py` 的 history 機制（語意不同）。模型已於 2026-09-03
  修復為 `gemini-3.7-flash`（PR #17），本設計不再變更該檔。
- 不碰 `services/voice_live.py`、`tools/tts_tool.py` 的模型（見模型分級）。
- 不做影片上傳（LINE `VideoMessage`）——需 GCS bucket、生命週期規則、
  記憶體重估，與本設計無關，另案。

---

## 流程

### 進入模式

YouTube 摘要按鈕組新增 quick reply：

```
🎬 問這部影片  → postback {"action": "video_qa", "url": "..."}
```

按下**不呼叫 Gemini**，只寫入 session 並回提示，附「🚪 結束問影片」quick reply。

### 模式中每則訊息的判斷順序

```
是文字訊息，且使用者在影片模式中？
├─ 否 → 原路，不動
└─ 是 → 脫離條件檢查
        ├─ 含網址 / 以 / 開頭 / 非文字訊息 → 清模式，交還原路
        └─ 否 → 配額檢查
                ├─ 超支 → 不打 Gemini，回訊息 + 清模式
                └─ 通過 → show_loading_animation()
                          → ask_youtube_video()
                          → record(usage)
                          → _reply_with_overflow(答案 + 結束按鈕)
```

**脫離判斷必須在配額判斷之前**：使用者貼新網址想換主題，不該因影片配額用完被擋。
這是行為契約，有對應測試。

### 脫離方式

| 方式 | 觸發 |
|---|---|
| 手動 | 每則答案掛「🚪 結束問影片」 |
| 自動 | 網址 / `/` 指令 / 圖片、語音、位置訊息 |
| 超時 | 30 分鐘 session TTL |

刻意不用 LLM 判斷意圖：需多打一次 Gemini，而誤判代價很低（再問一次即可）。

### 延遲處理

實測長片 26–53 秒，逼近 LINE reply token 邊界。因此：

- 先 `show_loading_animation()`——**不消耗 reply token**（既有慣例見 `main.py:894`）
- 答案回來走 `_reply_with_overflow()`——reply 成功不動用 push 額度，失敗才 push
  （P0 既有機制）

---

## 模型分級

### 現況：兩層，只有一層是硬寫的

`agents/` 那層**已經是 config 驅動**——`location_agent`、`github_agent`、
`content_agent` 用 `config.fast_model`，`orchestrator` 用 `config.orchestrator_model`，
`vision_agent`、`chat_agent` 用 `config.chat_model`。

硬寫模型字串的是 `tools/` 與 `loader/`（不走 ADK、直接呼叫 SDK 的路徑）。
收斂工作主要在這兩層。

### Tier 1 — `gemini-3.7-flash`（剩 3 處字面值，2 個邏輯位置）

| 位置 | 現況 | 理由 | 狀態 |
|---|---|---|---|
| `loader/chat_session.py` | ~~`gemini-3-pro-preview`~~ → `CHAT_MODEL = "gemini-3.7-flash"` | 404，修故障 | **已完成**（PR #17，2026-09-03） |
| `config/agent_config.py:22,58`（`orchestrator_model`） | `gemini-2.5-pro` | 過舊；回一字燒 1,066 tokens | 待做 |
| `tools/summarizer.py:227`（agentic vision） | `gemini-3-flash-preview` | preview → stable（實測仍存活，但同屬會下架的一類） | 待做 |

原則是**維持既有能力層級，只做現代化**：現在是 pro 級的升到 3.7-flash，
現在是 lite 級的升到 3.5-flash-lite。

### Tier 2 — `gemini-3.5-flash-lite`（23 處）

所有 `gemini-3.1-flash-lite` 字面值，除 `tools/youtube_tool.py:204`（歸 Tier 3）：

| 檔案 | 處數 |
|---|---|
| `loader/langtools.py` | 6（161, 206, 491, 550, 634, 686） |
| `tools/maps_tool.py` | 5（109, 144, 247, 314, 379） |
| `config/agent_config.py` | 4（21, 23 預設值；57, 59 env 預設）＝ `chat_model` + `fast_model` |
| `tools/summarizer.py` | 2（159, 322） |
| `loader/searchtool.py`、`loader/gh_tools.py`、`loader/maps_grounding.py`、`loader/youtube_gcp.py`、`tools/audio_tool.py`、`services/batch_service.py` | 各 1 |

注意 `config.chat_model` 同時被 `agents/vision_agent.py:81`（註解寫
"Use capable model for vision"）與 `agents/chat_agent.py` 使用。兩者現況都是
`3.1-flash-lite`，改為 `3.5-flash-lite` 行為等價，不變更能力層級。

成本代價：output $1.50/M → $2.50/M（貴 67%）。仍升級的理由是 `3.1-flash-lite`
遲早比照 `gemini-3-pro-preview` 無預警下架，且 3.5-flash-lite 在 agentic 支援名單上。

### Tier 3 — 影片

`tools/youtube_tool.py`：`gemini-3.5-flash-lite` + `AGENTIC` + `thinking_level="LOW"`。
見 Spike 結論二、三、四。

### 不動

| 位置 | 模型 | 理由 |
|---|---|---|
| `services/voice_live.py:21` | `gemini-3.1-flash-live-preview` | Live API 僅支援此模型 |
| `tools/tts_tool.py:19` | `gemini-3.1-flash-tts-preview` | TTS 為獨立模型家族 |

### 收斂

`tools/` 與 `loader/` 的硬寫字串改為讀 `config/agent_config.py`，與 `agents/`
那層一致。既有的 `CHAT_MODEL` / `FAST_MODEL` / `ORCHESTRATOR_MODEL` 三個環境變數
沿用，新增 `VIDEO_MODEL`（Tier 3）。

完成後換模型只需改環境變數，不必再全 repo 掃一遍——本次之所以要掃 28 處，
正是因為過去沒有這一層。

---

## 前置任務：升級 SDK

`media_processing` 欄位自 **google-genai 2.20.0** 起提供（逐版驗證：2.19.0 無、
2.20.0 有）。`requirements-lock.txt` 現鎖 2.7.0 → 需升至 2.21.0。

跳 14 個 minor 版本是本案最大風險，且與 agentic 無關。**須獨立完成並驗證後
才開始其他工作**：

1. 升版，跑完整測試（門檻：192 passed / 2 skipped 不退步）
2. 重點確認 `services/voice_live.py`——Live API 介面在此區間最易變動，且零測試
3. 確認 `tools/tts_tool.py`、`services/batch_service.py` 正常

---

## 錯誤處理

- Gemini 429：沿用 `youtube_tool` 既有 retry（指數退避，最多 2 次）。
- 影片為私人／網址無效：明確中文訊息，並清除影片模式。
- Firestore 不可用：`usage_meter` 與 `video_qa` 皆安靜降級
  （照 `services/url_cache.py` 慣例——記帳壞掉不能讓功能壞掉）。
- 其餘照 `loader/error_handler.py` 的 `FriendlyErrorMessage`。

---

## 測試

### ① 防成本默默爆掉（第一級，非附加）

```
test_video_call_always_sets_thinking_level_low
test_video_call_uses_agentic_media_processing
test_video_call_uses_v1beta1            # v1 會靜默退回 STATIC
test_video_call_uses_supported_model    # 3.1-flash-lite 會靜默降級
```

斷言 SDK 收到的參數。存在理由：這四件事錯了，程式照跑、答案照出，
只有成本默默變化——人工 review 抓不到。

### ② 反向守衛

```
test_voice_live_model_unchanged
test_tts_model_unchanged
```

本次要掃 28 處模型字面值，下次掃的人不會記得這兩個例外。

### ③ 模式狀態機

```
test_enter_video_mode_does_not_call_gemini
test_url_message_exits_video_mode
test_slash_command_exits_video_mode
test_image_message_exits_video_mode
test_normal_text_stays_in_video_mode
test_session_expires_after_ttl
test_exit_check_runs_before_budget_check
```

### ④ 用量記錄

```
test_record_accumulates_daily_spend
test_usage_survives_firestore_roundtrip
test_firestore_unavailable_degrades_silently
test_budget_unset_means_unlimited
```

慣例：zh-TW docstring 說明「為什麼有這個測試」、用 `tests/fakes.py` 的
`FakeStore` / `UnavailableStore`、不打網路。

---

## 範圍外

- 配額強制的細節（上限值、重置排程、用完的文案）——只留環境變數接縫。
- 每則訊息顯示花費、`/usage` 指令（資料已記錄，日後可加）。
- LINE `VideoMessage` 影片上傳（原提案 C）。
- 影片摘要沿用至問答第一輪的 context 重用——Vertex 上不可行，見 Spike 結論一。
