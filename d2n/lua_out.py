"""Écriture d'un niveau spécial NetHack (Lua, cf. dat/*.lua)."""


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
    for x, y, name in res.monsters:
        out.append(f'des.monster("{name}", {x:02d}, {y:02d})')
    for x, y, cls, name in res.objects:
        out.append(f'des.object({{ id = "{name}", class = "{cls}", '
                   f'x = {x:02d}, y = {y:02d} }})')
    return "\n".join(out) + "\n"


def dungeon_snippet(dungeon_name, level_names):
    """Extrait à intégrer dans dat/dungeon.lua pour une branche de
    plusieurs niveaux."""
    levels = "\n".join(f'         {{ name = "{n}", base = {i} }},'
                       for i, n in enumerate(level_names, 1))
    return f"""\
-- Branche « {dungeon_name} » générée par Doom2Nethack.
--
-- 1) Dans dat/dungeon.lua, ajouter à la liste `branches` de
--    « The Dungeons of Doom » (escalier descendant vers la branche,
--    entre les niveaux 2 et 4) :
--
--       {{
--          name = "{dungeon_name}",
--          base = 2,
--          range = 3
--       }},
--
-- 2) Ajouter ce donjon à la liste `dungeon` (par exemple juste avant
--    « Fort Ludios ») :

   {{
      name = "{dungeon_name}",
      base = {len(level_names)},
      flags = {{ "mazelike" }},
      levels = {{
{levels}
      }}
   }},

-- 3) Recompiler et réinstaller (make install) : dungeon.lua fait partie
--    de l'archive nhdat.
-- 4) Copier ensuite {', '.join(n + '.lua' for n in level_names)}
--    dans HACKDIR (make install recrée ce répertoire).
"""
