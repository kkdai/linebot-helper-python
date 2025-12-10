"""
Error handling utilities with retry logic and user-friendly messages
"""
import logging
from typing import Optional, Callable, Any
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from httpx import HTTPStatusError, TimeoutException, ConnectError

logger = logging.getLogger(__name__)


class FriendlyErrorMessage:
    """Generate user-friendly error messages in Traditional Chinese"""

    @staticmethod
    def get_message(error: Exception, url: Optional[str] = None) -> str:
        """Convert technical errors to user-friendly messages"""

        # HTTP Status Errors
        if isinstance(error, HTTPStatusError):
            status_code = error.response.status_code
            if status_code == 403:
                return f"❌ 抱歉，無法存取這個網站（被拒絕存取）。\n{url or ''}\n\n可能原因：網站有防爬蟲保護，請稍後再試。"
            elif status_code == 404:
                return f"❌ 找不到這個頁面（404）。\n{url or ''}\n\n請確認網址是否正確。"
            elif status_code == 429:
                return f"❌ 請求過於頻繁（429）。\n{url or ''}\n\n請稍後再試（約 1-2 分鐘）。"
            elif status_code == 500:
                return f"❌ 網站伺服器錯誤（500）。\n{url or ''}\n\n這是對方網站的問題，請稍後再試。"
            elif status_code == 502 or status_code == 503:
                return f"❌ 網站暫時無法使用（{status_code}）。\n{url or ''}\n\n請稍後再試。"
            else:
                return f"❌ 網站回應錯誤（HTTP {status_code}）。\n{url or ''}\n\n請稍後再試或嘗試其他來源。"

        # Timeout Errors
        if isinstance(error, TimeoutException):
            return f"⏱️ 讀取超時。\n{url or ''}\n\n網站回應太慢，已自動重試但仍失敗。請稍後再試。"

        # Connection Errors
        if isinstance(error, ConnectError):
            return f"🔌 無法連線到網站。\n{url or ''}\n\n請檢查網址是否正確，或稍後再試。"

        # Gemini API Errors
        if "google.generativeai" in str(type(error)):
            if "quota" in str(error).lower():
                return "❌ AI 服務配額已用完，請聯繫管理員。"
            elif "rate" in str(error).lower():
                return "⏱️ AI 服務請求過於頻繁，請稍後再試。"
            else:
                return f"❌ AI 處理失敗：{str(error)[:100]}"

        # Generic Errors
        error_msg = str(error)
        if len(error_msg) > 200:
            error_msg = error_msg[:200] + "..."

        return f"❌ 處理時發生錯誤。\n\n技術訊息：{error_msg}\n\n已通知開發者，請稍後再試。"


# Retry decorator for HTTP requests
def retry_http_request(max_attempts: int = 3):
    """
    Retry decorator for HTTP requests with exponential backoff

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((HTTPStatusError, TimeoutException, ConnectError)),
        reraise=True
    )


# Retry decorator for Gemini API calls
def retry_gemini_request(max_attempts: int = 3):
    """
    Retry decorator for Gemini API calls with exponential backoff

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )


class CircuitBreaker:
    """
    Simple circuit breaker implementation
    Prevents cascading failures by stopping requests after consecutive failures
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        """
        Initialize circuit breaker

        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            timeout: Seconds to wait before attempting to close circuit
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection

        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function

        Returns:
            Function result

        Raises:
            Exception: If circuit is open or function fails
        """
        import time

        # Check if circuit is open
        if self.state == "open":
            if time.time() - self.last_failure_time < self.timeout:
                raise Exception(f"Circuit breaker is OPEN. Service temporarily unavailable. Try again in {int(self.timeout - (time.time() - self.last_failure_time))} seconds.")
            else:
                self.state = "half-open"
                logger.info("Circuit breaker moving to HALF-OPEN state")

        try:
            result = func(*args, **kwargs)
            # Success - reset circuit
            if self.state == "half-open":
                self.state = "closed"
                logger.info("Circuit breaker CLOSED")
            self.failure_count = 0
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.error(f"Circuit breaker OPENED after {self.failure_count} consecutive failures")

            raise e


# Global circuit breakers for different services
firecrawl_circuit = CircuitBreaker(failure_threshold=5, timeout=60)
gemini_circuit = CircuitBreaker(failure_threshold=3, timeout=30)


def handle_error_with_fallback(primary_func: Callable, fallback_func: Optional[Callable] = None,
                               url: Optional[str] = None) -> Any:
    """
    Execute primary function with optional fallback

    Args:
        primary_func: Primary function to execute
        fallback_func: Optional fallback function if primary fails
        url: URL being processed (for error messages)

    Returns:
        Result from primary or fallback function

    Raises:
        Exception: If both primary and fallback fail
    """
    try:
        return primary_func()
    except Exception as e:
        logger.error(f"Primary function failed: {e}")

        if fallback_func:
            logger.info("Attempting fallback function")
            try:
                return fallback_func()
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
                # Return user-friendly message for the original error
                raise Exception(FriendlyErrorMessage.get_message(e, url))
        else:
            raise Exception(FriendlyErrorMessage.get_message(e, url))


async def safe_execute(func: Callable, *args, error_context: str = "", **kwargs) -> tuple[Any, Optional[str]]:
    """
    Safely execute a function and return result with optional error message

    Args:
        func: Function to execute (can be sync or async)
        *args, **kwargs: Arguments to pass to function
        error_context: Context string for error logging

    Returns:
        Tuple of (result, error_message)
        - If success: (result, None)
        - If failure: (None, friendly_error_message)
    """
    try:
        if callable(func):
            if hasattr(func, '__call__'):
                # Check if async
                import inspect
                if inspect.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                return result, None
        return None, "Invalid function"
    except Exception as e:
        logger.error(f"Error in {error_context}: {e}")
        url = kwargs.get('url') or (args[0] if args else None)
        error_msg = FriendlyErrorMessage.get_message(e, url if isinstance(url, str) else None)
        return None, error_msg
