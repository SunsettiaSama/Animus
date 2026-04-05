from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

import uvicorn

from config.react.memory.embedding_config import EmbeddingConfig
from react.memory.long_term.embedding.service import app, init


def main(cfg: EmbeddingConfig | None = None) -> None:
    if cfg is None:
        cfg = EmbeddingConfig()

    init(cfg)

    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        workers=cfg.workers,
    )


if __name__ == "__main__":
    main()
