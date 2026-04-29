from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.skill.base import BaseSkill

# Matches double-quoted strings (handles simple escapes like \")
_RE_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
# Strips leading bullets, numbers and punctuation from list lines
_RE_BULLET = re.compile(r'^[\s•\-*0-9.、]+')


class DomainLearningArgs(BaseModel):
    goal: str = Field(..., min_length=1, description="学习目标，例如「量子计算基础」")
    max_concepts: int = Field(6, ge=1, le=12, description="最多拆解的核心概念数，默认 6")
    max_iter: int = Field(2, ge=1, le=4, description="最大迭代轮次（补漏），默认 2")


class DomainLearningSkill(BaseSkill):
    """
    五阶段领域学习技能：
    Phase 1 — LLM 拆解目标为概念列表
    Phase 2 — 检查已知边界（knowledge_list）
    Phase 3 — 研究循环（web_search → web_fetch → LLM 提炼 → knowledge_save）
    Phase 4 — 跨概念综合（LLM）
    Phase 5 — 识别剩余空白，若未达 max_iter 则回 Phase 2
    """

    name: str = "domain_learning"
    description: str = (
        "系统性学习某个领域或主题，自动分解概念、检索资料、提炼知识并保存。"
        "参数：goal（学习目标），max_concepts（最多概念数，默认 6），max_iter（迭代轮次，默认 2）"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = DomainLearningArgs

    llm: Any = None         # LLM 实例
    kb: Any = None          # KnowledgeBase 实例
    web_search: Any = None  # WebSearchAction 实例
    web_fetch: Any = None   # WebFetchAction 实例

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _llm_ask(self, prompt: str) -> str:
        return self.llm.generate(prompt)

    def _parse_json_list(self, text: str) -> list[str]:
        """Extract a JSON string array from LLM output; fall back to line splitting."""
        start = text.find("[")
        end   = text.rfind("]") + 1
        if start != -1 and end > start:
            # Use regex to pull quoted strings — avoids json.loads on untrusted input
            items = _RE_QUOTED.findall(text[start:end])
            if items:
                return [s for s in items if s.strip()]
        # Fallback: split lines, strip bullets / numbering
        return [
            _RE_BULLET.sub("", line).strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("{")
        ]

    # ── Phase implementations ─────────────────────────────────────────────────

    def _phase1_decompose(self, goal: str, max_concepts: int) -> list[str]:
        prompt = (
            f"将学习目标「{goal}」拆解为最多 {max_concepts} 个核心概念。"
            "每个概念是一个简短的名词短语。"
            "只返回 JSON 数组格式，例如：[\"概念1\", \"概念2\"]"
        )
        raw = self._llm_ask(prompt)
        concepts = self._parse_json_list(raw)
        return concepts[:max_concepts]

    def _phase2_known_gap(self, goal: str, concepts: list[str]) -> tuple[list[str], list[str]]:
        known_set: set[str] = set()
        if self.kb is not None:
            rows = self.kb.store.list_by_domain(goal, limit=100)
            for r in rows:
                c = r.get("concept", "")
                if c:
                    known_set.add(c.lower())

        known = [c for c in concepts if c.lower() in known_set]
        gap = [c for c in concepts if c.lower() not in known_set]
        return known, gap

    def _phase3_research(self, goal: str, gap_concepts: list[str], log: list[str]) -> int:
        saved = 0
        for concept in gap_concepts:
            query = f"{concept} {goal}"
            urls: list[str] = []

            if self.web_search is not None:
                search_result = self.web_search.execute(query=query, max_results=3)
                for line in search_result.splitlines():
                    if line.strip().startswith("URL:"):
                        url = line.strip()[4:].strip()
                        if url:
                            urls.append(url)

            contents: list[str] = []
            for url in urls[:3]:
                if self.web_fetch is not None:
                    page = self.web_fetch.execute(url=url, max_chars=3000)
                    contents.append(page)

            raw_content = "\n\n---\n\n".join(contents) if contents else f"（未能获取「{concept}」的网络资料）"

            extract_prompt = (
                f"从以下内容中提炼关于「{concept}」（领域：{goal}）的关键知识点。\n"
                "返回 JSON 格式：{\"fact\": \"核心内容描述\", \"confidence\": 0.0~1.0}\n\n"
                f"内容：\n{raw_content[:4000]}"
            )
            extracted = self._llm_ask(extract_prompt)

            fact = extracted
            confidence = 0.8
            start = extracted.find("{")
            end = extracted.rfind("}") + 1
            if start != -1 and end > start:
                snippet = extracted[start:end]
                # Extract "fact" value: first quoted string after "fact":
                fact_m = re.search(r'"fact"\s*:\s*"((?:[^"\\]|\\.)*)"', snippet)
                if fact_m:
                    fact = fact_m.group(1)
                # Extract "confidence" value: number after "confidence":
                conf_m = re.search(r'"confidence"\s*:\s*([0-9.]+)', snippet)
                if conf_m:
                    confidence = min(1.0, max(0.0, float(conf_m.group(1))))

            if self.kb is not None:
                self.kb.ingest_text(
                    fact,
                    source="agent_learning",
                    source_type="agent_learning",
                    title=f"{goal}/{concept}",
                    meta={
                        "domain": goal,
                        "concept": concept,
                        "sources": urls,
                        "confidence": confidence,
                    },
                )
                saved += 1
                log.append(f"已保存概念「{concept}」")

        return saved

    def _phase4_synthesize(self, goal: str, concepts: list[str]) -> str:
        prompt = (
            f"基于以下概念，综合总结领域「{goal}」的核心知识，并指出各概念之间的联系。\n"
            f"概念列表：{', '.join(concepts)}\n\n"
            "请用 2~4 段话说明，语言简洁清晰。"
        )
        return self._llm_ask(prompt)

    def _phase5_gaps(self, goal: str, covered: list[str]) -> list[str]:
        prompt = (
            f"关于领域「{goal}」，以下概念已被覆盖：{', '.join(covered)}。\n"
            "还有哪些重要方面尚未被覆盖？"
            "只返回 JSON 数组格式的概念列表，最多 4 个，例如：[\"概念A\", \"概念B\"]。"
            "若已足够完整，返回空数组 []。"
        )
        raw = self._llm_ask(prompt)
        return self._parse_json_list(raw)[:4]

    # ── Main execute ──────────────────────────────────────────────────────────

    def execute(self, goal: str, max_concepts: int = 6, max_iter: int = 2, **kwargs) -> str:
        log: list[str] = []
        all_saved = 0
        all_covered: list[str] = []

        concepts = self._phase1_decompose(goal, max_concepts)
        log.append(f"Phase 1 — 拆解出 {len(concepts)} 个概念：{', '.join(concepts)}")

        current_concepts = concepts

        for iteration in range(max_iter):
            known, gap = self._phase2_known_gap(goal, current_concepts)
            log.append(f"Phase 2 [轮 {iteration + 1}] — 已知: {known or '无'}，空白: {gap or '无'}")

            if not gap:
                log.append("所有概念已覆盖，提前完成。")
                break

            saved = self._phase3_research(goal, gap, log)
            all_saved += saved
            all_covered.extend(gap)

            if iteration < max_iter - 1:
                remaining_gaps = self._phase5_gaps(goal, concepts + all_covered)
                log.append(f"Phase 5 [轮 {iteration + 1}] — 识别到新空白: {remaining_gaps or '无'}")
                if not remaining_gaps:
                    break
                current_concepts = remaining_gaps
            else:
                break

        synthesis = self._phase4_synthesize(goal, concepts)

        final_gaps = self._phase5_gaps(goal, concepts + all_covered) if all_covered else []

        report_parts = [
            f"## 领域学习报告：{goal}",
            f"\n### 概念覆盖（共 {len(concepts)} 个）",
            "- " + "\n- ".join(concepts),
            f"\n### 新增知识条目：{all_saved} 条",
            "\n### 综合摘要",
            synthesis,
        ]
        if final_gaps:
            report_parts.append("\n### 剩余空白")
            report_parts.append("- " + "\n- ".join(final_gaps))
        else:
            report_parts.append("\n### 剩余空白：无（覆盖完整）")

        report_parts.append("\n### 执行日志")
        report_parts.append("\n".join(f"  {line}" for line in log))

        return "\n".join(report_parts)
