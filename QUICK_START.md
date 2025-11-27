# 快速開始指南 🚀

LINE Bot 新功能使用指南

---

## 📦 安裝

```bash
# 安裝所有依賴
pip install -r requirements.txt

# 啟動應用
uvicorn main:app --reload
```

---

## 🎯 新功能速覽

### 1. 智能摘要長度 📏

**三種摘要模式，隨心選擇：**

| 指令 | 效果 | 適合情境 |
|------|------|----------|
| `URL` | 標準摘要 | 日常使用 |
| `URL [短]` | 簡短摘要（1-3 點） | 快速瀏覽 |
| `URL [詳]` | 詳細摘要（完整分析） | 深入了解 |

**範例：**
```
# 快速瀏覽
https://techcrunch.com/article [短]

# 深入閱讀
https://arxiv.org/paper [詳]
```

---

### 2. 書籤系統 📚

**儲存喜歡的文章，隨時找回：**

#### 💾 儲存書籤
```
https://example.com 🔖
```
Bot 會自動儲存 URL、標題和摘要

#### 📖 查看所有書籤
```
/bookmarks
```
或
```
/書籤
```
顯示最近 10 筆書籤

#### 🔍 搜尋書籤
```
/search Python
```
或
```
/搜尋 AI
```
搜尋所有包含關鍵字的書籤

#### 🎯 組合使用
```
https://example.com [詳] 🔖
```
使用詳細模式並儲存為書籤

---

### 3. 更好的錯誤處理 🛡️

**不再看到難懂的技術錯誤！**

以前：
```
HTTPStatusError: 403 Forbidden
```

現在：
```
❌ 抱歉，無法存取這個網站（被拒絕存取）。

可能原因：網站有防爬蟲保護，請稍後再試。
```

**自動重試：**
- 網路錯誤自動重試 3 次
- 多種備用方案（Firecrawl → SingleFile → httpx）
- 大幅提升成功率

---

## 📱 完整指令列表

| 指令 | 功能 | 範例 |
|------|------|------|
| `URL` | 文章摘要 | `https://example.com` |
| `URL [短]` | 簡短摘要 | `https://example.com [短]` |
| `URL [詳]` | 詳細摘要 | `https://example.com [詳]` |
| `URL 🔖` | 儲存書籤 | `https://example.com 🔖` |
| `/bookmarks` | 查看書籤 | `/bookmarks` |
| `/search` | 搜尋書籤 | `/search AI` |
| `@g` | GitHub 摘要 | `@g` |
| `圖片` | 圖片分析 | 直接發送圖片 |
| `文字` | 網路搜尋 | 任何文字訊息 |

---

## 🎨 使用場景

### 場景 1：快速瀏覽新聞
```
1. 發送：https://news.ycombinator.com/item?id=123 [短]
2. 獲得：3 個關鍵重點
3. 決定是否深入閱讀
```

### 場景 2：深入學習技術文章
```
1. 發送：https://arxiv.org/paper [詳]
2. 獲得：完整的背景、方法、結論分析
3. 發送：同樣的 URL 加上 🔖 儲存起來
```

### 場景 3：建立個人知識庫
```
1. 每天閱讀文章時加上 🔖 儲存
2. 定期使用 /bookmarks 回顧
3. 用 /search 快速找到相關內容
```

### 場景 4：處理失敗的網站
```
1. 發送有問題的 URL
2. Bot 自動嘗試多種方法
3. 如果全部失敗，給出清楚的錯誤原因
```

---

## 🔧 API 使用

### 建立書籤（程式化）
```bash
curl -X POST http://localhost:8000/bookmarks/create \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "USER_LINE_ID",
    "url": "https://example.com",
    "title": "Example Title",
    "summary": "This is a summary",
    "tags": "tech,ai"
  }'
```

### 查詢書籤
```bash
curl http://localhost:8000/bookmarks/list/USER_LINE_ID?limit=10
```

### 搜尋書籤
```bash
curl "http://localhost:8000/bookmarks/search/USER_LINE_ID?q=Python&limit=5"
```

---

## 💡 最佳實踐

### 1. 選擇合適的摘要模式
- 📰 新聞 → 短摘要
- 📝 部落格 → 標準摘要
- 📚 論文/長文 → 詳細摘要

### 2. 善用書籤功能
- 🌟 重要文章加上 🔖
- 🏷️ 定期整理書籤
- 🔍 使用標籤分類

### 3. 組合使用
```
# 快速瀏覽 + 儲存重要的
https://important-article.com [短] 🔖

# 深入閱讀 + 儲存
https://research-paper.com [詳] 🔖
```

---

## ⚠️ 注意事項

### 摘要模式
- 支援格式：`[短]`、`[詳]`、`(short)`、`(detailed)`
- 不區分大小寫
- 可放在 URL 前後

### 書籤
- 每個用戶的書籤獨立儲存
- 搜尋支援標題、摘要、標籤、URL
- 預設顯示最近 10 筆

### 錯誤處理
- 自動重試 3 次
- 多種備用方案
- 友好的中文錯誤訊息

---

## 🐛 常見問題

### Q: 為什麼有些網站無法摘要？
A: Bot 會嘗試多種方法，如果全部失敗會給出具體原因。常見原因：
- 網站有防爬蟲保護
- 內容需要登入
- 網站暫時無法連線

### Q: 書籤會永久儲存嗎？
A: 是的，儲存在 SQLite 資料庫中。建議定期備份 `linebot_bookmarks.db` 檔案。

### Q: 可以刪除書籤嗎？
A: 目前通過 API 支援刪除功能：
```bash
curl -X DELETE http://localhost:8000/bookmarks/delete/BOOKMARK_ID \
  -H "Content-Type: application/json" \
  -d '{"user_id": "USER_LINE_ID"}'
```

### Q: 摘要模式可以設定預設值嗎？
A: 目前預設為標準模式，未來版本會支援用戶偏好設定。

---

## 📞 需要幫助？

- 📖 完整文件：`IMPROVEMENTS.md`
- 🐛 回報問題：GitHub Issues
- 💬 使用說明：直接問 Bot `/help`（即將推出）

---

## 🎉 開始使用

1. 發送任何 URL 給 Bot
2. 嘗試不同的摘要模式
3. 儲存喜歡的文章
4. 建立你的知識庫！

**祝使用愉快！** 🚀
