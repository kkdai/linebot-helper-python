# 🔍 純文字搜尋功能改進建議

## 📊 目前實作分析

### 現有流程
```
用戶輸入純文字
    ↓
handle_text_message()
    ↓
extract_keywords_with_gemini() [如果文字 > 10 詞]
    ↓
search_with_google_custom_search()
    ↓
返回前 5 個搜尋結果（標題、連結、snippet）
    ↓
summarize_text() - 總結搜尋結果
    ↓
回傳兩則訊息：[摘要] + [原始搜尋結果]
```

### 目前的問題

#### 1. ❌ 沒有對話記憶 (Memory/Session)
```python
# main.py:284
async def handle_text_message(event: MessageEvent, user_id: str):
    msg = event.message.text  # 每次都是新的對話，無上下文
```

**問題**：
- 無法進行連續對話
- 不記得之前搜尋的內容
- 每次都要重新輸入完整問題

**範例**：
```
用戶: "Python 是什麼？"
Bot: [搜尋結果 + 摘要]

用戶: "它有什麼優點？"  ❌ Bot 不知道 "它" 指的是 Python
```

#### 2. ⚠️ 搜尋結果處理簡單
```python
# main.py:312-315
for i, result in enumerate(search_results[:5], 1):
    result_text += f"{i}. {result['title']}\n"
    result_text += f"   {result['link']}\n"
    result_text += f"   {result['snippet']}\n\n"
```

**問題**：
- 只使用搜尋結果的 snippet（通常很短）
- 沒有深入閱讀搜尋結果頁面的完整內容
- 摘要品質受限於 snippet 的質量

#### 3. ⚠️ 需要兩個 API 調用
```python
# 1. Gemini 提取關鍵字
keywords = extract_keywords_with_gemini(text, ...)

# 2. Google Custom Search
results = search_with_google_custom_search(keywords, ...)

# 3. Gemini 總結結果
summary = summarize_text(result_text, 300)
```

**問題**：
- 增加延遲（3 次 API 調用）
- 增加成本
- 複雜度較高

#### 4. ❌ 無法追問或深入討論
**問題**：
- 用戶無法針對搜尋結果提問
- 無法要求更詳細的解釋
- 無法進行多輪問答

---

## 🚀 改進方案

### 方案 1: Vertex AI Grounding with Google Search ⭐ **推薦**

使用 Vertex AI 的 **Google Search Grounding** 功能，這是 Google 官方的 RAG (Retrieval-Augmented Generation) 方案。

#### 優點
✅ **內建網路搜尋** - 不需要 Custom Search API
✅ **自動引用來源** - Gemini 會標註資訊來源
✅ **支援 Chat Session** - 原生支援對話記憶
✅ **更高品質** - Gemini 直接存取完整網頁內容
✅ **單一 API 調用** - 減少延遲和成本
✅ **動態搜尋** - Gemini 決定何時需要搜尋

#### 架構設計

```python
# 新增檔案: loader/chat_session.py

from google import genai
from google.genai import types
import os
from datetime import datetime, timedelta

# Session 管理
class ChatSessionManager:
    def __init__(self):
        self.sessions = {}  # {user_id: {session, last_active, history}}
        self.session_timeout = timedelta(minutes=30)  # 30分鐘過期

    def get_or_create_session(self, user_id: str):
        """獲取或創建用戶的聊天 session"""
        now = datetime.now()

        # 檢查是否有現有 session
        if user_id in self.sessions:
            session_data = self.sessions[user_id]
            # 檢查是否過期
            if now - session_data['last_active'] < self.session_timeout:
                session_data['last_active'] = now
                return session_data['session'], session_data['history']

        # 創建新 session
        client = genai.Client(
            vertexai=True,
            project=os.getenv('GOOGLE_CLOUD_PROJECT'),
            location=os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1'),
            http_options=types.HttpOptions(api_version="v1")
        )

        # 啟用 Google Search Grounding
        config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=2048,
            # 關鍵：啟用 Google Search
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        # 創建 chat session
        chat = client.chats.create(
            model="gemini-2.0-flash",
            config=config
        )

        self.sessions[user_id] = {
            'session': chat,
            'last_active': now,
            'history': []
        }

        return chat, []

    def clear_session(self, user_id: str):
        """清除用戶的 session"""
        if user_id in self.sessions:
            del self.sessions[user_id]

    def add_to_history(self, user_id: str, role: str, content: str):
        """記錄對話歷史"""
        if user_id in self.sessions:
            self.sessions[user_id]['history'].append({
                'role': role,
                'content': content,
                'timestamp': datetime.now()
            })


# 使用 Grounding 進行搜尋和回答
async def search_and_answer_with_grounding(
    query: str,
    user_id: str,
    session_manager: ChatSessionManager
):
    """
    使用 Vertex AI Grounding 搜尋並回答問題

    Args:
        query: 用戶問題
        user_id: LINE 用戶 ID
        session_manager: Session 管理器

    Returns:
        回答文字和引用來源
    """
    try:
        # 獲取或創建 chat session
        chat, history = session_manager.get_or_create_session(user_id)

        # 構建 prompt（加入繁體中文指示）
        prompt = f"""請用台灣用語的繁體中文回答以下問題。
如果需要最新資訊，請搜尋網路。
請提供詳細且準確的答案，並在回答結尾列出參考來源。

問題：{query}"""

        # 發送訊息
        response = chat.send_message(prompt)

        # 記錄到歷史
        session_manager.add_to_history(user_id, "user", query)
        session_manager.add_to_history(user_id, "assistant", response.text)

        # 提取引用來源（如果有）
        sources = []
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata'):
                metadata = candidate.grounding_metadata
                if hasattr(metadata, 'grounding_chunks'):
                    for chunk in metadata.grounding_chunks:
                        if hasattr(chunk, 'web'):
                            sources.append({
                                'title': chunk.web.title if hasattr(chunk.web, 'title') else 'Unknown',
                                'uri': chunk.web.uri if hasattr(chunk.web, 'uri') else ''
                            })

        return {
            'answer': response.text,
            'sources': sources,
            'has_history': len(history) > 0
        }

    except Exception as e:
        logging.error(f"Grounding search failed: {e}")
        raise


# 格式化回應
def format_grounding_response(result: dict) -> str:
    """格式化 Grounding 回應"""
    text = result['answer']

    # 加入 session 指示器
    if result['has_history']:
        text = f"💬 [對話中]\n\n{text}"

    # 加入來源
    if result['sources']:
        text += "\n\n📚 參考來源：\n"
        for i, source in enumerate(result['sources'][:3], 1):
            text += f"{i}. {source['title']}\n   {source['uri']}\n"

    return text
```

#### 修改 main.py

```python
# main.py

from loader.chat_session import ChatSessionManager, search_and_answer_with_grounding, format_grounding_response

# 全局 session manager
chat_session_manager = ChatSessionManager()

async def handle_text_message(event: MessageEvent, user_id: str):
    """處理純文字訊息 - 使用 Grounding"""
    msg = event.message.text

    # 檢查特殊指令
    if msg.lower() in ['/clear', '/清除', '/reset']:
        chat_session_manager.clear_session(user_id)
        reply_msg = TextSendMessage(text="✅ 對話已重置")
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
        return

    try:
        # 使用 Grounding 搜尋並回答
        result = await search_and_answer_with_grounding(
            query=msg,
            user_id=user_id,
            session_manager=chat_session_manager
        )

        # 格式化回應
        response_text = format_grounding_response(result)

        # 回覆
        reply_msg = TextSendMessage(text=response_text)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])

    except Exception as e:
        logger.error(f"Grounding search error: {e}")
        error_msg = "❌ 抱歉，處理您的問題時發生錯誤，請稍後再試。"
        reply_msg = TextSendMessage(text=error_msg)
        await line_bot_api.reply_message(event.reply_token, [reply_msg])
```

#### 使用範例

```
用戶: "Python 是什麼？"
Bot: Python 是一種高階、直譯式的程式語言...
     [Gemini 自動搜尋網路並引用來源]

     📚 參考來源：
     1. Python官方網站
        https://www.python.org/

用戶: "它有什麼優點？"  ✅ Bot 記得 "它" = Python
Bot: 💬 [對話中]

     Python 的主要優點包括：
     1. 語法簡潔易讀...
```

---

### 方案 2: 改進現有搜尋 + 加入 Chat Session

保留現有的 Google Custom Search，但加入對話記憶和更好的內容處理。

#### 優點
✅ 保留現有 Custom Search 投資
✅ 可以完全控制搜尋邏輯
✅ 加入 Session 管理

#### 缺點
❌ 需要維護更多代碼
❌ 搜尋結果質量受限於 snippet
❌ 需要多次 API 調用

#### 架構設計

```python
# loader/chat_session.py (方案2)

class SimpleSessionManager:
    """簡單的 Session 管理器"""
    def __init__(self):
        self.sessions = {}  # {user_id: conversation_history}
        self.max_history = 10  # 最多保留10輪對話

    def add_message(self, user_id: str, role: str, content: str):
        """添加訊息到歷史"""
        if user_id not in self.sessions:
            self.sessions[user_id] = []

        self.sessions[user_id].append({
            'role': role,
            'content': content
        })

        # 限制歷史長度
        if len(self.sessions[user_id]) > self.max_history * 2:
            self.sessions[user_id] = self.sessions[user_id][-self.max_history*2:]

    def get_history(self, user_id: str) -> list:
        """獲取對話歷史"""
        return self.sessions.get(user_id, [])

    def clear_history(self, user_id: str):
        """清除歷史"""
        if user_id in self.sessions:
            del self.sessions[user_id]


async def search_with_context(
    query: str,
    user_id: str,
    session_manager: SimpleSessionManager,
    search_api_key: str,
    search_engine_id: str
):
    """帶上下文的搜尋"""
    from loader.searchtool import search_from_text
    from loader.langtools import summarize_text

    # 獲取歷史
    history = session_manager.get_history(user_id)

    # 如果有歷史，加入上下文
    if history:
        # 使用 Gemini 重寫問題（加入上下文）
        context = "\n".join([f"{h['role']}: {h['content']}" for h in history[-4:]])

        client = genai.Client(
            vertexai=True,
            project=os.getenv('GOOGLE_CLOUD_PROJECT'),
            location=os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1'),
            http_options=types.HttpOptions(api_version="v1")
        )

        rewrite_prompt = f"""根據以下對話歷史，將用戶的新問題改寫成一個完整、獨立的搜尋查詢。
只返回改寫後的查詢，不要有其他文字。

對話歷史：
{context}

新問題：{query}

改寫後的搜尋查詢："""

        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=rewrite_prompt
        )

        search_query = response.text.strip()
        logger.info(f"Rewritten query: {search_query}")
    else:
        search_query = query

    # 執行搜尋
    results = search_from_text(search_query, None, search_api_key, search_engine_id)

    if not results:
        return None

    # 格式化搜尋結果
    result_text = "\n".join([
        f"{i}. {r['title']}\n{r['snippet']}"
        for i, r in enumerate(results[:5], 1)
    ])

    # 使用歷史生成回答
    answer_prompt = f"""根據以下搜尋結果和對話歷史，用繁體中文回答用戶的問題。

對話歷史：
{context if history else '(無)'}

用戶問題：{query}

搜尋結果：
{result_text}

請提供詳細且有用的回答："""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=answer_prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=1024
        )
    )

    # 記錄到歷史
    session_manager.add_message(user_id, "user", query)
    session_manager.add_message(user_id, "assistant", response.text)

    return {
        'answer': response.text,
        'results': results[:3],
        'has_history': len(history) > 0
    }
```

---

### 方案 3: 混合方案（最靈活）

結合兩者優點：
- **優先使用 Grounding** - 快速、高品質
- **備用 Custom Search** - Grounding 失敗時使用
- **統一 Session 管理** - 不管用哪種方法都保留對話記憶

---

## 📊 方案比較

| 特性 | 方案1: Grounding | 方案2: 改進現有 | 方案3: 混合 |
|------|-----------------|----------------|------------|
| **對話記憶** | ✅ 原生支援 | ✅ 自行實作 | ✅ 統一管理 |
| **搜尋品質** | ⭐⭐⭐⭐⭐ 最好 | ⭐⭐⭐ 中等 | ⭐⭐⭐⭐⭐ 最好 |
| **回應速度** | ⭐⭐⭐⭐ 快（1次API） | ⭐⭐ 慢（3次API） | ⭐⭐⭐⭐ 快 |
| **引用來源** | ✅ 自動 | ⚠️ 僅連結 | ✅ 自動 |
| **實作複雜度** | ⭐⭐ 簡單 | ⭐⭐⭐⭐ 複雜 | ⭐⭐⭐ 中等 |
| **成本** | 💰 Gemini API | 💰 Gemini + Custom Search | 💰💰 兩者 |
| **可控性** | ⚠️ Google控制 | ✅ 完全控制 | ✅ 彈性高 |
| **維護性** | ⭐⭐⭐⭐⭐ 簡單 | ⭐⭐ 需維護 | ⭐⭐⭐ 中等 |

---

## 🎯 建議實作順序

### 第一階段：實作 Grounding + Session（1-2天）
1. 新增 `loader/chat_session.py`
2. 修改 `main.py` 的 `handle_text_message()`
3. 測試基本對話功能
4. 測試 session 過期機制

### 第二階段：優化使用者體驗（1天）
1. 加入特殊指令（/clear, /help）
2. 改進回應格式
3. 加入對話狀態指示器
4. 測試長對話場景

### 第三階段：加入備用方案（選用，1天）
1. 保留現有 Custom Search 作為 fallback
2. Grounding 失敗時自動切換
3. 記錄效能數據

---

## 💡 額外建議

### 1. Session 持久化
目前 session 儲存在記憶體，伺服器重啟會遺失。可以考慮：
- Redis（推薦）- 快速、支援過期
- 檔案系統 - 簡單但效能較差
- Cloud Datastore - Google Cloud 原生

```python
# 使用 Redis 的範例
import redis
import json

class RedisSessionManager:
    def __init__(self):
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=0
        )
        self.ttl = 1800  # 30 分鐘

    def save_session(self, user_id: str, data: dict):
        key = f"session:{user_id}"
        self.redis.setex(key, self.ttl, json.dumps(data))

    def get_session(self, user_id: str):
        key = f"session:{user_id}"
        data = self.redis.get(key)
        return json.loads(data) if data else None
```

### 2. 對話分析和監控
記錄對話質量指標：
- 對話輪數
- 搜尋成功率
- 用戶滿意度（可加入 👍👎 按鈕）

### 3. 多模態支援
Grounding 也支援圖片：
```python
# 用戶可以同時發送文字和圖片
contents = [
    types.Part.from_text(query),
    types.Part.from_image_bytes(image_data, mime_type="image/png")
]
```

---

## 📝 環境變數更新

```bash
# .env 需要加入（如果用 Redis）
REDIS_HOST=localhost
REDIS_PORT=6379

# Grounding 不需要 Custom Search API，但保留作為備用
SEARCH_API_KEY=your_key  # 選用
SEARCH_ENGINE_ID=your_id  # 選用
```

---

## ✅ 總結

### 推薦：方案 1（Grounding + Session）

**理由**：
1. ✅ **最簡單** - 代碼量最少，維護最容易
2. ✅ **最快速** - 只需一次 API 調用
3. ✅ **最高品質** - Google 官方 RAG 方案
4. ✅ **原生 Session** - Gemini Chat 內建對話記憶
5. ✅ **自動引用** - 自動標註資訊來源

**適合**：
- 想要快速實作對話記憶
- 追求高品質搜尋結果
- 減少維護負擔
- 未來可能加入更多 AI 功能

**如果你需要**：
- ✅ 我可以幫你實作完整的 Grounding + Session 方案
- ✅ 提供測試程式碼
- ✅ 更新相關文檔

要開始實作嗎？
