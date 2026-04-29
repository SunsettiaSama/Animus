from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import torch
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from config.embedding.config import BuildConfig
from embedding.corpus import Chunk, build_chunks, load_csv


def _resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def _chunks_to_documents(chunks: list[Chunk]) -> list[Document]:
    return [
        Document(
            page_content=c.text,
            metadata={"chunk_id": c.chunk_id, "source_row": c.source_row, **c.meta},
        )
        for c in chunks
    ]


def build(cfg: BuildConfig) -> None:
    print(f"[1/4] loading corpus  →  {cfg.csv_path}")
    rows = load_csv(cfg.csv_path, cfg.text_column, cfg.extra_columns)
    print(f"      {len(rows)} rows loaded")

    print(f"[2/4] chunking  (size={cfg.chunk_size}, overlap={cfg.chunk_overlap})")
    chunks = build_chunks(rows, cfg.chunk_size, cfg.chunk_overlap)
    print(f"      {len(chunks)} chunks produced")

    device = _resolve_device(cfg.device)
    print(f"[3/4] embedding  model={cfg.model_name_or_path}  device={device}")

    inner: dict = {"low_cpu_mem_usage": False}
    if cfg.use_fp16 and device != "cpu":
        inner["torch_dtype"] = torch.float16

    embeddings = HuggingFaceBgeEmbeddings(
        model_name=cfg.model_name_or_path,
        model_kwargs={"device": device, "model_kwargs": inner},
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": cfg.batch_size,
        },
        embed_instruction=cfg.passage_prefix,
        query_instruction=cfg.query_prefix,
    )

    print("[4/4] building FAISS index and saving")
    docs = _chunks_to_documents(chunks)
    vectorstore = FAISS.from_documents(docs, embeddings)
    os.makedirs(cfg.output_dir, exist_ok=True)
    vectorstore.save_local(cfg.output_dir, cfg.index_filename.replace(".faiss", ""))
    print(f"      index  →  {cfg.output_dir}/")
    print("done.")
