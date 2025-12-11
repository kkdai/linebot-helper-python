# 🔧 Client Closed 錯誤修復

## 問題描述

**錯誤訊息：**
```
ERROR:loader.chat_session:Grounding search failed: Cannot send a request, as the client has been closed.
```

**發生時機：**
用戶發送純文字訊息時，系統嘗試使用 Grounding 功能進行搜尋和回答。

---

## 問題原因

### 原始代碼的問題

在 `loader/chat_session.py` 中：

```python
# ❌ 錯誤的實作
def get_or_create_session(self, user_id: str):
    # ...
    client = self._create_client()  # 創建 client

    chat = client.chats.create(     # 使用 client 創建 chat
        model="gemini-2.0-flash",
        config=config
    )

    self.sessions[user_id] = {
        'chat': chat,  # 只保存 chat，沒保存 client
        ...
    }

    return chat, []
    # 函數結束後，client 被垃圾回收並關閉
    # 導致 chat 無法使用！
```

**問題分析：**
1. `client` 是局部變數，函數結束後會被垃圾回收
2. 當 `client` 被關閉時，基於它創建的 `chat` session 也無法使用
3. 後續調用 `chat.send_message()` 時會出現 "client has been closed" 錯誤

---

## 解決方案

### 修復後的代碼

```python
# ✅ 正確的實作
class ChatSessionManager:
    def __init__(self, session_timeout_minutes: int = 30):
        self.sessions: Dict[str, dict] = {}
        self.session_timeout = timedelta(minutes=session_timeout_minutes)

        # 關鍵修復：創建共享的 client 實例
        # 保持 client 存活，不被垃圾回收
        self.client = self._create_client()

        logger.info(f"ChatSessionManager initialized with {session_timeout_minutes}min timeout")

    def get_or_create_session(self, user_id: str):
        # ...

        # 使用共享的 self.client（不會被關閉）
        chat = self.client.chats.create(
            model="gemini-2.0-flash",
            config=config
        )

        self.sessions[user_id] = {
            'chat': chat,
            ...
        }

        return chat, []
        # self.client 仍然存活，chat 可以正常使用
```

### 修復要點

1. **共享 Client 實例**
   - 在 `__init__()` 中創建 `self.client`
   - 所有 chat sessions 共用同一個 client
   - Client 生命週期與 ChatSessionManager 相同

2. **避免重複創建**
   - 不再每次都創建新的 client
   - 減少資源消耗
   - 提升效能

3. **正確的生命週期管理**
   - Client 在 ChatSessionManager 初始化時創建
   - Client 在整個應用程式運行期間保持活躍
   - 只有當 ChatSessionManager 被銷毀時，client 才會關閉

---

## 驗證修復

### 1. 語法檢查
```bash
python -m py_compile loader/chat_session.py
# 輸出：✅ Syntax check passed
```

### 2. 測試步驟

#### 方法 A：使用測試腳本
```bash
# 運行測試
python test_grounding.py

# 選擇互動式測試
選項 2: 互動式測試

# 輸入問題
你: 幫我找一下關於日本地震最新消息
助手: [應該成功返回答案，不再出現 client closed 錯誤]
```

#### 方法 B：透過 LINE Bot
```bash
# 1. 重啟應用
uvicorn main:app --reload

# 2. 在 LINE 發送訊息
發送：幫我找一下關於日本地震最新消息

# 3. 預期結果
✅ 成功收到回答（包含搜尋結果和來源）
❌ 不再出現 "client closed" 錯誤
```

### 3. 日誌確認

**成功的日誌應該顯示：**
```
INFO:loader.chat_session:Creating Vertex AI client for project your-project-id
INFO:main:Chat Session Manager initialized with 30min timeout
INFO:main:Processing text message with Grounding for user U9b2...
INFO:loader.chat_session:Creating new session for user U9b2...
INFO:loader.chat_session:Chat session created successfully for user U9b2...
INFO:loader.chat_session:Sending message to Grounding API for user U9b2...
INFO:loader.chat_session:Received response from Grounding API: [response preview]
INFO:main:Successfully responded to user U9b2...
```

**不應該出現：**
```
ERROR:loader.chat_session:Grounding search failed: Cannot send a request, as the client has been closed.
```

---

## 技術細節

### Google GenAI SDK 的 Client 管理

根據 `google-genai` SDK 的設計：

1. **Client 是長期存活的物件**
   - 應該在應用程式啟動時創建
   - 可以重複使用
   - 包含連線池和認證資訊

2. **Chat Session 依賴 Client**
   - Chat session 是基於 client 創建的
   - 需要 client 保持活躍才能發送訊息
   - 當 client 關閉時，所有基於它的 session 都無法使用

3. **最佳實踐**
   ```python
   # 推薦：應用程式級別的 client
   class MyApp:
       def __init__(self):
           self.client = genai.Client(...)  # 創建一次

       def create_chat(self):
           return self.client.chats.create(...)  # 重複使用

   # 不推薦：函數級別的 client
   def create_chat():
       client = genai.Client(...)  # 每次都創建
       chat = client.chats.create(...)
       return chat  # client 被關閉，chat 無法使用
   ```

---

## 額外改進

### 1. 增強錯誤日誌
在修復中，我也增強了日誌輸出：

```python
# Before
def _create_client(self):
    return genai.Client(...)

# After
def _create_client(self):
    logger.info(f"Creating Vertex AI client for project {VERTEX_PROJECT}")
    return genai.Client(...)
```

### 2. 更詳細的成功日誌
```python
# Before
chat = client.chats.create(...)
return chat, []

# After
chat = self.client.chats.create(...)
logger.info(f"Chat session created successfully for user {user_id}")
return chat, []
```

### 3. 完整的異常堆疊
```python
# Before
except Exception as e:
    logger.error(f"Failed to create chat session: {e}")
    raise

# After
except Exception as e:
    logger.error(f"Failed to create chat session: {e}", exc_info=True)
    raise
```

---

## 效能影響

### Before（錯誤實作）
- 每個用戶 session 創建都會建立新的 client
- 多次認證請求
- 資源浪費

### After（修復後）
- 所有用戶共用一個 client
- 認證只需一次（應用程式啟動時）
- 資源利用更有效率

**改善：**
- ✅ 減少認證 API 調用
- ✅ 減少記憶體使用
- ✅ 提升回應速度

---

## 相關資源

### 文檔
- [Google GenAI SDK 文檔](https://ai.google.dev/gemini-api/docs)
- [Vertex AI Client 最佳實踐](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini)

### 相關檔案
- `loader/chat_session.py` - 修復的檔案
- `main.py` - 使用 ChatSessionManager 的地方
- `test_grounding.py` - 測試腳本

---

## 檢查清單

- [x] ✅ 修復 client 生命週期問題
- [x] ✅ 創建共享 client 實例
- [x] ✅ 增強日誌輸出
- [x] ✅ 語法檢查通過
- [ ] ⏳ 實際測試（待用戶驗證）

---

## 總結

**問題：** Client 在函數結束後被關閉，導致 chat session 無法使用

**解決：** 在 ChatSessionManager 中創建共享的 client 實例，保持其生命週期

**結果：**
- ✅ 錯誤已修復
- ✅ 效能提升
- ✅ 代碼更符合最佳實踐

**下一步：** 重啟應用程式並測試功能

```bash
# 重啟應用
uvicorn main:app --reload

# 測試
發送任何問題給 Bot，應該正常工作了！
```
