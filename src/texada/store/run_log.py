"""Request-level run log inspired by CC Switch's proxy request ledger."""
from __future__ import annotations

import json

import aiosqlite

from texada.config import TeXadaConfig
from texada.types import RunLogEntry

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_logs (
    run_id          TEXT PRIMARY KEY,
    operation       TEXT NOT NULL,
    input_type      TEXT NOT NULL,
    input_text      TEXT NOT NULL,
    input_bytes     INTEGER NOT NULL DEFAULT 0,
    input_mime      TEXT NOT NULL DEFAULT '',
    model_role      TEXT NOT NULL DEFAULT '',
    model_name      TEXT NOT NULL DEFAULT '',
    backend         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL,
    status_code     INTEGER NOT NULL,
    output_latex    TEXT NOT NULL DEFAULT '',
    intent          TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT '',
    render_mode     TEXT NOT NULL DEFAULT '',
    valid           BOOLEAN,
    latency_ms      REAL NOT NULL DEFAULT 0,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    stop_reason     TEXT NOT NULL DEFAULT '',
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    tool_names_json TEXT NOT NULL DEFAULT '[]',
    trace_json      TEXT NOT NULL DEFAULT '[]',
    error_message   TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_run_logs_created ON run_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_logs_operation ON run_logs(operation);
CREATE INDEX IF NOT EXISTS idx_run_logs_status ON run_logs(status);
CREATE INDEX IF NOT EXISTS idx_run_logs_model ON run_logs(model_name);
"""


class RunLogStore:
    """SQLite-backed execution ledger with searchable request-level detail."""

    def __init__(self, config: TeXadaConfig):
        self.db_path = config.data_dir / "runs.db"
        self.max_days = config.run_log_max_days
        self.max_items = config.run_log_max_items
        self._initialized = False

    async def _get_conn(self) -> aiosqlite.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        if not self._initialized:
            await conn.executescript(SCHEMA)
            await conn.commit()
            self._initialized = True
        return conn

    async def add(self, entry: RunLogEntry) -> str:
        if not entry.run_id.strip():
            raise ValueError("run_id is required")
        conn = await self._get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO run_logs (
                    run_id, operation, input_type, input_text, input_bytes, input_mime,
                    model_role, model_name, backend, status, status_code, output_latex,
                    intent, source, render_mode, valid, latency_ms, tokens_used,
                    stop_reason, tool_call_count, tool_names_json, trace_json,
                    error_message, created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP)
                )
                """,
                self._params(entry),
            )
            await self._cleanup_locked(conn)
            await conn.commit()
            return entry.run_id
        finally:
            await conn.close()

    async def get(self, run_id: str) -> RunLogEntry | None:
        conn = await self._get_conn()
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM run_logs WHERE run_id = ? LIMIT 1",
                (run_id,),
            )
            return self._row_to_entry(rows[0]) if rows else None
        finally:
            await conn.close()

    async def list_recent(
        self,
        query: str = "",
        *,
        operation: str = "",
        status: str = "",
        limit: int = 50,
        offset: int = 0,
        include_trace: bool = True,
    ) -> list[RunLogEntry]:
        conn = await self._get_conn()
        try:
            clauses: list[str] = []
            params: list[str | int] = []
            if operation.strip() and operation != "all":
                clauses.append("operation = ?")
                params.append(operation.strip().lower())
            if status.strip() and status != "all":
                clauses.append("status = ?")
                params.append(status.strip().lower())
            if query.strip():
                pattern = f"%{query.strip()}%"
                clauses.append(
                    "(run_id LIKE ? OR input_text LIKE ? OR output_latex LIKE ? "
                    "OR model_name LIKE ? OR error_message LIKE ? OR tool_names_json LIKE ?)"
                )
                params.extend([pattern] * 6)
            if include_trace:
                sql = "SELECT *, 0 AS stored_trace_available FROM run_logs"
            else:
                sql = (
                    "SELECT run_id, operation, input_type, input_text, input_bytes, "
                    "input_mime, model_role, model_name, backend, status, status_code, "
                    "output_latex, intent, source, render_mode, valid, latency_ms, "
                    "tokens_used, stop_reason, tool_call_count, tool_names_json, "
                    "'' AS trace_json, error_message, created_at, "
                    "CASE WHEN LENGTH(TRIM(trace_json)) > 2 THEN 1 ELSE 0 END "
                    "AS stored_trace_available FROM run_logs"
                )
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = await conn.execute_fetchall(sql, params)
            return [self._row_to_entry(row) for row in rows]
        finally:
            await conn.close()

    async def export_all(self) -> list[RunLogEntry]:
        conn = await self._get_conn()
        try:
            rows = await conn.execute_fetchall(
                "SELECT * FROM run_logs ORDER BY created_at DESC, rowid DESC"
            )
            return [self._row_to_entry(row) for row in rows]
        finally:
            await conn.close()

    async def import_entries(
        self,
        entries: list[RunLogEntry],
        *,
        mode: str = "merge",
    ) -> dict[str, int]:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"merge", "replace"}:
            raise ValueError("mode must be 'merge' or 'replace'")
        conn = await self._get_conn()
        imported = 0
        skipped = 0
        cleared = 0
        try:
            if normalized_mode == "replace":
                cursor = await conn.execute("DELETE FROM run_logs")
                cleared = max(cursor.rowcount, 0)
            for entry in entries:
                if not entry.run_id.strip():
                    skipped += 1
                    continue
                existing = await conn.execute_fetchall(
                    "SELECT run_id FROM run_logs WHERE run_id = ? LIMIT 1",
                    (entry.run_id,),
                )
                if existing:
                    skipped += 1
                    continue
                await conn.execute(
                    """
                    INSERT INTO run_logs (
                        run_id, operation, input_type, input_text, input_bytes, input_mime,
                        model_role, model_name, backend, status, status_code, output_latex,
                        intent, source, render_mode, valid, latency_ms, tokens_used,
                        stop_reason, tool_call_count, tool_names_json, trace_json,
                        error_message, created_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP)
                    )
                    """,
                    self._params(entry),
                )
                imported += 1
            await self._cleanup_locked(conn)
            await conn.commit()
            return {"imported": imported, "skipped": skipped, "cleared": cleared}
        finally:
            await conn.close()

    async def clear(self) -> int:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute("DELETE FROM run_logs")
            deleted = max(cursor.rowcount, 0)
            await conn.commit()
            return deleted
        finally:
            await conn.close()

    async def _cleanup_locked(self, conn: aiosqlite.Connection) -> int:
        deleted = 0
        if self.max_days > 0:
            cursor = await conn.execute(
                "DELETE FROM run_logs WHERE created_at < datetime('now', ?)",
                (f"-{self.max_days} days",),
            )
            deleted += max(cursor.rowcount, 0)
        if self.max_items > 0:
            cursor = await conn.execute(
                """
                DELETE FROM run_logs
                WHERE run_id IN (
                    SELECT run_id FROM run_logs
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self.max_items,),
            )
            deleted += max(cursor.rowcount, 0)
        return deleted

    @staticmethod
    def _params(entry: RunLogEntry) -> tuple:
        valid = None if entry.valid is None else bool(entry.valid)
        return (
            entry.run_id,
            entry.operation,
            entry.input_type,
            entry.input_text,
            entry.input_bytes,
            entry.input_mime,
            entry.model_role,
            entry.model_name,
            entry.backend,
            entry.status,
            entry.status_code,
            entry.output_latex,
            entry.intent,
            entry.source,
            entry.render_mode,
            valid,
            entry.latency_ms,
            entry.tokens_used,
            entry.stop_reason,
            entry.tool_call_count,
            json.dumps(entry.tool_names, ensure_ascii=False),
            json.dumps(entry.trace, ensure_ascii=False),
            entry.error_message,
            entry.created_at,
        )

    @staticmethod
    def _loads_list(raw: str) -> list:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @classmethod
    def _row_to_entry(cls, row: aiosqlite.Row) -> RunLogEntry:
        trace = cls._loads_list(row["trace_json"])
        trace_available = bool(trace)
        if "stored_trace_available" in row.keys():
            trace_available = trace_available or bool(row["stored_trace_available"])
        return RunLogEntry(
            run_id=row["run_id"],
            operation=row["operation"],
            input_type=row["input_type"],
            input_text=row["input_text"],
            input_bytes=row["input_bytes"],
            input_mime=row["input_mime"],
            model_role=row["model_role"],
            model_name=row["model_name"],
            backend=row["backend"],
            status=row["status"],
            status_code=row["status_code"],
            output_latex=row["output_latex"],
            intent=row["intent"],
            source=row["source"],
            render_mode=row["render_mode"],
            valid=None if row["valid"] is None else bool(row["valid"]),
            latency_ms=row["latency_ms"],
            tokens_used=row["tokens_used"],
            stop_reason=row["stop_reason"],
            tool_call_count=row["tool_call_count"],
            tool_names=cls._loads_list(row["tool_names_json"]),
            trace=trace,
            trace_available=trace_available,
            error_message=row["error_message"],
            created_at=row["created_at"],
        )
