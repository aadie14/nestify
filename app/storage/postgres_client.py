"""PostgreSQL Client — Production metadata backend with SQLite fallback.

Implements a minimal StorageBackend interface used for state persistence.
If PostgreSQL is unavailable, operations transparently route to SQLite.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.database.db import get_connection

logger = logging.getLogger(__name__)


class StorageBackend(Protocol):
    """Abstract metadata storage backend."""

    async def execute(self, query: str, *args: Any) -> None:
        ...

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        ...

    async def close(self) -> None:
        ...


@dataclass(slots=True)
class SQLiteFallbackBackend(StorageBackend):
    """SQLite fallback adapter for development/offline mode."""

    async def execute(self, query: str, *args: Any) -> None:
        conn = get_connection()
        try:
            conn.execute(query, args)
            conn.commit()
        finally:
            conn.close()

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(query, args).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def close(self) -> None:
        return


class PostgresClient(StorageBackend):
    """Async PostgreSQL wrapper that degrades to SQLite fallback."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None
        self._connected = False
        self._fallback = SQLiteFallbackBackend()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to PostgreSQL if DSN is configured and reachable."""

        if not self._dsn:
            logger.warning("POSTGRES_DSN not set — using SQLite metadata backend")
            self._connected = False
            return False

        try:
            import asyncpg  # type: ignore[import-untyped]

            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=5)
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            self._connected = True
            logger.info("Connected to PostgreSQL metadata backend")
        except Exception as exc:
            self._connected = False
            logger.warning("PostgreSQL unavailable (%s) — using SQLite fallback", exc)

        return self._connected

    async def execute(self, query: str, *args: Any) -> None:
        if not self._connected or self._pool is None:
            await self._fallback.execute(query, *args)
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(query, *args)
        except Exception as exc:
            logger.warning("PostgreSQL execute failed (%s) — routing to SQLite fallback", exc)
            self._connected = False
            await self._fallback.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if not self._connected or self._pool is None:
            return await self._fallback.fetch(query, *args)

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("PostgreSQL fetch failed (%s) — routing to SQLite fallback", exc)
            self._connected = False
            return await self._fallback.fetch(query, *args)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        self._connected = False


_client: PostgresClient | None = None


async def get_postgres_client() -> PostgresClient:
    """Return the shared PostgreSQL client instance."""

    global _client
    if _client is None:
        _client = PostgresClient(settings.postgres_dsn)
        await _client.connect()
    return _client
