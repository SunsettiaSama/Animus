from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from agent.soul.memory.short_term.manager import ShortTermMemoryManager
from agent.soul.memory.long_term.manager import LongTermMemoryManager
from agent.soul.memory.writer.turn_writer import TurnWriter
from agent.soul.memory.writer.rumination_writer import RuminationWriter
from agent.soul.memory.writer.narrative_writer import NarrativeWriter
from agent.soul.memory.unit import FactualMemory, MemoryUnit, NarrativeMemory, ReconstructiveMemory
from agent.soul.memory.flush import FlushEngine, FlushResult
from agent.soul.memory.retriever import EmbedderBackend, MemoryRetriever, ScoredUnit, VectorBackend
from config.soul.memory.service_config import MemoryServiceConfig

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from infra.db.redis import RedisClient
    from infra.db.mysql import MySQLClient
    from agent.soul.life.experience.unit import ExperienceUnit
    from agent.soul.workers import DomainWorker


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
        与 :meth:`ruminate` 等价别名：反刍指定 ID 的记忆（STM/LTM 皆可；
        来源可为 FactualMemory 或 ReconstructiveMemory）。

    - ruminate(unit_id, trigger=..., emotional_context=...)
        **记忆内部统一反刍入口**。解析 STM→LTM，链式支持「事实→重构→再重构…」；
        心跳与其它调度器只需调用此方法，无需区分存储层或类型。

    - recall(query, top_k, emotional_context)
        混合检索。暂为骨架实现，返回 MemoryBlock；
        完整检索逻辑（Qdrant + activation 重排）由 Retriever 模块承接。

    线程安全性
    ----------
    async_ingest=True（默认）时，ingest_turn 在 MemoryService 内部起一条后台线程；
    调用方（如 TaoLoop.post_process）应直接调用 ingest_turn，勿再外包 Thread。

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
        rumination_writer: RuminationWriter,
        narrative_writer: NarrativeWriter,
        flush_engine: FlushEngine,
        retriever: MemoryRetriever,
        cfg: MemoryServiceConfig,
        heartbeat_flush_interval_sec: float = 21600.0,
        worker: DomainWorker | None = None,
    ) -> None:
        self._stm = stm
        self._ltm = ltm
        self._turn_writer = turn_writer
        self._rumination_writer = rumination_writer
        self._narrative_writer = narrative_writer
        self._flush_engine = flush_engine
        self._retriever = retriever
        self._cfg = cfg
        self._heartbeat_flush_interval_sec = heartbeat_flush_interval_sec
        self._last_heartbeat_flush_mono: float = 0.0
        self._worker = worker

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker

    def _enqueue_write(self, fn: Callable[[], None]) -> None:
        if self._worker is not None:
            self._worker.enqueue(fn)
            return
        if self._cfg.async_ingest:
            threading.Thread(target=fn, daemon=True, name="memory-write").start()
        else:
            fn()
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
        soul_config=None,
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

        if soul_config is None:
            raise ValueError("MemoryService.build 需要 soul_config，请由 SoulService 注入")

        sc = soul_config
        hb_flush_sec = sc.memory_heartbeat_flush_interval_sec

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
        rumination_writer = RuminationWriter(llm, ltm)
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
        return cls(
            stm, ltm, turn_writer, rumination_writer, narrative_writer,
            flush_engine, retriever, cfg,
            heartbeat_flush_interval_sec=hb_flush_sec,
        )

    # ── Resolve / Ruminate（反刍：memory 内部闭环）────────────────────────────

    def get_unit(self, unit_id: str) -> MemoryUnit | None:
        """按 ID 解析记忆单元：优先 STM，其次 LTM。"""
        u = self._stm.get(unit_id)
        if u is not None:
            return u
        return self._ltm.get(unit_id)

    def ruminate(
        self,
        unit_id: str,
        *,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        """对一条已有记忆执行一次反刍，写入新的 ReconstructiveMemory（LTM）。

        ``unit_id`` 可指向 FactualMemory 或 ReconstructiveMemory（允许链式多次反刍）。
        NarrativeMemory 等类型不适用，返回 None。
        """
        source = self.get_unit(unit_id)
        if source is None:
            return None
        if source.MEMORY_TYPE not in ("factual", "reconstructive"):
            return None
        return self._rumination_writer.ruminate_from_source(
            source,
            trigger,
            emotional_context,
            stm=self._stm,
        )

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
        self._enqueue_write(
            lambda: self._safe_ingest_turn(question, answer, persona_snapshot)
        )

    def enqueue_flush(self) -> None:
        """STM → LTM 归档（入 memory-worker 队列）。"""
        self._enqueue_write(self._safe_flush)

    def _safe_flush(self) -> None:
        self.flush()

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
            待反刍的记忆单元 id（FactualMemory 或 ReconstructiveMemory；须已在 STM 或 LTM）
        trigger
            触发重构的情境描述
        emotional_context
            当前情绪状态文字（可来自 EmotionalStateBlock.render()）

        返回
        ----
        写入成功的 ReconstructiveMemory；source 不存在时返回 None。
        """
        return self.ruminate(
            source_unit_id,
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

    # ── MemoryIngestPort 实现 ─────────────────────────────────────────────────

    def ingest_experience(self, unit: ExperienceUnit) -> FactualMemory:
        """将体验编排层擢升的 ExperienceUnit 转化为 FactualMemory 写入 STM。

        映射关系
        --------
        situation.perception  → fact（客观发生了什么）
        situation.narration   → perception（agent 对事件的主观叙述）
        feeling.emotion_label → emotion
        feeling.salience      → emotion_intensity + base_activation
        feeling.valence_delta → Valence 枚举（>0.15 正向，<-0.15 负向）
        experience.id         → life_event_id
        """
        from agent.soul.memory.unit import Valence

        vd = unit.feeling.valence_delta
        if vd > 0.15:
            valence = Valence.positive
        elif vd < -0.15:
            valence = Valence.negative
        else:
            valence = Valence.neutral

        fact       = unit.situation.perception or unit.situation.narration or unit.action.content
        perception = unit.situation.narration  or unit.situation.perception or unit.action.content
        raw_focus  = perception or fact
        focus      = raw_focus[:60] if raw_focus else unit.id[:8]

        mem = FactualMemory(
            focus=focus,
            fact=fact,
            perception=perception,
            emotion=unit.feeling.emotion_label,
            emotion_intensity=unit.feeling.salience,
            valence=valence,
            base_activation=max(0.3, unit.feeling.salience),
            life_event_id=unit.id,
        )
        self._stm.put(mem)
        return mem

    def retract_experience(self, life_event_id: str) -> bool:
        """从 STM 撤回与 ``ExperienceUnit.id`` 关联的条目（交会折叠 supersede 时调用）。"""
        if not life_event_id:
            return False
        for unit in self._stm.list_all():
            if unit.life_event_id == life_event_id:
                self._stm.delete(unit.id)
                return True
        return False

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
            self._enqueue_write(lambda: self._ltm_on_recall_batch(ltm_ids))

        # ── 渲染 MemoryBlock ───────────────────────────────────────────────────
        entries = [s.render_line() for s in scored]
        return MemoryBlock(label="记忆参考", entries=entries)

    def continuity_for_narrative(self, query: str) -> list[str]:
        """Life 叙事连续性：混合检索 + 分差筛选，返回最多 2 条 prompt 行。"""
        q = query.strip()
        if not q:
            return []
        scored = self._retriever.continuity_for_narrative(
            q,
            top_k=self._cfg.narrative_continuity_top_k,
            candidate_k=self._cfg.narrative_continuity_candidate_k,
            min_relevance=self._cfg.narrative_continuity_min_relevance,
            min_final_score=self._cfg.narrative_continuity_min_final_score,
            max_score_gap=self._cfg.narrative_continuity_max_score_gap,
        )
        return [s.render_line(max_content=100) for s in scored]

    def search(self, mode: str, **kwargs) -> list[dict]:
        """对外检索接口：recent / semantic / by_valence / by_field / hybrid。"""
        from agent.soul.memory.codec import scored_to_dict
        from agent.soul.memory.unit import Valence

        m = mode.strip().lower()
        retriever = self._retriever

        if m in ("recent", "timeline"):
            scored = retriever.recent(
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                memory_type=kwargs.get("memory_type"),
                include_stm=bool(kwargs.get("include_stm", True)),
                include_ltm=bool(kwargs.get("include_ltm", True)),
            )
        elif m == "semantic":
            scored = retriever.semantic(
                query=str(kwargs["query"]),
                top_k=int(kwargs.get("top_k", 10)),
            )
        elif m == "by_valence":
            valence = Valence(str(kwargs.get("valence", "neutral")))
            scored = retriever.by_valence(
                valence=valence,
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                emotion_hint=str(kwargs.get("emotion_hint", "")),
                include_stm=bool(kwargs.get("include_stm", True)),
                include_ltm=bool(kwargs.get("include_ltm", True)),
            )
        elif m == "by_field":
            valence_raw = kwargs.get("valence")
            valence = Valence(str(valence_raw)) if valence_raw else None
            scored = retriever.by_field(
                memory_type=kwargs.get("memory_type"),
                valence=valence,
                chapter=kwargs.get("chapter"),
                source_id=kwargs.get("source_id"),
                emotion_contains=kwargs.get("emotion_contains"),
                created_after=kwargs.get("created_after"),
                created_before=kwargs.get("created_before"),
                limit=int(kwargs.get("limit", 20)),
            )
        elif m in ("hybrid", "smart", "recall"):
            valence_raw = kwargs.get("valence")
            valence = Valence(str(valence_raw)) if valence_raw else None
            scored = retriever.hybrid(
                query=str(kwargs.get("query", "")),
                top_k=int(kwargs.get("top_k", self._cfg.recall_top_k)),
                valence=valence,
                memory_type=kwargs.get("memory_type"),
                w_relevance=float(kwargs.get("w_relevance", 0.6)),
                w_activation=float(kwargs.get("w_activation", 0.4)),
            )
        else:
            raise ValueError(
                f"unknown memory search mode: {mode!r} "
                "(expected recent|semantic|by_valence|by_field|hybrid)"
            )

        return [scored_to_dict(s) for s in scored]

    # ── Heartbeat: 受控反刍 ───────────────────────────────────────────────────

    def heartbeat_ruminate(self) -> dict:
        """轻量反刍 API：wander(1) + ruminate(1)，不串联 Persona/Life。

        心跳默认定时任务已升级为完整 wander 演化（见 HeartbeatOrchestrator._run_wander）；
        本方法保留供测试或直接 API 调用。
        """
        wandered = self._retriever.wander(n=1)
        if not wandered:
            return {"wandered": 0, "ruminated": 0}

        su = wandered[0]
        if su.unit.MEMORY_TYPE not in ("factual", "reconstructive"):
            return {
                "wandered": 1,
                "ruminated": 0,
                "skipped_type": su.unit.MEMORY_TYPE,
                "unit_id": su.unit.id,
            }

        ru = self.ruminate(
            su.unit.id,
            trigger="心跳反刍",
            emotional_context="",
        )
        out: dict = {
            "wandered": 1,
            "ruminated": 1 if ru is not None else 0,
            "unit_id": su.unit.id,
        }
        if ru is not None:
            out["reconstructed_id"] = ru.id
        return out

    # ── Bridge: MemoryHeartbeatPort ───────────────────────────────────────────

    def tick(self, snapshot) -> object:
        """实现 MemoryHeartbeatPort.tick()：wander → ruminate → 构建情绪信号。

        流程
        ----
        1. retriever.wander() 随机采样浮现记忆（受 snapshot 情绪偏置影响）
        2. 对 factual / reconstructive 调用 :meth:`ruminate`
        3. 从浮现记忆提取情绪信号返回给 PersonaManager.receive_drift()
        """
        from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

        tid = getattr(snapshot, "tick_id", "") or ""
        kws = [k for k in (getattr(snapshot, "attention_keywords", None) or []) if k]

        wandered = self._retriever.wander(n=2, focus_keywords=kws or None)
        wandered_ids = [s.unit.id for s in wandered]

        emotional_ctx = getattr(snapshot, "emotional_state", "") or ""

        ruminated_ids: list[str] = []
        for su in wandered:
            if su.unit.MEMORY_TYPE not in ("factual", "reconstructive"):
                continue
            ru = self.ruminate(
                su.unit.id,
                trigger=f"心跳漂移；情绪背景：{emotional_ctx or '平静'}",
                emotional_context=emotional_ctx,
            )
            if ru is not None:
                ruminated_ids.append(ru.id)

        flushed_count = 0
        now_m = time.monotonic()
        if now_m - self._last_heartbeat_flush_mono >= self._heartbeat_flush_interval_sec:
            flushed_count = self.flush().flushed
            self._last_heartbeat_flush_mono = now_m

        narrative_triggered = False

        if wandered:
            top = max(wandered, key=lambda s: s.unit.emotion_intensity)
            avg_intensity = sum(s.unit.emotion_intensity for s in wandered) / len(wandered)
            hint = ""
            if ruminated_ids:
                ru_unit = self._ltm.get(ruminated_ids[0])
                if ru_unit is not None:
                    hint = getattr(ru_unit, "reconstructed_fact", "")[:200]
            signal = EmotionalSignal(
                dominant_emotion=top.unit.emotion or "",
                dominant_valence=top.unit.valence,
                intensity=round(avg_intensity, 3),
                source_unit_ids=wandered_ids,
                narrative_hint=hint,
                tick_id=tid,
            )
        else:
            signal = EmotionalSignal(tick_id=tid)

        return MemoryHeartbeatResult(
            wandered_ids=wandered_ids,
            wandered_units=wandered,
            ruminated_ids=ruminated_ids,
            narrative_triggered=narrative_triggered,
            flushed_count=flushed_count,
            signal=signal,
            tick_id=tid,
        )

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
