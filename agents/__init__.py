"""
Agents for LINE Bot

This module provides agents for handling different types of user requests.
Each agent is specialized for a specific task domain, coordinated by the Orchestrator.

關於 ADK：每個 agent 都留著 `from google.adk.agents import Agent` 的 import guard，
但 `google-adk` 不在依賴裡（見 requirements.txt 的說明），而且就算裝了，建出來的
`adk_agent` 物件也沒有任何一條路徑會呼叫它——所有實際工作都是直接呼叫 tools/
底下的函式。讀這裡的程式碼時請不要假設正式環境跑的是 ADK 路徑。
"""

from .chat_agent import (
    ChatAgent,
    create_chat_agent,
    format_chat_response,
    get_session_status_message,
)
from .content_agent import (
    ContentAgent,
    create_content_agent,
    format_content_response,
)
from .location_agent import (
    LocationAgent,
    create_location_agent,
    format_location_response,
)
from .vision_agent import (
    VisionAgent,
    create_vision_agent,
    format_vision_response,
)
from .github_agent import (
    GitHubAgent,
    create_github_agent,
    format_github_response,
)
from .orchestrator import (
    Orchestrator,
    create_orchestrator,
    format_orchestrator_response,
    IntentType,
    OrchestratorResult,
)

__all__ = [
    # Orchestrator (Main Controller)
    "Orchestrator",
    "create_orchestrator",
    "format_orchestrator_response",
    "IntentType",
    "OrchestratorResult",
    # Chat Agent
    "ChatAgent",
    "create_chat_agent",
    "format_chat_response",
    "get_session_status_message",
    # Content Agent
    "ContentAgent",
    "create_content_agent",
    "format_content_response",
    # Location Agent
    "LocationAgent",
    "create_location_agent",
    "format_location_response",
    # Vision Agent
    "VisionAgent",
    "create_vision_agent",
    "format_vision_response",
    # GitHub Agent
    "GitHubAgent",
    "create_github_agent",
    "format_github_response",
]
