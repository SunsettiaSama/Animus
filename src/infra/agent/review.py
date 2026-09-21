"""工具调用格式审查：parse 之后、执行之前的兜底闸门；违规整批拦截。

与 parse-error 路径同构：审查不过不执行，纠错文本作为 observation 回写，
由模型在下一步自行修正（消耗一步）。
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

_FUZZY_CUTOFF = 0.6


@dataclass
class CallReviewResult:
    ok: bool
    issues: list[str] = field(default_factory=list)
    # ok=False 时可直接回写时间线的纠错 observation 文本；ok=True 恒为空串。
    correction: str = ""


@runtime_checkable
class CallReview(Protocol):
    """审查一批待执行的工具调用；只读，不改写 calls。"""

    def review(self, calls: list[dict]) -> CallReviewResult:
        ...


ToolNamesSource = frozenset[str] | Callable[[], frozenset[str]]


class WhitelistCallReview:
    """按工具名白名单审查 T/A 调用。

    未知工具给出显式模糊纠正建议（告知模型、由模型决定），不做静默替换；
    白名单为空时退化为纯结构检查（args 必须为 dict），不误拦。
    """

    def __init__(self, tool_names: ToolNamesSource, *, fuzzy_suggest: bool = True) -> None:
        self._tool_names = tool_names
        self._fuzzy_suggest = fuzzy_suggest

    def _names(self) -> frozenset[str]:
        try:
            raw = self._tool_names() if callable(self._tool_names) else self._tool_names
            return frozenset(raw)
        except Exception:
            return frozenset()

    def review(self, calls: list[dict]) -> CallReviewResult:
        names = self._names()
        issues: list[str] = []
        for call in calls or []:
            action = str(call.get("action") or "").strip()
            args = call.get("args")
            if not action:
                issues.append("存在 action 为空的调用")
                continue
            if names and action not in names:
                issues.append(self._unknown_tool_issue(action, names))
            if args is not None and not isinstance(args, dict):
                issues.append(
                    f"工具 {action!r} 的 args 必须是对象/dict，实际为 "
                    f"{type(args).__name__}"
                )
        if not issues:
            return CallReviewResult(ok=True)
        return CallReviewResult(ok=False, issues=issues, correction=self._correction(issues, names))

    def _unknown_tool_issue(self, action: str, names: frozenset[str]) -> str:
        issue = f"未知工具: {action!r}"
        if self._fuzzy_suggest and names:
            match = difflib.get_close_matches(
                action, sorted(names), n=1, cutoff=_FUZZY_CUTOFF
            )
            if match:
                issue += (
                    f"（你是否想用 {match[0]!r}？请使用修正后的名称重新发起，"
                    "不要自行发明工具）"
                )
        return issue

    def _correction(self, issues: list[str], names: frozenset[str]) -> str:
        available = (
            f"Available tools / 可用工具: {sorted(names)}" if names else "（当前未提供工具清单 / no tool catalog provided）"
        )
        listed = "\n".join(f"- {issue}" for issue in issues)
        return (
            "[SYSTEM FORMAT REVIEW] The tool-call batch failed review and was "
            "NOT executed.\n"
            "[系统格式审查] 上一批工具调用未通过审查，已整批拦截、均未执行：\n"
            f"{listed}\n"
            f"{available}\n"
            "请只用可用工具重新发起调用，格式：\n"
            '<A>[{"action": "工具名", "args": {...}}]</A>'
        )
