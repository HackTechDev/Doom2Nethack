#!/usr/bin/env python3
"""Menu interactif de Doom2Nethack : conversion des cartes d'un WAD et
niveaux déjà convertis (rangés dans out/<WAD>/).

    ./Doom2Nethack.py [--theme NOM] [--sans-souris] [WAD]
"""

import sys

from d2n.tui import main

if __name__ == "__main__":
    sys.exit(main())
