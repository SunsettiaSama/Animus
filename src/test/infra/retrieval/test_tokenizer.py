from __future__ import annotations

from infra.retrieval.tokenizer import (
    _tokenize_fallback,
    backend,
    tokenize,
)


def test_backend_is_known_value():
    assert backend() in ("jieba", "fallback")


def test_tokenize_cjk_returns_terms_with_pos_or_blank():
    terms, used = tokenize("你还记得那家拉面店吗")
    assert used == backend()
    words = [t.word for t in terms]
    assert any("拉面" in w or "拉面店" in w for w in words)
    # 词性要么有值（jieba），要么为空串（fallback）
    assert all(isinstance(t.pos, str) for t in terms)


def test_tokenize_empty_and_whitespace():
    assert tokenize("") == ([], backend())
    assert tokenize("   ") == ([], backend())


def test_tokenize_deterministic():
    a = tokenize("跟我聊聊上次的项目进度")
    b = tokenize("跟我聊聊上次的项目进度")
    assert a == b


def test_fallback_tokenizer_keeps_cjk_runs_and_latin_words():
    terms = _tokenize_fallback("聊聊 project-alpha 123 猫")
    words = [t.word for t in terms]
    assert "聊聊" in words
    assert "猫" in words
    assert "project-alpha" in words  # 复合标识符整体保留
    assert "123" in words
    assert all(t.pos == "" for t in terms)
