"""Correspondances Doom -> NetHack (types de linedefs, secteurs, things)."""

# Portes manuelles : le secteur porte est du côté gauche (arrière) du
# linedef.  Valeur : état NetHack de la porte.
DOOR_LINEDEFS = {
    1: "closed", 117: "closed",                 # porte normale / rapide
    31: "closed", 118: "closed",                # ouverture permanente
    26: "locked", 27: "locked", 28: "locked",   # portes à clé
    32: "locked", 33: "locked", 34: "locked",
}

# Fins de niveau (interrupteurs, lignes à franchir).
EXIT_LINEDEFS = {11, 51, 52, 124, 197, 198}

# Téléporteurs empruntés par le joueur (125 et 126 : monstres seulement) ;
# la destination est dans le secteur portant le tag du linedef.
TELEPORT_LINEDEFS = {39, 97}

# Linedef infranchissable (flag ML_BLOCKING).
ML_BLOCKING = 0x0001

# Types spéciaux de secteurs qui infligent des dégâts.
DAMAGE_SECTORS = {4, 5, 7, 11, 16}
SECRET_SECTOR = 9

# Monstre en embuscade (« deaf ») / thing présent seulement en multijoueur.
MTF_AMBUSH = 0x0008
MTF_MULTI = 0x0010

# Niveaux de difficulté où un thing est présent.
SKILL_FLAGS = {"easy": 0x0001, "medium": 0x0002, "hard": 0x0004}

PLAYER_START = 1

# Monstres Doom -> monstre NetHack (include/monsters.h) : (nom, invisible).
#
# La branche Doom se trouve vers les profondeurs 3 à 16, où le héros a
# typiquement un niveau d'expérience de 3 à 10.  Le niveau NetHack du
# monstre (« niv ») suit donc la force du monstre Doom (points de vie entre
# parenthèses) : piétaille 3-4, intermédiaires 5-8, lourds 8-11, et seuls
# les boss de fin d'épisode dépassent 12.
MONSTERS = {
    # piétaille
    3004: ("human zombie", False),      # zombieman (20) : niv 4, lent
    9: ("ghoul", False),                # shotgun guy (30) : niv 3, paralyse
    3001: ("imp", False),               # imp (60) : niv 3, rapide
    3006: ("fire ant", False),          # lost soul (100) : niv 3, feu
    # intermédiaires
    84: ("soldier", False),             # SS (50) : niv 6, armé
    65: ("soldier", False),             # chaingunner (70) : niv 6, armé
    3002: ("wolf", False),              # demon (150) : niv 5, morsure
    58: ("wolf", True),                 # spectre (150) : demon invisible
    3005: ("flaming sphere", False),    # cacodemon (400) : niv 6, explose
    71: ("gas spore", False),           # pain elemental (400) : explose
    66: ("human mummy", False),         # revenant (300) : niv 6
    68: ("giant spider", False),        # arachnotron (500) : niv 5
    67: ("ogre", False),                # mancubus (600) : niv 5
    # lourds
    69: ("horned devil", False),        # hell knight (500) : niv 6
    3003: ("barbed devil", False),      # baron of hell (1000) : niv 8
    64: ("lich", False),                # arch-vile (700) : niv 11
    # boss
    7: ("pit fiend", False),            # spider mastermind (3000) : niv 13
    16: ("balrog", False),              # cyberdemon (4000) : niv 16
}

# Objets Doom -> (classe, nom d'objet NetHack) (include/objects.h).
OBJECTS = {
    2011: ("!", "healing"),             # stimpack
    2012: ("!", "extra healing"),       # medikit
    2013: ("!", "full healing"),        # soulsphere
    2018: ("[", "ring mail"),           # armure verte
    2019: ("[", "plate mail"),          # armure bleue
    2005: (")", "two-handed sword"),    # tronçonneuse
    2001: (")", "crossbow"),            # fusil à pompe
    82: (")", "crossbow"),              # super fusil à pompe
    2002: (")", "crossbow bolt"),       # mitrailleuse
    2003: ("/", "striking"),            # lance-roquettes
    2004: ("/", "lightning"),           # fusil à plasma
    2006: ("/", "death"),               # BFG9000
    5: ("(", "skeleton key"),           # carte bleue
    6: ("(", "skeleton key"),           # carte jaune
    13: ("(", "skeleton key"),          # carte rouge
    38: ("(", "skeleton key"),          # crâne rouge
    39: ("(", "skeleton key"),          # crâne jaune
    40: ("(", "skeleton key"),          # crâne bleu
}

# Symbole NetHack des monstres de MONSTERS (aperçu des cartes).
SYMBOLS = {
    "human zombie": "Z", "ghoul": "Z", "imp": "i", "fire ant": "a",
    "soldier": "@", "wolf": "d", "flaming sphere": "e", "gas spore": "e",
    "human mummy": "M", "giant spider": "s", "ogre": "O",
    "horned devil": "&", "barbed devil": "&", "lich": "L",
    "pit fiend": "&", "balrog": "&",
}

# Noms Doom des things de MONSTERS et OBJECTS (aperçu des cartes).
DOOM_NAMES = {
    3004: "zombieman", 9: "shotgun guy", 3001: "imp", 3006: "lost soul",
    84: "SS", 65: "chaingunner", 3002: "demon", 58: "spectre",
    3005: "cacodemon", 71: "pain elemental", 66: "revenant",
    68: "arachnotron", 67: "mancubus", 69: "hell knight",
    3003: "baron of hell", 64: "arch-vile", 7: "spider mastermind",
    16: "cyberdemon",
    2011: "stimpack", 2012: "medikit", 2013: "soulsphere",
    2018: "armure verte", 2019: "armure bleue", 2005: "tronçonneuse",
    2001: "fusil à pompe", 82: "super fusil à pompe",
    2002: "mitrailleuse", 2003: "lance-roquettes", 2004: "fusil à plasma",
    2006: "BFG9000", 5: "carte bleue", 6: "carte jaune", 13: "carte rouge",
    38: "crâne rouge", 39: "crâne jaune", 40: "crâne bleu",
}


def doom_sources(table, value):
    """Noms Doom des things que `table` convertit en `value`."""
    return [DOOM_NAMES[t] for t, v in table.items()
            if v == value and t in DOOM_NAMES]
