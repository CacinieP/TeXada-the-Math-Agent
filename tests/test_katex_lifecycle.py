"""Native KaTeX ownership and ASGI shutdown must share a serial boundary."""

import asyncio
import gc
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import pytest

from texada.semantic import katex


def instrument_context(monkeypatch, tmp_path, *, fail_call=False, fail_init=False):
    instances = []
    events = []

    class Context:
        def __init__(self):
            self.owner = threading.current_thread()
            self.closed = False
            self.number = len(instances)
            with pytest.raises(RuntimeError, match="no running event loop"):
                asyncio.get_running_loop()
            instances.append(self)
            self.record("create")

        def record(self, operation):
            assert threading.current_thread() is self.owner
            assert not self.closed
            events.append((self.number, operation))

        def set_soft_memory_limit(self, _value):
            self.record("soft_limit")

        def set_hard_memory_limit(self, _value):
            self.record("hard_limit")

        def eval(self, _source):
            self.record("eval")
            if fail_init:
                raise RuntimeError("bootstrap failure")

        def call(self, function, _latex):
            self.record(function)
            if fail_call and self.number == 0:
                raise RuntimeError("native call failure")
            return json.dumps({"ok": True, "ast": [], "html": "<span>x</span>"})

        def close(self):
            self.record("close")
            self.closed = True

    monkeypatch.setattr(katex, "MiniRacer", Context)
    source = tmp_path / "katex.js"
    source.write_text("// instrumented native context")
    return katex.KaTeXASTParser(source), instances, events


@pytest.mark.asyncio
async def test_complete_context_lifecycle_stays_on_plain_owner(monkeypatch, tmp_path):
    parser, instances, events = instrument_context(monkeypatch, tmp_path)
    try:
        # The first caller has a running loop; V8 must not capture that loop.
        assert parser.parse("x").ok
        with ThreadPoolExecutor(max_workers=1) as caller:
            assert caller.submit(parser.render, "x").result().ok
            caller.submit(parser.close).result()
        assert instances[0].closed
        assert parser._owner is None and parser._context is None
        assert [operation for _, operation in events] == [
            "create", "soft_limit", "hard_limit", "eval", "eval", "eval",
            "texadaParseKaTeX", "texadaRenderKaTeX", "close",
        ]
        # The same parser supports a later ASGI lifespan with a new owner.
        assert parser.render("x").ok
        assert len(instances) == 2
    finally:
        parser.close()
    assert all(context.closed for context in instances)


def test_close_finishes_before_concurrent_reopen(monkeypatch, tmp_path):
    parser, instances, events = instrument_context(monkeypatch, tmp_path)
    assert parser.parse("x").ok
    original_close = instances[0].close
    entered, release, parse_started = (threading.Event() for _ in range(3))

    def blocking_close():
        entered.set()
        assert release.wait(5)
        original_close()

    instances[0].close = blocking_close

    def parse_again():
        parse_started.set()
        return parser.parse("y")

    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            closing = callers.submit(parser.close)
            assert entered.wait(5)
            parsing = callers.submit(parse_again)
            assert parse_started.wait(5)
            try:
                with pytest.raises(TimeoutError):
                    parsing.result(timeout=0.05)
                assert len(instances) == 1
            finally:
                release.set()
            closing.result(timeout=5)
            assert parsing.result(timeout=5).ok
        assert events.index((0, "close")) < events.index((1, "create"))
    finally:
        release.set()
        parser.close()


def test_failure_rebuild_and_initialization_cleanup_keep_owner(monkeypatch, tmp_path):
    parser, instances, events = instrument_context(monkeypatch, tmp_path, fail_call=True)
    try:
        assert not parser.parse("x").ok
        assert instances[0].closed
        assert parser.render("y").ok
        assert instances[0].owner is instances[1].owner
        assert events.index((0, "close")) < events.index((1, "create"))
    finally:
        parser.close()
    broken, instances, _ = instrument_context(monkeypatch, tmp_path, fail_init=True)
    try:
        assert "bootstrap failure" in broken.parse("x").error
        assert instances[0].closed and broken._context is None
    finally:
        broken.close()


def test_unshared_parser_collection_releases_context_and_thread(monkeypatch, tmp_path):
    parser, instances, _ = instrument_context(monkeypatch, tmp_path)
    assert parser.parse("x").ok
    owner = parser._owner
    del parser
    gc.collect()
    owner.join(timeout=5)
    assert instances[0].closed and not owner.is_alive()


@pytest.mark.parametrize("exception,argument", [
    (KeyboardInterrupt, "interrupted native call"),
    (SystemExit, 37),
    (GeneratorExit, "interrupted generator"),
])
def test_owner_survives_base_exception_and_can_release_native_context(
    monkeypatch, tmp_path, exception, argument,
):
    parser, instances, _ = instrument_context(monkeypatch, tmp_path)
    assert parser.parse("x").ok

    def interrupted(*_args):
        raise exception(argument)

    instances[0].call = interrupted
    try:
        with pytest.raises(exception) as caught:
            parser.render("y")
        if exception is SystemExit:
            assert caught.value.code == argument
        else:
            assert str(caught.value) == argument
        assert instances[0].closed
        assert parser._owner.is_alive()
        assert parser.parse("z").ok
    finally:
        parser.close()


def test_constructor_internal_failure_releases_native_context_before_caller_gc():
    # MiniRacer.__init__ allocates native V8, then evaluates its own bootstrap.
    # That constructor frame must not travel to the caller in a Future error.
    program = r'''
import gc
import threading
from py_mini_racer import MiniRacer
from texada.semantic.katex import KaTeXASTParser

created, closed = [], []
real_init, real_close, real_eval = MiniRacer.__init__, MiniRacer.close, MiniRacer.eval
def record_init(self, *args, **kwargs):
    created.append((id(self), threading.current_thread()))
    return real_init(self, *args, **kwargs)
def record_close(self, *args, **kwargs):
    if getattr(self, "_own_context_maker", None) is not None:
        closed.append((id(self), threading.current_thread()))
    return real_close(self, *args, **kwargs)
def fail_bootstrap(self, *args, **kwargs):
    try:
        raise ValueError("original bootstrap failure")
    except ValueError as cause:
        raise RuntimeError("constructor bootstrap failure") from cause

MiniRacer.__init__, MiniRacer.close, MiniRacer.eval = record_init, record_close, fail_bootstrap
parser = KaTeXASTParser()
try:
    result = parser.parse("x")
    assert not result.ok and "constructor bootstrap failure" in result.error
    assert len(created) == len(closed) == 1, (created, closed)
    assert created == closed, "partial constructor was not released by its owner"
    assert created[0][1] is not threading.current_thread()
    gc.collect()
    assert created == closed, "caller GC must not trigger another native release"
    MiniRacer.eval = real_eval
    assert parser.parse("x+1").ok
finally:
    parser.close()
    MiniRacer.__init__, MiniRacer.close, MiniRacer.eval = real_init, real_close, real_eval
assert created == closed and len(closed) == 2
print("constructor failure and chained traceback released on owner before caller GC")
'''
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "released on owner before caller GC" in result.stdout
    assert not result.stderr


def test_cli_natural_exit_closes_shared_native_owner():
    program = r'''
import asyncio
from texada.semantic.katex import shared_katex_parser
async def main():
    parser = shared_katex_parser()
    assert parser.parse(r"\frac{x}{2}").ok
    assert parser.render("x+1").ok
asyncio.run(main())
print("natural exit without manual close")
'''
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "natural exit without manual close" in result.stdout
    assert not result.stderr


def test_native_context_survives_repeated_asgi_shutdown_in_subprocess(tmp_path):
    # A native regression must fail with a useful exit code/trace instead of
    # taking the entire pytest worker down. This exercises real V8 and KaTeX.
    program = r'''
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from uuid import uuid4
from fastapi.testclient import TestClient
from texada.api import create_app
from texada.config import TeXadaConfig
from texada.handoff import text_digest
from texada.semantic.katex import shared_katex_parser

parser = shared_katex_parser()
async def render_from_ephemeral_loop():
    assert parser.render(r"\frac{x}{2}").ok
for iteration in range(20):
    assert parser.parse("x+1").ok
    asyncio.run(render_from_ephemeral_loop())
    config = TeXadaConfig(data_dir=Path(sys.argv[1])/str(iteration),
        backend="openai_compatible", openai_base_url="http://127.0.0.1:1/v1",
        openai_api_key="inert-no-provider", openai_model_name="MiniCPM-V-4.7-1B",
        openai_vision_model_name="MiniCPM-V-4.7-1B")
    original = r"\frac{x}{2"
    envelope = {"schema_version": 1, "transfer_id": str(uuid4()),
        "document_sha256": text_digest("$"+original+"$"),
        "input_sha256": text_digest(original),
        "source_range": {"start":1, "end":1+len(original), "encoding":"unicode-codepoints"},
        "formula_id":"lifecycle", "expected_revision":1, "original_latex":original,
        "requested_action":"repair", "allowed_scope":"syntax_repair",
        "checkpoint":"MiniCPM-V-4.7-1B", "requires_review":True, "evidence":[],
        "budget":{"max_steps":3, "max_seconds":30, "max_tokens":256}}
    with ThreadPoolExecutor(max_workers=3) as callers:
        with TestClient(create_app(config)) as client:
            response = client.post("/api/handoff/formula", json=envelope)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["candidate"] == original+"}"
            assert body["review"]["checks"]["compile"]["status"] == "valid"
            assert body["inference_fingerprint"]["calls"] == []
            tasks = [callers.submit(parser.render, "y+1") for _ in range(6)]
        assert all(task.result().ok for task in tasks)
    parser.close()
    assert parser._owner is None and parser._context is None
assert parser.parse("z+1").ok
parser.close()
print("20 real ASGI/V8 lifecycle cycles passed")
'''
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("TEXADA_")}
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", program, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "20 real ASGI/V8 lifecycle cycles passed" in result.stdout
