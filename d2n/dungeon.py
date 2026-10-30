"""Déclaration d'une branche Doom dans dat/dungeon.lua de NetHack.

Les blocs ajoutés sont encadrés de marqueurs, ce qui permet de les
remplacer ou de les retirer :

    python3 -m d2n.dungeon patch dat/dungeon.lua "Doom E1M1" e1m1a e1m1b
    python3 -m d2n.dungeon unpatch dat/dungeon.lua [nom]
"""

import re
import sys

BEGIN = "-- doom2nethack:begin "
END = "-- doom2nethack:end "


def branch_block(name, base=2, rng=3):
    """Entrée de la liste `branches` des Dungeons of Doom (escalier vers la
    branche entre les niveaux base et base + rng - 1)."""
    return (f"         {{\n"
            f'            name = "{name}",\n'
            f"            base = {base},\n"
            f"            range = {rng}\n"
            f"         }},\n")


def dungeon_block(name, level_names):
    """Entrée de la liste `dungeon` : un donjon d'un niveau par morceau."""
    levels = "".join(f'         {{ name = "{n}", base = {i} }},\n'
                     for i, n in enumerate(level_names, 1))
    return (f"   {{\n"
            f'      name = "{name}",\n'
            f"      base = {len(level_names)},\n"
            f'      flags = {{ "mazelike" }},\n'
            f"      levels = {{\n"
            f"{levels}"
            f"      }}\n"
            f"   }},\n")


def _marked(name, block, indent):
    return f"{indent}{BEGIN}{name}\n{block}{indent}{END}{name}\n"


def declared(text):
    """Branches Doom déclarées dans le texte de dungeon.lua : {nom : liste
    des niveaux}."""
    pattern = (rf"{re.escape(BEGIN)}(?P<n>[^\n]*)\n(?P<b>.*?)"
               rf"{re.escape(END)}(?P=n)\n")
    out = {}
    for m in re.finditer(pattern, text, flags=re.S):
        if "levels = {" in m.group("b"):        # bloc du donjon
            out[m.group("n")] = re.findall(r'\{ name = "([^"]+)"',
                                           m.group("b"))
    return out


def unpatch(text, name=None):
    """Retire les blocs de la branche `name` (toutes si None)."""
    who = re.escape(name) if name else r"[^\n]*"
    pattern = (rf"[ \t]*{re.escape(BEGIN)}(?P<n>{who})\n.*?"
               rf"[ \t]*{re.escape(END)}(?P=n)\n")
    return re.sub(pattern, "", text, flags=re.S)


def patch(text, name, level_names):
    """Ajoute (ou remplace) la branche `name` dans le texte de
    dungeon.lua."""
    text = unpatch(text, name)
    main = text.find('name = "The Dungeons of Doom"')
    if main < 0:
        raise ValueError("« The Dungeons of Doom » introuvable")
    m = re.compile(r"^      branches = \{\n", re.M).search(text, main)
    if not m:
        raise ValueError("liste `branches` introuvable")
    text = (text[:m.end()] + _marked(name, branch_block(name), " " * 9) +
            text[m.end():])
    m = re.search(r'^   \{\n      name = "Fort Ludios",', text, re.M)
    if not m:
        raise ValueError("« Fort Ludios » introuvable")
    return (text[:m.start()] +
            _marked(name, dungeon_block(name, level_names), " " * 3) +
            text[m.start():])


def main(argv):
    if len(argv) >= 4 and argv[1] == "patch":
        path, name, levels = argv[2], argv[3], argv[4:]
        if not levels:
            raise SystemExit("aucun niveau")
        func = lambda t: patch(t, name, levels)          # noqa: E731
    elif len(argv) in (3, 4) and argv[1] == "unpatch":
        path = argv[2]
        name = argv[3] if len(argv) == 4 else None
        func = lambda t: unpatch(t, name)                # noqa: E731
    else:
        raise SystemExit(__doc__)
    with open(path) as f:
        text = f.read()
    try:
        new = func(text)
    except ValueError as e:
        raise SystemExit(f"{path} : {e}")
    with open(path, "w") as f:
        f.write(new)


if __name__ == "__main__":
    main(sys.argv)
