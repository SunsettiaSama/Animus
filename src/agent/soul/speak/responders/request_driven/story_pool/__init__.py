"""story_pool — 剧情材料预热池（材料供给侧新抽象层）。

分层：
- freshness.py  纯策略（TTL 判级，零依赖）
- store.py      JSON 持久化（原子写，只懂数据形状）
- pool.py       池本体（候选条目管理/选取/失效 + 活体剧情快照）
- prewarmer.py  编排（复用编剧产码，1 全量 + N 骨架，后台线程 + 预算护栏）

消费方只有 SpeakService：冷启动时先查池（take_freshest）注入，
未命中再走正常 ensure_screenwriter_init，并回填池。
"""

from .freshness import FreshnessPolicy, live_snapshot_policy, pool_entry_policy
from .pool import StoryMaterialPool, StoryPoolEntry
from .prewarmer import StoryPrewarmer
from .store import StoryPoolStore

__all__ = [
    "FreshnessPolicy",
    "StoryMaterialPool",
    "StoryPoolEntry",
    "StoryPoolStore",
    "StoryPrewarmer",
    "live_snapshot_policy",
    "pool_entry_policy",
]
