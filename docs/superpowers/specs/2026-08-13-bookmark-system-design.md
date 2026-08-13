# 書籤/稍後讀系統設計

日期:2026-08-13
狀態:已核准(對話中確認,方案 C + 社群貼文加摘要分析)

## 目標

讓使用者把處理過的文章存成書籤稍後閱讀:`/save <url>` 主動存檔、
社群貼文 carousel 上一鍵儲存、`/list` 與 `/search` 瀏覽。

## 資料模型

Firestore collection `bookmarks`(沿用 `services/firestore_store.FirestoreKVStore`):

- doc id:`sha1(user_id + url)` 前 20 碼(同使用者同網址去重,重存即更新)
- 欄位:
  - `user_id`: str
  - `url`: str
  - `title`: str
  - `summary`: str(摘要+重點分析)
  - `created_at`: float(epoch)
  - `saved`: bool(false = 候選,尚未被使用者確認儲存)
  - `source`: `"command"` | `"button"`

## 流程

### 社群貼文 carousel 改動

1. `generate_social_media_posts()` prompt 擴充:同一次 Gemini 呼叫額外回傳
   `title` 與 `summary_analysis`(150–250 字摘要與重點分析)。
2. Carousel 第一顆 bubble 為「📌 摘要與分析」:標題 + 摘要分析 +
   「🔖 儲存書籤」postback 按鈕;其後為 FB/LinkedIn/Threads 三顆(共 4 顆)。
3. 產生 carousel 時即寫入書籤 doc(`saved=false` 候選);postback data 只帶
   `action=save_bookmark&id=<doc_id>`(postback data 限 300 字元,不放內容)。
4. 使用者點按鈕 → 翻成 `saved=true`、回覆確認訊息。
5. 寫入新候選時順手刪除該使用者 7 天以上未儲存的舊候選。

### 指令(進 orchestrator 前攔截,與 /clear、/status 同層)

- `/save <url>`:`load_url()` 爬取 → `summarize_for_bookmark()`(langtools 新函式,
  回傳 title+summary JSON)→ 存 `saved=true, source=command`。
- `/list`:該使用者 `saved=true` 依 `created_at` 新→舊取 10 筆,回 Flex carousel。
- `/search <關鍵字>`:同 `/list`,先在 Python 內對 title+summary 做不分大小寫
  子字串比對(個人規模,不建索引、不引入搜尋服務)。

### 書籤 carousel bubble

標題、摘要節錄(~100 字)、儲存日期、「開啟連結」(uri action)、
「🗑 刪除」(postback `action=delete_bookmark&id=<doc_id>`)。

## 元件劃分

- `services/bookmark_service.py`:`BookmarkService`(save_candidate / confirm_save /
  save_direct / list_saved / search / delete / cleanup_stale_candidates),
  store 由建構子注入,單元測試用 FakeStore。
- Flex bubble 組裝為獨立純函式(可單測)。
- `main.py`:指令攔截三條 + postback 兩個分支,邏輯全部委給 service。

## 錯誤處理

- 爬取/摘要失敗:回覆現有 FriendlyErrorMessage 風格的中文錯誤,不寫入資料。
- Firestore 不可用(store 降級):指令回覆「書籤功能暫時無法使用」。
- `/search` 無結果、`/list` 空庫:回覆引導文字訊息(非 carousel)。

## 測試

- BookmarkService 全流程單元測試(FakeStore):候選→確認、直存、去重、
  list 排序與上限、search 比對、刪除、過期候選清理。
- Flex builder:結構欄位、postback data 格式與長度上限。
- prompt 擴充:回傳 JSON 含 title/summary_analysis 欄位的解析與 fallback。

## 範圍外(v1 不做)

bookmark-makerserver 整合、分頁、標籤分類、全文檢索。
