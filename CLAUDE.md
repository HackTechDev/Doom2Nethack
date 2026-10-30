# CLAUDE.md

Doom2Nethack convertit un niveau Doom / Doom II (WAD vanilla) en niveau
spécial NetHack (Lua). Les hauteurs sont ignorées : seule la disposition
des salles compte. Python 3, bibliothèque standard uniquement.

## Langue et conventions

- Répondre en français. Code, commentaires, docstrings, messages, docs et
  messages de commit sont en français ; garder ce style (commentaires
  brefs, docstrings d'une ou deux phrases, typographie française :
  espace avant `:` `;` `?` `!`).
- Ne commiter que sur demande explicite. Si une demande dit « puis fait un
  commit », commiter seulement quand les tests passent : utiliser
  `set -o pipefail` quand la sortie des tests est filtrée (`| tail`),
  sinon un échec passe inaperçu.
- Toute nouvelle fonction ou touche du menu se documente dans `README.md`,
  et dans `TUTORIAL.md` si elle concerne le parcours décrit. Une piste
  réalisée de `IMPROVEMENTS.md` passe dans le paragraphe « Réalisé » de sa
  section.

## Commandes

```sh
python3 -m unittest discover -s tests          # tests (~30 s)
python3 doom2nethack.py -p -m E1M1 freedoom-0.13.0/freedoom1.wad
./Doom2Nethack.sh [WAD]                        # menu interactif (curses)
./convertDoom2Nethack.sh [-n N|auto] WAD MAP   # convertir et installer
python3 -m d2n.play [--branch] NIVEAU          # jouer un niveau installé
```

Les WAD sont dans le répertoire des WAD (`WAD_DIR`, défaut
`../Doom/Wad` : `/home/util01/JEUX/NETHACK/Doom/Wad`) ; un WAD introuvable
depuis le répertoire courant y est cherché (`find_wad()`, `d2n/wad.py`).
Les tests Freedoom (`TestFreedoom`) supposent Freedoom dans
`$WAD_DIR/freedoom-0.13.0` ; ils sont sautés sinon. `TestYadex` lit le
`test.wad` de Yadex dans `YADEX_DIR` (défaut `../YadexEditor` :
`/home/util01/JEUX/NETHACK/YadexEditor`). `tests/make_test_wad.py`
construit le petit WAD de test (3 salles, la dernière sombre).

## Architecture (`d2n/`)

- `wad.py` : lecture des WAD (lumps VERTEXES, LINEDEFS, SIDEDEFS, SECTORS,
  THINGS), répertoire des WAD (`WAD_DIR`, `find_wad()`) et de Yadex
  (`YADEX_DIR`).
- `tables.py` : correspondances Doom → NetHack (portes, sorties,
  téléporteurs, monstres, objets, symboles, noms Doom).
- `convert.py` : `Options` (dataclass passée **par position** par
  `doom2nethack.py` : ajouter un champ à la fin), `Result`, conversion
  `raster` (rasterisation des secteurs, connectivité, portes, escaliers,
  zones sombres).
- `rooms.py` : mode `rooms` (secteurs regroupés en salles rectangulaires
  reliées par des couloirs).
- `split.py` : découpage d'un niveau en plusieurs niveaux reliés par des
  escaliers (branche).
- `lua_out.py` : écriture du `.lua` (`des.map`, régions, escaliers,
  monstres, objets).
- `dungeon.py` : déclaration des branches dans `dat/dungeon.lua`, entre
  marqueurs `-- doom2nethack:begin/end <nom>`.
- `tui.py` : menu interactif ; `play.py` : lance `nethack -D` dans un
  pseudo-terminal et tape les touches qui mènent au niveau.

Sorties dans `out/<WAD sans .wad>/` (ignoré par git) : `<carte>.lua`, ou
`<carte>/` pour une branche, plus `doom2nethack.json` (WAD et options de
chaque conversion). Le menu garde aussi `out/.options.json` et
`out/.recent-wads.json`.

## NetHack : précautions

- Installation de l'utilisateur : `~/nh/install/games` (HACKDIR
  `~/nh/install/games/lib/nethackdir`), sources dans `NETHACK_SRC`
  (défaut `../NetHack-5.0.0` : `/home/util01/JEUX/NETHACK/NetHack-5.0.0`).
  Les tests qui lisent les sources (`TestTui`, `TestTables`,
  `TestDungeonPatch`) sont sautés sans elles. Version 5.0 dérivée de 3.7,
  traduite en français : les invites et la ligne d'état sont en français
  (`Niv:`, `--Plus--`), à reconnaître en plus de l'anglais.
- Ne jamais lancer `make install` : il efface HACKDIR (sauvegardes,
  record, sysconf). Ne pas modifier `dat/dungeon.lua`, `nhdat` ni HACKDIR
  sans accord de l'utilisateur.
- Pour les essais en jeu, utiliser une copie isolée de NetHack (sources
  copiées, `make PREFIX=<copie> all install`, `WIZARDS` renseigné) et la
  piloter dans tmux ; supprimer ensuite ses parties sauvegardées
  (`save/`). Fermer une session tmux sauvegarde la partie en cours.
- En mode wizard le personnage s'appelle toujours `wizard`. NetHack refuse
  l'escalier montant au niveau 1 : charger les niveaux à partir du
  niveau 2 (`Ctrl-V 3`, `#wizloaddes`).

## Captures du README

`docs/*.svg` sont produites depuis des captures tmux par
`docs/ansi2svg.py` (mode d'emploi dans son en-tête).
