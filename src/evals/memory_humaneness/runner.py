"""3.3 对比 harness：同一批用例 × 多个记忆基座 → 回复 + 评测记录。

日志约定（logger ``evals.memory_humaneness``）：
- INFO：每条用例×基座的结果行（命中数/评分/耗时）、阶段开始结束、滚动均值；
- DEBUG：检索命中的记忆行、回复全文、评审理由；
- WARNING：单条失败与评审降级（不中断 run，但一定可见）。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .bases import preload
from .judge import JudgeVerdict, strip_reasoning  # noqa: F401  (strip_reasoning 再导出供测试)
from .prompt import compose_human, compose_system
from .schema import HumanenessCase

log = logging.getLogger("evals.memory_humaneness")


@dataclass
class CaseRecord:
    case_id: str
    category: str
    base: str
    reply: str
    memory_lines: list[str] = field(default_factory=list)
    judge: dict = field(default_factory=dict)
    elapsed_sec: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class HumanenessHarness:
    """对每个 (case, base) 组合：预载记忆 → 检索 → 组装 prompt → LLM 回复 → 评判。

    ``transcript_path`` 给出时，每次 LLM 原始输出（回复/评委）在**解析之前**
    逐条追加落盘（``{"kind", "case_id", "base", "raw"}``）——先保存再解析，
    之后任何解析 bug 只需离线重放修复，无需重烧 API。
    """

    def __init__(
        self,
        llm: Any,
        judge: Any,
        *,
        recall_top_k: int = 5,
        transcript_path: str | Path | None = None,
        query_rewriter=None,
    ) -> None:
        self._llm = llm
        self._judge = judge
        self._recall_top_k = recall_top_k
        self._transcript_path = Path(transcript_path) if transcript_path else None
        self._query_rewriter = query_rewriter
        # LLM 调用计数（进度行按调用计价，不再只报组合数）
        self.gen_calls = 0
        self.judge_calls = 0

    @property
    def _judge_is_llm(self) -> bool:
        return getattr(self._judge, "name", "") == "llm_expert"

    def _save_raw(self, kind: str, case_id: str, base: str, raw: str) -> None:
        if not self._transcript_path or not raw:
            return
        self._transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with self._transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"kind": kind, "case_id": case_id, "base": base, "raw": raw},
                ensure_ascii=False,
            ))
            fh.write("\n")

    def run_case(self, case: HumanenessCase, base) -> CaseRecord:
        t0 = time.perf_counter()
        kind = getattr(base, "kind", "?")
        log.debug("── %s × %s 开始（预载 %d 条记忆）", case.case_id, kind, len(case.memories))
        try:
            preload(base, case.memories)
            query = self._recall_query(case)
            if self._query_rewriter is not None:
                query = self._query_rewriter.rewrite(query).query
            block = base.recall(query, top_k=self._recall_top_k)
            memory_lines = list(block.entries or [])
            log.debug(
                "%s × %s 检索命中 %d/%d：%s",
                case.case_id, kind, len(memory_lines), self._recall_top_k,
                " | ".join(line[:40] for line in memory_lines) or "（无）",
            )
            system = compose_system(case, block.render())
            human = compose_human(case)
            raw_reply = self._llm.generate_messages(_messages(system, human))
            self.gen_calls += 1
            self._save_raw("reply", case.case_id, kind, raw_reply)  # 先保存，再解析
            reply = strip_reasoning(raw_reply)
            if not reply:
                raise ValueError("回复剥离思维链后为空（模型只输出了推理过程）")
            verdict = self._judge.judge(case, memory_lines, reply)
            if self._judge_is_llm:
                self.judge_calls += 1
            self._save_raw("judge", case.case_id, kind, verdict.raw)
            elapsed = time.perf_counter() - t0
            record = CaseRecord(
                case_id=case.case_id,
                category=case.category,
                base=kind,
                reply=reply,
                memory_lines=memory_lines,
                judge=verdict.to_dict(),
                elapsed_sec=round(elapsed, 3),
            )
            overall = record.judge.get("scores", {}).get("overall", 0.0)
            log.info(
                "%s [%s] × %s → overall=%.1f  reply %d 字  (检索+回复+评判 %.1fs)",
                case.case_id, case.category, kind, overall, len(reply), elapsed,
            )
            log.debug(
                "%s × %s 回复：%s\n   评审（%s）：%s",
                case.case_id, kind, reply, verdict.judge, verdict.rationale,
            )
            return record
        except Exception as exc:  # 单条失败不拖垮整个 run
            elapsed = time.perf_counter() - t0
            log.warning(
                "%s × %s 失败（%.1fs）：%s: %s",
                case.case_id, kind, elapsed, type(exc).__name__, exc,
            )
            return CaseRecord(
                case_id=case.case_id,
                category=case.category,
                base=kind,
                reply="",
                elapsed_sec=round(elapsed, 3),
                error=f"{type(exc).__name__}: {exc}",
            )

    def run(
        self,
        cases: list[HumanenessCase],
        base_factories: list,
        *,
        progress_every: int = 10,
    ) -> list[CaseRecord]:
        """每条用例 × 每个基座工厂：实例化全新基座（用例间记忆互不污染）。

        ``base_factories`` 为 ``Callable[[], base]`` 列表，如
        ``[lambda: GraphMemoryBase.build(), lambda: StackMemoryBase.build(), NullMemoryBase]``。
        """
        total = len(cases) * max(1, len(base_factories))
        calls_per_combo = 1 + (1 if self._judge_is_llm else 0)
        est_total_calls = total * calls_per_combo
        log.info(
            "run 开始：%d 用例 × %d 基座 = %d 组合 = 约 %d 次 LLM 调用"
            "（回复 %d%s，judge=%s）",
            len(cases), len(base_factories), total, est_total_calls,
            total, " + 评判 %d" % total if self._judge_is_llm else "",
            getattr(self._judge, "name", "?"),
        )
        t0 = time.perf_counter()
        records: list[CaseRecord] = []
        for ci, case in enumerate(cases, 1):
            for factory in base_factories:
                base = factory()
                record = self.run_case(case, base)
                dispose = getattr(base, "dispose", None)
                if callable(dispose):
                    dispose()
                records.append(record)
            done = ci * len(base_factories)
            if progress_every > 0 and done % progress_every == 0:
                self._log_running(
                    records, done, total, time.perf_counter() - t0,
                    calls_used=self.gen_calls + self.judge_calls,
                )
        self._log_summary(records, time.perf_counter() - t0)
        return records

    @staticmethod
    def _log_running(
        records: list[CaseRecord],
        done: int,
        total: int,
        wall: float,
        *,
        calls_used: int = 0,
    ) -> None:
        ok = [r for r in records if not r.error]
        errs = len(records) - len(ok)
        by_base: dict[str, list[float]] = {}
        for r in ok:
            v = r.judge.get("scores", {}).get("overall")
            if v is not None:
                by_base.setdefault(r.base, []).append(v)
        means = "  ".join(
            f"{base}={sum(v) / len(v):.2f}(n={len(v)})" for base, v in sorted(by_base.items())
        )
        rate = done / wall if wall > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else 0.0
        log.info(
            "进度 %d/%d 组合（错误 %d）｜LLM 已用 %d 次｜滚动 overall：%s"
            "｜%.1f 组合/分，预计剩余 %.0f 分钟",
            done, total, errs, calls_used, means or "-", rate * 60, eta / 60,
        )

    def _log_summary(self, records: list[CaseRecord], wall: float) -> None:
        ok = [r for r in records if not r.error]
        log.info(
            "run 结束：%d/%d 成功，错误 %d，墙钟 %.1fs｜LLM 调用合计 %d 次"
            "（生成 %d + 评判 %d）",
            len(ok), len(records), len(records) - len(ok), wall,
            self.gen_calls + self.judge_calls, self.gen_calls, self.judge_calls,
        )

    @staticmethod
    def _recall_query(case: HumanenessCase) -> str:
        # 检索 query = 历史 + 当前输入（含指代线索）
        parts = [t.text for t in case.history] + [case.current_user]
        return " ".join(p for p in parts if p.strip())


def _messages(system: str, human: str):
    from langchain_core.messages import HumanMessage, SystemMessage

    return [SystemMessage(content=system), HumanMessage(content=human)]
