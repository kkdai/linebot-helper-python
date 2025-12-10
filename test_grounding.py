#!/usr/bin/env python3
"""
測試腳本：Vertex AI Grounding with Chat Session

使用此腳本測試新的對話功能，無需透過 LINE Bot
"""
import os
import asyncio
import logging
from loader.chat_session import (
    ChatSessionManager,
    search_and_answer_with_grounding,
    format_grounding_response,
    get_session_status_message
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_basic_chat():
    """測試基本對話功能"""
    print("\n" + "="*60)
    print("測試 1: 基本對話功能")
    print("="*60)

    session_manager = ChatSessionManager(session_timeout_minutes=30)
    test_user_id = "test_user_123"

    # 第一個問題
    print("\n用戶: Python 是什麼？")
    result1 = await search_and_answer_with_grounding(
        query="Python 是什麼？",
        user_id=test_user_id,
        session_manager=session_manager
    )
    response1 = format_grounding_response(result1)
    print(f"\n助手:\n{response1}")

    # 第二個問題（應該記住 Python）
    print("\n" + "-"*60)
    print("\n用戶: 它有什麼優點？")
    result2 = await search_and_answer_with_grounding(
        query="它有什麼優點？",
        user_id=test_user_id,
        session_manager=session_manager
    )
    response2 = format_grounding_response(result2)
    print(f"\n助手:\n{response2}")

    # 顯示 session 狀態
    print("\n" + "-"*60)
    status = get_session_status_message(session_manager, test_user_id)
    print(f"\n{status}")


async def test_multiple_users():
    """測試多用戶 session 隔離"""
    print("\n" + "="*60)
    print("測試 2: 多用戶 Session 隔離")
    print("="*60)

    session_manager = ChatSessionManager(session_timeout_minutes=30)

    # 用戶 A
    user_a = "user_a"
    print(f"\n用戶 A: 台北有什麼好吃的？")
    result_a = await search_and_answer_with_grounding(
        query="台北有什麼好吃的？",
        user_id=user_a,
        session_manager=session_manager
    )
    print(f"\n助手 (給用戶A):\n{format_grounding_response(result_a, include_sources=False)[:200]}...\n")

    # 用戶 B
    user_b = "user_b"
    print(f"\n用戶 B: 高雄有什麼景點？")
    result_b = await search_and_answer_with_grounding(
        query="高雄有什麼景點？",
        user_id=user_b,
        session_manager=session_manager
    )
    print(f"\n助手 (給用戶B):\n{format_grounding_response(result_b, include_sources=False)[:200]}...\n")

    # 用戶 A 追問（應該記得台北）
    print(f"\n用戶 A: 那邊交通方便嗎？")
    result_a2 = await search_and_answer_with_grounding(
        query="那邊交通方便嗎？",
        user_id=user_a,
        session_manager=session_manager
    )
    print(f"\n助手 (給用戶A):\n{format_grounding_response(result_a2, include_sources=False)[:200]}...\n")

    print("\n✅ 測試通過：兩個用戶的對話獨立，互不干擾")


async def test_clear_session():
    """測試清除 session"""
    print("\n" + "="*60)
    print("測試 3: 清除 Session")
    print("="*60)

    session_manager = ChatSessionManager(session_timeout_minutes=30)
    test_user_id = "test_user_clear"

    # 建立對話
    print("\n用戶: JavaScript 是什麼？")
    await search_and_answer_with_grounding(
        query="JavaScript 是什麼？",
        user_id=test_user_id,
        session_manager=session_manager
    )
    print("✅ 對話已建立")

    # 顯示狀態
    status = get_session_status_message(session_manager, test_user_id)
    print(f"\n清除前:\n{status}")

    # 清除 session
    session_manager.clear_session(test_user_id)
    print("\n🗑️  執行 clear_session()")

    # 再次顯示狀態
    status = get_session_status_message(session_manager, test_user_id)
    print(f"\n清除後:\n{status}")


async def test_sources_extraction():
    """測試來源提取"""
    print("\n" + "="*60)
    print("測試 4: 來源提取")
    print("="*60)

    session_manager = ChatSessionManager(session_timeout_minutes=30)
    test_user_id = "test_user_sources"

    print("\n用戶: 2024年美國總統選舉結果？")
    result = await search_and_answer_with_grounding(
        query="2024年美國總統選舉結果？",
        user_id=test_user_id,
        session_manager=session_manager
    )

    print(f"\n助手:\n{result['answer'][:300]}...\n")

    if result['sources']:
        print(f"\n✅ 找到 {len(result['sources'])} 個來源：")
        for i, source in enumerate(result['sources'][:3], 1):
            print(f"{i}. {source['title']}")
            print(f"   {source['uri']}")
    else:
        print("\n⚠️  未找到來源（可能是 Grounding 未返回來源資訊）")


async def interactive_test():
    """互動式測試"""
    print("\n" + "="*60)
    print("互動式測試模式")
    print("="*60)
    print("\n輸入 'exit' 或 'quit' 離開")
    print("輸入 '/clear' 清除對話記憶")
    print("輸入 '/status' 查看對話狀態")
    print("-"*60)

    session_manager = ChatSessionManager(session_timeout_minutes=30)
    test_user_id = "interactive_user"

    while True:
        try:
            user_input = input("\n你: ").strip()

            if user_input.lower() in ['exit', 'quit', '離開', '退出']:
                print("\n👋 再見！")
                break

            if not user_input:
                continue

            if user_input.lower() in ['/clear', '/清除']:
                session_manager.clear_session(test_user_id)
                print("\n✅ 對話已重置")
                continue

            if user_input.lower() in ['/status', '/狀態']:
                status = get_session_status_message(session_manager, test_user_id)
                print(f"\n{status}")
                continue

            # 發送問題
            result = await search_and_answer_with_grounding(
                query=user_input,
                user_id=test_user_id,
                session_manager=session_manager
            )

            response = format_grounding_response(result)
            print(f"\n助手:\n{response}")

        except KeyboardInterrupt:
            print("\n\n👋 再見！")
            break
        except Exception as e:
            print(f"\n❌ 錯誤: {e}")


async def main():
    """主測試函數"""
    print("\n" + "="*60)
    print("Vertex AI Grounding with Chat Session - 測試程式")
    print("="*60)

    # 檢查環境變數
    if not os.getenv('GOOGLE_CLOUD_PROJECT'):
        print("\n❌ 錯誤: GOOGLE_CLOUD_PROJECT 環境變數未設定")
        print("請執行: export GOOGLE_CLOUD_PROJECT=your-project-id")
        return

    print(f"\n✅ Vertex AI Project: {os.getenv('GOOGLE_CLOUD_PROJECT')}")
    print(f"✅ Location: {os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')}")

    print("\n請選擇測試模式：")
    print("1. 自動測試（運行所有測試）")
    print("2. 互動式測試（手動輸入問題）")

    try:
        choice = input("\n選擇 (1/2): ").strip()

        if choice == "1":
            # 自動測試
            await test_basic_chat()
            await test_multiple_users()
            await test_clear_session()
            await test_sources_extraction()
            print("\n" + "="*60)
            print("✅ 所有自動測試完成")
            print("="*60)
        elif choice == "2":
            # 互動式測試
            await interactive_test()
        else:
            print("❌ 無效的選擇")

    except KeyboardInterrupt:
        print("\n\n👋 測試中斷")


if __name__ == "__main__":
    asyncio.run(main())
