# Project Roadmap — LINE Bot Information Helper

> 專案總覽與現況。細節不寫在這裡：功能設計看 [`docs/superpowers/specs/`](../superpowers/specs/)，
> 執行細節看 `docs/02_implement/sprint-*.md`（尚未建立）。

**最後更新**：2026-09-16

---

## 目前狀態

| 項目 | 狀態 |
|---|---|
| 部署 | Cloud Run `us-central1`，no-cpu-throttling |
| 測試 | 306 passed / 2 skipped（`pytest -v`，CI 見 `.github/workflows/`） |
| 模型 | `gemini-3.7-flash`（推理）／`gemini-3.5-flash-lite`（高頻、影片）／LIFF 語音程式預設 `gemini-3.8-live`，**但正式環境以 `VOICE_MODEL` 釘在 `gemini-3.1-flash-live-preview`**（見決策紀錄 2026-09-16 事故），見 `config/agent_config.py` |
| 持久化 | Firestore（chat sessions、bookmarks、reports、batch jobs、usage records） |
| 目前焦點 | P2 測試安全網——見下方 P2 清單 |

---

## 已完成的能力

| 領域 | 內容 | 規格 |
|---|---|---|
| 網址處理 | 多層降級爬取（Firecrawl／SingleFile／httpx／CloudScraper）、WAF 偵測、文件轉 Markdown | — |
| 社群文案 | 中英文各 4 平台（FB／LinkedIn／Threads／Twitter），人性化守則 + 台灣在地化 | — |
| 書籤系統 | `/save` `/list` `/search`，候選 → 確認儲存兩段式 | [bookmark](../superpowers/specs/2026-08-13-bookmark-system-design.md) |
| 研究報告 | 按鈕產生 grounded 報告，Firestore 永久保存 + 7 天快取 | [research-report](../superpowers/specs/2026-08-15-research-report-design.md) |
| 語音 | LINE 語音訊息、朗讀摘要、LIFF 即時語音助理（Gemini 3.8 Live） | [voice](../superpowers/specs/2026-03-28-liff-voice-assistant-design.md) |
| 影片問答 | 針對 YouTube 影片連續提問，答案帶時間戳（agentic video understanding） | [video-qa](../superpowers/specs/2026-09-02-video-qa-design.md) |
| 其他 | 圖片分析、地點/美食查詢、GitHub 摘要、Gemini Batch webhook |  |

---

## 接下來的規劃

排序依據：**先修會咬人的、再省錢、再補安全網、最後才加功能。**

### P0 — 已知缺陷 — Completed（2026-08-26）

| # | 項目 | 問題 | 狀態 |
|---|---|---|---|
| 0 | 聊天功能無法使用 | `loader/chat_session.py` 寫死的 `gemini-3-pro-preview` 已從 Vertex AI 下架，真實路徑回 404；該檔例外處理直接 raise。README 首項功能整段時間不能用，且無測試覆蓋 | Completed（2026-09-03） |
| 1 | 多網址訊息只回得出第一個 | `handle_url_message` 對每個網址產生 5 則訊息，結尾 `results[:5]` 直接截斷 | Completed |
| 2 | LINE 訊息額度已用滿 | carousel + 4 則純文字 = 5，剛好卡在單次上限，再加東西就會被擠掉 | Completed |

作法：加 `_reply_with_overflow` / `_push_in_chunks`——前 5 則走 reply（不計 push 額度），
其餘自動分批 push。單一網址的常見情境行為完全不變、不動用 push；多網址不再掉訊息；
日後新增平台會自動溢位到 push 而不是被平台丟掉。

順帶修掉同類的兩處：`handle_url_push_message`（訊息數等於網址數，上限只擋在 `/urls`
端點那頭）與 `handle_agentic_vision_with_prompt`（回覆 + N 張標註圖，張數不固定）。

回歸測試見 `tests/test_line_message_overflow.py`——把 `results[:5]` 放回去會直接失敗
（10 則只送出 5 則）。

P0-0 作法：模型抽成模組常數 `CHAT_MODEL`，改用實測可用的 `gemini-3.7-flash`。
回歸測試見 `tests/test_chat_session_model.py`——守的是 bug class 而非單一字串：
斷言不得使用 preview／實驗模型（preview 會無預警下架，這次就是這樣壞的），
且必須在實測可用清單內。

### P0.5 — 影片問答任務中發現的既有問題 — Completed（2026-09-03）

以下三項是 2026-09-03 影片問答＋模型分級升級任務過程中發現的既有問題，與該
任務無關、非該任務造成。

| # | 項目 | 問題 | 狀態 |
|---|---|---|---|
| 13 | 正式環境沒裝 `google-adk` | `Dockerfile:15` 把 `requirements-lock.txt` 複製成 `requirements.txt` 安裝，但鎖定檔沒有 `google-adk`，三個呼叫端的 import guard 安靜降級 | Completed（2026-09-03，改為明確不依賴 ADK） |
| 14 | YouTube 摘要按鈕是死碼 | `"youtube_summary"` postback 有 handler，但沒有任何地方會產生送出這個 action 的按鈕 | Completed（2026-09-03，砍掉 handler） |
| 15 | `find_url()` 抓不到省略協定的網址 | 正則是 `r'https?://[^\s]+'`，`www.youtube.com/watch?v=...` 完全偵測不到。影響整條網址流程 | Completed（2026-09-03） |

P0.5-13 作法：查證後發現 `adk_agent` 物件只有被「建立」、沒有任何一條路徑會呼叫
（沒有 runner、沒有 `.run()`），所有工作都是直接呼叫 `tools/` 的函式。裝上去只是
多建幾個沒人用的物件，代價卻是 fastapi 0.115.5 → >=0.133、starlette 0.41.3 → >=1.3.1
的大版本升級。因此改成明確不依賴：從 `requirements.txt` 移除並寫清楚原因，
`agents/` 的 import guard 保留（ADK 遷移分支還在）。回歸測試
`tests/test_requirements_lock.py` 守的是 bug class——任何寫進 `requirements.txt`
卻沒進鎖定檔的套件都會失敗，不必再靠人眼發現「正式環境其實沒裝」。

P0.5-14 作法：砍掉 handler 而不是補按鈕——Twitter 文案已由網址流程的 carousel
產出，而那則訊息的 quick reply 位置現在掛的是「🎬 問這部影片」。
`tests/test_postback_actions.py` 要求 handler 與按鈕成對存在（兩個方向都檢查）。

P0.5-15 作法：帶協定／`www.` 開頭／白名單 TLD 的裸網域三種都認，一律補 `https://`
再回傳（下游 `is_youtube_url()`、爬蟲、書籤都預期完整網址）。TLD 走白名單，否則
`main.py`、`app.json` 這類檔名會被當成網址。全形標點排除在網址字元外、但保留中文
字（`zh.wikipedia.org/wiki/台灣` 是合法網址），半形標點在尾端剝除且保留成對括號。
已知取捨：純文字提到裸網域會被當成網址，影片問答模式下會觸發離開——該啟發式本來
就偏向離開，誤判成本低。測試見 `tests/test_find_url.py`。

未處理的相關發現：`agents/orchestrator.py:122` 自己有一份 `https?://` 正則，
沒有共用 `find_url()`，同樣抓不到省略協定的網址。目前 `main.py` 會先用
`find_url()` 把帶網址的訊息路由到 `handle_url_message`，所以這條路徑影響有限，
但邏輯分歧仍在。

### P1 — 成本與延遲

| # | 項目 | 理由 | 估時 | 狀態 |
|---|---|---|---|---|
| 3 | 爬取結果快取 | 同一個網址原本最多被爬 3 次（初次、英文貼文、研究報告） | — | Completed（2026-08-26） |
| 4 | 用量與成本觀測 | 目前沒有任何 token／成本統計，也沒有錯誤聚合。每則網址至少 1 次 Gemini，按鈕還會再打。先把 `usage_metadata` 記進 log 或 Firestore，再談優化 | 1-2d | Completed（2026-09-03，由 `services/usage_meter.py` 完成，隨影片問答一併實作） |

P1-3 作法：`services/url_cache.py` + `load_url` 最外層的快取包裝，四個呼叫點自動受惠、
不需各自改。TTL 24 小時（不比照報告的 7 天——存的是網頁當下內容，放太久會拿到舊資料）。
空內容不快取（那代表爬取失敗），超過 700 KB 不快取（Firestore 單一文件上限 1 MiB）。
Firestore 不可用或讀寫出錯時安靜降級成直接爬。`use_cache=False` 可強制重爬。

### P2 — 測試安全網

| # | 項目 | 理由 | 估時 | 狀態 |
|---|---|---|---|---|
| 5 | `loader/error_handler.py` 補測試 | 227 行的 retry + circuit breaker，是所有降級策略的安全網，目前零測試。壞掉不會有人發現 | 0.5d | Not Started |
| 6 | 其他無測試模組 | `chat_agent`(381)、`maps_tool`(410)、`chat_session`(358)、`summarizer`(355)、`youtube_tool`(259) | 2-3d | Not Started |
| 7 | main.py handler 測試 | 2078 行、50+ 個 function，目前只有 `test_webhook_async` 摸到入口 | 1-2d | Not Started |

### P3 — 結構整理

| # | 項目 | 理由 | 估時 | 狀態 |
|---|---|---|---|---|
| 8 | 拆分 `main.py` | webhook 路由、LINE handler、batch webhook、LIFF、WebSocket 全混在一份 2078 行的檔案。照現有 `services/` 慣例拆成 `handlers/` | 2d | Not Started |

> 建議排在 P2 之後：沒有測試就大搬家，等於把安全網拆掉再走鋼索。

### P4 — 新功能（想清楚再做）

| # | 項目 | 備註 | 狀態 |
|---|---|---|---|
| 9 | 使用者偏好設定 | 預設摘要模式、預設語言、要不要純文字版。做完 P0-2 之後特別合理 | Not Started |
| 10 | 書籤標籤與全文檢索 | 目前 `/search` 是簡單比對 | Not Started |
| 11 | 內容來源擴充 | Reddit、arXiv | Not Started |
| 12 | 日文貼文 | 中英之外的第三語言，架構已支援（比照 `SocialMediaPostsEN`） | Not Started |

---

## 決策紀錄

| 日期 | 決策 | 原因 |
|---|---|---|
| 2026-09-16 | **事故**：LIFF 語音全面連不上（13:45–14:37 UTC）。正式環境 `VOICE_MODEL` 回滾到 `gemini-3.1-flash-live-preview`（revision `00278-hsv`）；resume handle 保存邏輯抽到 `voice_live.run_relay_with_resumption()` 並修正 | 兩層原因。(1) Google 端 `gemini-3.8-live` 行為改變：標準 PTT 流程（activity_start→音訊→activity_end）穩定回 1007 Precondition check failed，同一份 config 當天稍早是成功的，3.1 仍正常。(2) 我們的潛伏 bug：3.8 在 1007 之前就先送出 resume handle，舊迴圈把死 session 的 handle 存起來，之後 15 分鐘內每次連線都 1011，使用者被鎖住。3.1 在 1007 前不發 handle，所以從沒踩到。修正後：失敗的 session 不存 handle 且作廢舊的；帶 handle 連不上時丟掉重試一次。已對真實 API 驗證兩個情境。**修正只解決鎖死，不解決 3.8 PTT 本身壞掉** |
| 2026-09-16 | LIFF 語音助理從 `gemini-3.1-flash-live-preview` 換成 `gemini-3.8-live`（GA），模型 ID 收回 `config/agent_config.py`，`EXEMPT_FILES` 由 2 個檔縮為 1 個 | 3.8 Live 是 GA（名稱不含 `-preview`），堵上 P0-0 那個 bug class 最後一個缺口。實測對現有 `LiveConnectConfig` 完全相容：PTT activity 信號、`session_resumption`、雙向 transcription、Aoede 語音、兩個 Tool 物件與 tool calling 皆逐項驗過 |
| 2026-09-16 | 不採用 `gemini-3.8-live-extended-thinking` | 該模型強制要求 `thinking_level`，未帶 `thinking_config` 連線直接被擋（1007）。`build_live_config()` 目前不送，已用 `LIVE_CAPABLE` 名單擋住誤設 |
| 2026-09-16 | `tools/tts_tool.py` 維持 preview 例外 | 查證當日 API 上三個 TTS 模型全是 preview（`2.5-flash-preview-tts`／`2.5-pro-preview-tts`／`3.1-flash-tts-preview`），無 GA 版可換 |
| 2026-09-03 | 影片問答的 `thinking_tokens` 屬伺服器端非決定性（同設定同影片同批次仍在 ~0 與 ~35,000–37,000 間跳動），維持 `thinking_level="LOW"` 並加 `THINKING_TOKENS_WARN_THRESHOLD` 警告 log，不切換其他 thinking 參數 | 27 次對照實驗顯示 `thinking_budget=0`、省略 `thinking_config` 與 `LOW` 量測不出差異，換一個沒有實測優勢的參數只是把「測過的行為」換成「沒測過的行為」；`thinking_budget` 與 `thinking_level` 也不能並用（400 錯誤），見 [video-qa 結論三](../superpowers/specs/2026-09-02-video-qa-design.md) |
| 2026-09-03 | 影片一律 thinking_level=LOW，且固定用 3.5-flash-lite | 3.5-flash-lite 是唯一經端到端驗證、正常情況下較便宜的基準模型（不代表成本穩定——結論三的 27 次尖峰量測就是在這個模型上做的）；3.7-flash 從未重複測試，且測試中較易觸發 429 |
| 2026-09-03 | 影片問答採 stateless 重新查詢，不保留 context | Vertex AI 不回傳 tool_call/tool_response parts，history 重播會 400 或被完整重跑 |
| 2026-09-03 | 模型一律不用 preview／實驗版，並以測試強制 | `gemini-3-pro-preview` 無預警下架把聊天功能弄壞，且完全沒被發現 |
| 2026-08-26 | 爬取快取 TTL 設 24 小時，而非比照報告的 7 天 | 存的是網頁當下內容，新聞類頁面放太久會拿到舊資料 |
| 2026-08-26 | 訊息一律走「reply 前 5 則 + push 溢位」，不再截斷 | 截斷會讓已付出的爬取與 Gemini 成本白費 |
| 2026-08-26 | Twitter 文案採資深軟體總監人設，字數依 X Premium Basic 放寬 | 使用者帳號無 280 字元限制 |
| 2026-08-26 | Threads 從「脆友吐槽」改為「專業觀點」 | 對外文案要維持專業形象 |
| 2026-08-19 | 研究報告改存 Firestore | Cloud Run instance 回收會讓記憶體版失效 |
| — | 移除 LangChain，全面改用 Vertex AI | 配額與成本管理較佳（見 [IMPROVEMENTS.md](../IMPROVEMENTS.md)） |
