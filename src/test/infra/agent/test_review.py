from __future__ import annotations

from infra.agent.review import WhitelistCallReview


def test_known_tools_pass():
    review = WhitelistCallReview(frozenset({"memory_search", "web_search"}))
    result = review.review(
        [
            {"action": "web_search", "args": {"q": "x"}},
            {"action": "memory_search", "args": {"query": "y"}},
        ]
    )
    assert result.ok
    assert result.issues == []
    assert result.correction == ""


def test_unknown_tool_rejected_with_explicit_suggestion():
    review = WhitelistCallReview(frozenset({"memory_search", "web_search"}))
    result = review.review([{"action": "memroy_search", "args": {"query": "x"}}])
    assert not result.ok
    assert any("memroy_search" in i for i in result.issues)
    # 模糊纠正只做显式建议，不静默替换
    assert "你是否想用 'memory_search'" in result.issues[0]
    assert result.correction.count("memory_search") >= 1


def test_correction_contains_available_tools_and_template():
    review = WhitelistCallReview(frozenset({"web_search"}))
    result = review.review([{"action": "no_such_tool", "args": {}}])
    assert not result.ok
    assert "未通过审查" in result.correction
    assert "均未执行" in result.correction
    assert "可用工具" in result.correction
    assert "'web_search'" in result.correction
    assert '<A>[{"action": "工具名", "args": {...}}]</A>' in result.correction


def test_unknown_without_close_match_has_no_suggestion():
    review = WhitelistCallReview(frozenset({"web_search"}))
    result = review.review([{"action": "zzzQQQ", "args": {}}])
    assert not result.ok
    assert all("你是否想用" not in i for i in result.issues)


def test_fuzzy_suggest_disabled():
    review = WhitelistCallReview(frozenset({"web_search"}), fuzzy_suggest=False)
    result = review.review([{"action": "web_sear", "args": {}}])
    assert not result.ok
    assert all("你是否想用" not in i for i in result.issues)


def test_args_not_dict_flagged():
    review = WhitelistCallReview(frozenset({"web_search"}))
    result = review.review([{"action": "web_search", "args": "q=x"}])
    assert not result.ok
    assert any("args" in i and "dict" in i for i in result.issues)


def test_missing_args_key_passes_structural_check():
    review = WhitelistCallReview(frozenset({"web_search"}))
    assert review.review([{"action": "web_search"}]).ok


def test_empty_action_flagged():
    review = WhitelistCallReview(frozenset({"web_search"}))
    result = review.review([{"action": "", "args": {}}])
    assert not result.ok
    assert any("action 为空" in i for i in result.issues)


def test_empty_whitelist_degrades_to_structural_check():
    review = WhitelistCallReview(frozenset())
    assert review.review([{"action": "anything_at_all", "args": {}}]).ok


def test_callable_tool_names_source():
    review = WhitelistCallReview(lambda: frozenset({"dynamic_tool"}))
    assert review.review([{"action": "dynamic_tool", "args": {}}]).ok
    assert not review.review([{"action": "other_tool", "args": {}}]).ok


def test_callable_source_failure_degrades_to_structural():
    def boom() -> frozenset[str]:
        raise RuntimeError("registry down")

    review = WhitelistCallReview(boom)
    assert review.review([{"action": "anything_at_all", "args": {}}]).ok
