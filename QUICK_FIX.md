# 🚨 Docker Build 錯誤快速修復

## 問題
```
ModuleNotFoundError: No module named 'langchain_google_vertexai'
```

## 原因
遷移到 Vertex AI 後，`requirements-lock.txt` 未更新。

## ✅ 已修復的內容

### 1. 更新 requirements-lock.txt
```diff
- langchain_google_genai==1.0.10
- google-generativeai==0.7.2
+ langchain-google-vertexai==2.0.11
```

### 2. 新增檔案
- ✅ `.dockerignore` - 優化 Docker build
- ✅ `.env.example` - 環境變數範例
- ✅ `docker-test.sh` - 測試腳本
- ✅ `DOCKER_DEPLOYMENT.md` - 完整部署指南

## 🚀 快速測試

### 方法 1: 使用測試腳本
```bash
./docker-test.sh
```

### 方法 2: 手動測試
```bash
# 1. Build image
docker build -t linebot-helper .

# 2. 建立 .env 檔案
cp .env.example .env
# 編輯 .env，填入你的設定值

# 3. 執行 container (使用 Service Account)
docker run -d \
  --name linebot-app \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/service-account-key.json:/app/service-account-key.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/app/service-account-key.json \
  linebot-helper

# 4. 查看 logs
docker logs -f linebot-app
```

## ⚠️ 重要提醒

### Vertex AI 認證
Docker 部署時必須提供 Google Cloud 認證：

**選項 A: Service Account Key (推薦)**
```bash
# 1. 從 GCP Console 下載 service account key JSON
# 2. 放在專案目錄: service-account-key.json
# 3. 掛載到 container 並設定環境變數
```

**選項 B: Application Default Credentials (僅限本機測試)**
```bash
gcloud auth application-default login
docker run -v ~/.config/gcloud:/root/.config/gcloud:ro ...
```

### 環境變數檢查
確保 `.env` 包含：
```bash
GOOGLE_CLOUD_PROJECT=your-project-id  # 必要！
GOOGLE_CLOUD_LOCATION=us-central1      # 可選，預設值
```

## 🐛 如果仍有問題

### 檢查 1: 確認依賴正確安裝
```bash
docker run -it linebot-helper pip list | grep langchain
```
應該看到：
```
langchain-google-vertexai  2.0.11
```

### 檢查 2: 查看詳細錯誤
```bash
docker logs linebot-app 2>&1 | grep -A 10 "Error"
```

### 檢查 3: 重新 build（清除快取）
```bash
docker build --no-cache -t linebot-helper .
```

## 📚 更多資訊

- 完整部署指南: [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)
- Vertex AI 遷移: [VERTEX_AI_MIGRATION.md](VERTEX_AI_MIGRATION.md)
