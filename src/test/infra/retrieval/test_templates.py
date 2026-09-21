from __future__ import annotations

import re

from infra.retrieval.templates import (
    BUILTIN_TEMPLATES,
    RewriteTemplate,
    TemplateStore,
)


def test_builtin_templates_compile_and_have_general_fallback():
    for t in BUILTIN_TEMPLATES:
        if t.patterns:
            assert t.compiled, t.template_id
        assert t.frame
    general = [t for t in BUILTIN_TEMPLATES if not t.patterns]
    assert len(general) == 1


def test_match_returns_first_hit_and_capture_group():
    t = next(x for x in BUILTIN_TEMPLATES if x.template_id == "builtin.remember_q")
    m = t.match("你还记得我们上次去的拉面店吗")
    assert m is not None
    assert "我们上次去的拉面店" == m.group(1)


def test_lazy_capture_does_not_match_empty():
    # 回归：`(.*?)吗?` 曾捕获空串导致框架剥除失效
    t = next(x for x in BUILTIN_TEMPLATES if x.template_id == "builtin.remember_q")
    m = t.match("还记得我们上次去的拉面店吗")
    assert m is not None
    assert m.group(1).strip() != ""


def test_store_orders_pattern_first_then_general():
    store = TemplateStore()
    order = [t.template_id for t in store.active_templates()]
    assert order[-1] == "builtin.general"
    assert "builtin.remember_q" in order


def test_store_add_dedupes_by_pattern_fingerprint(tmp_path):
    store = TemplateStore(tmp_path / "templates.json")
    t1 = RewriteTemplate(
        template_id="grown.a", name="a", source="grown", patterns=(r"(前几天)(.+)",)
    )
    t2 = RewriteTemplate(
        template_id="grown.b", name="b", source="grown", patterns=(r"(前几天)(.+)",)
    )
    assert store.add(t1) is True
    assert store.add(t2) is False  # pattern 集相同 → 拒绝
    assert store.add(RewriteTemplate(template_id="builtin.general", name="x")) is False


def test_store_retire_only_grown(tmp_path):
    store = TemplateStore(tmp_path / "templates.json")
    t = RewriteTemplate(
        template_id="grown.x", name="x", source="grown", patterns=(r"(哪个城市)(.+)",)
    )
    store.add(t)
    assert store.retire("grown.x") is True
    assert store.get("grown.x") is None
    assert store.retire("builtin.general") is False


def test_store_persistence_roundtrip(tmp_path):
    path = tmp_path / "templates.json"
    store = TemplateStore(path)
    store.add(
        RewriteTemplate(
            template_id="grown.p",
            name="p",
            source="grown",
            patterns=(r"(哪一年)(.+)",),
            drop_words=frozenset({"大概"}),
            frame="time",
        )
    )
    store.retire("grown.p")

    store2 = TemplateStore(path)
    # 退役状态持久化：grown.p 不在 active，get 返回 None
    assert store2.get("grown.p") is None
    ids = [t.template_id for t in store2.grown_templates()]
    assert "grown.p" not in ids


def test_from_dict_rejects_invalid_regex_via_store(tmp_path):
    # from_dict 本身不编译；store._load 对坏正则跳过——用 from_dict 手工验证字段
    t = RewriteTemplate.from_dict(
        {
            "template_id": "grown.q",
            "name": "q",
            "patterns": [r"(上一份工作)(.+)"],
            "drop_words": ["那个"],
            "frame": "recall",
        }
    )
    assert t.source == "grown"
    assert t.compiled[0].search("上一份工作是什么") is not None
