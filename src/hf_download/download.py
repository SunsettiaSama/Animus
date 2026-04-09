from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from huggingface_hub import hf_hub_download, snapshot_download

from config.hf_download.config import DownloadConfig


def _kwargs(cfg: DownloadConfig) -> dict:
    kw: dict = {}
    if cfg.token:
        kw["token"] = cfg.token
    if cfg.endpoint:
        kw["endpoint"] = cfg.endpoint
    return kw


def download(cfg: DownloadConfig) -> str:
    assert cfg.repo_id, "repo_id must not be empty"
    assert cfg.local_dir, "local_dir must not be empty"

    base_kw = _kwargs(cfg)

    if cfg.filename:
        print(f"[hf_download] downloading file  {cfg.repo_id}/{cfg.filename}")
        path = hf_hub_download(
            repo_id=cfg.repo_id,
            filename=cfg.filename,
            repo_type=cfg.repo_type,
            revision=cfg.revision,
            local_dir=cfg.local_dir,
            **base_kw,
        )
        print(f"[hf_download] saved  →  {path}")
        return path

    print(f"[hf_download] downloading repo  {cfg.repo_id}")
    kw = dict(base_kw)
    if cfg.ignore_patterns:
        kw["ignore_patterns"] = cfg.ignore_patterns

    path = snapshot_download(
        repo_id=cfg.repo_id,
        repo_type=cfg.repo_type,
        revision=cfg.revision,
        local_dir=cfg.local_dir,
        **kw,
    )
    print(f"[hf_download] saved  →  {path}")
    return path
