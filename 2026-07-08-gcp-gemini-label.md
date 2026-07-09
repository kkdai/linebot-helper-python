---
layout: post
title: "[GCP 帳單與 Vertex AI] 破解單一專案 Gemini 費用拆分難題：Vertex AI 動態計費標籤 (Labels) 實戰記"
description: "紀錄如何解決 Google Cloud 帳單中無法依 API Key 拆分 Gemini 費用的痛點。透過將專案重構為 Vertex AI，並在 SDK 中動態傳遞計費標籤 (Request Labels)，實現精準的成本分攤與分析。"
category:
- GCP
- AI
- Python
tags: ["GCP Billing", "Vertex AI", "Gemini API", "Request Labels", "Cost Management", "Python SDK"]
---

# 痛點：同一個專案內的 Gemini API 費用如何精準分攤？

在開發企業級 LLM 服務或是經營多租戶 (Multi-tenant) 平台時，最常被財務與維運團隊問到的問題就是：
> 「我們同一個 GCP 專案內接了許多不同的業務與 LINE Bot，每天的 Gemini Key 費用都會統統出現在 Gemini API 的範圍，我們有辦法根據不同的 Gemini Key 或不同的使用者來拆分費用嗎？」

**直接回答你的問題：**
在 Google Cloud 帳單（Cloud Billing）報告中，**無法直接「根據不同的 API Key 金鑰名稱」來分開顯示費用**。
Google Cloud 的帳單報表最小的歸屬維度是到「專案 (Project)」、「服務 (Service)」和「SKU (產品細項)」，系統並不會把個別的 API Key 字串當作獨立的計費項目。對帳單系統來說，同一個專案內不論你建了 10 把還是 100 把 API Key，通通都會被揉在一起算成一筆 Gemini API 的總帳。

---

# 山不轉路轉：Vertex AI 的「請求標籤 (Labels)」救星

如果因為架構限制非得塞在同一個專案，最推薦的做法就是：**切換至 Vertex AI 呼叫，並使用「請求標籤 (Labels)」**。

如果你目前使用的是 Google AI Studio 的 API Key，它在單一專案內是無法傳遞計費標籤的。但如果你將程式碼改為呼叫 **Vertex AI 的 Gemini API**（一樣在同一個專案內），Vertex AI 支援在每次發送請求時，動態帶入自訂的 `labels`（標籤）。

### 原理與流程
在每次發送請求（例如呼叫 `generateContent`）時，於 API Request 中帶入特定的 Metadata：

```json
{
  "contents": { ... },
  "labels": {
    "client_id": "info_helper",
    "api_key_group": "marketing_team"
  }
}
```

這些自訂標籤會直接被傳遞到 GCP 的帳單系統。之後當你到 GCP 帳單報告中，在「分組依據 (Group by)」選擇你設定的標籤鍵（例如 `client_id`），就能在同一個專案內，把不同標籤（代表不同服務、客戶或使用者）的費用算得一清二楚！

---

# 專案實戰改造：全面導入 Labels 機制

為了完成這個需求，我們盤點了目前 LINE Bot 專案的 API 呼叫架構，並進行了以下重構。

### 1. 專案 API 呼叫盤點
經由掃描，我們發現專案中絕大部分都是使用 Vertex AI 進行呼叫（17 個 Client 中有 14 個使用 `vertexai=True`），只有少數例外：
*   **Vertex AI 呼叫**：包括 GitHub 摘要、多個 Google Maps Grounding 工具、文字摘要、圖片分析、語音轉文字等（共 11 個檔案、19 處呼叫點）。
*   **Gemini API Key 呼叫**：`main.py` 的 Live API、`batch_service.py` 的 Batch 服務，以及 `tts_tool.py` 的 TTS 語音合成。

> [!IMPORTANT]
> `labels` 參數僅 Vertex AI 支援，若在 API Key (`vertexai=False`) 下帶入此參數會導致 SDK 拋出 Error，因此我們只針對 11 個使用 Vertex AI 的檔案進行修改。

### 2. 實作修改方式

對於 `google-genai` Python SDK，我們有兩種主要的修改場景：

#### 場景 A：已包含 `GenerateContentConfig`
若原本的呼叫就帶有 Config，我們只需在 config 中額外傳入 `labels={"client_id": "info_helper"}`：

```python
# 修改前 (例如 loader/gh_tools.py)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=2048,
    )
)

# 修改後
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=2048,
        labels={"client_id": "info_helper"},  # 帶入計費標籤
    )
)
```

#### 場景 B：無 Config 參數
若原本的呼叫非常簡單（例如 `searchtool.py` 或 `youtube_gcp.py`），我們需要主動帶入一個包含 labels 的 `GenerateContentConfig`：

```python
# 修改前 (例如 loader/searchtool.py)
response = client.models.generate_content(
    model="gemini-3.1-flash-lite-preview",
    contents=prompt,
)

# 修改後
response = client.models.generate_content(
    model="gemini-3.1-flash-lite-preview",
    contents=prompt,
    config=types.GenerateContentConfig(
        labels={"client_id": "info_helper"},  # 新增 config 帶入標籤
    ),
)
```

### 3. 被修改的檔案清單

我們總共對以下 11 個檔案中的 19 個呼叫點進行了精準修改，並在提交前使用 Python 的 AST 模組（`ast.parse`）以及 Flake8 進行語法與排版檢驗：

1.  **[agents/chat_agent.py](file:///Users/al03034132/Documents/linebot-helper-python/agents/chat_agent.py)**：修改 `_create_chat_config()`，為一般問答及 Grounding 對話都加上 labels。
2.  **[loader/chat_session.py](file:///Users/al03034132/Documents/linebot-helper-python/loader/chat_session.py)**：為 Chat session config 帶入 labels。
3.  **[loader/gh_tools.py](file:///Users/al03034132/Documents/linebot-helper-python/loader/gh_tools.py)**：GitHub 摘要 API。
4.  **[loader/langtools.py](file:///Users/al03034132/Documents/linebot-helper-python/loader/langtools.py)**：文字摘要、圖片 JSON 生成、社群貼文生成。
5.  **[loader/maps_grounding.py](file:///Users/al03034132/Documents/linebot-helper-python/loader/maps_grounding.py)**：地圖搜尋 API。
6.  **[loader/searchtool.py](file:///Users/al03034132/Documents/linebot-helper-python/loader/searchtool.py)**：關鍵字提取工具。
7.  **[loader/youtube_gcp.py](file:///Users/al03034132/Documents/linebot-helper-python/loader/youtube_gcp.py)**：YouTube 影片理解 API。
8.  **[tools/audio_tool.py](file:///Users/al03034132/Documents/linebot-helper-python/tools/audio_tool.py)**：異步語音轉文字。
9.  **[tools/maps_tool.py](file:///Users/al03034132/Documents/linebot-helper-python/tools/maps_tool.py)**：地圖附近搜尋、餐廳名稱擷取、批次與評價搜尋等 5 處呼叫。
10. **[tools/summarizer.py](file:///Users/al03034132/Documents/linebot-helper-python/tools/summarizer.py)**：文字摘要與 Agentic Vision 圖像理解。
11. **[tools/youtube_tool.py](file:///Users/al03034132/Documents/linebot-helper-python/tools/youtube_tool.py)**：YouTube 摘要工具。

---

# 避坑指南：小心 SDK 模組導入問題

在為 `youtube_gcp.py` 與 `youtube_tool.py` 重構無 Config 的呼叫時，由於這兩個檔案原本只使用了 named import 導入特定的型別：
```python
from google.genai.types import HttpOptions, Part
```
當我們在程式碼中寫下 `types.GenerateContentConfig(...)` 時，系統會拋出 `NameError: name 'types' is not defined` 的錯誤。

**解決辦法：**
我們需要修正該 import 敘述，直接引入 [GenerateContentConfig](file:///Users/al03034132/Documents/linebot-helper-python/loader/youtube_gcp.py#L8)：
```python
# 修改前
from google.genai.types import HttpOptions, Part

# 修改後
from google.genai.types import HttpOptions, Part, GenerateContentConfig
```
並在呼叫時直接使用，而不加上 `types.` 前綴：
```python
config=GenerateContentConfig(labels={"client_id": "info_helper"})
```

---

# 總結與後續步驟

本次修改成功將 `client_id=info_helper` 標籤注入至 LINE Bot 專案內所有 Vertex AI API 的呼叫中。

1.  **帳單生效延遲**：請注意，當我們開始帶入 `labels` 之後，GCP 的帳單數據通常會有 24 到 48 小時的生效延遲。
2.  **在 GCP Billing 設定**：過兩天後，可以前往 GCP Console -> **Billing (計費)** -> **Reports (報表)**。在右側的 Group by (分組依據) 中選擇 **Labels** 並輸入我們的 key `client_id`。
3.  **大功告成**：此時報表就會將 `info_helper` 當作獨立的計費列獨立繪出，完美解決了專案費用分開核銷與統計的難題！
