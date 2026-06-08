"""History Store — SQLite-backed history with auto-cleanup."""
from __future__ import annotations

import aiosqlite
from pathlib import Path

from texada.config import TeXadaConfig
from texada.types import HistoryEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text TEXT NOT NULL,
    input_type TEXT NOT NULL,
    latex      TEXT NOT NULL,
    intent     TEXT NOT NULL,
    source     TEXT NOT NULL,
    render_mode TEXT NOT NULL,
    valid      BOOLEAN NOT NULL,
    latency_ms REAL NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    starred    BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_input ON history(input_text);
"""


class HistoryStore:
    """SQLite history — auto-cleanup >30 days."""

    def __init__(self, config: TeXadaConfig):
        self.db_path = config.data_dir / "history.db"
        self.max_days = config.history_max_days
        self.max_items = config.history_max_items

    async def _get_conn(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path)
        await conn.executescript(SCHEMA)
        return conn

    async def add(self, entry: HistoryEntry) -> int:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute_insert(
                "INSERT INTO history (input_text, input_type, latex, intent, source, "
                "render_mode, valid, latency_ms, tokens_used, starred) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.input_text, entry.input_type, entry.latex, entry.intent,
                 entry.source, entry.render_mode, entry.valid, entry.latency_ms,
                 entry.tokens_used, entry.starred),
            )
            await conn.commit()
            return cursor
        finally:
            await conn.close()

    async def list_recent(self, query: str = "", limit: int = 50) -> list[HistoryEntry]:
        conn = await self._get_conn()
        try:
            if query:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM history WHERE input_text LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{query}%", limit),
                )
            else:
                rows = await conn.execute_fetchall(
                    "SELECT * FROM history ORDER BY created_at DESC LIMIT ?", (limit,),
                )
            return [HistoryEntry(**dict(row)) for row in rows]
        finally:
            await conn.close()

    async def cleanup(self) -> int:
        """Delete entries older than max_days."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "DELETE FROM history WHERE created_at < datetime('now', ?)",
                (f"-{self.max_days} days",),
            )
            await conn.commit()
            return cursor.rowcount
        finally:
            await conn.close()