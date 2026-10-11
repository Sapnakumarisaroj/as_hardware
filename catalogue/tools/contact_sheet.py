"""Tiles a folder's pictures into numbered contact sheets for visual review (local tool, not shipped).

    python catalogue/tools/contact_sheet.py "<folder under assets/as-hardware-images>" OUT_DIR [per_sheet]
"""

import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2] / "assets" / "as-hardware-images"
TILE, LABEL, COLS = 220, 54, 4


def main() -> None:
    folder, out = ROOT / sys.argv[1], Path(sys.argv[2])
    per_sheet = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png"})
    for start in range(0, len(files), per_sheet):
        chunk = files[start : start + per_sheet]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * TILE, rows * (TILE + LABEL)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(chunk):
            x, y = (i % COLS) * TILE, (i // COLS) * (TILE + LABEL)
            try:
                img = Image.open(path).convert("RGB")
                img.thumbnail((TILE - 10, TILE - 10))
                sheet.paste(img, (x + (TILE - img.width) // 2, y + (TILE - img.height) // 2))
            except Exception as exc:  # noqa: BLE001
                draw.text((x + 5, y + 5), f"unreadable: {exc}", fill="red")
            label = f"{start + i + 1}. {path.stem}"
            draw.multiline_text((x + 3, y + TILE), "\n".join(textwrap.wrap(label, 36)[:4]), fill="black")
        name = out / f"{folder.name[:20]}_{start // per_sheet + 1}.png".replace(" ", "_").replace("&", "and")
        sheet.save(name)
        print(name)


if __name__ == "__main__":
    main()
