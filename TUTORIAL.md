# Tutoriel : un niveau Doom dans NetHack

Ce tutoriel convertit E1M1 de Freedoom en niveau NetHack, l'affiche, puis
le joue. Il montre ensuite comment comparer deux méthodes de conversion,
découper un grand niveau en plusieurs niveaux reliés par des escaliers,
et convertir tout un épisode. Comptez une vingtaine de minutes.

Le `README.md` reste la référence complète des options et des touches.

## 0. Avant de commencer

Il vous faut :

- **Python 3** et son module `curses` (présent sur toute distribution
  Linux) ;
- **NetHack installé**, par défaut dans `~/nh/install/games` ;
- **le mode wizard autorisé** pour votre compte : votre nom d'utilisateur
  sur la ligne `WIZARDS=` de
  `~/nh/install/games/lib/nethackdir/sysconf` ;
- **un fichier WAD** : ce tutoriel utilise Freedoom 0.13.0, rangé dans
  le répertoire des WAD, `/home/util01/JEUX/NETHACK/Doom/Wad` (par
  défaut `../Doom/Wad`, à côté du projet) : `freedoom-0.13.0/freedoom1.wad`
  (épisodes E1 à E4) et `freedoom-0.13.0/freedoom2.wad` (cartes MAP01 à
  MAP32). Un WAD introuvable depuis le répertoire courant est cherché
  dans ce répertoire : il suffit d'écrire `freedoom-0.13.0/freedoom1.wad`.

Pour les branches (étape 6), il faut aussi les sources de NetHack
configurées, par défaut dans `../NetHack-5.0.0`, à côté du projet (ici
`/home/util01/JEUX/NETHACK/NetHack-5.0.0`).

Si NetHack ou les WAD sont ailleurs, indiquez-le avant de lancer le
menu :

```sh
export HACKDIR=/chemin/vers/nethackdir     # répertoire de jeu
export NETHACK=/chemin/vers/nethack        # exécutable
export NETHACK_SRC=/chemin/vers/sources    # pour les branches
export WAD_DIR=/chemin/vers/wad            # répertoire des WAD
```

## 1. Lancer le menu

Depuis le répertoire du projet :

```sh
./Doom2Nethack.sh freedoom-0.13.0/freedoom1.wad
```

Le menu principal s'ouvre. En haut s'affiche le fichier WAD utilisé ; en
bas, les touches disponibles dans l'écran courant. Dans tous les menus :

| Touche              | Effet                              |
|---------------------|------------------------------------|
| `↑` `↓`             | choisir une ligne                  |
| `Page↑` `Page↓`     | défiler d'une page                 |
| `Entrée`            | valider                            |
| `q` ou `Échap`      | revenir à l'écran précédent        |
| `l`                 | journal des conversions            |

La prochaine fois, `./Doom2Nethack.sh` sans argument reprendra ce
WAD. Pour en changer, choisissez **Choisir un autre WAD** : la liste
commence par les WAD récents, suivis du contenu du répertoire. `w` va au
répertoire des WAD, `/` permet de taper un chemin (`Tab` complète).

## 2. Convertir E1M1

1. Choisissez **Convertir des cartes**. L'écran liste les 36 cartes de
   `freedoom1.wad`. Au-dessus, la destination (`out/freedoom1/`) et les
   options de conversion.
2. La ligne E1M1 est sélectionnée : appuyez sur `Entrée`.

La conversion se fait en arrière-plan. La barre du haut montre sa
progression, puis `✔ 1 conversion(s) terminée(s)`. La ligne E1M1 indique
alors `✔ converti`. Le fichier écrit est `out/freedoom1/e1m1.lua`.

Pour lire ce qu'a dit la conversion, appuyez sur `l` (journal), puis
`Entrée` sur E1M1 : taille de la carte, échelle (unités Doom par case),
nombre de portes, de monstres et d'objets, part du sol dans le noir, et
les avertissements éventuels (une porte mal entourée de murs, un passage
creusé pour relier deux zones...). `q` pour revenir.

## 3. Regarder la carte

1. Revenez au menu principal (`q`) et choisissez **Niveaux convertis**.
   Les niveaux sont classés par WAD : la section `freedoom1` contient
   `e1m1     niveau simple`.
2. `Entrée` affiche la carte en couleurs :
   - murs `-` `|`, portes `+` en jaune, couloirs `#` ;
   - `<` escalier montant (le départ du joueur Doom), `>` escalier
     descendant (la sortie du niveau Doom) ;
   - monstres en rouge (soulignés s'ils sont invisibles), objets en cyan ;
   - zones sombres grisées : ce sont les secteurs peu éclairés du niveau
     Doom.
3. Un curseur part de l'escalier montant. Déplacez-le avec les flèches
   (`Maj` + flèche : 8 cases), ou sautez de monstre en objet avec `Tab`
   (`Maj-Tab` : en arrière). La ligne au-dessus de la carte décrit la
   case, par exemple :

   ```
   (25,08) monstre : imp ← Doom : imp — sur : sol
   (22,04) objet : potion of healing ← Doom : stimpack — sur : sol
   ```

   Vous voyez ainsi ce qu'est devenu chaque monstre et chaque objet Doom.

## 4. Jouer le niveau

Toujours sur l'aperçu (ou sur la ligne `e1m1` de la liste), appuyez sur
`p`.

1. Le menu propose de copier `e1m1.lua` dans le répertoire de jeu de
   NetHack : répondez `o`.
2. NetHack démarre en mode wizard. Répondez vous-même à ses questions :
   choix du personnage, tutoriel...
3. Dès que la carte s'affiche, le menu tape les touches à votre place :
   téléportation au niveau 3 (`Ctrl-V` `3`), chargement du niveau
   (`#wizloaddes` `e1m1`), puis carte révélée (`Ctrl-F`). Ne touchez à
   rien pendant ces quelques secondes.
4. Vous êtes sur l'escalier `<`, au départ du niveau Doom. Jouez : la
   sortie du niveau Doom est l'escalier `>`.

Pour revenir au menu, terminez la partie, ou sauvegardez-la avec `S`.
Dans la liste, `e1m1` indique maintenant `✔ installé`.

> En mode wizard, le personnage s'appelle toujours `wizard`. Si une partie
> `wizard` est sauvegardée, NetHack la reprend : le niveau est alors
> chargé dans cette partie.

## 5. Essayer l'autre méthode et comparer

Le menu sait convertir de deux façons :

- **raster** (par défaut) : le plan Doom est décalqué case par case. Les
  formes des salles sont fidèles, mais la carte est étirée pour remplir
  l'écran NetHack ;
- **rooms** : les secteurs Doom sont regroupés en salles rectangulaires,
  placées comme dans le niveau Doom et reliées par des couloirs `#`. Le
  résultat ressemble davantage à un niveau NetHack.

Pour les comparer sur E1M1 :

1. Ouvrez **Convertir des cartes** et sélectionnez E1M1.
2. Appuyez sur `m` : la ligne des options indique `mode rooms`.
3. Appuyez sur `c`. La carte est convertie avec les options actuelles,
   sans être enregistrée, et affichée à côté de la conversion
   enregistrée : A (raster) et B (rooms). Si le terminal fait moins de
   160 colonnes, les deux cartes s'affichent l'une après l'autre :
   `Espace` passe de l'une à l'autre.
4. Le curseur est commun aux deux cartes : placez-le sur un monstre de A
   pour voir ce qu'il y a au même endroit dans B.
5. `g` garde B à la place de A ; `q` garde A.

Les autres options s'ouvrent avec `o` : difficulté (monstres présents en
easy, medium ou hard), sols à dégâts (nukage changée en eau ou en lave),
seuil de lumière des zones sombres, taille de la carte, etc. Les plus
courantes ont un raccourci : `m` mode, `n` découpage, `s` difficulté,
`h` sols. Le menu garde vos options pour la prochaine fois : pensez à
revenir aux valeurs par défaut (`o`, puis **Valeurs par défaut**) si vous
ne voulez plus convertir en mode rooms.

## 6. Un grand niveau en plusieurs niveaux NetHack

Un niveau Doom fait souvent 4 000 unités de large ou plus, alors que la
carte NetHack ne fait que 75 × 19 cases : les couloirs étroits
disparaissent et les salles sont écrasées. La solution est de découper
le niveau en plusieurs niveaux NetHack, reliés par des escaliers aux
endroits où le joueur Doom passe d'une partie à l'autre. Ces niveaux
forment une **branche** du donjon.

1. Dans **Convertir des cartes**, sélectionnez E1M2 et appuyez sur `n`
   jusqu'à lire `découpage auto` (le nombre de niveaux est alors choisi
   d'après la taille du niveau Doom).
2. `Entrée` : la ligne E1M2 indique `✔ branche`. Les niveaux sont dans
   `out/freedoom1/e1m2/` (`e1m2a.lua`, `e1m2b.lua`...).
3. Dans **Niveaux convertis**, `Entrée` sur `e1m2 branche de N niveaux`
   affiche le premier niveau ; `Page↓` passe au suivant. L'escalier `>`
   d'un niveau mène au `<` du suivant, de l'autre côté du passage Doom.
4. `i` installe la branche. Le script `convertDoom2Nethack.sh` prend la
   main dans le terminal : il déclare la branche « Doom E1M2 » dans le
   fichier `dat/dungeon.lua` des sources de NetHack, reconstruit
   l'archive de données `nhdat` et copie les niveaux. Il demande
   confirmation avant de modifier quoi que ce soit, et garde une copie des
   fichiers d'origine (`.doom2nethack.orig`).
5. `p` lance une **nouvelle** partie et vous téléporte au premier niveau
   de la branche (une partie sauvegardée garde l'ancien plan du donjon).
   Sans téléportation, l'escalier qui mène à la branche se trouve entre
   les niveaux 2 et 4 du donjon principal.

Pour retirer toutes les branches Doom de NetHack : **Retirer les branches
Doom**, dans le menu principal.

## 7. Convertir tout un épisode

1. Dans **Convertir des cartes**, cochez des cartes avec `Espace`, ou
   toutes avec `a`.
2. `Entrée` les convertit l'une après l'autre, en arrière-plan.
3. Le menu reste utilisable pendant ce temps : regardez les premiers
   niveaux convertis pendant que les suivants se convertissent.
4. Le journal (`l`) liste les résultats ; `r` les résume tous ; `x`
   arrête les conversions en cours et en attente.

Quitter le menu arrête aussi les conversions, après confirmation.

## 8. Sans le menu

Tout ce que fait le menu existe en ligne de commande :

```sh
# lister les cartes d'un WAD
python3 doom2nethack.py --list freedoom-0.13.0/freedoom1.wad

# convertir E1M1 en mode rooms et afficher la carte
python3 doom2nethack.py -p --mode rooms -m E1M1 freedoom-0.13.0/freedoom1.wad

# convertir et installer un niveau, ou une branche
./convertDoom2Nethack.sh freedoom-0.13.0/freedoom1.wad E1M1
./convertDoom2Nethack.sh -n auto freedoom-0.13.0/freedoom1.wad E1M2

# jouer un niveau installé, ou le premier niveau d'une branche
python3 -m d2n.play e1m1
python3 -m d2n.play --branch e1m2a
```

Dans NetHack, sans le menu : `Ctrl-V` `3` `Entrée` pour descendre au
niveau 3, `#wizloaddes` `Entrée` `e1m1` `Entrée` pour charger le niveau,
`Ctrl-F` pour révéler la carte.

## 9. En cas de problème

| Symptôme | Cause et solution |
|----------|-------------------|
| NetHack refuse le mode wizard | Votre nom d'utilisateur n'est pas sur la ligne `WIZARDS=` du fichier `sysconf` du répertoire de jeu. |
| `HACKDIR introuvable` ou `NetHack introuvable` | NetHack n'est pas installé à l'endroit par défaut : définissez `HACKDIR` et `NETHACK` (étape 0). |
| `WAD introuvable` | Le WAD n'est ni dans le répertoire courant ni dans le répertoire des WAD : donnez son chemin complet, ou définissez `WAD_DIR` (étape 0). |
| `p` ne va pas au niveau et rend la main | Une question de NetHack attendait encore une réponse, ou les invites ne sont pas reconnues. Faites le chemin à la main (étape 8), ou relancez avec `D2N_PLAY_LOG=/tmp/play.log` pour voir les touches envoyées. |
| Branche absente du menu de téléportation | La branche n'est pas installée (`i`), ou la partie a été commencée avant son installation : commencez une nouvelle partie. |
| Pas d'escalier montant au niveau 1 | NetHack n'en crée pas au premier niveau du donjon : chargez le niveau à partir du niveau 2 (le menu utilise le niveau 3). |
| Carte peu ressemblante | Essayez l'autre mode (`m`), un découpage (`n`), ou l'échelle uniforme (`o`) ; comparez avec `c`. |
| Trop de monstres | Les niveaux Doom en contiennent beaucoup : passez la difficulté à `easy` (`s`). |
