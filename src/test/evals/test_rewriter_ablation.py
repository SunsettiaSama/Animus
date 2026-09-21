from __future__ import annotations

from evals.memory_humaneness.retrieval_bench import evaluate_base, evaluate_case
from evals.memory_humaneness.schema import HumanenessCase, MemorySeed
from infra.retrieval import TemplateRewriter


def _case(case_id="c1", memories=None, anchors=None, current="还记得吗", history=None):
    return HumanenessCase(
        case_id=case_id,
        category="日常",
        memories=memories or [],
        current_user=current,
        history=history or [],
        must_remember=anchors or [],
    )


class _ListBase:
    """最简协议基座：recall 返回 query 分词命中的记忆行。"""

    kind = "list"

    def __init__(self) -> None:
        self.items: list[str] = []
        self.last_query = ""

    def ingest(self, text: str, **_) -> str:
        self.items.append(text)
        return str(len(self.items))

    def recall(self, query: str, top_k: int = 5, **__):
        from agent.soul.memory.graph.networks.block import MemoryBlock

        self.last_query = query
        chars = [c for c in query if "\u4e00" <= c <= "\u9fff"]
        grams = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
        grams |= {w for w in query.split() if len(w) >= 2}
        hits = [t for t in self.items if any(g in t for g in grams)][:top_k]
        return MemoryBlock(label=self.kind, entries=hits)

    def search(self, mode: str, **kwargs):
        return []

    def dispose(self) -> None:
        pass


def test_evaluate_case_without_rewriter_keeps_legacy_behavior():
    case = _case(
        memories=[MemorySeed(text="我们上次去了海边看日出")],
        anchors=["海边"],
        current="你还记得我们上次去的地方吗",
    )
    base = _ListBase()
    base.items = ["我们上次去了海边看日出"]
    ev = evaluate_case(base, case, top_k=5)
    assert ev.rewrite_template == ""
    assert ev.rewrite_query == ""
    assert base.last_query == "你还记得我们上次去的地方吗"
    assert ev.hit_at_k


def test_evaluate_case_with_rewriter_records_metadata_and_rewrites_query():
    case = _case(
        memories=[MemorySeed(text="上次一起去了那家拉面店")],
        anchors=["拉面店"],
        current="你还记得我们上次一起去的拉面店吗",
    )
    base = _ListBase()
    base.items = ["上次一起去了那家拉面店"]
    rewriter = TemplateRewriter()
    ev = evaluate_case(base, case, top_k=5, query_rewriter=rewriter)
    assert ev.rewrite_template == "builtin.remember_q"
    assert ev.rewrite_query  # 改写后的 query 被记录
    assert any("拉面" in e for e in ev.rewrite_entities)
    assert base.last_query == ev.rewrite_query  # recall 收到的是改写后 query
    assert "还记得" not in base.last_query
    assert ev.hit_at_k  # 关键词仍在 → 依然命中锚点


def test_matrix_arms_zero_pollution_and_deterministic():
    from evals.memory_humaneness.ablation import ablation_factory

    cases = [
        _case(
            case_id="m1",
            memories=[MemorySeed(text="上周去了杭州西湖断桥")],
            anchors=["西湖"],
            current="还记得上周去的地方吗",
        ),
        _case(
            case_id="m2",
            memories=[MemorySeed(text="养的猫叫年糕")],
            anchors=["年糕"],
            current="你说过你养了一只猫",
        ),
    ]
    rewriter = TemplateRewriter()
    for kind in ("kg_bm25", "kg_spread"):
        r1 = evaluate_base(ablation_factory(kind), cases, query_rewriter=rewriter)
        r2 = evaluate_base(ablation_factory(kind), cases, query_rewriter=rewriter)
        assert r1["metrics"]["hit_at_k"] == r2["metrics"]["hit_at_k"]
        # 用例间零污染：工厂模式下 m2 的存储不含 m1 的记忆
        for c in r1["cases"]:
            assert c.case_id in {"m1", "m2"}


def test_off_arm_matches_baseline_exactly():
    """rewriter=None 的结果与不传参数（历史默认）完全一致——回归保护。"""
    from evals.memory_humaneness.ablation import ablation_factory

    cases = [
        _case(
            case_id="r1",
            memories=[MemorySeed(text="周末去爬了山")],
            anchors=["爬山"],
            current="还记得周末做了什么吗",
        )
    ]
    baseline = evaluate_base(ablation_factory("kg_bm25"), cases)
    off = evaluate_base(ablation_factory("kg_bm25"), cases, query_rewriter=None)
    assert baseline["metrics"] == off["metrics"]


def _load_walk_module():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "memory_rewriter_ablation.py"
    spec = importlib.util.spec_from_file_location("_memory_rewriter_ablation", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_kg_walk_arm_entity_boost_ranks_anchor_first():
    mod = _load_walk_module()
    # 构造玩具用例：锚点记忆与 query 共享实体"拉面店"
    case = _case(
        case_id="w1",
        memories=[
            MemorySeed(text="上次一起去的拉面店在巷子深处"),
            MemorySeed(text="那家拉面店旁边有家旧书店"),
        ],
        anchors=["拉面店"],
        current="你还记得我们上次一起去的拉面店吗",
    )
    rewriter = TemplateRewriter()
    result = evaluate_base(mod._walk_factory(), [case], query_rewriter=rewriter)
    lines = result["cases"][0].lines
    assert lines, "kg_walk 臂应产出检索行"
    assert any("拉面店" in line for line in lines)
