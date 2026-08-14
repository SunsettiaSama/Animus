from __future__ import annotations

from agent.soul.speak.responders.request_driven.orchestrator import SpeakPromptBundle

from .contracts import RhythmPlan, ShareHandOff


def attach_rhythm_to_bundle(
    bundle: SpeakPromptBundle,
    *,
    plan: RhythmPlan,
    handoff: ShareHandOff,
    proactive: bool,
) -> SpeakPromptBundle:
    """Map rhythm plan fields into existing SpeakPromptBundle.meta (no ComposeBundle fork)."""
    bundle.meta["rhythm_gate"] = plan.gate
    bundle.meta["rhythm_mood"] = plan.mood
    bundle.meta["rhythm_cue"] = plan.cue
    bundle.meta["rhythm_tempo"] = plan.tempo
    bundle.meta["rhythm_reply_guide"] = plan.reply_guide
    bundle.meta["rhythm_reason"] = plan.reason
    bundle.meta["rhythm_share_tag"] = plan.share_tag
    bundle.meta["rhythm_share_id"] = plan.share_id
    bundle.meta["rhythm_proactive"] = proactive
    if handoff.active:
        bundle.meta["rhythm_share_title"] = handoff.material_line()
        bundle.meta["rhythm_share_handoff"] = handoff.snapshot()
    guide = plan.reply_guide.strip()
    if guide:
        existing = str(bundle.meta.get("reply_guide") or "").strip()
        bundle.meta["reply_guide"] = (
            f"{existing}\n{guide}".strip() if existing else guide
        )
    mood = plan.mood.strip()
    if mood:
        bundle.meta["mood"] = mood
    return bundle


def build_reply_user_text(
    *,
    user_text: str,
    proactive: bool,
    plan: RhythmPlan,
) -> str:
    body = user_text.strip()
    if body:
        return body
    if proactive:
        guide = plan.reply_guide.strip() or plan.cue.strip() or "轻声接一句"
        return f"[系统] 对方暂时沉默。请按主动开口说明自然接一句：{guide}"
    return ""
