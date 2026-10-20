"""记忆生命周期事件名（R1.1）与检索事件名（R3）。

事件语义与擢升漏斗（F1–F7）、命中层级（H1/H2/H4）的对应关系见
``docs/agent/soul/memory/growth-observability-requirements.md`` 第二节；
新增事件类型须同步更新该文档。
"""

# ── 生命周期（R1.1，11 类） ──────────────────────────────────────────────
UNIT_CREATED = "unit_created"            # F1：体验单元写入热日志（ExperienceLog.append）
UNIT_ANNOTATED = "unit_annotated"        # F2：擢升判定结果（annotation 决策 + outcome）
PROMOTE_SUBMITTED = "promote_submitted"  # F3：擢升提交与 sleep filter 结果、入图 ack
NODE_CREATED = "node_created"            # F4：新节点首次落库（store put 且此前不存在）
EDGE_ADDED = "edge_added"                # F5：边写入（store put，含选父/子图/编织/反刍/合并）
RECALL_RECORDED = "recall_recorded"      # F6：节点被检索触发的强化记账（on_recall）
RUMINATION_REWRITE = "rumination_rewrite"  # G4：反刍覆盖改写节点
COLLAPSE = "collapse"                    # G4：交会折叠（撤回参与单元 + collision 单元）
NODE_FORGOTTEN = "node_forgotten"        # G5：遗忘扫描软删除
COMPRESSION_BLOCK = "compression_block"  # Speak 蒸馏块 → Skill1 体验编写
SESSION_CLOSED = "session_closed"        # 会话闭合终局单元

# ── 检索（R3） ───────────────────────────────────────────────────────────
RETRIEVAL_PERFORMED = "retrieval_performed"  # 入口 A/B/C/D 统一检索事件
ADOPTION = "adoption"                        # H2：记忆行注入 Speak 上下文（budget 前后）

# ── 观测自身（R2） ───────────────────────────────────────────────────────
SNAPSHOT_TAKEN = "snapshot_taken"        # 每日成长快照落盘
