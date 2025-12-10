# Docker 部署指南（Vertex AI 版本）

## 🚨 重要變更

此應用程式已從 Gemini API 遷移至 **Vertex AI**，Docker 部署時需要額外設定 Google Cloud 認證。

---

## 📦 本地 Docker 測試

### 1. 設定環境變數

建立 `.env` 檔案：

```bash
# LINE Bot 設定
ChannelSecret=your_channel_secret
ChannelAccessToken=your_channel_access_token
LINE_USER_ID=your_line_user_id
ChannelAccessTokenHF=your_hf_token

# Vertex AI 設定（必要）
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# 可選設定
SEARCH_API_KEY=your_search_api_key
SEARCH_ENGINE_ID=your_search_engine_id
firecrawl_key=your_firecrawl_key
```

### 2. 準備 Google Cloud 認證

**選項 A: 使用 Service Account Key**

```bash
# 1. 下載 service account key JSON
# 2. 放在專案根目錄，命名為 service-account-key.json
# 3. 確保 .dockerignore 中有排除此檔案（安全考量）
```

**選項 B: 使用 Application Default Credentials**

```bash
# 本機開發時使用
gcloud auth application-default login
```

### 3. Build Docker Image

```bash
# Build image
docker build -t linebot-helper .

# 確認 image 建立成功
docker images | grep linebot-helper
```

### 4. 執行 Docker Container

**使用 Service Account Key:**

```bash
docker run -d \
  --name linebot-app \
  -p 8080:8080 \
  --env-file .env \
  -v $(pwd)/service-account-key.json:/app/service-account-key.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/app/service-account-key.json \
  linebot-helper
```

**使用本機 ADC (僅限開發):**

```bash
docker run -d \
  --name linebot-app \
  -p 8080:8080 \
  --env-file .env \
  -v ~/.config/gcloud:/root/.config/gcloud:ro \
  linebot-helper
```

### 5. 檢查 Logs

```bash
# 即時查看 logs
docker logs -f linebot-app

# 檢查錯誤
docker logs linebot-app 2>&1 | grep -i error
```

### 6. 測試

```bash
# 測試健康檢查端點
curl http://localhost:8080/

# 從 LINE 傳送訊息測試
```

---

## ☁️ 部署到 Google Cloud Run

### 方式 1: 使用 Cloud Build + Artifact Registry

```bash
# 1. 設定專案
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export SERVICE_NAME=linebot-helper

# 2. 啟用必要的 API
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com

# 3. 建立 Artifact Registry repository
gcloud artifacts repositories create linebot-repo \
  --repository-format=docker \
  --location=$REGION

# 4. Build and push image
gcloud builds submit \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/linebot-repo/$SERVICE_NAME

# 5. Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/linebot-repo/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
  --set-env-vars "GOOGLE_CLOUD_LOCATION=$REGION" \
  --set-env-vars "ChannelSecret=your_secret" \
  --set-env-vars "ChannelAccessToken=your_token" \
  --set-env-vars "LINE_USER_ID=your_user_id" \
  --set-env-vars "ChannelAccessTokenHF=your_hf_token"
```

### 方式 2: 使用 Secret Manager (推薦)

```bash
# 1. 建立 secrets
echo -n "your_channel_secret" | \
  gcloud secrets create channel-secret --data-file=-

echo -n "your_channel_access_token" | \
  gcloud secrets create channel-access-token --data-file=-

# 2. Deploy with secrets
gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/linebot-repo/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
  --set-env-vars "GOOGLE_CLOUD_LOCATION=$REGION" \
  --set-secrets="ChannelSecret=channel-secret:latest" \
  --set-secrets="ChannelAccessToken=channel-access-token:latest"
```

---

## 🔐 認證說明

### Vertex AI 認證方式

Cloud Run 部署時，**不需要** service account key 檔案。Cloud Run 會自動使用：

1. **預設 Service Account**: `[PROJECT_NUMBER]-compute@developer.gserviceaccount.com`
2. **自動授權**: Cloud Run 自動有權限呼叫 Vertex AI

如果需要自訂權限：

```bash
# 建立 service account
gcloud iam service-accounts create linebot-sa \
  --display-name="LINE Bot Service Account"

# 授予 Vertex AI 權限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:linebot-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Deploy 時指定 service account
gcloud run deploy $SERVICE_NAME \
  --service-account=linebot-sa@$PROJECT_ID.iam.gserviceaccount.com \
  ...
```

---

## 🐛 常見問題

### 問題 1: ModuleNotFoundError: No module named 'langchain_google_vertexai'

**原因**: requirements-lock.txt 未更新

**解決**:
```bash
# 確認 requirements-lock.txt 包含
langchain-google-vertexai==2.0.11
```

### 問題 2: 認證失敗

**錯誤訊息**: `Could not automatically determine credentials`

**解決**:
```bash
# 本機開發
gcloud auth application-default login

# Docker 部署
# 確保掛載 service account key 或 gcloud config
```

### 問題 3: Vertex AI API 未啟用

**錯誤訊息**: `API has not been used in project`

**解決**:
```bash
gcloud services enable aiplatform.googleapis.com
```

### 問題 4: 配額超限（雖然使用 Vertex AI）

**原因**: 區域配額限制

**解決**:
```bash
# 切換到不同區域
export GOOGLE_CLOUD_LOCATION=asia-east1

# 或申請提升配額
# https://cloud.google.com/vertex-ai/docs/quotas
```

---

## 📊 監控和 Logs

### Cloud Run Logs

```bash
# 查看即時 logs
gcloud run services logs read $SERVICE_NAME \
  --region=$REGION \
  --limit=50 \
  --format="table(timestamp,textPayload)"

# 查看錯誤 logs
gcloud run services logs read $SERVICE_NAME \
  --region=$REGION \
  --log-filter="severity>=ERROR"
```

### 監控 Vertex AI 使用量

```bash
# 前往 Cloud Console
# https://console.cloud.google.com/vertex-ai/online-prediction/usage
```

---

## 🔧 開發 Tips

### 快速重建和部署

建立 `deploy.sh`:

```bash
#!/bin/bash
set -e

PROJECT_ID="your-project-id"
REGION="us-central1"
SERVICE_NAME="linebot-helper"

echo "🔨 Building image..."
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT_ID/linebot-repo/$SERVICE_NAME

echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/linebot-repo/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated

echo "✅ Deployment complete!"
```

使用:
```bash
chmod +x deploy.sh
./deploy.sh
```

---

## 💰 成本估算

### Cloud Run 定價（約略）
- **免費額度**: 每月 2M requests, 360K GB-seconds
- **付費**:
  - Requests: $0.40 per 1M requests
  - Memory: $0.0000025 per GB-second
  - CPU: $0.00002400 per vCPU-second

### Vertex AI 定價（Gemini models）
- **gemini-2.0-flash-lite**:
  - Input: ~$0.075 per 1M tokens
  - Output: ~$0.30 per 1M tokens
- **gemini-2.0-flash**:
  - Input: ~$0.15 per 1M tokens
  - Output: ~$0.60 per 1M tokens

參考: https://cloud.google.com/vertex-ai/pricing

---

## ✅ 部署檢查清單

- [ ] 更新 `requirements-lock.txt` (包含 langchain-google-vertexai)
- [ ] 設定環境變數 (GOOGLE_CLOUD_PROJECT)
- [ ] 啟用 Vertex AI API
- [ ] 設定 Google Cloud 認證
- [ ] Build Docker image 成功
- [ ] 本機測試通過
- [ ] Deploy to Cloud Run
- [ ] 設定 LINE Webhook URL
- [ ] 測試所有功能
- [ ] 設定監控和告警
- [ ] 檢查成本預算

---

完成！🎉
