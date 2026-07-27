"""History Store — SQLite-backed history with auto-cleanup."""
from __future__ import annotations

import aiosqlite

from texada.config import TeXadaConfig
from texada.types import HistoryEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_history_latex ON history(latex);
CREATE INDEX IF NOT EXISTS idx_history_type ON history(input_type);
"""


class HistoryStore:
    """SQLite history — auto-cleanup >30 days."""

    def __init__(self, config: TeXadaConfig):
        self.db_path = config.data_dir / "history.db"
        self.max_days = config.history_max_days
        self.max_items = config.history_max_items
        self._initialized = False

    async def _get_conn(self) -> aiosqlite.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        if not self._initialized:
            await conn.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in await conn.execute_fetchall("PRAGMA table_info(history)")
            }
            if "run_id" not in columns:
                await conn.execute(
                    "ALTER TABLE history ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"
                )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_run_id ON history(run_id)"
            )
            await conn.commit()
            self._initialized = True
        return conn

    async def add(self, entry: HistoryEntry) -> int:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute_insert(
                "INSERT INTO history (run_id, input_text, input_type, latex, intent, source, "
                "render_mode, valid, latency_ms, tokens_used, starred) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.run_id, entry.input_text, entry.input_type, entry.latex, entry.intent,
                 entry.source, entry.render_mode, entry.valid, entry.latency_ms,
                 entry.tokens_used, entry.starred),
            )
            await self._cleanup_locked(conn)
            await conn.commit()
            return cursor[0]
        finally:
            await conn.close()

    async def export_all(self, input_type: str = "") -> list[HistoryEntry]:
        """Export history entries without UI pagination limits."""
        conn = await self._get_conn()
        try:
            params: list[str] = []
            sql = "SELECT * FROM history"
            normalized_type = input_type.strip().lower()
            if normalized_type and normalized_type != "all":
                sql += " WHERE input_type = ?"
                params.append(normalized_type)
            sql += " ORDER BY created_at DESC, id DESC"
            rows = await conn.execute_fetchall(sql, params)
            return [self._row_to_entry(row) for row in rows]
        finally:
            await conn.close()

    async def import_entries(
        self,
        entries: list[HistoryEntry],
        *,
        mode: str = "merge",
    ) -> dict[str, int]:
        """Import history entries.

        ``merge`` skips exact duplicates; ``replace`` clears history first.
        """
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"merge", "replace"}:
            raise ValueError("mode must be 'merge' or 'replace'")

        conn = await self._get_conn()
        imported = 0
        skipped = 0
        cleared = 0
        try:
            if normalized_mode == "replace":
                cursor = await conn.execute("DELETE FROM history")
                cleared = max(cursor.rowcount, 0)

            for entry in entries:
                if entry.run_id.strip():
                    duplicate = await conn.execute_fetchall(
                        "SELECT id FROM history WHERE run_id = ? LIMIT 1",
                        (entry.run_id,),
                    )
                else:
                    duplicate = await conn.execute_fetchall(
                        """
                        SELECT id FROM history
                        WHERE input_text = ?
                          AND input_type = ?
                          AND latex = ?
                          AND created_at = ?
                        LIMIT 1
                        """,
                        (entry.input_text, entry.input_type, entry.latex, entry.created_at),
                    )
                if duplicate:
                    skipped += 1
                    continue

                await conn.execute(
                    """
                    INSERT INTO history (
                        run_id, input_text, input_type, latex, intent, source, render_mode,
                        valid, latency_ms, tokens_used, starred, created_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP)
                    )
                    """,
                    (
                        entry.run_id,
                        entry.input_text,
                        entry.input_type,
                        entry.latex,
                        entry.intent,
                        entry.source,
                        entry.render_mode,
                        entry.valid,
                        entry.latency_ms,
                        entry.tokens_used,
                        entry.starred,
                        entry.created_at,
                    ),
                )
                imported += 1

            await self._cleanup_locked(conn)
            await conn.commit()
            return {"imported": imported, "skipped": skipped, "cleared": cleared}
        finally:
            await conn.close()

    async def clear(self, input_type: str = "") -> int:
        """Clear all history, or only one history type."""
        conn = await self._get_conn()
        try:
            normalized_type = input_type.strip().lower()
            if normalized_type and normalized_type != "all":
                cursor = await conn.execute(
                    "DELETE FROM history WHERE input_type = ?",
                    (normalized_type,),
                )
            else:
                cursor = await conn.execute("DELETE FROM history")
            deleted = max(cursor.rowcount, 0)
            await conn.commit()
            return deleted
        finally:
            await conn.close()

    async def list_recent(
        self,
        query: str = "",
        limit: int = 50,
        input_type: str = "",
    ) -> list[HistoryEntry]:
        conn = await self._get_conn()
        try:
            clauses: list[str] = []
            params: list[str | int] = []
            normalized_type = input_type.strip().lower()
            if normalized_type and normalized_type != "all":
                clauses.append("input_type = ?")
                params.append(normalized_type)
            normalized_query = query.strip()
            if normalized_query:
                pattern = f"%{normalized_query}%"
                clauses.append(
                    "(input_text LIKE ? OR latex LIKE ? OR intent LIKE ? OR source LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])

            sql = "SELECT * FROM history"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = await conn.execute_fetchall(sql, params)
            return [self._row_to_entry(row) for row in rows]
        finally:
            await conn.close()

    async def cleanup(self) -> int:
        """Delete entries older than max_days and trim records beyond max_items."""
        conn = await self._get_conn()
        try:
            deleted = await self._cleanup_locked(conn)
            await conn.commit()
            return deleted
        finally:
            await conn.close()

    async def _cleanup_locked(self, conn: aiosqlite.Connection) -> int:
        deleted = 0
        if self.max_days > 0:
            cursor = await conn.execute(
                "DELETE FROM history WHERE created_at < datetime('now', ?)",
                (f"-{self.max_days} days",),
            )
            deleted += max(cursor.rowcount, 0)
        if self.max_items > 0:
            cursor = await conn.execute(
                """
                DELETE FROM history
                WHERE id IN (
                    SELECT id FROM history
                    ORDER BY starred DESC, created_at DESC, id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self.max_items,),
            )
            deleted += max(cursor.rowcount, 0)
        return deleted

    @staticmethod
    def _row_to_entry(row: aiosqlite.Row) -> HistoryEntry:
        return HistoryEntry(
            id=row["id"],
            run_id=row["run_id"],
            input_text=row["input_text"],
            input_type=row["input_type"],
            latex=row["latex"],
            intent=row["intent"],
            source=row["source"],
            render_mode=row["render_mode"],
            valid=bool(row["valid"]),
            latency_ms=row["latency_ms"],
            tokens_used=row["tokens_used"],
            starred=bool(row["starred"]),
            created_at=row["created_at"],
        )
