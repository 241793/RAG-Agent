"""工作流引擎单测：拓扑排序、变量解析、条件分支跳过。"""
from __future__ import annotations

import pytest

from app.agents.workflow.engine import (
    _eval_expr,
    render,
    topo_sort,
    validate_graph,
)
from app.core.errors import ValidationError


def test_topo_sort_linear():
    g = {
        "nodes": [{"id": "a", "type": "start"}, {"id": "b", "type": "llm"}, {"id": "c", "type": "end"}],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
    }
    assert topo_sort(g) == ["a", "b", "c"]


def test_topo_sort_cycle_raises():
    g = {
        "nodes": [{"id": "a", "type": "start"}, {"id": "b", "type": "llm"}, {"id": "c", "type": "end"}],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}, {"source": "c", "target": "b"}],
    }
    with pytest.raises(ValidationError):
        topo_sort(g)


def test_validate_requires_single_start_and_end():
    with pytest.raises(ValidationError):
        validate_graph({"nodes": [{"id": "a", "type": "llm"}], "edges": []})
    with pytest.raises(ValidationError):
        validate_graph({"nodes": [{"id": "a", "type": "start"}], "edges": []})  # 无 end


def test_render_single_ref_returns_raw():
    ctx = {"n1": {"output": {"a": 1}}}
    assert render("{{n1.output}}", ctx) == {"a": 1}
    assert render("{{n1.output.a}}", ctx) == 1


def test_render_mixed_string():
    ctx = {"n1": {"output": "你好"}}
    assert render("结果：{{n1.output}}！", ctx) == "结果：你好！"


def test_eval_expr_operators():
    assert _eval_expr("5 > 3") is True
    assert _eval_expr("'abc' == 'abc'") is True
    assert _eval_expr("'hello' contains 'ell'") is True
    assert _eval_expr("2 >= 3") is False


def test_eval_expr_contains_chinese():
    assert _eval_expr("这段文字 contains '无法回答'") is False
    assert _eval_expr("我无法回答 contains '无法回答'") is True
