"""
草稿本工具测试
==============
覆盖 react/action/tools/impl/scratchpad.py：
  - ScratchpadStore               — 核心 K-V 存储
  - NoteWriteAction  (note_write)
  - NoteReadAction   (note_read)
  - NoteDeleteAction (note_delete)

运行方式：
  cd E:/ReAct
  python -m pytest src/test/tools/test_scratchpad.py -v
"""
from __future__ import annotations

import importlib.machinery
import sys
import threading
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
from agent.react.action.tools.impl.scratchpad import (
    NoteDeleteAction,
    NoteReadAction,
    NoteWriteAction,
    ScratchpadStore,
)


# ═════════════════════════════════════════════════════════════════════════════
#  ScratchpadStore
# ═════════════════════════════════════════════════════════════════════════════

class TestScratchpadStore:

    def setup_method(self):
        self.store = ScratchpadStore()

    def test_write_and_read(self):
        self.store.write("key1", "value1")
        assert self.store.read("key1") == "value1"

    def test_read_nonexistent_returns_none(self):
        assert self.store.read("no_such_key") is None

    def test_overwrite(self):
        self.store.write("k", "first")
        self.store.write("k", "second")
        assert self.store.read("k") == "second"

    def test_delete_existing(self):
        self.store.write("d", "val")
        result = self.store.delete("d")
        assert result is True
        assert self.store.read("d") is None

    def test_delete_nonexistent_returns_false(self):
        result = self.store.delete("ghost")
        assert result is False

    def test_all_keys_sorted(self):
        self.store.write("banana", "b")
        self.store.write("apple", "a")
        self.store.write("cherry", "c")
        keys = self.store.all_keys()
        assert keys == ["apple", "banana", "cherry"]

    def test_all_keys_empty(self):
        assert self.store.all_keys() == []

    def test_all_items(self):
        self.store.write("x", "1")
        self.store.write("y", "2")
        items = self.store.all_items()
        assert items == {"x": "1", "y": "2"}

    def test_reset_clears_all(self):
        self.store.write("a", "1")
        self.store.write("b", "2")
        self.store.reset()
        assert self.store.all_keys() == []
        assert self.store.read("a") is None

    def test_thread_safety(self):
        errors = []

        def writer(key: str, val: str):
            for _ in range(100):
                self.store.write(key, val)
                self.store.read(key)

        threads = [threading.Thread(target=writer, args=(f"k{i}", f"v{i}")) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            raise AssertionError(f"Thread errors: {errors}")


# ═════════════════════════════════════════════════════════════════════════════
#  NoteWriteAction
# ═════════════════════════════════════════════════════════════════════════════

class TestNoteWrite:

    def setup_method(self):
        self.store = ScratchpadStore()
        self.action = NoteWriteAction(store=self.store)

    def test_write_stores_value(self):
        self.action.execute(key="plan", content="Step 1: research")
        assert self.store.read("plan") == "Step 1: research"

    def test_returns_confirmation_with_key(self):
        result = self.action.execute(key="note1", content="hello")
        assert "note1" in result

    def test_returns_char_count(self):
        result = self.action.execute(key="k", content="hello")
        assert "5" in result

    def test_no_store_raises(self):
        action = NoteWriteAction(store=None)
        with pytest.raises(RuntimeError):
            action.execute(key="k", content="v")

    def test_overwrite_existing(self):
        self.action.execute(key="k", content="old")
        self.action.execute(key="k", content="new")
        assert self.store.read("k") == "new"

    def test_empty_content_allowed(self):
        result = self.action.execute(key="empty", content="")
        assert isinstance(result, str)


# ═════════════════════════════════════════════════════════════════════════════
#  NoteReadAction
# ═════════════════════════════════════════════════════════════════════════════

class TestNoteRead:

    def setup_method(self):
        self.store = ScratchpadStore()
        self.action = NoteReadAction(store=self.store)

    def test_read_existing(self):
        self.store.write("fact", "Paris is the capital of France")
        result = self.action.execute(key="fact")
        assert "Paris is the capital of France" in result

    def test_read_nonexistent_key(self):
        result = self.action.execute(key="missing")
        assert "不存在" in result

    def test_read_all_when_key_empty(self):
        self.store.write("alpha", "aaa")
        self.store.write("beta", "bbb")
        result = self.action.execute(key="")
        assert "alpha" in result
        assert "beta" in result

    def test_empty_store_list_message(self):
        result = self.action.execute(key="")
        assert "空" in result

    def test_key_in_result(self):
        self.store.write("mykey", "myvalue")
        result = self.action.execute(key="mykey")
        assert "mykey" in result

    def test_long_preview_truncated(self):
        self.store.write("long", "A" * 200)
        result = self.action.execute(key="")
        assert "..." in result

    def test_no_store_raises(self):
        action = NoteReadAction(store=None)
        with pytest.raises(RuntimeError):
            action.execute(key="k")


# ═════════════════════════════════════════════════════════════════════════════
#  NoteDeleteAction
# ═════════════════════════════════════════════════════════════════════════════

class TestNoteDelete:

    def setup_method(self):
        self.store = ScratchpadStore()
        self.action = NoteDeleteAction(store=self.store)

    def test_delete_existing(self):
        self.store.write("temp", "data")
        result = self.action.execute(key="temp")
        assert "temp" in result
        assert self.store.read("temp") is None

    def test_delete_nonexistent(self):
        result = self.action.execute(key="ghost")
        assert "不存在" in result

    def test_confirmation_contains_key(self):
        self.store.write("abc", "xyz")
        result = self.action.execute(key="abc")
        assert "abc" in result

    def test_no_store_raises(self):
        action = NoteDeleteAction(store=None)
        with pytest.raises(RuntimeError):
            action.execute(key="k")

    def test_delete_then_read_returns_none(self):
        self.store.write("x", "y")
        self.action.execute(key="x")
        assert self.store.read("x") is None


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [TestScratchpadStore, TestNoteWrite, TestNoteRead, TestNoteDelete]
    passed = failed = 0

    for cls in suites:
        print(f"\n── {cls.__name__} ──")
        inst = cls()
        for m in sorted(x for x in dir(cls) if x.startswith("test_")):
            inst.setup_method()
            try:
                getattr(inst, m)()
                print(f"  PASS  {m}")
                passed += 1
            except Exception:
                print(f"  FAIL  {m}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*50}")
    print(f"Result: {passed} passed, {failed} failed")
