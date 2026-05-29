from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEM = ROOT / "agent" / "soul" / "memory"

REPLACEMENTS = [
    (b"\xe7\x8e?", b"\xe7\x8e\xb0"),
    (b'\xe3\x80?""\r\n', b'\xe3\x80\x82"""\r\n'),
    (b"\xe3\x80?", b"\xe3\x80\x82"),
    (b"\xef\xbc?", b"\xef\xbc\x9a"),
    (b"\xe6\x80?\xe9", b"\xe6\x80\xa7\xe9"),
    (b"\xe6\x80?\xc3", b"\xe6\x80\xa7\xc3"),
    (b"\xe5\xba?\xc3", b"\xe5\xba\xa6\xc3"),
    (b"\xe5\xba?+", b"\xe5\xba\x93+"),
    (b"\xe8\xa6?e", b"\xe8\xa6\x81e"),
    (b"\xe5\x92?v", b"\xe5\x92\x8cv"),
    (b"\xe7\x9a?r", b"\xe7\x9a\x84r"),
    (b"\xe7\x9a?M", b"\xe7\x9a\x84M"),
    (b"\xe8\x80?,", b"\xe8\x80\x83,"),
    (b"\xef\xbc?,", b"\xef\xbc\x89,"),
    (b"\xef\xbc\x88\xe6\x9c\xaa\xe5\x91\xbd\xe5\x90\x8d\xef\xbc?, 0.0", b"\xef\xbc\x88\xe6\x9c\xaa\xe5\x91\xbd\xe5\x90\x8d\xef\xbc\x89\", 0.0"),
]


def main() -> None:
    raw = subprocess.check_output(
        ["git", "show", "HEAD:src/agent/soul/memory/retriever.py"],
        cwd=ROOT.parent,
    )
    for old, new in REPLACEMENTS:
        raw = raw.replace(old, new)
    text = raw.decode("utf-8")
    text = text.replace(
        '"semantic() 需要embedder 与vector_store。\n                "请经 MemoryInfraService 注入。',
        '"semantic() requires embedder and vector_store; "\n                "inject via MemoryInfraService.',
    )
    text = text.replace('label: str = "记忆参与",', 'label: str = "memory",')
    path = MEM / "retriever.py"
    compile(text, str(path), "exec")
    path.write_text(text, encoding="utf-8")
    print("fixed", path)


if __name__ == "__main__":
    main()
