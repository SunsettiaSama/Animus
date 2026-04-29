from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embedding.build import build
from config.embedding.config import BuildConfig


def _parse_args() -> BuildConfig:
    p = argparse.ArgumentParser(
        description="Build a static embedding knowledge base from a CSV corpus."
    )
    p.add_argument("--csv-path", default="corpus.csv", help="path to the input CSV file")
    p.add_argument("--text-column", default="text", help="name of the column containing the text")
    p.add_argument(
        "--extra-columns",
        nargs="*",
        default=[],
        help="additional CSV columns to store as metadata",
    )
    p.add_argument("--chunk-size", type=int, default=500, help="max characters per chunk")
    p.add_argument("--chunk-overlap", type=int, default=50, help="overlap characters between chunks")
    p.add_argument("--model", default="BAAI/bge-small-zh-v1.5", help="FlagEmbedding model path or HF id")
    p.add_argument("--no-fp16", action="store_true", help="disable fp16 (use fp32)")
    p.add_argument("--device", default="auto", help="cuda / cpu / auto")
    p.add_argument("--passage-prefix", default="", help="prefix prepended to every passage before encoding")
    p.add_argument("--query-prefix", default="query: ", help="prefix prepended to queries at search time (must match build-time setting)")
    p.add_argument("--batch-size", type=int, default=64, help="embedding batch size")
    p.add_argument("--output-dir", default="knowledge_base", help="directory to write the index")
    p.add_argument("--index-filename", default="index.faiss")
    p.add_argument("--meta-filename", default="meta.jsonl")

    args = p.parse_args()
    return BuildConfig(
        csv_path=args.csv_path,
        text_column=args.text_column,
        extra_columns=args.extra_columns or [],
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        model_name_or_path=args.model,
        use_fp16=not args.no_fp16,
        device=args.device,
        passage_prefix=args.passage_prefix,
        query_prefix=args.query_prefix,
        batch_size=args.batch_size,
        output_dir=args.output_dir,
        index_filename=args.index_filename,
        meta_filename=args.meta_filename,
    )


if __name__ == "__main__":
    cfg = _parse_args()
    build(cfg)
