"""Day phases and per-villager destination schedules."""

from __future__ import annotations

from agents import DEST_CABIN, DEST_PLAZA, DEST_YARD, Agent

PHASES = ("morning", "noon", "evening")

# home_id -> phase -> destination
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


class DayClock:
    def __init__(self) -> None:
        self.phase_index = 0
        self.day = 1

    @property
    def phase(self) -> str:
        return PHASES[self.phase_index]

    def advance(self) -> str:
        self.phase_index += 1
        if self.phase_index >= len(PHASES):
            self.phase_index = 0
            self.day += 1
        return self.phase

    def apply_schedule(self, agents: list[Agent]) -> None:
        phase = self.phase
        for agent in agents:
            table = SCHEDULE.get(agent.home_id, {})
            agent.destination = table.get(phase, DEST_YARD)
