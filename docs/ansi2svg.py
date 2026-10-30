#!/usr/bin/env python3
"""Capture tmux (capture-pane -e) -> image SVG d'un terminal.

    ansi2svg.py capture.txt image.svg COLONNES [titre]

Sert à produire les captures du README (docs/*.svg) sans outil
graphique : les caractères et les couleurs du terminal sont gardés.
Exemple, pour le menu principal :

    tmux new-session -d -s cap -x 96 -y 19 ./menuDoom2Nethack.sh; sleep 1
    tmux capture-pane -e -p -t cap > menu.ans
    python3 docs/ansi2svg.py menu.ans docs/menu.svg 96 ./menuDoom2Nethack.sh
    tmux kill-session -t cap

La capture de NetHack se fait de la même façon (80 x 24), après avoir
chargé le niveau avec `python3 -m d2n.play e1m1` dans la session tmux.
"""
import html
import re
import sys

PAL = ["#1e1e1e", "#cd3131", "#0dbc79", "#e5e510",
       "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5"]
BRIGHT = ["#666666", "#f14c4c", "#23d18b", "#f5f543",
          "#3b8eea", "#d670d6", "#29b8db", "#ffffff"]
FG, BG = "#d4d4d4", "#1e1e1e"
FONT = 14
CW, CH = 8.43, 18          # largeur et hauteur d'une case
PAD, TOP = 12, 34          # marges, hauteur de la barre de fenêtre


def parse(text, cols):
    """Lignes de cases (car, couleur texte, couleur fond, gras, souligné)."""
    rows = []
    st = dict(fg=None, bg=None, bold=False, dim=False, rev=False, ul=False)
    for line in text.split("\n"):
        cells = []
        for m in re.finditer(r"\x1b\[([0-9;]*)m|(.)", line):
            if m.group(2) is None:
                codes = [int(c) for c in m.group(1).split(";") if c] or [0]
                for c in codes:
                    if c == 0:
                        st = dict(fg=None, bg=None, bold=False, dim=False,
                                  rev=False, ul=False)
                    elif c == 1:
                        st["bold"] = True
                    elif c == 2:
                        st["dim"] = True
                    elif c == 4:
                        st["ul"] = True
                    elif c == 7:
                        st["rev"] = True
                    elif c == 22:
                        st["bold"] = st["dim"] = False
                    elif c == 24:
                        st["ul"] = False
                    elif c == 27:
                        st["rev"] = False
                    elif 30 <= c <= 37:
                        st["fg"] = c - 30
                    elif c == 39:
                        st["fg"] = None
                    elif 40 <= c <= 47:
                        st["bg"] = c - 40
                    elif c == 49:
                        st["bg"] = None
                    elif 90 <= c <= 97:
                        st["fg"] = c - 90 + 8
                continue
            cells.append((m.group(2), *colors(st), st["bold"], st["ul"]))
        # tmux coupe les espaces de fin : on prolonge le fond courant
        while len(cells) < cols:
            cells.append((" ", *colors(st), False, False))
        rows.append(cells[:cols])
    return rows


def colors(st):
    if st["fg"] is None:
        fg = FG
    elif st["fg"] >= 8:
        fg = BRIGHT[st["fg"] - 8]
    else:
        fg = (BRIGHT if st["bold"] else PAL)[st["fg"]]
    if st["dim"]:
        fg = "#" + "".join(f"{int(fg[i:i + 2], 16) * 55 // 100:02x}"
                           for i in (1, 3, 5))
    bg = PAL[st["bg"]] if st["bg"] is not None else BG
    if st["rev"]:
        fg, bg = (bg if st["bg"] is not None else BG), \
            (fg if st["fg"] is not None else FG)
    return fg, bg


def svg(rows, title):
    cols = max(len(r) for r in rows)
    w = PAD * 2 + cols * CW
    h = TOP + PAD + len(rows) * CH
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" '
           f'height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}">',
           '<style>text{font-family:"DejaVu Sans Mono",Menlo,Consolas,'
           f'"Liberation Mono",monospace;font-size:{FONT}px;'
           'white-space:pre}.b{font-weight:bold}.u{text-decoration:'
           'underline}</style>',
           f'<rect width="{w:.0f}" height="{h:.0f}" rx="8" fill="{BG}"/>',
           f'<rect width="{w:.0f}" height="{TOP - 6}" rx="8" fill="#323233"/>',
           f'<rect y="{TOP - 14}" width="{w:.0f}" height="8" fill="#323233"/>']
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        out.append(f'<circle cx="{18 + i * 20}" cy="{(TOP - 6) / 2}" r="6" '
                   f'fill="{c}"/>')
    out.append(f'<text x="{w / 2:.0f}" y="{(TOP - 6) / 2 + 5}" '
               f'fill="#aaaaaa" text-anchor="middle" style="font-size:13px">'
               f'{html.escape(title)}</text>')
    for j, row in enumerate(rows):
        y = TOP + j * CH
        # fonds
        x = 0
        while x < len(row):
            k = x
            while k < len(row) and row[k][2] == row[x][2]:
                k += 1
            if row[x][2] != BG:
                out.append(f'<rect x="{PAD + x * CW:.2f}" y="{y}" '
                           f'width="{(k - x) * CW + 0.6:.2f}" height="{CH}" '
                           f'fill="{row[x][2]}"/>')
            x = k
        # textes, par suites de même style
        x = 0
        while x < len(row):
            k = x
            style = row[x][1], row[x][3], row[x][4]
            while k < len(row) and (row[k][1], row[k][3], row[k][4]) == style:
                k += 1
            text = "".join(c[0] for c in row[x:k])
            if text.strip():
                cls = " ".join(c for c, on in (("b", style[1]),
                                              ("u", style[2])) if on)
                cls = f' class="{cls}"' if cls else ""
                out.append(f'<text x="{PAD + x * CW:.2f}" y="{y + 14}" '
                           f'fill="{style[0]}"{cls} textLength='
                           f'"{(k - x) * CW:.2f}" lengthAdjust='
                           f'"spacingAndGlyphs">{html.escape(text)}</text>')
            x = k
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    src, dst, cols = sys.argv[1], sys.argv[2], int(sys.argv[3])
    title = sys.argv[4] if len(sys.argv) > 4 else ""
    text = open(src, encoding="utf-8").read().rstrip("\n")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(svg(parse(text, cols), title))
