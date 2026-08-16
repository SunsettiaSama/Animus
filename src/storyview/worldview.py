from __future__ import annotations

from dataclasses import dataclass, field

# Storyview 场面通道暂时关闭。等场面与实体不再幻觉、世界观落地后，
# 再打开 SoulService._ensure_story_service / speak.bind_story / life.set_story_port。
STORYVIEW_CHANNEL_NOTE = (
    "备注：Storyview 场面端口与 StoryService 暂时关闭；"
    "此处只提供原神占位世界观，等 storyview 进一步完善后再打开这个位置的通道。"
)


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
        return cls.placeholder_teyvat()

    @classmethod
    def placeholder_teyvat(cls) -> StoryWorldview:
        """原神 / 提瓦特占位。不接 Storyview 场面，只给叙事一层薄背景。"""
        return cls(
            title="提瓦特（原神）",
            era="提瓦特大陆 · 七国纪年",
            setting=(
                "七国分立：蒙德、璃月、稻妻、须弥、枫丹、纳塔、至冬。"
                "元素力流转，神之眼持有者能驱使对应元素。"
                "冒险家协会、七天神像与各地城邦是日常锚点。"
                "先用这层薄设定占位，不展开未建立的神系争端或地区政治。"
            ),
            protagonist="在提瓦特旅行、与人通信的旅者同伴",
            tone="具体、轻快、能入镜的风物",
            themes=["旅行", "元素", "城邦日常"],
            canon=[
                STORYVIEW_CHANNEL_NOTE,
                "七国与七元素是已给出的底；不发明新的国度或元素",
                "不把 Storyview 旧场面（帐篷、老周、花房）当作当前事实",
                "角色与用户的往来写在编剧交互过程里，不靠场面引擎补人",
            ],
        )
