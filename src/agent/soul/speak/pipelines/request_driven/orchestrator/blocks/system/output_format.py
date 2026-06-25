from __future__ import annotations

from dataclasses import dataclass


def _speak_tag(kind: str, inner: str = "...") -> str:
    return f"[{kind}]{inner}[/{kind}]"


@dataclass(frozen=True)
class SpeakOutputFormat:
    """系统提示词中的 agent 输出格式说明（compose 侧）。"""

    max_fragments: int = 6

    def render_prompt(self) -> str:
        think = _speak_tag("think", "…")
        speak = _speak_tag("speak", "…")
        action = _speak_tag("action", "…")
        recall = _speak_tag("recall", "检索词")
        finish = _speak_tag("state", "finish")
        append = _speak_tag("state", "append")
        share = _speak_tag("state", "share")
        recall_state = _speak_tag("state", "recall")
        example = (
            f"{_speak_tag('think', '简短内部思考')}"
            f"{_speak_tag('speak', '对白')}"
            f"{_speak_tag('action', '动作')}"
            f"{_speak_tag('state', 'finish')}"
        )
        lines = [
            "回复时请用成对标签 [tag]…[/tag] 组织输出。",
            f"必填：{think}（内部，不对用户展示）；{finish}/{append}/{share}/{recall_state} 四选一。",
            (
                f"{finish} 结束等用户；{append} 本轮继续；"
                f"{share} 系统 pop 分享队列后交你内容；"
                f"{recall_state} 须带 {recall} 检索词。"
            ),
            (
                f"可选（可 0 段，短句、可穿插）：{speak} 对白、{action} 动作/神态；"
                f"总片段 ≤ {self.max_fragments}。示例：{example}"
            ),
            "禁止 [tag:…] 冒号单行、JSON/HTML/ReAct/<T><A><O>。",
        ]
        return "\n".join(lines)
