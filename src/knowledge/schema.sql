CREATE TABLE IF NOT EXISTS documents (
    id          VARCHAR(36)  NOT NULL,
    source      VARCHAR(512) NOT NULL,
    source_type VARCHAR(32)  NOT NULL,
    title       VARCHAR(512),
    status      VARCHAR(32)  NOT NULL DEFAULT 'pending',
    meta        JSON,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at  DATETIME     NULL,
    PRIMARY KEY (id),
    INDEX idx_doc_status  (status),
    INDEX idx_doc_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS content_blobs (
    id         VARCHAR(36) NOT NULL,
    doc_id     VARCHAR(36) NOT NULL,
    content    LONGTEXT    NOT NULL,
    encoding   VARCHAR(32) NOT NULL DEFAULT 'utf-8',
    created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at DATETIME    NULL,
    PRIMARY KEY (id),
    INDEX idx_blob_doc (doc_id),
    CONSTRAINT fk_blob_doc FOREIGN KEY (doc_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS doc_chunks (
    id          VARCHAR(36)  NOT NULL,
    doc_id      VARCHAR(36)  NOT NULL,
    chunk_index INT          NOT NULL,
    content     TEXT         NOT NULL,
    is_indexed  BOOLEAN      NOT NULL DEFAULT FALSE,
    meta        JSON,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at  DATETIME     NULL,
    PRIMARY KEY (id),
    INDEX idx_chunk_doc     (doc_id),
    INDEX idx_chunk_indexed (is_indexed),
    INDEX idx_chunk_deleted (deleted_at),
    FULLTEXT INDEX ft_chunk_content (content),
    CONSTRAINT fk_chunk_doc FOREIGN KEY (doc_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
