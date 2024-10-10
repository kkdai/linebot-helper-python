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

# 2個 worker，以充分利用 2vCPU, 避免长时间的请求阻塞。可以使用 --timeout 30. 设置适当的线程数。可以从 4 开始
CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 --timeout 30 main:app