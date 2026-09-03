"""測試：postback action 的 handler 與按鈕必須成對存在

背景：`"youtube_summary"` 在 `main.py` 有完整的 handler，但 repo 裡沒有任何地方
會產生送出這個 action 的按鈕，等於一整段永遠跑不到的死碼——review 時看起來功能
還在，實際上使用者按不到。

這裡守的是 bug class 而非單一字串：只要有人加了 handler 卻忘了掛按鈕（或反過來
砍掉按鈕卻留下 handler），這個測試就會失敗。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 產生按鈕的地方：正式程式碼，不含 tests/（測試裡的 payload 不算真的入口）
PRODUCTION_GLOBS = ("main.py", "agents/*.py", "loader/*.py", "services/*.py", "tools/*.py")

EMIT_PATTERN = re.compile(r'"action":\s*"([a-zA-Z_]+)"')
DISPATCH_PATTERN = re.compile(r'action_value\s*==\s*"([a-zA-Z_]+)"')


def _production_sources() -> list[Path]:
    paths: list[Path] = []
    for pattern in PRODUCTION_GLOBS:
        paths.extend(sorted(ROOT.glob(pattern)))
    return paths


def _emitted_actions() -> set[str]:
    actions: set[str] = set()
    for path in _production_sources():
        actions.update(EMIT_PATTERN.findall(path.read_text(encoding="utf-8")))
    return actions


def _dispatched_actions() -> set[str]:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    return set(DISPATCH_PATTERN.findall(source))


def test_every_postback_handler_has_a_button_that_sends_it():
    orphans = _dispatched_actions() - _emitted_actions()
    assert not orphans, (
        f"這些 postback action 有 handler 但沒有任何按鈕會送出，是死碼：{sorted(orphans)}"
    )


def test_every_postback_button_has_a_handler():
    unhandled = _emitted_actions() - _dispatched_actions()
    assert not unhandled, (
        f"這些按鈕送出的 postback action 沒有對應的 handler，按下去不會有反應：{sorted(unhandled)}"
    )
