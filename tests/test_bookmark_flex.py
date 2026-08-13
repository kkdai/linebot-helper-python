"""測試：書籤 Flex Message 組裝與指令解析（純函式，不需 LINE SDK/API）"""
import json
import time

from services.bookmark_flex import (
    build_summary_bubble,
    build_bookmark_carousel,
    parse_bookmark_command,
)


# --- 摘要與分析 bubble（社群貼文 carousel 第一顆）---

def test_summary_bubble_contains_title_and_analysis():
    bubble = build_summary_bubble("測試標題", "這是摘要分析內容", "https://example.com", "abc123")
    text = json.dumps(bubble, ensure_ascii=False)
    assert bubble["type"] == "bubble"
    assert "測試標題" in text
    assert "這是摘要分析內容" in text


def test_summary_bubble_save_button_postback_format():
    bubble = build_summary_bubble("t", "s", "https://example.com", "abc123")
    footer_actions = [
        c["action"] for c in bubble["footer"]["contents"]
        if c.get("type") == "button"
    ]
    postbacks = [a for a in footer_actions if a["type"] == "postback"]
    assert len(postbacks) == 1

    data = json.loads(postbacks[0]["data"])
    assert data == {"action": "save_bookmark", "id": "abc123"}
    assert len(postbacks[0]["data"]) <= 300, "postback data 上限 300 字元"


def test_summary_bubble_without_doc_id_has_no_save_button():
    """Firestore 不可用（沒有候選 doc）時，不顯示會失敗的儲存按鈕。"""
    bubble = build_summary_bubble("t", "s", "https://example.com", None)
    footer = bubble.get("footer")
    if footer:
        postbacks = [
            c for c in footer["contents"]
            if c.get("type") == "button" and c["action"]["type"] == "postback"
        ]
        assert postbacks == []


# --- 書籤列表 carousel ---

def make_bookmark(i: int) -> dict:
    return {
        "doc_id": f"doc{i}",
        "url": f"https://example.com/{i}",
        "title": f"書籤標題{i}",
        "summary": f"摘要內容{i}" * 30,  # 刻意超長，驗證截斷
        "created_at": time.time(),
        "saved": True,
    }


def test_bookmark_carousel_one_bubble_per_bookmark():
    carousel = build_bookmark_carousel([make_bookmark(1), make_bookmark(2)])
    assert carousel["type"] == "carousel"
    assert len(carousel["contents"]) == 2


def test_bookmark_bubble_has_open_and_delete_actions():
    carousel = build_bookmark_carousel([make_bookmark(1)])
    bubble = carousel["contents"][0]
    actions = [
        c["action"] for c in bubble["footer"]["contents"]
        if c.get("type") == "button"
    ]
    uri_actions = [a for a in actions if a["type"] == "uri"]
    postback_actions = [a for a in actions if a["type"] == "postback"]

    assert uri_actions[0]["uri"] == "https://example.com/1"
    data = json.loads(postback_actions[0]["data"])
    assert data == {"action": "delete_bookmark", "id": "doc1"}


def test_bookmark_bubble_truncates_long_summary():
    carousel = build_bookmark_carousel([make_bookmark(1)])
    text = json.dumps(carousel, ensure_ascii=False)
    body_texts = [
        c["text"] for c in carousel["contents"][0]["body"]["contents"]
        if c.get("type") == "text"
    ]
    summary_text = max(body_texts, key=len)
    assert len(summary_text) <= 120


# --- 指令解析 ---

def test_parse_save_command_with_url():
    assert parse_bookmark_command("/save https://example.com/a") == (
        "save", "https://example.com/a")


def test_parse_list_command():
    assert parse_bookmark_command("/list") == ("list", "")
    assert parse_bookmark_command("/list  ") == ("list", "")


def test_parse_search_command_with_keyword():
    assert parse_bookmark_command("/search python 教學") == ("search", "python 教學")


def test_parse_non_bookmark_commands_return_none():
    assert parse_bookmark_command("/clear") is None
    assert parse_bookmark_command("https://example.com") is None
    assert parse_bookmark_command("一般訊息") is None
    assert parse_bookmark_command("/saved-something") is None
