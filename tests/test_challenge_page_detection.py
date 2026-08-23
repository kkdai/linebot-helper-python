"""測試：Cloudflare/WAF 人機驗證頁偵測

背景：acm.org 這類網站被 Cloudflare 擋住時，httpx/cloudscraper 因為呼叫
raise_for_status() 會正確失敗、觸發 fallback；但 SingleFile 用 headless
Chromium 渲染頁面，不管拿到的是不是驗證頁都當成「抓取成功」回傳，導致驗證頁
內容被當成文章送去給 Gemini，產生莫名其妙的摘要而不是明確的錯誤訊息。

is_challenge_page 是共用偵測邏輯，httpx/cloudscraper/singlefile 三個 loader
抓到驗證頁都要主動 raise，讓 loader/url.py 的 fallback chain 換下一種方法。
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from loader.html import is_challenge_page, load_html_with_httpx, load_html_with_cloudscraper
from loader.singlefile import load_singlefile_html

CLOUDFLARE_CHALLENGE_HTML = """
<html><head><title>Attention Required! | Cloudflare</title></head>
<body><h1>Attention Required!</h1><p>Please complete the security check.</p></body></html>
"""

NORMAL_ARTICLE_HTML = """
<html><head><title>Russ Cox - People of ACM</title></head>
<body><h1>Russ Cox</h1><p>這是一篇正常的文章內容，講的是 Russ Cox 的訪談。</p></body></html>
"""


# --- 純函式：is_challenge_page ---

def test_detects_cloudflare_attention_required_title():
    assert is_challenge_page("Attention Required! | Cloudflare 這是驗證頁內文")


def test_detects_just_a_moment_challenge():
    assert is_challenge_page("Just a moment...請稍候，我們正在確認您的連線安全")


def test_normal_article_is_not_a_challenge_page():
    assert not is_challenge_page("這是一篇關於遠端工作如何提升生產力的正常文章內容")


def test_empty_text_is_not_a_challenge_page():
    assert not is_challenge_page("")


# --- httpx/cloudscraper：200 回應但內容是驗證頁 ---

def _fake_response(html: str):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def test_load_html_with_httpx_raises_on_challenge_page():
    with patch("loader.html.httpx.get", return_value=_fake_response(CLOUDFLARE_CHALLENGE_HTML)):
        with pytest.raises(RuntimeError, match="bot-challenge"):
            load_html_with_httpx("https://www.acm.org/some-article")


def test_load_html_with_httpx_returns_normal_content():
    with patch("loader.html.httpx.get", return_value=_fake_response(NORMAL_ARTICLE_HTML)):
        result = load_html_with_httpx("https://www.acm.org/some-article")
    assert "Russ Cox" in result


def test_load_html_with_cloudscraper_raises_on_challenge_page():
    fake_scraper = MagicMock()
    fake_scraper.get.return_value = _fake_response(CLOUDFLARE_CHALLENGE_HTML)
    with patch("loader.html.cloudscraper.create_scraper", return_value=fake_scraper):
        with pytest.raises(RuntimeError, match="bot-challenge"):
            load_html_with_cloudscraper("https://www.acm.org/some-article")


# --- SingleFile：headless Chromium 渲染完，不看狀態碼，只看內容 ---

@pytest.mark.asyncio
async def test_load_singlefile_html_raises_on_challenge_page():
    fd, path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(fd, "w") as f:
        f.write(CLOUDFLARE_CHALLENGE_HTML)

    async def fake_download(url):
        return path

    with patch("loader.singlefile.singlefile_download", new=fake_download):
        with pytest.raises(RuntimeError, match="bot-challenge"):
            await load_singlefile_html("https://www.acm.org/some-article")

    assert not os.path.exists(path), "偵測到驗證頁後也要清掉暫存檔"


@pytest.mark.asyncio
async def test_load_singlefile_html_returns_normal_content():
    fd, path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(fd, "w") as f:
        f.write(NORMAL_ARTICLE_HTML)

    async def fake_download(url):
        return path

    with patch("loader.singlefile.singlefile_download", new=fake_download):
        result = await load_singlefile_html("https://www.acm.org/some-article")

    assert "Russ Cox" in result
