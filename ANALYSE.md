# Analyse : conversion d'un niveau Doom en carte NetHack

## Objectif

Créer un outil qui convertit un niveau Doom (fichier WAD, tel que produit par
l'éditeur Yadex, `/home/sgond/app/YadexEditor`) en niveau spécial NetHack
(fichier `.lua` utilisable par la version de NetHack située dans
`/home/sgond/app/Nethack500_Lubuntu2604`).

Les hauteurs (sol / plafond) des secteurs Doom sont **ignorées** : seule la
disposition des salles entre elles (plan vu de dessus) est conservée.

## Conclusion : c'est faisable

Le problème se réduit à de la géométrie 2D : projeter le plan d'un niveau Doom
sur une grille de caractères NetHack.

## Source : le format WAD Doom

Un niveau est une séquence fixe de lumps (cf. Yadex `src/wstructs.h:216-257`
et `ANALYSE_wad.md`) :

```
LABEL (MAP01 / E1M1), THINGS, LINEDEFS, SIDEDEFS, VERTEXES, SEGS, SSECTORS,
NODES, SECTORS, REJECT, BLOCKMAP
```

Seuls 5 lumps sont utiles pour la conversion :

| Lump       | Taille enreg. | Contenu utile                                              |
|------------|---------------|------------------------------------------------------------|
| `VERTEXES` | 4 octets      | points `(x, y)` en int16                                   |
| `LINEDEFS` | 14 octets     | murs : `v1, v2, flags, type, tag, sidedef droit, gauche`   |
| `SIDEDEFS` | 30 octets     | textures + **numéro du secteur** de ce côté du mur         |
| `SECTORS`  | 26 octets     | hauteurs (ignorées), lumière, **type spécial**, tag        |
| `THINGS`   | 10 octets     | `x, y, angle, type, flags` : joueur, monstres, objets      |

`SEGS`, `SSECTORS`, `NODES`, `REJECT`, `BLOCKMAP` (structures de rendu BSP)
sont inutiles et peuvent même être absents (cas du `test.wad` de Yadex).

Le format est simple (en-tête 12 octets + répertoire de 16 octets par lump,
little-endian) : un lecteur autonome est préférable à la réutilisation du code
C++ de Yadex. On cible Doom / Doom II au format « vanilla » (pas Hexen, ni
UDMF).

## Cible : les niveaux spéciaux NetHack (Lua)

Cette version de NetHack (base 3.7) décrit ses niveaux spéciaux en Lua
(`dat/*.lua`, interprétés par `src/sp_lev.c`). Exemple de référence :
`dat/bigrm-1.lua`.

```lua
des.level_init({ style = "solidfill", fg = " " });
des.level_flags("mazelevel", "noflip");
des.map([[
-------
|.....|
|.....+
-------
]]);
des.stair("up", 1, 1)
des.monster("jackal", 3, 1)
```

Fonctions utiles : `des.map`, `des.door`, `des.stair`, `des.monster`,
`des.object`, `des.trap`, `des.region`, `des.terrain`.

Contraintes :

- Taille maximale de la carte : `COLNO = 80`, `ROWNO = 21`
  (`include/global.h:382`), soit environ **79 × 21** cases utilisables
  (la colonne 0 n'est pas utilisée).
- Test sans recompilation : commande `#wizloaddes` en mode wizard
  (`src/cmd.c:2085`) qui charge et exécute un fichier `.lua`.
- Intégration définitive : déclarer le niveau dans `dat/dungeon.lua`.

## Pipeline de conversion

1. **Lecture du WAD** : extraire le niveau voulu (`MAP01`, `E1M1`...).
2. **Rasterisation** :
   - calcul de la boîte englobante des vertex ;
   - mise à l'échelle vers la grille NetHack ;
   - pour chaque case, test « point dans polygone » (règle pair/impair sur
     les linedefs de chaque secteur) pour savoir dans quel secteur tombe son
     centre.
3. **Classification des cases** :
   - case dans un secteur → sol `.` ;
   - case vide adjacente à un sol → mur (`-` ou `|`) ;
   - linedef de type porte (1, 26-28, 31-34, 117, 118...) → porte `+` ;
   - secteur à dégâts (types 4, 5, 7, 16) → eau `}` ou lave `L` ;
   - secteur secret (type 9) → zone marquée (porte secrète `S` possible).
4. **Placement des entités** (`THINGS`) :
   - départ du joueur (type 1) → escalier montant ;
   - linedef de sortie (11, 51, 52, 124...) → escalier descendant ;
   - monstres et objets → table de correspondance Doom → NetHack
     (ex. imp → `imp`, medikit → potion de soin).
5. **Génération** du fichier `.lua`.

## Difficulté principale : l'échelle

- Un niveau Doom typique fait 3000 à 8000 unités de large, alors que la carte
  NetHack ne fait que 79 × 21 cases : compression d'environ 50 à 100 unités par
  case.
- Les couloirs de 64-128 unités deviennent épais d'une case, voire
  disparaissent.
- Le rapport largeur/hauteur imposé (~4:1) est très éloigné de celui d'un
  niveau Doom ; de plus une case de terminal est environ deux fois plus haute
  que large.
- Les petits secteurs (marches, piliers, zones de lumière) fragmentent la
  grille.

### Stratégies possibles

1. **Rasterisation brute** (prototype) : échelle non uniforme X/Y, puis
   post-traitement pour garantir la connectivité. Rapide, mais approximatif.
2. **Approche topologique** (recommandée pour une version aboutie) :
   - fusion des secteurs adjacents en « salles » logiques ;
   - graphe d'adjacence (portes / ouvertures entre salles) ;
   - placement de salles rectangulaires NetHack en conservant les positions
     relatives (centres projetés) ;
   - liaison des salles par des couloirs `#`.
   Résultat plus « NetHack », reconnaissable, connectivité garantie.
3. **Découpage** d'un niveau Doom trop grand en plusieurs niveaux NetHack
   reliés par des escaliers.

## Points d'attention

- Secteurs imbriqués, secteurs non fermés et linedefs mal formés sont
  fréquents dans les WAD amateurs : le test point-dans-polygone doit être
  robuste.
- Les téléporteurs Doom n'ont pas d'équivalent direct : pièges de téléportation
  (`des.trap("teleport")`) ou ignorés.
- Hexen, Boom et UDMF sont hors périmètre dans un premier temps.

## Plan de travail

1. **Prototype** (Python) : lecteur WAD, rasterisation brute, portes,
   escaliers, monstres de base, sortie `.lua` testable par `#wizloaddes`.
2. Robustesse et connectivité garantie.
3. Approche topologique et table complète des monstres et objets.
