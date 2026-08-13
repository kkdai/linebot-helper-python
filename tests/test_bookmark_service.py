"""測試：書籤/稍後讀系統的核心邏輯（BookmarkService）

規格：docs/superpowers/specs/2026-08-13-bookmark-system-design.md
- /save 直存（saved=True）、社群貼文 carousel 先寫候選（saved=False）再確認
- 同使用者同網址去重（doc id = sha1 前 20 碼）
- /list 依 created_at 新→舊、上限 10；/search 對 title+summary 子字串比對
- 確認/刪除必須驗證 doc 屬於該使用者
- 寫入候選時清掉 7 天以上的舊候選
"""
import time

from services.bookmark_service import BookmarkService
from tests.fakes import FakeStore, UnavailableStore

UID = "U-owner"
OTHER_UID = "U-someone-else"


def make_service():
    store = FakeStore()
    return BookmarkService(store=store), store


# --- 直存與去重 ---

def test_save_direct_creates_saved_bookmark():
    svc, _ = make_service()
    doc_id = svc.save_direct(UID, "https://example.com/a", "標題A", "摘要A")

    items = svc.list_saved(UID)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/a"
    assert items[0]["title"] == "標題A"
    assert items[0]["saved"] is True
    assert items[0]["source"] == "command"
    assert items[0]["doc_id"] == doc_id


def test_same_url_same_user_is_deduplicated():
    svc, store = make_service()
    id1 = svc.save_direct(UID, "https://example.com/a", "舊標題", "舊摘要")
    id2 = svc.save_direct(UID, "https://example.com/a", "新標題", "新摘要")

    assert id1 == id2
    items = svc.list_saved(UID)
    assert len(items) == 1
    assert items[0]["title"] == "新標題"


def test_same_url_different_users_are_separate():
    svc, _ = make_service()
    id1 = svc.save_direct(UID, "https://example.com/a", "t", "s")
    id2 = svc.save_direct(OTHER_UID, "https://example.com/a", "t", "s")
    assert id1 != id2


def test_doc_id_is_short_enough_for_postback_data():
    """postback data 上限 300 字元，JSON 包裝後 doc id 必須夠短。"""
    svc, _ = make_service()
    doc_id = svc.save_direct(UID, "https://example.com/" + "x" * 500, "t", "s")
    assert len(doc_id) <= 20


# --- 候選 → 確認流程 ---

def test_candidate_not_listed_until_confirmed():
    svc, _ = make_service()
    doc_id = svc.save_candidate(UID, "https://example.com/b", "標題B", "摘要B")

    assert svc.list_saved(UID) == []

    confirmed = svc.confirm_save(UID, doc_id)
    assert confirmed is not None
    assert confirmed["title"] == "標題B"

    items = svc.list_saved(UID)
    assert len(items) == 1
    assert items[0]["source"] == "button"


def test_confirm_save_rejects_other_users_doc():
    svc, _ = make_service()
    doc_id = svc.save_candidate(UID, "https://example.com/b", "t", "s")

    assert svc.confirm_save(OTHER_UID, doc_id) is None
    assert svc.list_saved(OTHER_UID) == []


def test_confirm_save_unknown_id_returns_none():
    svc, _ = make_service()
    assert svc.confirm_save(UID, "nonexistent") is None


def test_stale_candidates_cleaned_on_new_candidate():
    svc, store = make_service()
    old_id = svc.save_candidate(UID, "https://example.com/old", "舊", "舊")

    # 把候選改成 8 天前
    doc = store.load(old_id)
    doc["created_at"] = time.time() - 8 * 86400
    store.save(old_id, doc)

    svc.save_candidate(UID, "https://example.com/new", "新", "新")

    assert store.load(old_id) is None, "7 天以上的未儲存候選應被清掉"


def test_old_saved_bookmarks_are_never_cleaned():
    svc, store = make_service()
    doc_id = svc.save_direct(UID, "https://example.com/keep", "留", "留")
    doc = store.load(doc_id)
    doc["created_at"] = time.time() - 30 * 86400
    store.save(doc_id, doc)

    svc.save_candidate(UID, "https://example.com/new", "新", "新")

    assert store.load(doc_id) is not None, "已儲存的書籤不受候選清理影響"


# --- list 與 search ---

def test_list_orders_newest_first_and_limits():
    svc, store = make_service()
    for i in range(15):
        doc_id = svc.save_direct(UID, f"https://example.com/{i}", f"標題{i}", "s")
        doc = store.load(doc_id)
        doc["created_at"] = 1000.0 + i
        store.save(doc_id, doc)

    items = svc.list_saved(UID, limit=10)
    assert len(items) == 10
    assert items[0]["title"] == "標題14"
    assert items[-1]["title"] == "標題5"


def test_list_excludes_other_users():
    svc, _ = make_service()
    svc.save_direct(UID, "https://example.com/mine", "我的", "s")
    svc.save_direct(OTHER_UID, "https://example.com/theirs", "別人的", "s")

    titles = [b["title"] for b in svc.list_saved(UID)]
    assert titles == ["我的"]


def test_search_matches_title_and_summary_case_insensitive():
    svc, _ = make_service()
    svc.save_direct(UID, "https://example.com/1", "Python 教學", "介紹基礎語法")
    svc.save_direct(UID, "https://example.com/2", "美食清單", "台北 python 社群聚餐")
    svc.save_direct(UID, "https://example.com/3", "旅遊筆記", "京都行程")

    results = svc.search(UID, "PYTHON")
    urls = {b["url"] for b in results}
    assert urls == {"https://example.com/1", "https://example.com/2"}


def test_search_no_results_returns_empty():
    svc, _ = make_service()
    svc.save_direct(UID, "https://example.com/1", "標題", "摘要")
    assert svc.search(UID, "不存在的詞") == []


# --- 刪除 ---

def test_delete_own_bookmark():
    svc, _ = make_service()
    doc_id = svc.save_direct(UID, "https://example.com/a", "t", "s")
    assert svc.delete(UID, doc_id) is True
    assert svc.list_saved(UID) == []


def test_delete_rejects_other_users_doc():
    svc, _ = make_service()
    doc_id = svc.save_direct(UID, "https://example.com/a", "t", "s")
    assert svc.delete(OTHER_UID, doc_id) is False
    assert len(svc.list_saved(UID)) == 1


# --- Firestore 降級 ---

def test_unavailable_store_reports_not_available():
    svc = BookmarkService(store=UnavailableStore())
    assert svc.available is False
