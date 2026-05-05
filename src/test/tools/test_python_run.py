"""
Python 沙箱工具测试
===================
覆盖 react/action/tools/impl/python_run.py：
  - PythonRunAction (python_run)

sandbox 通过 MagicMock 注入，exec_python() 行为由测试控制。

运行方式：
  cd E:/ReAct
  python -m pytest src/test/tools/test_python_run.py -v
"""
from __future__ import annotations

import importlib.machinery
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
REACT_DIR = SRC / "agent" / "react"


def _pkg_stub(dotted_name: str, path: Path | None = None) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__package__ = dotted_name
    m.__spec__ = importlib.machinery.ModuleSpec(
        dotted_name, loader=None, is_package=True
    )
    if path is not None:
        m.__path__ = [str(path)]
        m.__spec__.submodule_search_locations = m.__path__
    sys.modules[dotted_name] = m
    return m


def _mod_stub(dotted_name: str) -> types.ModuleType:
    m = types.ModuleType(dotted_name)
    m.__spec__ = importlib.machinery.ModuleSpec(dotted_name, loader=None)
    sys.modules[dotted_name] = m
    return m


_pkg_stub("agent.react", REACT_DIR)
_lc = _pkg_stub("langchain_community")
_lce = _mod_stub("langchain_community.embeddings")
_lcv = _mod_stub("langchain_community.vectorstores")
_lcv.FAISS = MagicMock()
_lc.embeddings = _lce
_lc.vectorstores = _lcv
_lc_hf = _pkg_stub("langchain_huggingface")
_lc_hf.HuggingFaceEmbeddings = MagicMock(name="HuggingFaceEmbeddings")

sys.path.insert(0, str(SRC))

import pytest
from agent.react.action.tools.impl.python_run import PythonRunAction


def _make_sandbox(return_value: str = "", side_effect=None) -> MagicMock:
    sb = MagicMock()
    if side_effect is not None:
        sb.exec_python.side_effect = side_effect
    else:
        sb.exec_python.return_value = return_value
    return sb


# ═════════════════════════════════════════════════════════════════════════════
#  PythonRunAction
# ═════════════════════════════════════════════════════════════════════════════

class TestPythonRun:

    def test_no_sandbox_raises(self):
        action = PythonRunAction(sandbox=None)
        with pytest.raises(RuntimeError, match="沙箱"):
            action.execute(code="print(1)")

    def test_returns_sandbox_output(self):
        sb = _make_sandbox(return_value="42\n")
        action = PythonRunAction(sandbox=sb)
        result = action.execute(code="print(42)")
        assert "42" in result

    def test_code_forwarded_to_sandbox(self):
        sb = _make_sandbox(return_value="ok")
        action = PythonRunAction(sandbox=sb)
        code = "x = 1 + 2\nprint(x)"
        action.execute(code=code)
        sb.exec_python.assert_called_once_with(code)

    def test_sandbox_exception_propagates(self):
        sb = _make_sandbox(side_effect=RuntimeError("syntax error"))
        action = PythonRunAction(sandbox=sb)
        with pytest.raises(RuntimeError, match="syntax error"):
            action.execute(code="bad code !!!")

    def test_timeout_propagates(self):
        sb = _make_sandbox(side_effect=TimeoutError("execution timed out"))
        action = PythonRunAction(sandbox=sb)
        with pytest.raises(TimeoutError):
            action.execute(code="while True: pass")

    def test_empty_output(self):
        sb = _make_sandbox(return_value="")
        action = PythonRunAction(sandbox=sb)
        result = action.execute(code="x = 1")
        assert isinstance(result, str)

    def test_multiline_output(self):
        output = "line1\nline2\nline3"
        sb = _make_sandbox(return_value=output)
        action = PythonRunAction(sandbox=sb)
        result = action.execute(code="for i in range(3): print(i)")
        assert "line1" in result
        assert "line3" in result

    def test_sandbox_called_exactly_once(self):
        sb = _make_sandbox(return_value="done")
        action = PythonRunAction(sandbox=sb)
        action.execute(code="pass")
        assert sb.exec_python.call_count == 1


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    inst = TestPythonRun()
    passed = failed = 0
    for m in sorted(x for x in dir(TestPythonRun) if x.startswith("test_")):
        try:
            getattr(inst, m)()
            print(f"  PASS  {m}")
            passed += 1
        except Exception:
            print(f"  FAIL  {m}")
            traceback.print_exc()
            failed += 1

    print(f"\nResult: {passed} passed, {failed} failed")
