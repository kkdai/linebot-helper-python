# 使用具體的 tag 而不是 latest
FROM python:3.10.12-slim

# 設定 WORKDIR 早一點，這樣後續命令的工作目錄都會一致
WORKDIR /app

# 設定環境變數
ENV PORT=8080 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 複製 requirements.txt 用於緩存 Python 依賴
COPY requirements.txt .

# 安裝系統依賴和 Python 依賴
# 1. 合併 RUN 命令減少層數
# 2. 清理不必要的檔案減少映像大小
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        git \
        chromium \
    && npm install -g single-file-cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 複製應用程式代碼
# 將經常變動的文件放在最後
COPY . .

# 使用 EXPOSE 聲明容器會監聽的端口
EXPOSE $PORT

# 使用 ENTRYPOINT 和 CMD 的組合
ENTRYPOINT ["uvicorn"]
CMD ["main:app", "--host=0.0.0.0", "--port=8080"]