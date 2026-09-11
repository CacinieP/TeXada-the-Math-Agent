"""Model response extraction and request-local telemetry tests."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from texada.config import TeXadaConfig
from texada.core.model import MiniCPMModel


def _response(
    content: str,
    tokens: int,
    *,
    reasoning: str | None = None,
    reasoning_content: str | None = None,
):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    reasoning=reasoning,
                    reasoning_content=reasoning_content,
                ),
            )
        ],
        usage=SimpleNamespace(total_tokens=tokens),
    )


@pytest.mark.asyncio
async def test_text_generation_reports_provider_token_usage(monkeypatch, tmp_path):
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path))
    seen = {}

    def completion(**kwargs):
        seen.update(kwargs)
        return _response("x^2", 37)

    monkeypatch.setattr(
        model,
        "_completion_create",
        completion,
    )

    assert await model.generate_latex("x squared", "generic") == "x^2"
    assert seen["max_tokens"] == 768
    assert model.consume_tokens_used() == 37
    assert model.consume_tokens_used() == 0


@pytest.mark.asyncio
async def test_model_completion_reports_tokens_but_rule_completion_uses_zero(
    monkeypatch,
    tmp_path,
):
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path))
    monkeypatch.setattr(
        model,
        "_completion_create",
        lambda **kwargs: _response(r"x+\alpha", 19),
    )

    assert await model.complete_latex("x+\\unknown") == r"x+\alpha"
    assert model.consume_tokens_used() == 19
    assert await model.complete_latex("x+\\alp") == r"x+\alpha"
    assert model.consume_tokens_used() == 0
    assert await model.complete_latex(r"\sqrt{") == r"\sqrt{\placeholder{}}"
    assert model.consume_tokens_used() == 0


@pytest.mark.asyncio
async def test_ocr_uses_reasoning_field_before_retry(monkeypatch, tmp_path):
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path))
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return _response(
            "",
            23,
            reasoning=r"最终结果：$$\frac{a}{b}$$",
        )

    monkeypatch.setattr(model, "_completion_create", completion)

    assert await model.ocr_latex(b"image") == r"\frac{a}{b}"
    assert len(calls) == 1
    assert model.consume_tokens_used() == 23


@pytest.mark.asyncio
async def test_ocr_retries_empty_response_once(monkeypatch, tmp_path):
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path))
    responses = iter(
        [
            _response("", 11),
            _response(r"$$x^2+y^2$$", 17),
        ]
    )
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(model, "_completion_create", completion)

    assert await model.ocr_latex(b"image") == "x^2+y^2"
    assert len(calls) == 2
    assert calls[1]["temperature"] == 0.0
    assert "单条主体公式" in calls[1]["messages"][0]["content"]
    assert model.consume_tokens_used() == 28


@pytest.mark.asyncio
async def test_ocr_empty_retry_returns_actionable_error(monkeypatch, tmp_path):
    model = MiniCPMModel(TeXadaConfig(data_dir=tmp_path))
    monkeypatch.setattr(
        model,
        "_completion_create",
        lambda **kwargs: _response("", 3),
    )

    with pytest.raises(RuntimeError, match="裁剪到单个公式"):
        await model.ocr_latex(b"image")


def _mock_api_model(tmp_path, *, backend="ollama", name="hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M",
                    responses=None):
    """Exercise OpenAI request serialization without any network inference."""
    config = TeXadaConfig(
        data_dir=tmp_path, backend=backend, model_name=name,
        openai_model_name=name, vision_model_name=name, openai_vision_model_name=name,
        temperature=0.1, max_tokens=2048,
    )
    model = MiniCPMModel(config)
    requests = []
    scripted = iter(responses) if responses is not None else None

    def respond(request):
        requests.append(json.loads(request.content))
        status, content = next(scripted) if scripted else (200, r"\sin^2 x+\cos^2 x")
        if status != 200:
            return httpx.Response(status, json={"error": {"message": content}})
        return httpx.Response(200, json={
            "id": "mock-completion", "object": "chat.completion", "created": 0,
            "model": name,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        })

    model._client = OpenAI(
        base_url="http://texada.test/v1", api_key="test", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
    )
    return model, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    "hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M",
    "custom/MINICPM5-2B:q4_k_m",
])
async def test_local_2b_text_requests_disable_reasoning_and_keep_token_limits(tmp_path, name):
    model, requests = _mock_api_model(tmp_path, name=name)
    try:
        await model.plan([{"role": "user", "content": "write a formula"}], [])
        await model.generate_latex("write a formula", "generic")
        await model.complete_latex(r"\sin^2 x+\cos^2")
    finally:
        model.client.close()

    assert len(requests) == 3
    assert [request["reasoning_effort"] for request in requests] == ["none"] * 3
    assert [request["max_tokens"] for request in requests] == [2048, 768, 768]
    assert requests[0]["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_local_2b_tool_rejection_retry_keeps_reasoning_disabled(tmp_path):
    model, requests = _mock_api_model(
        tmp_path, responses=[(400, "tools unsupported"), (200, "x^2")],
    )
    tools = [{"type": "function", "function": {"name": "compile_tex",
              "parameters": {"type": "object", "properties": {}}}}]
    try:
        result = await model.plan([{"role": "user", "content": "square x"}], tools)
    finally:
        model.client.close()

    assert result.content == "x^2"
    assert len(requests) == 2
    assert requests[0]["tools"] == tools
    assert "tools" not in requests[1]
    assert "tool_choice" not in requests[1]
    assert [request["reasoning_effort"] for request in requests] == ["none", "none"]


@pytest.mark.asyncio
async def test_local_2b_generation_retry_keeps_reasoning_disabled(tmp_path):
    model, requests = _mock_api_model(tmp_path, responses=[(200, ""), (200, "x^2")])
    try:
        result = await model.generate_latex("square x", "generic")
    finally:
        model.client.close()

    assert result == "x^2"
    assert len(requests) == 2
    assert [request["reasoning_effort"] for request in requests] == ["none", "none"]
    assert [request["max_tokens"] for request in requests] == [768, 768]


@pytest.mark.asyncio
@pytest.mark.parametrize(("backend", "name"), [
    ("ollama", "hf.co/openbmb/MiniCPM5-1B-GGUF:Q4_K_M"),
    ("ollama", "another-text-model:latest"),
    ("openai_compatible", "hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M"),
])
async def test_other_text_models_and_openai_endpoints_keep_reasoning_defaults(
    tmp_path, backend, name,
):
    model, requests = _mock_api_model(tmp_path, backend=backend, name=name)
    try:
        await model.plan([{"role": "user", "content": "write a formula"}], [])
        await model.generate_latex("write a formula", "generic")
        await model.complete_latex(r"\sin^2 x+\cos^2")
    finally:
        model.client.close()

    assert len(requests) == 3
    assert all("reasoning_effort" not in request for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["ollama", "openai_compatible"])
async def test_ocr_requests_and_retry_keep_their_existing_reasoning_options(tmp_path, backend):
    # Even a shared model name must not apply text-only options to the OCR role.
    model, requests = _mock_api_model(
        tmp_path, backend=backend, responses=[(200, ""), (200, "x^2")],
    )
    try:
        result = await model.ocr_latex(b"fake-image-for-mock-http")
    finally:
        model.client.close()

    assert result == "x^2"
    assert len(requests) == 2
    assert [request["max_tokens"] for request in requests] == [512, 768]
    if backend == "ollama":
        assert all("reasoning_effort" not in request for request in requests)
    else:
        assert [request["reasoning_effort"] for request in requests] == ["low", "low"]
