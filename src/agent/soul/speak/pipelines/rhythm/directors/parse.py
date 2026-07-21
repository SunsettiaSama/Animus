from __future__ import annotations

from typing import Any

from ..contracts import Continuity, GateAction, RhythmPlan, RhythmSegment, ShareTag


def normalize_gate(value: str) -> GateAction:
    gate = value.strip().lower()
    if gate in ("listen", "speak", "hold", "brew"):
        return gate  # type: ignore[return-value]
    raise ValueError(f"rhythm: invalid gate {value!r}")


def normalize_continuity(value: str) -> Continuity:
    cont = value.strip().lower()
    if cont == "append":
        return "append"
    return "finish"


def normalize_share_tag(raw: Any) -> ShareTag:
    if raw is True:
        return "share"
    if raw is False or raw is None:
        return "none"
    text = str(raw).strip().lower()
    if text in ("", "none", "0", "false", "no"):
        return "none"
    if text in ("share", "1", "true", "yes"):
        return "share"
    if text in ("expand", "recall", "retrieve"):
        return "expand"
    raise ValueError(f"rhythm: invalid share tag {raw!r}")


def plan_from_payload(payload: dict[str, Any]) -> RhythmPlan:
    if "gate" not in payload:
        raise ValueError("rhythm: payload missing gate (possibly received arc JSON)")
    gate = normalize_gate(str(payload.get("gate", "")))
    continuity = normalize_continuity(str(payload.get("continuity", "finish")))
    cue = str(payload.get("cue", "")).strip()
    tempo = str(payload.get("tempo", "") or payload.get("pace", "")).strip()
    reply_guide = str(
        payload.get("reply_guide", "")
        or payload.get("guide", "")
        or payload.get("next", "")
    ).strip()
    reason = str(payload.get("reason", "")).strip()
    mood = str(payload.get("mood", "") or payload.get("affect", "")).strip()
    share_tag = normalize_share_tag(
        payload.get("share_tag", payload.get("share", "none"))
    )
    share_id = str(
        payload.get("share_id")
        or payload.get("share_item")
        or payload.get("share_ref")
        or ""
    ).strip()
    segments_raw = payload.get("segments")
    segments: list[RhythmSegment] = []
    if isinstance(segments_raw, list) and segments_raw:
        for item in segments_raw:
            if not isinstance(item, dict):
                continue
            segments.append(
                RhythmSegment(
                    wait_reason=str(item.get("wait_reason", "")).strip() or cue,
                    continuity=normalize_continuity(
                        str(item.get("continuity", "finish"))
                    ),
                )
            )
    if gate in ("speak", "brew") and not segments:
        segments = [RhythmSegment(wait_reason=cue or reason or "speak")]
    return RhythmPlan(
        gate=gate,
        segments=tuple(segments),
        continuity=continuity,
        cue=cue,
        tempo=tempo,
        reply_guide=reply_guide,
        reason=reason,
        mood=mood,
        share_tag=share_tag,
        share_id=share_id,
    )
