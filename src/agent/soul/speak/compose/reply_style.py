from __future__ import annotations

from dataclasses import dataclass

from .system.output_format import SpeakOutputFormat


@dataclass
class SpeakReplyStyle:
    """模块化短回复约束（委托 compose/system 输出格式）。"""

    max_fragments: int = 6

    def output_format(self) -> SpeakOutputFormat:
        return SpeakOutputFormat(max_fragments=self.max_fragments)

    def render_prompt(self) -> str:
        return self.output_format().render_prompt()
