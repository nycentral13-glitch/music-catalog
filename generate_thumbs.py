#!/usr/bin/env python3
"""
Generate 300x300 thumbnails for all cover art images.
Run once on the Pi: python3 generate_thumbs.py
Incremental — skips covers that already have a thumbnail.
"""
import os
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow not installed. Run: pip3 install Pillow --break-system-packages")
    raise SystemExit(1)

BASE_DIR   = Path(__file__).parent
COVERS_DIR = BASE_DIR / 'covers'
THUMBS_DIR = BASE_DIR / 'covers_thumb'
THUMB_SIZE = (300, 300)

THUMBS_DIR.mkdir(exist_ok=True)

covers = list(COVERS_DIR.glob('*'))
total  = len(covers)
done   = skipped = errors = 0

for i, src in enumerate(covers, 1):
    if not src.is_file():
        continue
    dest = THUMBS_DIR / src.name
    if dest.exists():
        skipped += 1
        continue
    try:
        with Image.open(src) as img:
            img = img.convert('RGB')
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            img.save(dest, 'JPEG', quality=82, optimize=True)
        done += 1
        if done % 100 == 0:
            print(f"  {done + skipped}/{total} processed...")
    except Exception as e:
        print(f"  ERROR {src.name}: {e}")
        errors += 1

print(f"\nDone: {done} generated, {skipped} skipped, {errors} errors")
