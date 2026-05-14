"""RunnableNode 真实用例测试。

场景：文本统计节点
  · 输入：list[str]
  · executor 执行三步 TAO 循环，产出词频统计
  · verifier 检查 output 结构，缺少 max_length 时触发纠错循环
  · doc_writer 异步写入结果

覆盖点
-------
  run()           完整流程 + 纠错循环
  review()        full / distilled 两种观察模式
  modify()        diff 注入与清除
  doc_writer      fire-and-forget 异步写入
  NodeRuntimeManager  单例生命周期（每个测试隔离）
"""
from __future__ import annotations

import threading
from typing import Any, Mapping

import pytest

from agent.flow.base.components import (
    CheckKind,
    NodeManifest,
    NodeObservation,
    NodeResult,
    ObservationMode,
    RunnableNode,
    VerificationCheck,
    VerificationResult,
)
from agent.flow.base.components.observation import TaoStep
from agent.flow.base.components.runtime import NodeExecutionContext
from infra.node_runtime import NodeRuntimeManager


# ── 测试隔离 ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_runtime():
    """每个测试前重置并配置 NodeRuntimeManager，测试后清理。"""
    NodeRuntimeManager.reset()
    NodeRuntimeManager.configure(executor_threads=2, verifier_threads=2, doc_threads=1)
    yield
    NodeRuntimeManager.reset()


# ── Stub 实现 ──────────────────────────────────────────────────────────────────

class TextStatsExecutor:
    """纯 Python executor，对输入文本列表计算字数统计。

    TAO 三步：
      Step 0 — Parse  : 解析输入，计算各文本词数
      Step 1 — Compute: 汇总 total / avg
      Step 2 — Format : 组装输出 dict

    纠错支持：若 ctx.corrections 中包含 "max_length"，
    额外计算并附加该字段（Step 2 变为 Augment）。
    """

    def run(
        self,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
        ctx: NodeExecutionContext | None = None,
    ) -> Any:
        texts: list[str] = inputs.get("texts", [])
        corrections: list[str] = ctx.corrections if ctx else []

        def emit(index: int, thought: str, action: str, action_input: Any, obs: str) -> None:
            if ctx and ctx.on_step:
                ctx.on_step(TaoStep(
                    index=index,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=obs,
                ))

        # Step 0: Parse
        word_counts = [len(t.split()) for t in texts]
        emit(0, "Parse each text into word tokens", "parse", texts,
             f"parsed {len(texts)} texts, counts={word_counts}")

        # Step 1: Compute
        total = sum(word_counts)
        avg = round(total / len(word_counts), 2) if word_counts else 0.0
        emit(1, "Aggregate word count statistics", "compute", word_counts,
             f"total={total}, avg={avg}")

        # Step 2: Format (or Augment if corrected)
        result: dict[str, Any] = {
            "total_words": total,
            "avg_length": avg,
            "count": len(texts),
        }
        if any("max_length" in c for c in corrections):
            result["max_length"] = max(word_counts) if word_counts else 0
            emit(2, "Add max_length field per verifier correction", "augment", result,
                 f"max_length={result['max_length']} added")
        else:
            emit(2, "Format final output dict", "format", result, "done")

        return result


class StrictVerifier:
    """校验 output 必须含 total_words / avg_length / count（abstract）。

    若缺少 max_length，产出 concrete 警告并附 correction 指令，
    触发 executor 的纠错循环。
    """

    def verify(
        self,
        manifest: NodeManifest,
        output: Any,
        observation: NodeObservation,
    ) -> VerificationResult:
        checks = [
            VerificationCheck(
                name="has_total_words",
                passed="total_words" in output,
                kind=CheckKind.abstract,
                detail="output must contain 'total_words'",
            ),
            VerificationCheck(
                name="has_avg_length",
                passed="avg_length" in output,
                kind=CheckKind.abstract,
                detail="output must contain 'avg_length'",
            ),
            VerificationCheck(
                name="has_count",
                passed="count" in output,
                kind=CheckKind.abstract,
                detail="output must contain 'count'",
            ),
            VerificationCheck(
                name="has_max_length",
                passed="max_length" in output,
                kind=CheckKind.concrete,
                detail="output should include max_length for completeness",
            ),
        ]
        return VerificationResult.build(checks)


class InMemoryDocWriter:
    """将 NodeResult 写入内存；write_event 在首次写入后 set。"""

    def __init__(self) -> None:
        self.records: list[tuple[NodeManifest, NodeResult]] = []
        self._lock = threading.Lock()
        self.write_event = threading.Event()

    def write(self, manifest: NodeManifest, result: NodeResult) -> None:
        with self._lock:
            self.records.append((manifest, result))
        self.write_event.set()


# ── 公共测试数据 ───────────────────────────────────────────────────────────────

_MANIFEST = NodeManifest(
    task_id="text_stats",
    description="Compute word count statistics from a list of texts.",
    input_contract="inputs['texts']: list[str]",
    output_contract="{'total_words': int, 'avg_length': float, 'count': int, 'max_length': int}",
    observation_mode=ObservationMode.distilled,
)

_INPUTS = {"texts": ["hello world", "foo bar baz", "one two three four"]}
# word counts:  2,             3,             4           → total=9, avg=3.0, max=4


# ── 测试：run() 基本流程 ───────────────────────────────────────────────────────

def test_run_returns_correct_output() -> None:
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    result = node.run(_INPUTS)

    assert result.task_id == "text_stats"
    assert result.output["total_words"] == 9
    assert result.output["avg_length"] == 3.0
    assert result.output["count"] == 3
    assert result.elapsed_seconds is not None and result.elapsed_seconds >= 0


def test_run_without_verifier_has_skip_verification() -> None:
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    result = node.run(_INPUTS)

    assert result.verification is not None
    assert "SKIPPED" in result.verification.verdict


# ── 测试：纠错循环 ────────────────────────────────────────────────────────────

def test_verifier_triggers_correction_loop() -> None:
    """StrictVerifier 检测到缺少 max_length → corrections 非空 → executor 重跑补充字段。"""
    node = RunnableNode(
        manifest=_MANIFEST,
        executor=TextStatsExecutor(),
        verifier=StrictVerifier(),
    )
    result = node.run(_INPUTS)

    # 纠错后 max_length 应出现
    assert "max_length" in result.output
    assert result.output["max_length"] == 4   # "one two three four" = 4 词

    # 第二轮校验：全部通过 → passed
    assert result.verification is not None
    assert result.verification.status.value == "passed"
    assert result.verification.corrections == []


def test_verifier_all_pass_no_correction() -> None:
    """输入中 max_length 已提前由 executor 提供时，不应触发纠错。"""
    class AlwaysPassVerifier:
        def verify(self, manifest, output, observation):
            return VerificationResult.build([
                VerificationCheck("always_ok", passed=True, kind=CheckKind.abstract),
            ])

    call_count = {"n": 0}

    class CountingExecutor:
        def run(self, manifest, inputs, ctx=None):
            call_count["n"] += 1
            return {"total_words": 1, "avg_length": 1.0, "count": 1}

    node = RunnableNode(
        manifest=_MANIFEST,
        executor=CountingExecutor(),
        verifier=AlwaysPassVerifier(),
    )
    node.run(_INPUTS)

    assert call_count["n"] == 1   # 没有纠错，executor 只跑一次


# ── 测试：log_entries ─────────────────────────────────────────────────────────

def test_log_entries_contain_executor_and_verifier_sources() -> None:
    node = RunnableNode(
        manifest=_MANIFEST,
        executor=TextStatsExecutor(),
        verifier=StrictVerifier(),
    )
    result = node.run(_INPUTS)

    sources = {e.source for e in result.log_entries}
    assert "executor" in sources
    assert "verifier" in sources


def test_log_entries_have_timestamps() -> None:
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    result = node.run(_INPUTS)

    for entry in result.log_entries:
        assert entry.timestamp.endswith("Z")
        assert "T" in entry.timestamp


# ── 测试：review() ────────────────────────────────────────────────────────────

def test_review_distilled_after_run() -> None:
    node = RunnableNode(
        manifest=_MANIFEST,
        executor=TextStatsExecutor(),
        verifier=StrictVerifier(),
    )
    node.run(_INPUTS)
    obs = node.review()

    assert obs.task_id == "text_stats"
    assert obs.mode == ObservationMode.distilled
    assert obs.step_count > 0
    assert obs.summary != ""
    assert obs.verification_report != ""


def test_review_full_mode_exposes_all_steps() -> None:
    """full 模式：返回 executor 执行的全部 TaoStep。"""
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    node.run(_INPUTS)
    obs = node.review(mode=ObservationMode.full)

    assert obs.mode == ObservationMode.full
    assert len(obs.steps) == 3     # parse, compute, format
    assert obs.steps[0].action == "parse"
    assert obs.steps[1].action == "compute"
    assert obs.steps[2].action == "format"


def test_review_before_run_returns_empty_observation() -> None:
    """run() 前调用 review()：步骤列表为空，summary 为空字符串。"""
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    obs = node.review()

    assert obs.step_count == 0
    assert obs.steps == []
    assert obs.summary == ""


def test_review_planner_context_format() -> None:
    """to_planner_context() 应输出可读文本，包含 task_id 和 summary。"""
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    node.run(_INPUTS)
    obs = node.review()

    ctx_text = obs.to_planner_context()
    assert "text_stats" in ctx_text
    assert "total_steps" in ctx_text


# ── 测试：modify() ────────────────────────────────────────────────────────────

def test_modify_diff_injected_into_executor_context() -> None:
    """modify() 后的第一次 run()，executor 能读到 manifest_diff。"""
    received: list[dict] = []

    class DiffCapture:
        def run(self, manifest, inputs, ctx=None):
            if ctx:
                received.append(dict(ctx.manifest_diff))
            return {"total_words": 1, "avg_length": 1.0, "count": 1}

    node = RunnableNode(manifest=_MANIFEST, executor=DiffCapture())
    node.modify(description="Updated description")
    node.run(_INPUTS)

    assert len(received) == 1
    assert "description" in received[0]
    before, after = received[0]["description"]
    assert before == _MANIFEST.description
    assert after == "Updated description"


def test_modify_diff_cleared_after_run() -> None:
    """run() 后 diff 清空，第二次 run() 不再注入旧 diff。"""
    received: list[dict] = []

    class DiffCapture:
        def run(self, manifest, inputs, ctx=None):
            if ctx:
                received.append(dict(ctx.manifest_diff))
            return {"total_words": 1, "avg_length": 1.0, "count": 1}

    node = RunnableNode(manifest=_MANIFEST, executor=DiffCapture())
    node.modify(description="Once")
    node.run(_INPUTS)   # 第一次：有 diff
    node.run(_INPUTS)   # 第二次：diff 应为空

    assert received[0] != {}
    assert received[1] == {}


def test_modify_updates_manifest() -> None:
    node = RunnableNode(manifest=_MANIFEST, executor=TextStatsExecutor())
    node.modify(system_note="Use concise output")

    assert node.manifest.system_note == "Use concise output"


# ── 测试：NodeDocumentWriter 异步写入 ─────────────────────────────────────────

def test_doc_writer_called_async() -> None:
    """NodeDocumentWriter.write() 应在 run() 返回后异步调用。"""
    writer = InMemoryDocWriter()
    node = RunnableNode(
        manifest=_MANIFEST,
        executor=TextStatsExecutor(),
        doc_writer=writer,
    )
    node.run(_INPUTS)

    # 等待 doc_pool 完成写入（最多 5 秒）
    assert writer.write_event.wait(timeout=5.0), "doc_writer.write() was not called"

    assert len(writer.records) == 1
    manifest_written, result_written = writer.records[0]
    assert manifest_written.task_id == "text_stats"
    assert result_written.output["total_words"] == 9


def test_doc_writer_receives_full_result() -> None:
    """doc_writer 写入的 NodeResult 应含 observation / verification / log_entries。"""
    writer = InMemoryDocWriter()
    node = RunnableNode(
        manifest=_MANIFEST,
        executor=TextStatsExecutor(),
        verifier=StrictVerifier(),
        doc_writer=writer,
    )
    node.run(_INPUTS)

    assert writer.write_event.wait(timeout=5.0)
    _, result = writer.records[0]

    assert result.observation is not None
    assert result.verification is not None
    assert len(result.log_entries) > 0
