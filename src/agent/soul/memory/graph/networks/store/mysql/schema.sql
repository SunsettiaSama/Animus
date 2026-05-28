-- 记忆图节点（事件 + 社交统一存储）
CREATE TABLE IF NOT EXISTS soul_memory_units (
    id                VARCHAR(36)   NOT NULL PRIMARY KEY,
    memory_type       VARCHAR(30)   NOT NULL,
    network           VARCHAR(20)   NOT NULL DEFAULT 'event',
    interactor_id     VARCHAR(64)   NOT NULL DEFAULT '',
    node_role         VARCHAR(20)   NOT NULL DEFAULT '',

    focus             TEXT          NOT NULL,
    emotion           VARCHAR(100)  NOT NULL DEFAULT '',
    emotion_intensity FLOAT         NOT NULL DEFAULT 0.0,
    valence           VARCHAR(10)   NOT NULL DEFAULT 'neutral',

    tier                VARCHAR(20)   NOT NULL DEFAULT 'short_term',
    base_activation     FLOAT         NOT NULL DEFAULT 0.5,
    recall_count        INT           NOT NULL DEFAULT 0,
    rehearsal_count     INT           NOT NULL DEFAULT 0,
    narrative_ref_count INT           NOT NULL DEFAULT 0,
    last_accessed       DATETIME      NOT NULL,
    created_at          DATETIME      NOT NULL,
    meta_json           JSON,

    fact              TEXT,
    perception        TEXT,
    source_id         VARCHAR(36),
    reconstructed_fact TEXT,
    trigger_ctx       TEXT,
    narrative         LONGTEXT,
    source_ids_json   JSON,
    chapter           VARCHAR(200)  NOT NULL DEFAULT '',

    core_traits       LONGTEXT,
    trait_version     INT           NOT NULL DEFAULT 1,
    last_evolved_at   DATETIME      DEFAULT NULL,
    neighborhood_label VARCHAR(200) NOT NULL DEFAULT '',
    neighborhood_content TEXT,

    archived          TINYINT(1)    NOT NULL DEFAULT 0,
    archived_at       DATETIME      DEFAULT NULL,

    INDEX idx_memory_type (memory_type),
    INDEX idx_network (network),
    INDEX idx_interactor (interactor_id),
    INDEX idx_node_role (node_role),
    INDEX idx_valence (valence),
    INDEX idx_last_accessed (last_accessed),
    INDEX idx_archived (archived),
    INDEX idx_source_id (source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS soul_memory_edges (
    id          VARCHAR(36)  NOT NULL PRIMARY KEY,
    from_id     VARCHAR(36)  NOT NULL,
    to_id       VARCHAR(36)  NOT NULL,
    edge_type   VARCHAR(20)  NOT NULL,
    weight      FLOAT        NOT NULL DEFAULT 1.0,
    meta_json   JSON,
    created_at  DATETIME     NOT NULL,
    INDEX idx_from (from_id),
    INDEX idx_to (to_id),
    INDEX idx_edge_type (edge_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS soul_interactors (
    id            VARCHAR(64)  NOT NULL PRIMARY KEY,
    display_name  VARCHAR(200) NOT NULL DEFAULT '',
    created_at    DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
