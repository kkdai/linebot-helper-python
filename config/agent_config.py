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
    chat_model: str = "gemini-2.5-flash"
    orchestrator_model: str = "gemini-2.5-pro"
    fast_model: str = "gemini-2.5-flash-lite"

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

    location = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1')

    return AgentConfig(
        project_id=project_id,
        location=location,
        chat_model=os.getenv('CHAT_MODEL', 'gemini-2.5-flash'),
        orchestrator_model=os.getenv('ORCHESTRATOR_MODEL', 'gemini-2.5-pro'),
        fast_model=os.getenv('FAST_MODEL', 'gemini-2.5-flash-lite'),
        session_timeout_minutes=int(os.getenv('SESSION_TIMEOUT_MINUTES', '30')),
        max_history_length=int(os.getenv('MAX_HISTORY_LENGTH', '20')),
        max_output_tokens=int(os.getenv('MAX_OUTPUT_TOKENS', '2048')),
        temperature=float(os.getenv('AGENT_TEMPERATURE', '0.7')),
        enable_grounding=os.getenv('ENABLE_GROUNDING', 'true').lower() == 'true',
        enable_maps_grounding=os.getenv('ENABLE_MAPS_GROUNDING', 'true').lower() == 'true',
    )
