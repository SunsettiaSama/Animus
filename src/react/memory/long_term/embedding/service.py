from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

import torch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from FlagEmbedding import FlagModel
from pydantic import BaseModel

from config.react.memory.embedding_config import EmbeddingConfig

app = FastAPI()

_model: FlagModel | None = None
_cfg: EmbeddingConfig | None = None


def init(cfg: EmbeddingConfig) -> None:
    global _model, _cfg

    device = cfg.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    _model = FlagModel(
        cfg.model_name_or_path,
        use_fp16=cfg.use_fp16,
        device=device,
    )
    _cfg = cfg


class QueryRequest(BaseModel):
    text: str


class PassageRequest(BaseModel):
    texts: list[str]


@app.get("/health")
def health():
    return {"status": "ok", "ready": _model is not None}


@app.post("/embeddings/query")
def embed_query(req: QueryRequest):
    if _model is None:
        return JSONResponse(status_code=503, content={"error": "model not initialized"})
    text = _cfg.query_prefix + req.text
    vector = _model.encode(text)
    return {"embedding": vector.tolist()}


@app.post("/embeddings/passage")
def embed_passages(req: PassageRequest):
    if _model is None:
        return JSONResponse(status_code=503, content={"error": "model not initialized"})
    texts = [_cfg.passage_prefix + t for t in req.texts]
    vectors = _model.encode(texts)
    return {"embeddings": vectors.tolist()}
