"""Model response extraction and request-local telemetry tests."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError, OpenAI

from texada.config import TeXadaConfig
from texada.core.model import MiniCPMModel


def _legacy_config(tmp_path):
    return TeXadaConfig(
        data_dir=tmp_path, backend="ollama", model_name="MiniCPM5-2B",
        vision_model_name="MiniCPM-V-4.6",
    )


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
    model = MiniCPMModel(_legacy_config(tmp_path))
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
    assert "timeout" not in seen
    assert model.consume_tokens_used() == 37
    assert model.consume_tokens_used() == 0


@pytest.mark.asyncio
async def test_model_completion_reports_tokens_but_rule_completion_uses_zero(
    monkeypatch,
    tmp_path,
):
    model = MiniCPMModel(_legacy_config(tmp_path))
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
    model = MiniCPMModel(_legacy_config(tmp_path))
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
    model = MiniCPMModel(_legacy_config(tmp_path))
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
    model = MiniCPMModel(_legacy_config(tmp_path))
    monkeypatch.setattr(
        model,
        "_completion_create",
        lambda **kwargs: _response("", 3),
    )

    with pytest.raises(RuntimeError, match="裁剪到单个公式"):
        await model.ocr_latex(b"image")


def _mock_api_model(tmp_path, *, backend="ollama", name="hf.co/openbmb/MiniCPM5-2B-GGUF:Q4_K_M",
                    responses=None, on_request=None):
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
        if on_request:
            on_request(request)
        status, content = next(scripted) if scripted else (200, r"\sin^2 x+\cos^2 x")
        if status != 200:
            error = content if isinstance(content, dict) else {"error": {"message": content}}
            return httpx.Response(status, json=error)
        message = content if isinstance(content, dict) else {
            "role": "assistant", "content": content,
        }
        return httpx.Response(200, json={
            "id": "mock-completion", "object": "chat.completion", "created": 0,
            "model": name,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": message}],
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


@pytest.mark.asyncio
@pytest.mark.parametrize(("backend", "name"), [
    ("openai_compatible", "MiniCPM-V-4.7-1B"),
    ("openai_compatible", "minicpm-v-4.7-1b-q4_k_m"),
    ("ollama", "hf.co/openbmb/MiniCPM-V-4_7-1B-GGUF:Q4_K_M"),
    ("ollama", "custom/MINICPM-V4.7-1B:q4_k_m"),
])
async def test_v47_single_checkpoint_disables_thinking_for_every_inference_role(
    tmp_path, backend, name,
):
    model, requests = _mock_api_model(tmp_path, backend=backend, name=name)
    try:
        await model.plan([{"role": "user", "content": "write a formula"}], [])
        await model.generate_latex("write a formula", "generic")
        await model.complete_latex(r"\sin^2 x+\cos^2")
        await model.ocr_latex(b"fake-image-for-mock-http")
    finally:
        model.client.close()

    assert len(requests) == 4
    assert [request["model"] for request in requests] == [name] * 4
    if backend == "ollama":
        assert [request["reasoning_effort"] for request in requests] == ["none"] * 4
        assert all("chat_template_kwargs" not in request for request in requests)
    else:
        assert all(request["chat_template_kwargs"] == {"enable_thinking": False}
                   for request in requests)
        assert all("reasoning_effort" not in request for request in requests)
    assert [request["max_tokens"] for request in requests] == [2048, 768, 768, 512]
    assert requests[0]["tool_choice"] == "auto"
    assert requests[3]["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,",
    )


@pytest.mark.asyncio
async def test_v47_planner_preserves_native_tool_calls_and_tool_retry_options(tmp_path):
    tool = {"type": "function", "function": {"name": "compile_tex",
            "parameters": {"type": "object", "properties": {"latex": {"type": "string"}}}}}
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[
            (200, {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_compile", "type": "function", "function": {
                    "name": "compile_tex", "arguments": '{"latex": "x^2"}',
                },
            }]}),
            (400, "tools unsupported"),
            (200, "x^2"),
        ],
    )
    try:
        native = await model.plan([{"role": "user", "content": "square x"}], [tool])
        fallback = await model.plan([{"role": "user", "content": "square x"}], [tool])
    finally:
        model.client.close()

    assert len(native.tool_calls) == 1
    assert native.tool_calls[0].name == "compile_tex"
    assert native.tool_calls[0].arguments == {"latex": "x^2"}
    assert fallback.content == "x^2"
    assert len(requests) == 3
    assert requests[0]["tools"] == requests[1]["tools"] == [tool]
    assert "tools" not in requests[2]
    assert "tool_choice" not in requests[2]
    assert all(request["chat_template_kwargs"] == {"enable_thinking": False}
               for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["generate", "ocr"])
async def test_v47_retries_hidden_reasoning_instead_of_accepting_it_as_final_output(
    tmp_path, role,
):
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[
            (200, {"role": "assistant", "content": "", "reasoning": "x^3",
                   "reasoning_content": "x^4"}),
            (200, "x^2"),
        ],
    )
    try:
        if role == "generate":
            result = await model.generate_latex("square x", "generic")
        else:
            result = await model.ocr_latex(b"fake-image-for-mock-http")
    finally:
        model.client.close()

    assert result == "x^2"
    assert len(requests) == 2
    assert all(request["chat_template_kwargs"] == {"enable_thinking": False}
               for request in requests)
    assert all("reasoning_effort" not in request for request in requests)
    assert model.consume_tokens_used() == 20


@pytest.mark.asyncio
async def test_v47_completion_ignores_hidden_reasoning(tmp_path):
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(200, {"role": "assistant", "content": "", "reasoning": "x^3"})],
    )
    try:
        result = await model.complete_latex(r"x+\unknown")
    finally:
        model.client.close()

    assert result == ""
    assert len(requests) == 1
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_v47_ocr_hidden_reasoning_cannot_bypass_empty_retry_error(tmp_path):
    hidden = {"role": "assistant", "content": "", "reasoning": "x^3",
              "reasoning_content": "x^4"}
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(200, hidden), (200, hidden)],
    )
    try:
        with pytest.raises(RuntimeError, match="裁剪到单个公式"):
            await model.ocr_latex(b"fake-image-for-mock-http")
    finally:
        model.client.close()

    assert len(requests) == 2
    assert model.consume_tokens_used() == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["MiniCPM-V-4.6", "MiniCPM-V-4.7-8B", "other-model"])
async def test_other_checkpoints_do_not_receive_v47_template_options(tmp_path, name):
    model, requests = _mock_api_model(tmp_path, backend="openai_compatible", name=name)
    try:
        await model.generate_latex("write a formula", "generic")
        await model.ocr_latex(b"fake-image-for-mock-http")
    finally:
        model.client.close()

    assert len(requests) == 2
    assert all("chat_template_kwargs" not in request for request in requests)
    assert "reasoning_effort" not in requests[0]
    assert requests[1]["reasoning_effort"] == "low"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["generate", "complete", "ocr", "planner"])
async def test_v47_final_formula_wins_over_math_in_visible_thinking_blocks(tmp_path, role):
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(200, "<think>$x^3$</think>\n$x^2$")],
    )
    try:
        if role == "generate":
            result = await model.generate_latex("square x", "generic")
        elif role == "complete":
            result = await model.complete_latex(r"x+\unknown")
        elif role == "ocr":
            result = await model.ocr_latex(b"fake-image-for-mock-http")
        else:
            turn = await model.plan([{"role": "user", "content": "square x"}], [])
            result = model.extract_latex(turn.content)
        assert model.extract_latex("<think>$x^3$</think>\n$x^2$") == "x^2"
    finally:
        model.client.close()

    assert result == "x^2"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["generate", "ocr"])
@pytest.mark.parametrize("content", ["<think>$x^3$</think>", "<think>$x^3$"])
async def test_v47_thinking_only_content_retries_and_accepts_only_visible_final_math(
    tmp_path, role, content,
):
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(200, content), (200, "<think>$x^4$</think>\n$x^2$")],
    )
    try:
        if role == "generate":
            result = await model.generate_latex("square x", "generic")
        else:
            result = await model.ocr_latex(b"fake-image-for-mock-http")
    finally:
        model.client.close()

    assert result == "x^2"
    assert len(requests) == 2
    assert all(request["chat_template_kwargs"] == {"enable_thinking": False}
               for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["generate", "complete", "ocr", "planner"])
async def test_v47_unclosed_thinking_content_cannot_become_a_final_formula(tmp_path, role):
    content = "<think>$x^3$"
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(200, content), (200, content)],
    )
    try:
        if role == "generate":
            assert await model.generate_latex("square x", "generic") == ""
        elif role == "complete":
            assert await model.complete_latex(r"x+\unknown") == ""
        elif role == "ocr":
            with pytest.raises(RuntimeError, match="裁剪到单个公式"):
                await model.ocr_latex(b"fake-image-for-mock-http")
        else:
            turn = await model.plan([{"role": "user", "content": "square x"}], [])
            assert model.extract_latex(turn.content) == ""
        assert model.extract_latex(content) == ""
    finally:
        model.client.close()

    assert len(requests) == (2 if role in {"generate", "ocr"} else 1)


def test_legacy_extractor_keeps_its_existing_thinking_tag_behavior(tmp_path):
    model = MiniCPMModel(_legacy_config(tmp_path))
    assert model.extract_latex("<think>$x^3$</think>\n$x^2$") == "x^3"


@pytest.mark.asyncio
async def test_generation_retry_timeout_uses_the_original_remaining_budget(monkeypatch, tmp_path):
    clock = [0.0]
    timeouts = []
    monkeypatch.setattr("texada.core.model.time", SimpleNamespace(monotonic=lambda: clock[0]))

    def observe_request(request):
        timeouts.append(dict(request.extensions["timeout"]))
        # The first request consumes 80 of the original 120 seconds.
        clock[0] = 80.0 if len(timeouts) == 1 else 120.0

    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(200, ""), (200, "x^2")], on_request=observe_request,
    )
    try:
        result = await model.generate_latex("square x", "generic", deadline_monotonic=120.0)
    finally:
        model.client.close()

    assert result == "x^2"
    assert len(requests) == 2
    assert timeouts == [
        {"connect": 90.0, "read": 90.0, "write": 90.0, "pool": 90.0},
        {"connect": 40.0, "read": 40.0, "write": 40.0, "pool": 40.0},
    ]
    assert all("timeout" not in request for request in requests)
    assert all(request["chat_template_kwargs"] == {"enable_thinking": False}
               for request in requests)
    assert model.consume_tokens_used() == 20


@pytest.mark.asyncio
async def test_generation_expired_initial_deadline_makes_no_provider_request(monkeypatch, tmp_path):
    monkeypatch.setattr("texada.core.model.time", SimpleNamespace(monotonic=lambda: 120.0))
    model, requests = _mock_api_model(tmp_path, name="MiniCPM-V-4.7-1B")
    try:
        with pytest.raises(TimeoutError, match="预算已耗尽"):
            await model.generate_latex("square x", "generic", deadline_monotonic=120.0)
    finally:
        model.client.close()

    assert requests == []
    assert model.consume_tokens_used() == 0


@pytest.mark.asyncio
async def test_generation_exhausted_deadline_propagates_before_internal_retry(
    monkeypatch, tmp_path,
):
    clock = [0.0]
    monkeypatch.setattr("texada.core.model.time", SimpleNamespace(monotonic=lambda: clock[0]))

    def exhaust_budget(request):
        clock[0] = 120.0

    model, requests = _mock_api_model(
        tmp_path, name="MiniCPM-V-4.7-1B", responses=[(200, "")], on_request=exhaust_budget,
    )
    try:
        with pytest.raises(TimeoutError, match="预算已耗尽"):
            await model.generate_latex("square x", "generic", deadline_monotonic=120.0)
    finally:
        model.client.close()

    assert len(requests) == 1
    assert model.consume_tokens_used() == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"error": {"message": "Request rejected by provider", "code": "content_policy_violation"}},
    {"message": "Request rejected by provider", "code": "content_policy_violation"},
])
async def test_planner_provider_policy_rejection_does_not_retry_without_tools(tmp_path, body):
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[(400, body), (200, "x^2")],
    )
    tools = [{"type": "function", "function": {"name": "compile_tex",
              "parameters": {"type": "object", "properties": {}}}}]
    try:
        with pytest.raises(BadRequestError):
            await model.plan([{"role": "user", "content": "square x"}], tools)
    finally:
        model.client.close()

    assert len(requests) == 1
    assert requests[0]["tools"] == tools


@pytest.mark.asyncio
async def test_planner_unsupported_tools_error_keeps_the_compatibility_retry(tmp_path):
    model, requests = _mock_api_model(
        tmp_path, backend="openai_compatible", name="MiniCPM-V-4.7-1B",
        responses=[
            (400, {"error": {"message": "tools unsupported", "code": "unsupported_parameter",
                             "param": "tools"}}),
            (200, "x^2"),
        ],
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
