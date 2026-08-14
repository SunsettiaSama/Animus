from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    passed  = "passed"
    warning = "warning"   # 产出物部分满足 output_contract
    failed  = "failed"    # 产出物不符合预期或为空


class CheckKind(str, Enum):
    abstract = "abstract"   # 结构 / 类型检查（output_contract 声明的形态是否满足）
    concrete = "concrete"   # 内容 / 语义检查（实际值是否合理、完整）


@dataclass(frozen=True)
class VerificationCheck:
    """单项检查结果。"""
    name: str
    passed: bool
    kind: CheckKind = CheckKind.abstract
    detail: str = ""


@dataclass
class VerificationResult:
    """节点输出的完整校验报告。

    生命周期
    --------
    · NodeVerifier.verify() 生成本对象。
    · RunnableNode.run() 将其挂载到 NodeResult.verification。
    · NodeObservation.to_planner_context() 将 report 字段嵌入 Planner 可读文本。
    · NodeDocumentWriter.write() 将其（连同 NodeResult）写入持久化文档。

    字段说明
    --------
    status          整体判定：passed / warning / failed。
    verdict         一句话结论，供 Planner 快速阅读。
    checks          逐项检查明细（abstract + concrete）。
    report          格式化多行报告，嵌入 NodeObservation 传给 Planner。
    corrections     verifier 发现的具体问题，以自然语言指令形式写给 executor 重跑时使用。
                    非空时 RunnableNode 自动触发纠错循环（executor 重跑一次）。
    log_entries     按时序追加的日志行，供文档写入器持久化。
    """

    status: VerificationStatus
    verdict: str
    checks: list[VerificationCheck]
    report: str
    corrections: list[str] = field(default_factory=list)
    log_entries: list[str] = field(default_factory=list)

    # ── 工厂方法 ──────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        checks: list[VerificationCheck],
        extra_note: str = "",
    ) -> "VerificationResult":
        """从 checks 列表推导整体状态并生成报告。

        规则
        ----
        · 所有 abstract 检查通过 AND 所有 concrete 检查通过 → passed
        · abstract 全通过但有 concrete 警告              → warning
        · 任意 abstract 检查失败                        → failed
        """
        abstract_checks = [c for c in checks if c.kind == CheckKind.abstract]
        concrete_checks  = [c for c in checks if c.kind == CheckKind.concrete]

        abstract_ok = all(c.passed for c in abstract_checks)
        concrete_ok  = all(c.passed for c in concrete_checks)

        if not abstract_ok:
            status = VerificationStatus.failed
        elif not concrete_ok:
            status = VerificationStatus.warning
        else:
            status = VerificationStatus.passed

        passed_n = sum(1 for c in checks if c.passed)
        verdict = (
            f"[{status.value.upper()}] {passed_n}/{len(checks)} checks passed"
            + (f" — {extra_note}" if extra_note else "")
        )

        report = cls._format_report(status, verdict, checks, extra_note)
        log_entries = [
            f"[{c.kind.value}][{'OK' if c.passed else 'FAIL'}] {c.name}: {c.detail}"
            for c in checks
        ]

        # concrete 失败的检查项 → 生成给 executor 的纠错指令
        corrections = [
            f"Fix '{c.name}': {c.detail}" if c.detail else f"Fix '{c.name}'"
            for c in concrete_checks
            if not c.passed
        ]

        return cls(
            status=status,
            verdict=verdict,
            checks=checks,
            report=report,
            corrections=corrections,
            log_entries=log_entries,
        )

    @classmethod
    def skip(cls, reason: str = "no verifier configured") -> "VerificationResult":
        """当没有 Verifier 时生成一个占位结果，不影响节点状态。"""
        return cls(
            status=VerificationStatus.passed,
            verdict=f"[SKIPPED] {reason}",
            checks=[],
            report=f"Verification skipped: {reason}",
        )

    # ── 格式化 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_report(
        status: VerificationStatus,
        verdict: str,
        checks: list[VerificationCheck],
        extra_note: str,
    ) -> str:
        _status_icon = {"passed": "[OK]", "warning": "[WARN]", "failed": "[FAIL]"}
        icon = _status_icon.get(status.value, "[?]")

        lines = [
            f"+-- Verification Report {icon}",
            f"|   {verdict}",
        ]

        abstract_checks = [c for c in checks if c.kind == CheckKind.abstract]
        concrete_checks  = [c for c in checks if c.kind == CheckKind.concrete]

        if abstract_checks:
            lines.append("|   Abstract checks (structure / type):")
            for c in abstract_checks:
                mark = "[OK]" if c.passed else "[FAIL]"
                lines.append(f"|     {mark} {c.name}" + (f": {c.detail}" if c.detail else ""))

        if concrete_checks:
            lines.append("|   Concrete checks (content / semantics):")
            for c in concrete_checks:
                mark = "[OK]" if c.passed else "[WARN]"
                lines.append(f"|     {mark} {c.name}" + (f": {c.detail}" if c.detail else ""))

        if extra_note:
            lines.append(f"|   Note: {extra_note}")

        lines.append("+--")
        return "\n".join(lines)

    def to_planner_report(self) -> str:
        """精简单行报告，嵌入 NodeObservation 的 distilled 模式输出。"""
        failed = [c.name for c in self.checks if not c.passed]
        if failed:
            return f"{self.verdict} | failed: {', '.join(failed)}"
        return self.verdict

    def __bool__(self) -> bool:
        return self.status != VerificationStatus.failed
