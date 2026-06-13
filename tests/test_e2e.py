"""End-to-End integration tests for TeXada API server."""
import io
import pytest
import httpx
from PIL import Image

BASE_URL = "http://127.0.0.1:18732"


def _server_is_running() -> bool:
    """Check if the API server is accessible."""
    try:
        r = httpx.get(f"{BASE_URL}/api/status", timeout=2.0)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = pytest.mark.skipif(
    not _server_is_running(),
    reason="TeXada API server not running at {BASE_URL}",
)


@pytest.fixture
async def client():
    """Async HTTP client fixture with a generous timeout for local LLM inference."""
    async with httpx.AsyncClient(timeout=60.0) as cl:
        yield cl


@pytest.mark.asyncio
async def test_e2e_status(client):
    """Verify /api/status endpoint works and returns correct model configuration."""
    response = await client.get(f"{BASE_URL}/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["model"] == "openbmb/minicpm-v4.6"
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
async def test_e2e_convert_generic(client):
    """Verify /api/convert with generic math text."""
    payload = {
        "text": "x的平方加上y的平方",
        "render_mode": "katex"
    }
    response = await client.post(f"{BASE_URL}/api/convert", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "x^2" in data["latex"] or "x^{2}" in data["latex"]
    assert "y^2" in data["latex"] or "y^{2}" in data["latex"]


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
    assert data["intent"] == "ocr"
