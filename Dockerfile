# 使用具體的 tag 而不是 latest
FROM python:3.10.12-slim

# 設定 WORKDIR 早一點，這樣後續命令的工作目錄都會一致
WORKDIR /app

# 設定環境變數
ENV PORT=8080 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 複製 requirements 文件用於緩存 Python 依賴
# 使用鎖定版本確保可重現的構建
COPY requirements-lock.txt requirements.txt
COPY requirements.txt ./requirements-fallback.txt

# 安裝系統依賴和 Python 依賴
# 1. 合併 RUN 命令減少層數
# 2. 清理不必要的檔案減少映像大小
# Node.js 與 single-file-cli 版本都鎖死，避免未來 rebuild 時默默抓到不相容的新版：
# - Node.js：改用 NodeSource 24.x（Debian apt 內建的 v18 太舊），鎖精確版號。
#   single-file-cli 依賴的 ws/simple-cdp 需要全域 CloseEvent，Node 24 才有（Node 22 沒有，
#   即使開 --experimental-websocket 也一樣，實測過），這是這次 acm.org 爬取全滅的根本原因
# - single-file-cli：鎖在 2.0.83，已驗證在 Node 24 下可正常抓取
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        git \
        chromium \
        ffmpeg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs=24.19.0-1nodesource1 \
    && npm install -g single-file-cli@2.0.83 \
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