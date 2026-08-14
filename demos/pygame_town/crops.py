"""Individual crops: dry / watered / ready; water and harvest."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Crop:
    tile_x: int
    tile_y: int
    owner: str
    watered: bool = False
    ready: bool = False
    harvested: bool = False

    def water(self) -> bool:
        if self.harvested or self.ready:
            return False
        if self.watered:
            return False
        self.watered = True
        self.ready = True
        return True

    def harvest(self) -> bool:
        if self.harvested or not self.ready:
            return False
        self.harvested = True
        self.ready = False
        self.watered = False
        return True

    def reset_plant(self) -> None:
        self.watered = False
        self.ready = False
        self.harvested = False


def make_yard_crops(owner: str, tiles: list[tuple[int, int]]) -> list[Crop]:
    return [Crop(tile_x=x, tile_y=y, owner=owner) for x, y in tiles]
