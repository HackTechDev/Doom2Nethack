#!/usr/bin/env python3
"""Convertit un niveau Doom (WAD) en niveau(x) spécial(aux) NetHack (Lua)."""

import argparse
import os
import sys

from d2n.convert import MAX_HEIGHT, MAX_WIDTH, Options, convert
from d2n.lua_out import dungeon_snippet, to_lua
from d2n.split import MAX_PARTS, auto_parts, convert_parts
from d2n.wad import Wad, WadError, find_wad

# Répertoire de sortie par défaut (ignoré par git).
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def parts_arg(value):
    if value == "auto":
        return value
    n = int(value)
    if not 1 <= n <= MAX_PARTS:
        raise argparse.ArgumentTypeError(f"entre 1 et {MAX_PARTS}")
    return n


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wad", help="fichier WAD (IWAD ou PWAD), cherché aussi "
                   "dans le répertoire des WAD (WAD_DIR)")
    p.add_argument("-m", "--map", help="niveau à convertir (MAP01, E1M1...)"
                   " ; par défaut le premier")
    p.add_argument("-o", "--output", help="fichier .lua de sortie pour un "
                   "seul niveau (défaut : out/<wad>/<niveau>.lua ; '-' pour "
                   "la sortie standard)")
    p.add_argument("-n", "--parts", type=parts_arg, default=1,
                   help="découper en N niveaux NetHack reliés par des "
                   f"escaliers (1 à {MAX_PARTS}, ou 'auto')")
    p.add_argument("-d", "--outdir",
                   help="répertoire de sortie pour un niveau découpé "
                   "(défaut : out/<wad>/<niveau>)")
    p.add_argument("-l", "--list", action="store_true",
                   help="lister les niveaux du WAD")
    p.add_argument("-p", "--preview", action="store_true",
                   help="afficher la carte obtenue")
    p.add_argument("--width", type=int, default=MAX_WIDTH)
    p.add_argument("--height", type=int, default=MAX_HEIGHT)
    p.add_argument("--keep-aspect", action="store_true",
                   help="échelle uniforme au lieu d'étirer la carte")
    p.add_argument("--samples", type=int, default=3,
                   help="échantillons par case et par axe (défaut 3)")
    p.add_argument("--coverage", type=float, default=0.34,
                   help="fraction de case couverte pour faire un sol")
    p.add_argument("--hazards", choices=("none", "water", "lava"),
                   default="none",
                   help="rendu des sols à dégâts (nukage, lave...)")
    p.add_argument("--mode", choices=("raster", "rooms"), default="raster",
                   help="raster : plan décalqué case par case (défaut) ; "
                   "rooms : salles rectangulaires reliées par des couloirs")
    p.add_argument("--rooms", type=int, default=0,
                   help="mode rooms : nombre de salles visé par niveau "
                   "(défaut : automatique, 12 au plus)")
    p.add_argument("--dark-below", type=int, default=144,
                   help="zones sombres : secteurs dont la lumière Doom "
                   "(0-255) est inférieure (défaut 144 ; 0 : tout éclairé)")
    p.add_argument("--skill", choices=("easy", "medium", "hard"),
                   default="medium",
                   help="difficulté Doom des monstres et objets")
    a = p.parse_args(argv)
    a.wad = find_wad(a.wad)

    if not 3 <= a.width <= MAX_WIDTH or not 3 <= a.height <= MAX_HEIGHT:
        p.error(f"taille maximale {MAX_WIDTH}x{MAX_HEIGHT}")
    opts = Options(a.width, a.height, a.samples, a.coverage, a.keep_aspect,
                   a.hazards, a.skill, a.mode, a.rooms, a.dark_below)
    try:
        wad = Wad(a.wad)
        names = wad.level_names()
        if a.list:
            print("\n".join(names))
            return 0
        if not names:
            raise WadError(f"{a.wad} : aucun niveau")
        level = wad.load_level(a.map or names[0])
        n = auto_parts(level, opts) if a.parts == "auto" else a.parts
        results = [convert(level, opts)] if n == 1 else \
            convert_parts(level, n, opts)
    except (WadError, ValueError, OSError) as e:
        print(f"doom2nethack : {e}", file=sys.stderr)
        return 1

    source = os.path.basename(a.wad)
    # out/<nom du WAD sans extension>/, comme le menu (d2n/tui.py)
    wad_dir = os.path.join(OUT_DIR, os.path.splitext(source)[0])
    log = sys.stderr if a.output == "-" else sys.stdout
    written = []
    if n == 1:
        out = a.output or os.path.join(wad_dir,
                                       f"{results[0].name.lower()}.lua")
        lua = to_lua(results[0], source)
        if out == "-":
            sys.stdout.write(lua)
        else:
            written.append(_write(out, lua))
    else:
        outdir = a.outdir or os.path.join(wad_dir, level.name.lower())
        for i, res in enumerate(results):
            written.append(_write(os.path.join(outdir, f"{res.name}.lua"),
                                  to_lua(res, source, branch=i == 0)))
        snippet = dungeon_snippet(f"Doom {level.name}",
                                  [r.name for r in results])
        written.append(_write(os.path.join(
            outdir, f"{level.name.lower()}-dungeon.lua"), snippet))

    for res in results:
        if a.preview:
            print("\n".join(_with_stairs(res)), file=log)
        print(f"{res.name} : carte {res.width}x{res.height}, "
              f"{res.scale[0]:.0f}x{res.scale[1]:.0f} unités par case, "
              f"{len(res.doors)} porte(s), {len(res.monsters)} monstre(s), "
              f"{len(res.objects)} objet(s)", file=log)
        floor = sum(row.count(".") + row.count("#") + row.count("+")
                    for row in res.grid)
        dark = sum(res.grid[y][x] in ".#+" for x, y in res.dark)
        if dark:
            res.info.append(f"{100 * dark // max(floor, 1)} % du sol dans "
                            "le noir")
        for i in res.info:
            print(f"  info : {i}", file=log)
        for w in res.warnings:
            print(f"  attention : {w}", file=log)
    for path in written:
        print(f"écrit : {path}", file=log)
    return 0


def _write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def _with_stairs(res):
    """Carte avec les escaliers, pour l'aperçu."""
    grid = [list(row) for row in res.grid]
    for c, pos in (("<", res.upstair), (">", res.downstair)):
        if pos:
            grid[pos[1]][pos[0]] = c
    return ["".join(row) for row in grid]


if __name__ == "__main__":
    sys.exit(main())
