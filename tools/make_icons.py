#!/usr/bin/env python3
"""Generate Super Duper Lite YT icons using only Pillow.

Outputs:
    --svg PATH            write the SVG (static, gradient play button)
    --png PATH            write a single PNG
    --size N              size for --png (default 256)
    --output-dir DIR      write icon-24.png, icon-64.png, icon-256.png
    --pi-apps-dir DIR     write icon-24.png, icon-64.png (Pi-Apps folder)

Requires Pillow. Install with:  python3 -m pip install --user Pillow
"""
from __future__ import annotations

import argparse
import os
import sys

SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
    'width="256" height="256">\n'
    '  <defs>\n'
    '    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">\n'
    '      <stop offset="0" stop-color="#3b82f6"/>\n'
    '      <stop offset="1" stop-color="#1d4ed8"/>\n'
    '    </linearGradient>\n'
    '  </defs>\n'
    '  <rect width="256" height="256" rx="56" fill="#0f1115"/>\n'
    '  <rect x="24" y="56" width="208" height="144" rx="32" fill="url(#g)"/>\n'
    '  <path d="M108 96 L108 160 L164 128 Z" fill="#ffffff"/>\n'
    '</svg>\n'
)


def draw_icon(size: int):
    """Return a Pillow image of the icon at *size* pixels."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = max(2, size // 8)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius,
                        fill=(15, 17, 21, 255))
    pad = max(2, size // 10)
    inner_radius = max(2, size // 8)
    d.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=inner_radius, fill=(59, 130, 246, 255),
    )
    cx, cy = size // 2, size // 2
    tri = max(6, size * 3 // 8)
    points = [
        (cx - tri // 2 + max(1, size // 32), cy - tri // 2),
        (cx - tri // 2 + max(1, size // 32), cy + tri // 2),
        (cx + tri // 2, cy),
    ]
    d.polygon(points, fill=(255, 255, 255, 255))
    return img


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate sdlyt icons")
    parser.add_argument("--svg", help="Write SVG to this path")
    parser.add_argument("--png", help="Write a single PNG to this path")
    parser.add_argument("--size", type=int, default=256,
                        help="Size for --png (default 256)")
    parser.add_argument("--output-dir", help="Write icon-24/64/256 PNGs here")
    parser.add_argument("--pi-apps-dir", help="Write icon-24.png and icon-64.png here")
    args = parser.parse_args(argv)

    if args.svg:
        os.makedirs(os.path.dirname(os.path.abspath(args.svg)), exist_ok=True)
        with open(args.svg, "w", encoding="utf-8") as handle:
            handle.write(SVG)
        print("wrote", args.svg)

    try:
        import PIL  # noqa: F401
        have_pil = True
    except Exception:
        have_pil = False

    if args.png:
        if not have_pil:
            print("Pillow not installed; skipping", args.png)
        else:
            os.makedirs(os.path.dirname(os.path.abspath(args.png)), exist_ok=True)
            draw_icon(args.size).save(args.png, "PNG")
            print("wrote", args.png)

    if args.output_dir:
        if not have_pil:
            print("Pillow not installed; skipping PNGs in", args.output_dir)
        else:
            os.makedirs(args.output_dir, exist_ok=True)
            for size in (24, 64, 256):
                path = os.path.join(args.output_dir, "icon-%d.png" % size)
                draw_icon(size).save(path, "PNG")
                print("wrote", path)

    if args.pi_apps_dir:
        if not have_pil:
            print("Pillow not installed; skipping Pi-Apps icons")
        else:
            os.makedirs(args.pi_apps_dir, exist_ok=True)
            for size in (24, 64):
                path = os.path.join(args.pi_apps_dir, "icon-%d.png" % size)
                draw_icon(size).save(path, "PNG")
                print("wrote", path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
