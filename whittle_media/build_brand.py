#!/usr/bin/env python3
"""
whittle brand asset generator.

Emits the icon (master + small-size variant + transparent mark), platform icon
exports for iOS / Android / web, a wordmark, a splash logo and a social image.

Single source of truth for geometry and colour so every asset stays identical.
Regenerate with:  python3 build_brand.py
"""

import io
import math
import os
import re

import cairosvg
from PIL import Image, ImageDraw
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

# PATHS RESOLVED AGAINST THIS FILE, NOT THE MACHINE IT WAS WRITTEN ON.
#
# These were absolute paths into the sandbox that produced the first assets
# (/mnt/user-data/outputs and /home/claude/jbm), which do not exist on any
# other computer - so the generator could not be re-run, and the README's
# instruction to re-run it was untrue. The assets now land in `build/` beside
# this script.
#
# The font is only needed for the wordmark, whose glyphs are converted to
# outlines so the font is never redistributed. It is looked for in a few
# ordinary places and the wordmark is skipped with a message if it is not
# found, rather than taking the whole run down with it.
import glob as _glob

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build")


def _find_font(name):
    candidates = [
        os.path.join(HERE, "fonts", name),
        os.path.expanduser("~/.local/share/fonts/%s" % name),
        "/usr/share/fonts/truetype/jetbrains-mono/%s" % name,
    ]
    for pattern in ("/snap/*/*/jbr/lib/fonts/%s" % name,
                    os.path.expanduser("~/Downloads/**/jbr/lib/fonts/%s" % name)):
        candidates.extend(sorted(_glob.glob(pattern, recursive=True)))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


FONT_BOLD = _find_font("JetBrainsMono-Bold.ttf")
FONT_REG = _find_font("JetBrainsMono-Regular.ttf")

# THE WORDMARK'S FACE. Space Grotesk, from this repository - see wordmark_svg.
#
# NOT A SYSTEM FONT. The previous one pointed at /usr/share/fonts, so the brand
# built differently depending on whose machine ran it, and on a machine without
# Ubuntu installed it did not build at all. This file is in the repo, is the
# face the brief already names, and is the same file the web client serves - so
# the wordmark and the interface are set in one thing rather than two.
#
# Variable, wght 300-700; instanced to 700 before the glyphs are drawn.
FONT_WORD = os.path.join(HERE, "..", "whittle", "web", "static", "fonts",
                         "spacegrotesk-latin.woff2")

# ---------------------------------------------------------------- tokens
CASE = "#0B0F0D"      # app background / icon field
BEZEL = "#151B18"     # panels
ETCH = "#2A322D"      # rules and borders
GRID = "#182019"      # graticule
PHOSPHOR = "#FFB000"  # amber accent
SCREEN = "#DCE3DC"    # the printable part, primary text
DIM = "#7C8880"       # secondary text
PEN_DIM = "#4A554E"   # construction geometry

ISO = math.tan(math.radians(30))  # 0.5774, isometric y-drop per unit of x

S = 1024  # master canvas


def iso_cube(cx, cy, w):
    """Vertices of an isometric cube of half-width w, centred on (cx, cy)."""
    h = w * ISO
    return {
        "T": (cx, cy - 2 * h),
        "UR": (cx + w, cy - h),
        "LR": (cx + w, cy + h),
        "B": (cx, cy + 2 * h),
        "LL": (cx - w, cy + h),
        "UL": (cx - w, cy - h),
        "C": (cx, cy),
    }


def pts(*p):
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in p)


def mark_svg(cx, cy, w, stroke, inner, cut=0.26, mono=False):
    """
    The whittle mark: a block with a corner pared off, and the shaving lifting
    away from the cut.

    WHY THIS AND NOT THE SECTION CUT IT REPLACED. The old mark was an isometric
    solid with a quarter notch taken out of it - a section view, the drafting
    convention for showing what is inside a part. Correct for a CAD tool called
    bpcad, and it says nothing about a tool called whittle. This one draws the
    name: you start with a block, you take material off, and what falls away is
    a shaving. That is also, exactly, what the product does.

    WHAT IS KEPT. The isometric hexagon silhouette, because it was proved to
    read at 16 px and every icon in the set is generated from it. The amber cut
    face, because a lit interior is the recognition. What changed is that the
    cut is now ONE flat plane rather than three faces of a notch - a paring, not
    an excavation - and a curl comes off it.

    mono=True renders one colour for Android themed icons.
    """
    part = "#FFFFFF" if mono else SCREEN
    h = w * ISO
    C = (cx, cy)                     # the near corner, where the blade went in
    u = (-w, -h)                     # C -> upper-left
    v_ = (w, -h)                     # C -> upper-right
    d = (0.0, 2 * h)                 # C -> bottom

    def P(*terms):
        x, y = C
        for vec, k in terms:
            x += vec[0] * k
            y += vec[1] * k
        return (x, y)

    f = cut
    UL, UR, T = P((u, 1)), P((v_, 1)), P((u, 1), (v_, 1))
    B = P((d, 1))
    LL, LR = P((u, 1), (d, 1)), P((v_, 1), (d, 1))

    # The three points the cut passes through, one along each edge from C.
    cu, cv, cd = P((u, f)), P((v_, f)), P((d, f))

    if mono:
        cut_fill = "#FFFFFF"
        f_top = f_left = f_right = "none"
    else:
        cut_fill = PHOSPHOR
        f_top, f_left, f_right = "#1F2723", "#161D19", "#0F1512"

    g = []
    # The three outer faces. Each is a rhombus that has lost the corner at C,
    # so each is a pentagon.
    g.append('<polygon points="%s" fill="%s"/>' % (pts(cu, UL, T, UR, cv), f_top))
    g.append('<polygon points="%s" fill="%s"/>' % (pts(cu, UL, LL, B, cd), f_left))
    g.append('<polygon points="%s" fill="%s"/>' % (pts(cv, UR, LR, B, cd), f_right))

    # THE CUT ITSELF: one flat triangle where the blade passed. A single plane
    # rather than the old three-faced notch - that is the difference between
    # paring a corner and cutting a quarter out.
    g.append('<polygon points="%s" fill="%s"/>' % (pts(cu, cv, cd), cut_fill))
    if mono:
        g[-1] = g[-1].replace('/>', ' fill-opacity="0.55"/>')

    # The three edges that survive between the cut and the far corners.
    for start_pt, end_pt in ((cu, UL), (cv, UR), (cd, B)):
        g.append(
            f'<line x1="{start_pt[0]:.2f}" y1="{start_pt[1]:.2f}" '
            f'x2="{end_pt[0]:.2f}" y2="{end_pt[1]:.2f}" stroke="{part}" '
            f'stroke-width="{inner}" stroke-linecap="round"/>'
        )

    # THE SHAVING. It springs from the top edge of the cut and curls away over
    # the block's shoulder. Drawn as a ribbon - an outer arc out, an inner arc
    # back - because a stroked spiral goes thin at 16 px and disappears, and a
    # filled ribbon keeps its weight all the way down.
    g.append(_shaving(cu, cv, UR, w, part, mono, None if mono else CASE))

    # Silhouette last, over everything.
    g.append(
        f'<polygon points="{pts(T, UR, LR, B, LL, UL)}" fill="none" '
        f'stroke="{part}" stroke-width="{stroke}" stroke-linejoin="round"/>'
    )
    return "\n".join(g)


def _shaving(cu, cv, UR, w, colour, mono=False, case=None):
    """
    The curl of material coming off the cut, as a filled ribbon.

    IT CROSSES THE BLOCK, AND IT HAS TO. This carried a comment claiming "the
    whole ribbon sits OUTSIDE the silhouette", and that was never true and
    never could be: `C` is the near corner where all three visible faces meet,
    which on an isometric hexagon is the CENTRE. A shaving springing from a cut
    taken there has to travel over a face to get anywhere, whichever way it
    goes. The claim was wishful, and the render showed the ribbon cutting
    across the top face and through the right-hand silhouette edge.

    WHAT THE OLD COMMENT GOT RIGHT was the actual failure it was trying to
    avoid: "a light ribbon on a dark face with another light edge behind it has
    nothing to separate the two - at 48 px they merged into one grey smear."
    That is a real observation and it has a real fix, which is not to route
    around the block but to give the ribbon its own edge. It is drawn with a
    stroke in the CASE colour, so wherever it passes - over a face, over the
    silhouette, over the amber cut - there is always a dark line between it and
    what is behind it.

    So: the ribbon leaves the cut's top edge along that edge's own direction,
    so it reads as material just lifted rather than a decoration parked nearby,
    and it rolls anticlockwise over the upper-right shoulder.
    """
    # The tail STRADDLES the cut's right-hand corner: one side rooted on the
    # cut face, the other on the edge it rolls over. Anchoring both sides at
    # the single point left a dark wedge between ribbon and block that looked
    # like a drawing error.
    ex, ey = cv
    ax = cu[0] + (cv[0] - cu[0]) * 0.72
    ay = cu[1] + (cv[1] - cu[1]) * 0.72
    bx = ex + (UR[0] - ex) * 0.20
    by = ey + (UR[1] - ey) * 0.20

    # The roll, out past the block's shoulder.
    rx = ex + w * 0.62
    ry = ey - w * 0.52
    R = w * 0.26          # outer radius of the roll
    r = w * 0.145         # the hole it curls around; R - r is the ribbon

    outer = f"M {ax:.2f},{ay:.2f} " \
            f"C {ax + w*0.16:.2f},{ay - w*0.30:.2f} {rx - R*1.40:.2f},{ry + R*0.70:.2f} " \
            f"{rx - R:.2f},{ry:.2f} " \
            f"A {R:.2f},{R:.2f} 0 1 1 {rx + R*0.70:.2f},{ry + R*0.72:.2f} "
    inner = f"A {r:.2f},{r:.2f} 0 1 0 {rx - r:.2f},{ry:.2f} " \
            f"C {rx - r*1.30:.2f},{ry + w*0.20:.2f} {bx + w*0.24:.2f},{by - w*0.22:.2f} " \
            f"{bx:.2f},{by:.2f} Z"

    # THE SEPARATING EDGE. Wide enough to read at 48 px, and in the ground
    # colour rather than a darker tint of the ribbon, so it works over the
    # amber cut and over the dark faces alike.
    #
    # A stroke straddles the path, so half of it eats into the ribbon - the
    # width is set against the ribbon's own thickness (R - r) rather than
    # against the icon, or a small mark ends up with an outline and no fill.
    edge = ""
    if case is not None:
        edge = (f' stroke="{case}" stroke-width="{max(w * 0.022, (R - r) * 0.30):.2f}"'
                f' stroke-linejoin="round"')

    opacity = ' fill-opacity="0.85"' if mono else ''
    return f'<path d="{outer}{inner}" fill="{colour}"{opacity}{edge}/>'


def graticule(size, step=96):
    lines = []
    n = int(size / step)
    for i in range(1, n + 1):
        p = i * step
        lines.append(
            f'<line x1="{p}" y1="0" x2="{p}" y2="{size}" stroke="{GRID}" stroke-width="2"/>'
        )
        lines.append(
            f'<line x1="0" y1="{p}" x2="{size}" y2="{p}" stroke="{GRID}" stroke-width="2"/>'
        )
    c = size / 2
    lines.append(
        f'<line x1="{c}" y1="0" x2="{c}" y2="{size}" stroke="{ETCH}" stroke-width="3"/>'
    )
    lines.append(
        f'<line x1="0" y1="{c}" x2="{size}" y2="{c}" stroke="{ETCH}" stroke-width="3"/>'
    )
    return "\n".join(lines)


def dim_line(x1, x2, y, up_to_y):
    """Drafting dimension line with extension lines and end ticks."""
    o = []
    for x in (x1, x2):
        o.append(
            f'<line x1="{x:.2f}" y1="{up_to_y:.2f}" x2="{x:.2f}" y2="{y + 26:.2f}" '
            f'stroke="{PEN_DIM}" stroke-width="4"/>'
        )
        o.append(
            f'<line x1="{x:.2f}" y1="{y - 22:.2f}" x2="{x:.2f}" y2="{y + 22:.2f}" '
            f'stroke="{PHOSPHOR}" stroke-width="8" stroke-linecap="round"/>'
        )
    o.append(
        f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}" '
        f'stroke="{PHOSPHOR}" stroke-width="8" stroke-linecap="round"/>'
    )
    return "\n".join(o)


def icon_master():
    body = [
        f'<rect width="{S}" height="{S}" fill="{CASE}"/>',
        graticule(S),
        mark_svg(512, 512, 280, stroke=24, inner=17, cut=0.46),
        f'<rect x="7" y="7" width="{S-14}" height="{S-14}" fill="none" '
        f'stroke="{ETCH}" stroke-width="7"/>',
    ]
    return svg_doc(S, body)


def icon_small():
    """Simplified for 16-128 px: no graticule, no dimension line, heavier strokes."""
    body = [
        f'<rect width="{S}" height="{S}" fill="{CASE}"/>',
        mark_svg(512, 512, 300, stroke=34, inner=24, cut=0.50),
    ]
    return svg_doc(S, body)


def mark_only(mono=False, scale=1.0):
    """Transparent mark for adaptive foregrounds, splash and themed icons."""
    w = 290 * scale
    body = [mark_svg(512, 512, w, stroke=26 * scale, inner=18 * scale,
                     cut=0.48, mono=mono)]
    return svg_doc(S, body)


def svg_doc(size, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">\n' + "\n".join(body) + "\n</svg>\n"
    )


# ---------------------------------------------------------------- wordmark
def glyph_paths(text, font_path, letterspace=0.0, weight=None):
    """
    One text string as SVG path data, with the glyphs converted to outlines.

    `weight` instantiates a VARIABLE font at that weight first. Ubuntu ships as
    a single file with a wght axis, and drawing it without instancing gives the
    Regular - a wordmark noticeably lighter than intended, which is the kind of
    thing nobody spots until it is on a phone next to something else.
    """
    try:
        font = TTFont(font_path)
    except ImportError as exc:
        # A WOFF2 NEEDS A BROTLI DECOMPRESSOR, and fontTools does not ship one.
        # Without this the failure is `ImportError: No module named brotli`
        # from three frames inside fontTools, which says nothing about fonts.
        raise SystemExit(
            "%s is a WOFF2 and fontTools cannot decompress it: %s\n"
            "Install the decompressor:  pip install 'fonttools[woff]'"
            % (os.path.basename(font_path), exc)
        ) from exc
    if weight is not None and "fvar" in font:
        from fontTools.varLib import instancer

        font = instancer.instantiateVariableFont(font, {"wght": weight},
                                                 inplace=False)
    upem = font["head"].unitsPerEm
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    d = []
    x = 0.0
    for ch in text:
        gname = cmap[ord(ch)]
        spen = SVGPathPen(gs)
        tpen = TransformPen(spen, (1, 0, 0, -1, x, 0))
        gs[gname].draw(tpen)
        p = spen.getCommands()
        if p:
            d.append(p)
        x += hmtx[gname][0] + letterspace * upem
    return " ".join(d), x, upem


def wordmark_svg(colour=SCREEN, cursor=PHOSPHOR, height=200):
    """
    The wordmark: `whittle`, lowercase, in Space Grotesk at 700.

    WHY THE TERMINAL LOOK WENT. It was JetBrains Mono Bold with an amber block
    cursor after it, which says "developer tool" before it says anything else -
    and the product is for somebody who wants a birdhouse, not somebody who
    wants a CAD kernel. A blinking-cursor logotype was the single most technical
    thing on the screen.

    WHY UBUNTU WENT TOO, which replaced it. It is a good face and it is the
    wrong one here for two reasons. It is instantly recognisable as Ubuntu to
    anyone who has seen a Linux desktop, and generically humanist to everyone
    else - so it is either somebody else's brand or no brand at all. And it was
    loaded from /usr/share/fonts, so the wordmark built differently depending
    on whose machine ran the script, and not at all on a machine without it.

    SPACE GROTESK IS THE ONE THE BRIEF ALREADY NAMES - 11.3, "Archivo or Space
    Grotesk for UI, JetBrains Mono for dimensions" - and it is already in this
    repository, already served to the web client, already OFL. Set against
    Archivo it is the one with letterforms of its own: flat, cut terminals on
    the `t` and the `e`, a squared `w`, a grotesque drawn with a straight edge
    rather than defaulted to. That reads as a precision instrument without
    reading as a terminal, which is the whole brief for this mark.

    The glyphs are converted to outlines here, so the font is never
    redistributed - the same arrangement every version of this wordmark had.

    `cursor` is kept in the signature and ignored, so every existing caller
    still works; the block it used to draw is gone on purpose.
    """
    d, adv, upem = glyph_paths("whittle", FONT_WORD, letterspace=-0.01,
                               weight=700)
    scale = height / upem
    cap = upem * 0.73
    pad = height * 0.18
    text_w = adv * scale
    total_w = text_w + pad * 2
    total_h = height + pad * 2
    baseline = pad + cap * scale
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" '
        f'height="{total_h:.0f}" viewBox="0 0 {total_w:.0f} {total_h:.0f}">\n'
        f'<g transform="translate({pad:.2f},{baseline:.2f}) scale({scale:.5f})">\n'
        f'<path d="{d}" fill="{colour}"/>\n</g>\n'
        f'</svg>\n'
    )


# ---------------------------------------------------------------- raster
def png(svg_str, path, w, h=None, bg=None):
    cairosvg.svg2png(
        bytestring=svg_str.encode(), write_to=path,
        output_width=w, output_height=h or w, background_color=bg,
    )


def png_wide(svg_str, path, w):
    """
    Rasterise an SVG that is NOT square, at its own aspect.

    `png()` defaults the height to the width, which is right for an icon and
    wrong for everything else. Every wordmark went through it, so a logotype
    three times wider than it is tall was being written into a square canvas -
    correct pixels, floating in two thirds empty transparency, and anything
    placing it by its box put it a third of its own width out of position.
    """
    m = re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', svg_str)
    if not m:
        raise ValueError("no width/height on the svg to take an aspect from")
    ratio = float(m.group(2)) / float(m.group(1))
    cairosvg.svg2png(bytestring=svg_str.encode(), write_to=path,
                     output_width=w, output_height=int(round(w * ratio)))


def _trim(path):
    """
    Crop a transparent PNG to its ink. In place.

    FOR THE ASSET A LAYOUT POSITIONS, and only that one. `wordmark_svg` pads
    itself by 18% of its height on every side, which is right for a logo file
    somebody drops into a document and wrong for one a flex row places next to
    a mark: the padding is invisible, so an 8 dp gap becomes 8 dp plus a
    sixth of the wordmark's height, and the two halves of the lockup read as
    two unrelated things. Sizing by the padded height shrinks the letters
    against the mark for the same reason.

    The press versions keep their padding. This is the one that gets measured.
    """
    im = Image.open(path).convert("RGBA")
    box = im.getbbox()
    if box:
        im.crop(box).save(path)


def rounded(path_in, path_out, radius_ratio=0.22):
    im = Image.open(path_in).convert("RGBA")
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=int(w * radius_ratio), fill=255
    )
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    out.save(path_out)


def pad_canvas(svg_str, path, size, inner_ratio):
    """Render the mark inside a safe zone on a full-bleed field (maskable icons)."""
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=svg_str.encode(), write_to=buf,
                     output_width=int(size * inner_ratio),
                     output_height=int(size * inner_ratio))
    fg = Image.open(buf).convert("RGBA")
    base = Image.new("RGBA", (size, size), CASE)
    off = (size - fg.width) // 2
    base.alpha_composite(fg, (off, off))
    base.save(path)


def social_image():
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), CASE)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=GRID, width=1)
    d.rectangle([24, 24, W - 25, H - 25], outline=ETCH, width=3)

    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=mark_only().encode(), write_to=buf,
                     output_width=300, output_height=300)
    mk = Image.open(buf).convert("RGBA")
    im.paste(mk, (96, (H - 300) // 2), mk)

    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=wordmark_svg(height=150).encode(), write_to=buf,
                     output_height=190)
    wm = Image.open(buf).convert("RGBA")
    im.paste(wm, (452, 214), wm)

    from PIL import ImageFont
    f = ImageFont.truetype(FONT_REG, 27)
    d.text((464, 400), "Describe a part. Print a part that fits.", font=f, fill=SCREEN)
    f2 = ImageFont.truetype(FONT_REG, 22)
    d.text((464, 444), "or bring a model you already have and make it printable",
           font=f2, fill=DIM)
    im.save(f"{OUT}/social/og-image-1200x630.png")
    im.resize((600, 315), Image.LANCZOS).save(f"{OUT}/social/twitter-600x315.png")


# ---------------------------------------------------------------- main
def main():
    for sub in ("source", "ios", "android", "web", "splash", "social", "wordmark"):
        os.makedirs(f"{OUT}/{sub}", exist_ok=True)

    master, small = icon_master(), icon_small()
    mark, mark_mono = mark_only(), mark_only(mono=True)
    wm_light = wordmark_svg(colour=SCREEN)
    wm_dark = wordmark_svg(colour="#1A1D1B")

    # editable sources
    for name, s in (
        ("icon-master.svg", master), ("icon-small.svg", small),
        ("mark.svg", mark), ("mark-monochrome.svg", mark_mono),
    ):
        open(f"{OUT}/source/{name}", "w").write(s)
    open(f"{OUT}/wordmark/wordmark-light.svg", "w").write(wm_light)
    open(f"{OUT}/wordmark/wordmark-dark.svg", "w").write(wm_dark)
    png_wide(wm_light, f"{OUT}/wordmark/wordmark-light-2400.png", 2400)
    png_wide(wm_dark, f"{OUT}/wordmark/wordmark-dark-2400.png", 2400)

    # THE ONE THE APP DRAWS, and it was missing - which made every decision
    # about the wordmark's face invisible where it matters most.
    #
    # The native client rendered the name as TEXT in its prose family, which on
    # Android is `sans-serif` - the system face. So the brand could be set in
    # Space Grotesk, in Ubuntu or in JetBrains Mono and the phone's first screen
    # looked identical either way. A logotype is a drawing, not a string, and
    # the one place it is guaranteed to be the drawing is an image.
    #
    # Transparent, at 3x the ~26 dp it is drawn at, so it is sharp on a phone
    # without shipping the 2400 px press version inside the APK.
    png_wide(wm_light, f"{OUT}/wordmark/wordmark-app.png", 360)
    _trim(f"{OUT}/wordmark/wordmark-app.png")

    # AND THE MARK THAT GOES BESIDE IT. The app was using
    # adaptive-foreground-432.png, which is the ANDROID LAUNCHER foreground -
    # the mark inside a 72 dp safe zone, so a third of that canvas is
    # transparent margin by design. Dropped into a row it made the mark two
    # thirds the size it was asked for and added a third of its width to the
    # gap beside it, which is why the lockup read as two unrelated objects.
    #
    # Same treatment as the wordmark: full bleed, then trimmed to its ink, so a
    # layout that asks for 26 dp gets 26 dp of mark.
    png(mark, f"{OUT}/source/mark-app.png", 240)
    _trim(f"{OUT}/source/mark-app.png")

    def art(sz):
        return master if sz >= 512 else small

    # iOS
    for sz in (1024, 180, 167, 152, 120, 87, 80, 76, 60, 58, 40, 29):
        png(art(sz), f"{OUT}/ios/AppIcon-{sz}.png", sz)

    # Android
    png(art(512), f"{OUT}/android/play-store-512.png", 512)
    bg_only = svg_doc(S, [
        f'<rect width="{S}" height="{S}" fill="{CASE}"/>',
        graticule(S),
    ])
    png(bg_only, f"{OUT}/android/adaptive-background-432.png", 432)
    pad = 288 / 432  # 72dp safe zone inside a 108dp canvas
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=mark.encode(), write_to=buf,
                     output_width=int(432 * pad), output_height=int(432 * pad))
    fg = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    m = Image.open(buf).convert("RGBA")
    fg.alpha_composite(m, ((432 - m.width) // 2, (432 - m.height) // 2))
    fg.save(f"{OUT}/android/adaptive-foreground-432.png")
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=mark_mono.encode(), write_to=buf,
                     output_width=int(432 * pad), output_height=int(432 * pad))
    mo = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    m2 = Image.open(buf).convert("RGBA")
    mo.alpha_composite(m2, ((432 - m2.width) // 2, (432 - m2.height) // 2))
    mo.save(f"{OUT}/android/adaptive-monochrome-432.png")
    for sz in (192, 144, 96, 72, 48):
        png(art(sz), f"{OUT}/android/legacy-launcher-{sz}.png", sz)

    # Web
    for sz in (512, 192, 180, 48, 32, 16):
        png(art(sz), f"{OUT}/web/icon-{sz}.png", sz)
    rounded(f"{OUT}/web/icon-512.png", f"{OUT}/web/icon-512-rounded.png")
    rounded(f"{OUT}/web/icon-192.png", f"{OUT}/web/icon-192-rounded.png")
    pad_canvas(mark, f"{OUT}/web/maskable-512.png", 512, 0.66)
    ico = [Image.open(f"{OUT}/web/icon-{s}.png").convert("RGBA") for s in (48, 32, 16)]
    ico[0].save(f"{OUT}/web/favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)])

    # Splash
    png(mark, f"{OUT}/splash/splash-logo-1152.png", 1152)
    png(mark, f"{OUT}/splash/splash-logo-android12-960.png", 960)
    for name, (w, h) in {
        "splash-1290x2796.png": (1290, 2796),
        "splash-1179x2556.png": (1179, 2556),
        "splash-1080x1920.png": (1080, 1920),
    }.items():
        base = Image.new("RGB", (w, h), CASE)
        d = ImageDraw.Draw(base)
        for x in range(0, w, 60):
            d.line([(x, 0), (x, h)], fill=GRID, width=1)
        for y in range(0, h, 60):
            d.line([(0, y), (w, y)], fill=GRID, width=1)
        side = int(min(w, h) * 0.42)
        buf = io.BytesIO()
        cairosvg.svg2png(bytestring=mark.encode(), write_to=buf,
                         output_width=side, output_height=side)
        mk = Image.open(buf).convert("RGBA")
        base.paste(mk, ((w - side) // 2, (h - side) // 2 - int(h * 0.04)), mk)
        buf = io.BytesIO()
        cairosvg.svg2png(bytestring=wordmark_svg(height=120).encode(),
                         write_to=buf, output_width=int(w * 0.44))
        wm = Image.open(buf).convert("RGBA")
        base.paste(wm, ((w - wm.width) // 2, (h + side) // 2 + int(h * 0.01)), wm)
        base.save(f"{OUT}/splash/{name}")

    social_image()
    print("done")


if __name__ == "__main__":
    main()
