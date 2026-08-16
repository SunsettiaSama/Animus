"""Stage Kenney CC0 tiles + generate simple top-down character sprites."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
RAW_PNG = ROOT / "raw" / "rpg" / "PNG"
TILES = ROOT / "tiles"
CHARS = ROOT / "chars"
PROPS = ROOT / "props"
SIZE = 32


def load_tile(num: str, size: int = SIZE) -> Image.Image:
    path = RAW_PNG / f"rpgTile{num}.png"
    im = Image.open(path).convert("RGBA")
    return im.resize((size, size), Image.Resampling.LANCZOS)


def save(im: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest)


def solidify_dirt(im: Image.Image, dirt=(180, 145, 85, 255)) -> Image.Image:
    """Replace grassy pixels so path/soil tiles read as continuous dirt."""
    out = im.copy()
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 20:
                continue
            if g > r + 20 and g > b:
                px[x, y] = dirt
    return out


def make_char(body: tuple[int, int, int], hair: tuple[int, int, int], outline=(40, 30, 20, 255)) -> Image.Image:
    """Top-down chibi: shadow + body + head + hair — clearer than a flat circle."""
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((8, 22, 24, 30), fill=(0, 0, 0, 70))
    d.ellipse((7, 12, 25, 28), fill=outline)
    d.ellipse((8, 13, 24, 27), fill=body + (255,))
    d.ellipse((9, 4, 23, 18), fill=outline)
    d.ellipse((10, 5, 22, 17), fill=(240, 210, 180, 255))
    d.ellipse((10, 3, 22, 11), fill=hair + (255,))
    d.rectangle((13, 10, 14, 12), fill=(30, 30, 40, 255))
    d.rectangle((18, 10, 19, 12), fill=(30, 30, 40, 255))
    return im


def make_crop(stage: str) -> Image.Image:
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((10, 22, 22, 28), fill=(0, 0, 0, 60))
    if stage == "dry":
        d.rectangle((14, 14, 18, 24), fill=(120, 90, 50, 255))
        d.ellipse((11, 8, 21, 16), fill=(150, 120, 60, 255))
    elif stage == "wet":
        d.rectangle((14, 14, 18, 24), fill=(90, 120, 160, 255))
        d.ellipse((11, 7, 21, 16), fill=(100, 150, 200, 255))
    else:
        d.rectangle((14, 12, 18, 24), fill=(70, 120, 50, 255))
        d.ellipse((8, 4, 24, 18), fill=(60, 180, 70, 255))
        d.ellipse((12, 6, 20, 14), fill=(90, 210, 90, 255))
    return im


def main() -> None:
    if not RAW_PNG.exists():
        raise SystemExit(f"missing Kenney pack at {RAW_PNG}")

    mapping = {
        "grass": "019",
        "plaza": "047",
        "fence": "161",
        "cabin_wall": "064",
        "cabin_roof": "100",
        "cabin_door": "189",
        "tree": "175",
        "bush": "179",
        "barrel": "215",
    }
    for name, num in mapping.items():
        save(load_tile(num), TILES / f"{name}.png")

    path = solidify_dirt(load_tile("006"), dirt=(176, 140, 78, 255))
    soil = solidify_dirt(load_tile("005"), dirt=(150, 110, 60, 255))
    save(path, TILES / "path.png")
    save(soil, TILES / "soil.png")

    cabin = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    wall = load_tile("048")  # beige masonry block
    roof = load_tile("108")  # roof peak / stair-like roof piece
    door = load_tile("189").resize((12, 14), Image.Resampling.LANCZOS)
    cabin.paste(wall, (0, 0), wall)
    cabin.paste(roof, (0, -6), roof)
    cabin.paste(door, (10, 16), door)
    save(cabin, TILES / "cabin.png")

    chars = {
        "player": ((240, 220, 120), (90, 60, 40)),
        "he": ((220, 96, 96), (60, 40, 40)),
        "mai": ((96, 140, 220), (40, 50, 80)),
        "moss": ((80, 180, 120), (30, 70, 40)),
    }
    for name, (body, hair) in chars.items():
        save(make_char(body, hair), CHARS / f"{name}.png")

    for stage in ("dry", "wet", "ready"):
        save(make_crop(stage), PROPS / f"crop_{stage}.png")

    license_src = ROOT / "raw" / "rpg" / "license.txt"
    if license_src.exists():
        shutil.copy2(license_src, ROOT / "KENNEY_LICENSE.txt")

    print("staged tiles", sorted(p.name for p in TILES.glob("*.png")))
    print("staged chars", sorted(p.name for p in CHARS.glob("*.png")))
    print("staged props", sorted(p.name for p in PROPS.glob("*.png")))


if __name__ == "__main__":
    main()
