"""情绪烈度推断单元测试（真实导入链；每会话仅付一次重导入成本）。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.memory.emotion_intensity import (
    infer_emotion_intensity,
    node_emotion_intensity,
)
from agent.soul.memory.graph.networks.event.node import FactualMemory


def test_infer_from_subjective_and_emotion_label():
    intensity = infer_emotion_intensity(
        "难过",
        "我今天特别难过，心里堵得慌",
    )
    assert intensity >= 0.52


def test_infer_calm_subjective_maps_low():
    intensity = infer_emotion_intensity(
        "平静",
        "我在午后阳光里继续整理笔记，心里很安静",
    )
    assert 0.15 <= intensity <= 0.35


def test_node_emotion_intensity_uses_perception():
    node = FactualMemory(
        focus="整理笔记",
        fact="raw",
        perception="我欣喜若狂地完成了一份报告",
        emotion="开心",
        emotion_intensity=0.1,
    )
    assert node_emotion_intensity(node) >= 0.52
    assert node.activation() > 0.5
