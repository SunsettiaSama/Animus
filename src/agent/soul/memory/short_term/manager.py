from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.soul.memory.codec import unit_from_json, unit_to_json
from agent.soul.memory.unit import MemoryTier, MemoryUnit, Valence

if TYPE_CHECKING:
    from infra.db.redis import RedisClient

# ── Redis key schema ──────────────────────────────────────────────────────────
#   soul:stm:{id}               → JSON 全量记录（带 TTL）
#   soul:stm:idx:valence:{v}    → Set  按情感倾向索引
#   soul:stm:idx:type:{t}       → Set  按 memory_type 索引
_PFX         = "soul:stm:"
_KEY_UNIT    = _PFX + "{}"
_KEY_VALENCE = _PFX + "idx:valence:{}"
_KEY_TYPE    = _PFX + "idx:type:{}"


def _ttl_for(
    unit: MemoryUnit,
    half_life_days: float = 3.0,
    min_ttl_hours: float = 1.0,
) -> int:
    """根据当前激活度推算 TTL（秒）。激活度越低 TTL 越短。"""
    now = datetime.now(timezone.utc)
    a = unit.activation(now=now, half_life_days=half_life_days)
    base_secs = int(half_life_days * 86400)
    min_secs = int(min_ttl_hours * 3600)
    return max(min_secs, int(base_secs * a))


class ShortTermMemoryManager:
    """短期记忆管理器（Redis 后端）。

    短期记忆对应近期会话产出的 MemoryUnit（tier=short_term），
    以 Redis TTL 模拟激活度衰减——TTL 到期即自然遗忘，无需清理任务。

    激活度高的条目（常被命中、情绪强烈）TTL 更长，可在此层持续存在；
    激活度积累到晋升阈值后由 Processor 或 ForgettingEngine 调用
    `promote()` 迁移至 LongTermMemoryManager（MySQL）。

    TTL 策略
    ---------
    默认半衰期 3 天：
        TTL = 3days × activation（最低 1 小时）

    使用
    ----
        redis_client = RedisClient("redis://localhost:6379/0")
        stm = ShortTermMemoryManager(redis_client)
        stm.put(unit)
        unit = stm.get(unit_id)
    """

    def __init__(
        self,
        redis_client: RedisClient,
        half_life_days: float = 3.0,
        min_ttl_hours: float = 1.0,
    ) -> None:
        self._r = redis_client.r
        self._half_life = half_life_days
        self._min_ttl_hours = min_ttl_hours

    # ── Write ─────────────────────────────────────────────────────────────────

    def put(self, unit: MemoryUnit) -> None:
        """存入短期记忆。若已存在则覆盖，TTL 重置。"""
        ttl = _ttl_for(unit, self._half_life, self._min_ttl_hours)
        key = _KEY_UNIT.format(unit.id)
        pipe = self._r.pipeline()
        pipe.set(key, unit_to_json(unit), ex=ttl)
        pipe.sadd(_KEY_VALENCE.format(unit.valence.value), unit.id)
        pipe.sadd(_KEY_TYPE.format(unit.MEMORY_TYPE), unit.id)
        pipe.execute()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, unit_id: str) -> MemoryUnit | None:
        raw = self._r.get(_KEY_UNIT.format(unit_id))
        if raw is None:
            return None
        return unit_from_json(raw)

    def get_many(self, unit_ids: list[str]) -> list[MemoryUnit]:
        if not unit_ids:
            return []
        keys = [_KEY_UNIT.format(uid) for uid in unit_ids]
        raws = self._r.mget(keys)
        return [unit_from_json(r) for r in raws if r is not None]

    def list_by_valence(self, valence: Valence, limit: int = 50) -> list[MemoryUnit]:
        """返回指定情感倾向下的所有短期记忆（自动清理已过期 id）。"""
        ids = self._r.smembers(_KEY_VALENCE.format(valence.value))
        units = self.get_many(list(ids))
        expired = {uid for uid in ids if self._r.get(_KEY_UNIT.format(uid)) is None}
        if expired:
            self._r.srem(_KEY_VALENCE.format(valence.value), *expired)
        return sorted(units, key=lambda u: u.last_accessed, reverse=True)[:limit]

    def list_by_type(self, memory_type: str, limit: int = 50) -> list[MemoryUnit]:
        ids = self._r.smembers(_KEY_TYPE.format(memory_type))
        units = self.get_many(list(ids))
        expired = {uid for uid in ids if self._r.get(_KEY_UNIT.format(uid)) is None}
        if expired:
            self._r.srem(_KEY_TYPE.format(memory_type), *expired)
        return sorted(units, key=lambda u: u.last_accessed, reverse=True)[:limit]

    # ── Recall update ─────────────────────────────────────────────────────────

    def on_recall(self, unit_id: str) -> MemoryUnit | None:
        """命中后更新 recall_count + last_accessed，并刷新 TTL。"""
        unit = self.get(unit_id)
        if unit is None:
            return None
        unit.on_recall()
        self.put(unit)
        return unit

    def add_rehearsal(self, unit_id: str) -> None:
        """反刍命中该条 STM 记忆后更新 rehearsal_count + last_accessed，并刷新 TTL。"""
        unit = self.get(unit_id)
        if unit is None:
            return
        unit.on_rehearsal()
        self.put(unit)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, unit_id: str) -> None:
        unit = self.get(unit_id)
        pipe = self._r.pipeline()
        pipe.delete(_KEY_UNIT.format(unit_id))
        if unit is not None:
            pipe.srem(_KEY_VALENCE.format(unit.valence.value), unit_id)
            pipe.srem(_KEY_TYPE.format(unit.MEMORY_TYPE), unit_id)
        pipe.execute()

    # ── Promote to long-term ──────────────────────────────────────────────────

    def promote(self, unit_id: str, lt_manager: LongTermMemoryManager) -> bool:
        """将短期记忆晋升为长期记忆，成功后从 Redis 删除。

        Returns True if the unit was found and promoted, False otherwise.
        """
        unit = self.get(unit_id)
        if unit is None:
            return False
        unit.promote_to_long()
        lt_manager.put(unit)
        self.delete(unit_id)
        return True

    # ── Iterate all ───────────────────────────────────────────────────────────

    def list_all(self, limit: int = 2000) -> list[MemoryUnit]:
        """返回 STM 中所有未过期的 unit，跨类型合并。

        用于 FlushEngine 批量扫描：读取三类类型索引 Set，
        取并集后批量 mget，自动过滤已过期 id（TTL 到期但 Set 未清理的残留）。
        `limit` 是安全上限，防止 Redis 中意外堆积过多条目。
        """
        all_ids: set[str] = set()
        for mt in ("factual", "reconstructive", "narrative"):
            all_ids |= self._r.smembers(_KEY_TYPE.format(mt))
        if not all_ids:
            return []
        id_list = list(all_ids)[:limit]
        return self.get_many(id_list)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def count(self, memory_type: str | None = None) -> int:
        """返回短期记忆中有效条目数量（TTL 未过期）。"""
        if memory_type:
            ids = self._r.smembers(_KEY_TYPE.format(memory_type))
        else:
            ids = (
                self._r.smembers(_KEY_TYPE.format("factual"))
                | self._r.smembers(_KEY_TYPE.format("reconstructive"))
                | self._r.smembers(_KEY_TYPE.format("narrative"))
            )
        return sum(1 for uid in ids if self._r.exists(_KEY_UNIT.format(uid)))


from agent.soul.memory.long_term.manager import LongTermMemoryManager  # noqa: E402
