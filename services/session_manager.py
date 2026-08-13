"""
Session Manager

Centralized session management with TTL support and automatic cleanup.
Provides thread-safe session handling for multi-user chat environments.
"""

import asyncio
import inspect
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from threading import Lock

from .firestore_store import FirestoreKVStore

logger = logging.getLogger(__name__)

SESSION_COLLECTION = "chat_sessions"


def _serialize_history(history: List[dict]) -> List[dict]:
    """datetime 轉 epoch float，避免 Firestore 回讀時 tz-aware/naive 混用問題。"""
    out = []
    for msg in history:
        m = dict(msg)
        ts = m.get('timestamp')
        if isinstance(ts, datetime):
            m['timestamp'] = ts.timestamp()
        out.append(m)
    return out


def _deserialize_history(raw: Optional[List[dict]]) -> List[dict]:
    out = []
    for msg in raw or []:
        m = dict(msg)
        ts = m.get('timestamp')
        if isinstance(ts, (int, float)):
            m['timestamp'] = datetime.fromtimestamp(ts)
        out.append(m)
    return out


def _make_chat(chat_factory: Callable, history: List[dict]) -> Any:
    """重建 chat 時盡量把歷史傳給 factory（讓模型接續上下文）。

    舊式零參數 factory 不收 history，也要能正常運作。
    """
    try:
        supports_history = 'history' in inspect.signature(chat_factory).parameters
    except (TypeError, ValueError):
        supports_history = False

    if supports_history and history:
        return chat_factory(history=history)
    return chat_factory()


@dataclass
class SessionData:
    """Data structure for a single user session"""
    user_id: str
    chat: Any  # Gemini chat instance
    history: List[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionStats:
    """Statistics about session manager state"""
    active_sessions: int
    total_messages: int
    oldest_session_age_minutes: float
    cleanup_runs: int
    sessions_cleaned: int


class SessionManager:
    """
    Centralized session manager with TTL and automatic cleanup.

    Features:
    - Thread-safe session operations
    - Automatic expiration based on TTL
    - Background cleanup task
    - Session statistics and monitoring
    - Event callbacks for session lifecycle

    Usage:
        manager = SessionManager(timeout_minutes=30)
        await manager.start_cleanup_task()

        # Get or create session
        session = manager.get_or_create_session(user_id, chat_factory)

        # Update session activity
        manager.touch_session(user_id)

        # Clean shutdown
        await manager.stop_cleanup_task()
    """

    def __init__(
        self,
        timeout_minutes: int = 30,
        max_history_length: int = 20,
        cleanup_interval_seconds: int = 300,  # 5 minutes
        store=None
    ):
        """
        Initialize SessionManager.

        Args:
            timeout_minutes: Session TTL in minutes
            max_history_length: Maximum messages to keep in history
            cleanup_interval_seconds: Interval between cleanup runs
            store: Persistent KV store (defaults to Firestore; falls back to
                   memory-only when Firestore is unavailable)
        """
        self.timeout = timedelta(minutes=timeout_minutes)
        self.max_history_length = max_history_length
        self.cleanup_interval = cleanup_interval_seconds
        self._store = store if store is not None else FirestoreKVStore(SESSION_COLLECTION)

        self._sessions: Dict[str, SessionData] = {}
        self._lock = Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._cleanup_runs = 0
        self._sessions_cleaned = 0

        # Callbacks
        self._on_session_created: Optional[Callable[[str], None]] = None
        self._on_session_expired: Optional[Callable[[str], None]] = None

        logger.info(
            f"SessionManager initialized: timeout={timeout_minutes}min, "
            f"max_history={max_history_length}, cleanup_interval={cleanup_interval_seconds}s"
        )

    def set_callbacks(
        self,
        on_created: Optional[Callable[[str], None]] = None,
        on_expired: Optional[Callable[[str], None]] = None
    ) -> None:
        """
        Set lifecycle callbacks.

        Args:
            on_created: Called when a new session is created (user_id)
            on_expired: Called when a session expires (user_id)
        """
        self._on_session_created = on_created
        self._on_session_expired = on_expired

    def is_expired(self, session: SessionData) -> bool:
        """Check if a session has expired"""
        return datetime.now() - session.last_active >= self.timeout

    def _persist_session(self, session: SessionData) -> None:
        """把 session（不含 chat 物件，無法序列化）寫進持久化 store。"""
        self._store.save(session.user_id, {
            'user_id': session.user_id,
            'history': _serialize_history(session.history),
            'created_at': session.created_at.timestamp(),
            'last_active': session.last_active.timestamp(),
        })

    def _restore_session(
        self,
        user_id: str,
        chat_factory: Callable[..., Any]
    ) -> Optional[SessionData]:
        """從持久化 store 還原 session（instance 重啟後對話記憶不遺失）。

        呼叫端必須已持有 self._lock。
        """
        stored = self._store.load(user_id)
        if not stored:
            return None

        last_active = datetime.fromtimestamp(stored.get('last_active', 0))
        if datetime.now() - last_active >= self.timeout:
            self._store.delete(user_id)
            return None

        history = _deserialize_history(stored.get('history'))
        session = SessionData(
            user_id=user_id,
            chat=_make_chat(chat_factory, history),
            history=history,
            created_at=datetime.fromtimestamp(
                stored.get('created_at', time.time())),
            last_active=datetime.now()
        )
        self._sessions[user_id] = session
        self._persist_session(session)
        logger.info(f"Restored session for user {user_id} from persistent store "
                    f"({len(history)} messages)")
        return session

    def get_session(self, user_id: str) -> Optional[SessionData]:
        """
        Get an existing session if it exists and is not expired.

        Args:
            user_id: User identifier

        Returns:
            SessionData if valid session exists, None otherwise
        """
        with self._lock:
            session = self._sessions.get(user_id)
            if session and not self.is_expired(session):
                return session
            return None

    def get_or_create_session(
        self,
        user_id: str,
        chat_factory: Callable[[], Any]
    ) -> SessionData:
        """
        Get existing session or create a new one.

        Args:
            user_id: User identifier
            chat_factory: Factory function to create new chat instance

        Returns:
            SessionData for the user
        """
        with self._lock:
            session = self._sessions.get(user_id)

            # Return existing valid session
            if session and not self.is_expired(session):
                session.last_active = datetime.now()
                logger.debug(f"Reusing session for user {user_id}")
                return session

            # Log expiration
            if session:
                logger.info(f"Session expired for user {user_id}")
            else:
                # 記憶體沒有：可能是 instance 重啟，試著從持久化 store 還原
                restored = self._restore_session(user_id, chat_factory)
                if restored:
                    return restored

            # Create new session
            logger.info(f"Creating new session for user {user_id}")
            chat = chat_factory()
            new_session = SessionData(
                user_id=user_id,
                chat=chat,
                history=[],
                created_at=datetime.now(),
                last_active=datetime.now()
            )
            self._sessions[user_id] = new_session
            self._persist_session(new_session)

            # Callback
            if self._on_session_created:
                try:
                    self._on_session_created(user_id)
                except Exception as e:
                    logger.warning(f"Session created callback failed: {e}")

            return new_session

    def touch_session(self, user_id: str) -> bool:
        """
        Update session's last active time.

        Args:
            user_id: User identifier

        Returns:
            True if session was updated, False if not found
        """
        with self._lock:
            session = self._sessions.get(user_id)
            if session:
                session.last_active = datetime.now()
                self._persist_session(session)
                return True
            return False

    def add_to_history(
        self,
        user_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Add a message to session history.

        Args:
            user_id: User identifier
            role: "user" or "assistant"
            content: Message content
            metadata: Optional additional data

        Returns:
            True if message was added, False if session not found
        """
        with self._lock:
            session = self._sessions.get(user_id)
            if not session:
                return False

            message = {
                'role': role,
                'content': content,
                'timestamp': datetime.now()
            }
            if metadata:
                message['metadata'] = metadata

            session.history.append(message)

            # Trim history if needed
            if len(session.history) > self.max_history_length:
                session.history = session.history[-self.max_history_length:]

            self._persist_session(session)
            return True

    def get_history(self, user_id: str) -> List[dict]:
        """
        Get conversation history for a user.

        Args:
            user_id: User identifier

        Returns:
            List of history messages, empty if no session
        """
        with self._lock:
            session = self._sessions.get(user_id)
            if session:
                return list(session.history)
            return []

    def clear_session(self, user_id: str) -> bool:
        """
        Clear a user's session.

        Args:
            user_id: User identifier

        Returns:
            True if session was cleared, False if not found
        """
        with self._lock:
            self._store.delete(user_id)
            if user_id in self._sessions:
                del self._sessions[user_id]
                logger.info(f"Cleared session for user {user_id}")
                return True
            return False

    def get_session_info(self, user_id: str) -> Optional[dict]:
        """
        Get session information for display.

        Args:
            user_id: User identifier

        Returns:
            Session info dict or None
        """
        with self._lock:
            session = self._sessions.get(user_id)
            if not session:
                return None

            return {
                'user_id': session.user_id,
                'history_count': len(session.history),
                'created_at': session.created_at,
                'last_active': session.last_active,
                'is_expired': self.is_expired(session),
                'age_minutes': (datetime.now() - session.created_at).total_seconds() / 60
            }

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions.

        Returns:
            Number of sessions removed
        """
        with self._lock:
            expired_users = [
                user_id for user_id, session in self._sessions.items()
                if self.is_expired(session)
            ]

            for user_id in expired_users:
                del self._sessions[user_id]
                self._store.delete(user_id)

                # Callback
                if self._on_session_expired:
                    try:
                        self._on_session_expired(user_id)
                    except Exception as e:
                        logger.warning(f"Session expired callback failed: {e}")

            if expired_users:
                logger.info(f"Cleaned up {len(expired_users)} expired sessions")
                self._sessions_cleaned += len(expired_users)

            self._cleanup_runs += 1
            return len(expired_users)

    def get_stats(self) -> SessionStats:
        """
        Get session manager statistics.

        Returns:
            SessionStats with current state
        """
        with self._lock:
            total_messages = sum(
                len(s.history) for s in self._sessions.values()
            )

            oldest_age = 0.0
            if self._sessions:
                oldest = min(
                    s.created_at for s in self._sessions.values()
                )
                oldest_age = (datetime.now() - oldest).total_seconds() / 60

            return SessionStats(
                active_sessions=len(self._sessions),
                total_messages=total_messages,
                oldest_session_age_minutes=oldest_age,
                cleanup_runs=self._cleanup_runs,
                sessions_cleaned=self._sessions_cleaned
            )

    async def start_cleanup_task(self) -> None:
        """Start the background cleanup task"""
        if self._running:
            logger.warning("Cleanup task already running")
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session cleanup task started")

    async def stop_cleanup_task(self) -> None:
        """Stop the background cleanup task"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Session cleanup task stopped")

    async def _cleanup_loop(self) -> None:
        """Background loop for periodic cleanup"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                cleaned = self.cleanup_expired_sessions()
                logger.debug(f"Cleanup run completed: {cleaned} sessions removed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}", exc_info=True)

    def __len__(self) -> int:
        """Return number of active sessions"""
        with self._lock:
            return len(self._sessions)

    def __contains__(self, user_id: str) -> bool:
        """Check if user has an active session"""
        return self.get_session(user_id) is not None


# Singleton instance for app-wide use
_session_manager: Optional[SessionManager] = None


def get_session_manager(
    timeout_minutes: int = 30,
    max_history_length: int = 20,
    cleanup_interval_seconds: int = 300
) -> SessionManager:
    """
    Get or create the singleton SessionManager instance.

    Args:
        timeout_minutes: Session TTL (only used on first call)
        max_history_length: Max history length (only used on first call)
        cleanup_interval_seconds: Cleanup interval (only used on first call)

    Returns:
        SessionManager singleton instance
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(
            timeout_minutes=timeout_minutes,
            max_history_length=max_history_length,
            cleanup_interval_seconds=cleanup_interval_seconds
        )
    return _session_manager
