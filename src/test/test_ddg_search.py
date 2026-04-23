import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from network.search.backend.ddg import DDGBackend
from network.search.engine import SearchEngine
from network.search.result import SearchResult


# ── helpers ───────────────────────────────────────────────────────────────────

def _print_results(results: list[SearchResult], label: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {label}  ({len(results)} results)")
    print(f"{'─' * 60}")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r.title}")
        print(f"    {r.url}")
        print(f"    {r.snippet[:120].rstrip()}…" if len(r.snippet) > 120 else f"    {r.snippet}")
        print()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_ddg_available():
    b = DDGBackend()
    assert b.is_available(), "duckduckgo_search package not installed"
    assert b.name == "duckduckgo"
    print("  DDGBackend.is_available() = True")
    print(f"  DDGBackend.name           = {b.name!r}")


def test_ddg_basic_search():
    b = DDGBackend()
    results = b.search("Python programming language", max_results=3, language="auto", categories="general")
    _print_results(results, "DDGBackend · 'Python programming language'")
    assert len(results) > 0, "Expected at least 1 result"
    for r in results:
        assert isinstance(r, SearchResult)
        assert r.title
        assert r.url.startswith("http")
        assert r.engine == "duckduckgo"


def test_ddg_chinese_query():
    b = DDGBackend()
    results = b.search("Python 教程 入门", max_results=3, language="auto", categories="general")
    _print_results(results, "DDGBackend · 'Python 教程 入门'")
    assert len(results) > 0, "Expected at least 1 result"


def test_ddg_max_results():
    b = DDGBackend()
    results = b.search("machine learning", max_results=5, language="auto", categories="general")
    _print_results(results, "DDGBackend · max_results=5")
    assert len(results) <= 5


def test_engine_uses_ddg():
    engine = SearchEngine()
    name = engine.active_backend_name
    print(f"\n  SearchEngine active backend: {name!r}")
    results = engine.search("ReAct agent LLM", max_results=3)
    _print_results(results, f"SearchEngine ({name}) · 'ReAct agent LLM'")
    assert len(results) > 0, "SearchEngine returned no results"


# ── entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("availability",    test_ddg_available),
        ("basic search",    test_ddg_basic_search),
        ("chinese query",   test_ddg_chinese_query),
        ("max_results cap", test_ddg_max_results),
        ("engine dispatch", test_engine_uses_ddg),
    ]

    passed = failed = 0
    for name, fn in tests:
        print(f"\n>> {name}")
        try:
            fn()
            print(f"  [PASS]")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}\n")
    sys.exit(0 if failed == 0 else 1)
