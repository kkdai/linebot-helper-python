# Pure Vertex AI implementation - no LangChain
import os
import logging
import PIL.Image
from io import BytesIO
from typing import Any
from pydantic import BaseModel, Field


# Use google-genai SDK for Vertex AI
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Set the user agent
os.environ["USER_AGENT"] = "myagent"

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'global')


def _get_vertex_client():
    """Get Vertex AI client instance"""
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai package not available")
    if not VERTEX_PROJECT:
        raise ValueError("GOOGLE_CLOUD_PROJECT not set")

    return genai.Client(
        vertexai=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,
        http_options=types.HttpOptions(api_version="v1")
    )


def summarize_text(text: str, max_tokens: int = 100, mode: str = "normal") -> str:
    '''
    Summarize a text using Vertex AI Gemini.

    Args:
        text: Text to summarize
        max_tokens: Maximum tokens for the summary (deprecated, use mode instead)
        mode: Summary mode - "short", "normal", or "detailed"

    Returns:
        Summarized text in Traditional Chinese
    '''
    return summarize_text_with_mode(text, mode)


def summarize_text_with_mode(text: str, mode: str = "normal") -> str:
    '''
    Summarize a text with different length modes using Vertex AI.

    Args:
        text: Text to summarize
        mode: Summary mode
            - "short" (短): 50-100 characters, key points only
            - "normal" (標準): 200-300 characters, balanced summary
            - "detailed" (詳細): 500-800 characters, comprehensive analysis

    Returns:
        Summarized text in Traditional Chinese
    '''
    # Define prompts for different modes
    prompts = {
        "short": """用台灣用語的繁體中文，用 1-3 個重點總結文章核心內容。務必極度簡潔。

原文： "{text}"

# 要求
- 只列出 1-3 個最關鍵重點
- 每個重點不超過 15 字
- 直接列出重點，不需要前言
- 結尾加入 2-3 個英文 hashtag

# 範例輸出：
- AI 技術快速發展
- 影響就業市場
- 需要政策規範
#AI #Technology #Policy""",

        "normal": """用台灣用語的繁體中文，簡潔地以條列式總結文章重點。在摘要後直接加入相關的英文 hashtag，以空格分隔。內容來源可以是網頁、文章、論文、影片字幕或逐字稿。

原文： "{text}"
請遵循以下步驟來完成此任務：

# 步驟
1. 從提供的內容中提取重要重點，無論來源是網頁、文章、論文、影片字幕或逐字稿。
2. 將重點整理成條列式，確保每一點為簡短且明確的句子。
3. 使用符合台灣用語的簡潔繁體中文。
4. 在摘要結尾處，加入至少三個相關的英文 hashtag，並以空格分隔。

# 輸出格式
- 重點應以條列式列出，每一點應為一個短句或片語，語言必須簡潔明瞭。
- 最後加入至少三個相關的英文 hashtag，每個 hashtag 之間用空格分隔。

# 範例
輸入：
文章內容：
台灣的報告指出，環境保護的重要性日益增加。許多人開始選擇使用可重複使用的產品。政府也實施了多項政策來降低廢物。

摘要：

輸出：
- 環境保護重要性增加
- 越來越多人使用可重複產品
- 政府實施減廢政策
#EnvironmentalProtection #Sustainability #Taiwan

reply in zh-TW""",

        "detailed": """用台灣用語的繁體中文，詳細地以條列式總結文章內容，包含背景、主要論點、細節和結論。

原文： "{text}"

# 要求
1. 提供完整的文章背景和上下文
2. 詳細列出所有重要論點和細節
3. 包含具體的數據、案例或例子（如果有）
4. 分析文章的結論和影響
5. 使用台灣用語的繁體中文
6. 結尾加入相關的英文 hashtag

# 輸出格式

【背景】
- 提供文章背景和上下文

【主要內容】
- 詳細列出所有重要論點
- 包含具體細節和數據
- 列出關鍵案例或例子

【結論與影響】
- 總結文章結論
- 分析可能的影響

#Hashtag1 #Hashtag2 #Hashtag3

reply in zh-TW"""
    }

    # Select prompt based on mode
    prompt_template = prompts.get(mode, prompts["normal"])
    prompt = prompt_template.replace("{text}", text)

    try:
        client = _get_vertex_client()

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=2048,
                labels={"client_id": "info_helper"},
            )
        )

        return response.text if response.text else "無法生成摘要"

    except Exception as e:
        logging.error(f"Error summarizing text: {e}")
        raise


def generate_json_from_image(img: PIL.Image.Image, prompt: str) -> Any:
    '''
    Analyze image using Vertex AI Gemini.

    Args:
        img: PIL Image object
        prompt: Prompt for image analysis

    Returns:
        Response object with text attribute
    '''
    try:
        client = _get_vertex_client()

        # Convert PIL Image to bytes
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()

        # Create multimodal content
        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_image_bytes(
                data=img_byte_arr,
                mime_type="image/png"
            )
        ]

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.5,
                max_output_tokens=2048,
                labels={"client_id": "info_helper"},
            )
        )

        logging.info(f">>>>{response.text}")

        # Return a simple object with text attribute for compatibility
        class ImageResponse:
            def __init__(self, text):
                self.text = text
                self.parts = [text] if text else []
                self.candidates = []

        return ImageResponse(response.text if response.text else "")

    except Exception as e:
        logging.error(f"Error analyzing image: {e}")
        raise


# Legacy helper function for compatibility
def docs_to_str(docs: list) -> str:
    """Convert documents to string (for backward compatibility)"""
    if not docs:
        return ""

    # Handle different document types
    result = []
    for doc in docs:
        if hasattr(doc, 'page_content'):
            result.append(doc.page_content)
        elif isinstance(doc, dict) and 'page_content' in doc:
            result.append(doc['page_content'])
        elif isinstance(doc, str):
            result.append(doc)
        else:
            result.append(str(doc))

    return "\n".join(result)


class SocialMediaPosts(BaseModel):
    title: str = Field(description="文章標題（15 字內，取自原文重點，繁體中文台灣用語）")
    summary_analysis: str = Field(description="文章摘要與重點分析（150-250 字繁體中文：先 2-3 句摘要文章核心內容，再 2-3 句分析重點、為什麼值得讀、對讀者的意義。純文字不用 markdown）")
    facebook: str = Field(description="適合 Facebook 的爆款分享貼文文案，包含吸引人的標題、Emoji、條列重點、互動問題及相關 Hashtag")
    linkedin: str = Field(description="適合 LinkedIn 的專業商務貼文文案，著重專業洞察、核心收穫、引人深思的問題及專業 Hashtag")
    threads: str = Field(description="適合 Threads 的口語化貼文文案，以脆友語氣撰寫，第一句需有強烈共鳴或槽點，段落極短，少用 Hashtag，著重引導留言討論")


class BookmarkSummary(BaseModel):
    title: str = Field(description="文章標題（15 字內，取自原文重點，繁體中文台灣用語）")
    summary: str = Field(description="文章摘要與重點分析（150-250 字繁體中文：先摘要核心內容，再點出重點與值得注意之處。純文字不用 markdown）")


# 人性化守則：萃取自 speak-human-tw (github.com/Raymondhou0917/speak-human-tw)
# 這個台灣原生「說人話」skill 的內容規則（非其互動式審查流程），並保留原本
# 參考 blader/humanizer 的爆款場景調整。核心：先保事實 → 再去 AI 味 → 最後加人味。
# 放在排版技巧「之前」並標最高優先，讓模型在「人味 vs 排版花招」衝突時優先保住真實感。
HUMANIZE_GUIDELINES = """# 人性化守則（最高優先，凌駕以下排版技巧）：
寫得像一個真實、有觀點的台灣人，而不是 AI 在「生成內容」。順序：先保事實 → 再去 AI 味 → 最後加人味。

## A. 先刪（刪掉不用補）
1. AI 開場定型句／時代大帽子：不要用「在當今這個時代」「隨著 AI 快速發展」「讓我們一起來看看」「老實說？」「你有沒有想過…」。第一句就該有只有這篇文章才有的資訊。
2. 對話殘留與諂媚：不要「好問題！」「希望這對你有幫助」「以下是為你整理的…」。
3. 通用積極結論、罐頭收尾：不要「未來充滿無限可能」「讓我們一起邁向…」「總的來說」「綜上所述」。允許停在最後一個具體句子上，不必補新結尾。

## B. 再具體化（寫不出具體就刪，不要換句空話）
4. 誇大意義詞落地：「標誌著／見證了／奠定基礎／體現了／不僅僅是」改成具體事實，寫不出來就刪。
5. 假推論與無源權威：「這意味著…」問得出誰在推論、根據什麼再留；「研究顯示／業界專家認為」沒出處就刪，不要編造來源或數字。
6. 補立場：「各有優缺點／因人而異／取決於多方面因素」代表整段沒判斷，改成明確選擇與理由。
7. 具體 ＞ 抽象：能講「一個月省 3 小時」就不要講「大幅提升效率」。

## C. 再降格式
8. 「不是 A，而是 B」與「不僅…更…」整篇最多各一次，其餘改直述。
9. 「首先／其次／最後」不硬湊三點：需要幾點寫幾點，結構服從邏輯不服從對稱。
10. 破折號每 300–500 字最多 1 次；粗體一段最多 2–3 個詞。

## D. 台灣在地化（AI 產繁中最容易露餡處）
11. 中國用語一律替換：視頻→影片、質量→品質、信息→資訊、網絡→網路、軟件→軟體、水平→水準、立馬→馬上、默認→預設、反饋→回饋、支持(功能)→支援、性價比→CP值、給力→很到位、靠譜→可靠、接地氣→貼近日常；「賦能／閉環／抓手」這類整句重寫成「讓誰能做到什麼」。
12. 全形標點：中文句一律「，。：；！？「」（）、」；刪節號用「⋯⋯」不用「...」；並列用頓號「、」。
13. 台灣語氣詞：社群口語可用「喔／耶／啦／欸／齁」收尾；砍中國腔「哈／好噠／是滴」。量詞用台灣慣用（一部影片、一支手機、一則貼文）。

## E. 加人味（乾淨只是及格線）
14. 對事實做出反應，不只報告事實；適當用第一人稱「我」，那是誠實不是不專業。
15. 句長長短交錯、允許輕微不對稱，最有話說的那點給兩倍篇幅。
16. 但人味是作者的：不要替作者發明沒說過的經歷、故事或立場。

（emoji 用量依各平台指南處理，共同原則是調味不是裝飾、不要每行都放。）
"""


def _build_social_media_prompt(text: str) -> str:
    """Build the viral social-media generation prompt for a given article text.

    Extracted so the prompt (humanize guidelines + per-platform tuning) can be
    unit-tested without calling the Gemini API.
    """
    return f"""請針對以下網頁內容，完成兩件事：
1. 產出文章標題（title，15 字內）與「摘要與重點分析」（summary_analysis，150-250 字：先 2-3 句摘要核心內容，再 2-3 句分析重點與為什麼值得讀。此欄位是給讀者快速理解文章用的，語氣中性直述即可，不是社群貼文）。
2. 為三個不同的社群平台（Facebook、LinkedIn、Meta Threads）各撰寫一篇容易「爆款」（高互動、高分享、吸引眼球）的繁體中文（台灣用語）分享貼文。

網頁內容：
{text}

{HUMANIZE_GUIDELINES}
# 寫作指南：

## 1. Facebook 爆款貼文：
- 吸引人的 Hook：第一句話必須非常吸睛，善用好奇心、痛點或誇張的開頭。但依人性化守則，開場改用「真實痛點／真實場景」，禁止假掰誇張詞。
- 版面排版：多用 Emoji，段落清晰，使用條列式（Bullet points）整理核心觀點。
- 呼籲行動（CTA）：結尾提出一個好回答的問題，引導讀者留言或分享。
- Hashtags：加入 3-5 個相關的熱門 Hashtag。
- 長度：約 200-400 字。

## 2. LinkedIn 專業貼文：
- 專業 Hook：第一句從商業洞察、職場學習、趨勢分析或個人省思出發。
- 內容結構：語氣專業、理性，分享文章的核心價值、給職場人士或企業的具體 Takeaways。此平台人性化守則權重高：專業不等於八股，要像一個有實戰經驗的真人在分享觀點，可用第一人稱與具體經歷。禁止 buzzword 空堆（如「賦能」「數位轉型」「無縫接軌」連發），並嚴禁 AI 正式腔套語（如「值得我們深入探討」「至關重要」「不容忽視的現象」「在當今這個時代」）。每個 Takeaway 要具體可執行。
- 呼籲行動：徵求專業意見或開啟思辨討論，例如：「你怎麼看這個趨勢？」
- Hashtags：加入 3-5 個專業領域的 Hashtag。
- 長度：約 300-500 字。

## 3. Meta Threads 脆友討論：
- Threads 脆友 Hook：極度口語化、像跟朋友講話，第一句要帶有強烈共鳴、槽點、吐槽、或一針見血的觀點。
- 內容風格：段落極短（每段 1-2 句話），善用白話文、網路用語或迷因感。以分享八卦、大實話或內行人才懂的梗為佳。此平台人性化守則權重最高：要像真的脆友在講話，容許不完美、口語破碎感，善用台灣語氣詞（喔／耶／啦／欸／齁）收尾，嚴禁任何 AI 腔。emoji 收斂，整篇最多 1 個。
- 呼籲行動：隨性引導留言，例如：「有人也是這樣嗎？」
- Hashtags：不使用或僅使用 1 個 Hashtag。
- 長度：約 150-300 字。
"""


def generate_social_media_posts(text: str) -> dict:
    """
    Generate viral social media posts for FB, LinkedIn, and Threads from article text.

    Args:
        text: The text content of the crawled webpage.

    Returns:
        dict: A dictionary containing:
            - facebook: FB copy
            - linkedin: LinkedIn copy
            - threads: Threads copy
    """
    if not text or not text.strip():
        return {
            "title": "無法取得網頁內容",
            "summary_analysis": "無法取得網頁內容，無法產生摘要。",
            "facebook": "無法取得網頁內容，無法產生文案。",
            "linkedin": "無法取得網頁內容，無法產生文案。",
            "threads": "無法取得網頁內容，無法產生文案。"
        }

    prompt = _build_social_media_prompt(text)

    try:
        client = _get_vertex_client()
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=SocialMediaPosts,
                # gemini-3.1-flash-lite 是思考模型，此上限為「思考 + 輸出」共用。
                # 人性化守則變豐富後思考 token 增加，4096 會偶爾把 JSON 輸出擠爆
                # 導致截斷、json.loads 失敗。拉高留餘裕（實際只產出約 800-1200 tokens）。
                max_output_tokens=8192,
                labels={"client_id": "info_helper"},
            )
        )

        import json
        if response.text:
            return json.loads(response.text)
        else:
            raise Exception("Empty response text from Gemini")

    except Exception as e:
        logging.error(f"Error generating social media posts: {e}")
        # Fallback dictionary
        return {
            "title": "摘要生成失敗",
            "summary_analysis": f"生成摘要失敗：{str(e)[:100]}",
            "facebook": f"生成 Facebook 文案失敗：{str(e)[:100]}",
            "linkedin": f"生成 LinkedIn 文案失敗：{str(e)[:100]}",
            "threads": f"生成 Threads 文案失敗：{str(e)[:100]}"
        }


def summarize_for_bookmark(text: str) -> dict:
    """為 /save 書籤指令產生標題與摘要分析（不產社群貼文）。

    Returns:
        dict: {"title": str, "summary": str}
    """
    if not text or not text.strip():
        return {
            "title": "無法取得網頁內容",
            "summary": "無法取得網頁內容，無法產生摘要。"
        }

    prompt = f"""請針對以下網頁內容，產出文章標題（title，15 字內）與「摘要與重點分析」
（summary，150-250 字繁體中文台灣用語：先 2-3 句摘要核心內容，再 2-3 句分析重點
與值得注意之處。純文字，不用 markdown 符號）。

網頁內容：
{text}"""

    try:
        client = _get_vertex_client()
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
                response_schema=BookmarkSummary,
                max_output_tokens=4096,
                labels={"client_id": "info_helper"},
            )
        )

        import json
        if response.text:
            return json.loads(response.text)
        raise Exception("Empty response text from Gemini")

    except Exception as e:
        logging.error(f"Error generating bookmark summary: {e}")
        return {
            "title": "摘要生成失敗",
            "summary": f"生成摘要失敗：{str(e)[:100]}"
        }

