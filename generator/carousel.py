#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROPHOTO Instagram carousel generator.

Usage:
    python carousel.py post.txt [--photos DIR] [--out DIR] [--jpg]

Post file format (UTF-8):

    # ЗЙОМКА НА БІЛОМУ ФОНІ            <- cover title (auto-split if long)
    > від *чорного* до чисто білого     <- cover subline; *word* = red underline
    cta: дізнатись тонкощі **роботи зі світлом**   (optional; default kept)
    photos: a.jpg, b.jpg, c.jpg         <- cover photos (optional)

    ## ЩОБ З БІЛОГО ОТРИМАТИ ТЕМНО-СІРИЙ ФОН   <- section title (= inner slide)
    layout: A | B                       <- optional; default alternates A,B,A,B…
    photos: d.jpg, e.jpg, f.jpg
    1. світло збоку — чим **ближче до фону,** тим світліше фон;
    2. принцип: чим **менше світла потрапляє на фон,** тим він темніший;
    - або просто дефіс замість номера

    **text** = Bold, everything else = Light. If an item has no ** markup the
    key phrase (up to the first , — ( : ;) is bolded automatically.

Photos are looked up in --photos DIR (or next to post.txt). Missing photos
fall back to a dark placeholder.
"""
import os, re, sys, math, argparse, io
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
W, H = 3240, 4050
WHITE = (255, 255, 255, 255)
RED = (235, 66, 59, 255)

# ----------------------------------------------------------------------------
# fonts
# ----------------------------------------------------------------------------
_font_cache = {}
def font(style, size):
    key = (style, size)
    if key not in _font_cache:
        path = os.path.join(ASSETS, "fonts", f"KyivTypeSans-{style}.ttf")
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]

# ----------------------------------------------------------------------------
# assets
# ----------------------------------------------------------------------------
_asset_cache = {}
def svg(name, w=None, h=None):
    """Load pre-rasterized assets/svg/<name>.png and scale to given width (keeps aspect)."""
    key = (name, w, h)
    if key not in _asset_cache:
        im = Image.open(os.path.join(ASSETS, "svg", name + ".png")).convert("RGBA")
        if w and not h: h = round(im.height * w / im.width)
        if h and not w: w = round(im.width * h / im.height)
        if w: im = im.resize((int(w), int(h)), Image.LANCZOS)
        _asset_cache[key] = im
    return _asset_cache[key]

def png(name):
    if name not in _asset_cache:
        _asset_cache[name] = Image.open(os.path.join(ASSETS, name)).convert("RGBA")
    return _asset_cache[name]

def fit(im, w, h):
    return im.resize((int(w), int(h)), Image.LANCZOS)

def logo(w, h):
    """White PROPHOTO logo fitted (aspect kept) into w x h box, centered."""
    im = png("logo_wide.png"); im = im.crop(im.getbbox())
    r = min(w / im.width, h / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    box = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    box.alpha_composite(im, ((box.width - im.width) // 2, (box.height - im.height) // 2))
    return box

# ----------------------------------------------------------------------------
# rich text (Light / Bold runs, uppercase, fixed line height)
# ----------------------------------------------------------------------------
TOKEN_RE = re.compile(r"(\*\*.+?\*\*|\*.+?\*|\n|\s+|[^\s]+)")

def parse_runs(text, base="Light"):
    """'aa **bb** cc' -> [(word, style, underline)] tokens incl. spaces/newlines."""
    runs = []
    for m in TOKEN_RE.finditer(text):
        t = m.group(0)
        if t.startswith("**") and t.endswith("**") and len(t) > 4:
            for sub in TOKEN_RE.finditer(t[2:-2]):
                s = sub.group(0)
                runs.append((s, "Bold", False))
        elif t.startswith("*") and t.endswith("*") and len(t) > 2:
            for sub in TOKEN_RE.finditer(t[1:-1]):
                s = sub.group(0)
                runs.append((s, base, True))
        else:
            runs.append((t, base, False))
    # merge: split spaces properly
    out = []
    for t, st, ul in runs:
        if t == "\n":
            out.append(("\n", st, ul))
        elif t.isspace():
            out.append((" ", st, ul))
        else:
            out.append((t.upper(), st, ul))
    return out

def layout_text(text, size, width, base="Light", align="left"):
    """Return list of lines; each line = (list of (x_offset, token, style, ul), line_width)."""
    runs = parse_runs(text, base)
    space_w = font(base, size).getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    def flush():
        nonlocal cur, cur_w
        # strip trailing space
        while cur and cur[-1][1] == " ":
            cur_w -= cur[-1][4]; cur.pop()
        lines.append((cur, cur_w)); cur, cur_w = [], 0.0
    for t, st, ul in runs:
        if t == "\n":
            flush(); continue
        if t == " ":
            if not cur: continue
            cur.append((cur_w, " ", st, ul, space_w)); cur_w += space_w; continue
        tw = font(st, size).getlength(t)
        if cur and cur_w + tw > width:
            flush()
        cur.append((cur_w, t, st, ul, tw)); cur_w += tw
    if cur: flush()
    return lines

def draw_text(img, x, y, text, size, width, lh=None, base="Light", align="left",
              color=WHITE, return_words=False):
    """Draw wrapped rich text with top-left at (x,y). Returns (height, word_boxes)."""
    lh = lh or size
    lines = layout_text(text, size, width, base, align)
    draw = ImageDraw.Draw(img)
    asc, desc = font("Bold", size).getmetrics()
    baseline_off = (lh - (asc + desc)) / 2 + asc
    boxes = []
    for i, (toks, lw) in enumerate(lines):
        ly = y + i * lh
        if align == "center": lx = x + (width - lw) / 2
        elif align == "right": lx = x + width - lw
        else: lx = x
        for off, t, st, ul, tw in toks:
            if t == " ": continue
            draw.text((lx + off, ly + baseline_off), t, font=font(st, size), fill=color, anchor="ls")
            if ul:
                boxes.append((lx + off, ly, tw, lh))
    return len(lines) * lh, boxes

def text_height(text, size, width, lh=None, base="Light"):
    lh = lh or size
    return len(layout_text(text, size, width, base)) * lh

# ----------------------------------------------------------------------------
# photos
# ----------------------------------------------------------------------------
def load_photo(path):
    if path and os.path.exists(path):
        return Image.open(path).convert("RGB")
    return None

def cover_crop(im, w, h):
    w, h = int(w), int(h)
    if im is None:
        ph = Image.new("RGB", (w, h), (28, 28, 28))
        d = ImageDraw.Draw(ph)
        d.rectangle([0, 0, w - 1, h - 1], outline=(70, 70, 70), width=6)
        d.line([0, 0, w, h], fill=(50, 50, 50), width=4); d.line([w, 0, 0, h], fill=(50, 50, 50), width=4)
        return ph
    r = max(w / im.width, h / im.height)
    im2 = im.resize((max(w, int(im.width * r + 0.5)), max(h, int(im.height * r + 0.5))), Image.LANCZOS)
    l = (im2.width - w) // 2; t = (im2.height - h) // 2
    return im2.crop((l, t, l + w, t + h))

def place_photos(img, boxes, photos):
    """Left, right, then center on top (z-order as in the template)."""
    for i in (0, 2, 1):
        x, y, w, h = boxes[i]
        img.paste(cover_crop(photos[i], w, h), (x, y))

# ----------------------------------------------------------------------------
# constant decorations
# ----------------------------------------------------------------------------
def base_canvas():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    # "БЛІК": soft white glow, top-left, blurred, ~38% opacity
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-425 + 500, -161 + 900, -425 + 2380 - 500, -161 + 5041 - 1500], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(420))
    glow = glow.point(lambda v: int(v * 0.30))
    img.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), (0, 0), glow)
    return img

def dashed_vline(img, x, y0, y1, dash=6, gap=6, width=3, c0=(174, 174, 174), c1=(72, 72, 72), fade=True):
    """Vertical dashed line with vertical gradient (alpha fades to 0 at bottom)."""
    d = ImageDraw.Draw(img)
    y = y0
    while y < y1:
        t = (y - y0) / max(1, (y1 - y0))
        col = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
        a = int(255 * (1 - t)) if fade else 255
        d.line([x, y, x, min(y + dash, y1)], fill=col + (a,), width=width)
        y += dash + gap

def dotted_hline(img, x0, x1, y, dot=1, gap=10, width=3, color=WHITE):
    d = ImageDraw.Draw(img)
    x = x0
    while x < x1:
        d.line([x, y, min(x + dot, x1), y], fill=color, width=width); x += dot + gap

def gradient_hline(img, x0, x1, y, width=3, c0=(255, 255, 255), c1=(153, 153, 153)):
    """Solid line fading to transparent from left to right (template 'Line 5/8')."""
    d = ImageDraw.Draw(img)
    steps = 200
    for i in range(steps):
        t = i / steps
        xa = x0 + (x1 - x0) * t; xb = x0 + (x1 - x0) * (t + 1 / steps)
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)) + (int(255 * (1 - t)),)
        d.line([xa, y, xb, y], fill=col, width=width)

def side_rails(img):
    """Left/right dashed rails with 5 dots (inner slides, layout A)."""
    for x in (193, 3113):
        dashed_vline(img, x, 145, 145 + 3489)
    d = ImageDraw.Draw(img)
    for x, ys in ((193, (1116, 1640, 1785, 2515, 2627)), (3113, (1110, 1630, 1775, 2499, 2610))):
        for y in ys:
            d.ellipse([x - 13, y, x + 13, y + 26], fill=WHITE)

def vertical_lines(img):
    """Cover / last slide: 4 dashed vertical lines."""
    for x in (264, 1116, 2119, 2976):
        dashed_vline(img, x, 0, H)

def bottom_nav(img):
    """Solid line — triangle — dotted line (inner slides)."""
    d = ImageDraw.Draw(img)
    d.line([287, 3860, 1674, 3860], fill=WHITE, width=3)
    d.polygon([(1474, 3860), (1408.75, 3895.5), (1408.75, 3824.5)], fill=WHITE)
    dotted_hline(img, 1783, 2953, 3860)

def paste(img, im, x, y):
    img.alpha_composite(im, (int(round(x)), int(round(y))))

def squiggle_under(img, line_x, line_bottom):
    """Red squiggle at the start of the last title line."""
    sq = svg("squiggle", 685)
    paste(img, sq, line_x, line_bottom + 40)

def title_block(img, title):
    """Centered inner-slide title (Bold 128/128) at template position; returns (last line x, bottom y)."""
    x, y, w, size = 474, 393, 1963, 128
    lines = layout_text(title, size, w, "Bold")
    h, _ = draw_text(img, x, y, title, size, w, base="Bold", align="center")
    toks, lw = lines[-1]
    last_x = x + (w - lw) / 2
    return last_x, y + h

# ----------------------------------------------------------------------------
# list rendering
# ----------------------------------------------------------------------------
SIZE, LH, GAP = 80, 90, 80

def auto_bold(text):
    if "**" in text: return text
    m = re.search(r"[,—–(:;]", text)
    head = text[:m.start()].strip() if m else " ".join(text.split()[:3])
    words = head.split()
    if len(words) > 5: head = " ".join(words[:5])
    if not head: return text
    return "**" + head + "**" + text[len(head):] if text.startswith(head) else text

def item_height(text, width):
    return text_height(text, SIZE, width, LH)

def draw_items(img, items, num_x, text_x, width, y_top, y_bottom, center=True, gap=GAP):
    """Draw numbered items; block vertically centered in [y_top, y_bottom]."""
    hs = [item_height(t, width) for _, t in items]
    total = sum(hs) + gap * (len(items) - 1)
    y = y_top + (y_bottom - y_top - total) / 2 if center else y_top
    for (num, text), h in zip(items, hs):
        draw_text(img, text_x, y, text, SIZE, width, LH)
        if num:
            draw_text(img, num_x, y + (h - LH) / 2, num, SIZE, 400, LH, base="Heavy")
        y += h + gap
    return y

# ----------------------------------------------------------------------------
# slides
# ----------------------------------------------------------------------------
DEFAULT_CTA = "дізнатись тонкощі **роботи зі світлом**"

def render_cover(title, subline, cta, photos):
    img = base_canvas()
    vertical_lines(img)
    # photos
    place_photos(img, ((-29, 872, 1065, 2282), (1103, 872, 1047, 2282), (2217, 872, 1051, 2282)), photos)
    # logo
    paste(img, logo(537, 302), 305, 312)
    # title
    ts = 200
    while ts > 120 and len(layout_text(title, ts, 2008, "Bold")) > 2:
        ts -= 8
    draw_text(img, 1146, 250 + (200 - ts), title, ts, 2008, ts, base="Bold")
    # subline (centered, Light 100, shrinks to fit one line) + red underline under *marked* word
    size = 100
    while size > 60 and len(layout_text(subline, size, 2600, "Light")) > 1:
        size -= 4
    sy = 3276 + (100 - size) // 2
    _, boxes = draw_text(img, 320, sy, subline, size, 2600, size, base="Light", align="center")
    if boxes:
        x0 = min(b[0] for b in boxes); x1 = max(b[0] + b[2] for b in boxes); y = boxes[0][1]
        ul = svg("underline", 556)
        ul = ul.resize((int(x1 - x0 + 60), 62), Image.LANCZOS)
        paste(img, ul, x0 - 30, y + size + 8)
    # CTA row
    draw_text(img, 158, 3637, cta, 64, 900, 64, base="Light")
    dotted_hline(img, 1036, 2358, 3707)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2468, 3653, 2468 + 508, 3653 + 108], radius=54, fill=(217, 217, 217, 255))
    paste(img, svg("pill_arrow", 259), 2594, 3707 - 22)
    return img

def render_inner_A(title, items, photos, two_col=False):
    img = base_canvas()
    side_rails(img)
    lx, bottom = title_block(img, title)
    squiggle_under(img, lx, bottom)
    place_photos(img, ((104, 869, 971, 1265), (1002, 761, 1274, 1537), (2276, 869, 885, 1265)), photos)
    single = block_h(items, REG_A1[2], REG_A1[3]) <= REG_A1[1] - REG_A1[0]
    if single and not two_col:
        draw_items(img, items, 590, 786, REG_A1[2], REG_A1[0], REG_A1[1], gap=REG_A1[3])
        paste(img, png("svg/arrow_up.png"), 2640, 2660)
    else:
        left, right, _, _ = split_two(items)
        draw_items(img, left, 239, 350, 1100, REG_A2[0], REG_A2[1], gap=REG_A2[3])
        draw_items(img, right, 1540, 1648, 1480, REG_A2[0], REG_A2[1], gap=REG_A2[3])
    bottom_nav(img)
    return img

def render_inner_B(title, items, photos):
    img = base_canvas()
    # single left rail with dots
    dashed_vline(img, 436, 0, 3170)
    d = ImageDraw.Draw(img)
    for y in (848, 1331, 1465, 2138, 2241):
        d.ellipse([424, y, 448, y + 24], fill=WHITE)
    lx, bottom = title_block(img, title)
    squiggle_under(img, lx, bottom)
    draw_items(img, items, 752, 936, REG_B[2], REG_B[0], REG_B[1], center=False, gap=REG_B[3])
    gradient_hline(img, -121, 3468, 2253); gradient_hline(img, -121, 3468, 2500)
    paste(img, png("svg/arrow_down.png"), 2849, 1925)
    place_photos(img, ((15, 2610, 1147, 1367), (1067, 2415, 1118, 1520), (2092, 2610, 1179, 1367)), photos)
    bottom_nav(img)
    return img

def render_last():
    img = base_canvas()
    vertical_lines(img)
    txt = ("**пишіть,** чи зрозуміло та корисно\n\n"
           "**серденько,** бо їх приємно бачити\n\n"
           "**зберігайте,** щоб не загубити")
    draw_text(img, 1072, 1480, txt, 96, 1095, 96, base="Light", align="center")
    paste(img, svg("comment", 138), 1303, 2796)
    paste(img, svg("heart", 270), 1474, 2797)
    paste(img, svg("save", 115), 1777, 2797)
    dotted_hline(img, 18, 1174, 3794)
    ImageDraw.Draw(img).line([2014, 3794, 3222, 3794], fill=WHITE, width=3)
    paste(img, logo(600, 157), 1320, 3715)
    return img

# ----------------------------------------------------------------------------
# parsing + pagination
# ----------------------------------------------------------------------------
def parse_post(path):
    post = {"title": "", "subline": "", "cta": DEFAULT_CTA, "photos": [], "sections": []}
    cur = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        s = line.strip()
        if not s: continue
        if s.startswith("## "):
            cur = {"title": s[3:].strip(), "items": [], "photos": [], "layout": None}
            post["sections"].append(cur); continue
        if s.startswith("# "):
            post["title"] = s[2:].strip(); continue
        if s.startswith("> "):
            post["subline"] = s[2:].strip(); continue
        low = s.lower()
        if low.startswith("cta:"):
            post["cta"] = s[4:].strip(); continue
        if low.startswith("photos:"):
            lst = [p.strip() for p in s[7:].split(",") if p.strip()]
            (cur if cur else post)["photos"] = lst; continue
        if low.startswith("layout:") and cur:
            cur["layout"] = s[7:].strip().upper()[:1]; continue
        m = re.match(r"^(\d+)[.)]\s*(.*)$", s)
        if m and cur:
            cur["items"].append((m.group(1) + ".", m.group(2))); continue
        if s.startswith(("- ", "• ")) and cur:
            cur["items"].append(("", s[2:].strip())); continue
        if cur and cur["items"]:               # continuation line
            n, t = cur["items"][-1]; cur["items"][-1] = (n, t + " " + s)
    # cover split: if no subline, split long title
    if not post["subline"]:
        words = post["title"].split()
        if len(words) > 4:
            cut = 3
            post["subline"] = " ".join(words[cut:]); post["title"] = " ".join(words[:cut])
    # auto-bold + auto-number
    for sec in post["sections"]:
        fixed = []
        for i, (n, t) in enumerate(sec["items"], 1):
            fixed.append((n if n else f"{i}.", auto_bold(t)))
        sec["items"] = fixed
    return post

# regions (y_top, y_bottom, text width, gap) taken from the template
REG_A1 = (2375, 3620, 1420, 80)      # layout A, single column
REG_A2 = (2600, 3560, 1100, 120)     # layout A, each of two columns
REG_B  = (880, 2200, 1800, 80)       # layout B, list above photos

def block_h(items, width, gap):
    return sum(item_height(t, width) for _, t in items) + gap * (len(items) - 1)

def split_two(items):
    """Split contiguous items into two columns balanced by height."""
    best = None
    for k in range(1, len(items)):
        a, b = items[:k], items[k:]
        ha, hb = block_h(a, REG_A2[2], REG_A2[3]), block_h(b, REG_A2[2], REG_A2[3])
        score = max(ha, hb)
        if best is None or score < best[0]: best = (score, a, b, ha, hb)
    return best[1], best[2], best[3], best[4]

def page_fits(items, layout):
    if layout == "B":
        return block_h(items, REG_B[2], REG_B[3]) <= REG_B[1] - REG_B[0]
    if block_h(items, REG_A1[2], REG_A1[3]) <= REG_A1[1] - REG_A1[0]:
        return True
    if len(items) >= 4:
        a, b, ha, hb = split_two(items)
        return max(ha, hb) <= REG_A2[1] - REG_A2[0]
    return False

def paginate(items, layout):
    """Fewest pages such that every page fits; among those, the most balanced split."""
    n = len(items)
    if n == 0: return []
    import itertools
    for k in range(1, n + 1):
        best = None
        for cuts in itertools.combinations(range(1, n), k - 1):
            idx = (0,) + cuts + (n,)
            pages = [items[idx[i]:idx[i + 1]] for i in range(k)]
            if all(page_fits(p, layout) for p in pages):
                spread = max(len(p) for p in pages) - min(len(p) for p in pages)
                if best is None or spread < best[0]: best = (spread, pages)
        if best: return best[1]
    return [[it] for it in items]

def build(post, photo_dir):
    def P(names, n=3):
        out = [load_photo(os.path.join(photo_dir, nm)) for nm in names]
        while len(out) < n: out.append(None)
        return out[:n]
    slides = [render_cover(post["title"], post["subline"], post["cta"], P(post["photos"]))]
    pool = list(post["photos"])
    for i, sec in enumerate(post["sections"]):
        layout = sec["layout"] or ("A" if i % 2 == 0 else "B")
        names = sec["photos"] or pool
        photos = P(names)
        pages = paginate(sec["items"], layout)
        for pg in pages:
            if layout == "B":
                slides.append(render_inner_B(sec["title"], pg, photos))
            else:
                slides.append(render_inner_A(sec["title"], pg, photos))
    slides.append(render_last())
    return slides

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post"); ap.add_argument("--photos", default=None)
    ap.add_argument("--out", default="out"); ap.add_argument("--jpg", action="store_true")
    ap.add_argument("--preview", action="store_true", help="also write a contact sheet")
    a = ap.parse_args()
    photo_dir = a.photos or os.path.dirname(os.path.abspath(a.post))
    post = parse_post(a.post)
    slides = build(post, photo_dir)
    os.makedirs(a.out, exist_ok=True)
    paths = []
    for i, s in enumerate(slides, 1):
        rgb = s.convert("RGB")
        p = os.path.join(a.out, f"slide_{i:02d}." + ("jpg" if a.jpg else "png"))
        rgb.save(p, quality=95) if a.jpg else rgb.save(p)
        paths.append(p)
    if a.preview:
        th = [s.convert("RGB").resize((W // 6, H // 6), Image.LANCZOS) for s in slides]
        cols = min(4, len(th)); rows = math.ceil(len(th) / cols)
        sheet = Image.new("RGB", (cols * (W // 6 + 20) + 20, rows * (H // 6 + 20) + 20), (40, 40, 40))
        for i, t in enumerate(th):
            sheet.paste(t, (20 + (i % cols) * (W // 6 + 20), 20 + (i // cols) * (H // 6 + 20)))
        sheet.save(os.path.join(a.out, "preview.jpg"), quality=85)
    print("\n".join(paths))

if __name__ == "__main__":
    main()
