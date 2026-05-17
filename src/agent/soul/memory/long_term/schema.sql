-- 长期记忆表（三类记忆单元统一存储，memory_type 区分）
CREATE TABLE IF NOT EXISTS soul_memory_units (
    id                VARCHAR(36)   NOT NULL PRIMARY KEY,
    memory_type       VARCHAR(20)   NOT NULL COMMENT 'factual | reconstructive | narrative',

    -- 语义锚点与情绪
    focus             TEXT          NOT NULL,
    emotion           VARCHAR(100)  NOT NULL DEFAULT '',
    emotion_intensity FLOAT         NOT NULL DEFAULT 0.0,
    valence           VARCHAR(10)   NOT NULL DEFAULT 'neutral',

    -- 激活度元数据
    tier                VARCHAR(20)   NOT NULL DEFAULT 'long',
    base_activation     FLOAT         NOT NULL DEFAULT 0.5,
    recall_count        INT           NOT NULL DEFAULT 0,
    rehearsal_count     INT           NOT NULL DEFAULT 0,
    narrative_ref_count INT           NOT NULL DEFAULT 0,
    last_accessed       DATETIME      NOT NULL,
    created_at          DATETIME      NOT NULL,
    meta_json           JSON,

    -- FactualMemory 字段
    fact              TEXT,
    perception        TEXT,

    -- ReconstructiveMemory 字段
    source_id         VARCHAR(36),
    reconstructed_fact TEXT,
    trigger_ctx       TEXT          COMMENT '触发重构的上下文（trigger 为保留字，改用 trigger_ctx）',

    -- NarrativeMemory 字段
    narrative         LONGTEXT,
    source_ids_json   JSON          COMMENT 'list[str]，涉及的记忆单元 id',
    chapter           VARCHAR(200)  NOT NULL DEFAULT '',

    -- 软删除 / 遗忘
    archived          TINYINT(1)    NOT NULL DEFAULT 0,
    archived_at       DATETIME      DEFAULT NULL,

    INDEX idx_memory_type  (memory_type),
    INDEX idx_valence      (valence),
    INDEX idx_last_accessed (last_accessed),
    INDEX idx_archived     (archived),
    INDEX idx_source_id    (source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
