"""
Database models and operations for bookmark system
"""
import os
from datetime import datetime
from typing import List, Optional
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as async_sessionmaker
from sqlalchemy.future import select

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./linebot_bookmarks.db")

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# Create async session factory
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


class Bookmark(Base):
    """
    Bookmark model for storing user's saved URLs

    Attributes:
        id: Primary key
        user_id: LINE user ID
        url: Bookmarked URL
        title: Page title or user-provided title
        summary: AI-generated summary
        summary_mode: Mode used for summarization (short/normal/detailed)
        tags: Comma-separated tags
        created_at: Timestamp when bookmark was created
        accessed_count: Number of times bookmark was accessed
    """
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(100), nullable=False, index=True)
    url = Column(Text, nullable=False)
    title = Column(String(500))
    summary = Column(Text)
    summary_mode = Column(String(20), default="normal")  # short, normal, detailed
    tags = Column(Text)  # Comma-separated tags
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    accessed_count = Column(Integer, default=0)

    # Create composite index for user_id and created_at for efficient queries
    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self):
        """Convert bookmark to dictionary"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "url": self.url,
            "title": self.title,
            "summary": self.summary[:200] + "..." if self.summary and len(self.summary) > 200 else self.summary,
            "summary_mode": self.summary_mode,
            "tags": self.tags.split(",") if self.tags else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "accessed_count": self.accessed_count
        }


class SearchHistory(Base):
    """
    Search history model for tracking user searches

    Attributes:
        id: Primary key
        user_id: LINE user ID
        query: Search query
        results_count: Number of results found
        created_at: Timestamp when search was performed
    """
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(100), nullable=False, index=True)
    query = Column(String(500), nullable=False)
    results_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_user_search_created', 'user_id', 'created_at'),
    )


# Database operations
async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Get database session"""
    async with async_session() as session:
        yield session


# Bookmark operations
async def create_bookmark(
    user_id: str,
    url: str,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    summary_mode: str = "normal",
    tags: Optional[str] = None
) -> Bookmark:
    """
    Create a new bookmark

    Args:
        user_id: LINE user ID
        url: URL to bookmark
        title: Page title
        summary: AI-generated summary
        summary_mode: Summarization mode used
        tags: Comma-separated tags

    Returns:
        Created bookmark object
    """
    async with async_session() as session:
        bookmark = Bookmark(
            user_id=user_id,
            url=url,
            title=title,
            summary=summary,
            summary_mode=summary_mode,
            tags=tags
        )
        session.add(bookmark)
        await session.commit()
        await session.refresh(bookmark)
        return bookmark


async def get_user_bookmarks(
    user_id: str,
    limit: int = 10,
    offset: int = 0
) -> List[Bookmark]:
    """
    Get user's bookmarks

    Args:
        user_id: LINE user ID
        limit: Maximum number of bookmarks to return
        offset: Offset for pagination

    Returns:
        List of bookmarks
    """
    async with async_session() as session:
        result = await session.execute(
            select(Bookmark)
            .filter(Bookmark.user_id == user_id)
            .order_by(Bookmark.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()


async def search_bookmarks(
    user_id: str,
    keyword: str,
    limit: int = 10
) -> List[Bookmark]:
    """
    Search bookmarks by keyword

    Args:
        user_id: LINE user ID
        keyword: Search keyword
        limit: Maximum number of results

    Returns:
        List of matching bookmarks
    """
    async with async_session() as session:
        keyword_pattern = f"%{keyword}%"
        result = await session.execute(
            select(Bookmark)
            .filter(
                Bookmark.user_id == user_id,
                (
                    Bookmark.title.like(keyword_pattern) |
                    Bookmark.summary.like(keyword_pattern) |
                    Bookmark.tags.like(keyword_pattern) |
                    Bookmark.url.like(keyword_pattern)
                )
            )
            .order_by(Bookmark.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


async def delete_bookmark(bookmark_id: int, user_id: str) -> bool:
    """
    Delete a bookmark

    Args:
        bookmark_id: Bookmark ID
        user_id: LINE user ID (for authorization)

    Returns:
        True if deleted, False if not found
    """
    async with async_session() as session:
        result = await session.execute(
            select(Bookmark).filter(
                Bookmark.id == bookmark_id,
                Bookmark.user_id == user_id
            )
        )
        bookmark = result.scalar_one_or_none()

        if bookmark:
            await session.delete(bookmark)
            await session.commit()
            return True
        return False


async def increment_bookmark_access(bookmark_id: int, user_id: str):
    """
    Increment access count for a bookmark

    Args:
        bookmark_id: Bookmark ID
        user_id: LINE user ID
    """
    async with async_session() as session:
        result = await session.execute(
            select(Bookmark).filter(
                Bookmark.id == bookmark_id,
                Bookmark.user_id == user_id
            )
        )
        bookmark = result.scalar_one_or_none()

        if bookmark:
            bookmark.accessed_count += 1
            await session.commit()


async def get_bookmark_stats(user_id: str) -> dict:
    """
    Get user's bookmark statistics

    Args:
        user_id: LINE user ID

    Returns:
        Dictionary with statistics
    """
    async with async_session() as session:
        result = await session.execute(
            select(Bookmark).filter(Bookmark.user_id == user_id)
        )
        bookmarks = result.scalars().all()

        return {
            "total_bookmarks": len(bookmarks),
            "total_accessed": sum(b.accessed_count for b in bookmarks),
            "most_accessed": max((b.to_dict() for b in bookmarks), key=lambda x: x['accessed_count']) if bookmarks else None
        }


# Search history operations
async def record_search(user_id: str, query: str, results_count: int = 0):
    """
    Record a search query

    Args:
        user_id: LINE user ID
        query: Search query
        results_count: Number of results found
    """
    async with async_session() as session:
        search = SearchHistory(
            user_id=user_id,
            query=query,
            results_count=results_count
        )
        session.add(search)
        await session.commit()


async def get_recent_searches(user_id: str, limit: int = 5) -> List[SearchHistory]:
    """
    Get user's recent searches

    Args:
        user_id: LINE user ID
        limit: Maximum number of searches to return

    Returns:
        List of search history entries
    """
    async with async_session() as session:
        result = await session.execute(
            select(SearchHistory)
            .filter(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
