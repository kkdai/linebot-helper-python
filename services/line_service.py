"""
LINE Service

Wrapper for LINE Bot API operations, providing a clean interface
for sending messages and handling LINE-specific formatting.
"""

import logging
from typing import List, Optional, Union

from linebot import AsyncLineBotApi
from linebot.models import (
    TextSendMessage,
    QuickReply,
    QuickReplyButton,
    PostbackAction,
)

logger = logging.getLogger(__name__)

# LINE message length limit
MAX_MESSAGE_LENGTH = 5000


class LineService:
    """
    LINE Bot API service wrapper.

    Provides simplified methods for common LINE operations
    and handles message formatting and length limits.
    """

    def __init__(self, line_bot_api: AsyncLineBotApi):
        """
        Initialize LINE service.

        Args:
            line_bot_api: Async LINE Bot API instance
        """
        self.api = line_bot_api

    async def reply_text(
        self,
        reply_token: str,
        text: str,
        quick_reply: Optional[QuickReply] = None
    ) -> None:
        """
        Reply with a text message, automatically handling length limits.

        Args:
            reply_token: LINE reply token
            text: Text content to send
            quick_reply: Optional quick reply buttons
        """
        messages = self._split_long_message(text)

        # Add quick reply to the last message only
        if quick_reply and messages:
            messages[-1] = TextSendMessage(
                text=messages[-1].text,
                quick_reply=quick_reply
            )

        await self.api.reply_message(reply_token, messages)

    async def push_text(
        self,
        user_id: str,
        text: str,
        quick_reply: Optional[QuickReply] = None
    ) -> None:
        """
        Push a text message to a user.

        Args:
            user_id: LINE user ID
            text: Text content to send
            quick_reply: Optional quick reply buttons
        """
        messages = self._split_long_message(text)

        # Add quick reply to the last message only
        if quick_reply and messages:
            messages[-1] = TextSendMessage(
                text=messages[-1].text,
                quick_reply=quick_reply
            )

        await self.api.push_message(user_id, messages)

    async def reply_messages(
        self,
        reply_token: str,
        messages: List[TextSendMessage]
    ) -> None:
        """
        Reply with multiple messages.

        Args:
            reply_token: LINE reply token
            messages: List of TextSendMessage objects
        """
        # LINE allows max 5 messages per reply
        if len(messages) > 5:
            logger.warning(f"Too many messages ({len(messages)}), truncating to 5")
            messages = messages[:5]

        await self.api.reply_message(reply_token, messages)

    async def push_messages(
        self,
        user_id: str,
        messages: List[TextSendMessage]
    ) -> None:
        """
        Push multiple messages to a user.

        Args:
            user_id: LINE user ID
            messages: List of TextSendMessage objects
        """
        # Send in batches of 5 (LINE limit)
        for i in range(0, len(messages), 5):
            batch = messages[i:i + 5]
            await self.api.push_message(user_id, batch)

    def _split_long_message(self, text: str) -> List[TextSendMessage]:
        """
        Split a long message into multiple messages if needed.

        Args:
            text: Text to potentially split

        Returns:
            List of TextSendMessage objects
        """
        if len(text) <= MAX_MESSAGE_LENGTH - 100:  # Leave some buffer
            return [TextSendMessage(text=text)]

        # Split by paragraphs first
        paragraphs = text.split('\n\n')
        messages = []
        current_text = ""

        for paragraph in paragraphs:
            # Check if adding this paragraph would exceed limit
            if len(current_text) + len(paragraph) + 2 > MAX_MESSAGE_LENGTH - 100:
                if current_text:
                    messages.append(TextSendMessage(text=current_text.strip()))
                current_text = paragraph
            else:
                current_text += ("\n\n" if current_text else "") + paragraph

        # Add remaining text
        if current_text:
            messages.append(TextSendMessage(text=current_text.strip()))

        return messages if messages else [TextSendMessage(text=text[:MAX_MESSAGE_LENGTH - 100])]

    @staticmethod
    def create_quick_reply_buttons(
        buttons: List[dict]
    ) -> QuickReply:
        """
        Create quick reply buttons from a list of button definitions.

        Args:
            buttons: List of dicts with 'label', 'data', and 'display_text' keys

        Returns:
            QuickReply object with the buttons
        """
        items = []
        for btn in buttons:
            items.append(
                QuickReplyButton(
                    action=PostbackAction(
                        label=btn['label'],
                        data=btn['data'],
                        display_text=btn.get('display_text', btn['label'])
                    )
                )
            )
        return QuickReply(items=items)

    @staticmethod
    def format_error_message(error: Exception, context: str = "") -> str:
        """
        Format an error into a user-friendly message.

        Args:
            error: The exception that occurred
            context: Additional context about what was being attempted

        Returns:
            Formatted error message string
        """
        error_str = str(error).lower()

        if "quota" in error_str or "rate limit" in error_str or "429" in error_str:
            return (
                "⏳ 系統目前繁忙，請稍後再試。\n\n"
                "💡 建議等待 1-2 分鐘後重試。"
            )
        elif "timeout" in error_str:
            return (
                "⏱️ 處理時間過長，請稍後再試。\n\n"
                "💡 如果問題持續，請嘗試簡化您的問題。"
            )
        elif "not found" in error_str or "404" in error_str:
            return (
                "🔍 找不到相關資訊。\n\n"
                "💡 請嘗試用不同的方式描述您的問題。"
            )
        elif "empty response" in error_str:
            return (
                "⚠️ 無法生成回應，可能是內容被過濾。\n\n"
                "💡 請嘗試用不同的問法。"
            )
        else:
            base_msg = "❌ 處理時發生錯誤。"
            if context:
                base_msg = f"❌ {context}時發生錯誤。"
            return f"{base_msg}\n\n請稍後再試，或使用 /clear 清除對話記憶後重新開始。"
