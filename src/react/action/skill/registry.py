from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

from react.action.skill.base import BaseSkill


@dataclass
class SkillMeta:
    name: str
    description: str
    skill_type: str
    version: str
    action_cls: type[BaseSkill]
    tags: list[str] = field(default_factory=list)


class SkillRegistry:
    """
    技能注册表。

    技能与工具共享 BaseAction 基类，因此可以通过
    to_tool_entries() 无缝合并进 ToolRegistry，从而
    让 ToolManager.search() 和 tool_search 工具能发现它们。
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillMeta] = {}

    # --- 注册 ---

    def add(
        self,
        skill_cls: type[BaseSkill],
        tags: list[str] | None = None,
    ) -> type[BaseSkill]:
        fields = skill_cls.model_fields
        name = fields["name"].default
        desc = fields["description"].default
        skill_type = fields["skill_type"].default
        version = fields["version"].default
        self._skills[name] = SkillMeta(
            name=name,
            description=desc,
            skill_type=skill_type,
            version=version,
            action_cls=skill_cls,
            tags=tags or [],
        )
        return skill_cls

    # --- 查询 ---

    def get(self, name: str) -> SkillMeta | None:
        return self._skills.get(name)

    def all(self) -> list[SkillMeta]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def search(
        self,
        query: str,
        top_k: int = 5,
        exclude: list[str] | None = None,
    ) -> list[SkillMeta]:
        exclude_set = set(exclude or [])
        words = query.lower().split()
        scored: list[tuple[int, SkillMeta]] = []
        for meta in self._skills.values():
            if meta.name in exclude_set:
                continue
            corpus = " ".join([
                meta.name, meta.description,
                meta.skill_type, meta.version,
                *meta.tags, "skill",
            ]).lower()
            score = sum(1 for w in words if w in corpus)
            if score > 0:
                scored.append((score, meta))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    # --- 与 ToolRegistry 集成 ---

    def to_tool_entries(self) -> list[tuple[type[BaseSkill], str, list[str]]]:
        """
        返回可直接传入 ToolRegistry.add() 的三元组列表。

        category 固定为 'skill:<skill_type>'，tags 追加 'skill' 标签，
        确保 tool_search 通过 'skill' 关键词能命中技能。
        """
        return [
            (
                meta.action_cls,
                f"skill:{meta.skill_type}",
                meta.tags + ["skill", meta.skill_type, meta.version],
            )
            for meta in self._skills.values()
        ]

    # --- LangChain 接口 ---

    def as_langchain_tools(self) -> list[BaseTool]:
        return [meta.action_cls() for meta in self._skills.values()]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
