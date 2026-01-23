"""
GitHub Agent

ADK-based agent for GitHub-related tasks like issue summarization.
"""

import logging
from typing import Optional
from datetime import datetime, timedelta

try:
    from google.adk.agents import Agent
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False

from config.agent_config import AgentConfig, get_agent_config

# Import the existing GitHub tools
try:
    from loader.gh_tools import summarized_yesterday_github_issues
    GITHUB_TOOLS_AVAILABLE = True
except ImportError:
    GITHUB_TOOLS_AVAILABLE = False
    logging.warning("GitHub tools not available")

logger = logging.getLogger(__name__)

# Agent instruction
GITHUB_AGENT_INSTRUCTION = """你是 GitHub 助手，專門處理 GitHub 相關的任務。

## 功能
1. 摘要 GitHub Issues
2. 追蹤專案更新
3. 提供開發進度報告

## 回應原則
- 使用台灣用語的繁體中文
- 摘要要簡潔但包含關鍵資訊
- 標明 Issue 編號和狀態
- 適合在 LINE 訊息中閱讀
"""


class GitHubAgent:
    """
    ADK-based GitHub Agent for repository management tasks.

    Handles:
    - Issue summarization
    - Activity tracking
    - Progress reports
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize GitHubAgent.

        Args:
            config: Agent configuration. If None, loads from environment.
        """
        self.config = config or get_agent_config()

        if not GITHUB_TOOLS_AVAILABLE:
            logger.warning("GitHub tools not available")

        # Initialize ADK agent if available
        if ADK_AVAILABLE:
            self._init_adk_agent()
        else:
            self.adk_agent = None

        logger.info(f"GitHubAgent initialized (ADK: {ADK_AVAILABLE}, Tools: {GITHUB_TOOLS_AVAILABLE})")

    def _init_adk_agent(self):
        """Initialize ADK agent for orchestration"""
        try:
            self.adk_agent = Agent(
                name="github_agent",
                model=self.config.fast_model,
                description="GitHub Agent，處理 GitHub Issues 摘要和專案追蹤",
                instruction=GITHUB_AGENT_INSTRUCTION,
                tools=[],  # GitHub tools are sync, handled separately
            )
            logger.info("ADK GitHub Agent created successfully")
        except Exception as e:
            logger.warning(f"Failed to create ADK agent: {e}")
            self.adk_agent = None

    def get_issues_summary(self) -> dict:
        """
        Get a summary of recent GitHub issues.

        Returns:
            dict with 'status', 'summary', and optional 'error_message'
        """
        if not GITHUB_TOOLS_AVAILABLE:
            return {
                "status": "error",
                "error_message": "GitHub 工具未安裝或設定"
            }

        try:
            logger.info("Fetching GitHub issues summary")

            summary = summarized_yesterday_github_issues()

            if not summary:
                return {
                    "status": "success",
                    "summary": "📋 目前沒有新的 GitHub Issues"
                }

            return {
                "status": "success",
                "summary": summary
            }

        except Exception as e:
            logger.error(f"GitHub issues error: {e}", exc_info=True)
            return {
                "status": "error",
                "error_message": f"取得 GitHub Issues 時發生錯誤: {str(e)[:100]}"
            }


def create_github_agent(config: Optional[AgentConfig] = None) -> GitHubAgent:
    """
    Factory function to create a GitHubAgent.

    Args:
        config: Optional configuration

    Returns:
        Configured GitHubAgent instance
    """
    return GitHubAgent(config)


def format_github_response(result: dict) -> str:
    """
    Format GitHub agent response for display.

    Args:
        result: Result dict from GitHubAgent

    Returns:
        Formatted response string
    """
    if result["status"] != "success":
        return f"❌ {result.get('error_message', 'GitHub 操作失敗')}"

    return result.get("summary", "無資料")
