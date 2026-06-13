"""
Orchestrator Agent

The main controller agent that routes requests to specialized agents
and handles Agent-to-Agent (A2A) communication.
"""

import asyncio
import logging
import re
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass
from enum import Enum

try:
    from google.adk.agents import Agent
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False

from config.agent_config import AgentConfig, get_agent_config

# Import all specialized agents
from .chat_agent import ChatAgent, create_chat_agent, format_chat_response
from .content_agent import ContentAgent, create_content_agent, format_content_response
from .location_agent import LocationAgent, create_location_agent, format_location_response
from .vision_agent import VisionAgent, create_vision_agent, format_vision_response
from .github_agent import GitHubAgent, create_github_agent, format_github_response

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Types of user intents that the orchestrator can detect"""
    CHAT = "chat"                    # General conversation
    URL_SUMMARY = "url_summary"      # URL content summarization
    YOUTUBE_SUMMARY = "youtube"      # YouTube video summarization
    IMAGE_ANALYSIS = "image"         # Image analysis
    LOCATION_SEARCH = "location"     # Location-based search
    GITHUB_SUMMARY = "github"        # GitHub operations
    COMMAND = "command"              # System commands (/clear, /help, etc.)
    RESTAURANT_SEARCH = "restaurant_search" # Restaurant/food search intent
    UNKNOWN = "unknown"



@dataclass
class Intent:
    """Represents a detected user intent"""
    type: IntentType
    confidence: float
    data: Dict[str, Any]


@dataclass
class AgentTask:
    """Represents a task to be executed by an agent"""
    agent_name: str
    method: str
    kwargs: Dict[str, Any]


@dataclass
class OrchestratorResult:
    """Result from orchestrator processing"""
    success: bool
    responses: List[Dict[str, Any]]
    intents: List[Intent]
    error: Optional[str] = None


# Orchestrator instruction for ADK
ORCHESTRATOR_INSTRUCTION = """你是 LINE Bot 的主控 Agent (Orchestrator)。
你的職責是分析用戶訊息的意圖，並將任務分派給適當的專業 Agent。

## 可用的專業 Agent
1. **ChatAgent**: 處理一般對話和問答，支援 Google Search Grounding
2. **ContentAgent**: 處理 URL 內容摘要（網頁、YouTube、PDF）
3. **LocationAgent**: 處理地點搜尋（加油站、停車場、餐廳）
4. **VisionAgent**: 處理圖片分析
5. **GitHubAgent**: 處理 GitHub 相關操作

## 路由規則
- 訊息包含 URL → ContentAgent
- 訊息是 "@g" → GitHubAgent
- 訊息是系統指令 (/clear, /help, /status) → 直接處理
- 收到圖片 → VisionAgent
- 收到位置 → LocationAgent
- 其他文字訊息 → ChatAgent

## 複合任務
如果用戶的訊息包含多個意圖（例如：「幫我找餐廳，然後摘要這篇文章 https://...」），
你應該並行處理多個任務，然後彙整結果。
"""


class Orchestrator:
    """
    Main Orchestrator Agent for routing requests to specialized agents.

    Implements Agent-to-Agent (A2A) communication pattern where the orchestrator
    analyzes user intent and delegates tasks to appropriate specialist agents.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize Orchestrator with all specialized agents.

        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or get_agent_config()

        # Initialize all specialized agents
        self.chat_agent = create_chat_agent(self.config)
        self.content_agent = create_content_agent(self.config)
        self.location_agent = create_location_agent(self.config)
        self.vision_agent = create_vision_agent(self.config)
        self.github_agent = create_github_agent(self.config)

        # URL patterns for intent detection
        self._url_pattern = re.compile(
            r'https?://[^\s<>"{}|\\^`\[\]]+'
        )
        self._youtube_pattern = re.compile(
            r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|m\.youtube\.com)[^\s]*'
        )

        # Initialize ADK orchestrator if available
        if ADK_AVAILABLE:
            self._init_adk_orchestrator()
        else:
            self.adk_agent = None

        logger.info("Orchestrator initialized with all specialized agents")

    def _init_adk_orchestrator(self):
        """Initialize ADK orchestrator agent with sub-agents"""
        try:
            # Collect ADK agents from specialized agents
            sub_agents = []
            for agent in [self.chat_agent, self.content_agent,
                         self.location_agent, self.vision_agent, self.github_agent]:
                if hasattr(agent, 'adk_agent') and agent.adk_agent:
                    sub_agents.append(agent.adk_agent)

            self.adk_agent = Agent(
                name="orchestrator",
                model=self.config.orchestrator_model,
                description="LINE Bot 主控 Agent，負責意圖分析和任務路由",
                instruction=ORCHESTRATOR_INSTRUCTION,
                sub_agents=sub_agents if sub_agents else None,
                tools=[],
            )
            logger.info(f"ADK Orchestrator created with {len(sub_agents)} sub-agents")
        except Exception as e:
            logger.warning(f"Failed to create ADK orchestrator: {e}")
            self.adk_agent = None

    def detect_intents(self, message: str) -> List[Intent]:
        """
        Detect user intents from a text message.

        Args:
            message: User's text message

        Returns:
            List of detected intents, ordered by confidence
        """
        intents = []
        message_lower = message.lower().strip()

        # Check for system commands
        if message_lower in ['/clear', '/清除', '/reset', '/重置',
                            '/status', '/狀態', '/info',
                            '/help', '/幫助', '/說明',
                            '/session-stats', '/stats']:
            intents.append(Intent(
                type=IntentType.COMMAND,
                confidence=1.0,
                data={'command': message_lower}
            ))
            return intents  # Commands are exclusive

        # Check for GitHub command
        if message_lower == '@g':
            intents.append(Intent(
                type=IntentType.GITHUB_SUMMARY,
                confidence=1.0,
                data={}
            ))
            return intents

        # Check for URLs
        urls = self._url_pattern.findall(message)
        if urls:
            for url in urls:
                if self._youtube_pattern.match(url):
                    intents.append(Intent(
                        type=IntentType.YOUTUBE_SUMMARY,
                        confidence=0.95,
                        data={'url': url}
                    ))
                else:
                    intents.append(Intent(
                        type=IntentType.URL_SUMMARY,
                        confidence=0.95,
                        data={'url': url}
                    ))

        # Check for restaurant / food keywords
        restaurant_keywords = ["餐廳", "美食", "好吃", "小吃", "餐酒館", "咖啡廳", "早午餐", "火鍋", "燒肉", "壽司", "拉麵", "牛肉麵", "吃什麼", "點餐", "吃東西"]
        if not intents and any(kw in message_lower for kw in restaurant_keywords):
            intents.append(Intent(
                type=IntentType.RESTAURANT_SEARCH,
                confidence=0.9,
                data={'message': message}
            ))

        # If no special intents, it's a chat message
        if not intents:
            intents.append(Intent(
                type=IntentType.CHAT,
                confidence=0.9,
                data={'message': message}
            ))

        return intents


    async def process_text(
        self,
        user_id: str,
        message: str,
        mode: str = "normal"
    ) -> OrchestratorResult:
        """
        Process a text message by detecting intents and routing to agents.

        Args:
            user_id: User identifier for session management
            message: User's text message
            mode: Summary mode for URL processing

        Returns:
            OrchestratorResult with responses from all agents
        """
        intents = self.detect_intents(message)
        logger.info(f"Detected {len(intents)} intent(s) for user {user_id}")

        responses = []

        # Handle single intent
        if len(intents) == 1:
            intent = intents[0]
            result = await self._route_intent(user_id, intent, mode)
            responses.append(result)

        # Handle multiple intents (parallel execution)
        elif len(intents) > 1:
            tasks = []
            for intent in intents:
                tasks.append(self._route_intent(user_id, intent, mode))

            # Execute all tasks in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    responses.append({
                        'status': 'error',
                        'error_message': str(result),
                        'intent': intents[i].type.value
                    })
                else:
                    responses.append(result)

        return OrchestratorResult(
            success=all(r.get('status') == 'success' for r in responses if isinstance(r, dict)),
            responses=responses,
            intents=intents
        )

    async def _route_intent(
        self,
        user_id: str,
        intent: Intent,
        mode: str = "normal"
    ) -> Dict[str, Any]:
        """
        Route a single intent to the appropriate agent.

        Args:
            user_id: User identifier
            intent: Detected intent
            mode: Processing mode

        Returns:
            Result dict from the agent
        """
        try:
            if intent.type == IntentType.COMMAND:
                return await self._handle_command(user_id, intent.data['command'])

            elif intent.type == IntentType.GITHUB_SUMMARY:
                result = self.github_agent.get_issues_summary()
                result['intent'] = 'github'
                return result

            elif intent.type == IntentType.YOUTUBE_SUMMARY:
                url = intent.data['url']
                # Map mode for YouTube
                youtube_mode = "detail" if mode == "detailed" else mode
                if youtube_mode not in ["normal", "detail", "twitter"]:
                    youtube_mode = "normal"
                result = await self.content_agent.summarize_youtube(url, mode=youtube_mode)
                result['intent'] = 'youtube'
                result['url'] = url
                return result

            elif intent.type == IntentType.URL_SUMMARY:
                url = intent.data['url']
                result = await self.content_agent.process_url(url, mode=mode)
                result['intent'] = 'url'
                return result

            elif intent.type == IntentType.RESTAURANT_SEARCH:
                session = self.chat_agent.session_manager.get_session(user_id)
                last_location = session.metadata.get("last_location") if session else None
                
                if not last_location:
                    return {
                        'status': 'success',
                        'response': "📍 偵測到您想要尋找美食！請點選下方按鈕或加號傳送您的『位置資訊』，我將利用 Google Maps Grounding 與 Gemini Batch API 為您進行深度評論與菜色分析！",
                        'intent': 'restaurant_search',
                        'need_location': True
                    }
                
                # Trigger restaurant search at last known location
                latitude = last_location['latitude']
                longitude = last_location['longitude']
                address = last_location.get('address', '')
                
                result = await self.location_agent.search(latitude, longitude, "restaurant")
                result['intent'] = 'restaurant_search'
                result['latitude'] = latitude
                result['longitude'] = longitude
                result['address'] = address
                result['has_location'] = True
                return result

            elif intent.type == IntentType.CHAT:
                result = await self.chat_agent.chat(user_id, intent.data['message'])
                result['intent'] = 'chat'
                return result


            else:
                return {
                    'status': 'error',
                    'error_message': f'Unknown intent type: {intent.type}',
                    'intent': intent.type.value
                }

        except Exception as e:
            logger.error(f"Error routing intent {intent.type}: {e}", exc_info=True)
            return {
                'status': 'error',
                'error_message': str(e)[:100],
                'intent': intent.type.value
            }

    async def _handle_command(self, user_id: str, command: str) -> Dict[str, Any]:
        """Handle system commands"""
        if command in ['/clear', '/清除', '/reset', '/重置']:
            success = self.chat_agent.clear_session(user_id)
            if success:
                return {
                    'status': 'success',
                    'response': "✅ 對話已重置\n\n你可以開始新的對話了！",
                    'intent': 'command'
                }
            else:
                return {
                    'status': 'success',
                    'response': "📊 目前沒有進行中的對話。\n\n發送任何訊息開始新對話！",
                    'intent': 'command'
                }

        elif command in ['/status', '/狀態', '/info']:
            from .chat_agent import get_session_status_message
            status = get_session_status_message(self.chat_agent, user_id)
            return {
                'status': 'success',
                'response': status,
                'intent': 'command'
            }

        elif command in ['/help', '/幫助', '/說明']:
            help_text = """🤖 智能助手 (ADK Orchestrator)

💬 對話功能
發送任何問題，我會自動搜尋網路並提供詳細回答。
支援連續對話，我會記住我們的對話內容！

🔗 內容摘要
發送任何網址，我會自動擷取並摘要內容。
• 網頁文章
• YouTube 影片
• PDF 文件

📍 位置服務
發送你的位置，可以搜尋附近的：
• ⛽ 加油站
• 🅿️ 停車場
• 🍴 餐廳

🖼️ 圖片分析
發送圖片，我會分析圖片內容。

⚡ 特殊指令
/clear - 清除對話記憶
/status - 查看對話狀態
/stats - 查看 Session 統計
/help - 顯示此說明
@g - GitHub Issues 摘要

提示：對話會在 30 分鐘無互動後自動過期。"""
            return {
                'status': 'success',
                'response': help_text,
                'intent': 'command'
            }

        elif command in ['/session-stats', '/stats']:
            # Get session statistics from session manager
            if hasattr(self.chat_agent, 'session_manager'):
                stats = self.chat_agent.session_manager.get_stats()
                stats_text = f"""📈 Session 統計資訊

👥 活躍對話數：{stats.active_sessions}
💬 總訊息數：{stats.total_messages}
⏱️ 最舊對話：{stats.oldest_session_age_minutes:.1f} 分鐘
🧹 清理次數：{stats.cleanup_runs}
🗑️ 已清理對話：{stats.sessions_cleaned}"""
                return {
                    'status': 'success',
                    'response': stats_text,
                    'intent': 'command'
                }
            else:
                return {
                    'status': 'success',
                    'response': "📊 Session 管理器未啟用",
                    'intent': 'command'
                }

        return {
            'status': 'error',
            'error_message': f'Unknown command: {command}',
            'intent': 'command'
        }

    async def process_image(
        self,
        image_data: bytes,
        prompt: Optional[str] = None
    ) -> OrchestratorResult:
        """
        Process an image message.

        Args:
            image_data: Image bytes
            prompt: Optional analysis prompt

        Returns:
            OrchestratorResult with image analysis
        """
        result = await self.vision_agent.analyze(image_data, prompt)
        result['intent'] = 'image'

        return OrchestratorResult(
            success=result.get('status') == 'success',
            responses=[result],
            intents=[Intent(IntentType.IMAGE_ANALYSIS, 1.0, {})]
        )

    async def process_image_agentic(
        self,
        image_data: bytes,
        prompt: Optional[str] = None
    ) -> OrchestratorResult:
        """
        Process an image using Agentic Vision (gemini-3-flash-preview).

        Args:
            image_data: Image bytes
            prompt: Optional analysis prompt

        Returns:
            OrchestratorResult with agentic vision analysis
        """
        result = await self.vision_agent.analyze_agentic(image_data, prompt)
        result['intent'] = 'image'

        return OrchestratorResult(
            success=result.get('status') == 'success',
            responses=[result],
            intents=[Intent(IntentType.IMAGE_ANALYSIS, 1.0, {})]
        )

    async def process_location(
        self,
        latitude: float,
        longitude: float,
        place_type: Literal["gas_station", "parking", "restaurant"] = "restaurant"
    ) -> OrchestratorResult:
        """
        Process a location search request.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            place_type: Type of place to search

        Returns:
            OrchestratorResult with location search results
        """
        result = await self.location_agent.search(latitude, longitude, place_type)
        result['intent'] = 'location'

        return OrchestratorResult(
            success=result.get('status') == 'success',
            responses=[result],
            intents=[Intent(IntentType.LOCATION_SEARCH, 1.0, {'place_type': place_type})]
        )


def create_orchestrator(config: Optional[AgentConfig] = None) -> Orchestrator:
    """
    Factory function to create an Orchestrator.

    Args:
        config: Optional configuration

    Returns:
        Configured Orchestrator instance
    """
    return Orchestrator(config)


def format_orchestrator_response(result: OrchestratorResult) -> str:
    """
    Format orchestrator result for display.

    Args:
        result: OrchestratorResult from orchestrator processing

    Returns:
        Formatted response string
    """
    if not result.responses:
        return "❌ 無法處理您的請求"

    # Single response
    if len(result.responses) == 1:
        response = result.responses[0]
        intent = response.get('intent', 'unknown')

        if response.get('status') != 'success':
            return f"❌ {response.get('error_message', '處理失敗')}"

        # Format based on intent type
        if intent == 'command':
            return response.get('response', '')
        elif intent == 'chat':
            return format_chat_response(response)
        elif intent in ['url', 'youtube']:
            return format_content_response(response)
        elif intent == 'location':
            return format_location_response(response)
        elif intent == 'restaurant_search':
            if response.get('has_location'):
                return format_location_response(response)
            else:
                return response.get('response', '')
        elif intent == 'image':
            return format_vision_response(response)
        elif intent == 'github':
            return format_github_response(response)

        else:
            return response.get('response', response.get('content', ''))

    # Multiple responses - combine them
    parts = []
    for i, response in enumerate(result.responses, 1):
        if response.get('status') == 'success':
            intent = response.get('intent', 'unknown')
            if intent in ['url', 'youtube']:
                parts.append(format_content_response(response, include_url=True))
            elif intent == 'chat':
                parts.append(format_chat_response(response, include_sources=False))
            else:
                parts.append(str(response.get('content', response.get('response', ''))))
        else:
            parts.append(f"❌ 任務 {i}: {response.get('error_message', '失敗')}")

    return "\n\n---\n\n".join(parts)
