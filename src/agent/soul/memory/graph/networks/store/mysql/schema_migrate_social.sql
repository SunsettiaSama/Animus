-- 已有库升级：在 soul_memory_units 上追加 social 画像与向量字段
ALTER TABLE soul_memory_units
    ADD COLUMN related_interactors_json JSON AFTER neighborhood_content;
ALTER TABLE soul_memory_units
    ADD COLUMN portrait_json JSON AFTER related_interactors_json;
ALTER TABLE soul_memory_units
    ADD COLUMN agent_relation TEXT AFTER portrait_json;
ALTER TABLE soul_memory_units
    ADD COLUMN embed_text TEXT AFTER agent_relation;
ALTER TABLE soul_memory_units
    ADD COLUMN embedding_json JSON AFTER embed_text;
