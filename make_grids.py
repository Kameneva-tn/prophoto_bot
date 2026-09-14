# -*- coding: utf-8 -*-
"""Збирає превʼю у вигляді Instagram-сітки з номерами: previews/grid_covers.jpg та grid_t<N>.jpg"""
import os, glob, json
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); PREV = os.path.join(HERE, "previews")
FONT = os.path.join(HERE, "generator", "assets", "fonts", "KyivTypeSans-Bold.ttf")
CELL_W, CELL_H, GAP, COLS = 360, 450, 6, 3

def badge(draw, x, y, text, size=44):
    f = ImageFont.truetype(FONT, size); tw = draw.textlength(text, font=f); pad = 18
    w, h = int(tw + pad * 2), size + pad
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(235, 66, 59))
    draw.text((x + pad, y + pad // 2 - 2), text, font=f, fill="white")

def grid(paths, labels, out, top_label=None):
    rows = -(-len(paths) // COLS)
    W = COLS * CELL_W + (COLS - 1) * GAP; H = rows * CELL_H + (rows - 1) * GAP
    im = Image.new("RGB", (W, H), (18, 18, 18)); d = ImageDraw.Draw(im)
    for i, p in enumerate(paths):
        c, r = i % COLS, i // COLS; x, y = c * (CELL_W + GAP), r * (CELL_H + GAP)
        th = Image.open(p).convert("RGB").resize((CELL_W, CELL_H), Image.LANCZOS); im.paste(th, (x, y))
        badge(d, x + 14, y + 14, labels[i])
    im.save(out, quality=88); return out

if __name__ == "__main__":
    T = json.load(open(os.path.join(HERE, "templates.json"), encoding="utf-8"))
    grid([os.path.join(PREV, f"t{t}_s01.jpg") for t in T], [t for t in T], os.path.join(PREV, "grid_covers.jpg"))
    for t in T:
        paths = sorted(glob.glob(os.path.join(PREV, f"t{t}_s*.jpg")))
        grid(paths, [f"{t}.{i+1}" for i in range(len(paths))], os.path.join(PREV, f"grid_t{t}.jpg"))
    print("grids ok")
