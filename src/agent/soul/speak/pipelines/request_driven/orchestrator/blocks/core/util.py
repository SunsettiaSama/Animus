from __future__ import annotations

from ...bundle import SpeakPromptBundle


def distilled_context(bundle: SpeakPromptBundle) -> str:
    distilled = bundle.persona.dialogue_compressed.strip()
    if not distilled:
        distilled = bundle.guidance.context_distill.strip()
    if not distilled:
        return ""
    lines = [line.strip() for line in distilled.splitlines() if line.strip()]
    body: list[str] = []
    for line in lines:
        if line.startswith("【") and "】" in line:
            continue
        if line.startswith("以下为") or line.startswith("generation="):
            continue
        body.append(line.lstrip("- ").strip())
    return "\n".join(body) if body else distilled[:400]
