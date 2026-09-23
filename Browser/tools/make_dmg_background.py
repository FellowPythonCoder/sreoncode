"""Render the Sreon disk-image artwork (plus a simulated-Finder preview).

The .dmg a user opens is a Finder window, and dmgbuild paints our PNG behind
the icons -- so the artwork has to know exactly where Finder puts them:

    dmgbuild icon_locations / create-dmg "--icon name x y"
        -> (x, y) of the TOP-LEFT corner of the icon, in POINTS, measured from
           the top-left of the window's content area.
        -> Finder draws the item label a few points under the icon.

`layout()` is the single source of truth: tools/build.py imports these same
numbers and hands them to dmgbuild, so the artwork and the icon positions can
never drift apart.  A 1x PNG sized to the window is written for 1x displays and
a @2x PNG for Retina; dmgbuild merges the pair into one multi-resolution TIFF.

Type: DM Sans, the face Sreon's own site uses (converted from the repo woff2,
see tools/fonts).  Its latin subset has no arrow glyph, so path separators are
drawn as real chevrons instead of typed as characters.

    python3 Browser/tools/make_dmg_background.py             # write the PNGs
    python3 Browser/tools/make_dmg_background.py --preview    # fake icons+labels
    python3 Browser/tools/make_dmg_background.py --convert-fonts
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TOOLS = Path(__file__).resolve().parent
BROWSER = TOOLS.parent
ASSETS = BROWSER / "assets"
FONT_CANDIDATES = [TOOLS / "fonts", Path("/usr/share/fonts/truetype/dejavu")]

# --------------------------------------------------------------- geometry ----

WINDOW = (680, 486)   # Finder content area, in points
ICON_SIZE = 128       # Finder icon size, in points
TEXT_SIZE = 13        # Finder label size, in points

CHIP = (44, 112, 236, 336)      # panel behind Sreon.app
DROP = (444, 112, 636, 336)     # dashed drop target around the Applications alias
CARD = (44, 348, 636, 474)      # "if macOS says..." instructions
ARROW_Y = 210                    # vertical centre of the icons; icon_y = this - 64
LABEL_ROW = 300                  # "drop here" baseline row, inside the panels

# ----------------------------------------------------------------- palette ---

CREAM_TOP = (253, 250, 245)
CREAM_BOTTOM = (244, 238, 228)
PURPLE = (92, 67, 160)
PURPLE_SOFT = (114, 92, 182)
LAVENDER_EDGE = (222, 212, 245)
INK = (35, 27, 56)
MUTED = (112, 102, 133)
CARD_FILL = (255, 253, 250)
CARD_EDGE = (232, 225, 243)

# value = faux-weight stroke radius as a fraction of the font size
_NAMES = {"regular": ("DMSans-Regular", 0.0), "medium": ("DMSans-Medium", 0.0),
          "semibold": ("DMSans-Medium", 0.010), "bold": ("DMSans-Medium", 0.018),
          "dejavu-bold": ("DejaVuSans-Bold", 0.0)}
_FONT_CACHE = {}


def rgba(color, alpha=255):
    return (int(color[0]), int(color[1]), int(color[2]), int(alpha))


def font(weight, size, scale):
    """Return (ImageFont, stroke_width_px) for a role name."""
    key = (weight, round(size * scale))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    name, ratio = _NAMES[weight]
    loaded = None
    for folder in FONT_CANDIDATES:
        for suffix in (".ttf", ".otf"):
            path = folder / f"{name}{suffix}"
            if path.is_file():
                try:
                    loaded = ImageFont.truetype(str(path), key[1])
                except OSError:
                    loaded = None
                break
        if loaded:
            break
    stroke = 0 if ratio <= 0 else max(1, int(round(ratio * size * scale)))
    if loaded is None:
        raise SystemExit(f"missing font {name}.ttf -- run: python3 {__file__} --convert-fonts")
    _FONT_CACHE[key] = (loaded, stroke)
    return loaded, stroke


def text(draw, xy, value, *, size, weight="regular", color=INK, scale=1.0,
         anchor=None, tracking=0.0):
    """Draw text (letter-spacing optional) and return the run width in points."""
    f, stroke = font(weight, size, scale)
    ink = rgba(color)
    x, y = xy[0] * scale, xy[1] * scale
    if tracking <= 0:
        draw.text((x, y), value, font=f, fill=ink, anchor=anchor,
                  stroke_width=stroke, stroke_fill=ink)
        return (draw.textlength(value, font=f) + 2 * stroke) / scale
    widths = [draw.textlength(c, font=f) + 2 * stroke for c in value]
    total = sum(widths) + tracking * scale * (len(value) - 1)
    cursor = x - total if anchor else x
    for char, width in zip(value, widths):
        draw.text((cursor, y), char, font=f, fill=ink, stroke_width=stroke, stroke_fill=ink)
        cursor += width + tracking * scale
    return total / scale


def fits(draw, value, *, size, weight="regular", scale=1.0, tracking=0.0):
    f, stroke = font(weight, size, scale)
    total = sum(draw.textlength(c, font=f) + 2 * stroke for c in value)
    return total / scale + tracking * (len(value) - 1) if value else 0.0


# ------------------------------------------------------------------ pieces ---

def paint_base(size, scale):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    height = size[1]
    for y in range(height):
        t = y / max(1, height - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(CREAM_TOP, CREAM_BOTTOM))
        draw.line([(0, y), (size[0], y)], fill=colour + (255,))
    # a faint dot grid keeps the large flat areas from banding on cheap displays
    dots = Image.new("RGBA", size, (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    step = max(6, int(round(10 * scale)))
    for row, yy in enumerate(range(0, height, step)):
        offset = (step // 2) if row % 2 else 0
        for xx in range(offset, size[0], step):
            dd.point((xx, yy), fill=(255, 255, 255, 22))
    img.alpha_composite(dots)
    return img


def paint_glow(img, center, radius, scale, *, color=PURPLE, alpha=44):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = center[0] * scale, center[1] * scale
    r = radius * scale
    steps = 24
    for i in range(steps, 0, -1):
        frac = i / steps
        shade = int(alpha * (1 - frac) ** 2.4)
        if shade > 0:
            draw.ellipse([cx - r * frac, cy - r * frac, cx + r * frac, cy + r * frac],
                         fill=rgba(color, shade))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(int(round(15 * scale)))))


def soft_shadow(img, box, radius, scale, *, color=PURPLE, alpha=40, blur=10, offset=(0, 6)):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = [int(round(v * scale)) for v in box]
    ox, oy = [int(round(v * scale)) for v in offset]
    draw.rounded_rectangle([x0 + ox, y0 + oy, x1 + ox, y1 + oy],
                           radius=int(round(radius * scale)), fill=rgba(color, alpha))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(int(round(blur * scale)))))


def panel(img, box, radius, scale, *, fill=None, edge=None, edge_width=1.0):
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = [int(round(v * scale)) for v in box]
    r = int(round(radius * scale))
    if fill is not None:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)
    if edge is not None:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, outline=rgba(edge),
                               width=max(1, int(round(edge_width * scale))))


def rounded_rect_path(box, radius, samples_per_arc=16):
    """Closed clockwise polyline around a rounded rectangle (arcs sampled)."""
    x0, y0, x1, y1 = box
    r = max(0.1, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    path = []

    def arc(cx, cy, a0, a1):
        for i in range(samples_per_arc + 1):
            angle = math.radians(a0 + (a1 - a0) * i / samples_per_arc)
            path.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    arc(x0 + r, y0 + r, 180, 270)
    arc(x1 - r, y0 + r, 270, 360)
    arc(x1 - r, y1 - r, 0, 90)
    arc(x0 + r, y1 - r, 90, 180)
    path.append(path[0])
    return path


def dash_round_rect(img, box, radius, scale, color, width, dash, gap):
    """Even dashes walked along the real perimeter (Pillow has no dash support)."""
    draw = ImageDraw.Draw(img)
    path = rounded_rect_path(tuple(v * scale for v in box), radius * scale)
    lengths, total = [0.0], 0.0
    for a, b in zip(path, path[1:]):
        total += math.dist(a, b)
        lengths.append(total)
    if total <= 0:
        return
    weight = max(1, int(round(width * scale)))
    ink = rgba(color)
    travelled = 0.0
    dash_px, gap_px = dash * scale, gap * scale

    def point_at(distance):
        distance = min(max(distance, 0.0), total)
        index = 0
        while index < len(lengths) - 2 and lengths[index + 1] < distance:
            index += 1
        span = lengths[index + 1] - lengths[index] or 1
        t = (distance - lengths[index]) / span
        a, b = path[index], path[index + 1]
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    while travelled < total - dash_px * 0.25:
        stop = min(travelled + dash_px, total)
        steps = max(2, int((stop - travelled) / 3))
        run = [point_at(travelled + (stop - travelled) * k / (steps - 1)) for k in range(steps)]
        draw.line(run, fill=ink, width=weight, joint="curve")
        travelled = stop + gap_px


def chevron(draw, x, y, scale, size, *, color=MUTED, weight=None):
    """A small ">" separator, drawn (DM Sans' latin subset has no arrow glyph)."""
    half = size * 0.30 * scale
    w = max(1, int(round((weight if weight else size * 0.085) * scale)))
    px = x * scale
    cy = y * scale + half * 0.05
    draw.line([(px - half * 0.42, cy - half), (px + half * 0.5, cy),
               (px - half * 0.42, cy + half)], fill=rgba(color), width=w, joint="curve")
    return (half * 1.0 + half * 0.9) / scale


def paint_arrow(img, start_x, end_x, y, scale, *, color=PURPLE_SOFT, weight=9.0):
    x0, x1, yy = start_x * scale, end_x * scale, y * scale
    w = max(2, int(round(weight * scale)))
    points = []
    span = x1 - x0
    for i in range(61):
        t = i / 60
        points.append((x0 + span * t, yy - 16 * scale * math.sin(math.pi * t) ** 1.35))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).line(points, fill=rgba(PURPLE, 30),
                                width=w + int(2.5 * scale), joint="curve")
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(int(round(3.5 * scale)))))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.line(points, fill=rgba(color, 235), width=w, joint="curve")
    head = 15 * scale
    tip_x = points[-1][0]
    draw.polygon([(tip_x + head * 0.75, yy), (tip_x - head * 0.35, yy - head * 0.8),
                  (tip_x - head * 0.35, yy + head * 0.8)], fill=rgba(color, 235))
    img.alpha_composite(layer)


def step_line(draw, scale, y, number, segments, x_left, *, size=13.5):
    """One instruction row: a filled number chip then alternating styled runs."""
    cx, cy, r = (x_left + 10) * scale, (y + 9) * scale, 10.5 * scale
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba(PURPLE, 255))
    number_font, number_stroke = font("bold", 11.5, scale)
    draw.text((cx, cy), str(number), font=number_font, fill=(255, 255, 255, 255), anchor="mm",
              stroke_width=number_stroke, stroke_fill=(255, 255, 255, 255))
    styles = {"body": (INK, "regular"), "key": (PURPLE, "bold"), "menu": (INK, "semibold"),
              "dim": (PURPLE_SOFT, "regular")}
    x = x_left + 30
    for kind, value in segments:
        if kind == "chev":
            x += chevron(draw, x + 3, y + 7, scale, size, color=MUTED) + 6
            continue
        if kind == "dim":
            color, weight = styles[kind]
            x += text(draw, (x, y), value, size=size - 1.5, weight=weight, color=color,
                      scale=scale)
            continue
        color, weight = styles[kind]
        x += text(draw, (x, y), value, size=size, weight=weight, color=color,
                  scale=scale, tracking=0.08)
        x += 1.5
    return (x - x_left) / scale


# ------------------------------------------------------------------- render ---

# What the build actually contains. CI slices this from the arch it froze for, so the
# artwork can never promise a binary that the DMG does not carry.
DEFAULT_PLATFORMS = os.environ.get("SREON_PLATFORMS", "Apple silicon")


def default_version() -> str:
    """Browser/VERSION, so the artwork and the installers always show one number."""
    try:
        return (BROWSER / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    except OSError:
        return "0.0.0"


def layout():
    """The numbers tools/build.py hands to dmgbuild (all in points)."""
    app_x = (CHIP[0] + CHIP[2]) // 2 - ICON_SIZE // 2
    apps_x = (DROP[0] + DROP[2]) // 2 - ICON_SIZE // 2
    icon_y = ARROW_Y - ICON_SIZE // 2
    return {
        "window": WINDOW,
        "icon_size": ICON_SIZE,
        "text_size": TEXT_SIZE,
        "icon_locations": {"Sreon.app": [app_x, icon_y], "Applications": [apps_x, icon_y]},
        "background": "assets/dmg-background.png",
        "background_2x": "assets/dmg-background@2x.png",
    }


def render(scale=1.0, *, icons=None, labels=None, version="0.5.1",
           platforms=DEFAULT_PLATFORMS, strict=True):
    """Draw the artwork. `strict` raises when any text run would be clipped."""
    problems = []

    def guard(name, x, width, limit):
        if width > limit - x:
            problems.append(f"{name}: needs {width:.0f}pt, only {limit - x:.0f}pt free")
        return width

    size = (int(round(WINDOW[0] * scale)), int(round(WINDOW[1] * scale)))
    img = paint_base(size, scale)
    draw = ImageDraw.Draw(img)

    left_cx = (CHIP[0] + CHIP[2]) // 2
    right_cx = (DROP[0] + DROP[2]) // 2
    icon_x, icon_y = layout()["icon_locations"]["Sreon.app"]

    paint_glow(img, (left_cx, ARROW_Y), 136, scale, alpha=46)
    paint_glow(img, (right_cx, ARROW_Y), 136, scale, alpha=36)

    # ---- header -------------------------------------------------------------
    mark = 44
    if icons and icons.get("mark") is not None:
        tile = icons["mark"].convert("RGBA").resize((int(mark * scale),) * 2, Image.LANCZOS)
        img.alpha_composite(tile, (int(CHIP[0] * scale), int(22 * scale)))
    else:
        panel(img, (CHIP[0], 22, CHIP[0] + mark, 22 + mark), 13, scale,
              fill=rgba((255, 255, 255), 235), edge=LAVENDER_EDGE)
        text(draw, (CHIP[0] + mark / 2, 22 + mark / 2), "S", size=21, weight="bold",
             color=PURPLE, scale=scale, anchor="mm")

    title_x = CHIP[0] + mark + 15
    text(draw, (title_x, 18), "Install Sreon", size=28, weight="bold", color=INK, scale=scale)
    subtitle = "Drag Sreon onto Applications. That is the whole install."
    guard("subtitle", title_x,
         fits(draw, subtitle, size=13.5, weight="medium", scale=scale), WINDOW[0] - 150)
    text(draw, (title_x, 58), subtitle, size=13.5, weight="medium", color=MUTED, scale=scale)

    # version pill, right aligned on the header row
    pill_text = f"version {version}"
    pill_w = fits(draw, pill_text, size=11.5, weight="semibold", scale=scale) + 20
    pill = (DROP[2] - pill_w, 22, DROP[2], 22 + 21)
    panel(img, pill, 10.5, scale, fill=rgba(PURPLE, 22))
    text(draw, ((pill[0] + pill[2]) / 2, (pill[1] + pill[3]) / 2 - 0.5), pill_text,
         size=11.5, weight="semibold", color=PURPLE, scale=scale, anchor="mm")
    guard("platforms", title_x, fits(draw, platforms, size=11, weight="medium", scale=scale),
          DROP[2] - 0)
    text(draw, (DROP[2], 51), platforms, size=11, weight="medium",
         color=MUTED, scale=scale, anchor="rm")

    # ---- the two panels -----------------------------------------------------
    soft_shadow(img, CHIP, 24, scale, alpha=26, blur=13, offset=(0, 8))
    panel(img, CHIP, 24, scale, fill=rgba((255, 255, 255), 198), edge=LAVENDER_EDGE)
    soft_shadow(img, DROP, 24, scale, alpha=32, blur=13, offset=(0, 8))
    panel(img, DROP, 24, scale, fill=rgba((250, 247, 255), 240))
    dash_round_rect(img, DROP, 24, scale, PURPLE, 2.0, 10, 8)

    text(draw, (right_cx, LABEL_ROW), "drop here", size=12, weight="semibold",
         color=PURPLE, scale=scale, anchor="ma", tracking=1.1)

    # ---- arrow and its captions --------------------------------------------
    paint_arrow(img, 254, 424, ARROW_Y, scale)
    mid = (254 + 424) // 2
    text(draw, (mid, ARROW_Y - 76), "drag me", size=12.5, weight="semibold", color=PURPLE_SOFT,
         scale=scale, anchor="ma", tracking=0.6)
    text(draw, (mid, ARROW_Y + 32), "takes 5 seconds", size=11, weight="regular", color=MUTED,
         scale=scale, anchor="ma")

    # ---- the "if macOS says..." card ---------------------------------------
    soft_shadow(img, CARD, 20, scale, alpha=28, blur=14, offset=(0, 8))
    panel(img, CARD, 20, scale, fill=rgba(CARD_FILL, 250), edge=CARD_EDGE)
    x0, y0, x1, y1 = [int(round(v * scale)) for v in CARD]
    draw.rounded_rectangle([x0, y0 + int(15 * scale), x0 + int(4 * scale), y1 - int(15 * scale)],
                           radius=int(2 * scale), fill=rgba(PURPLE, 205))
    pad = 22
    heading = "If macOS says “Sreon” can’t be opened"
    text(draw, (CARD[0] + pad, 361), heading, size=15.5, weight="bold", color=INK, scale=scale)
    hint = "right-click Sreon, then Open"
    heading_w = fits(draw, heading, size=15.5, weight="bold", scale=scale)
    room = (CARD[2] - CARD[0]) - 2 * pad - heading_w - 26
    if fits(draw, hint, size=11.5, weight="medium", scale=scale) > max(room, 0):
        hint = "right-click, then Open"
    if fits(draw, hint, size=11.5, weight="medium", scale=scale) <= max(room, 0):
        text(draw, (CARD[2] - pad, 364), hint, size=11.5, weight="medium", color=MUTED,
             scale=scale, anchor="rm")
        guard("card hint", CARD[0] + pad + heading_w + 26,
             fits(draw, hint, size=11.5, weight="medium", scale=scale), CARD[2] - pad)
    lede = "Normal for a free, open-source app Apple has not notarised. It happens once, then never again."
    guard("card lede", CARD[0] + pad, fits(draw, lede, size=11.5, scale=scale), CARD[2] - pad)
    text(draw, (CARD[0] + pad, 384), lede, size=11.5, weight="regular", color=MUTED, scale=scale)

    rows = [
        [("body", "Open Sreon once, then click "), ("key", "Done"), ("body", " on the warning."),
         ("dim", "      (don’t move it to the Bin)")],
        [("menu", "Apple menu"), ("chev", ""), ("menu", "System Settings"), ("chev", ""),
         ("menu", "Privacy & Security")],
        [("body", "Under "), ("key", "Security"), ("body", ", click "), ("key", "Open Anyway"),
         ("body", ", then "), ("key", "Open"), ("body", " — once, ever.")],
    ]
    y = 408
    widest = 0.0
    for index, segments in enumerate(rows, start=1):
        widest = max(widest, step_line(draw, scale, y, index, segments, CARD[0] + pad))
        y += 21
    guard("instruction rows", CARD[0] + pad, widest, CARD[2] - pad)

    # ---- preview scaffolding (never in the shipped PNG) --------------------
    positions = layout()["icon_locations"]
    if icons:
        for name in ("Sreon.app", "Applications"):
            image = (icons or {}).get(f"{name}_image")
            if image is None:
                continue
            x, yy = positions[name]
            side = int(round(ICON_SIZE * scale))
            img.alpha_composite(image.convert("RGBA").resize((side, side), Image.LANCZOS),
                                (int(x * scale), int(yy * scale)))
    if labels:
        label_font, label_stroke = font("medium", TEXT_SIZE, scale)
        for value, centre_x in labels.items():
            top = (icon_y + ICON_SIZE + 3) * scale
            box = draw.textbbox((0, 0), value, font=label_font)
            width, height = box[2] - box[0], box[3] - box[1]
            plate = int(4 * scale)
            draw.rounded_rectangle([centre_x * scale - width / 2 - plate, top - int(3 * scale),
                                    centre_x * scale + width / 2 + plate, top + height + plate],
                                   radius=int(4 * scale), fill=(255, 255, 255, 215))
            draw.text((centre_x * scale, top), value, font=label_font, fill=(60, 52, 80, 255),
                      anchor="ma", stroke_width=0)
    if problems and strict:
        raise SystemExit("artwork does not fit: " + "; ".join(problems)
                         + "  (shorten the copy or widen WINDOW)")
    return img


def convert_fonts():
    """Rebuild tools/fonts/*.ttf from the woff2 files the site already ships."""
    from fontTools.ttLib import TTFont

    pairs = [("dm-sans-latin-400-normal.woff2", "DMSans-Regular.ttf"),
             ("dm-sans-latin-500-normal.woff2", "DMSans-Medium.ttf"),
             ("instrument-serif-latin-400-normal.woff2", "InstrumentSerif-Regular.ttf")]
    source, target = BROWSER.parent / "site" / "assets" / "fonts", TOOLS / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    for name, out in pairs:
        if not (source / name).is_file():
            print("skip, missing", source / name)
            continue
        loaded = TTFont(str(source / name))
        loaded.flavor = None
        loaded.save(str(target / out))
        print("converted", out, (target / out).stat().st_size // 1024, "KiB")


# ----------------------------------------------------- Windows installer art ---
# NSIS stretches these into place, so shipping 2x sizes (300x114 -> 150x57 and
# 328x628 -> 164x314) keeps the wizard crisp on high-DPI displays.
NSIS_HEADER = (300, 114)
NSIS_SIDEBAR = (328, 628)


def render_nsis_header():
    width, height = NSIS_HEADER
    img = Image.new("RGBA", (width, height), CREAM_TOP[:3] + (255,))
    draw = ImageDraw.Draw(img)
    for x in range(width):
        t = x / max(1, width - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip((252, 249, 243), (238, 231, 248)))
        draw.line([(x, 0), (x, height)], fill=colour)
    paint_glow(img, (30, height - 10), 120, 1.0, alpha=30)
    draw = ImageDraw.Draw(img)
    mark = 54
    panel(img, (16, (height - mark) // 2 - 3, 16 + mark, (height + mark) // 2 - 3), 15, 1.0,
          fill=(255, 255, 255, 235), edge=LAVENDER_EDGE)
    text(draw, (16 + mark / 2, height / 2 - 3), "S", size=25, weight="bold", color=PURPLE,
         anchor="mm")
    text(draw, (84, 26), "Sreon", size=26, weight="bold", color=INK)
    text(draw, (84, 66), "Search privately. Browse freely.", size=12.5, weight="medium", color=MUTED)
    draw.rectangle([0, height - 6, width, height], fill=rgba(PURPLE, 255))
    draw.rectangle([0, height - 6, width // 3, height], fill=rgba(PURPLE_SOFT, 255))
    return img.convert("RGB")


def render_nsis_sidebar():
    width, height = NSIS_SIDEBAR
    img = Image.new("RGBA", (width, height), PURPLE[:3] + (255,))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(((104, 78, 176)), (46, 30, 86)))
        draw.line([(0, y), (width, y)], fill=colour)
    paint_glow(img, (width * 0.4, height * 0.30), 190, 1.0, color=(255, 255, 255), alpha=54)
    draw = ImageDraw.Draw(img)
    mark = 96
    panel(img, (30, 40, 30 + mark, 40 + mark), 24, 1.0, fill=(255, 255, 255, 245))
    text(draw, (30 + mark / 2, 40 + mark / 2), "S", size=46, weight="bold", color=PURPLE, anchor="mm")
    text(draw, (30, 172), "Sreon", size=34, weight="bold", color=(255, 255, 255, 255))
    text(draw, (30, 226), "Search privately.", size=15.5, weight="medium", color=(226, 218, 246, 255))
    text(draw, (30, 252), "Browse freely.", size=15.5, weight="medium", color=(226, 218, 246, 255))
    y = 330
    for line in ("No accounts, no telemetry.",
                 "Your vault stays on this PC.",
                 "Pages run in Chromium,",
                 "the same engine family other",
                 "embedded browsers use."):
        text(draw, (30, y), line, size=13, color=(206, 197, 234, 255))
        y += 22
    draw.line([30, height - 96, 120, height - 96], fill=(176, 158, 224, 255), width=2)
    text(draw, (30, height - 76), "Free and open source", size=12.5, weight="medium",
         color=(226, 218, 246, 255))
    text(draw, (30, height - 54), "64-bit installer", size=12.5, color=(198, 188, 228, 255))
    return img.convert("RGB")


def write_nsis_assets(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    for name, image in (("header.bmp", render_nsis_header()), ("welcome.bmp", render_nsis_sidebar())):
        target = directory / name
        image.save(target, "BMP", optimize=True)
        print(f"wrote {target}  {image.size[0]}x{image.size[1]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preview", action="store_true", help="overlay fake Finder icons and labels")
    parser.add_argument("--print-layout", action="store_true", help="emit the dmgbuild geometry as JSON")
    parser.add_argument("--nsis-assets", action="store_true",
                        help="also write the Windows installer bitmaps")
    parser.add_argument("--convert-fonts", action="store_true",
                        help="rebuild tools/fonts/*.ttf from the site woff2 files, then exit")
    parser.add_argument("--version",
                        default=os.environ.get("SREON_VERSION") or default_version())
    parser.add_argument("--platforms", default=DEFAULT_PLATFORMS,
                        help="the small right-aligned line in the header")
    parser.add_argument("--out-dir", default=str(ASSETS))
    args = parser.parse_args()

    if args.nsis_assets:
        write_nsis_assets(BROWSER / "installer" / "nsis")
        return
    if args.convert_fonts:
        convert_fonts()
        return
    if args.print_layout:
        print(json.dumps(layout(), indent=2))
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, scale in (("dmg-background.png", 1.0), ("dmg-background@2x.png", 2.0)):
        image = render(scale, version=args.version, platforms=args.platforms)
        path = out_dir / name
        image.save(path, optimize=True)
        print(f"wrote {path}  {image.size[0]}x{image.size[1]}  {path.stat().st_size / 1024:.0f} KiB")
    print("dmgbuild geometry:", json.dumps(layout()["icon_locations"]),
          f"icon_size={ICON_SIZE} text_size={TEXT_SIZE} window={WINDOW}")

    if args.preview:
        mark = Image.open(ASSETS / "mark.png")
        app_icon = Image.open(ASSETS / "icon.png")
        folder = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        fd = ImageDraw.Draw(folder)
        fd.rounded_rectangle([48, 120, 464, 432], radius=44, fill=(126, 196, 240, 255))
        fd.rounded_rectangle([48, 76, 268, 176], radius=30, fill=(96, 172, 220, 255))
        folder_font, folder_stroke = font("bold", 150, 1.0)
        fd.text((256, 292), "A", font=folder_font, fill=(255, 255, 255, 235), anchor="mm",
                stroke_width=folder_stroke, stroke_fill=(255, 255, 255, 235))
        preview = render(2.0, version=args.version, platforms=args.platforms,
                         icons={"mark": mark, "Sreon.app_image": app_icon,
                                "Applications_image": folder},
                         labels={"Sreon": left_label_x(), "Applications": right_label_x()})
        target = out_dir / "dmg-preview.png"
        preview.save(target)
        print("wrote", target)


def left_label_x():
    return (CHIP[0] + CHIP[2]) // 2


def right_label_x():
    return (DROP[0] + DROP[2]) // 2


if __name__ == "__main__":
    main()
