#!/usr/bin/env bash
# Convertit un niveau Doom et l'installe dans NetHack pour le tester.
#
#   ./convertDoom2Nethack.sh [options] WAD [NIVEAU]
#
# Un seul niveau NetHack (défaut) : le .lua est copié dans HACKDIR, à charger
# avec #wizloaddes.  Avec -n, le niveau Doom devient une branche de plusieurs
# niveaux : dat/dungeon.lua est modifié, l'archive nhdat reconstruite
# (make dlb) et copiée dans HACKDIR.  On n'utilise pas make install, qui
# efface HACKDIR (parties sauvegardées, record, sysconf).

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
NETHACK_SRC=${NETHACK_SRC:-/home/sgond/app/Nethack500_Lubuntu2604}
HACKDIR=${HACKDIR:-$HOME/nh/install/games/lib/nethackdir}
NETHACK=${NETHACK:-$(dirname "$(dirname "$HACKDIR")")/nethack}
OUTDIR=${OUTDIR:-$SCRIPT_DIR/out}
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

usage() {
    cat <<EOF
Usage : $(basename "$0") [options] WAD [NIVEAU]
        $(basename "$0") --restore [-y]

Convertit le niveau NIVEAU (défaut : le premier) du fichier WAD et
l'installe dans NetHack pour le tester.

Options :
  -n, --parts N|auto  découper en une branche de N niveaux reliés par des
                      escaliers (modifie dungeon.lua et nhdat)
  -y, --yes           ne pas demander de confirmation
      --restore       retirer toutes les branches Doom de dungeon.lua et
                      réinstaller nhdat
  -h, --help          afficher cette aide
  Les autres options (--mode, --skill, --hazards...) sont passées
  à doom2nethack.py.

Variables d'environnement :
  NETHACK_SRC  sources NetHack   ($NETHACK_SRC)
  HACKDIR      répertoire de jeu ($HACKDIR)
  OUTDIR       fichiers générés  ($OUTDIR)
EOF
}

die() { echo "convertDoom2Nethack.sh : $*" >&2; exit 1; }

confirm() {
    [ "$YES" = 1 ] && return 0
    read -r -p "$1 [o/N] " answer
    [[ "$answer" =~ ^[oOyY] ]] || die "abandon"
}

check_install() {
    [ -d "$HACKDIR" ] || die "HACKDIR introuvable : $HACKDIR"
    [ -f "$HACKDIR/nhdat" ] || die "pas d'archive nhdat dans $HACKDIR"
    if ! grep -Eq "^WIZARDS=.*\b$(id -un)\b" "$HACKDIR/sysconf" 2>/dev/null
    then
        echo "attention : $(id -un) n'est pas dans WIZARDS de" \
             "$HACKDIR/sysconf ; le mode wizard (-D) sera refusé." >&2
    fi
}

# Reconstruit nhdat à partir de dat/ et le copie dans HACKDIR.
install_nhdat() {
    [ -f "$NETHACK_SRC/Makefile" ] ||
        die "sources NetHack non configurées : $NETHACK_SRC"
    echo "== Reconstruction de nhdat (make dlb)"
    make -C "$NETHACK_SRC" dlb > "$OUTDIR/make-dlb.log" 2>&1 ||
        die "make dlb a échoué, voir $OUTDIR/make-dlb.log"
    [ -f "$HACKDIR/nhdat.doom2nethack.orig" ] ||
        cp -p "$HACKDIR/nhdat" "$HACKDIR/nhdat.doom2nethack.orig"
    cp "$NETHACK_SRC/dat/nhdat" "$HACKDIR/nhdat"
}

backup_dungeon() {
    local f="$NETHACK_SRC/dat/dungeon.lua"
    [ -f "$f.doom2nethack.orig" ] || cp -p "$f" "$f.doom2nethack.orig"
}

YES=0
RESTORE=0
PARTS=1
ARGS=()
POS=()
while [ $# -gt 0 ]; do
    case "$1" in
    -n|--parts) PARTS=${2:?}; shift ;;
    --parts=*) PARTS=${1#*=} ;;
    -y|--yes) YES=1 ;;
    --restore) RESTORE=1 ;;
    -h|--help) usage; exit 0 ;;
    --skill|--hazards|--width|--height|--samples|--coverage|--mode|--rooms|\
    --dark-below)
        ARGS+=("$1" "${2:?}"); shift ;;
    -*) ARGS+=("$1") ;;
    *) POS+=("$1") ;;
    esac
    shift
done

mkdir -p "$OUTDIR"
check_install

if [ "$RESTORE" = 1 ]; then
    confirm "Retirer les branches Doom de $NETHACK_SRC/dat/dungeon.lua" \
            "et réinstaller nhdat dans $HACKDIR ?"
    python3 -m d2n.dungeon unpatch "$NETHACK_SRC/dat/dungeon.lua" 2>&1 ||
        die "échec de la modification de dungeon.lua"
    install_nhdat
    echo "Branches Doom retirées.  Les fichiers .lua copiés restent dans" \
         "$HACKDIR (sans effet)."
    exit 0
fi

[ ${#POS[@]} -ge 1 ] && [ ${#POS[@]} -le 2 ] || { usage >&2; exit 1; }
WAD=$(realpath "${POS[0]}")
[ -f "$WAD" ] || die "WAD introuvable : $WAD"
MAP=${POS[1]:-$(python3 "$SCRIPT_DIR/doom2nethack.py" --list "$WAD" | head -n 1)}
[ -n "$MAP" ] || die "aucun niveau dans $WAD"
MAP=${MAP^^}
LOWER=${MAP,,}

if [ "$PARTS" = 1 ]; then
    echo "== Conversion de $MAP"
    python3 "$SCRIPT_DIR/doom2nethack.py" -p -m "$MAP" "${ARGS[@]}" \
        -o "$OUTDIR/$LOWER.lua" "$WAD"
    cp "$OUTDIR/$LOWER.lua" "$HACKDIR/"
    cat <<EOF

== $LOWER.lua est installé dans $HACKDIR

Pour charger le niveau :
  1. Lancer NetHack en mode wizard :
       $NETHACK -D
  2. Descendre au niveau 3 (au niveau 1, NetHack refuse l'escalier
     montant) : Ctrl-V, puis 3 et Entrée.
  3. Charger le niveau : #wizloaddes, Entrée, puis $LOWER et Entrée.
  4. Afficher toute la carte : Ctrl-F.

Pour explorer : _ (déplacement automatique), ; (regarder un monstre),
Ctrl-W « potion of monster detection » (voir tous les monstres).
EOF
    exit 0
fi

echo "== Conversion de $MAP en branche ($PARTS niveaux demandés)"
rm -rf "${OUTDIR:?}/$LOWER"
python3 "$SCRIPT_DIR/doom2nethack.py" -p -m "$MAP" -n "$PARTS" "${ARGS[@]}" \
    -d "$OUTDIR/$LOWER" "$WAD"
mapfile -t LEVELS < <(cd "$OUTDIR/$LOWER" &&
                      ls "$LOWER"?.lua | sed 's/\.lua$//')
NAME="Doom $MAP"

echo
confirm "Déclarer la branche « $NAME » dans $NETHACK_SRC/dat/dungeon.lua" \
        "et remplacer $HACKDIR/nhdat (sauvegardes .doom2nethack.orig) ?"
backup_dungeon
python3 -m d2n.dungeon patch "$NETHACK_SRC/dat/dungeon.lua" "$NAME" \
    "${LEVELS[@]}" || die "échec de la modification de dungeon.lua"
install_nhdat
for l in "${LEVELS[@]}"; do
    cp "$OUTDIR/$LOWER/$l.lua" "$HACKDIR/"
done

cat <<EOF

== Branche « $NAME » installée : ${LEVELS[*]}

Pour charger les niveaux :
  1. Commencer une NOUVELLE partie en mode wizard (une partie sauvegardée
     garde l'ancien plan du donjon) :
       $NETHACK -D
  2. Aller dans la branche : Ctrl-V, puis ? et Entrée.  Le menu liste
     « $NAME » et ses niveaux ; choisir la lettre de ${LEVELS[0]}.
     (Sans téléportation : l'escalier de la branche est entre les
     niveaux 2 et 4 du donjon principal.)
  3. Afficher toute la carte : Ctrl-F.
  4. Passer au niveau suivant par l'escalier > ; on arrive sur le < du
     niveau suivant, de l'autre côté du passage Doom.

Pour retirer les branches Doom :  $(basename "$0") --restore
EOF
