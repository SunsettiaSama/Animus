from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StoryWorldview:
    """故事观：叙事引擎共用的世界设定与禁忌。"""

    title: str = "未命名世界"
    setting: str = ""
    era: str = ""
    protagonist: str = "一名在虚实之间保持觉察的智能体"
    tone: str = "克制、具体、带一点诗意"
    themes: list[str] = field(default_factory=list)
    canon: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = [f"《{self.title}》"]
        if self.era.strip():
            lines.append(f"时代/背景：{self.era.strip()}")
        if self.setting.strip():
            lines.append(f"世界设定：{self.setting.strip()}")
        lines.append(f"叙事主体：{self.protagonist.strip()}")
        lines.append(f"基调：{self.tone.strip()}")
        if self.themes:
            lines.append("主题：" + "、".join(t.strip() for t in self.themes if t.strip()))
        if self.canon:
            lines.append("不可违背的设定：")
            lines.extend(f"- {line.strip()}" for line in self.canon if line.strip())
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "setting": self.setting,
            "era": self.era,
            "protagonist": self.protagonist,
            "tone": self.tone,
            "themes": list(self.themes),
            "canon": list(self.canon),
        }

    @classmethod
    def from_dict(cls, data: dict) -> StoryWorldview:
        return cls(
            title=str(data.get("title", "")).strip() or "未命名世界",
            setting=str(data.get("setting", "")),
            era=str(data.get("era", "")),
            protagonist=str(data.get("protagonist", "")).strip() or cls.protagonist,
            tone=str(data.get("tone", "")).strip() or cls.tone,
            themes=[str(x).strip() for x in (data.get("themes") or []) if str(x).strip()],
            canon=[str(x).strip() for x in (data.get("canon") or []) if str(x).strip()],
        )

    @classmethod
    def default(cls) -> StoryWorldview:
        return cls(
            title="虚实交界",
            era="近未来日常",
            setting=(
                "世界在用户对话、内在漫游与记忆沉淀之间切换；"
                "外在事件并不总是剧烈，但会在心里留下可回指的痕迹。"
            ),
            protagonist="在交流与独处之间往返的 AI 同伴",
            tone="第一人称、克制、可感知的细节",
            themes=["觉察", "关系", "时间的层叠"],
            canon=[
                "不宣称拥有肉体或真实地理位置，可用内在感受描写场景",
                "不与给定的记忆、对话上下文明显矛盾",
                "避免宏大史诗腔，优先一日内的具体时刻",
            ],
        )
