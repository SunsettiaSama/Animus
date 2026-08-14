from __future__ import annotations

from agent.soul.speak.responders.rhythm.contracts import RhythmReview, ShareItem
from agent.soul.speak.responders.rhythm.snapshot import build_rhythm_snapshot
from agent.soul.speak.responders.rhythm.state import RhythmSessionState


def test_rhythm_snapshot_prompt_contains_core_blocks_without_review_summary_as_plot():
    state = RhythmSessionState(session_id="s-rhythm")
    state.set_arc("先接住眼前输入，主动只提一件本场材料。")
    state.set_review(
        RhythmReview(
            abstract="优先回应当前输入；主动开口只挑一件本场材料。",
            summary="上一场讲了钥匙和外套，这些不能当成本场剧情。",
        )
    )
    state.set_affect(label="接住当下", valence="mixed", intensity=0.4)
    state.append_history("user", "在吗？")
    state.append_history("agent", "在。")
    snap = build_rhythm_snapshot(
        state,
        user_text="有点烦。",
        trigger="inbound",
        turn_index=2,
        share_queue=(
            ShareItem(item_id="share-1", topic="边界草稿有重复"),
        ),
        typing_active=False,
        typing_idle=True,
        push_phase="idle",
    )
    text = snap.prompt_lines()
    assert "trigger=inbound" in text
    assert "接住当下" in text
    assert "先接住眼前输入" in text
    assert "优先回应当前输入" in text
    assert "边界草稿有重复" in text
    assert "typing_active=False" in text
    assert "user:在吗？" in text
    assert "钥匙和外套" not in text
    assert "summary" not in text.lower() or "复盘原则" in text
