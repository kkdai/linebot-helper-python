#!/bin/bash
# Docker Build 測試腳本

set -e  # 遇到錯誤就停止

echo "🔍 檢查 requirements-lock.txt..."
if grep -q "langchain-google-vertexai" requirements-lock.txt; then
    echo "✅ langchain-google-vertexai 已在 requirements-lock.txt 中"
else
    echo "❌ 錯誤：langchain-google-vertexai 不在 requirements-lock.txt 中"
    exit 1
fi

if grep -q "langchain_google_genai" requirements-lock.txt; then
    echo "❌ 錯誤：舊的 langchain_google_genai 仍在 requirements-lock.txt 中"
    exit 1
else
    echo "✅ 舊的 langchain_google_genai 已移除"
fi

echo ""
echo "🔨 開始 Docker Build..."
docker build -t linebot-helper-test . 2>&1 | tee docker-build.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo ""
    echo "✅ Docker Build 成功！"
    echo ""
    echo "📦 Image 資訊："
    docker images linebot-helper-test
    echo ""
    echo "💡 下一步："
    echo "1. 準備 .env 檔案"
    echo "2. 執行: docker run --env-file .env -p 8080:8080 linebot-helper-test"
    echo ""
    echo "📚 詳細部署指南請參考: DOCKER_DEPLOYMENT.md"
else
    echo ""
    echo "❌ Docker Build 失敗"
    echo "查看詳細錯誤: cat docker-build.log"
    exit 1
fi
