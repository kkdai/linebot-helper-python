"""
Chat Agent

ADK-based conversational agent with Google Search Grounding support.
Handles general text conversations with memory and web search capabilities.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

try:
    from google.adk.agents import Agent
    from google.adk.runners import InMemoryRunner
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False
    logging.warning("google-adk package not available, using fallback implementation")

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logging.error("google-genai package not available")

from config.agent_config import AgentConfig, get_agent_config

logger = logging.getLogger(__name__)


# Agent instruction for chat conversations
CHAT_AGENT_INSTRUCTION = """你是一個智能助手，專門回答用戶的問題。

## 回應原則
1. 使用台灣用語的繁體中文回答
2. 如果需要最新資訊，請搜尋網路並提供準確的答案
3. 提供詳細且有用的回答，確保資訊來源可靠
4. 不要使用 markdown 格式（不要用 **、##、- 等符號），使用純文字回答
5. 回答要簡潔但完整，適合在 LINE 訊息中閱讀

## 回應格式
- 直接回答問題，不需要開場白
- 如果有多個重點，使用數字編號（1. 2. 3.）
- 適當使用換行來提高可讀性
"""


class ChatAgent:
    """
    ADK-based Chat Agent with conversation memory and Google Search Grounding.

    This agent handles general text conversations, maintains conversation history,
    and can search the web for up-to-date information.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize ChatAgent.

        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or get_agent_config()
        self.sessions: Dict[str, dict] = {}
        self.session_timeout = timedelta(minutes=self.config.session_timeout_minutes)

        # Initialize Vertex AI client
        self.client = self._create_client()

        # Initialize ADK agent if available
        if ADK_AVAILABLE:
            self._init_adk_agent()
        else:
            self.adk_agent = None

        logger.info(f"ChatAgent initialized (ADK: {ADK_AVAILABLE})")

    def _create_client(self):
        """Create Vertex AI client"""
        if not GENAI_AVAILABLE:
            raise ImportError("google-genai package not available")

        return genai.Client(
            vertexai=True,
            project=self.config.project_id,
            location=self.config.location,
            http_options=types.HttpOptions(api_version="v1")
        )

    def _init_adk_agent(self):
        """Initialize ADK agent (for future multi-agent orchestration)"""
        try:
            self.adk_agent = Agent(
                name="chat_agent",
                model=self.config.chat_model,
                description="對話式問答 Agent，處理一般文字訊息並支援 Google Search Grounding",
                instruction=CHAT_AGENT_INSTRUCTION,
                tools=[],  # Tools will be added in Phase 3
            )
            logger.info("ADK Chat Agent created successfully")
        except Exception as e:
            logger.warning(f"Failed to create ADK agent: {e}")
            self.adk_agent = None

    def _is_session_expired(self, session_data: dict) -> bool:
        """Check if session is expired"""
        last_active = session_data.get('last_active')
        if not last_active:
            return True
        return datetime.now() - last_active >= self.session_timeout

    def get_or_create_session(self, user_id: str) -> Tuple[Any, List[dict]]:
        """
        Get or create a chat session for a user.

        Args:
            user_id: User identifier

        Returns:
            Tuple of (chat_session, history)
        """
        now = datetime.now()

        if user_id in self.sessions:
            session_data = self.sessions[user_id]

            if not self._is_session_expired(session_data):
                session_data['last_active'] = now
                logger.info(f"Reusing session for user {user_id}")
                return session_data['chat'], session_data['history']
            else:
                logger.info(f"Session expired for user {user_id}")

        # Create new session
        logger.info(f"Creating new session for user {user_id}")

        chat_config = types.GenerateContentConfig(
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_output_tokens,
        )

        # Enable Google Search Grounding if configured
        if self.config.enable_grounding:
            chat_config = types.GenerateContentConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_output_tokens,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )

        chat = self.client.chats.create(
            model=self.config.chat_model,
            config=chat_config
        )

        self.sessions[user_id] = {
            'chat': chat,
            'last_active': now,
            'history': [],
            'created_at': now
        }

        return chat, []

    def add_to_history(self, user_id: str, role: str, content: str) -> None:
        """
        Add a message to conversation history.

        Args:
            user_id: User identifier
            role: "user" or "assistant"
            content: Message content
        """
        if user_id in self.sessions:
            self.sessions[user_id]['history'].append({
                'role': role,
                'content': content,
                'timestamp': datetime.now()
            })

            # Limit history length
            max_len = self.config.max_history_length
            if len(self.sessions[user_id]['history']) > max_len:
                self.sessions[user_id]['history'] = \
                    self.sessions[user_id]['history'][-max_len:]

    def clear_session(self, user_id: str) -> bool:
        """
        Clear a user's session.

        Args:
            user_id: User identifier

        Returns:
            True if session was cleared, False if no session existed
        """
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"Cleared session for user {user_id}")
            return True
        return False

    def get_session_info(self, user_id: str) -> Optional[dict]:
        """
        Get session information for a user.

        Args:
            user_id: User identifier

        Returns:
            Session info dict or None if no session exists
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

    async def chat(self, user_id: str, message: str) -> dict:
        """
        Process a chat message and return a response.

        Args:
            user_id: User identifier
            message: User's message

        Returns:
            dict with 'answer', 'sources', and 'has_history' keys
        """
        try:
            chat, history = self.get_or_create_session(user_id)

            # Build prompt with instructions
            prompt = f"""{CHAT_AGENT_INSTRUCTION}

問題：{message}"""

            logger.info(f"Processing message for user {user_id}: {message[:50]}...")

            # Send message
            response = chat.send_message(prompt)

            # Extract response text
            response_text = self._extract_response_text(response)
            if not response_text:
                raise ValueError("API returned empty response")

            # Record history
            self.add_to_history(user_id, "user", message)
            self.add_to_history(user_id, "assistant", response_text)

            # Extract sources if available
            sources = self._extract_sources(response)

            return {
                'answer': response_text,
                'sources': sources,
                'has_history': len(history) > 0
            }

        except Exception as e:
            logger.error(f"Chat failed: {e}", exc_info=True)
            raise

    def _extract_response_text(self, response) -> Optional[str]:
        """Extract text from response object"""
        if response.text:
            return response.text

        # Try extracting from candidates
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                if hasattr(candidate.content, 'parts') and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'text'):
                            return part.text

        return None

    def _extract_sources(self, response) -> List[dict]:
        """Extract grounding sources from response"""
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
        except Exception as e:
            logger.warning(f"Failed to extract sources: {e}")

        return sources

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.

        Returns:
            Number of sessions cleaned up
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


def create_chat_agent(config: Optional[AgentConfig] = None) -> ChatAgent:
    """
    Factory function to create a ChatAgent.

    Args:
        config: Optional configuration. If None, loads from environment.

    Returns:
        Configured ChatAgent instance
    """
    return ChatAgent(config)


def format_chat_response(result: dict, include_sources: bool = True) -> str:
    """
    Format a chat response for display.

    Args:
        result: Result dict from ChatAgent.chat()
        include_sources: Whether to include source citations

    Returns:
        Formatted response string
    """
    text = result['answer']

    # Add session indicator if in conversation
    if result['has_history']:
        text = f"💬 [對話中]\n\n{text}"

    # Add sources if available
    if include_sources and result['sources']:
        text += "\n\n📚 參考來源：\n"
        for i, source in enumerate(result['sources'][:3], 1):
            title = source.get('title', 'Unknown')
            uri = source.get('uri', '')
            if uri:
                text += f"{i}. {title}\n   {uri}\n"

    return text


def get_session_status_message(agent: ChatAgent, user_id: str) -> str:
    """
    Get a status message for a user's session.

    Args:
        agent: ChatAgent instance
        user_id: User identifier

    Returns:
        Status message string
    """
    info = agent.get_session_info(user_id)

    if not info:
        return "📊 目前沒有進行中的對話。\n\n發送任何訊息開始新對話！"

    return f"""📊 對話狀態

💬 對話輪數：{info['history_count']} 條訊息
⏰ 開始時間：{info['created_at'].strftime('%Y-%m-%d %H:%M')}
🕐 最後活動：{info['last_active'].strftime('%H:%M')}

使用 /clear 清除對話記憶"""
