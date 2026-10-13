"""Run log persistence, filtering, correlation, and backup tests."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from texada.agent.runtime import AgentRunResult, TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.render.engine import RenderEngine
from texada.store.history import HistoryStore
from texada.store.run_log import RunLogStore
from texada.types import RenderMode, RunLogEntry

LEGACY_RUN_LOG_SCHEMA = """
CREATE TABLE run_logs (
    run_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    input_type TEXT NOT NULL,
    input_text TEXT NOT NULL,
    input_bytes INTEGER NOT NULL DEFAULT 0,
    input_mime TEXT NOT NULL DEFAULT '',
    model_role TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    backend TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    output_latex TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    render_mode TEXT NOT NULL DEFAULT '',
    valid BOOLEAN,
    latency_ms REAL NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT NOT NULL DEFAULT '',
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    tool_names_json TEXT NOT NULL DEFAULT '[]',
    trace_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture
def inference_fingerprint():
    return {
        "schema_version": 1,
        "status": "REPORTED",
        "identity": {
            "backend": "openai",
            "configured_model": "MiniCPM-V-4.7-1B",
        },
        "identity_sha256": "recorded-identity-hash",
        "calls": [
            {
                "purpose": "ocr",
                "requested_model": "MiniCPM-V-4.7-1B",
                "reported_model": {"value": "provider-alias", "status": "REPORTED"},
            }
        ],
    }


@pytest.mark.asyncio
async def test_run_log_store_round_trip_filters_and_deduplicates(tmp_path, inference_fingerprint):
    store = RunLogStore(TeXadaConfig(data_dir=tmp_path))
    entry = RunLogEntry(
        run_id="run-1",
        operation="agent",
        input_type="nl",
        input_text="二重积分",
        model_role="planner",
        model_name="MiniCPM5-1B",
        backend="ollama",
        status="success",
        status_code=200,
        output_latex="\\iint_D f",
        valid=True,
        latency_ms=12.5,
        tokens_used=24,
        stop_reason="planner_final",
        tool_call_count=2,
        tool_names=["parse_tex", "render_math"],
        trace=[{"step": 1, "tool_calls": [{"name": "parse_tex"}]}],
        inference_fingerprint=inference_fingerprint,
    )

    assert await store.add(entry) == "run-1"
    loaded = await store.get("run-1")
    assert loaded is not None
    assert loaded.tool_names == ["parse_tex", "render_math"]
    assert loaded.trace[0]["step"] == 1
    assert loaded.inference_fingerprint == inference_fingerprint

    assert [item.run_id for item in await store.list_recent("MiniCPM")] == ["run-1"]
    assert await store.list_recent(status="error") == []
    assert [item.run_id for item in await store.list_recent(operation="agent")] == ["run-1"]
    summary = (await store.list_recent(include_trace=False))[0]
    assert summary.trace == []
    assert summary.trace_available is True
    assert summary.inference_fingerprint == inference_fingerprint

    imported = await store.import_entries([entry])
    assert imported == {"imported": 0, "skipped": 1, "cleared": 0}


@pytest.mark.asyncio
async def test_run_log_migrates_old_database_once_without_inventing_identity(tmp_path):
    with sqlite3.connect(tmp_path / "runs.db") as conn:
        conn.executescript(LEGACY_RUN_LOG_SCHEMA)
        conn.execute(
            "INSERT INTO run_logs ("
            "run_id, operation, input_type, input_text, model_name, status, status_code"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "convert", "nl", "historical request", "old-model", "success", 200),
        )

    expected = {
        "schema_version": 1,
        "status": "NOT_CHECKED",
        "reason": "legacy_record",
        "identity": None,
        "identity_sha256": None,
        "calls": [],
    }
    config = TeXadaConfig(data_dir=tmp_path, model_name="different-current-model")
    # New instances repeat initialization against an already migrated database.
    for _ in range(2):
        loaded = await RunLogStore(config).get("legacy")
        assert loaded is not None
        assert loaded.model_name == "old-model"
        assert loaded.inference_fingerprint == expected

    with sqlite3.connect(tmp_path / "runs.db") as conn:
        columns = conn.execute("PRAGMA table_info(run_logs)").fetchall()
        assert [column[1] for column in columns].count("inference_fingerprint_json") == 1
        assert conn.execute(
            "SELECT inference_fingerprint_json FROM run_logs WHERE run_id = 'legacy'"
        ).fetchone() == ("",)


@pytest.mark.asyncio
async def test_run_log_migration_handles_concurrent_store_initialization(tmp_path):
    with sqlite3.connect(tmp_path / "runs.db") as conn:
        conn.executescript(LEGACY_RUN_LOG_SCHEMA)

    stores = [RunLogStore(TeXadaConfig(data_dir=tmp_path)) for _ in range(2)]
    await asyncio.gather(*(store.list_recent() for store in stores))

    with sqlite3.connect(tmp_path / "runs.db") as conn:
        columns = conn.execute("PRAGMA table_info(run_logs)").fetchall()
        assert [column[1] for column in columns].count("inference_fingerprint_json") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_message", "column_present", "accepted"),
    [
        ("duplicate column name: inference_fingerprint_json", True, True),
        ("duplicate column name: inference_fingerprint_json", False, False),
        ("database is locked", True, False),
    ],
)
async def test_run_log_migration_only_accepts_verified_duplicate_race(
    error_message, column_present, accepted
):
    after_race = [{"name": "inference_fingerprint_json"}] if column_present else []
    conn = SimpleNamespace(
        execute_fetchall=AsyncMock(side_effect=[[], after_race]),
        execute=AsyncMock(side_effect=aiosqlite.OperationalError(error_message)),
    )

    if accepted:
        await RunLogStore._migrate_inference_fingerprint(conn)
        assert conn.execute_fetchall.await_count == 2
    else:
        with pytest.raises(aiosqlite.OperationalError, match=error_message):
            await RunLogStore._migrate_inference_fingerprint(conn)
        expected_queries = 2 if "duplicate column" in error_message else 1
        assert conn.execute_fetchall.await_count == expected_queries


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["merge", "replace"])
async def test_run_log_backup_preserves_inference_fingerprint(
    tmp_path, inference_fingerprint, mode
):
    source = RunLogStore(TeXadaConfig(data_dir=tmp_path / "source"))
    await source.add(
        RunLogEntry(
            run_id="recorded",
            operation="ocr",
            inference_fingerprint=inference_fingerprint,
        )
    )
    # A JSON backup round trip must preserve the entire envelope, including calls.
    exported = await source.export_all()
    backup = json.loads(json.dumps([asdict(entry) for entry in exported]))
    imported_entries = [RunLogEntry(**entry) for entry in backup]
    destination = RunLogStore(TeXadaConfig(data_dir=tmp_path / mode))
    await destination.add(RunLogEntry(run_id="existing", operation="validate"))

    result = await destination.import_entries(imported_entries, mode=mode)
    assert result == {"imported": 1, "skipped": 0, "cleared": int(mode == "replace")}
    loaded = await destination.get("recorded")
    assert loaded is not None
    assert loaded.inference_fingerprint == inference_fingerprint
    summary = (await destination.list_recent(operation="ocr", include_trace=False))[0]
    assert summary.inference_fingerprint == inference_fingerprint
    duplicate = await destination.import_entries(imported_entries)
    assert duplicate == {"imported": 0, "skipped": 1, "cleared": 0}
    assert (await destination.get("recorded")).inference_fingerprint == inference_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["", "{broken", "[]", "null", '"old"', "42"])
async def test_run_log_invalid_fingerprint_json_is_legacy(tmp_path, raw):
    store = RunLogStore(TeXadaConfig(data_dir=tmp_path))
    entry = RunLogEntry(run_id="invalid", operation="validate")
    await store.add(entry)
    with sqlite3.connect(tmp_path / "runs.db") as conn:
        conn.execute(
            "UPDATE run_logs SET inference_fingerprint_json = ? WHERE run_id = ?",
            (raw, entry.run_id),
        )

    loaded = await store.get(entry.run_id)
    assert loaded is not None
    assert loaded.inference_fingerprint == entry.inference_fingerprint
    assert loaded.inference_fingerprint["reason"] == "legacy_record"


def test_run_log_missing_fingerprint_column_is_legacy():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(LEGACY_RUN_LOG_SCHEMA)
        conn.execute(
            "INSERT INTO run_logs (run_id, operation, input_type, input_text, status, status_code) "
            "VALUES ('legacy', 'validate', '', '', 'success', 200)"
        )
        row = conn.execute("SELECT * FROM run_logs").fetchone()

    entry = RunLogStore._row_to_entry(row)
    assert entry.inference_fingerprint["status"] == "NOT_CHECKED"
    assert entry.inference_fingerprint["reason"] == "legacy_record"


@pytest.mark.asyncio
async def test_run_log_default_is_unlimited_and_optional_item_cap_still_works(tmp_path):
    unlimited = RunLogStore(TeXadaConfig(data_dir=tmp_path / "unlimited"))
    for index in range(3):
        await unlimited.add(
            RunLogEntry(
                run_id=f"unlimited-{index}",
                operation="validate",
                status="success",
                status_code=200,
            )
        )
    assert len(await unlimited.export_all()) == 3

    capped = RunLogStore(
        TeXadaConfig(
            data_dir=tmp_path / "capped",
            run_log_max_items=2,
        )
    )
    for index in range(3):
        await capped.add(
            RunLogEntry(
                run_id=f"capped-{index}",
                operation="validate",
                status="success",
                status_code=200,
            )
        )
    assert [item.run_id for item in await capped.export_all()] == [
        "capped-2",
        "capped-1",
    ]


@pytest.mark.asyncio
async def test_history_migrates_old_database_and_correlates_run_id(tmp_path):
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input_text TEXT NOT NULL,
            input_type TEXT NOT NULL,
            latex TEXT NOT NULL,
            intent TEXT NOT NULL,
            source TEXT NOT NULL,
            render_mode TEXT NOT NULL,
            valid BOOLEAN NOT NULL,
            latency_ms REAL NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            starred BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO history (
            input_text, input_type, latex, intent, source, render_mode, valid, latency_ms
        ) VALUES ('old', 'nl', 'x', 'generic', 'model', 'katex', 1, 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = HistoryStore(TeXadaConfig(data_dir=tmp_path))
    entries = await store.list_recent()

    assert len(entries) == 1
    assert entries[0].run_id == ""


@pytest.mark.asyncio
async def test_agent_api_records_success_trace_and_history_correlation(tmp_path, monkeypatch):
    async def fake_run(self, user_input, *, context="", render_mode=RenderMode.KATEX):
        renderer = RenderEngine(self.config)
        return AgentRunResult(
            latex="x^2",
            valid=True,
            render=renderer.render("x^2", mode_override=render_mode),
            semantic_document={"kind": "document"},
            trace=[
                {
                    "step": 1,
                    "tool_calls": [{"name": "parse_tex"}],
                    "observations": [],
                }
            ],
            tokens_used=7,
            latency_ms=8.0,
            stop_reason="planner_final",
        )

    monkeypatch.setattr(TeXadaAgentRuntime, "run", fake_run)

    from texada.api import create_app

    client = TestClient(create_app(TeXadaConfig(data_dir=tmp_path)))
    response = client.post("/api/agent", json={"text": "x squared"})

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] == "success"
    assert detail["operation"] == "agent"
    assert detail["tool_names"] == ["parse_tex"]
    assert detail["tool_call_count"] == 1
    assert detail["trace"][0]["step"] == 1

    summary = client.get("/api/runs?operation=agent").json()[0]
    assert summary["trace_available"] is True
    assert "trace" not in summary

    history = client.get("/api/history").json()
    assert history[0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_agent_api_records_failure_and_run_import_export(tmp_path, monkeypatch):
    async def fail_run(self, user_input, *, context="", render_mode=RenderMode.KATEX):
        raise RuntimeError("planner unavailable")

    monkeypatch.setattr(TeXadaAgentRuntime, "run", fail_run)

    from texada.api import create_app

    client = TestClient(create_app(TeXadaConfig(data_dir=tmp_path)))
    response = client.post("/api/agent", json={"text": "x"})

    assert response.status_code == 503
    runs = client.get("/api/runs?status=error").json()
    assert len(runs) == 1
    assert runs[0]["error_message"] == "planner unavailable"
    assert runs[0]["status_code"] == 503

    exported = client.get("/api/runs/export").json()
    assert exported["_meta"]["schema_version"] == 2
    duplicate = client.post(
        "/api/runs/import",
        json={"mode": "merge", "run_logs": exported["run_logs"]},
    ).json()
    assert duplicate["skipped"] == 1

    cleared = client.delete("/api/runs").json()
    assert cleared["deleted"] == 1


@pytest.mark.asyncio
async def test_preset_import_export_replace_preserves_builtins(tmp_path):
    from texada.api import create_app

    client = TestClient(create_app(TeXadaConfig(data_dir=tmp_path)))
    client.post("/api/shorthands", json={"key": "old", "value": "x"})

    response = client.post(
        "/api/shorthands/import",
        json={
            "mode": "replace",
            "presets": {"new": "y", "euler": "must-not-overwrite"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"imported": 1, "skipped": 1, "cleared": 1}
    exported = client.get("/api/shorthands/export").json()
    assert exported["presets"] == {"new": "y"}
    all_presets = {item["key"]: item["value"] for item in client.get("/api/shorthands").json()}
    assert "old" not in all_presets
    assert all_presets["euler"] != "must-not-overwrite"
