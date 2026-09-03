r"""測試：find_url() 的網址偵測

背景：原本的正則是 `https?://[^\s]+`，使用者實際上很常貼沒帶協定的網址
（LINE 從別的 app 分享、手打、或從搜尋結果複製），例如
`www.youtube.com/watch?v=...`。這些完全偵測不到，整條網址流程（摘要、書籤、
研究報告、影片問答）就像沒收到網址一樣。

另一半是中文語境特有的：中文標點會直接貼著網址（`...com/x，很讚`），
`[^\s]+` 會把標點一起吃進網址裡，抓到了也爬不動。

守的是這兩個 bug class，同時要求不能誤抓 email 與檔名。
"""
from loader.utils import find_url


# --- 原本就該有的行為，不能被改壞 ---

def test_finds_plain_https_url():
    assert find_url("看這篇 https://example.com/a/b 很棒") == ["https://example.com/a/b"]


def test_finds_multiple_urls():
    assert find_url("https://a.com/1 https://b.com/2") == [
        "https://a.com/1", "https://b.com/2"]


def test_returns_empty_list_when_no_url():
    assert find_url("今天天氣不錯") == []


# --- 省略協定的網址 ---

def test_finds_www_url_without_scheme():
    assert find_url("www.youtube.com/watch?v=abc123") == [
        "https://www.youtube.com/watch?v=abc123"]


def test_finds_bare_domain_with_path():
    assert find_url("幫我看 youtu.be/dQw4w9WgXcQ") == ["https://youtu.be/dQw4w9WgXcQ"]


def test_finds_bare_domain_without_path():
    assert find_url("去 example.com 看看") == ["https://example.com"]


def test_scheme_less_url_is_recognised_as_youtube():
    # 下游 is_youtube_url() 只認 https:// 開頭，所以補協定是這個修正的重點
    from loader.url import is_youtube_url
    urls = find_url("www.youtube.com/watch?v=abc123")
    assert is_youtube_url(urls[0])


# --- 中文標點黏在網址後面 ---

def test_strips_trailing_chinese_punctuation():
    assert find_url("看 https://example.com/a，然後呢？") == ["https://example.com/a"]


def test_strips_trailing_ascii_period():
    assert find_url("see https://example.com/a.") == ["https://example.com/a"]


def test_keeps_balanced_parentheses_in_url():
    url = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert find_url(f"參考 {url} 這頁") == [url]


def test_strips_unbalanced_closing_parenthesis():
    assert find_url("(見 https://example.com/a)") == ["https://example.com/a"]


# --- 不能誤抓 ---

def test_ignores_email_address():
    assert find_url("寄到 someone@example.com 給我") == []


def test_ignores_source_file_names():
    assert find_url("錯誤在 main.py 第 12 行，設定看 app.json") == []


def test_ignores_version_numbers():
    assert find_url("升級到 fastapi 0.141.1") == []


def test_lowercases_host_but_not_path():
    # 手打網址正是省略協定的主要來源，而手機鍵盤會把句首字母自動大寫
    assert find_url("Www.YouTube.com/watch?v=AbC") == [
        "https://www.youtube.com/watch?v=AbC"]
