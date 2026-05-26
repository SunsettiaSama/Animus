from __future__ import annotations

from dataclasses import dataclass

from ...protocol.tags import SPEAK_TAG_NAMES, speak_tag


@dataclass(frozen=True)
class SpeakOutputFormat:
    """系统提示词中的 agent 输出格式说明（compose 侧）。"""

    max_fragments: int = 6

    def render_prompt(self) -> str:
        think = speak_tag("think")
        speak = speak_tag("speak")
        action = speak_tag("action")
        finish = speak_tag("state", "finish")
        append = speak_tag("state", "append")
        anchor = speak_tag("anchor", "工具名")
        observe = speak_tag("observe")
        lines = [
            "【输出格式】",
            "使用方括号标签，按顺序输出；speak 与 action 可交替、多段，优先短句：",
            f"- {think} 内部思考，简短，不对用户展示",
            f"- {speak} 角色对白，可多次",
            f"- {action} 角色动作，可多次",
            f"- {finish} 结束本轮，等待用户；或 {append} 继续追加输出",
            "可选（可省略）：",
            f"- {anchor} 现实锚点工具（暂未实现，仅占位）",
            f"- {observe} 外部工具/召回观察结果（有则写，无则省略）",
            f"- 建议总片段不超过 {self.max_fragments} 段，避免长段堆砌",
            "- 不要输出 JSON、XML、ReAct 或 <T>/<A>/<O> 标签",
        ]
        _ = SPEAK_TAG_NAMES
        return "\n".join(lines)
