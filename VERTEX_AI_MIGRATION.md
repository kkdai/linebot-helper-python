# Vertex AI 遷移指南

## ✅ 已完成的變更

本專案已全面從 Gemini API (API key) 遷移至 Google Vertex AI，以獲得更高的配額和更穩定的服務。

### 修改的檔案

1. **loader/langtools.py** - 文字摘要和圖片分析
   - `ChatGoogleGenerativeAI` → `ChatVertexAI`
   - 使用 LangChain 的 Vertex AI 整合

2. **loader/searchtool.py** - 搜尋關鍵字提取
   - `google.generativeai` → `google.genai.Client(vertexai=True)`
   - 使用新的 google-genai SDK

3. **loader/gh_tools.py** - GitHub Issues 摘要
   - `ChatGoogleGenerativeAI` → `ChatVertexAI`

4. **loader/youtube_gcp.py** - YouTube 影片摘要
   - HTTP API 呼叫 → `google.genai.Client(vertexai=True)`

5. **loader/maps_grounding.py** - 地圖搜尋（已使用 Vertex AI）
   - 無需修改

6. **main.py** - 主程式
   - 移除 `google.generativeai` import 和 configure
   - 環境變數從 `GOOGLE_API_KEY` 改為 `GOOGLE_CLOUD_PROJECT`

7. **requirements.txt** - 依賴套件
   - 新增 `langchain-google-vertexai>=2.0.0`
   - 移除 `langchain_google_genai` 和 `google-generativeai`

8. **README.md** - 文檔更新
   - 更新環境變數說明
   - 新增 Vertex AI 設定步驟

## 🚀 設定步驟

### 1. 安裝新的依賴套件

```bash
# 安裝更新後的依賴
pip install -r requirements.txt

# 或使用鎖定版本（需要先重新生成）
pip freeze > requirements-lock.txt
```

### 2. 設定環境變數

更新你的 `.env` 檔案或環境變數：

```bash
# 必要 - Vertex AI 配置
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"  # 可選，預設為 us-central1

# 不再需要（可以移除）
# GOOGLE_API_KEY="..."  # ❌ 已不再使用
```

### 3. 設定 Google Cloud 認證

選擇以下其中一種方式：

**方式 A: Application Default Credentials (推薦)**
```bash
gcloud auth application-default login
```

**方式 B: Service Account**
```bash
# 下載 service account key JSON 檔案
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

### 4. 啟用 Vertex AI API

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 選擇你的專案
3. 啟用 "Vertex AI API"
4. （可選）檢查並設定配額限制

## 🧪 測試步驟

### 測試 1: 文字摘要功能
```bash
# 啟動應用程式
uvicorn main:app --reload

# 在 LINE Bot 傳送一個 URL 測試摘要功能
# 例如：https://example.com
```

### 測試 2: 圖片分析功能
```bash
# 在 LINE Bot 傳送一張圖片
# 系統應該回覆圖片的描述（繁體中文）
```

### 測試 3: 搜尋功能
```bash
# 在 LINE Bot 傳送一段文字（非 URL）
# 系統應該提取關鍵字並返回搜尋結果
```

### 測試 4: YouTube 摘要
```bash
# 在 LINE Bot 傳送一個 YouTube URL
# 例如：https://www.youtube.com/watch?v=xxxxx
```

### 測試 5: 地圖搜尋
```bash
# 在 LINE 傳送位置訊息
# 選擇「餐廳」、「加油站」或「停車場」
```

## 📊 Vertex AI vs Gemini API 比較

| 項目 | Gemini API (舊) | Vertex AI (新) |
|------|----------------|---------------|
| 認證方式 | API Key | OAuth2 / Service Account |
| RPM 限制 | 15 次/分鐘 | 300-2000 次/分鐘 |
| TPM 限制 | 1M tokens/分鐘 | 4M tokens/分鐘 |
| 費用 | 免費層級有限 | 按使用量計費 |
| 配額彈性 | 固定 | 可申請提升 |
| 企業支援 | 無 | 有 SLA |

## ⚠️ 注意事項

1. **費用**: Vertex AI 是付費服務，請監控使用量
   - 檢查價格：https://cloud.google.com/vertex-ai/pricing
   - 設定預算提醒：https://cloud.google.com/billing/docs/how-to/budgets

2. **區域選擇**:
   - 大部分功能：`us-central1` 或 `asia-east1`
   - Maps Grounding：建議使用 `global`

3. **配額監控**:
   ```bash
   # 查看目前配額使用狀況
   gcloud services quota list --service=aiplatform.googleapis.com
   ```

4. **相容性**:
   - 舊的 `GOOGLE_API_KEY` 環境變數已不再使用
   - 請確保移除或註解掉相關設定

## 🐛 疑難排解

### 錯誤 1: "GOOGLE_CLOUD_PROJECT not set"
```bash
# 確認環境變數已設定
echo $GOOGLE_CLOUD_PROJECT

# 如果為空，請設定
export GOOGLE_CLOUD_PROJECT="your-project-id"
```

### 錯誤 2: "google-genai package not available"
```bash
# 重新安裝依賴
pip install google-genai>=1.0.0
```

### 錯誤 3: "Permission denied" 或認證錯誤
```bash
# 重新認證
gcloud auth application-default login

# 確認專案設定
gcloud config set project your-project-id
```

### 錯誤 4: 429 Rate Limit (仍然發生)
```bash
# 檢查配額設定
gcloud services quota list --service=aiplatform.googleapis.com

# 申請提升配額
# https://cloud.google.com/vertex-ai/docs/quotas
```

## 📝 回滾步驟（如需）

如果需要回到使用 Gemini API:

```bash
# 1. 切換到 commit 前的版本
git log --oneline  # 找到遷移前的 commit
git checkout <commit-hash>

# 2. 或手動修改
# - 在 requirements.txt 加回 langchain_google_genai 和 google-generativeai
# - 在各檔案中將 ChatVertexAI 改回 ChatGoogleGenerativeAI
# - 在 main.py 加回 genai.configure(api_key=...)
```

## 🎉 完成！

遷移完成後，你應該能夠：
- ✅ 享受更高的 API 配額（300-2000 RPM vs 15 RPM）
- ✅ 更穩定的服務品質
- ✅ 企業級的支援和 SLA
- ✅ 更好的成本管理和監控

如有問題，請查看：
- [Vertex AI 文檔](https://cloud.google.com/vertex-ai/docs)
- [Google GenAI SDK](https://github.com/googleapis/python-genai)
- [LangChain Vertex AI](https://python.langchain.com/docs/integrations/llms/google_vertex_ai_palm)
