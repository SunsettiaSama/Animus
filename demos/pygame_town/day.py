"""Day clock: 1 real minute = 1 game hour; phases derived from hour."""

from __future__ import annotations

from agents import DEST_CABIN, DEST_PLAZA, DEST_YARD, Agent

# 现实时间 → 游戏时间
REAL_SECONDS_PER_GAME_HOUR = 60.0

PHASES = ("morning", "noon", "evening")

# home_id -> phase -> destination（无活动任务时的默认去向）
SCHEDULE: dict[str, dict[str, str]] = {
    "he": {
        "morning": DEST_YARD,
        "noon": DEST_PLAZA,
        "evening": DEST_CABIN,
    },
    "mai": {
        "morning": DEST_CABIN,
        "noon": DEST_PLAZA,
        "evening": DEST_YARD,
    },
    "moss": {
        "morning": DEST_PLAZA,
        "noon": DEST_YARD,
        "evening": DEST_PLAZA,
    },
}


def phase_for_hour(hour: int) -> str:
    h = int(hour) % 24
    if 6 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "noon"
    return "evening"


class DayClock:
    def __init__(self, *, start_hour: int = 8) -> None:
        self.day = 1
        self.hour = int(start_hour) % 24
        self._accum = 0.0

    @property
    def phase(self) -> str:
        return phase_for_hour(self.hour)

    @property
    def label(self) -> str:
        return f"Day {self.day} {self.hour:02d}:00 ({self.phase})"

    def seconds_to_next_hour(self) -> float:
        return max(0.0, REAL_SECONDS_PER_GAME_HOUR - self._accum)

    def tick(self, real_dt: float) -> bool:
        """Accumulate real time; return True when a game-hour elapses."""
        if real_dt <= 0:
            return False
        self._accum += real_dt
        advanced = False
        while self._accum >= REAL_SECONDS_PER_GAME_HOUR:
            self._accum -= REAL_SECONDS_PER_GAME_HOUR
            self.advance_hour()
            advanced = True
        return advanced

    def advance_hour(self) -> int:
        self.hour += 1
        if self.hour >= 24:
            self.hour = 0
            self.day += 1
        return self.hour

    def advance(self) -> str:
        """Manual skip (key N): jump one game hour immediately."""
        self._accum = 0.0
        self.advance_hour()
        return self.phase

    def apply_schedule(self, agents: list[Agent], *, skip_busy: bool = True) -> None:
        phase = self.phase
        for agent in agents:
            if skip_busy and agent.busy:
                continue
            table = SCHEDULE.get(agent.home_id, {})
            agent.destination = table.get(phase, DEST_YARD)
