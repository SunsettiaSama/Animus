CREATE TABLE IF NOT EXISTS soul_session_channels (
    session_id     VARCHAR(64)  NOT NULL PRIMARY KEY,
    interactor_id  VARCHAR(64)  NOT NULL,
    bound_at       DATETIME     NOT NULL,
    INDEX idx_channel_interactor (interactor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
