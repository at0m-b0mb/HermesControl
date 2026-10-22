"""
Build the repo's social preview card and its mark.

Follows the house card spec: a 1280x640 canvas with GitHub's 40pt (80px) safe
border, drawn at 2x and resampled, with every *meaningful* rectangle registered
with a :class:`SafeBox` as it is drawn. Background art is deliberately never
registered, so it stays free to bleed the way a crop expects. Authoring happens
at 104px rather than on the 80px limit, because a glyph's left bearing and a
thick line's end caps both put ink outside their anchor and a card authored
exactly on the limit measures 77.

The right half is not an illustration of the product — it is the product. It
carries the real context windows of the Ollama models on the machine this was
built on, read out of Ollama's ``/api/show`` (``model_info.*.context_length``),
plotted against the 64,000-token floor that Hermes Agent enforces in
``agent/agent_init.py::_enforce_minimum_context``. Two of them clear it and two
do not, which is the single most useful thing this app tells you and the reason
it exists.

Usage::

    python3 tools_gen_card.py

Writes ``images/social-preview.png`` and ``images/mark.png``. The card still
has to be uploaded by hand — GitHub exposes no API for the social preview.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = os.path.join(HERE, "images")
OWNER = "at0m-b0mb"
REPO = "HermesControl"

SERIF = "/System/Library/Fonts/Supplemental/Iowan Old Style.ttc"
SANS = "/System/Library/Fonts/SFNS.ttf"
MONO = "/System/Library/Fonts/Menlo.ttc"

# The house palette, identical to the app's light theme so the card and the
# window are visibly the same object.
PAPER, INK, MUTED, FAINT = "#F3F1EC", "#1B1813", "#575144", "#6B6554"
RULE, BRASS, SHINE = "#DCD6C9", "#7A5D18", "#C39B24"
WATERMARK = "#E7E1D3"
FAULT = "#8C1F16"

#: Measured on 2026-10-22 from Ollama's /api/show on the build machine.
#: (label, real context window, size). Order is the chart's order.
MODELS = [
    ("qwen3.5-abliterated:35b", 262_144, "23.9 GB"),
    ("llama3.1:latest",         131_072, "4.9 GB"),
    ("qwen3-abliterated:8b-v2",  40_960, "5.0 GB"),
    ("qwen2.5:7b",               32_768, "4.7 GB"),
]
FLOOR = 64_000           # Hermes Agent refuses anything under this.
AXIS_MAX = 262_144


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


class SafeBox:
    """Refuses a card whose information would be eaten by a crop.

    Registering rectangles as they are drawn beats measuring the finished PNG,
    because a pixel scan cannot tell information from atmosphere — a watermark
    that is *supposed* to bleed would trip it.
    """

    def __init__(self, w: int, h: int, safe: int):
        self.w, self.h, self.safe = w, h, safe
        self.rects: list[tuple[str, tuple[int, int, int, int]]] = []

    def add(self, name: str, box) -> None:
        self.rects.append((name, tuple(int(round(v)) for v in box)))

    def check(self) -> int | None:
        worst = None
        for name, (l, t, r, b) in self.rects:
            m = min(l, t, self.w - r, self.h - b)
            if worst is None or m < worst[0]:
                worst = (m, name, (l, t, r, b))
        if worst is None:
            return None
        m, name, box = worst
        assert m >= self.safe, (
            f"{name} at {box} leaves a {m}px margin on {self.w}x{self.h}; "
            f"GitHub's safe border needs {self.safe}px.")
        return m


def draw_mark(d: ImageDraw.ImageDraw, x: int, y: int, s: int,
              ink: str, accent: str, shine: str) -> None:
    """The app itself: a window with a rail, and the context ribbon inside it.

    An outline container with filled accents. A filled container carrying
    same-coloured detail reads as a solid blob at tile size.
    """
    stroke = max(2, s // 26)
    d.rounded_rectangle([x, y, x + s, y + int(s * 0.78)],
                        radius=s // 10, outline=ink, width=stroke)
    # The rail down the left, as in the window.
    rail = x + int(s * 0.26)
    d.line([(rail, y + stroke), (rail, y + int(s * 0.78) - stroke)],
           fill=ink, width=stroke)
    for i in range(3):                      # rail items
        iy = y + int(s * 0.20) + i * int(s * 0.17)
        d.line([(x + int(s * 0.08), iy), (x + int(s * 0.20), iy)],
               fill=accent, width=stroke)
    # The ribbon: a trough, a fill, and the threshold mark.
    bx0, bx1 = rail + int(s * 0.12), x + s - int(s * 0.12)
    by = y + int(s * 0.46)
    bh = max(3, int(s * 0.10))
    d.rounded_rectangle([bx0, by, bx1, by + bh], radius=bh // 2,
                        fill=RULE if ink != PAPER else MUTED)
    fill_to = bx0 + int((bx1 - bx0) * 0.52)
    d.rounded_rectangle([bx0, by, fill_to, by + bh], radius=bh // 2, fill=accent)
    thr = bx0 + int((bx1 - bx0) * 0.62)
    d.line([(thr, by - bh), (thr, by + bh * 2)], fill=shine, width=stroke)


def wrap(d: ImageDraw.ImageDraw, text: str, fnt, width: int, max_lines: int):
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=fnt) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def fmt(n: int) -> str:
    return f"{n / 1000:.0f}K" if n < 1_000_000 else f"{n / 1_000_000:.1f}M"


def render_card(path: str) -> int:
    W, H, SS, SAFE = 1280, 640, 2, 80
    im = Image.new("RGB", (W * SS, H * SS), PAPER)
    d = ImageDraw.Draw(im)
    box = SafeBox(W * SS, H * SS, SAFE * SS)

    # No watermark. The usual pale echo of the mark would sit straight through
    # the chart on the right, and the house rule when art fights type is to mask
    # it off the content — here the chart *is* the content of that half, so the
    # art has nowhere to go. A real measurement beats a decorative glyph.

    lx = 104 * SS
    col = int(520 * SS)

    mark = 76 * SS
    draw_mark(d, lx, 104 * SS, mark, INK, BRASS, SHINE)
    box.add("mark", (lx, 104 * SS, lx + mark, 104 * SS + int(mark * 0.78)))

    name = "Hermes Control"
    f_name = font(SERIF, 66 * SS)
    ny = 232 * SS
    d.text((lx, ny), name, font=f_name, fill=INK)
    nw = d.textlength(name, font=f_name)
    box.add("name", (lx, ny, lx + nw, ny + f_name.size))

    rule_y = ny + f_name.size + 18 * SS
    d.line([(lx, rule_y), (lx + max(nw, 180 * SS), rule_y)], fill=BRASS, width=3 * SS)

    sub = ("A desktop control panel for Nous Research's Hermes Agent. "
           "Isolated install, every documented setting, local and hosted models.")
    f_sub = font(SANS, 26 * SS)
    lines = wrap(d, sub, f_sub, col, 3)
    ty = rule_y + 28 * SS
    for i, line in enumerate(lines):
        d.text((lx, ty + i * 37 * SS), line, font=f_sub, fill=MUTED)
    box.add("sub", (lx, ty, lx + col, ty + len(lines) * 37 * SS))

    # Footer derived from the safe box, never from the canvas height: deriving
    # from the canvas is exactly how a card ends up with a 36px bottom margin.
    f_foot = font(SANS, 19 * SS)
    f_url = font(MONO, 19 * SS)
    foot = "Python  ·  PySide6  ·  Windows, macOS, Linux  ·  MIT"
    uy = H * SS - SAFE * SS - 24 * SS - 20 * SS
    fy = uy - 32 * SS
    d.text((lx, fy), foot, font=f_foot, fill=FAINT)
    box.add("meta", (lx, fy, lx + d.textlength(foot, font=f_foot), fy + 22 * SS))
    url = f"github.com/{OWNER}/{REPO}"
    d.text((lx, uy), url, font=f_url, fill=BRASS)
    box.add("url", (lx, uy, lx + d.textlength(url, font=f_url), uy + 22 * SS))

    # --- the measurement ---------------------------------------------------
    px = 686 * SS
    pw = int(406 * SS)
    f_lab = font(SANS, 15 * SS)
    f_mono = font(MONO, 16 * SS)
    f_val = font(MONO, 15 * SS)

    head = "CONTEXT WINDOW, MEASURED"
    d.text((px, 128 * SS), head, font=f_lab, fill=FAINT)
    box.add("chart-head", (px, 128 * SS, px + d.textlength(head, font=f_lab),
                           128 * SS + 18 * SS))

    floor_x = px + int(pw * (FLOOR / AXIS_MAX))
    top = 166 * SS
    row = 74 * SS
    bar_h = 17 * SS

    for i, (label, window, size) in enumerate(MODELS):
        y = top + i * row
        ok = window >= FLOOR
        d.text((px, y), label, font=f_mono, fill=INK if ok else MUTED)
        box.add(f"model-{i}", (px, y, px + d.textlength(label, font=f_mono),
                               y + 18 * SS))
        by = y + 26 * SS
        d.rounded_rectangle([px, by, px + pw, by + bar_h],
                            radius=bar_h // 2, fill="#E6E1D6")
        bw = max(int(pw * (window / AXIS_MAX)), bar_h)
        d.rounded_rectangle([px, by, px + bw, by + bar_h],
                            radius=bar_h // 2, fill=BRASS if ok else "#D8CFC4")
        value = fmt(window)
        vx = px + bw + 10 * SS
        # A short bar ends just left of the floor line, so its value would sit
        # on top of the one mark the chart exists to show. Push it clear.
        if vx + d.textlength(value, font=f_val) > floor_x - 4 * SS:
            vx = max(vx, floor_x + 11 * SS)
        d.text((vx, by + 1 * SS), value, font=f_val, fill=INK if ok else FAULT)
        box.add(f"value-{i}", (px, by, vx + d.textlength(value, font=f_val),
                               by + bar_h))

    # The floor, drawn across the bars only. A single line spanning the whole
    # chart runs straight through the model names and makes them hard to read —
    # the same mistake as an arc crossing a caption. Segments still read as one
    # floor because they share an x.
    for i in range(len(MODELS)):
        by = top + i * row + 26 * SS
        d.line([(floor_x, by - 9 * SS), (floor_x, by + bar_h + 9 * SS)],
               fill=SHINE, width=3 * SS)
    cap = f"{FLOOR:,} FLOOR"
    cy = top + 3 * row + 58 * SS
    cw = d.textlength(cap, font=f_lab)
    # A caption centred under its element can still leave the box; clamp it.
    cx = min(max(floor_x - cw / 2, SAFE * SS), W * SS - SAFE * SS - cw)
    d.text((cx, cy), cap, font=f_lab, fill=BRASS)
    box.add("floor-caption", (cx, cy, cx + cw, cy + 18 * SS))

    margin = box.check()
    im.resize((W, H), Image.LANCZOS).save(path)
    return margin // SS


def render_mark(path: str, size: int = 512) -> None:
    SS = 2
    im = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    inset = int(size * SS * 0.11)
    draw_mark(d, inset, int(size * SS * 0.16), size * SS - inset * 2,
              INK, BRASS, SHINE)
    im.resize((size, size), Image.LANCZOS).save(path)


def assert_safe_border(path: str, margin: int = 80) -> None:
    """Belt and braces: measure the finished file as well as the model.

    The renderer supersamples and rescales, so the margin in the code is not
    necessarily the margin in the file. Only genuinely dark ink counts: LANCZOS
    rings at a high-contrast edge and can overshoot past either input colour,
    so a threshold set just under the lightest drawn tone reports phantom ink.
    """
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()

    def dark(p) -> bool:
        # Below every paper-ish tone (rules, troughs, inactive bars all sit
        # above 600) and above nothing that carries words.
        return sum(p) < 500

    points = [(x, y) for y in range(H) for x in range(W) if dark(px[x, y])]
    assert points, "nothing was drawn"
    left = min(p[0] for p in points)
    right = max(p[0] for p in points)
    top = min(p[1] for p in points)
    bottom = max(p[1] for p in points)
    worst = min(left, W - 1 - right, top, H - 1 - bottom)
    print(f"  measured margins  left {left}  right {W - 1 - right}  "
          f"top {top}  bottom {H - 1 - bottom}")
    assert worst >= margin, (
        f"ink reaches {worst}px from an edge; GitHub's safe border needs {margin}px")


def main() -> int:
    os.makedirs(IMAGES, exist_ok=True)
    card = os.path.join(IMAGES, "social-preview.png")
    mark = os.path.join(IMAGES, "mark.png")
    registered = render_card(card)
    print(f"  {card}")
    print(f"  registered margin {registered}px (safe border is 80px)")
    assert_safe_border(card, 80)
    render_mark(mark)
    print(f"  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
