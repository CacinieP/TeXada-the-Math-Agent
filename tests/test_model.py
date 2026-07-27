"""Model response extraction and request-local telemetry tests."""

from types import SimpleNamespace

import pytest

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
