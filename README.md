# Doom2Nethack

Convertit un niveau Doom / Doom II (fichier WAD, par exemple produit par
Yadex) en niveau spécial NetHack au format Lua. Les hauteurs sont ignorées :
seule la disposition des salles est conservée. Voir `ANALYSE.md`.

Le prototype est en Python 3, sans dépendance externe.

## Charger un niveau Doom dans NetHack

### Prérequis

- NetHack compilé et installé (par défaut dans `~/nh/install/games`), avec
  ses sources configurées (`NETHACK_SRC`, par défaut
  `/home/sgond/app/Nethack500_Lubuntu2604`).
- Le mode wizard autorisé : ajouter son nom d'utilisateur à la ligne
  `WIZARDS=` de `~/nh/install/games/lib/nethackdir/sysconf`.
- Un fichier WAD Doom ou Doom II, par exemple Freedoom.
  `python3 doom2nethack.py --list fichier.wad` liste ses niveaux.

### Un niveau Doom → un niveau NetHack

1. Convertir et installer le niveau :

   ```sh
   ./convertDoom2Nethack.sh ../freedoom-0.13.0/freedoom1.wad E1M1
   ```

   Le script affiche la carte obtenue et copie `out/e1m1.lua` dans le
   répertoire de jeu.
2. Lancer NetHack en mode wizard : `~/nh/install/games/nethack -D`.
3. Descendre au niveau 3 : `Ctrl-V`, `3`, `Entrée`. Au niveau 1, NetHack
   refuse de créer l'escalier montant.
4. Charger le niveau : `#wizloaddes`, `Entrée`, `e1m1`, `Entrée`.
5. Afficher toute la carte : `Ctrl-F`.

### Un grand niveau Doom → une branche de plusieurs niveaux

1. Convertir et installer la branche (`-n auto` choisit le nombre de
   niveaux, `-n 3` l'impose) :

   ```sh
   ./convertDoom2Nethack.sh -n auto ../freedoom-0.13.0/freedoom1.wad E1M1
   ```

   Après confirmation, le script déclare la branche « Doom E1M1 » dans
   `dat/dungeon.lua`, reconstruit l'archive `nhdat` et copie les niveaux
   (`e1m1a.lua`, `e1m1b.lua`…) dans le répertoire de jeu.
2. Commencer une **nouvelle** partie en mode wizard :
   `~/nh/install/games/nethack -D`. Une partie sauvegardée garde l'ancien
   plan du donjon.
3. Aller dans la branche : `Ctrl-V`, `?`, `Entrée`. Le menu liste
   « Doom E1M1 » et ses niveaux ; choisir la lettre de `e1m1a`. Sans
   téléportation, l'escalier de la branche se trouve entre les niveaux 2
   et 4 du donjon principal.
4. Passer d'un niveau au suivant par l'escalier `>` : on arrive sur le `<`
   du niveau suivant, de l'autre côté du passage Doom.
5. Pour retirer les branches Doom : `./convertDoom2Nethack.sh --restore`.

### Commandes utiles dans le jeu

| Touche      | Effet                                                    |
|-------------|----------------------------------------------------------|
| `Ctrl-F`    | révéler toute la carte (mode wizard)                     |
| `Ctrl-V`    | se téléporter à un niveau (`?` : menu des niveaux)       |
| `_`         | aller automatiquement à un endroit (par exemple `>`)     |
| `;`         | regarder un monstre ou un objet                          |
| `Ctrl-W`    | souhait : « potion of monster detection » montre les monstres |
| `#quit`     | abandonner la partie (fermer le terminal la sauvegarde)  |

## Utilisation de doom2nethack.py

```sh
python3 doom2nethack.py --list doom2.wad           # niveaux du WAD
python3 doom2nethack.py -p -m MAP01 doom2.wad      # écrit out/map01.lua
python3 doom2nethack.py -p --keep-aspect -o lvl.lua doom2.wad
python3 doom2nethack.py -p -n auto -m E1M1 freedoom1.wad  # out/e1m1/
python3 doom2nethack.py -p --mode rooms -m E1M1 freedoom1.wad  # salles
```

Options :

| Option                  | Rôle                                                  |
|-------------------------|-------------------------------------------------------|
| `-m`, `--map`           | niveau à convertir (défaut : le premier)              |
| `-o`, `--output`        | fichier de sortie (défaut `out/<niveau>.lua` ; `-` : sortie standard) |
| `-n`, `--parts`         | découpe en N niveaux reliés par des escaliers (`auto`) |
| `-d`, `--outdir`        | répertoire d'un niveau découpé (défaut `out/<niveau>`) |
| `-p`, `--preview`       | affiche la carte obtenue (avec `<` et `>`)            |
| `--width`, `--height`   | taille de la carte (max 75 × 19)                      |
| `--keep-aspect`         | échelle uniforme au lieu d'étirer la carte            |
| `--samples`             | échantillons par case et par axe (défaut 3)           |
| `--coverage`            | part d'une case à couvrir pour faire un sol (0.34)    |
| `--mode`                | `raster` (plan décalqué, défaut) ou `rooms` (salles et couloirs) |
| `--rooms`               | mode `rooms` : nombre de salles visé (défaut 12)      |
| `--hazards`             | sols à dégâts : `none` (défaut), `water` ou `lava`    |
| `--dark-below`          | lumière Doom (0-255) en dessous de laquelle une zone est sombre (144 ; 0 : tout éclairé) |
| `--skill`               | difficulté des things : `easy`, `medium` (défaut), `hard` |

## Fonctionnement de convertDoom2Nethack.sh

- Un seul niveau : le `.lua` est copié dans le répertoire de jeu (HACKDIR,
  par défaut `~/nh/install/games/lib/nethackdir`). Un fichier absent de
  l'archive `nhdat` y est cherché (`dlb_fopen()`, `src/dlb.c`), d'où
  `#wizloaddes` le charge.
- Branche (`-n`) : la branche est déclarée dans `dat/dungeon.lua` des
  sources NetHack (blocs entre marqueurs `doom2nethack:begin/end`, remplacés
  à chaque exécution), l'archive `nhdat` est reconstruite par `make dlb` et
  copiée dans HACKDIR, avec les `.lua`. Les originaux sont gardés en
  `*.doom2nethack.orig`. `make install` n'est pas utilisé : il efface
  HACKDIR (parties sauvegardées, `record`, `sysconf`).
- `NETHACK_SRC`, `HACKDIR` et `OUTDIR` permettent de changer les chemins ;
  les options `--skill`, `--hazards`… sont passées à `doom2nethack.py`.

## Deux modes de conversion

- `raster` (défaut) : une grille de 75 × 19 cases est posée sur le plan
  Doom ; chaque case est du sol si elle tombe dans un secteur. Fidèle à la
  forme des pièces, mais les détails sont écrasés par la compression.
- `rooms` : on garde quelles salles existent et lesquelles communiquent,
  puis on redessine un niveau à la manière de NetHack (`d2n/rooms.py`) :
  1. les secteurs sont regroupés en salles : un secteur presque entouré par
     un autre (flaque, estrade) ou très petit (marche, bande de lumière) est
     fusionné avec son voisin, puis les salles les plus liées sont
     fusionnées jusqu'au nombre visé (`--rooms`, 12 par défaut) ;
  2. les groupes longs et étroits deviennent des couloirs, les secteurs
     porte des portes : ce sont des passages, pas des salles ;
  3. chaque salle devient un rectangle placé à la position projetée de son
     centre Doom, de taille proportionnelle à son emprise, puis les
     rectangles sont écartés jusqu'à laisser un passage entre eux (moins de
     salles si elles ne tiennent pas) ;
  4. les salles reliées dans Doom, directement ou par des couloirs et des
     portes, sont reliées par des couloirs `#`, avec une porte à chaque
     bout (`+` pour une porte Doom, ouverture sans porte sinon) ;
  5. les secteurs inaccessibles depuis le départ (décors vus par une
     fenêtre, placards à monstres) sont retirés ; les téléporteurs comptent
     pour l'accessibilité. Une salle accessible mais non reliée est
     raccordée à la plus proche.

  Le niveau est plus lisible et plus « NetHack », mais la forme des pièces
  est perdue (un hall en L devient un rectangle). Les things gardent leur
  position relative dans leur salle.

Les deux modes fonctionnent avec le découpage en plusieurs niveaux.

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
qui explique comment déclarer la branche dans `dat/dungeon.lua` (ce que fait
`convertDoom2Nethack.sh`, via `python3 -m d2n.dungeon patch|unpatch`). Les
passages entre morceaux autres que la chaîne sont perdus, et la sortie Doom
peut ne pas tomber dans le dernier morceau (avertissement).

En mode wizard, `Ctrl-V` (téléportation de niveau) permet ensuite d'aller
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
- Éclairage : le niveau est éclairé, sauf les cases des secteurs dont la
  lumière Doom est inférieure à `--dark-below` (144 par défaut : les zones
  tamisées à 128 et moins). En mode `rooms`, une salle prend la lumière
  moyenne de ses secteurs, et un couloir celle des salles qu'il relie. Les
  murs qui ne bordent que des cases sombres sont sombres aussi. Les cases
  sombres sont passées à `des.region(selection, "unlit")`.
- Toute zone restée isolée (téléporteurs, sols mobiles, rambardes) est
  reliée à la zone principale : tout le niveau est accessible.

## Tests

```sh
python3 -m unittest discover tests
python3 tests/make_test_wad.py test3rooms.wad    # WAD de test à 3 salles
```
