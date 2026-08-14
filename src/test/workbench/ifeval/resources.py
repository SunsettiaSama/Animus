"""Local runtime resources required by the pinned official verifier."""
from __future__ import annotations

from pathlib import Path

from test.workbench.ifeval.dataset import DEFAULT_DATA_DIR

NLTK_DATA_DIR = DEFAULT_DATA_DIR / "nltk_data"


def configure_nltk_data(path: Path = NLTK_DATA_DIR) -> None:
    import nltk

    value = str(path)
    if value not in nltk.data.path:
        nltk.data.path.insert(0, value)


def download_nltk_resources(path: Path = NLTK_DATA_DIR) -> Path:
    import nltk

    path.mkdir(parents=True, exist_ok=True)
    ok = nltk.download("punkt", download_dir=str(path), quiet=True)
    if not ok:
        raise RuntimeError("failed to download NLTK punkt resource")
    configure_nltk_data(path)
    return path
