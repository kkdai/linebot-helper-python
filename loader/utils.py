# Pure Python implementation - no LangChain
import re


def docs_to_str(docs: list) -> str:
    """
    Convert documents to string (no LangChain dependency)

    Args:
        docs: List of documents (can be dicts, objects with page_content, or strings)

    Returns:
        Concatenated string of all document contents
    """
    if not docs:
        return ""

    result = []
    for doc in docs:
        # Handle dict with 'page_content' key
        if isinstance(doc, dict) and 'page_content' in doc:
            result.append(doc['page_content'].strip())
        # Handle object with page_content attribute
        elif hasattr(doc, 'page_content'):
            result.append(doc.page_content.strip())
        # Handle plain strings
        elif isinstance(doc, str):
            result.append(doc.strip())
        # Fallback: convert to string
        else:
            result.append(str(doc).strip())

    return "\n".join(result)


# 沒帶協定的網址只在這些 TLD 上才算數。不用「任何 .xx」是因為那會把 main.py、
# app.json、report.md 這類檔名全部當成網址——LINE 對話裡談程式碼比談 .py 網域
# 常見得多。要新增請挑真的會被貼進來的。
_BARE_DOMAIN_TLDS = (
    "com|net|org|edu|gov|info|biz|io|ai|app|dev|co|me|tv|be|ly|cc|news|blog|xyz|"
    "tw|jp|hk|cn|kr|uk|us|de|fr|nl|au|ca|sg"
)

# 網址的結束字元。全形標點必須列進來：中文標點會直接黏著網址（「…com/x，很讚」），
# 只靠空白切不開。但中文「字」不能列——https://zh.wikipedia.org/wiki/台灣 這種
# 網址是合法的，切掉就 404。
_URL_STOP_CHARS = "。，、；：！？…「」『』（）〈〉《》【】〔〕"
_URL_CHAR = rf"[^\s{_URL_STOP_CHARS}]"

# 半形標點黏在尾巴的情況由這裡剝掉（全形的已經被上面擋在網址外）。
_TRAILING_PUNCTUATION = ".,;:!?'\")]}>"
_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{", ">": "<"}

_URL_PATTERN = re.compile(
    # 前面不能接 @ 或網域字元：擋掉 email（someone@example.com）與網址中段
    rf"(?<![@A-Za-z0-9._-])"
    rf"(?:"
    rf"https?://{_URL_CHAR}+"                                  # 帶協定
    rf"|www\.{_URL_CHAR}+"                                     # www 開頭、省略協定
    rf"|(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"       # 其餘省略協定的網域
    rf"(?:{_BARE_DOMAIN_TLDS})\b"
    rf"(?::\d+)?(?:/{_URL_CHAR}*)?"
    rf")",
    re.IGNORECASE,
)


def _trim_trailing_punctuation(url: str) -> str:
    """剝掉黏在網址尾巴的半形標點。

    成對的括號留著——維基百科的 `/wiki/Foo_(bar)` 那個 `)` 是網址的一部分，
    剝掉就 404；`(見 https://a.com/b)` 的 `)` 沒有對應的左括號，才是標點。
    """
    while url and url[-1] in _TRAILING_PUNCTUATION:
        opening = _BRACKET_PAIRS.get(url[-1])
        if opening and url.count(opening) >= url.count(url[-1]):
            break
        url = url[:-1]
    return url


def _normalize_host_case(url: str) -> str:
    """把 scheme 與 host 轉小寫，path 原樣保留（path 是區分大小寫的）。

    手打網址正是省略協定的主要來源，而手機鍵盤會把句首字母自動大寫——
    `Www.youtube.com/...` 進了 is_youtube_url() 就認不出來。
    """
    scheme, sep, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme.lower()}{sep}{host.lower()}{slash}{path}"


def find_url(input_string: str) -> list:
    """
    Find all URLs in a string using regex

    省略協定的網址（www.youtube.com/...、youtu.be/xxx）一律補上 https:// 再回傳，
    因為下游的 is_youtube_url()、爬蟲、書籤都預期拿到完整網址。

    Args:
        input_string: String to search for URLs

    Returns:
        List of URLs found in the string
    """
    urls = []
    for match in _URL_PATTERN.finditer(input_string or ""):
        url = _trim_trailing_punctuation(match.group(0))
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            url = f"https://{url}"
        urls.append(_normalize_host_case(url))
    return urls
