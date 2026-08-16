"""Tile map: cabins, yards, plaza, crops, spawn points."""

from __future__ import annotations

from agents import DEST_CABIN, DEST_PLAZA, DEST_YARD, Agent
from crops import Crop, make_yard_crops

TILE = 32
MAP_W = 28
MAP_H = 18

# Tile kinds
GRASS = 0
PATH = 1
PLAZA = 2
CABIN = 3
SOIL = 4
FENCE = 5

COLORS = {
    GRASS: (86, 140, 72),
    PATH: (196, 168, 120),
    PLAZA: (168, 152, 120),
    CABIN: (120, 78, 52),
    SOIL: (110, 80, 48),
    FENCE: (90, 70, 50),
}


def _rect_fill(grid: list[list[int]], x0: int, y0: int, w: int, h: int, kind: int) -> None:
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            if 0 <= x < MAP_W and 0 <= y < MAP_H:
                grid[y][x] = kind


def build_grid() -> list[list[int]]:
    grid = [[GRASS for _ in range(MAP_W)] for _ in range(MAP_H)]
    # plaza center
    _rect_fill(grid, 10, 6, 8, 6, PLAZA)
    # paths
    _rect_fill(grid, 4, 8, 6, 2, PATH)
    _rect_fill(grid, 18, 8, 6, 2, PATH)
    _rect_fill(grid, 13, 2, 2, 4, PATH)
    _rect_fill(grid, 13, 12, 2, 4, PATH)

    # cabin he (left)
    _rect_fill(grid, 2, 3, 3, 3, CABIN)
    _rect_fill(grid, 2, 6, 5, 4, SOIL)
    # cabin mai (right)
    _rect_fill(grid, 23, 3, 3, 3, CABIN)
    _rect_fill(grid, 21, 6, 5, 4, SOIL)
    # cabin moss (bottom)
    _rect_fill(grid, 12, 14, 3, 3, CABIN)
    _rect_fill(grid, 16, 14, 5, 3, SOIL)

    # light fence accents
    for x in range(2, 7):
        grid[5][x] = FENCE
    for x in range(21, 26):
        grid[5][x] = FENCE
    return grid


HOME_POINTS = {
    "he": {
        DEST_CABIN: (3.5 * TILE, 4.5 * TILE),
        DEST_YARD: (4.5 * TILE, 7.5 * TILE),
        DEST_PLAZA: (12.0 * TILE, 8.5 * TILE),
    },
    "mai": {
        DEST_CABIN: (24.5 * TILE, 4.5 * TILE),
        DEST_YARD: (23.5 * TILE, 7.5 * TILE),
        DEST_PLAZA: (15.5 * TILE, 8.5 * TILE),
    },
    "moss": {
        DEST_CABIN: (13.5 * TILE, 15.5 * TILE),
        DEST_YARD: (18.0 * TILE, 15.0 * TILE),
        DEST_PLAZA: (14.0 * TILE, 10.5 * TILE),
    },
}

CROP_TILES = {
    "he": [(2, 7), (3, 7), (4, 7), (5, 7), (2, 8), (3, 8)],
    "mai": [(22, 7), (23, 7), (24, 7), (25, 7), (22, 8), (23, 8)],
    "moss": [(16, 15), (17, 15), (18, 15), (19, 15), (16, 16), (17, 16)],
}


class World:
    def __init__(self) -> None:
        self.tile = TILE
        self.grid = build_grid()
        self.crops: list[Crop] = []
        for owner, tiles in CROP_TILES.items():
            self.crops.extend(make_yard_crops(owner, tiles))
        self.agents = [
            Agent(
                name="小禾",
                color=(220, 96, 96),
                home_id="he",
                x=HOME_POINTS["he"][DEST_YARD][0],
                y=HOME_POINTS["he"][DEST_YARD][1],
                destination=DEST_YARD,
                target_xy=HOME_POINTS["he"][DEST_YARD],
            ),
            Agent(
                name="阿麦",
                color=(96, 140, 220),
                home_id="mai",
                x=HOME_POINTS["mai"][DEST_CABIN][0],
                y=HOME_POINTS["mai"][DEST_CABIN][1],
                destination=DEST_CABIN,
                target_xy=HOME_POINTS["mai"][DEST_CABIN],
            ),
            Agent(
                name="青苔",
                color=(80, 180, 120),
                home_id="moss",
                x=HOME_POINTS["moss"][DEST_PLAZA][0],
                y=HOME_POINTS["moss"][DEST_PLAZA][1],
                destination=DEST_PLAZA,
                target_xy=HOME_POINTS["moss"][DEST_PLAZA],
            ),
        ]
        self.player_x = 14.0 * TILE
        self.player_y = 4.0 * TILE
        self.player_speed = 140.0
        self.harvest_count = 0

    def pixel_size(self) -> tuple[int, int]:
        return MAP_W * self.tile, MAP_H * self.tile

    def home_points(self, home_id: str) -> dict[str, tuple[float, float]]:
        return HOME_POINTS[home_id]

    def crop_xy(self, crop: Crop) -> tuple[float, float]:
        return (crop.tile_x + 0.5) * self.tile, (crop.tile_y + 0.5) * self.tile

    def crops_for(self, owner: str) -> list[Crop]:
        return [c for c in self.crops if c.owner == owner and not c.harvested]

    def sync_agent_targets(self, *, skip_busy: bool = True) -> None:
        for agent in self.agents:
            if skip_busy and agent.busy:
                continue
            points = HOME_POINTS[agent.home_id]
            agent.target_xy = points[agent.destination]

    def agents_on_plaza(self) -> list[Agent]:
        return [
            a
            for a in self.agents
            if a.destination == DEST_PLAZA and a.at_destination()
        ]

    def nearest_crop(self, px: float, py: float, radius: float = 40.0) -> Crop | None:
        best: Crop | None = None
        best_d = radius
        for crop in self.crops:
            if crop.harvested:
                continue
            cx = (crop.tile_x + 0.5) * self.tile
            cy = (crop.tile_y + 0.5) * self.tile
            d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            if d < best_d:
                best_d = d
                best = crop
        return best

    def nearest_agent(self, px: float, py: float, radius: float = 48.0) -> Agent | None:
        best: Agent | None = None
        best_d = radius
        for agent in self.agents:
            d = ((agent.x - px) ** 2 + (agent.y - py) ** 2) ** 0.5
            if d < best_d:
                best_d = d
                best = agent
        return best

    def interact_crop(self) -> str:
        crop = self.nearest_crop(self.player_x, self.player_y)
        if crop is None:
            return ""
        if crop.ready:
            if crop.harvest():
                self.harvest_count += 1
                crop.reset_plant()
                return "harvested"
            return ""
        if crop.water():
            return "watered"
        return ""

    def update_player(self, dt: float, keys) -> None:
        import pygame

        dx = dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += 1
        if dx == 0 and dy == 0:
            return
        length = (dx * dx + dy * dy) ** 0.5
        self.player_x += dx / length * self.player_speed * dt
        self.player_y += dy / length * self.player_speed * dt
        w, h = self.pixel_size()
        self.player_x = max(12.0, min(w - 12.0, self.player_x))
        self.player_y = max(12.0, min(h - 12.0, self.player_y))
