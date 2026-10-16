"""Product boundary: preserve notation, reject explicit computation before inference."""
from unittest.mock import AsyncMock

import httpx
import pytest

from texada.agent.runtime import TeXadaAgentRuntime
from texada.api import create_app
from texada.config import TeXadaConfig
from texada.core.router import InputRouter
from texada.core.scope import ComputationOutsideScope, requests_computation


@pytest.mark.parametrize('text', [
    '计算 7+5', '请化简 (x+1)^2', '帮我因式分解 x^2-1', '求解 x+2=0',
    '请对 x^2 求导', '求 x^2 的积分', '证明勾股定理',
    '排版 x^2，然后计算 x=2 时的值', '不用计算，但请证明这个等式',
    'Calculate 7+5', 'Please solve x+2=0', 'Can you differentiate x^2?',
    'Typeset x+1 and evaluate it at x=2', 'Integrate x^2', 'Compute 7+5',
])
def test_explicit_computation_is_outside_scope(text):
    assert requests_computation(text)


@pytest.mark.parametrize('text', [
    '输入 7+5', 'x^2+1', r'\int_0^1 x^2\,dx',
    '输入 f(x) 的导数记号', '二重积分 f(x,y) 在 D 上',
    '求导符号', '把“计算”写成文本标签',
    '不用计算，只排版 7+5', '不要化简，保留 (x+1)^2',
    'Describe the derivative notation for f(x)', 'Typeset 7+5',
    'Do not calculate; typeset 7+5', 'Without solving, transcribe x+2=0',
    'Enter the label `calculate`', r'\text{calculate}',
])
def test_notation_and_negated_computation_remain_supported(text):
    assert not requests_computation(text)


@pytest.mark.asyncio
async def test_all_text_entry_points_reject_without_model_readiness(tmp_path):
    config = TeXadaConfig(data_dir=tmp_path)
    engine = TeXadaAgentRuntime(config)
    router = InputRouter(config)
    engine.backend.ensure_ready = AsyncMock(side_effect=AssertionError('inference forbidden'))
    router.backend.ensure_ready = AsyncMock(side_effect=AssertionError('inference forbidden'))
    for call in (engine.run, router.process_text, router.create_completion_candidate):
        with pytest.raises(ComputationOutsideScope):
            await call('计算 7+5')
    engine.backend.ensure_ready.assert_not_awaited()
    router.backend.ensure_ready.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/api/agent', '/api/convert', '/api/complete'])
async def test_api_rejects_computation_as_product_boundary_not_server_failure(tmp_path, path):
    app = create_app(TeXadaConfig(data_dir=tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        response = await client.post(path, json={'text': '计算 7+5'})
    assert response.status_code == 422
    assert '仅支持公式识别、转写和排版' in response.json()['detail']


def test_matrix_completion_marks_unknown_cell_without_inventing_a_value():
    from texada.core.completion import DeterministicCompletionEngine
    partial = r'\begin{pmatrix}1 & 2 \\ 3 &'
    result = DeterministicCompletionEngine().complete(partial)
    assert result.latex == partial + r'\placeholder{}'
