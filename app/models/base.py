"""SQLAlchemy base configuration and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

settings = get_settings()


def get_engine():
    """Create a new async engine (use for the current event loop)."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.debug,
    )


def get_session_factory(engine=None):
    """Create a session factory for the given engine."""
    if engine is None:
        engine = get_engine()
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Default engine and session factory for FastAPI (single event loop)
engine = get_engine()
async_session_factory = get_session_factory(engine)


@asynccontextmanager
async def get_task_session():
    """
    Get a database session for use in Celery tasks.

    Creates a fresh engine and session factory to avoid event loop issues.
    """
    task_engine = get_engine()
    task_session_factory = get_session_factory(task_engine)
    async with task_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
    await task_engine.dispose()


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
