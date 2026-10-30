# Idées d'amélioration

Pistes classées par priorité. Les chiffres viennent des essais sur les
68 niveaux de Freedoom 0.13.0 et des tests dans NetHack.

## Priorité haute

### Téléporteurs Doom → pièges de téléportation
Les linedefs de téléportation (39 et 97 ; 125 et 126 pour les monstres
seulement) sont ignorés. Pourtant,
`des.trap` accepte une destination fixe (`teledest = {x, y}`,
`lspo_trap()` dans `src/sp_lev.c`). La destination Doom est un thing 14
placé dans le secteur visé par le tag du linedef : on peut la projeter sur
la grille. Les téléporteurs restituent une partie des parcours Doom, et la
passe de connectivité creuserait moins de faux couloirs.

### Portes mal encadrées
Environ 180 des 722 portes de Freedoom sont signalées « mal entourées de
murs ». Pistes :
- placer la porte au point le plus étroit du passage plutôt qu'au centre
  du secteur porte ;
- refuser une porte dont la case n'a pas de mur des deux côtés après coup,
  et la déplacer d'une case ;
- murer les cases voisines quand le couloir creusé par la connectivité
  contourne une porte, qui ne sert alors plus à rien.

### Découpage aux portes et aux couloirs
La bissection géométrique coupe parfois une salle en deux. Un découpage
sur le graphe des secteurs (coupe minimale, pondérée par la largeur des
passages) couperait de préférence aux portes et aux couloirs étroits. Les
morceaux seraient des groupes de salles cohérents, avec un escalier au
niveau d'une vraie porte.

### Difficulté selon la profondeur réelle
La table des monstres est fixe. Une branche de 12 niveaux (MAP20) va de la
profondeur 3 à la profondeur 15 : les derniers morceaux sont trop faciles.
On pourrait définir plusieurs paliers par monstre Doom (par exemple zombie
humain → zombie ettin → zombie géant) et choisir selon la profondeur de
chaque morceau, connue d'après `dungeon.lua`.

## Priorité moyenne

### Rambardes et fenêtres → barreaux de fer
Les linedefs à deux faces marqués infranchissables (`ML_BLOCKING`) sont
aujourd'hui traités comme du sol. Dans E1M8, ils entourent la zone de
départ. NetHack a des barreaux de fer (`F` dans `des.map`), qui laissent
voir sans laisser passer : c'est l'équivalent exact.

### Secteurs secrets
Le type spécial 9 (secret) est lu mais pas utilisé. Les portes vers ces
secteurs pourraient devenir des portes secrètes (`S`), et les couloirs qui
y mènent des couloirs secrets.

### Éclairage
Tout le niveau est éclairé. Le niveau de lumière des secteurs Doom
(`Sector.light`) permettrait de laisser dans le noir les zones sombres
(lumière < 128), avec `des.region(..., "unlit")` sur les cases concernées.

### Things ignorés
Beaucoup de things sont ignorés (bonus, munitions, décors). Idées :
- bonus de santé (2014) → nourriture ; bonus d'armure (2015) → anneau ou
  bouclier selon la quantité ;
- munitions (2007, 2008, 2010, 2046-2049) → carreaux, dagues ou fléchettes ;
- barils explosifs (2035) → rochers, ou pièges de feu ;
- arbres et colonnes (43, 47, 48, 54…) → arbres `T` ou colonnes de mur ;
- lampes et torches → zones éclairées ;
- cartes et crânes de couleur → clés, en verrouillant les portes de la même
  couleur et en plaçant la clé avant la porte sur le parcours.

### Sols à dégâts
Avec `--hazards`, la nukage devient de l'eau ou de la lave, ce qui peut
bloquer le passage. Des pièges (feu, gaz soporifique) sur une partie des
cases garderaient l'idée « zone dangereuse » sans rendre la case
infranchissable.

### Densité de monstres
Un niveau Doom contient beaucoup plus de monstres qu'un niveau NetHack
(29 dans E1M1 en difficulté moyenne). On pourrait plafonner leur nombre par
niveau, ou les convertir en groupes moins nombreux mais plus forts.

### Sortie Doom hors du dernier morceau
Dans 27 morceaux sur 365, la sortie Doom n'est pas dans le dernier
morceau (le parcours fait une boucle). On pourrait marquer l'emplacement
de la sortie (autel, trône, portail) ou proposer une option qui impose la
sortie en fin de chaîne, quitte à enchaîner des morceaux non voisins.

## Priorité basse

### Épisode complet
Convertir un épisode entier (E1M1 à E1M9, ou MAP01 à MAP11) en un seul
donjon : la sortie de chaque carte mène au début de la suivante. Limites :
32 niveaux par donjon (`MAXLEVEL`) et 16 donjons au plus (`MAXDUNGEON`),
dont 9 déjà utilisés par NetHack.

### Mode salles et couloirs (`--mode rooms`)
Réalisé dans `d2n/rooms.py`. Pistes pour aller plus loin :
- garder la forme des salles : rasteriser chaque salle dans son rectangle
  (hall en L, pilier), en ne gardant de l'approche topologique que le
  rapprochement des salles et les couloirs ;
- suivre le tracé des couloirs Doom (coudes, embranchements) plutôt qu'un
  plus court chemin ;
- répartir les portes sur les murs et éviter deux portes voisines ;
- rendre les seuils de regroupement (`CORRIDOR_WIDTH`, `SMALL_AREA`,
  `EMBEDDED`) réglables, et les ajuster sur davantage de WAD ;
- retirer aussi en mode `raster` les secteurs inaccessibles depuis le
  départ (`doom_reachable()`).

### Passages perdus entre morceaux
Seuls les passages de la chaîne sont conservés. Les trous et trappes
(`des.trap("hole")`) mènent au niveau suivant et pourraient représenter un
deuxième passage vers l'avant, au moins dans un sens.

### Formats
Gérer les formats Boom (types de linedefs génériques), Hexen et UDMF
(`TEXTMAP`), utilisés par beaucoup de WAD récents.

### Intégration à Yadex
Ajouter à Yadex une commande « exporter vers NetHack » qui appelle
`doom2nethack.py` sur le niveau en cours, avec l'aperçu de la carte.

### Aperçu graphique
Un aperçu HTML superposant le plan Doom (linedefs) et la grille NetHack
aiderait à régler `--coverage`, `--samples` et le découpage.

### Tests en jeu automatiques
Le pilotage tmux utilisé pendant le développement pourrait devenir un test
automatique : charger chaque niveau généré avec `#wizloaddes` dans une
copie isolée de NetHack et vérifier l'absence d'erreur Lua. Une autre
option : un script `#wizloadlua`, sur le modèle de `test/*.lua`.

### Taille de carte
La carte est limitée à 75 × 19 par prudence (comme `bigrm`). On pourrait
vérifier dans `lspo_map()` si 77 × 21 passe, ce qui donnerait un peu plus
de détail.
