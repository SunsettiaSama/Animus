from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hf_download.download import download
from config import paths
from config.hf_download.config import DownloadConfig


def _load_yaml_config() -> DownloadConfig:
    return DownloadConfig.from_yaml(str(paths.hf_download_yaml))


def _parse_args() -> DownloadConfig:
    p = argparse.ArgumentParser(description="Download a model/dataset/space from HuggingFace Hub.")

    p.add_argument("--repo-id", default="", help="HuggingFace repo id, e.g. BAAI/bge-small-zh-v1.5")
    p.add_argument("--repo-type", default="model", choices=["model", "dataset", "space"])
    p.add_argument("--revision", default="main", help="branch / tag / commit hash")
    p.add_argument("--filename", default="", help="download a single file instead of the whole repo")
    p.add_argument("--local-dir", default="", help="local directory to save files")
    p.add_argument(
        "--ignore-patterns",
        nargs="*",
        default=[],
        help="glob patterns to exclude, e.g. '*.msgpack' '*.h5'",
    )
    p.add_argument("--token", default="", help="HuggingFace access token (for private repos)")
    p.add_argument("--endpoint", default="", help="custom endpoint, e.g. https://hf-mirror.com")

    args = p.parse_args()
    return DownloadConfig(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        revision=args.revision,
        filename=args.filename,
        local_dir=args.local_dir,
        ignore_patterns=args.ignore_patterns or [],
        token=args.token,
        endpoint=args.endpoint,
    )


def run(cfg: DownloadConfig) -> str:
    return download(cfg)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        cfg = _load_yaml_config()
    else:
        cfg = _parse_args()
    run(cfg)
