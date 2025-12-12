# Chat Session Management with Vertex AI Grounding
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Use google-genai SDK for Vertex AI
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

# Configure logging
logger = logging.getLogger(__name__)

# Vertex AI configuration
VERTEX_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
VERTEX_LOCATION = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')


class ChatSessionManager:
    """
    管理用戶的聊天 session，支援對話記憶和自動過期
    """

    def __init__(self, session_timeout_minutes: int = 30):
        """
        初始化 Session Manager

        Args:
            session_timeout_minutes: Session 過期時間（分鐘），預設 30 分鐘
        """
        self.sessions: Dict[str, dict] = {}  # {user_id: session_data}
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        # 創建共享的 Vertex AI client（重要：保持 client 實例不被關閉）
        self.client = self._create_client()
        logger.info(f"ChatSessionManager initialized with {session_timeout_minutes}min timeout")

    def _create_client(self) -> genai.Client:
        """創建 Vertex AI client"""
        if not GENAI_AVAILABLE:
            raise ImportError("google-genai package not available")
        if not VERTEX_PROJECT:
            raise ValueError("GOOGLE_CLOUD_PROJECT not set")

        logger.info(f"Creating Vertex AI client for project {VERTEX_PROJECT}")
        return genai.Client(
            vertexai=True,
            project=VERTEX_PROJECT,
            location=VERTEX_LOCATION,
            http_options=types.HttpOptions(api_version="v1")
        )

    def _is_session_expired(self, session_data: dict) -> bool:
        """檢查 session 是否過期"""
        last_active = session_data.get('last_active')
        if not last_active:
            return True
        return datetime.now() - last_active >= self.session_timeout

    def get_or_create_session(self, user_id: str) -> Tuple[object, List[dict]]:
        """
        獲取或創建用戶的聊天 session

        Args:
            user_id: LINE 用戶 ID

        Returns:
            (chat_session, history): Chat session 物件和對話歷史
        """
        now = datetime.now()

        # 檢查是否有現有 session
        if user_id in self.sessions:
            session_data = self.sessions[user_id]

            # 檢查是否過期
            if not self._is_session_expired(session_data):
                # 更新最後活動時間
                session_data['last_active'] = now
                logger.info(f"Reusing existing session for user {user_id}")
                return session_data['chat'], session_data['history']
            else:
                logger.info(f"Session expired for user {user_id}, creating new one")

        # 創建新 session
        logger.info(f"Creating new session for user {user_id}")

        try:
            # 啟用 Google Search Grounding
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=2048,
                # 關鍵：啟用 Google Search
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )

            # 創建 chat session（使用共享的 client）
            chat = self.client.chats.create(
                model="gemini-3-pro-preview",
                config=config
            )

            self.sessions[user_id] = {
                'chat': chat,
                'last_active': now,
                'history': [],
                'created_at': now
            }

            logger.info(f"Chat session created successfully for user {user_id}")
            return chat, []

        except Exception as e:
            logger.error(f"Failed to create chat session: {e}", exc_info=True)
            raise

    def add_to_history(self, user_id: str, role: str, content: str) -> None:
        """
        記錄對話歷史

        Args:
            user_id: LINE 用戶 ID
            role: "user" 或 "assistant"
            content: 對話內容
        """
        if user_id in self.sessions:
            self.sessions[user_id]['history'].append({
                'role': role,
                'content': content,
                'timestamp': datetime.now()
            })

            # 限制歷史長度（保留最近 20 條訊息）
            if len(self.sessions[user_id]['history']) > 20:
                self.sessions[user_id]['history'] = \
                    self.sessions[user_id]['history'][-20:]

            logger.debug(f"Added to history for user {user_id}: {role}")

    def clear_session(self, user_id: str) -> bool:
        """
        清除用戶的 session

        Args:
            user_id: LINE 用戶 ID

        Returns:
            是否成功清除
        """
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"Cleared session for user {user_id}")
            return True
        return False

    def get_session_info(self, user_id: str) -> Optional[dict]:
        """
        獲取 session 資訊

        Args:
            user_id: LINE 用戶 ID

        Returns:
            Session 資訊字典，如果不存在則返回 None
        """
        if user_id not in self.sessions:
            return None

        session_data = self.sessions[user_id]
        return {
            'history_count': len(session_data['history']),
            'created_at': session_data['created_at'],
            'last_active': session_data['last_active'],
            'is_expired': self._is_session_expired(session_data)
        }

    def cleanup_expired_sessions(self) -> int:
        """
        清理過期的 sessions

        Returns:
            清理的 session 數量
        """
        expired_users = [
            user_id for user_id, session_data in self.sessions.items()
            if self._is_session_expired(session_data)
        ]

        for user_id in expired_users:
            del self.sessions[user_id]

        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired sessions")

        return len(expired_users)


async def search_and_answer_with_grounding(
    query: str,
    user_id: str,
    session_manager: ChatSessionManager
) -> dict:
    """
    使用 Vertex AI Grounding 搜尋並回答問題

    Args:
        query: 用戶問題
        user_id: LINE 用戶 ID
        session_manager: Session 管理器

    Returns:
        回答結果字典，包含 answer, sources, has_history
    """
    try:
        # 獲取或創建 chat session
        chat, history = session_manager.get_or_create_session(user_id)

        # 構建 prompt（加入繁體中文指示）
        prompt = f"""請用台灣用語的繁體中文回答以下問題。
如果需要最新資訊，請搜尋網路並提供準確的答案。
請提供詳細且有用的回答，並確保資訊來源可靠。
請不要使用 markdown 格式（不要用 **、##、- 等符號）。使用純文字回答。

問題：{query}"""

        logger.info(f"Sending message to Grounding API for user {user_id}")

        # 發送訊息
        response = chat.send_message(prompt)

        # 檢查 response.text 是否存在
        if not response.text:
            # 記錄詳細的 response 結構以便調試
            logger.error(f"Response.text is None. Response structure:")
            logger.error(f"  - Has candidates: {hasattr(response, 'candidates')}")
            if hasattr(response, 'candidates') and response.candidates:
                for i, candidate in enumerate(response.candidates):
                    logger.error(f"  - Candidate {i}:")
                    logger.error(f"    - Has content: {hasattr(candidate, 'content')}")
                    logger.error(f"    - Finish reason: {getattr(candidate, 'finish_reason', 'N/A')}")
                    if hasattr(candidate, 'safety_ratings'):
                        logger.error(f"    - Safety ratings: {candidate.safety_ratings}")

            # 嘗試從 candidates 中獲取文本
            response_text = None
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text'):
                                response_text = part.text
                                break

            if not response_text:
                raise ValueError("API returned empty response. This may be due to content filtering or rate limiting.")

            logger.info(f"Received response from Grounding API: {response_text[:100]}...")
        else:
            response_text = response.text
            logger.info(f"Received response from Grounding API: {response_text[:100]}...")

        # 記錄到歷史
        session_manager.add_to_history(user_id, "user", query)
        session_manager.add_to_history(user_id, "assistant", response_text)

        # 提取引用來源（如果有）
        sources = []
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'grounding_metadata'):
                    metadata = candidate.grounding_metadata
                    if hasattr(metadata, 'grounding_chunks'):
                        for chunk in metadata.grounding_chunks:
                            if hasattr(chunk, 'web'):
                                sources.append({
                                    'title': getattr(chunk.web, 'title', 'Unknown'),
                                    'uri': getattr(chunk.web, 'uri', '')
                                })
                        logger.info(f"Extracted {len(sources)} sources from grounding metadata")
        except Exception as e:
            logger.warning(f"Failed to extract sources: {e}")

        return {
            'answer': response_text,
            'sources': sources,
            'has_history': len(history) > 0
        }

    except Exception as e:
        logger.error(f"Grounding search failed: {e}", exc_info=True)
        raise


def format_grounding_response(result: dict, include_sources: bool = True) -> str:
    """
    格式化 Grounding 回應

    Args:
        result: search_and_answer_with_grounding 的返回結果
        include_sources: 是否包含參考來源

    Returns:
        格式化後的回應文字
    """
    text = result['answer']

    # 加入 session 指示器（如果是對話中）
    if result['has_history']:
        text = f"💬 [對話中]\n\n{text}"

    # 加入來源（如果有且需要顯示）
    if include_sources and result['sources']:
        text += "\n\n📚 參考來源：\n"
        # 最多顯示 3 個來源
        for i, source in enumerate(result['sources'][:3], 1):
            title = source.get('title', 'Unknown')
            uri = source.get('uri', '')
            if uri:
                text += f"{i}. {title}\n   {uri}\n"

    return text


def get_session_status_message(
    session_manager: ChatSessionManager,
    user_id: str
) -> str:
    """
    獲取 session 狀態訊息

    Args:
        session_manager: Session 管理器
        user_id: LINE 用戶 ID

    Returns:
        狀態訊息文字
    """
    info = session_manager.get_session_info(user_id)

    if not info:
        return "📊 目前沒有進行中的對話。\n\n發送任何訊息開始新對話！"

    status = f"""📊 對話狀態

💬 對話輪數：{info['history_count']} 條訊息
⏰ 開始時間：{info['created_at'].strftime('%Y-%m-%d %H:%M')}
🕐 最後活動：{info['last_active'].strftime('%H:%M')}

使用 /clear 清除對話記憶"""

    return status
