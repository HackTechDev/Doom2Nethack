# Doom2Nethack

Convertit un niveau Doom / Doom II (fichier WAD, par exemple produit par
Yadex) en niveau spécial NetHack au format Lua. Les hauteurs sont ignorées :
seule la disposition des salles est conservée. Voir `ANALYSE.md`.

Le prototype est en Python 3, sans dépendance externe.

## Utilisation

```sh
python3 doom2nethack.py --list doom2.wad           # niveaux du WAD
python3 doom2nethack.py -p -m MAP01 doom2.wad      # écrit map01.lua
python3 doom2nethack.py -p --keep-aspect -o lvl.lua doom2.wad
python3 doom2nethack.py -p -n auto -m E1M1 -d out freedoom1.wad  # découpage
```

Options :

| Option                  | Rôle                                                  |
|-------------------------|-------------------------------------------------------|
| `-m`, `--map`           | niveau à convertir (défaut : le premier)              |
| `-o`, `--output`        | fichier de sortie (`-` : sortie standard)             |
| `-n`, `--parts`         | découpe en N niveaux reliés par des escaliers (`auto`) |
| `-d`, `--outdir`        | répertoire de sortie d'un niveau découpé (défaut `.`) |
| `-p`, `--preview`       | affiche la carte obtenue (avec `<` et `>`)            |
| `--width`, `--height`   | taille de la carte (max 75 × 19)                      |
| `--keep-aspect`         | échelle uniforme au lieu d'étirer la carte            |
| `--samples`             | échantillons par case et par axe (défaut 3)           |
| `--coverage`            | part d'une case à couvrir pour faire un sol (0.34)    |
| `--hazards`             | sols à dégâts : `none` (défaut), `water` ou `lava`    |
| `--skill`               | difficulté des things : `easy`, `medium` (défaut), `hard` |

## Tester dans NetHack

1. Copier le `.lua` produit dans le répertoire de jeu (HACKDIR, par défaut
   `~/nh/install/games/lib/nethackdir`). Pas besoin de recompiler sans DLB :
   un fichier absent de l'archive `nhdat` est cherché dans ce répertoire
   (`dlb_fopen()`, `src/dlb.c`).
2. Lancer `nethack -D` (mode wizard ; l'utilisateur doit figurer dans
   `WIZARDS` du fichier `sysconf`).
3. Utiliser `#wizloaddes`, puis donner le nom du fichier (ex. `map01.lua`).

## Découpage en plusieurs niveaux

Un grand niveau Doom comprimé sur 75 × 19 cases perd ses détails. Avec
`--parts N` (ou `auto`, qui vise des cases d'environ 48 × 96 unités Doom,
12 niveaux au plus), il est découpé en une branche de N niveaux NetHack :

- les secteurs sont répartis par bissections successives le long de l'axe
  le plus comprimé ;
- les morceaux forment une chaîne (un niveau NetHack n'a qu'un escalier
  montant et un descendant) qui commence au départ du joueur et enchaîne de
  préférence des morceaux voisins dans Doom ;
- entre deux morceaux voisins, l'escalier descendant de l'un et l'escalier
  montant du suivant sont placés de part et d'autre du plus large passage
  qui les relie dans Doom ;
- le premier niveau reçoit l'escalier de branche (retour vers le donjon
  principal) au départ du joueur ; l'escalier descendant du dernier niveau
  est ignoré par NetHack (fond de la branche).

Sont produits `<niveau>a.lua`, `<niveau>b.lua`… et `<niveau>-dungeon.lua`,
qui explique comment déclarer la branche dans `dat/dungeon.lua`. Les
passages entre morceaux autres que la chaîne sont perdus, et la sortie Doom
peut ne pas tomber dans le dernier morceau (avertissement).

En mode wizard, `^V` (téléportation de niveau) permet ensuite d'aller
directement dans la branche.

## Ce que fait le prototype

- Rasterisation : chaque case est échantillonnée (3 × 3 par défaut) et
  rattachée au secteur Doom majoritaire (test point-dans-polygone).
- Connectivité : deux secteurs reliés dans Doom par une ligne franchissable,
  directement ou à travers des secteurs trop petits pour apparaître
  (marches, ascenseurs), le sont aussi sur la carte ; un couloir est creusé
  si besoin.
- Portes : une porte (`+`) par secteur porte (linedefs 1, 26-28, 31-34,
  117, 118). Les portes à clé sont verrouillées.
- Escaliers : l'escalier montant est au départ du joueur, l'escalier
  descendant à la sortie (linedefs 11, 51, 52, 124…).
- Monstres et objets : table de correspondance dans `d2n/tables.py`.
- Toute zone restée isolée (téléporteurs, sols mobiles, rambardes) est
  reliée à la zone principale : tout le niveau est accessible.

## Tests

```sh
python3 -m unittest discover tests
python3 tests/make_test_wad.py test3rooms.wad    # WAD de test à 3 salles
```
