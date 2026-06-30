CREATE TABLE IF NOT EXISTS story_world (
    world_id      VARCHAR(64)   NOT NULL PRIMARY KEY,
    title         VARCHAR(200)  NOT NULL DEFAULT '',
    era           VARCHAR(200)  NOT NULL DEFAULT '',
    setting       TEXT,
    tone          VARCHAR(200)  NOT NULL DEFAULT '',
    canon_json    JSON,
    meta_json     JSON,
    created_at    DATETIME      NOT NULL,
    updated_at    DATETIME      NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_location (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id      VARCHAR(64)   NOT NULL,
    parent_id     VARCHAR(36)   DEFAULT NULL,
    name          VARCHAR(200)  NOT NULL DEFAULT '',
    description   TEXT,
    atmosphere    TEXT,
    tags_json     JSON,
    INDEX idx_story_loc_world (world_id),
    INDEX idx_story_loc_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_entity (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id      VARCHAR(64)   NOT NULL,
    location_id   VARCHAR(36)   DEFAULT NULL,
    name          VARCHAR(200)  NOT NULL DEFAULT '',
    kind          VARCHAR(50)   NOT NULL DEFAULT 'object',
    description   TEXT,
    state_json    JSON,
    INDEX idx_story_ent_world (world_id),
    INDEX idx_story_ent_loc (location_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_lore (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id      VARCHAR(64)   NOT NULL,
    category      VARCHAR(80)   NOT NULL DEFAULT '',
    title         VARCHAR(200)  NOT NULL DEFAULT '',
    body          LONGTEXT      NOT NULL,
    tags_json     JSON,
    weight        INT           NOT NULL DEFAULT 10,
    INDEX idx_story_lore_world (world_id),
    INDEX idx_story_lore_cat (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_lore_link (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    lore_id       VARCHAR(36)   NOT NULL,
    ref_type      VARCHAR(20)   NOT NULL,
    ref_id        VARCHAR(36)   NOT NULL,
    INDEX idx_story_link_lore (lore_id),
    INDEX idx_story_link_ref (ref_type, ref_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_outline_arc (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id      VARCHAR(64)   NOT NULL,
    title         VARCHAR(200)  NOT NULL DEFAULT '',
    status        VARCHAR(20)   NOT NULL DEFAULT 'active',
    INDEX idx_story_arc_world (world_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_outline_beat (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    arc_id        VARCHAR(36)   NOT NULL,
    seq           INT           NOT NULL DEFAULT 0,
    summary       TEXT          NOT NULL,
    required      TINYINT(1)    NOT NULL DEFAULT 0,
    INDEX idx_story_beat_arc (arc_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_runtime (
    world_id              VARCHAR(64)  NOT NULL PRIMARY KEY,
    current_location_id   VARCHAR(36)  DEFAULT NULL,
    world_time            VARCHAR(64)  NOT NULL DEFAULT '',
    scene_snapshot_json   JSON,
    active_arc_id         VARCHAR(36)  DEFAULT NULL,
    updated_at            DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_event (
    event_id      VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id      VARCHAR(64)   NOT NULL,
    kind          VARCHAR(30)   NOT NULL DEFAULT '',
    status        VARCHAR(20)   NOT NULL DEFAULT 'open',
    scene_text    TEXT,
    cue           TEXT,
    created_at    DATETIME      NOT NULL,
    INDEX idx_story_event_world (world_id),
    INDEX idx_story_event_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_scene (
    id            VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id      VARCHAR(64)   NOT NULL,
    name          VARCHAR(200)  NOT NULL DEFAULT '',
    narrative     LONGTEXT      NOT NULL,
    location_id   VARCHAR(36)   DEFAULT NULL,
    tags_json     JSON,
    meta_json     JSON,
    INDEX idx_story_scene_world (world_id),
    INDEX idx_story_scene_loc (location_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_scene_edge (
    id                VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id          VARCHAR(64)   NOT NULL,
    from_scene_id     VARCHAR(36)   NOT NULL,
    to_scene_id       VARCHAR(36)   NOT NULL,
    transition_text   TEXT          NOT NULL,
    weight            INT           NOT NULL DEFAULT 10,
    INDEX idx_story_scene_edge_world (world_id),
    INDEX idx_story_scene_edge_from (from_scene_id),
    INDEX idx_story_scene_edge_to (to_scene_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_event_log (
    id                VARCHAR(36)   NOT NULL PRIMARY KEY,
    event_id          VARCHAR(36)   NOT NULL,
    world_id          VARCHAR(64)   NOT NULL,
    scene_text        TEXT,
    resolution_text   TEXT,
    dice_value        INT           NOT NULL DEFAULT 0,
    dice_tendency     VARCHAR(200)  NOT NULL DEFAULT '',
    deviation_flag    TINYINT(1)    NOT NULL DEFAULT 0,
    deviation_note    TEXT,
    state_patch_json  JSON,
    created_at        DATETIME      NOT NULL,
    INDEX idx_story_log_world (world_id),
    INDEX idx_story_log_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_agent_location_snapshot (
    snapshot_id       VARCHAR(36)   NOT NULL PRIMARY KEY,
    world_id          VARCHAR(64)   NOT NULL,
    scene_id          VARCHAR(36)   NOT NULL DEFAULT '',
    location_id       VARCHAR(36)   DEFAULT NULL,
    scene_text        TEXT,
    reason            VARCHAR(40)   NOT NULL DEFAULT 'arc_start',
    source_event_id   VARCHAR(36)   NOT NULL DEFAULT '',
    created_at        DATETIME      NOT NULL,
    INDEX idx_story_loc_snap_world (world_id),
    INDEX idx_story_loc_snap_created (world_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
