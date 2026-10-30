"""Écriture d'un niveau spécial NetHack (Lua, cf. dat/*.lua)."""

from .dungeon import branch_block, dungeon_block


def to_lua(res, source="", branch=False):
    """`branch` : premier niveau d'une branche ; l'escalier de branche (vers
    le donjon parent) remplace l'escalier montant, que NetHack ignore au
    premier niveau d'un donjon (mkstairs())."""
    out = [
        f"-- Niveau {res.name} converti depuis {source or 'un WAD Doom'}",
        "-- par Doom2Nethack.  Test : #wizloaddes en mode wizard.",
        "",
        'des.level_init({ style = "solidfill", fg = " " });',
        'des.level_flags("mazelevel", "noflip");',
        "",
        'des.map({ halign = "center", valign = "center", map = [[',
        *res.grid,
        "]] });",
        "",
        f"des.region(selection.area(00,00,{res.width - 1:02d},"
        f"{res.height - 1:02d}), \"lit\");",
        "",
    ]
    if res.upstair:
        x, y = res.upstair
        if branch:
            out.append(f"des.levregion({{ region = {{{x:02d},{y:02d},"
                       f'{x:02d},{y:02d}}}, type = "branch" }})')
        else:
            out.append(f'des.stair("up", {x:02d},{y:02d})')
    if res.downstair:
        out.append(f'des.stair("down", {res.downstair[0]:02d},'
                   f'{res.downstair[1]:02d})')
    for x, y, state in res.doors:
        out.append(f'des.door("{state}", {x:02d},{y:02d})')
    for x, y, name, invis, asleep in res.monsters:
        # toujours hostile : par défaut NetHack tire au hasard selon
        # l'alignement du héros (lspo_monster())
        extra = "".join([", invisible = 1" if invis else "",
                         ", asleep = 1" if asleep else ""])
        out.append(f'des.monster({{ id = "{name}", x = {x:02d}, '
                   f'y = {y:02d}, peaceful = 0{extra} }})')
    for x, y, cls, name in res.objects:
        out.append(f'des.object({{ id = "{name}", class = "{cls}", '
                   f'x = {x:02d}, y = {y:02d} }})')
    return "\n".join(out) + "\n"


def dungeon_snippet(dungeon_name, level_names):
    """Extrait à intégrer dans dat/dungeon.lua pour une branche de
    plusieurs niveaux (test_level.sh le fait automatiquement)."""
    branch = "".join("-- " + line + "\n" for line in
                     branch_block(dungeon_name).rstrip("\n").split("\n"))
    files = ", ".join(n + ".lua" for n in level_names)
    return f"""\
-- Branche « {dungeon_name} » générée par Doom2Nethack.
-- (test_level.sh fait toutes ces étapes automatiquement.)
--
-- 1) Dans dat/dungeon.lua, ajouter à la liste `branches` de
--    « The Dungeons of Doom » (escalier descendant vers la branche,
--    entre les niveaux 2 et 4) :
--
{branch}--
-- 2) Ajouter ce donjon à la liste `dungeon` (par exemple juste avant
--    « Fort Ludios ») :

{dungeon_block(dungeon_name, level_names)}
-- 3) Reconstruire l'archive nhdat, dont dungeon.lua fait partie
--    (make dlb dans les sources NetHack), et copier dat/nhdat dans
--    HACKDIR.  Éviter make install, qui efface HACKDIR (sauvegardes,
--    record, sysconf).
-- 4) Copier {files} dans HACKDIR.
"""
