"""書籤功能的 Flex Message 組裝與指令解析

純函式、只產生 dict，不依賴 LINE SDK，方便單元測試。
規格：docs/superpowers/specs/2026-08-13-bookmark-system-design.md
"""
import json
import re
from datetime import datetime
from typing import List, Optional, Tuple

SUMMARY_SNIPPET_LENGTH = 100

_COMMAND_PATTERN = re.compile(r"^/(save|list|search)(?:\s+(.*))?$", re.DOTALL)


def parse_bookmark_command(text: str) -> Optional[Tuple[str, str]]:
    """解析書籤指令。

    Returns:
        (command, argument)，非書籤指令回 None。
        例："/save https://x" → ("save", "https://x")；"/list" → ("list", "")
    """
    match = _COMMAND_PATTERN.match(text.strip())
    if not match:
        return None
    command = match.group(1)
    argument = (match.group(2) or "").strip()
    return command, argument


def build_summary_bubble(title: str, summary_analysis: str, url: str,
                         doc_id: Optional[str]) -> dict:
    """社群貼文 carousel 的第一顆 bubble：📌 摘要與分析 + 儲存書籤按鈕。

    doc_id 為 None 代表 Firestore 不可用（沒寫候選），不放會失敗的儲存按鈕。
    """
    footer_contents = [
        {
            "type": "button",
            "style": "link",
            "height": "sm",
            "action": {
                "type": "uri",
                "label": "🔗 開啟原文",
                "uri": url,
            },
        },
    ]

    if doc_id:
        footer_contents.insert(0, {
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": "📄 詳細研究報告",
                "data": json.dumps(
                    {"action": "research_report", "id": doc_id},
                    ensure_ascii=False),
                "displayText": "📄 產生詳細研究報告",
            },
        })
        footer_contents.insert(0, {
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": "🇺🇸 英文貼文",
                "data": json.dumps(
                    {"action": "generate_english_post", "id": doc_id},
                    ensure_ascii=False),
                "displayText": "🇺🇸 產生英文版貼文",
            },
        })
        footer_contents.insert(0, {
            "type": "button",
            "style": "primary",
            "color": "#E67E22",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": "🔖 儲存書籤",
                "data": json.dumps(
                    {"action": "save_bookmark", "id": doc_id},
                    ensure_ascii=False),
                "displayText": "🔖 儲存這篇文章",
            },
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "📌 摘要與分析",
                    "weight": "bold",
                    "color": "#ffffff",
                    "size": "lg",
                },
            ],
            "backgroundColor": "#E67E22",
            "paddingAll": "md",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": title or "（無標題）",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                    "color": "#111111",
                },
                {
                    "type": "text",
                    "text": summary_analysis or "（無摘要）",
                    "wrap": True,
                    "size": "sm",
                    "color": "#333333",
                },
            ],
            "paddingAll": "lg",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": footer_contents,
            "paddingAll": "md",
        },
    }


def _snippet(text: str, limit: int = SUMMARY_SNIPPET_LENGTH) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def build_bookmark_bubble(bookmark: dict) -> dict:
    """單顆書籤 bubble：標題、摘要節錄、日期、開啟連結、刪除。"""
    created_at = bookmark.get("created_at", 0)
    date_str = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d") if created_at else ""

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": bookmark.get("title") or "（無標題）",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                    "color": "#111111",
                },
                {
                    "type": "text",
                    "text": _snippet(bookmark.get("summary", "")),
                    "wrap": True,
                    "size": "sm",
                    "color": "#555555",
                },
                {
                    "type": "text",
                    "text": f"🕐 {date_str}",
                    "size": "xs",
                    "color": "#999999",
                },
            ],
            "paddingAll": "lg",
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#2C6E49",
                    "height": "sm",
                    "flex": 2,
                    "action": {
                        "type": "uri",
                        "label": "🔗 開啟連結",
                        "uri": bookmark.get("url", ""),
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "flex": 1,
                    "action": {
                        "type": "postback",
                        "label": "🗑 刪除",
                        "data": json.dumps(
                            {"action": "delete_bookmark",
                             "id": bookmark.get("doc_id", "")},
                            ensure_ascii=False),
                        "displayText": "🗑 刪除書籤",
                    },
                },
            ],
            "paddingAll": "md",
        },
    }


def build_bookmark_carousel(bookmarks: List[dict]) -> dict:
    return {
        "type": "carousel",
        "contents": [build_bookmark_bubble(b) for b in bookmarks],
    }


def build_platform_bubble(header_text: str, color: str, body_text: str,
                          clipboard_label: str, clipboard_text: str) -> dict:
    """單一社群平台貼文 bubble：header + 內文 + 複製到剪貼簿按鈕。

    中英文貼文共用此函式（差異只在傳入的文字語言），FB／LinkedIn／Threads
    各自呼叫一次即可組出對應 bubble，避免三份平台重複的 dict 字面值。
    """
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": header_text,
                    "weight": "bold",
                    "color": "#ffffff",
                    "size": "lg",
                },
            ],
            "backgroundColor": color,
            "paddingAll": "md",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": body_text,
                    "wrap": True,
                    "size": "sm",
                    "color": "#333333",
                },
            ],
            "paddingAll": "lg",
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": color,
                    "height": "sm",
                    "action": {
                        "type": "clipboard",
                        "label": clipboard_label,
                        "clipboardText": clipboard_text,
                    },
                },
            ],
            "paddingAll": "md",
        },
    }
