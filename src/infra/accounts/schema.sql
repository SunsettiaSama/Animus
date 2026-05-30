CREATE TABLE IF NOT EXISTS external_accounts (
    account_id     VARCHAR(36)   NOT NULL PRIMARY KEY,
    interactor_id  VARCHAR(64)   NOT NULL,
    display_name   VARCHAR(200)  NOT NULL DEFAULT '',
    meta_json      JSON,
    created_at     DATETIME      NOT NULL,
    updated_at     DATETIME      NOT NULL,
    UNIQUE KEY uq_external_accounts_interactor (interactor_id),
    INDEX idx_external_accounts_name (display_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
