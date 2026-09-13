"""拟人化记忆 benchmark 测试：数据集校验 + mock LLM 端到端 + 三基座协议。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from evals.memory_humaneness.judge import ExpertJudge, HeuristicJudge
from evals.memory_humaneness.report import aggregate, write_report
from evals.memory_humaneness.runner import HumanenessHarness
from evals.memory_humaneness.schema import CATEGORIES, load_cases, validate_dataset

DATASET = SRC / "evals" / "memory_humaneness" / "data" / "cases.jsonl"


class FakeReplyLLM:
    """鸭子类型 LLM：按用例生成确定性回复（覆盖/不覆盖锚点可控）。"""

    def __init__(self, *, cover_anchors: bool = True) -> None:
        self.cover_anchors = cover_anchors
        self.calls = 0

    def generate_messages(self, messages):
        self.calls += 1
        human = messages[-1].content
        # 从 system 的【相关记忆】里抽一个关键词回填，模拟"记得"或"不记得"
        system = messages[0].content
        if self.cover_anchors and "【相关记忆】" in system:
            block = system.split("【相关记忆】", 1)[1].strip()
            snippet = block.split("\n", 1)[0][:24]
            return f"记得呀，{snippet}……你突然提这个，怎么啦？"
        return "诶这个我真想不起来了，你跟我说说呗？"


class FakeJudgeLLM:
    """可编程评审：先返回合规 JSON，再返回垃圾，考察降级路径。

    ``wrapped`` 模式模拟推理型评委：输出带 <think>，且 think 里含花括号——
    用于回归"思维链内花括号导致 JSON 提取失败"的问题。
    """

    def __init__(self) -> None:
        self.mode = "json"

    def generate_messages(self, messages):
        if self.mode == "json":
            return json.dumps({
                "scores": {
                    "memory_coherence": 4.5, "human_likeness": 4.0,
                    "emotional_attunement": 4.0, "non_hallucination": 5.0,
                    "overall": 4.4,
                },
                "evidence": "记得呀，……",
                "rationale": "细节回忆自然，语气口语。",
            }, ensure_ascii=False)
        if self.mode == "wrapped":
            return ('<think>回复提到了蓝莓，锚点命中。'
                    '比如 {"memory_coherence": 4} 这样的维度分。'
                    '综合给出 overall。</think>\n'
                    + json.dumps({
                        "scores": {
                            "memory_coherence": 4.5, "human_likeness": 4.0,
                            "emotional_attunement": 4.0, "non_hallucination": 5.0,
                            "overall": 4.4,
                        },
                        "evidence": "记得呀，蓝莓……",
                        "rationale": "细节准确且口语。",
                    }, ensure_ascii=False))
        return "这不是 JSON"


# ── 数据集 ────────────────────────────────────────────────────────────────

def test_dataset_has_100_valid_cases():
    cases = load_cases(DATASET)
    assert len(cases) == 100
    assert validate_dataset(cases) == []
    cats = {c.category for c in cases}
    # multi_hop 属于 L4 多跳数据集（multihop_cases.jsonl），不在主数据集中
    assert cats == set(CATEGORIES) - {"multi_hop"}
    for cat in cats:
        n = sum(1 for c in cases if c.category == cat)
        assert n == 10, f"{cat} 应有 10 条，实际 {n}"
    ids = [c.case_id for c in cases]
    assert len(set(ids)) == 100


# ── 评判器 ────────────────────────────────────────────────────────────────

def test_heuristic_judge_scores_covered_reply_higher(tmp_path):
    cases = load_cases(DATASET)
    case = next(c for c in cases if c.category == "event_recall")
    covering = HeuristicJudge().judge(case, ["[x] 记忆行"], f"记得呀，{case.must_remember[0]}那事儿，哈哈。")
    missing = HeuristicJudge().judge(case, [], "完全不相关的一段话。")
    assert covering.scores["memory_coherence"] > missing.scores["memory_coherence"]
    assert 1.0 <= covering.scores["overall"] <= 5.0


def test_absence_case_rewards_honesty():
    cases = load_cases(DATASET)
    case = next(c for c in cases if c.category == "graceful_absence")
    honest = HeuristicJudge().judge(case, [], "这个我真想不起来了，你还没跟我说过呢。")
    fabricating = HeuristicJudge().judge(case, [], "你说过你室友叫大力呀。")
    assert honest.scores["non_hallucination"] > fabricating.scores["non_hallucination"]


def test_expert_judge_parses_json_and_falls_back():
    cases = load_cases(DATASET)
    case = cases[0]
    good = FakeJudgeLLM()
    verdict = ExpertJudge(good).judge(case, [], "回复")
    assert verdict.judge == "llm_expert"
    assert verdict.scores["overall"] == pytest.approx(4.4)

    # 回归：推理型评委的 think 里含花括号，不得破坏 JSON 提取（曾致 96% 静默降级）
    wrapped = FakeJudgeLLM()
    wrapped.mode = "wrapped"
    verdict_w = ExpertJudge(wrapped).judge(case, [], "回复")
    assert verdict_w.judge == "llm_expert"
    assert verdict_w.scores["overall"] == pytest.approx(4.4)
    assert verdict_w.rationale == "细节准确且口语。"

    bad = FakeJudgeLLM()
    bad.mode = "garbage"
    verdict2 = ExpertJudge(bad).judge(case, [], "回复")
    assert verdict2.judge == "heuristic"  # 垃圾输出降级，run 不中断


def test_expert_judge_salvages_broken_json():
    """回归：evidence 内嵌未转义引号 → loads 失败，但分数可逐维正则抢救。"""
    cases = load_cases(DATASET)
    case = cases[0]

    class _BrokenQuoteJudge:
        def generate_messages(self, messages):
            return (
                '<think>评估中，回复提到蓝莓。</think>\n'
                '{"scores": {"memory_coherence": 4, "human_likeness": 5, '
                '"emotional_attunement": 4, "non_hallucination": 5, "overall": 4}, '
                '"evidence": "回复说"蓝莓又捣乱了"，细节吻合。", '
                '"rationale": "记得准确。"}'
            )

    verdict = ExpertJudge(_BrokenQuoteJudge()).judge(case, [], "回复")
    assert verdict.judge == "llm_expert"
    assert verdict.scores["overall"] == pytest.approx(4.0)
    assert verdict.rationale.startswith("[regex修复]")
    assert "蓝莓" in verdict.evidence


def test_strip_reasoning_removes_think_blocks():
    from evals.memory_humaneness.runner import strip_reasoning

    assert strip_reasoning("<think>推理过程</think>嗯，记得呀。") == "嗯，记得呀。"
    # 多行思维链（DOTALL）
    assert strip_reasoning("<think>a\nb\nc</think>\n回复正文") == "回复正文"
    # 未闭合 <think>：丢弃其后全部内容
    assert strip_reasoning("前言<think>没闭合的思考") == "前言"
    assert strip_reasoning("普通回复") == "普通回复"


def test_harness_stores_stripped_reply(tmp_path):
    from evals.memory_humaneness.bases import NullMemoryBase
    from evals.memory_humaneness.runner import HumanenessHarness
    from evals.memory_humaneness.schema import load_cases as _load

    class _ThinkLLM:
        def generate_messages(self, messages):
            return "<think>长篇推理……</think>  记得呀，蓝莓嘛。"

    case = _load(DATASET)[0]
    harness = HumanenessHarness(_ThinkLLM(), HeuristicJudge())
    record = harness.run_case(case, NullMemoryBase())
    assert record.reply == "记得呀，蓝莓嘛。"
    assert record.error == ""


def test_transcript_saves_raw_before_parse(tmp_path):
    """先保存再解析：LLM 原始输出（含 think/花括号）完整落盘，记录里是剥离后的。"""
    from evals.memory_humaneness.bases import NullMemoryBase
    from evals.memory_humaneness.judge import ExpertJudge
    from evals.memory_humaneness.runner import HumanenessHarness

    class _ThinkReplyLLM:
        def generate_messages(self, messages):
            return "<think>内心戏 {含花括号}</think>记得呀，蓝莓。"

    cases = load_cases(DATASET)[:2]
    transcript = tmp_path / "raw_llm.jsonl"
    judge_llm = FakeJudgeLLM()
    judge_llm.mode = "wrapped"
    harness = HumanenessHarness(
        _ThinkReplyLLM(), ExpertJudge(judge_llm), transcript_path=transcript,
    )
    records = harness.run(cases, [lambda: NullMemoryBase()])

    assert len(records) == 2
    assert transcript.is_file()
    items = [json.loads(l) for l in transcript.open(encoding="utf-8")]
    assert [x["kind"] for x in items].count("reply") == 2
    assert [x["kind"] for x in items].count("judge") == 2
    reply_raw = next(x for x in items if x["kind"] == "reply")
    assert "<think>" in reply_raw["raw"]  # 完整原文，未截断未剥离
    assert all("<think>" not in r.reply for r in records)  # 记录里是剥离后的


def test_rejudge_replays_from_transcript_without_llm(tmp_path):
    """重放：transcript 已有评委原文 → 0 次 LLM 调用；缺失 → 只补缺并落盘续跑。"""
    from evals.memory_humaneness.bases import NullMemoryBase
    from evals.memory_humaneness.judge import ExpertJudge
    from evals.memory_humaneness.rejudge import rejudge_run
    from evals.memory_humaneness.runner import HumanenessHarness

    cases = load_cases(DATASET)[:2]
    transcript = tmp_path / "raw_llm.jsonl"
    judge_llm = FakeJudgeLLM()
    judge_llm.mode = "wrapped"
    harness = HumanenessHarness(
        FakeReplyLLM(), ExpertJudge(judge_llm), transcript_path=transcript,
    )
    records = harness.run(cases, [lambda: NullMemoryBase()])
    (tmp_path / "records.jsonl").write_text(
        "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    counting = FakeJudgeLLM()
    counting.mode = "wrapped"
    calls = {"n": 0}
    orig = counting.generate_messages

    def _counting(messages):
        calls["n"] += 1
        return orig(messages)

    counting.generate_messages = _counting

    # 全量重放：0 次评委调用
    out = rejudge_run(ExpertJudge(counting), tmp_path, dataset=DATASET,
                      out_dir=tmp_path / "rej")
    assert calls["n"] == 0
    assert (tmp_path / "rej" / "report.md").is_file()

    # 删掉最后一条评委原文 → 只补调 1 次，且补的落盘（可续跑）
    lines = transcript.read_text(encoding="utf-8").splitlines()
    transcript.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    calls["n"] = 0
    rejudge_run(ExpertJudge(counting), tmp_path, dataset=DATASET,
                out_dir=tmp_path / "rej2")
    assert calls["n"] == 1
    assert (tmp_path / "rej2" / "raw_llm.jsonl").is_file()

    # 再跑一次：上一轮补的已落盘 → 0 次调用（断点续跑语义）
    calls["n"] = 0
    rejudge_run(ExpertJudge(counting), tmp_path, dataset=DATASET,
                out_dir=tmp_path / "rej2")
    assert calls["n"] == 0


def test_rejudge_refix_fallback_recalls_and_resumes(tmp_path):
    """--refix-judge：降级记录补调评委；中断续跑不重复补调。"""
    import json as _json

    from evals.memory_humaneness.bases import NullMemoryBase
    from evals.memory_humaneness.judge import ExpertJudge
    from evals.memory_humaneness.rejudge import rejudge_run
    from evals.memory_humaneness.runner import HumanenessHarness

    cases = load_cases(DATASET)[:2]
    transcript = tmp_path / "raw_llm.jsonl"

    # 造一个"评委被截断降级"的 run：wrapped 评委输出改为纯截断 think
    class _TruncatedJudgeLLM:
        def generate_messages(self, messages):
            return "<think>评分中…预算耗尽被截断，没有 JSON"

    harness = HumanenessHarness(
        FakeReplyLLM(), ExpertJudge(_TruncatedJudgeLLM()), transcript_path=transcript,
    )
    records = harness.run(cases, [lambda: NullMemoryBase()])
    assert all(r.judge["judge"] == "heuristic" for r in records)  # 全降级
    (tmp_path / "records.jsonl").write_text(
        "\n".join(_json.dumps(r.to_dict(), ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    # 好评委：补调 2 次，transcript 落盘
    good = FakeJudgeLLM()
    good.mode = "wrapped"
    counting = _CountingWrap(good)
    rejudge_run(ExpertJudge(counting), tmp_path, dataset=DATASET,
                out_dir=tmp_path / "rej", refix_fallback=True)
    assert counting.calls == 2
    out_transcript = tmp_path / "rej" / "raw_llm.jsonl"
    assert out_transcript.is_file()

    # 断点续跑：新原文已在本输出目录 → 不再补调
    counting.calls = 0
    rejudge_run(ExpertJudge(counting), tmp_path, dataset=DATASET,
                out_dir=tmp_path / "rej", refix_fallback=True)
    assert counting.calls == 0


class _CountingWrap:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def generate_messages(self, messages):
        self.calls += 1
        return self.inner.generate_messages(messages)


# ── 三基座协议 ────────────────────────────────────────────────────────────

def _base_factories():
    from agent.soul.memory.ports import MemoryBasePort
    from evals.memory_humaneness.bases import StackMemoryBase

    stack = StackMemoryBase.build(jsonl_path=str(tmp_factory() / "s.jsonl"))

    class _None:
        kind = "none"
        def ingest(self, text, **kw):
            return ""
        def recall(self, query, top_k=5, emotional_context=""):
            from agent.soul.memory.graph.networks.block import MemoryBlock
            return MemoryBlock(label="记忆", entries=[])
        def search(self, mode, **kw):
            return []
        def dispose(self):
            pass

    null = _None()
    assert isinstance(stack.service, type(stack.service))  # sanity
    from agent.soul.memory.bypass import StackMemoryService
    assert isinstance(stack.service, StackMemoryService)
    assert isinstance(stack.service, MemoryBasePort)
    return stack, null


def tmp_factory():
    import tempfile
    return Path(tempfile.mkdtemp(prefix="mh_test_"))


def test_stack_and_none_bases_conform_to_protocol():
    from agent.soul.memory.ports import MemoryBasePort

    stack, null = _base_factories()
    assert isinstance(stack, MemoryBasePort) or hasattr(stack, "recall")  # 包装器鸭子满足
    for base in (stack, null):
        uid = base.ingest("一条测试记忆", focus="测试", days_ago=2)
        assert isinstance(uid, str)
        block = base.recall("测试记忆", top_k=3)
        assert hasattr(block, "entries")
        assert isinstance(base.search("recent", limit=2), list)
        base.dispose()


def test_full_base_injects_everything_verbatim():
    from evals.memory_humaneness.bases import FullMemoryBase

    base = FullMemoryBase()
    base.ingest("第一条关于橘猫蓝莓的记忆", days_ago=3)
    base.ingest("第二条关于晋升答辩的记忆", days_ago=1)
    block = base.recall("完全无关的查询量子物理", top_k=5)  # 查询不影响输出
    assert len(block.entries) == 2
    assert all("橘猫蓝莓" in e or "晋升答辩" in e for e in block.entries)
    assert "量子物理" not in block.render()


def test_compact_base_compresses_old_keeps_recent():
    from evals.memory_humaneness.bases import CompactMemoryBase

    base = CompactMemoryBase(keep_recent=1, digest_chars=12)
    base.ingest("很早以前发生的第甲条比较长的记忆内容在这里", days_ago=30)
    base.ingest("中间的第乙条记忆内容也不短需要被压缩掉", days_ago=10)
    base.ingest("最近刚发生的第丙条记忆", days_ago=1)
    block = base.recall("随便什么查询", top_k=5)
    assert len(block.entries) == 3
    assert block.entries[0].startswith("[已压缩]")
    assert block.entries[1].startswith("[已压缩]")
    assert len(block.entries[0]) <= 12 + len("[已压缩] ") + 1  # 摘要被截断
    assert block.entries[2].startswith("[近期]")
    assert "最近刚发生的第丙条记忆" in block.entries[2]
    # 压缩是查询无关的：同查询不同查询输出一致
    assert base.recall("另一个查询").entries == block.entries


# ── L2 检索指标 ───────────────────────────────────────────────────────────

def test_retrieval_metrics_synthetic():
    from evals.memory_humaneness.retrieval_bench import evaluate_base
    from evals.memory_humaneness.schema import HumanenessCase, MemorySeed

    class _FakeRetrieval:
        kind = "fake"

        def __init__(self, lines_by_query):
            self.lines_by_query = lines_by_query
            self.preloaded = 0

        def ingest(self, text, **kwargs):
            self.preloaded += 1
            return f"fake-{self.preloaded}"

        def recall(self, query, top_k=5, emotional_context=""):
            from agent.soul.memory.graph.networks.block import MemoryBlock
            return MemoryBlock(label="x", entries=self.lines_by_query.get(query, [])[:top_k])

    hit_case = HumanenessCase(
        case_id="c1", category="event_recall", current_user="蓝莓那只猫怎么样",
        memories=[MemorySeed(text="用户养了叫蓝莓的橘猫", focus="蓝莓")],
        must_remember=["蓝莓"],
    )
    empty_case = HumanenessCase(
        case_id="c2", category="graceful_absence", current_user="我大学室友叫什么",
        memories=[], must_remember=[],
    )

    base = _FakeRetrieval({
        "蓝莓那只猫怎么样": ["[x] 别的：无关内容", "[x] 蓝莓：命中行"],
        "我大学室友叫什么": ["[x] 不该出现的记忆"],
    })
    result = evaluate_base(base, [hit_case, empty_case], top_k=2)
    m = result["metrics"]
    assert m["hit_at_k"] == 1.0           # 第 2 行才命中
    assert m["mrr"] == 0.5
    assert m["seed_recall"] == 1.0
    assert m["false_positive_rate"] == 1.0  # 负样本不该返回东西

    miss_result = evaluate_base(_FakeRetrieval({"蓝莓那只猫怎么样": []}), [hit_case], top_k=2)
    assert miss_result["metrics"]["hit_at_k"] == 0.0
    assert len(miss_result["misses"]) == 1


# ── harness 端到端（mock LLM + 启发式评判）────────────────────────────────

def test_harness_end_to_end_and_report(tmp_path):
    cases = load_cases(DATASET)[:6]

    def stack_factory():
        from evals.memory_humaneness.bases import StackMemoryBase
        return StackMemoryBase.build(jsonl_path=str(tmp_path / "stack.jsonl"))

    def compact_factory():
        from evals.memory_humaneness.bases import CompactMemoryBase
        return CompactMemoryBase()

    def full_factory():
        from evals.memory_humaneness.bases import FullMemoryBase
        return FullMemoryBase()

    def none_factory():
        from evals.memory_humaneness.bases import NullMemoryBase
        return NullMemoryBase()

    llm_cover = FakeReplyLLM(cover_anchors=True)
    harness = HumanenessHarness(llm_cover, HeuristicJudge(), recall_top_k=5)
    records = harness.run(cases, [stack_factory, compact_factory, full_factory, none_factory])
    assert len(records) == 6 * 4
    for r in records:
        assert r.error == "", r.error
        assert 1.0 <= r.judge["scores"]["overall"] <= 5.0

    # stack 有记忆时命中锚点 → memory_coherence 应普遍高于 none 对照
    agg = aggregate(records)
    assert agg["stack"]["dimensions"]["memory_coherence"] > 0
    # full 基座信息全量在场，锚点覆盖不应低于 none
    assert agg["full"]["dimensions"]["memory_coherence"] >= agg["none"]["dimensions"]["memory_coherence"]

    report = write_report(records, tmp_path / "out", meta={"cases": 6})
    assert report.is_file()
    assert (tmp_path / "out" / "summary.json").is_file()
    assert (tmp_path / "out" / "records.jsonl").is_file()
    md = report.read_text(encoding="utf-8")
    assert "记忆基座拟人化对比报告" in md
    for kind in ("stack", "compact", "full", "none"):
        assert kind in md


def test_retrieval_bench_on_real_bases():
    """真实基座检索冒烟：用例按设计应命中，负样本应保持安静（重导入，跑得慢）。"""
    from evals.memory_humaneness.bases import GraphMemoryBase, StackMemoryBase
    from evals.memory_humaneness.retrieval_bench import evaluate_base

    cases = load_cases(DATASET)[:8]  # 前 8 条均为 event_recall 单记忆用例

    for factory in (
        lambda: StackMemoryBase.build(jsonl_path=str(tmp_factory() / "rb.jsonl")),
        lambda: GraphMemoryBase.build(),
    ):
        # 传工厂：每条用例全新基座，防止用例间记忆互相污染
        result = evaluate_base(factory, cases, top_k=5)
        m = result["metrics"]
        assert m["hit_at_k"] == 1.0, (m["base"], result["misses"][:3])
        assert m["seed_recall"] == 1.0
        assert m["false_positive_rate"] == 0.0
