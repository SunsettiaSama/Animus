"""记忆提示兜底：检索零命中时的显式"无记忆"信号。

设计原则：
- 提示行必须**可区分于任何记忆行**（带固定标记前缀），让 Agent 把它理解为
  "已核实的缺席"而非一条记忆——这是反幻觉设计：明确允许"想不起来"。
- 只对**做出过检索决策**的臂生效（graph/stack/kg_*）：检索判空才提示。
  注入臂（full/compact）从不判空，不该有提示。
- 评测端必须识别并跳过提示行（不参与命中/干扰计数），另计 ``hint_shown``
  作为"诚实报告率"观测量。
"""

NO_MEMORY_HINT = "【记忆提示】似乎没有任何记忆和当前内容相关呢"

DRIFT_TAG = "【隐约浮现】"
DRIFT_NOTE = ("（以下标注【隐约浮现】的记忆，是隐隐约约浮现出来的、"
              "和当前语境未必相关的念头：可以用「突然想起」之类的口吻轻轻带过，"
              "也可以完全忽略，不要当作确定的事实依据）")


def is_hint_line(line: str) -> bool:
    return line.strip().startswith("【记忆提示】")


def with_no_memory_hint(entries: list[str]) -> list[str]:
    """空检索 → 返回提示行；非空 → 原样返回。"""
    if entries:
        return entries
    return [NO_MEMORY_HINT]
