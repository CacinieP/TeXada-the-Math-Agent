"""Run log persistence, filtering, correlation, and backup tests."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from texada.agent.runtime import AgentRunResult, TeXadaAgentRuntime
from texada.config import TeXadaConfig
from texada.render.engine import RenderEngine
from texada.store.history import HistoryStore
from texada.store.run_log import RunLogStore
from texada.types import RenderMode, RunLogEntry


@pytest.mark.asyncio
async def test_run_log_store_round_trip_filters_and_deduplicates(tmp_path):
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
    )

    assert await store.add(entry) == "run-1"
    loaded = await store.get("run-1")
    assert loaded is not None
    assert loaded.tool_names == ["parse_tex", "render_math"]
    assert loaded.trace[0]["step"] == 1

    assert [item.run_id for item in await store.list_recent("MiniCPM")] == ["run-1"]
    assert await store.list_recent(status="error") == []
    assert [item.run_id for item in await store.list_recent(operation="agent")] == ["run-1"]
    summary = (await store.list_recent(include_trace=False))[0]
    assert summary.trace == []
    assert summary.trace_available is True

    imported = await store.import_entries([entry])
    assert imported == {"imported": 0, "skipped": 1, "cleared": 0}


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
