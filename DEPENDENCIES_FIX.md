# Dependencies Fix Guide

## 🐛 問題描述

**錯誤訊息：**
```
ModuleNotFoundError: No module named 'langchain_core.pydantic_v1'
```

**原因：**
LangChain 生態系統的新版本（0.3.x）移除了 `pydantic_v1` 兼容層，導致與 `langchain_google_genai` 的兼容性問題。

---

## ✅ 解決方案

### 方案 1：使用鎖定版本（推薦用於生產環境）

```bash
# 移除舊的依賴
pip uninstall -y langchain langchain_core langchain-community langchain_google_genai

# 安裝鎖定版本
pip install -r requirements-lock.txt
```

**優點：**
- ✅ 經過測試的穩定版本組合
- ✅ 可重現的構建
- ✅ 避免版本衝突

---

### 方案 2：使用版本約束（開發環境）

```bash
# 安裝帶版本約束的依賴
pip install -r requirements.txt
```

**版本約束：**
- `langchain>=0.1.0,<0.3.0` - 避免 0.3.x 的破壞性更改
- `langchain_core>=0.1.0,<0.3.0`
- `langchain-community>=0.0.20,<0.3.0`
- `langchain_google_genai>=0.0.6,<2.0.0`
- `pydantic>=1.10.0,<3.0.0` - 確保 pydantic 兼容性

---

## 🐳 Docker 修復

### 更新 Dockerfile

Dockerfile 已經正確配置，會自動使用 `requirements.txt`。

如果要使用鎖定版本，修改 Dockerfile：

```dockerfile
# 將這一行
COPY requirements.txt .

# 改為
COPY requirements-lock.txt requirements.txt
```

---

## 📋 驗證安裝

### 檢查版本

```bash
pip list | grep langchain
```

**預期輸出：**
```
langchain                 0.2.16
langchain-community       0.2.16
langchain-core            0.2.38
langchain-google-genai    1.0.10
```

### 測試導入

```bash
python3 -c "
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain.chains.summarize import load_summarize_chain
print('✅ All imports successful!')
"
```

### 完整測試

```bash
# 啟動應用
uvicorn main:app --reload

# 檢查日誌中是否有錯誤
# 應該看到：
# INFO: Database initialized successfully
# INFO: Application startup complete
```

---

## 🔧 常見問題

### Q1: 為什麼有兩個 requirements 文件？

- **requirements.txt**: 開發環境使用，有版本約束但允許小版本更新
- **requirements-lock.txt**: 生產環境使用，鎖定所有版本確保穩定性

### Q2: 如果還是有錯誤怎麼辦？

```bash
# 完全清理並重新安裝
pip freeze | xargs pip uninstall -y
pip install -r requirements-lock.txt
```

### Q3: 在 Docker 中部署應該用哪個？

**生產環境推薦使用鎖定版本：**

```dockerfile
# Dockerfile
COPY requirements-lock.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
```

---

## 📦 依賴版本說明

### 核心依賴

| 套件 | 版本 | 說明 |
|------|------|------|
| langchain | 0.2.16 | 核心框架 |
| langchain_core | 0.2.38 | 核心組件 |
| langchain-community | 0.2.16 | 社區組件 |
| langchain_google_genai | 1.0.10 | Google AI 整合 |

### 為什麼選擇這些版本？

1. **langchain 0.2.x**：穩定版本，包含 `pydantic_v1` 兼容層
2. **langchain_google_genai 1.0.x**：與 langchain 0.2.x 完全兼容
3. **pydantic 2.x**：最新穩定版，向後兼容

---

## 🚀 部署檢查清單

在部署前確認：

- [ ] 移除舊版本的 langchain 套件
- [ ] 安裝正確版本的依賴
- [ ] 測試所有導入成功
- [ ] 驗證應用可以啟動
- [ ] 測試基本功能（URL 摘要、書籤等）
- [ ] 檢查無錯誤日誌

---

## 📝 更新日誌

### 2025-11-27
- ✅ 修復 langchain pydantic_v1 導入錯誤
- ✅ 創建 requirements-lock.txt 鎖定版本
- ✅ 添加版本約束到 requirements.txt
- ✅ 添加 pydantic 明確依賴

---

## 🔗 相關資源

- [LangChain 版本遷移指南](https://python.langchain.com/docs/versions/)
- [Pydantic V2 遷移](https://docs.pydantic.dev/latest/migration/)
- [Google Generative AI Python SDK](https://github.com/google/generative-ai-python)

---

## ✅ 快速修復指令

```bash
# 一鍵修復（Linux/macOS）
pip uninstall -y langchain langchain_core langchain-community langchain_google_genai && \
pip install -r requirements-lock.txt && \
python3 -c "from langchain_google_genai import ChatGoogleGenerativeAI; print('✅ Fixed!')"

# Windows PowerShell
pip uninstall -y langchain langchain_core langchain-community langchain_google_genai
pip install -r requirements-lock.txt
python -c "from langchain_google_genai import ChatGoogleGenerativeAI; print('✅ Fixed!')"
```

**問題解決後，可以開始部署！** 🎉
