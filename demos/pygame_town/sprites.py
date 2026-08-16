"""Load Kenney CC0 tiles + character sprites for pygame_town."""

from __future__ import annotations

from pathlib import Path

import pygame

from world import CABIN, FENCE, GRASS, PATH, PLAZA, SOIL

ASSETS = Path(__file__).resolve().parent / "assets"
TILE_DIR = ASSETS / "tiles"
CHAR_DIR = ASSETS / "chars"
PROP_DIR = ASSETS / "props"

_TILE_FILES = {
    GRASS: "grass.png",
    PATH: "path.png",
    PLAZA: "plaza.png",
    CABIN: "cabin.png",
    SOIL: "soil.png",
    FENCE: "fence.png",
}


class SpriteBank:
    def __init__(self, tile_size: int = 32) -> None:
        self.tile_size = tile_size
        self.tiles: dict[int, pygame.Surface] = {}
        self.chars: dict[str, pygame.Surface] = {}
        self.crops: dict[str, pygame.Surface] = {}
        self.tree: pygame.Surface | None = None
        self.ready = False
        self._load()

    def _scale(self, surface: pygame.Surface) -> pygame.Surface:
        if surface.get_width() == self.tile_size and surface.get_height() == self.tile_size:
            return surface.convert_alpha()
        return pygame.transform.smoothscale(
            surface,
            (self.tile_size, self.tile_size),
        ).convert_alpha()

    def _load(self) -> None:
        missing = [name for name in _TILE_FILES.values() if not (TILE_DIR / name).exists()]
        if missing:
            raise FileNotFoundError(
                f"Missing tile assets under {TILE_DIR}: {missing}. "
                "Run: python demos/pygame_town/assets/_stage_assets.py"
            )
        for kind, name in _TILE_FILES.items():
            self.tiles[kind] = self._scale(pygame.image.load(str(TILE_DIR / name)))

        for name in ("player", "he", "mai", "moss"):
            path = CHAR_DIR / f"{name}.png"
            if not path.exists():
                raise FileNotFoundError(path)
            self.chars[name] = self._scale(pygame.image.load(str(path)))

        for stage in ("dry", "wet", "ready"):
            path = PROP_DIR / f"crop_{stage}.png"
            if not path.exists():
                raise FileNotFoundError(path)
            self.crops[stage] = self._scale(pygame.image.load(str(path)))

        tree_path = TILE_DIR / "tree.png"
        if tree_path.exists():
            self.tree = self._scale(pygame.image.load(str(tree_path)))
        self.ready = True

    def blit_tile(self, screen: pygame.Surface, kind: int, x: int, y: int) -> None:
        surf = self.tiles.get(kind)
        if surf is None:
            return
        screen.blit(surf, (x, y))

    def blit_char(
        self,
        screen: pygame.Surface,
        key: str,
        cx: float,
        cy: float,
        *,
        highlight: bool = False,
    ) -> None:
        surf = self.chars.get(key)
        if surf is None:
            return
        rect = surf.get_rect(center=(int(cx), int(cy)))
        screen.blit(surf, rect)
        if highlight:
            pygame.draw.circle(screen, (255, 255, 255), (int(cx), int(cy)), rect.width // 2 + 2, 2)

    def blit_crop(self, screen: pygame.Surface, stage: str, cx: float, cy: float) -> None:
        surf = self.crops.get(stage)
        if surf is None:
            return
        rect = surf.get_rect(center=(int(cx), int(cy)))
        screen.blit(surf, rect)
