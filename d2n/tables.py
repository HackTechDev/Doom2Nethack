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

# Linedef infranchissable (flag ML_BLOCKING).
ML_BLOCKING = 0x0001

# Types spéciaux de secteurs qui infligent des dégâts.
DAMAGE_SECTORS = {4, 5, 7, 11, 16}
SECRET_SECTOR = 9

# Thing présent seulement en multijoueur.
MTF_MULTI = 0x0010

# Niveaux de difficulté où un thing est présent.
SKILL_FLAGS = {"easy": 0x0001, "medium": 0x0002, "hard": 0x0004}

PLAYER_START = 1

# Monstres Doom -> nom de monstre NetHack (include/monsters.h).
MONSTERS = {
    3004: "human zombie",       # zombieman
    9: "soldier",               # shotgun guy
    65: "sergeant",             # chaingunner
    84: "soldier",              # Wolfenstein SS
    3001: "imp",                # imp
    3002: "hell hound",         # demon (pinky)
    58: "stalker",              # spectre (invisible)
    3006: "flaming sphere",     # lost soul
    3005: "floating eye",       # cacodemon
    71: "flaming sphere",       # pain elemental
    69: "bone devil",           # hell knight
    3003: "pit fiend",          # baron of hell
    68: "giant spider",         # arachnotron
    66: "skeleton",             # revenant
    67: "ettin",                # mancubus
    64: "lich",                 # arch-vile
    7: "giant spider",          # spider mastermind
    16: "balrog",               # cyberdemon
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
