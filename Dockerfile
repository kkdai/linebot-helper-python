FROM python:3.10.12

# 安裝 Node.js, npm, git 和 Chromium
RUN apt-get update && apt-get install -y nodejs npm git chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安裝 single-file-cli
RUN npm install -g single-file-cli

# 將專案複製到容器中
COPY . /app
# 設置工作目錄
WORKDIR /app

# 安裝必要的套件
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 設置環境變量
ENV PORT 8080

CMD uvicorn main:app --host=0.0.0.0 --port=$PORT