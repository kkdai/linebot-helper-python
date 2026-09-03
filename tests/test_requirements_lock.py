r"""測試：requirements.txt 與 requirements-lock.txt 不能各說各話

背景：`Dockerfile` 把 `requirements-lock.txt` 複製成 `requirements.txt` 再安裝，
所以正式環境裝的完全是鎖定檔那一份。`google-adk` 只寫在 requirements.txt、
沒進鎖定檔，正式環境就一直沒裝——而三個呼叫端都有 import guard 會安靜降級，
沒有任何錯誤，看 log 也只有一行 warning。加了套件卻沒進正式環境，這個 bug class
不該靠人眼發現。

反過來的方向刻意不檢查：鎖定檔本來就會多出間接依賴（aiohttp 等）。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# pip 的套件名比對規則：大小寫不分、`-` 與 `_`、`.` 等價（PEP 503）
def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_names(path: Path) -> set[str]:
    names = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        # 去掉 extras 與版本條件：uvicorn[standard]==0.32.1 -> uvicorn
        name = re.split(r"[\[<>=!;~ ]", line, maxsplit=1)[0].strip()
        if name:
            names.add(_canonical(name))
    return names


def test_every_declared_package_is_in_the_lock_file():
    declared = _package_names(ROOT / "requirements.txt")
    locked = _package_names(ROOT / "requirements-lock.txt")
    missing = declared - locked
    assert not missing, (
        "這些套件寫在 requirements.txt 但不在 requirements-lock.txt，"
        f"正式環境（Dockerfile 裝的是鎖定檔）不會安裝：{sorted(missing)}"
    )
