#!/usr/bin/env bash
# Lance le menu interactif de Doom2Nethack (Doom2Nethack.py).
#
#   ./Doom2Nethack.sh [WAD]
#
# Sans WAD, le menu reprend le dernier fichier utilisé, ou propose d'en
# choisir un.  Les variables HACKDIR et NETHACK (répertoire de jeu et
# exécutable NetHack) et WAD_DIR (répertoire des WAD, où est cherché un
# WAD introuvable) sont transmises au menu, comme pour
# convertDoom2Nethack.sh.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
export WAD_DIR=${WAD_DIR:-$(dirname "$SCRIPT_DIR")/Doom/Wad}

die() { echo "Doom2Nethack.sh : $*" >&2; exit 1; }

case "${1:-}" in
-h|--help)
    cat <<EOF
Usage : $(basename "$0") [WAD]

Menu interactif : conversion des cartes du fichier WAD (défaut : le
dernier utilisé) et niveaux déjà convertis, rangés dans out/<WAD>/.
Un WAD introuvable est cherché dans WAD_DIR ($WAD_DIR).
EOF
    exit 0 ;;
esac
[ $# -le 1 ] || die "un seul fichier WAD attendu (voir --help)"
[ $# -eq 0 ] || [ -f "$1" ] || [ -f "$WAD_DIR/$1" ] ||
    die "WAD introuvable : $1 (ni dans $WAD_DIR)"

command -v python3 > /dev/null || die "python3 introuvable"
python3 -c "import curses" 2> /dev/null ||
    die "module Python curses absent (paquet python3 de la distribution)"
[ -t 0 ] && [ -t 1 ] || die "un terminal est nécessaire"

# Le chemin du WAD reste relatif au répertoire courant : pas de cd.
exec python3 "$SCRIPT_DIR/Doom2Nethack.py" "$@"
