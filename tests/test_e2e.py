"""End-to-End integration tests for TeXada API server."""
import io
import os

import httpx
import pytest
from PIL import Image

_API_HOST = os.getenv("TEXADA_API_HOST", "127.0.0.1")
_API_PORT = os.getenv("TEXADA_API_PORT", "18732")
BASE_URL = os.getenv("TEXADA_E2E_BASE_URL", f"http://{_API_HOST}:{_API_PORT}").rstrip("/")
RUN_E2E = os.getenv("TEXADA_RUN_E2E") == "1"


def _server_is_running() -> bool:
    """Check if the API server is accessible."""
    try:
        r = httpx.get(f"{BASE_URL}/api/status", timeout=2.0)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = pytest.mark.skipif(
    not RUN_E2E or not _server_is_running(),
    reason=f"Set TEXADA_RUN_E2E=1 with TeXada API server running at {BASE_URL}",
)


@pytest.fixture
async def client():
    """Async HTTP client fixture with a generous timeout for local LLM inference."""
    async with httpx.AsyncClient(timeout=180.0) as cl:
        yield cl


@pytest.mark.asyncio
async def test_e2e_status(client):
    """Verify /api/status endpoint works and returns correct model configuration."""
    response = await client.get(f"{BASE_URL}/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "minicpm" in data["model"].lower()  # text model tag (config.model_name)
    assert data["render_mode"] == "katex"


@pytest.mark.asyncio
async def test_e2e_convert(client):
    """Verify /api/convert endpoint translates text to LaTeX using the model."""
    payload = {
        "text": "f(x)从0到1的定积分",
        "render_mode": "katex"
    }
    response = await client.post(f"{BASE_URL}/api/convert", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "latex" in data
    assert "katex_html" in data
    assert data["valid"] is True
    assert data["intent"] == "integral"
    assert "<span class=\"katex\">" in data["katex_html"]


@pytest.mark.asyncio
async def test_e2e_agent_runtime_and_operator_guard(client):
    """Verify the primary planner/tool path preserves a SymbolEngine anchor."""
    payload = {
        "text": "二重积分 f(x,y) 在区域 D 上",
        "render_mode": "katex",
    }
    response = await client.post(f"{BASE_URL}/api/agent", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "agent"
    assert data["valid"] is True
    assert r"\iint" in data["latex"]
    assert data["semantic_document"]["parser_backend"] == "katex-0.17.0-v8"
    assert data["agent_trace"]
    assert data["agent_trace"][-1]["origin"] == "runtime_guard"
    assert data["stop_reason"]
    assert data["run_id"]

    run_response = await client.get(f"{BASE_URL}/api/runs/{data['run_id']}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["operation"] == "agent"
    assert run["model_role"] == "planner"
    assert run["tool_call_count"] >= 2
    assert run["trace"]


@pytest.mark.asyncio
async def test_e2e_convert_generic(client):
    """Smoke-test the stochastic legacy compatibility route."""
    payload = {
        "text": "x的平方加上y的平方",
        "render_mode": "katex"
    }
    response = await client.post(f"{BASE_URL}/api/convert", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Exact formula quality is covered on the primary /api/agent path above.
    # A 1B sampler can legitimately vary on this legacy route, so its E2E
    # contract is non-empty, syntactically valid, locally renderable LaTeX.
    assert data["latex"].strip()
    assert data["valid"] is True
    assert '<span class="katex">' in data["katex_html"]


@pytest.mark.asyncio
async def test_e2e_completion_uses_agent_runtime(client):
    """Completion candidate is reviewed by MiniCPM5 through the shared tools."""
    response = await client.post(
        f"{BASE_URL}/api/complete",
        json={"text": "\\sum_{i=1}^{", "render_mode": "katex"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "agent"
    assert data["intent"] == "completion_agent"
    assert data["agent_trace"]
    assert data["agent_trace"][0]["origin"] == "candidate_intake"
    assert data["agent_trace"][-1]["origin"] == "runtime_guard"
    run = (await client.get(f"{BASE_URL}/api/runs/{data['run_id']}")).json()
    assert run["operation"] == "completion"
    assert run["model_role"] == "planner"
    assert run["tool_call_count"] >= 2
    assert run["trace"]


@pytest.mark.asyncio
async def test_e2e_shorthands(client):
    """Verify shorthands listing, creation, and deletion workflow."""
    # 1. Add a shorthand
    shorthand_payload = {
        "key": "test_e2e_sh",
        "value": "\\gamma_i^2"
    }
    response = await client.post(f"{BASE_URL}/api/shorthands", json=shorthand_payload)
    assert response.status_code == 200

    # 2. List shorthands and check if present
    list_response = await client.get(f"{BASE_URL}/api/shorthands?q=test_e2e_sh")
    assert list_response.status_code == 200
    items = list_response.json()
    assert any(item["key"] == "test_e2e_sh" for item in items)

    # 3. Test convert routes through shorthand automatically
    convert_response = await client.post(
        f"{BASE_URL}/api/convert",
        json={"text": "test_e2e_sh"}
    )
    assert convert_response.status_code == 200
    convert_data = convert_response.json()
    assert convert_data["latex"] == "\\gamma_i^2"
    assert convert_data["source"] == "shorthand"

    # 4. Delete the shorthand
    delete_response = await client.delete(f"{BASE_URL}/api/shorthands/test_e2e_sh")
    assert delete_response.status_code == 200


@pytest.mark.asyncio
async def test_e2e_validate(client):
    """Verify /api/validate endpoint checks LaTeX syntax."""
    # Valid LaTeX
    response_val = await client.post(
        f"{BASE_URL}/api/validate",
        json={"latex": "\\frac{a}{b}"}
    )
    assert response_val.status_code == 200
    assert response_val.json()["valid"] is True

    # Invalid LaTeX (unbalanced braces)
    response_inval = await client.post(
        f"{BASE_URL}/api/validate",
        json={"latex": "\\frac{a}{b"}
    )
    assert response_inval.status_code == 200
    assert response_inval.json()["valid"] is False


@pytest.mark.asyncio
async def test_e2e_ocr(client):
    """Verify /api/ocr endpoint processes a generated image."""
    # Generate a simple 100x100 white PNG image programmatically
    img = Image.new('RGB', (100, 100), color='white')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_bytes = img_byte_arr.getvalue()

    files = {
        "image": ("test_e2e.png", img_bytes, "image/png")
    }
    response = await client.post(
        f"{BASE_URL}/api/ocr",
        files=files,
        params={"render_mode": "katex"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "latex" in data
    assert "katex_html" in data
    assert data["source"] == "agent"
    assert data["intent"] == "ocr_agent"
    assert data["agent_trace"]
    assert data["agent_trace"][0]["origin"] == "candidate_intake"
    assert data["agent_trace"][-1]["origin"] == "runtime_guard"
    run = (await client.get(f"{BASE_URL}/api/runs/{data['run_id']}")).json()
    assert run["operation"] == "ocr"
    assert run["model_role"] == "planner"
    assert "->" in run["model_name"]
    assert run["tool_call_count"] >= 2
    assert run["trace"]
