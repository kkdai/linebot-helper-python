# 詳細研究報告(臨時網頁)設計

日期:2026-08-15
狀態:已核准(對話確認,研究方式選 B:文章 + Google Search Grounding)

## 目標

摘要 bubble 加第三顆按鈕「📄 詳細研究報告」:深入研究網址內容產生報告,
以臨時網頁呈現;報告只存記憶體,instance 休眠/回收即消失(刻意如此)。

## 流程

1. 摘要 bubble 按鈕 postback:`{"action": "research_report", "id": <bookmark_doc_id>}`
   (與儲存書籤同機制;Firestore 不可用沒有 doc id 時不顯示此按鈕)。
2. Postback handler:驗證書籤屬於該使用者 → 立即 reply「🔬 研究中,完成後傳連結」
   → 背景執行:`load_url()` 重新爬取 → `generate_research_report()` → 渲染 HTML
   → 存入記憶體 ReportStore → push 連結給使用者。
3. `GET /reports/{report_id}`:回報告頁;不存在或過期回「報告已過期」頁(404)。

## 研究報告生成(loader/langtools.py)

`generate_research_report(text, url) -> {"markdown": str, "sources": list}`

- 模型 `gemini-3.1-flash-lite` + `google_search` grounding 工具(方案 B):
  模型自動搜尋補充背景、相關報導、對照觀點。
- 輸出為 Markdown 純文字(grounding 工具與 response_schema 不能並用),
  結構:標題、執行摘要、背景脈絡、核心論點與證據、數據整理、
  對照觀點與批判、延伸問題。
- 引用來源從 `grounding_metadata` 抽取(同 chat_session 既有作法)。
- Grounding 呼叫失敗時降級:同 prompt 不帶工具重試一次;再失敗回錯誤。

## 臨時網頁

- `services/report_store.py`:`ReportStore`(dict + TTL 24h),
  `put(html) -> report_id`(uuid4 hex,不可猜測)、`get(report_id) -> html|None`,
  存取時順手清過期項。記憶體儲存 = instance 回收即消失,符合需求。
- `services/report_page.py`:`render_report_page(...)` 把 Markdown 轉 HTML
  (Python-Markdown 套件,extra 擴充)套進閱讀版型(inline CSS、行動裝置優先、
  標題/原文連結/產生時間/來源清單/「此為臨時頁面」提示);`render_expired_page()`。
- 連結用既有的 `app_base_url`(與 TTS 音檔同 pattern)。

## 錯誤處理

- 爬取或生成失敗:push FriendlyErrorMessage 風格中文錯誤。
- `app_base_url` 未偵測到:push 提示稍後再試。
- 報告過期/不存在:HTML 過期頁,HTTP 404。

## 測試

- ReportStore:存取 roundtrip、TTL 過期、未知 id。
- report_page:Markdown 轉出標題/列表、含原文連結與來源;過期頁。
- bookmark_flex:摘要 bubble 含 research 按鈕與 postback 格式;無 doc_id 時隱藏
  (既有「恰一顆 postback」測試同步更新為兩顆)。
- route:TestClient 塞報告後 GET 200;未知 id 404。
- BookmarkService 新增 `get_bookmark(user_id, doc_id)`(含所有權驗證)。

## 範圍外

報告列表頁、多輪 agentic 研究、PDF 匯出。

## 依賴

新增 `Markdown`(Python-Markdown)至 requirements.txt / requirements-lock.txt。

## 更新記錄

**2026-08-19：報告持久化**(對話確認)

原決定「報告只存記憶體，instance 回收即消失」推翻。改為 `ReportStore`
改用 `FirestoreKVStore`(與書籤共用模式)永久保存，不再設 TTL：

- `services/report_store.py`:`put`/`get` 介面不變，內部改呼叫
  `FirestoreKVStore(collection="reports")`；Firestore 不可用時優雅降級為
  no-op(與其他 store 一致，非 CI/本機開發常態)。
- `services/report_page.py`:移除「臨時頁面、24 小時後失效」提示；
  `render_expired_page()` 改為「找不到報告」(對應未知 id，而非過期)。
- 報告持久化不再是範圍外項目；報告列表頁、多輪 agentic 研究、PDF 匯出
  仍維持範圍外。
