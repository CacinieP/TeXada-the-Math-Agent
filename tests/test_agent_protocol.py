"""MiniCPM5 native XML tool-call compatibility tests."""
import json
from types import SimpleNamespace

from texada.agent.protocol import MiniCPMToolCallParser


def test_parse_official_minicpm5_xml_with_cdata_and_multiple_calls():
    raw = (
        "<think>check structure first</think>"
        '<function name="compile_tex">'
        '<param name="latex"><![CDATA[\\frac{a}{b}]]></param>'
        "</function><tool_sep>"
        '<function name="export">'
        '<param name="latex"><![CDATA[\\frac{a}{b}]]></param>'
        '<param name="format">"markdown"</param>'
        "</function>"
    )

    calls, content, reasoning = MiniCPMToolCallParser().parse_xml(raw)

    assert [call.name for call in calls] == ["compile_tex", "export"]
    assert calls[0].arguments["latex"] == r"\frac{a}{b}"
    assert calls[1].arguments["format"] == "markdown"
    assert content == ""
    assert reasoning == "check structure first"


def test_native_openai_tool_call_takes_precedence():
    function = SimpleNamespace(
        name="parse_tex",
        arguments=json.dumps({"latex": r"\int_0^1 x\,dx"}),
    )
    message = SimpleNamespace(
        content="",
        reasoning_content="plan",
        tool_calls=[SimpleNamespace(id="call_1", function=function)],
    )

    turn = MiniCPMToolCallParser().parse_message(message, tokens_used=12)

    assert turn.tool_calls[0].id == "call_1"
    assert turn.tool_calls[0].arguments["latex"] == r"\int_0^1 x\,dx"
    assert turn.reasoning == "plan"
    assert turn.tokens_used == 12
