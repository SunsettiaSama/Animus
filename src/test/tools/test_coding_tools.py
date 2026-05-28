"""agent.flow.coding.tools 的单元测试�?""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from agent.flow.coding import CodingToolSuite, CodeNodeExecutor, CodingConfig
from agent.flow.coding.executor import (
    _parse_tool_call,
    _parse_final_answer,
)
from agent.flow.coding.tools import ToolSpec


# ── CodingToolSuite 单元测试 ──────────────────────────────────────────────────

def test_suite_default_tools():
    suite = CodingToolSuite()
    names = suite.available_names()
    assert "read_file" in names
    assert "write_file" in names
    assert "run_python" in names
    assert "list_dir" in names
    assert "append_file" in names


def test_suite_disable():
    suite = CodingToolSuite()
    suite.disable("append_file", "run_python")
    assert "append_file" not in suite.available_names()
    assert "run_python" not in suite.available_names()
    assert "read_file" in suite.available_names()


def test_suite_register_custom():
    suite = CodingToolSuite()
    suite.register(
        "greet",
        lambda name="world": f"Hello, {name}!",
        ToolSpec("greet", "Says hello.", "name: str = 'world'"),
    )
    assert "greet" in suite.available_names()
    assert suite.call("greet", name="pytest") == "Hello, pytest!"


def test_suite_unknown_tool_returns_error():
    suite = CodingToolSuite()
    result = suite.call("nonexistent_tool")
    assert "未知工具" in result


def test_suite_render_tool_list():
    suite = CodingToolSuite()
    rendered = suite.render_tool_list()
    assert "read_file" in rendered
    assert "run_python" in rendered


# ── 内置工具功能测试 ──────────────────────────────────────────────────────────

def test_write_and_read_file():
    suite = CodingToolSuite()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "test.py")
        write_msg = suite.call("write_file", path=path, content="x = 1\n")
        assert "已写�? in write_msg
        content = suite.call("read_file", path=path)
        assert "x = 1" in content


def test_read_file_not_found():
    suite = CodingToolSuite()
    result = suite.call("read_file", path="/nonexistent/path/x.py")
    assert "不存�? in result


def test_append_file():
    suite = CodingToolSuite()
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "log.txt")
        suite.call("write_file", path=path, content="line1\n")
        suite.call("append_file", path=path, content="line2\n")
        content = suite.call("read_file", path=path)
        assert "line1" in content and "line2" in content


def test_list_dir():
    suite = CodingToolSuite()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("x")
        (Path(tmp) / "b.py").write_text("y")
        result = suite.call("list_dir", path=tmp)
        assert "a.py" in result
        assert "b.py" in result


def test_run_python_success():
    suite = CodingToolSuite()
    result = suite.call("run_python", code="print('hello coding')")
    assert "hello coding" in result
    assert "exit_code=0" in result


def test_run_python_error():
    suite = CodingToolSuite()
    result = suite.call("run_python", code="raise ValueError('oops')")
    assert "exit_code=1" in result
    assert "oops" in result


# ── mini-ReAct 解析单元测试 ───────────────────────────────────────────────────

def test_parse_tool_call_basic():
    text = "TOOL: read_file\nARGS:\npath: /tmp/a.py\n---"
    result = _parse_tool_call(text)
    assert result is not None
    name, args = result
    assert name == "read_file"
    assert args["path"] == "/tmp/a.py"


def test_parse_tool_call_multi_args():
    text = "TOOL: run_python\nARGS:\ncode: print(1)\ntimeout: 10\n---"
    name, args = _parse_tool_call(text)
    assert name == "run_python"
    assert args["timeout"] == "10"


def test_parse_tool_call_none_when_missing():
    assert _parse_tool_call("just some text") is None


def test_parse_final_answer():
    text = "FINAL_ANSWER:\ndef add(a, b): return a + b"
    answer = _parse_final_answer(text)
    assert answer == "def add(a, b): return a + b"


def test_parse_final_answer_none_when_missing():
    assert _parse_final_answer("no final answer here") is None


# ── CodeNodeExecutor 工具增强模式集成测试 ────────────────────────────────────

def test_executor_single_shot_no_tools():
    calls = []
    def llm(system, user):
        calls.append(system[:20])
        return "def foo(): pass"
    executor = CodeNodeExecutor(llm, language="python", tools=None)
    from agent.flow.base.components.node_spec import NodeManifest
    manifest = NodeManifest(
        task_id="impl_foo",
        description="Implement foo()",
        depends_on=(),
        tool_package="code:implement",
    )
    result = executor.run(manifest, {})
    assert "def foo" in result
    assert len(calls) == 1  # 只调用一�?LLM


def test_executor_with_tools_final_answer():
    calls = []
    def llm(system, user):
        calls.append(len(calls))
        # 第一轮直接给�?FINAL_ANSWER
        return "FINAL_ANSWER:\ndef add(a, b): return a + b"

    suite = CodingToolSuite()
    executor = CodeNodeExecutor(llm, tools=suite)
    from agent.flow.base.components.node_spec import NodeManifest
    manifest = NodeManifest(
        task_id="impl_add",
        description="Implement add function",
        depends_on=(),
        tool_package="code:implement",
    )
    result = executor.run(manifest, {})
    assert "def add" in result
    assert len(calls) == 1


def test_executor_with_tools_uses_tool_then_answers():
    """LLM 先调�?run_python，再给出 FINAL_ANSWER�?""
    step = [0]
    def llm(system, user):
        s = step[0]
        step[0] += 1
        if s == 0:
            return "TOOL: run_python\nARGS:\ncode: print(1+1)\n---"
        return "FINAL_ANSWER:\nresult = 2"

    suite = CodingToolSuite()
    executor = CodeNodeExecutor(llm, tools=suite, max_tool_iters=4)
    from agent.flow.base.components.node_spec import NodeManifest
    manifest = NodeManifest(
        task_id="compute",
        description="Compute 1+1",
        depends_on=(),
        tool_package="code:implement",
    )
    result = executor.run(manifest, {})
    assert "result = 2" in result
    assert step[0] == 2  # 两轮 LLM 调用
