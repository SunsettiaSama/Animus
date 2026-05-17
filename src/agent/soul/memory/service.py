from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent.soul.memory.short_term.manager import ShortTermMemoryManager
from agent.soul.memory.long_term.manager import LongTermMemoryManager
from agent.soul.memory.writer.turn_writer import TurnWriter
from agent.soul.memory.writer.heartbeat_writer import HeartbeatWriter
from agent.soul.memory.writer.narrative_writer import NarrativeWriter
from agent.soul.memory.unit import FactualMemory, MemoryUnit, NarrativeMemory, ReconstructiveMemory
from agent.soul.memory.flush import FlushEngine, FlushResult
from agent.soul.memory.retriever import EmbedderBackend, MemoryRetriever, ScoredUnit, VectorBackend
from config.soul.memory.service_config import MemoryServiceConfig

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from infra.db.redis import RedisClient
    from infra.db.mysql import MySQLClient


# ── Output block ──────────────────────────────────────────────────────────────

@dataclass
class MemoryBlock:
    """检索结果的渲染块，可直接注入 prompt。

    `units` 中的每条记忆按 final_score 降序排列（已由 Retriever 排序）。
    `render()` 输出 prompt-ready 的文本段落。
    """

    label: str = "记忆"
    entries: list[str] = field(default_factory=list)  # 每条记忆的渲染行

    def render(self) -> str:
        if not self.entries:
            return ""
        body = "\n".join(f"- {e}" for e in self.entries)
        return f"[{self.label}]\n{body}"

    def is_empty(self) -> bool:
        return not self.entries


# ── MemoryService ──────────────────────────────────────────────────────────────

class MemoryService:
    """记忆子系统的统一服务入口。

    外部调用方（TaoLoop、HeartbeatManager）只需知道三个方法：

    - ingest_turn(question, answer, persona_snapshot)
        实时对话写入。每轮对话结束后异步调用，内部流程：
        LLM 提炼 → FactualMemory → STM（Redis）
        若 emotion_intensity 超过阈值 → 同步晋升 LTM（MySQL）

    - ingest_heartbeat(source_unit_id, trigger, emotional_context)
        心跳重构写入。在心跳周期内调用，内部流程：
        读取原始 FactualMemory → LLM 重构 → ReconstructiveMemory → LTM

    - recall(query, top_k, emotional_context)
        混合检索。暂为骨架实现，返回 MemoryBlock；
        完整检索逻辑（Qdrant + activation 重排）由 Retriever 模块承接。

    线程安全性
    ----------
    ingest_turn 默认在调用线程的后台异步提交（async_ingest=True）；
    如需在同一线程同步等待，可设 async_ingest=False。

    使用示例
    --------
        svc = MemoryService.build(
            llm=llm,
            redis_client=redis,
            mysql_client=mysql,
        )
        svc.ingest_turn(question, answer, persona_snapshot)   # 非阻塞
        block = svc.recall("架构讨论")                         # 返回 MemoryBlock
        prompt_text = block.render()
    """

    def __init__(
        self,
        stm: ShortTermMemoryManager,
        ltm: LongTermMemoryManager,
        turn_writer: TurnWriter,
        heartbeat_writer: HeartbeatWriter,
        narrative_writer: NarrativeWriter,
        flush_engine: FlushEngine,
        retriever: MemoryRetriever,
        cfg: MemoryServiceConfig,
    ) -> None:
        self._stm = stm
        self._ltm = ltm
        self._turn_writer = turn_writer
        self._heartbeat_writer = heartbeat_writer
        self._narrative_writer = narrative_writer
        self._flush_engine = flush_engine
        self._retriever = retriever
        self._cfg = cfg


    # ── Factory ────────────────────────────────────────────────────────────────

    @property
    def retriever(self) -> MemoryRetriever:
        """暴露检索器，供人格层、心跳层等外部模块直接使用五种检索模式。"""
        return self._retriever

    @classmethod
    def build(
        cls,
        llm: BaseLLM,
        redis_client: RedisClient,
        mysql_client: MySQLClient,
        cfg: MemoryServiceConfig | None = None,
        embedder: EmbedderBackend | None = None,
        vector_store: VectorBackend | None = None,
    ) -> MemoryService:
        """从基础设施实例组装完整的 MemoryService。

        若未传入 cfg，自动加载 config/soul/memory/service.yaml；
        文件不存在时使用全部默认值，保证零配置可启动。

        参数
        ----
        llm
            BaseLLM 推理实例
        redis_client
            RedisClient 实例（用于短期记忆）
        mysql_client
            MySQLClient 实例（用于长期记忆）
        cfg
            MemoryServiceConfig，不传则自动读取约定路径的 YAML
        embedder
            可选，满足 EmbedderBackend 协议的嵌入器（供语义检索使用）
        vector_store
            可选，满足 VectorBackend 协议的向量存储（供语义检索使用）
        """
        if cfg is None:
            cfg = MemoryServiceConfig.load_default()

        stm = ShortTermMemoryManager(
            redis_client,
            half_life_days=cfg.stm_half_life_days,
            min_ttl_hours=cfg.stm_min_ttl_hours,
        )
        ltm = LongTermMemoryManager(mysql_client)
        turn_writer = TurnWriter(
            llm, stm, ltm,
            promote_threshold=cfg.promote_threshold,
        )
        heartbeat_writer = HeartbeatWriter(llm, ltm)
        narrative_writer = NarrativeWriter(llm, ltm)
        flush_engine = FlushEngine(
            stm, ltm,
            stm_half_life_days=cfg.stm_half_life_days,
            activation_floor=cfg.flush_activation_floor,
        )
        retriever = MemoryRetriever(
            stm, ltm,
            stm_half_life_days=cfg.stm_half_life_days,
            ltm_half_life_days=cfg.ltm_half_life_days,
            embedder=embedder,
            vector_store=vector_store,
        )
        return cls(stm, ltm, turn_writer, heartbeat_writer, narrative_writer, flush_engine, retriever, cfg)

    # ── Write interface ────────────────────────────────────────────────────────

    def ingest_turn(
        self,
        question: str,
        answer: str,
        persona_snapshot: str = "",
    ) -> None:
        """实时对话写入接口（TaoLoop 调用）。

        默认异步提交，不阻塞 TaoLoop 的响应通路。
        写入失败时打印警告，不向上抛出异常（后台任务不应影响主流程）。

        参数
        ----
        question
            用户问题
        answer
            Agent 本轮回答
        persona_snapshot
            PersonaManager.all_blocks() 渲染后的字符串（可选）
        """
        if self._cfg.async_ingest:
            t = threading.Thread(
                target=self._safe_ingest_turn,
                args=(question, answer, persona_snapshot),
                daemon=True,
                name="memory-ingest-turn",
            )
            t.start()
        else:
            self._safe_ingest_turn(question, answer, persona_snapshot)

    def ingest_heartbeat(
        self,
        source_unit_id: str,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        """心跳重构写入接口 → ReconstructiveMemory → LTM。

        同步执行（心跳本身已运行在后台线程）。

        参数
        ----
        source_unit_id
            待重构的原始 FactualMemory.id
        trigger
            触发重构的情境描述
        emotional_context
            当前情绪状态文字（可来自 EmotionalStateBlock.render()）

        返回
        ----
        写入成功的 ReconstructiveMemory；source 不存在时返回 None。
        """
        return self._heartbeat_writer.write(
            source_unit_id=source_unit_id,
            trigger=trigger,
            emotional_context=emotional_context,
        )

    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory | None:
        """叙事写入接口 → NarrativeMemory → LTM（LifeManager 日终回顾时调用）。

        将若干已存入 LTM 的事实性/重构型记忆整合为一条叙事记忆，
        模拟人类将零散记忆编织为"人生故事"的过程。

        同步执行（LifeManager 的日终回顾本身在后台线程运行）。

        参数
        ----
        source_unit_ids
            参与叙事编织的 MemoryUnit.id 列表（从 LTM 查询）
        chapter
            人生章节标签（如"系统构建早期"），用于跨章节检索
        persona_snapshot
            PersonaManager 渲染的人格上下文字符串（可选）
        emotional_context
            当前情绪状态文字（可来自 EmotionalStateBlock.render()）

        返回
        ----
        写入成功的 NarrativeMemory；source_unit_ids 全部无效时返回 None。
        """
        return self._narrative_writer.write(
            source_unit_ids=source_unit_ids,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def ingest_narrative_from_units(
        self,
        source_units: list[MemoryUnit],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory:
        """叙事写入接口（unit 对象直传版）→ NarrativeMemory → LTM。

        当调用方已在内存中持有 MemoryUnit 列表时使用此方法，避免二次读 DB。
        典型场景：LifeManager 在 run_daily_review() 期间已检索了相关 unit。

        参数
        ----
        source_units
            参与叙事编织的 MemoryUnit 实例列表
        chapter / persona_snapshot / emotional_context
            同 ingest_narrative()
        """
        return self._narrative_writer.write_from_units(
            source_units=source_units,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    # ── Lifecycle interface ────────────────────────────────────────────────────

    def flush(self) -> FlushResult:
        """STM → LTM 归档接口（心跳定期调用）。

        将 STM（Redis）中 activation >= floor 的条目全量归档进 LTM（MySQL），
        以当前 activation 值作为 LTM 初始 base_activation。
        activation < floor 的条目跳过，由 Redis TTL 自然淘汰。

        同步执行（心跳本身在后台线程运行）。

        返回
        ----
        FlushResult，包含 flushed / skipped / errors 计数。
        """
        return self._flush_engine.run()

    def forget_scan(
        self,
        threshold: float = 0.05,
        dry_run: bool = False,
    ) -> list[str]:
        """LTM 遗忘扫描接口（心跳定期调用）。

        对 LTM 中激活度长期低于 threshold 的条目执行软删除。
        与 flush() 搭配使用，构成完整记忆生命周期：

            STM ──flush()──> LTM ──forget_scan()──> archived

        参数
        ----
        threshold
            激活度低于此值则归档，默认 0.05
        dry_run
            True 时只返回候选 id，不执行归档

        返回
        ----
        被归档（或候选）的 unit_id 列表。
        """
        return self._ltm.forget_scan(
            threshold=threshold,
            half_life_days=self._cfg.ltm_half_life_days,
            dry_run=dry_run,
        )

    # ── Read interface ─────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        top_k: int | None = None,
        emotional_context: str = "",
    ) -> MemoryBlock:
        """混合记忆检索接口，含命中反馈闭环。

        每次返回的 unit 均触发 on_recall()：
        - STM：内联更新（Redis pipeline，微秒级）→ recall_count++，TTL 刷新
        - LTM：后台线程更新（MySQL UPDATE）→ recall_count++，last_accessed 刷新

        recall_count 的积累是后续 PromotionEngine 评分的核心信号之一。

        当前检索策略为骨架实现（按 activation 排序取近期条目），
        完整的向量检索 + activation 重排由后续 MemoryRetriever 模块承接。

        参数
        ----
        query
            检索查询（来自当前 question 或上下文摘要）
        top_k
            最多返回的记忆条数；不传则读 cfg.recall_top_k
        emotional_context
            当前情绪上下文（供情绪偏置使用，骨架阶段暂未使用）

        返回
        ----
        MemoryBlock，调用 .render() 可直接注入 prompt。
        """
        k = top_k if top_k is not None else self._cfg.recall_top_k

        # 混合检索：有 embedder 时走语义+activation，否则降级为近期+activation
        scored = self._retriever.hybrid(
            query=query,
            top_k=k,
            w_relevance=0.6,
            w_activation=0.4,
        )

        # ── 命中反馈闭环 ───────────────────────────────────────────────────────
        stm_ids = [s.unit.id for s in scored if s.source == "stm"]
        ltm_ids = [s.unit.id for s in scored if s.source == "ltm"]

        for uid in stm_ids:
            self._stm.on_recall(uid)   # 内联：Redis pipeline，极轻

        if ltm_ids:
            threading.Thread(
                target=self._ltm_on_recall_batch,
                args=(ltm_ids,),
                daemon=True,
                name="memory-recall-feedback",
            ).start()

        # ── 渲染 MemoryBlock ───────────────────────────────────────────────────
        entries = [s.render_line() for s in scored]
        return MemoryBlock(label="记忆参考", entries=entries)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _safe_ingest_turn(
        self,
        question: str,
        answer: str,
        persona_snapshot: str,
    ) -> None:
        self._turn_writer.write(question, answer, persona_snapshot)

    def _ltm_on_recall_batch(self, unit_ids: list[str]) -> None:
        """后台批量更新 LTM 命中记录（recall_count++，last_accessed 刷新）。"""
        for uid in unit_ids:
            self._ltm.on_recall(uid)
