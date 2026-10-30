#!/usr/bin/env python3
"""Convertit un niveau Doom (WAD) en niveau spécial NetHack (Lua)."""

import argparse
import os
import sys

from d2n.convert import MAX_HEIGHT, MAX_WIDTH, Options, convert
from d2n.lua_out import to_lua
from d2n.wad import Wad, WadError


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wad", help="fichier WAD (IWAD ou PWAD)")
    p.add_argument("-m", "--map", help="niveau à convertir (MAP01, E1M1...)"
                   " ; par défaut le premier")
    p.add_argument("-o", "--output", help="fichier .lua de sortie "
                   "(défaut : <niveau>.lua ; '-' pour la sortie standard)")
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
    a = p.parse_args(argv)

    if not 3 <= a.width <= MAX_WIDTH or not 3 <= a.height <= MAX_HEIGHT:
        p.error(f"taille maximale {MAX_WIDTH}x{MAX_HEIGHT}")
    try:
        wad = Wad(a.wad)
        names = wad.level_names()
        if a.list:
            print("\n".join(names))
            return 0
        if not names:
            raise WadError(f"{a.wad} : aucun niveau")
        level = wad.load_level(a.map or names[0])
        res = convert(level, Options(a.width, a.height, a.samples,
                                     a.coverage, a.keep_aspect, a.hazards))
    except (WadError, ValueError, OSError) as e:
        print(f"doom2nethack : {e}", file=sys.stderr)
        return 1

    lua = to_lua(res, os.path.basename(a.wad))
    out = a.output or f"{res.name.lower()}.lua"
    if out == "-":
        sys.stdout.write(lua)
    else:
        with open(out, "w") as f:
            f.write(lua)

    log = sys.stderr if out == "-" else sys.stdout
    if a.preview:
        print("\n".join(res.grid), file=log)
    print(f"{res.name} : carte {res.width}x{res.height}, "
          f"{res.scale[0]:.0f}x{res.scale[1]:.0f} unités par case, "
          f"{len(res.doors)} porte(s), {len(res.monsters)} monstre(s), "
          f"{len(res.objects)} objet(s)", file=log)
    for w in res.warnings:
        print(f"  attention : {w}", file=log)
    if out != "-":
        print(f"écrit : {out}", file=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
