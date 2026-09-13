"""CannedReplyLLM：离线确定性回复器（--fake-llm 冒烟模式用）。

从 system 的【相关记忆】块里抽第一行回填进回复，模拟"有记忆就记得"；
没有记忆块时固定回"想不起来"。不消耗任何 API。
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("evals.memory_humaneness")

_LINE_PREFIX_RE = re.compile(r"^(?:\[[^\]]*\]\s*)+")  # 去掉 “[近期] ” “[0] ” 等前缀


class FakeReplyLLM:
    def __init__(self, *, cover_anchors: bool = True) -> None:
        self.cover_anchors = cover_anchors
        self.calls = 0

    def generate_messages(self, messages) -> str:
        self.calls += 1
        system = messages[0].content
        if self.cover_anchors and "【相关记忆】" in system:
            block = system.split("【相关记忆】", 1)[1].strip()
            # 取第一条记忆行的正文片段（兼容 graph/stack 的 “kind：正文” 与
            # compact/full 的 “前缀 + 原文” 两种行格式）
            snippet = ""
            for line in block.splitlines():
                line = line.strip().lstrip("- ").strip()
                line = _LINE_PREFIX_RE.sub("", line)
                if line:
                    snippet = line[:24]
                    break
            if snippet:
                return f"记得呀，{snippet}……你突然提这个，怎么啦？"
        return "诶这个我真想不起来了，你跟我说说呗？"
