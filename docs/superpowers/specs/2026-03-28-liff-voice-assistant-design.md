# LIFF 即時語音助手 — Design Spec

**Date:** 2026-03-28
**Status:** Draft

---

## 目標

在現有的 LINE Bot Cloud Run 服務上新增一個 LIFF 語音助手，讓使用者在 LINE 內開啟網頁後，以即時雙向語音與 OA 互動。後端透過 Gemini Live API 處理音訊，並將每一輪對話自動推送回 LINE 聊天室。

---

## 架構

```
[LINE App]
  Rich Menu「🎤 語音助手」按鈕
    → 開啟 LIFF URL（https://{cloud-run-url}/liff/）

[LIFF App — 瀏覽器]
  · Web Audio API 捕捉麥克風 PCM（16kHz, 16-bit, mono）
  · 按住說話（預設）/ 免持模式（VAD）
  · 顯示對話氣泡（text）
  · 播放 AI 語音回應（PCM → Web Audio）
  · 首次開啟取得 GPS 座標（Geolocation API）
    ↕ WebSocket /ws/voice/{session_id}
    （上行：PCM chunks + JSON 事件；下行：PCM chunks + JSON text）

[FastAPI — Cloud Run]
  · GET /liff/ → 回傳 static/liff/index.html
  · GET /static/liff/voice.js → JS 靜態檔
  · WS /ws/voice/{session_id} → 語音 WebSocket Handler
    · 接收 PCM，轉發給 Gemini Live session
    · 注入 system context（GPS、user_id、Agent 能力說明）
    · 接收 Gemini Live 回應（PCM + text）
    · 串流 PCM + text 回瀏覽器
    · 每輪 turn_complete → push_message 到 LINE
    ↕ google-genai Live WebSocket（us-central1）

[Vertex AI]
  model: gemini-live-2.5-flash-native-audio
  response_modalities: ["AUDIO", "TEXT"]
  system_instruction: 含 GPS、現有 Agents 能力說明
```

---

## LIFF 前端

### 檔案

| 檔案 | 說明 |
|------|------|
| `static/liff/index.html` | LIFF app 主頁面 |
| `static/liff/voice.js` | WebSocket + Web Audio + UI 狀態機 |

### 三種 UI 狀態

**1. 待機（Idle）**
- 深色背景，中央大麥克風按鈕（藍色）
- 上方顯示歷史對話氣泡（若有）
- 右上角「免持模式」toggle（預設關）

**2. 錄音中（Recording）**
- 麥克風按鈕變紅 + 脈衝光暈動畫
- 對話區顯示紅色錄音氣泡 + 音波波形動畫
- 狀態文字：「● 錄音中，放開送出」
- Push-to-talk：放開按鈕即送出
- Hands-free：VAD 偵測到停頓自動送出

**3. AI 回應中（Speaking）**
- 文字氣泡邊出現（streaming text）邊播放語音（PCM streaming）
- 麥克風按鈕灰色半透明
- 狀態文字：「🔊 AI 說話中，點擊打斷」
- 點擊按鈕 → 送出中斷訊號 → Gemini Live 停止輸出

### 免持模式（Hands-free）
- Toggle 切換後，麥克風常開
- Gemini Live 內建 VAD 自動偵測說話結束
- 顯示警示：「⚠ 吵雜環境可能誤觸發」
- AI 說話中使用者開口 → Gemini Live 原生打斷支援

### LIFF 初始化流程
1. 載入 `@line/liff` SDK
2. `liff.init({ liffId: LIFF_ID })`
3. 取得 `liff.getProfile()` → `userId`（作為 session_id）
4. 請求 Geolocation（使用者允許時）→ 取得 `{lat, lng}`
5. 開啟 WebSocket `wss://.../ws/voice/{userId}`
6. 送出 JSON 初始化事件：`{ type: "init", user_id, lat, lng }`

---

## WebSocket 協定

### 上行（LIFF → 後端）

| 類型 | 格式 | 說明 |
|------|------|------|
| 初始化 | `JSON { type:"init", user_id, lat?, lng? }` | 連線後第一個訊息 |
| 音訊資料 | Binary（PCM bytes） | 錄音期間持續送出 |
| 錄音結束 | `JSON { type:"end_of_speech" }` | Push-to-talk 放開時 |
| 打斷 | `JSON { type:"interrupt" }` | 使用者點擊打斷 AI |
| 免持切換 | `JSON { type:"toggle_handsfree", enabled: bool }` | Toggle 狀態變更 |

### 下行（後端 → LIFF）

| 類型 | 格式 | 說明 |
|------|------|------|
| 文字片段 | `JSON { type:"text_chunk", text }` | Streaming text 即時顯示 |
| 音訊資料 | Binary（PCM bytes） | AI 語音串流播放 |
| 輪次完成 | `JSON { type:"turn_complete" }` | 一輪結束，恢復待機 |
| 錯誤 | `JSON { type:"error", message }` | 顯示錯誤提示 |

---

## 後端 WebSocket Handler

### 位置
`main.py` 新增，與現有 webhook handler 並列。

### 流程

```python
@app.websocket("/ws/voice/{session_id}")
async def voice_ws(ws: WebSocket, session_id: str):
    await ws.accept()
    # 1. 等待 init 事件，取得 user_id / GPS
    # 2. 建立 Gemini Live session（us-central1）
    #    - system_instruction 注入 GPS + Agent 能力說明
    # 3. 雙向 relay loop：
    #    - 接收 PCM binary → forward 給 Gemini Live
    #    - 接收 JSON 事件 → 控制 session
    #    - 接收 Gemini Live PCM → 回傳給 LIFF
    #    - 接收 Gemini Live text chunks → 回傳給 LIFF
    # 4. turn_complete：
    #    - 整理本輪文字（使用者說了什麼 + AI 回了什麼）
    #    - push_message(user_id, [TextSendMessage(text=summary)])
    # 5. 連線斷開 → 關閉 Gemini Live session
```

### System Instruction 結構

```
你是一個整合多種工具的語音助手，透過 LINE Bot 服務使用者。

使用者目前位置：{lat}, {lng}（若有）

你可以：
- 查詢附近地點（使用 maps 工具）
- 摘要網頁 / YouTube / PDF 內容
- 回答一般問題（搭配 Google Search）
- 分析圖片（使用者須在 LINE 聊天室傳送圖片）

請用繁體中文回應，語氣自然口語，適合語音播放（不要用條列符號）。
```

### Push to LINE 格式

每輪 `turn_complete` 後推送：

```
🎤 你說：{user_speech}

🤖 AI：{ai_response}
```

---

## 新增檔案總覽

| Action | 檔案 | 說明 |
|--------|------|------|
| Create | `static/liff/index.html` | LIFF 主頁面 |
| Create | `static/liff/voice.js` | 前端邏輯 |
| Modify | `main.py` | 新增 `/liff/` 路由、`/ws/voice/{id}` handler |
| Modify | `Dockerfile` | 確認 `static/` 目錄被 COPY |

---

## Rich Menu 設定

- 在 LINE Developers Console 建立 Rich Menu
- 加入「🎤 語音助手」按鈕，action type: `uri`
- URI: `https://liff.line.me/{LIFF_ID}`
- LIFF 在 LINE Developers Console 註冊，endpoint URL: `https://{cloud-run-url}/liff/`
- LIFF size: `full`（全螢幕）

---

## 錯誤處理

| 情境 | 處理方式 |
|------|----------|
| 使用者拒絕麥克風權限 | 顯示提示「請允許麥克風權限才能使用語音功能」 |
| 使用者拒絕 GPS 權限 | 正常運作，system_instruction 不含座標，地點查詢改為要求使用者口述位置 |
| Gemini Live 連線失敗 | 下行送 `{ type:"error" }`，LIFF 顯示「語音服務暫時無法使用」 |
| WebSocket 斷線 | LIFF 自動重連（最多 3 次），失敗後顯示重新整理提示 |
| push_message 失敗 | 僅 log error，不影響語音對話繼續 |

---

## 不在本次範圍

- 群組聊天室的語音助手（僅限 1:1）
- 多語言切換 UI
- 對話歷史持久化（跨 session）
- 語音指令控制 LINE Bot 其他功能（如傳送圖片）
- Rich Menu 透過 API 自動部署（手動設定）
