"""Villager entities and movement toward schedule targets."""

from __future__ import annotations

from dataclasses import dataclass, field

DEST_CABIN = "cabin"
DEST_YARD = "yard"
DEST_PLAZA = "plaza"


@dataclass
class Agent:
    name: str
    color: tuple[int, int, int]
    home_id: str
    x: float
    y: float
    destination: str = DEST_YARD
    speed: float = 90.0
    bubble: str = ""
    bubble_ttl: float = 0.0
    talking: bool = False
    target_xy: tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))

    def set_bubble(self, text: str, ttl: float = 6.0) -> None:
        self.bubble = text.strip()
        self.bubble_ttl = ttl
        self.talking = bool(self.bubble)

    def clear_bubble(self) -> None:
        self.bubble = ""
        self.bubble_ttl = 0.0
        self.talking = False

    def update(self, dt: float) -> None:
        if self.bubble_ttl > 0:
            self.bubble_ttl -= dt
            if self.bubble_ttl <= 0:
                self.clear_bubble()
        tx, ty = self.target_xy
        dx = tx - self.x
        dy = ty - self.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < 2.0:
            self.x, self.y = tx, ty
            return
        step = self.speed * dt
        if step >= dist:
            self.x, self.y = tx, ty
            return
        self.x += dx / dist * step
        self.y += dy / dist * step

    def at_destination(self, radius: float = 18.0) -> bool:
        tx, ty = self.target_xy
        dx = tx - self.x
        dy = ty - self.y
        return (dx * dx + dy * dy) ** 0.5 <= radius

    def tile_pos(self, tile_size: int) -> tuple[int, int]:
        return int(self.x // tile_size), int(self.y // tile_size)
