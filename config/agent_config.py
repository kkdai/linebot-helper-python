"""
Agent Configuration

Centralized configuration for all ADK agents.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
    """Configuration for ADK agents"""

    # Vertex AI settings
    project_id: str
    location: str

    # Model settings
    # 分級原則：維持既有能力層級，只做現代化。
    # 禁止 preview／實驗模型——會無預警下架（見 gemini-3-pro-preview 404）。
    # 例外僅 services/voice_live.py 與 tools/tts_tool.py，見 tests/test_model_config.py。
    chat_model: str = "gemini-3.5-flash-lite"
    # Tier 1「capable model」槽位。共用者：ADK orchestrator、
    # agentic vision（tools/summarizer.py）、grounded chat（loader/chat_session.py）。
    orchestrator_model: str = "gemini-3.7-flash"
    fast_model: str = "gemini-3.5-flash-lite"
    # 影片必須用 3.5-flash-lite：3.7-flash 在 agentic 會忽略 thinking_level，
    # 10 分鐘影片成本是前者的 60 倍，且易觸發 429。
    video_model: str = "gemini-3.5-flash-lite"

    # Session settings
    session_timeout_minutes: int = 30
    max_history_length: int = 20

    # Response settings
    max_output_tokens: int = 2048
    temperature: float = 0.7

    # Feature flags
    enable_grounding: bool = True
    enable_maps_grounding: bool = True


def get_agent_config() -> AgentConfig:
    """
    Get agent configuration from environment variables.

    Returns:
        AgentConfig: Configuration object with all settings

    Raises:
        ValueError: If required environment variables are not set
    """
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is required")

    location = os.getenv('GOOGLE_CLOUD_LOCATION', 'global')

    return AgentConfig(
        project_id=project_id,
        location=location,
        chat_model=os.getenv('CHAT_MODEL', 'gemini-3.5-flash-lite'),
        orchestrator_model=os.getenv('ORCHESTRATOR_MODEL', 'gemini-3.7-flash'),
        fast_model=os.getenv('FAST_MODEL', 'gemini-3.5-flash-lite'),
        video_model=os.getenv('VIDEO_MODEL', 'gemini-3.5-flash-lite'),
        session_timeout_minutes=int(os.getenv('SESSION_TIMEOUT_MINUTES', '30')),
        max_history_length=int(os.getenv('MAX_HISTORY_LENGTH', '20')),
        max_output_tokens=int(os.getenv('MAX_OUTPUT_TOKENS', '2048')),
        temperature=float(os.getenv('AGENT_TEMPERATURE', '0.7')),
        enable_grounding=os.getenv('ENABLE_GROUNDING', 'true').lower() == 'true',
        enable_maps_grounding=os.getenv('ENABLE_MAPS_GROUNDING', 'true').lower() == 'true',
    )
