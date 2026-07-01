#!/usr/bin/env python3
from PIL import Image
from pathlib import Path
import sys

INPUT_DIR = Path('assets/images')
OUTPUT_DIR = Path('static/optimized')
WIDTHS = [400, 800, 1200]
QUALITY = 80

def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def process_image(p: Path):
    try:
        img = Image.open(p)
    except Exception as e:
        print(f"Skipping {p}: {e}")
        return
    name = p.stem
    for w in WIDTHS:
        ratio = w / img.width
        h = int(img.height * ratio)
        resized = img.resize((w, h), Image.LANCZOS)
        out = OUTPUT_DIR / f"{name}-{w}.webp"
        resized.save(out, 'WEBP', quality=QUALITY)
        print(f"Wrote {out}")

def main():
    ensure_dirs()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else INPUT_DIR
    if not src.exists():
        print(f"Source directory {src} does not exist. Place images in {INPUT_DIR}.")
        return
    images = list(src.glob('*.*'))
    if not images:
        print(f"No images found in {src}")
        return
    for p in images:
        process_image(p)

if __name__ == '__main__':
    main()
