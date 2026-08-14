from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeResult:
    """CodeOrchestrator.run_coding() 的结构化产出。

    plan_id    运行标识（来自 OrchestratorResult）。
    status     "done" | "abort" | "timeout"。
    goal       原始编码目标。
    artifacts  task_id → 生成的代码字符串；仅包含成功执行的节点。
    summary    Replanner 汇总的综合结论；abort 时为失败原因。
    """

    plan_id: str
    status: str
    goal: str
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: str = ""

    @classmethod
    def from_run(
        cls,
        plan_id: str,
        status: str,
        goal: str,
        outputs: dict[str, Any],
        conclusion: str,
    ) -> "CodeResult":
        artifacts = {
            nid: str(out)
            for nid, out in outputs.items()
            if out is not None and str(out).strip()
        }
        return cls(
            plan_id=plan_id,
            status=status,
            goal=goal,
            artifacts=artifacts,
            summary=conclusion,
        )

    def render(self) -> str:
        lines: list[str] = [
            f"# 代码生成结果",
            f"**目标**: {self.goal}",
            f"**状态**: {self.status}",
            f"**节点数**: {len(self.artifacts)}",
            "",
        ]
        for nid, code in self.artifacts.items():
            lines.append(f"## {nid}")
            lang = _guess_lang(code)
            lines.append(f"```{lang}")
            lines.append(code)
            lines.append("```")
            lines.append("")
        if self.summary:
            lines.append("## 综合结论")
            lines.append(self.summary)
        return "\n".join(lines)


def _guess_lang(code: str) -> str:
    stripped = code.lstrip()
    if stripped.startswith("import ") or "def " in code or "class " in code:
        return "python"
    if "function " in code or "const " in code or "=>" in code:
        return "typescript"
    if "public class" in code or "void " in code:
        return "java"
    if "#include" in code:
        return "cpp"
    return ""
