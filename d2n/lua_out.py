"""Écriture d'un niveau spécial NetHack (Lua, cf. dat/*.lua)."""


def to_lua(res, source=""):
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
        out.append(f'des.stair("up", {res.upstair[0]:02d},'
                   f'{res.upstair[1]:02d})')
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
