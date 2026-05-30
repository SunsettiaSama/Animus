from __future__ import annotations

from dataclasses import dataclass

from ...io.outbound.stream.protocol.tags import speak_tag


@dataclass(frozen=True)
class SpeakOutputFormat:
    """系统提示词中的 agent 输出格式说明（compose 侧）。"""

    max_fragments: int = 6

    def render_prompt(self) -> str:
        think = speak_tag("think", "…")
        speak = speak_tag("speak", "…")
        action = speak_tag("action", "…")
        recall = speak_tag("recall", "检索词")
        finish = speak_tag("state", "finish")
        append = speak_tag("state", "append")
        share = speak_tag("state", "share")
        recall_state = speak_tag("state", "recall")
        example = (
            f"{speak_tag('think', '简短内部思考')}"
            f"{speak_tag('speak', '对白')}"
            f"{speak_tag('action', '动作')}"
            f"{speak_tag('state', 'finish')}"
        )
        lines = [
            "【输出格式】",
            "使用成对方括号标签（开闭标签）组织回复，形如 [tag]内容[/tag]。每轮必须输出，不可省略：",
            f"1. {think} — 内部思考（必填，简短，不对用户展示）",
            (
                f"2. {finish}、{append}、{share} 或 {recall_state} — 轮次状态（必填其一）："
            ),
            f"   - {finish} 结束本轮并等待用户",
            f"   - {append} 还要继续在本轮追加输出",
            (
                f"   - {share} 进入分享：系统将从待分享队列 pop 最想分享的一条，"
                "把完整内容交给你，再请你自然向用户分享"
            ),
            (
                f"   - {recall_state} 进入回忆：须同时写出 {recall}（检索词），"
                "系统会向 memory 检索相关内容后再请你组织回复"
            ),
            "",
            "按需选用（可整轮省略，不必强行对白）：",
            f"- {speak} — 角色对白；不是每轮都必须说话，无合适内容时可不写；向用户展示",
            f"- {action} — 角色动作/神态；可与 speak 穿插，也可单独出现；向用户展示",
            "",
            "关于「可交替、多段」：",
            "- 多段：同一轮可写多个 speak 或多个 action，也可 0 个",
            "- 交替：speak 与 action 可任意顺序穿插，例如 speak→action→speak",
            "- 优先短句：每条 speak/action 尽量一句说完，避免长段堆砌",
            "",
            f"建议 think + speak + action + state 总片段不超过 {self.max_fragments} 段。",
            f"示例（结构参考，勿照抄文案）：{example}",
            "禁止 [tag:内容] 冒号单行写法；禁止 JSON、HTML、ReAct 或 <T>/<A>/<O> 标签。",
        ]
        return "\n".join(lines)
