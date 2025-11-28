# 部署檢查清單 ✅

## 🔍 檢查結果摘要

**日期：** 2025-11-27
**狀態：** ✅ 準備就緒

---

## ✅ 已完成檢查

### 1. Python 語法檢查
- ✅ `main.py` - 無語法錯誤
- ✅ `database.py` - 無語法錯誤
- ✅ `loader/error_handler.py` - 無語法錯誤
- ✅ `loader/text_utils.py` - 無語法錯誤
- ✅ `loader/langtools.py` - 無語法錯誤
- ✅ 所有其他 loader 文件 - 無語法錯誤

### 2. 文件完整性
- ✅ `requirements.txt` - 包含所有新依賴
- ✅ `Dockerfile` - 配置正確
- ✅ `cloudbuild.yaml` - 配置正確
- ✅ `README.md` - 已更新至 v2.0

### 3. 文件檔案
- ✅ `IMPROVEMENTS.md` - 技術文件完整
- ✅ `QUICK_START.md` - 使用指南完整
- ✅ `DEPLOYMENT_CHECKLIST.md` - 本檔案

---

## 📋 部署前需要執行的步驟

### 步驟 1: 安裝新的依賴

**⚠️ 重要：使用鎖定版本避免兼容性問題**

```bash
# 推薦：使用鎖定版本（生產環境）
pip install -r requirements-lock.txt

# 或：使用版本約束（開發環境）
pip install -r requirements.txt
```

**新增的依賴：**
- `tenacity` - 重試機制
- `sqlalchemy` - ORM 框架
- `aiosqlite` - 非同步 SQLite
- `pydantic` - 資料驗證（明確版本）

**版本說明：**
- 使用 `requirements-lock.txt` 確保可重現的構建
- 使用 `requirements.txt` 允許小版本更新
- 詳見 `DEPENDENCIES_FIX.md`

### 步驟 2: 測試本地環境

```bash
# 啟動應用
uvicorn main:app --reload

# 測試基本功能
# 1. 發送 URL 測試摘要功能
# 2. 發送 "https://example.com 🔖" 測試書籤
# 3. 發送 "/bookmarks" 查看書籤列表
```

### 步驟 3: 檢查環境變數

確保以下環境變數已設定：

**必須的：**
- `ChannelSecret`
- `ChannelAccessToken`
- `LINE_USER_ID`
- `ChannelAccessTokenHF`
- `GOOGLE_API_KEY`

**可選的：**
- `firecrawl_key`
- `SEARCH_API_KEY`
- `SEARCH_ENGINE_ID`
- `DATABASE_URL` (預設: `sqlite+aiosqlite:///./linebot_bookmarks.db`)

### 步驟 4: 資料庫初始化

資料庫會在應用啟動時自動初始化，無需手動操作。

**檢查資料庫：**
```bash
# 啟動後應該會看到這個檔案
ls -la linebot_bookmarks.db

# 檢查資料庫結構
sqlite3 linebot_bookmarks.db ".schema"
```

---

## 🐳 Docker 部署

### 本地測試 Docker 構建

```bash
# 構建映像
docker build -t linebot-helper .

# 執行容器（需要環境變數）
docker run -p 8080:8080 \
  -e ChannelSecret="your_secret" \
  -e ChannelAccessToken="your_token" \
  -e LINE_USER_ID="your_user_id" \
  -e ChannelAccessTokenHF="your_hf_token" \
  -e GOOGLE_API_KEY="your_gemini_key" \
  linebot-helper

# 測試
curl http://localhost:8080/
```

### Google Cloud Platform 部署

```bash
# 使用 Cloud Build 部署
gcloud builds submit --config cloudbuild.yaml

# 或使用 App Engine
gcloud app deploy
```

---

## 🧪 測試指令

### 1. 測試摘要模式

```bash
# 在 LINE Bot 中發送：
https://news.ycombinator.com [短]
https://techcrunch.com/article [詳]
https://example.com
```

### 2. 測試書籤系統

```bash
# 儲存書籤
https://example.com 🔖

# 查看書籤
/bookmarks

# 搜尋書籤
/search Python
```

### 3. 測試錯誤處理

```bash
# 發送無效 URL（應該看到友好的錯誤訊息）
https://invalid-url-test-12345.com

# 發送被封鎖的網站（應該自動嘗試多種方法）
https://some-blocked-site.com
```

### 4. 測試 API

```bash
# 建立書籤
curl -X POST http://localhost:8080/bookmarks/create \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "url": "https://example.com",
    "title": "Test Bookmark",
    "summary": "This is a test"
  }'

# 查詢書籤
curl http://localhost:8080/bookmarks/list/test_user

# 搜尋書籤
curl "http://localhost:8080/bookmarks/search/test_user?q=test"
```

---

## ⚠️ 注意事項

### 資料庫備份

**重要：** SQLite 資料庫包含所有用戶的書籤資料。

```bash
# 建議每天備份
cp linebot_bookmarks.db linebot_bookmarks_$(date +%Y%m%d).db

# 或使用 cron job
0 2 * * * cp /path/to/linebot_bookmarks.db /path/to/backup/linebot_bookmarks_$(date +\%Y\%m\%d).db
```

### 生產環境建議

1. **使用 PostgreSQL 取代 SQLite**（高並發環境）
   ```bash
   # 設定環境變數
   export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname"
   ```

2. **設定日誌監控**
   - 整合 Sentry 或類似服務
   - 監控錯誤率和 API 配額

3. **效能監控**
   - 追蹤 Gemini API 使用量
   - 監控資料庫大小
   - 設定警報閾值

---

## 📊 驗收測試清單

在生產環境部署前，確保以下測試通過：

- [ ] 基本 URL 摘要功能正常
- [ ] 三種摘要模式（短/標準/詳細）正常運作
- [ ] 書籤儲存功能正常
- [ ] 書籤查詢功能正常
- [ ] 書籤搜尋功能正常
- [ ] 錯誤訊息顯示為友好的中文
- [ ] 無效 URL 能正確處理
- [ ] 圖片分析功能正常
- [ ] Web 搜尋功能正常
- [ ] GitHub 摘要功能正常
- [ ] N8N workflow 正常執行（如果使用）
- [ ] 資料庫正確初始化
- [ ] 所有 API endpoints 回應正常

---

## 🐛 已知問題

目前沒有已知的重大問題。

---

## 🔄 回滾計劃

如果部署後發現問題：

1. **資料庫**：書籤資料獨立儲存，不影響舊功能
2. **新功能**：可以選擇性停用書籤系統
3. **版本回滾**：保留舊版本的 Git commit

```bash
# 如需回滾到舊版本
git checkout <previous_commit_hash>
gcloud app deploy
```

---

## ✅ 最終確認

部署前最後檢查：

- [ ] 已在本地測試所有功能
- [ ] 已安裝所有新依賴
- [ ] 環境變數已正確設定
- [ ] 資料庫備份計劃已建立
- [ ] 文件已更新並提交
- [ ] 團隊成員已了解新功能

**準備就緒？開始部署！** 🚀

---

## 📞 支援

如有問題：
1. 查看 [IMPROVEMENTS.md](IMPROVEMENTS.md) 技術文件
2. 查看 [QUICK_START.md](QUICK_START.md) 使用指南
3. 檢查應用日誌
4. 提交 GitHub Issue

**部署成功後，記得更新此清單！**
