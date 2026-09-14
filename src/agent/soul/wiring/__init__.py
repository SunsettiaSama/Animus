"""wiring — 组装层（L3）：跨域接线的唯一居所。

规则（需求 §5.4）：SoulService/SpeakService 的 story 接线**增量零容忍**——
全部落在本包；组装根只调用，不内联。
"""
from __future__ import annotations
