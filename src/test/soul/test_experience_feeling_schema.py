from __future__ import annotations

from agent.soul.life.experience.domain.unit import ExperienceFeeling


def test_feeling_roundtrip_mood_fields():
    feeling = ExperienceFeeling(
        mood_span="接下来两三天你会有点沮丧",
        linger_days=3.0,
        subjective_narrative="刚才你摔了一跤，膝盖还在隐隐作痛。",
        emotion_label="沮丧",
        salience=0.6,
    )
    restored = ExperienceFeeling.from_dict(feeling.to_dict())
    assert restored.mood_span == feeling.mood_span
    assert restored.linger_days == 3.0
    assert restored.subjective_narrative == feeling.subjective_narrative


def test_effective_mood_span_fallback():
    feeling = ExperienceFeeling(emotion_label="期待")
    assert "期待" in feeling.effective_mood_span()
    assert feeling.effective_mood_span().startswith("接下来")
