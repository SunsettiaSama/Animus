from __future__ import annotations

import json
from pathlib import Path

transcripts = Path(r"C:\Users\admin\.cursor\projects\e-ReAct\agent-transcripts")
targets = {
    "segment.py": None,
    "typewriter.py": None,
    "arc.py": None,
    "on_scene.py": None,
    "parse.py": None,
    "review.py": None,
    "ports.py": None,
}
out_dir = Path(__file__).resolve().parent / "_recovered"
out_dir.mkdir(exist_ok=True)

for jf in sorted(transcripts.rglob("*.jsonl")):
    for line in jf.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Write" not in line:
            continue
        obj = json.loads(line)
        content = obj.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("name") != "Write":
                continue
            inp = part.get("input") or {}
            path = str(inp.get("path", ""))
            fname = Path(path).name
            if fname not in targets:
                continue
            norm = path.replace("\\", "/").lower()
            if "/directors/" not in norm and "\\directors\\" not in path.lower():
                continue
            body = inp.get("contents", "")
            prev = targets[fname]
            if body and (prev is None or len(body) > len(prev[0])):
                targets[fname] = (body, str(jf))

for fname, val in targets.items():
    if val is None:
        print(f"MISSING {fname}")
        continue
    body, src = val
    (out_dir / fname).write_text(body, encoding="utf-8")
    print(f"SAVED {fname} len={len(body)} from {Path(src).name}")
