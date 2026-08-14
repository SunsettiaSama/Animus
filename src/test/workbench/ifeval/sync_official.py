"""Fetch the pinned Apache-2.0 Google IFEval verifier sources."""
from __future__ import annotations

from pathlib import Path

import httpx

OFFICIAL_REVISION = "e6890f85757dd84e27ca6df2dd30651dafad28e0"
OFFICIAL_BASE_URL = (
    "https://raw.githubusercontent.com/google-research/google-research/"
    f"{OFFICIAL_REVISION}/instruction_following_eval"
)
OFFICIAL_FILES = (
    "instructions.py",
    "instructions_util.py",
    "instructions_registry.py",
    "evaluation_lib.py",
)
TARGET_DIR = Path(__file__).resolve().parent / "official"

_IMPORT_FROM = "from instruction_following_eval import "
_IMPORT_TO = "from test.workbench.ifeval.official import "


def sync_official_sources() -> list[Path]:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    init_path = TARGET_DIR / "__init__.py"
    init_path.write_text(
        '"""Pinned Google IFEval verifier (Apache-2.0)."""\n',
        encoding="utf-8",
    )
    written = [init_path]
    for filename in OFFICIAL_FILES:
        response = httpx.get(
            f"{OFFICIAL_BASE_URL}/{filename}",
            follow_redirects=True,
            timeout=120.0,
        )
        response.raise_for_status()
        source = response.text.replace(_IMPORT_FROM, _IMPORT_TO)
        path = TARGET_DIR / filename
        path.write_text(source, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for item in sync_official_sources():
        print(item)
