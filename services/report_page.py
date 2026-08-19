"""研究報告網頁渲染

Markdown（Gemini 產出）轉 HTML，套進行動裝置優先的閱讀版型。
純函式、inline CSS、無外部資源，方便單元測試也避免 CSP/CDN 問題。
"""
from datetime import datetime
from typing import List, Optional

import markdown as md

_PAGE_CSS = """
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
      "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
    line-height: 1.75; color: #1a1a1a; background: #f5f5f4;
  }
  .container { max-width: 720px; margin: 0 auto; padding: 24px 20px 48px; }
  .card { background: #ffffff; border-radius: 12px; padding: 28px 24px;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  h1 { font-size: 1.5rem; line-height: 1.4; margin: 0 0 4px; }
  h2 { font-size: 1.2rem; margin-top: 2em; padding-bottom: .3em;
       border-bottom: 2px solid #E67E22; }
  h3 { font-size: 1.05rem; margin-top: 1.6em; }
  a { color: #C0611A; word-break: break-all; }
  blockquote { margin: 1em 0; padding: .5em 1em; border-left: 4px solid #E67E22;
               background: #faf3ec; color: #555; }
  code { background: #f0f0ef; padding: .15em .4em; border-radius: 4px;
         font-size: .9em; }
  table { border-collapse: collapse; width: 100%; display: block;
          overflow-x: auto; }
  th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; }
  .meta { color: #888; font-size: .85rem; margin-bottom: 24px; }
  .sources { margin-top: 32px; font-size: .9rem; }
  .sources li { margin-bottom: .5em; }
  @media (prefers-color-scheme: dark) {
    body { background: #191918; color: #e8e8e6; }
    .card { background: #242422; box-shadow: none; }
    blockquote { background: #2e2a24; color: #bbb; }
    code { background: #333; }
    th, td { border-color: #444; }
    a { color: #e89a55; }
  }
"""


def render_report_page(title: str, markdown_text: str, url: str,
                       sources: Optional[List[dict]] = None) -> str:
    body_html = md.markdown(markdown_text or "", extensions=["extra"])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    sources_html = ""
    if sources:
        items = "".join(
            f'<li><a href="{s.get("uri", "")}" target="_blank" rel="noopener">'
            f'{s.get("title") or s.get("uri", "")}</a></li>'
            for s in sources if s.get("uri")
        )
        if items:
            sources_html = (
                '<div class="sources"><h2>📚 參考來源</h2>'
                f'<ol>{items}</ol></div>'
            )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title or '研究報告'}</title>
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="container">
  <div class="card">
    <h1>🔬 {title or '研究報告'}</h1>
    <div class="meta">
      產生時間：{generated_at}<br>
      原文：<a href="{url}" target="_blank" rel="noopener">{url}</a>
    </div>
    {body_html}
    {sources_html}
  </div>
</div>
</body>
</html>"""


def render_expired_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>找不到報告</title>
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="container">
  <div class="card">
    <h1>🔍 找不到這份報告</h1>
    <p>這個連結對應的研究報告不存在，可能是網址有誤。</p>
    <p>回到 LINE 重新點「📄 詳細研究報告」即可再產生一份。</p>
  </div>
</div>
</body>
</html>"""
