"""Draws the README's privacy diagram in Steward's day and night colours.

    uv run python scripts/readme_diagram.py

Writes docs/images/privacy-flow-light.svg and docs/images/privacy-flow-dark.svg. The README shows one or the other
with <picture>, following the reader's GitHub theme. The rows follow docs/explanations/privacy.md: aliases such as
"Account 1" and "Payee 4" (src/steward/advisor/aliases.py), notes never sent (P3), no account numbers (P5).
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"

# From web/src/styles/sky.css: the day phase and the night phase.
THEMES = {
    "light": dict(bg="#FAF8F3", surface="#FFFFFF", surface2="#EDEDEA", ink="#17212A", muted="#42505C",
                  line="#D9D8D4", accent="#7C3352", accent_text="#7C3352", tint="#7C3352", tint_a="0.07",
                  pill_a="0.12", green="#33793B"),
    "dark": dict(bg="#0E1729", surface="#17233C", surface2="#26344F", ink="#EEF1EC", muted="#B8C3C9",
                 line="#34425E", accent="#A9567E", accent_text="#EBB3CC", tint="#A9567E", tint_a="0.16",
                 pill_a="0.22", green="#8DC49A"),
}

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
W, H = 880, 452
LX, LW = 28, 292           # left column: what Steward holds
GX, GW = 352, 176          # the gateway band
RX, RW = 560, 292          # right column: what Claude sees
ROW_Y, ROW_H, ROW_GAP = 104, 50, 14

# (on your machine, amount, what Claude sees, kind): kind "alias" swaps the label, "kept" passes as is, "home" stops.
ROWS = [
    ("Joint checking ••4417", "$4,212", "Account 1", "alias"),
    ("Venmo to Dana", "−$120", "Payee 4", "alias"),
    ("Note: braces for Theo", "", "Never sent", "home"),
    ("Eating out, November", "$386", "Eating out, November", "kept"),
]


def text(x: float, y: float, s: str, *, size: float = 15, fill: str, weight: int = 400, anchor: str = "start",
         extra: str = "") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{escape(s)}</text>')


def draw(t: dict[str, str]) -> str:
    p: list[str] = []
    add = p.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{SANS}" role="img" aria-labelledby="title desc">')
    add('<title id="title">What leaves your machine when you ask Steward a question</title>')
    add('<desc id="desc">Steward sends your question through your own gateway. Account and payee names become '
        'aliases such as Account 1 and Payee 4, notes and account numbers stay on your machine, and figures such '
        'as spending by category go through. The answer comes back in aliases and Steward puts the real names '
        'back on your screen.</desc>')
    add('<defs>'
        f'<marker id="head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{t["muted"]}"/></marker>'
        f'<marker id="headA" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{t["accent"]}"/></marker>'
        '</defs>')
    add(f'<rect width="{W}" height="{H}" rx="18" fill="{t["bg"]}"/>')

    # Column headings.
    add(text(LX, 52, "On your machine", size=19, weight=650, fill=t["ink"]))
    add(text(LX, 76, "What Steward holds", size=14, fill=t["muted"]))
    add(text(RX, 52, "Claude", size=19, weight=650, fill=t["ink"]))
    add(text(RX, 76, "What it sees", size=14, fill=t["muted"]))

    rows_bottom = ROW_Y + len(ROWS) * ROW_H + (len(ROWS) - 1) * ROW_GAP
    # The gateway: a band every question passes through.
    gy, gh = ROW_Y - 66, rows_bottom - ROW_Y + 84
    add(f'<rect x="{GX}" y="{gy}" width="{GW}" height="{gh}" rx="16" fill="{t["tint"]}" '
        f'fill-opacity="{t["tint_a"]}" stroke="{t["accent"]}" stroke-width="1.5"/>')
    cx = GX + GW / 2
    # A small shield.
    sy = gy + 18
    add(f'<path d="M{cx} {sy} l11 4 v8 c0 7 -5 11 -11 14 c-6 -3 -11 -7 -11 -14 v-8 z" fill="none" '
        f'stroke="{t["accent_text"]}" stroke-width="1.8" stroke-linejoin="round"/>')
    add(f'<path d="M{cx - 4.5} {sy + 13} l3.2 3.2 l6 -6.4" fill="none" stroke="{t["accent_text"]}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')
    add(text(cx, gy + 62, "Your gateway", size=16, weight=650, fill=t["ink"], anchor="middle"))

    for i, (held, amount, seen, kind) in enumerate(ROWS):
        y = ROW_Y + i * (ROW_H + ROW_GAP)
        mid = y + ROW_H / 2
        base = mid + 5
        # The path through the gateway, drawn first so the band's labels sit on top of it.
        if kind == "home":
            add(f'<line x1="{LX + LW}" y1="{mid}" x2="{cx - 52}" y2="{mid}" stroke="{t["muted"]}" '
                f'stroke-width="1.5" stroke-dasharray="3 4"/>')
        else:
            add(f'<line x1="{LX + LW}" y1="{mid}" x2="{RX - 2}" y2="{mid}" stroke="{t["muted"]}" '
                f'stroke-width="1.5" marker-end="url(#head)"/>')
        # What the gateway did to this row.
        label = {"alias": "name → alias", "kept": "sent as is", "home": "stops here"}[kind]
        dash = ' stroke-dasharray="3 3"' if kind == "home" else ""
        add(f'<rect x="{cx - 52}" y="{mid - 12}" width="104" height="24" rx="12" '
            f'fill="{t["bg"]}" stroke="{t["muted"] if kind == "home" else t["line"]}"{dash}/>')
        add(text(cx, mid + 4.5, label, size=12.5, fill=t["muted"], anchor="middle"))

        # Left: what Steward holds.
        add(f'<rect x="{LX}" y="{y}" width="{LW}" height="{ROW_H}" rx="10" fill="{t["surface"]}" '
            f'stroke="{t["line"]}"/>')
        add(text(LX + 16, base, held, fill=t["ink"]))
        if amount:
            add(text(LX + LW - 16, base, amount, fill=t["ink"], weight=600, anchor="end",
                     extra=' font-variant-numeric="tabular-nums"'))

        # Right: what Claude sees.
        if kind == "home":
            add(f'<rect x="{RX}" y="{y}" width="{RW}" height="{ROW_H}" rx="10" fill="none" stroke="{t["line"]}" '
                f'stroke-dasharray="5 5"/>')
            add(text(RX + 16, base, seen, fill=t["muted"],
                     extra=' font-style="italic"'))
            continue
        add(f'<rect x="{RX}" y="{y}" width="{RW}" height="{ROW_H}" rx="10" fill="{t["surface"]}" '
            f'stroke="{t["line"]}"/>')
        if kind == "alias":
            pw = 14 + 8.6 * len(seen)
            add(f'<rect x="{RX + 10}" y="{mid - 14}" width="{pw}" height="28" rx="8" fill="{t["tint"]}" '
                f'fill-opacity="{t["pill_a"]}"/>')
            add(text(RX + 17, base, seen, fill=t["accent_text"], weight=650))
        else:
            add(text(RX + 16, base, seen, fill=t["ink"]))
        add(text(RX + RW - 16, base, amount, fill=t["ink"], weight=600, anchor="end",
                 extra=' font-variant-numeric="tabular-nums"'))

    # The answer coming back.
    ay = rows_bottom + 50
    add(f'<line x1="{RX + RW - 8}" y1="{ay}" x2="{LX + 8}" y2="{ay}" stroke="{t["accent"]}" stroke-width="1.8" '
        f'marker-end="url(#headA)"/>')
    add(f'<rect x="{W / 2 - 250}" y="{ay - 15}" width="500" height="30" rx="15" fill="{t["bg"]}"/>')
    add(text(W / 2, ay + 5, "The answer comes back in aliases. Steward puts the real names back.",
             size=14.5, fill=t["ink"], weight=600, anchor="middle"))
    add(text(W / 2, H - 26, "Steward never connects to Claude; only your gateway does. A local model there also "
             "looks for names Steward doesn't hold, and can miss one.", size=12.5, fill=t["muted"], anchor="middle"))
    add("</svg>")
    return "\n".join(p) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        (OUT / f"privacy-flow-{name}.svg").write_text(draw(theme), encoding="utf-8")


if __name__ == "__main__":
    main()
