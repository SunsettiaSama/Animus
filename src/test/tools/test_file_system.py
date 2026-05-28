"""
文件系统工具测试
================
覆盖 react/action/tools/impl/file_system.py�?
  - FileReadAction   (file_read)
  - FileWriteAction  (file_write)
  - FileListAction   (file_list)
  - FileExistsAction (file_exists)

sandbox �?MagicMock 注入，resolve_path 返回 tmp_path 下的真实路径�?

运行方式�?
  cd E:/ReAct
  python -m pytest src/test/tools/test_file_system.py -v
"""
from __future__ import annotations

import importlib.machinery
import os
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

from agent.react.action.tools.impl.file_system import (
    FileExistsAction,
    FileListAction,
    FileReadAction,
    FileWriteAction,
)


def _make_sandbox(root: Path) -> MagicMock:
    """构造一个把相对路径解析�?root/ 下的 sandbox mock�?""
    sb = MagicMock()
    sb.cfg.max_file_size_bytes = 10_485_760

    def resolve(p: str) -> Path:
        rp = Path(p)
        if rp.is_absolute():
            raise ValueError(f"绝对路径越权: {p}")
        resolved = (root / rp).resolve()
        if not str(resolved).startswith(str(root.resolve())):
            raise ValueError(f"路径逃�? {p}")
        return resolved

    sb.resolve_path.side_effect = resolve
    return sb


# ════════════════════════════════════════════════════════════════════════════�?
#  FileWriteAction & FileReadAction
# ════════════════════════════════════════════════════════════════════════════�?

class TestFileWriteRead:

    def test_write_then_read_roundtrip(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        writer = FileWriteAction(sandbox=sb)
        reader = FileReadAction(sandbox=sb)

        content = "Hello, 世界！\nSecond line."
        writer.execute(path="note.txt", content=content)
        result = reader.execute(path="note.txt")

        assert "Hello, 世界�? in result
        assert "Second line." in result

    def test_write_creates_parent_dirs(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        writer = FileWriteAction(sandbox=sb)
        writer.execute(path="a/b/c.txt", content="nested")
        assert (tmp_path / "a" / "b" / "c.txt").exists()

    def test_write_overwrite_by_default(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        writer = FileWriteAction(sandbox=sb)
        writer.execute(path="f.txt", content="first")
        writer.execute(path="f.txt", content="second")
        result = FileReadAction(sandbox=sb).execute(path="f.txt")
        assert "second" in result
        assert "first" not in result

    def test_append_mode(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        writer = FileWriteAction(sandbox=sb)
        writer.execute(path="log.txt", content="line1\n")
        writer.execute(path="log.txt", content="line2\n", mode="append")
        result = FileReadAction(sandbox=sb).execute(path="log.txt")
        assert "line1" in result
        assert "line2" in result

    def test_write_returns_char_count(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        result = FileWriteAction(sandbox=sb).execute(path="x.txt", content="hello")
        assert "5" in result

    def test_read_max_chars_truncates(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        big = "A" * 200
        FileWriteAction(sandbox=sb).execute(path="big.txt", content=big)
        result = FileReadAction(sandbox=sb).execute(path="big.txt", max_chars=50)
        assert "截断" in result or len(result) < 300

    def test_read_nonexistent_raises(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        with pytest.raises(Exception):
            FileReadAction(sandbox=sb).execute(path="ghost.txt")

    def test_path_escape_raises(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        with pytest.raises((ValueError, Exception)):
            FileReadAction(sandbox=sb).execute(path="../escape.txt")


# ════════════════════════════════════════════════════════════════════════════�?
#  FileListAction
# ════════════════════════════════════════════════════════════════════════════�?

class TestFileList:

    def test_list_files(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        (tmp_path / "alpha.txt").write_text("a")
        (tmp_path / "beta.txt").write_text("b")
        result = FileListAction(sandbox=sb).execute(path=".")
        assert "alpha.txt" in result
        assert "beta.txt" in result

    def test_list_directory_marked(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        (tmp_path / "subdir").mkdir()
        result = FileListAction(sandbox=sb).execute(path=".")
        assert "[目录]" in result
        assert "subdir" in result

    def test_list_empty_dir(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        result = FileListAction(sandbox=sb).execute(path=".")
        assert "�? in result

    def test_list_recursive(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        sub = tmp_path / "child"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")
        result = FileListAction(sandbox=sb).execute(path=".", recursive=True)
        assert "deep.txt" in result

    def test_list_nonexistent_dir(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        result = FileListAction(sandbox=sb).execute(path="nodir")
        assert "不存�? in result or "不是目录" in result

    def test_shows_file_size(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        (tmp_path / "sized.txt").write_text("12345")
        result = FileListAction(sandbox=sb).execute(path=".")
        assert "字节" in result


# ════════════════════════════════════════════════════════════════════════════�?
#  FileExistsAction
# ════════════════════════════════════════════════════════════════════════════�?

class TestFileExists:

    def test_existing_file(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        (tmp_path / "exists.txt").write_text("yes")
        result = FileExistsAction(sandbox=sb).execute(path="exists.txt")
        assert "存在" in result
        assert "文件" in result

    def test_existing_directory(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        (tmp_path / "mydir").mkdir()
        result = FileExistsAction(sandbox=sb).execute(path="mydir")
        assert "存在" in result
        assert "目录" in result

    def test_nonexistent_path(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        result = FileExistsAction(sandbox=sb).execute(path="ghost.txt")
        assert "不存�? in result

    def test_shows_size_for_file(self, tmp_path):
        sb = _make_sandbox(tmp_path)
        (tmp_path / "sized.txt").write_text("hello")
        result = FileExistsAction(sandbox=sb).execute(path="sized.txt")
        assert "字节" in result


# ════════════════════════════════════════════════════════════════════════════�?
#  直接运行
# ════════════════════════════════════════════════════════════════════════════�?

if __name__ == "__main__":
    import tempfile
    import traceback

    passed = failed = 0

    def _tmp():
        d = tempfile.mkdtemp()
        return Path(d)

    suites = [TestFileWriteRead, TestFileList, TestFileExists]
    for cls in suites:
        print(f"\n── {cls.__name__} ──")
        inst = cls()
        for m in sorted(x for x in dir(cls) if x.startswith("test_")):
            tmp = _tmp()
            try:
                getattr(inst, m)(tmp)
                print(f"  PASS  {m}")
                passed += 1
            except Exception:
                print(f"  FAIL  {m}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed} passed, {failed} failed")
