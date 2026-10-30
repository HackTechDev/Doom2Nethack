"""Menu interactif (curses) : conversion des cartes d'un WAD et niveaux déjà
convertis.

Les niveaux convertis sont rangés dans out/<WAD sans .wad>/ : un fichier
<carte>.lua par niveau simple, un répertoire <carte>/ par niveau découpé en
branche.  Le fichier doom2nethack.json de ce répertoire garde le chemin du
WAD et les options de chaque conversion, pour réinstaller une branche avec
convertDoom2Nethack.sh."""

import curses
import filecmp
import json
import locale
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from dataclasses import dataclass

from .convert import MAX_HEIGHT, MAX_WIDTH
from .dungeon import declared
from .play import play
from .split import MAX_PARTS
from .tables import MONSTERS, OBJECTS, SYMBOLS, doom_sources
from .wad import WAD_DIR, Wad, WadError, find_wad

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT, "out")
CLI = os.path.join(PROJECT, "doom2nethack.py")
SCRIPT = os.path.join(PROJECT, "convertDoom2Nethack.sh")
HACKDIR = os.environ.get("HACKDIR", os.path.expanduser(
    "~/nh/install/games/lib/nethackdir"))
NETHACK = os.environ.get("NETHACK", os.path.join(
    os.path.dirname(os.path.dirname(HACKDIR)), "nethack"))
NETHACK_SRC = os.environ.get("NETHACK_SRC", os.path.join(
    os.path.dirname(PROJECT), "NetHack-5.0.0"))
DUNGEON_LUA = os.path.join(NETHACK_SRC, "dat", "dungeon.lua")
META = "doom2nethack.json"
RECENT_WADS = os.path.join(OUT_DIR, ".recent-wads.json")
OPTIONS_FILE = os.path.join(OUT_DIR, ".options.json")
LAST_WAD = os.path.join(OUT_DIR, ".last-wad")       # ancien format
MAX_RECENT = 10

DEFAULT_OPTS = {"mode": "raster", "parts": "1", "skill": "medium",
                "hazards": "none", "dark": 144, "rooms": 0,
                "width": MAX_WIDTH, "height": MAX_HEIGHT,
                "keep_aspect": False, "coverage": 0.34}
# Options de l'écran d'options : (clé, libellé, valeurs, aide).  Une liste
# est parcourue en boucle ; un triplet (type, min, max) est saisi au
# clavier (type "parts" : nombre de niveaux ou « auto »).
OPTIONS = [
    ("mode", "Mode", ["raster", "rooms"],
     "raster : plan décalqué ; rooms : salles et couloirs"),
    ("parts", "Découpage", ("parts", 1, MAX_PARTS),
     f"niveaux NetHack par carte (1 à {MAX_PARTS}, ou auto)"),
    ("skill", "Difficulté", ["easy", "medium", "hard"],
     "monstres et objets présents"),
    ("hazards", "Sols à dégâts", ["none", "water", "lava"],
     "rendu de la nukage et de la lave"),
    ("dark", "Seuil de lumière", (int, 0, 256),
     "secteurs plus sombres laissés dans le noir (0 : tout éclairé)"),
    ("rooms", "Salles visées", (int, 0, 99),
     "mode rooms, par niveau (0 : automatique)"),
    ("width", "Largeur", (int, 3, MAX_WIDTH), "de la carte, en cases"),
    ("height", "Hauteur", (int, 3, MAX_HEIGHT), "de la carte, en cases"),
    ("keep_aspect", "Échelle uniforme", [False, True],
     "sinon la carte est étirée"),
    ("coverage", "Couverture", (float, 0.01, 1.0),
     "part d'une case à couvrir pour faire un sol"),
]
# Raccourcis du menu de conversion : touche -> (option, valeurs).
CYCLES = {
    "m": ("mode", ["raster", "rooms"]),
    "n": ("parts", ["1", "2", "3", "4", "auto"]),
    "s": ("skill", ["easy", "medium", "hard"]),
    "h": ("hazards", ["none", "water", "lava"]),
}

INSTALL_TEXT = """\
{name}.lua est installé dans {hackdir}

Pour charger le niveau :
  1. Lancer NetHack en mode wizard :
       {nethack} -D
  2. Descendre au niveau 3 (au niveau 1, NetHack refuse l'escalier
     montant) : Ctrl-V, puis 3 et Entrée.
  3. Charger le niveau : #wizloaddes, Entrée, puis {name} et Entrée.
  4. Afficher toute la carte : Ctrl-F."""


# --- fichiers ---------------------------------------------------------------

def wad_dir(wad, outdir=OUT_DIR):
    """Répertoire des niveaux convertis d'un WAD."""
    return os.path.join(outdir, os.path.splitext(os.path.basename(wad))[0])


@dataclass
class Converted:
    name: str           # carte Doom en minuscules (e1m1)
    path: str           # fichier .lua, ou répertoire d'une branche
    parts: list         # fichiers .lua des niveaux NetHack

    @property
    def split(self):
        return os.path.isdir(self.path)


@dataclass
class Section:
    name: str           # nom du WAD sans extension
    path: str
    wad: str            # chemin du WAD, s'il est connu
    levels: list


def load_meta(d):
    try:
        with open(os.path.join(d, META)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_meta(d, meta):
    with open(os.path.join(d, META), "w") as f:
        json.dump(meta, f, indent=2)


def converted_levels(outdir=OUT_DIR):
    """Niveaux convertis, une section par WAD."""
    sections = []
    try:
        names = sorted(os.listdir(outdir))
    except OSError:
        return sections
    for name in names:
        d = os.path.join(outdir, name)
        if not os.path.isdir(d):
            continue
        files = sorted(os.listdir(d))
        if any(f.endswith("-dungeon.lua") for f in files):
            continue            # branche écrite directement dans out/
        levels = []
        for f in files:
            p = os.path.join(d, f)
            if f.endswith(".lua") and os.path.isfile(p):
                levels.append(Converted(f[:-4], p, [p]))
            elif os.path.isdir(p):
                parts = sorted(os.path.join(p, g) for g in os.listdir(p)
                               if g.endswith(".lua")
                               and not g.endswith("-dungeon.lua"))
                if parts:
                    levels.append(Converted(f, p, parts))
        if levels:
            levels.sort(key=lambda lv: (lv.name, lv.split))
            sections.append(Section(name, d, load_meta(d).get("wad"),
                                    levels))
    return sections


def conversion_args(opts):
    args = ["--mode", opts["mode"], "--skill", opts["skill"],
            "--hazards", opts["hazards"], "--dark-below", str(opts["dark"])]
    for key in ("rooms", "width", "height", "coverage"):
        if opts[key] != DEFAULT_OPTS[key]:
            args += [f"--{key}", str(opts[key])]
    if opts["keep_aspect"]:
        args.append("--keep-aspect")
    return args


def parse_option(spec, text):
    """Valeur saisie pour une option (type, min, max) ; ValueError si elle
    est invalide."""
    kind, lo, hi = spec
    text = text.strip().replace(",", ".")
    if kind == "parts" and text == "auto":
        return text
    try:
        value = (float if kind is float else int)(text)
    except ValueError:
        value = None
    if value is None or not lo <= value <= hi:
        raise ValueError(f"valeur invalide : entre {lo} et {hi}"
                         + (" ou auto" if kind == "parts" else ""))
    return str(value) if kind == "parts" else value


def load_options(path=OPTIONS_FILE):
    """Options de conversion gardées de la session précédente ; une valeur
    absente, inconnue ou invalide est remplacée par la valeur par
    défaut."""
    opts = dict(DEFAULT_OPTS)
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return opts
    if not isinstance(saved, dict):
        return opts
    for key, _, spec, _ in OPTIONS:
        if key not in saved:
            continue
        value = saved[key]
        if isinstance(spec, list):
            if any(value == v and type(value) is type(v) for v in spec):
                opts[key] = value
        elif isinstance(value, (str, int, float)) and \
                not isinstance(value, bool):
            try:
                opts[key] = parse_option(spec, str(value))
            except ValueError:
                pass
    return opts


def save_options(opts, path=OPTIONS_FILE):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(opts, f, indent=2)
    except OSError:
        pass                    # les options restent valables pour la session


def option_text(key, value):
    if key == "keep_aspect":
        return "oui" if value else "non"
    if key in ("rooms", "dark") and value == 0:
        return "automatique" if key == "rooms" else "0 (tout éclairé)"
    return str(value)


META_LOCK = threading.Lock()


def run_conversion(wad, mapname, opts, outdir=OUT_DIR, started=None):
    """Convertit une carte avec doom2nethack.py.  Retourne (réussite,
    lignes affichées par la commande).  `started(proc)` reçoit le
    processus lancé (pour pouvoir l'arrêter)."""
    d = wad_dir(wad, outdir)
    low = mapname.lower()
    args = conversion_args(opts)
    cmd = [sys.executable, CLI, "-p", "-m", mapname, *args]
    if opts["parts"] == "1":
        key = f"{low}.lua"
        cmd += ["-o", os.path.join(d, key), wad]
    else:
        key = low
        shutil.rmtree(os.path.join(d, key), ignore_errors=True)
        cmd += ["-n", opts["parts"], "-d", os.path.join(d, key), wad]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if started:
        started(proc)
    out, err = proc.communicate()
    if proc.returncode == 0:
        with META_LOCK:
            meta = load_meta(d)
            meta["wad"] = os.path.abspath(wad)
            meta.setdefault("levels", {})[key] = {"parts": opts["parts"],
                                                  "args": args}
            save_meta(d, meta)
    return proc.returncode == 0, (out + err).splitlines()


class Jobs:
    """File de conversions traitées l'une après l'autre en arrière-plan.
    `version` augmente à chaque changement, pour rafraîchir l'affichage."""

    def __init__(self, outdir=OUT_DIR):
        self.outdir = outdir
        self.lock = threading.Lock()
        self.pending = []           # (wad, carte, options)
        self.current = None
        self.proc = None
        self.thread = None
        self.results = []           # (wad, carte, réussite, lignes)
        self.version = 0
        self.total = self.done = self.failed = 0

    def add(self, wad, name, opts):
        with self.lock:
            if (wad, name) in self.queued():
                return
            if not self.active():
                self.total = self.done = self.failed = 0
            self.pending.append((wad, name, dict(opts)))
            self.total += 1
            self.version += 1
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _run(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.current = self.proc = self.thread = None
                    self.version += 1
                    return
                job = self.current = self.pending.pop(0)
                self.version += 1
            ok, lines = run_conversion(*job, outdir=self.outdir,
                                       started=self._started)
            with self.lock:
                if self.current is job:     # pas arrêtée entre-temps
                    self.results.append((job[0], job[1], ok, lines))
                    self.done += 1
                    self.failed += not ok
                self.version += 1

    def _started(self, proc):
        with self.lock:
            self.proc = proc

    def queued(self):
        """(wad, carte) en cours ou en attente."""
        jobs = self.pending + ([self.current] if self.current else [])
        return [(w, n) for w, n, _ in jobs]

    def active(self):
        return len(self.pending) + (self.current is not None)

    def state(self, wad, name):
        if self.current and self.current[:2] == (wad, name):
            return "conversion..."
        if (wad, name) in self.queued():
            return "en attente"
        return None

    def stop(self):
        """Abandonne les conversions en attente et celle en cours."""
        with self.lock:
            self.total -= len(self.pending)
            self.pending.clear()
            if self.current:
                self.total -= 1
                self.current = None
                if self.proc:
                    self.proc.terminate()
            self.version += 1

    def wait(self, timeout=None):
        t = self.thread
        if t:
            t.join(timeout)


def delete_level(section, level):
    if level.split:
        shutil.rmtree(level.path)
    else:
        os.remove(level.path)
    with META_LOCK:
        meta = load_meta(section.path)
        if meta.get("levels", {}).pop(os.path.basename(level.path), None):
            save_meta(section.path, meta)


def summary_lines(results, error_attr=0):
    """Résumé de plusieurs conversions : (carte, réussite, lignes)."""
    out = []
    for *_, name, ok, lines in results:
        if ok:
            out.append((f"{name:<8} ok", curses.A_BOLD))
            out += [f"    {line.strip()}" for line in lines
                    if re.match(r"\s*(\w+ : carte|info|attention)", line)]
        else:
            out.append((f"{name:<8} ÉCHEC", error_attr | curses.A_BOLD))
            out += [(f"    {line}", error_attr) for line in lines[-3:]]
    return out


def branch_name(level):
    """Nom de la branche déclarée par convertDoom2Nethack.sh."""
    return f"Doom {level.name.upper()}"


def declared_branches(dungeon=DUNGEON_LUA):
    try:
        with open(dungeon) as f:
            return declared(f.read())
    except OSError:
        return {}


def install_state(level, hackdir=HACKDIR, branches=None):
    """État dans NetHack d'un niveau converti : None (non installé) ou un
    texte.  `branches` : branches déclarées dans dungeon.lua."""
    copies = [os.path.join(hackdir, os.path.basename(p)) for p in level.parts]
    present = [os.path.isfile(c) for c in copies]
    names = [os.path.basename(p)[:-4] for p in level.parts]
    listed = level.split and (branches or {}).get(branch_name(level))
    if not any(present):
        return "déclaré, fichiers absents" if listed else None
    if not all(present):
        return "installé en partie"
    same = all(filecmp.cmp(p, c, shallow=False)
               for p, c in zip(level.parts, copies))
    if level.split and listed != names:
        return "fichiers copiés, branche non déclarée" if not listed \
            else "installé, autre découpage"
    return "installé" if same else "installé, autre version"


@dataclass
class LevelView:
    """Contenu d'un niveau .lua, pour l'aperçu."""
    grid: list          # lignes de des.map
    dark: set           # cases sombres
    stairs: dict        # (x, y) -> "<" ou ">"
    monsters: dict      # (x, y) -> (nom, invisible, endormi)
    objects: dict       # (x, y) -> (classe, nom)
    doors: dict         # (x, y) -> état de la porte
    branch: tuple = None    # escalier de branche (remplace "<")

    @property
    def width(self):
        return max((len(r) for r in self.grid), default=0)

    @property
    def desc(self):
        return (f"carte {self.width}x{len(self.grid)}, "
                f"{len(self.doors)} porte(s), "
                f"{len(self.monsters)} monstre(s), "
                f"{len(self.objects)} objet(s), {len(self.dark)} case(s) "
                f"sombre(s)")

    def cell(self, x, y):
        """(caractère, nature) de la case : escalier, monstre, objet, ou
        le terrain de la carte."""
        if (x, y) in self.stairs:
            return self.stairs[x, y], "stair"
        if (x, y) in self.monsters:
            name, invisible, _ = self.monsters[x, y]
            return SYMBOLS.get(name, "M"), "invisible" if invisible \
                else "monster"
        if (x, y) in self.objects:
            return self.objects[x, y][0], "object"
        return self.terrain(x, y)

    def terrain(self, x, y):
        row = self.grid[y] if y < len(self.grid) else ""
        c = row[x] if x < len(row) else " "
        return c, TERRAIN.get(c, "floor")

    def describe(self, x, y):
        """Description de la case : monstre, objet, escalier, terrain."""
        what = []
        if (x, y) in self.monsters:
            name, invisible, asleep = self.monsters[x, y]
            state = [s for s, on in (("invisible", invisible),
                                     ("endormi", asleep)) if on]
            doom = doom_sources(MONSTERS, (name, invisible))
            what.append(f"monstre : {name}"
                        + (f" ({', '.join(state)})" if state else "")
                        + (f" ← Doom : {', '.join(doom)}" if doom else ""))
        if (x, y) in self.objects:
            cls, name = self.objects[x, y]
            full = {"!": f"potion of {name}", "/": f"wand of {name}"}.get(
                cls, name)
            doom = doom_sources(OBJECTS, (cls, name))
            what.append(f"objet : {full}"
                        + (f" ← Doom : {', '.join(doom)}" if doom else ""))
        if (x, y) in self.stairs:
            what.append("escalier de branche" if (x, y) == self.branch else
                        "escalier montant" if self.stairs[x, y] == "<" else
                        "escalier descendant")
        c, kind = self.terrain(x, y)
        ground = TERRAIN_NAMES.get(kind, kind)
        if kind == "door":
            state = self.doors.get((x, y))
            ground += f" ({DOOR_NAMES.get(state, state)})" if state else ""
        if (x, y) in self.dark:
            ground += ", zone sombre"
        what.append(("sur : " if what else "") + ground)
        return f"({x:02d},{y:02d}) " + " — ".join(what)

    def points(self):
        """Cases des monstres et objets, dans l'ordre de lecture."""
        return sorted(set(self.monsters) | set(self.objects),
                      key=lambda p: (p[1], p[0]))


TERRAIN = {"-": "wall", "|": "wall", " ": "rock", "+": "door", "#": "corridor",
           "}": "water", "L": "lava", "F": "bars", "S": "door"}
TERRAIN_NAMES = {"wall": "mur", "rock": "roche", "door": "porte",
                 "corridor": "couloir", "floor": "sol", "water": "eau",
                 "lava": "lave", "bars": "barreaux de fer"}
DOOR_NAMES = {"closed": "fermée", "locked": "verrouillée", "open": "ouverte",
              "nodoor": "sans porte", "broken": "cassée"}


def parse_lua(path):
    with open(path) as f:
        text = f.read()
    m = re.search(r"map = \[\[\n(.*?)\n\]\]", text, re.S)
    grid = m.group(1).split("\n") if m else []
    stairs, branch = {}, None
    for c, pattern in (("<", r'des\.stair\("up", (\d+),(\d+)\)'),
                       ("b", r"region = \{(\d+),(\d+),"),
                       (">", r'des\.stair\("down", (\d+),(\d+)\)')):
        for x, y in re.findall(pattern, text):
            if c == "b":
                branch = int(x), int(y)
            stairs[int(x), int(y)] = "<" if c == "b" else c
    dark = set()
    for x1, y, x2 in re.findall(r"dark = dark \| selection\.area\((\d+),(\d+),"
                                r"(\d+),\d+\)", text):
        dark.update((x, int(y)) for x in range(int(x1), int(x2) + 1))
    monsters = {}
    for line in re.findall(r"des\.monster\(.*", text):
        m = re.search(r'id = "([^"]+)", x = (\d+), y = (\d+)', line)
        if m:
            monsters[int(m.group(2)), int(m.group(3))] = \
                (m.group(1), "invisible = 1" in line, "asleep = 1" in line)
    objects = {(int(x), int(y)): (cls, name) for name, cls, x, y in
               re.findall(r'des\.object\(\{ id = "([^"]+)", class = "(.)", '
                          r'x = (\d+), y = (\d+)', text)}
    doors = {(int(x), int(y)): state for state, x, y in
             re.findall(r'des\.door\("(\w+)", (\d+),(\d+)\)', text)}
    return LevelView(grid, dark, stairs, monsters, objects, doors, branch)


def lua_summary(path):
    """(description, carte avec les escaliers) d'un niveau .lua."""
    view = parse_lua(path)
    grid = [list(r) for r in view.grid]
    for (x, y), c in view.stairs.items():
        if y < len(grid) and x < len(grid[y]):
            grid[y][x] = c
    return view.desc, ["".join(r) for r in grid]


def rel(path):
    """Chemin relatif au projet quand il s'y trouve."""
    r = os.path.relpath(path, PROJECT)
    return path if r.startswith("..") else r


def recent_wads(path=RECENT_WADS):
    """WAD récents, le dernier utilisé d'abord (fichiers existants)."""
    try:
        with open(path) as f:
            wads = [w for w in json.load(f) if isinstance(w, str)]
    except (OSError, ValueError, TypeError):
        wads = []
        if path == RECENT_WADS:             # reprise de l'ancien format
            try:
                with open(LAST_WAD) as f:
                    wads = [f.read().strip()]
            except OSError:
                pass
    return [w for w in wads if os.path.isfile(w)]


def last_wad():
    return next(iter(recent_wads()), None)


def remember_wad(wad, path=RECENT_WADS):
    """Met `wad` en tête des WAD récents."""
    wads = [wad] + [w for w in recent_wads(path) if w != wad]
    save_recent(wads, path)


def forget_wad(wad, path=RECENT_WADS):
    save_recent([w for w in recent_wads(path) if w != wad], path)


def save_recent(wads, path=RECENT_WADS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(wads[:MAX_RECENT], f, indent=2)


def complete_path(text, base):
    """Complétion d'un chemin (relatif à `base`) : (texte complété,
    candidats)."""
    full = os.path.join(base, os.path.expanduser(text))
    head, tail = os.path.split(full)
    try:
        names = sorted(n for n in os.listdir(head or ".")
                       if n.startswith(tail) and
                       (tail.startswith(".") or not n.startswith(".")))
    except OSError:
        return text, []
    if not names:
        return text, []
    common = os.path.commonprefix(names)
    done = text + common[len(tail):]
    if len(names) == 1 and os.path.isdir(os.path.join(head, common)):
        done += "/"
    return done, names


# --- interface --------------------------------------------------------------

LOGO = [("█▀▄ █▀█ █▀█ █▀▄▀█", "█▄ █ █▀▀ ▀█▀ █ █ ▄▀▄ ▄▀▀ █▄▀"),
        ("█▄▀ █▄█ █▄█ █ ▀ █", "█ ▀█ ██▄  █  █▀█ █▀█ ▀▄▄ █ █")]

UP = (curses.KEY_UP,)
DOWN = (curses.KEY_DOWN,)
JOURNAL = "l"
ENTER = ("\n", "\r", curses.KEY_ENTER)
BACK = ("q", "Q", "\x1b")

# Thèmes et univers repris du lanceur Nethack_Launcher : chaque élément de
# l'affichage a une couleur (ou None) et des attributs.
COLOR_NAMES = {"noir": curses.COLOR_BLACK, "rouge": curses.COLOR_RED,
               "vert": curses.COLOR_GREEN, "jaune": curses.COLOR_YELLOW,
               "bleu": curses.COLOR_BLUE, "magenta": curses.COLOR_MAGENTA,
               "cyan": curses.COLOR_CYAN, "blanc": curses.COLOR_WHITE}
ATTR_NAMES = {"gras": curses.A_BOLD, "pale": curses.A_DIM,
              "inverse": curses.A_REVERSE, "souligne": curses.A_UNDERLINE}
COMMON_STYLES = {
    "titre": (None, "gras"), "dim": (None, "pale"), "aide": (None, "pale"),
    "path": (None, "gras"), "indisponible": (None, "pale"),
    "selection": (None, "inverse", "gras"),
}
THEMES = {
    "classique": {
        "logo": ("rouge", "gras"), "logo2": ("jaune", "gras"),
        "separateur": ("bleu",), "groupe": ("bleu", "gras"),
        "numero": ("cyan",), "touche": ("jaune", "gras"),
        "description": ("cyan",), "label": ("cyan",),
        "accent": ("jaune", "gras"), "ok": ("vert",), "warn": ("jaune",),
        "busy": ("magenta", "gras"), "error": ("rouge", "gras"),
        "invite": ("jaune", "gras"),
    },
    "cyber": {
        "logo": ("magenta", "gras"), "logo2": ("cyan", "gras"),
        "titre": ("cyan", "gras"), "separateur": ("cyan",),
        "groupe": ("magenta", "gras"), "numero": ("vert",),
        "touche": ("cyan", "gras"), "description": ("magenta",),
        "label": ("cyan",), "accent": ("vert", "gras"), "ok": ("vert",),
        "warn": ("jaune",), "busy": ("magenta", "gras"),
        "error": ("rouge", "gras"), "invite": ("cyan", "gras"),
    },
    "sobre": {
        "logo": (None, "gras"), "logo2": (None, "gras"),
        "separateur": (None,), "groupe": (None, "gras"),
        "numero": (None,), "touche": (None, "gras"),
        "description": (None,), "label": (None,),
        "accent": (None, "gras"), "ok": (None, "gras"), "warn": (None,),
        "busy": (None, "gras"), "error": (None, "gras"),
        "invite": (None, "gras"),
    },
}
THEME_NAMES = ("auto", *THEMES)

# Textes de l'interface : l'univers « cyber » suit la version cyberpunk de
# NetHack (langue fr@cyber), comme le lanceur.
TEXTS = {
    "classique": {
        "titre": "CONVERTISSEUR DOOM",
        "sous_titre": "conversion de niveaux Doom en niveaux NetHack",
        "groupe_conversion": "Conversion",
        "groupe_reglages": "Réglages",
        "convert": "Convertir des cartes",
        "convert_desc": "Convertit les cartes du WAD dans {out}/<WAD>/ : "
        "une à une, ou plusieurs cochées, en arrière-plan.",
        "levels": "Niveaux convertis",
        "levels_desc": "Aperçu en couleurs, installation dans NetHack et "
        "partie en mode wizard sur un niveau converti.",
        "journal": "Journal des conversions",
        "journal_desc": "Résultat de chaque conversion de la session "
        "({n} pour l'instant).",
        "wad": "Choisir un autre WAD",
        "wad_desc": "WAD récents et explorateur de fichiers, à partir du "
        "répertoire des WAD.",
        "restore": "Retirer les branches Doom",
        "restore_desc": "Retire de dungeon.lua les branches Doom déclarées "
        "({n}) et réinstalle nhdat (convertDoom2Nethack.sh --restore).",
        "restore_none": "aucune branche",
        "quitter": "Quitter",
        "quitter_desc": "Quitter le menu ; les conversions en cours sont "
        "arrêtées, après confirmation.",
        "aide": "↑/↓ choisir · Entrée valider · touche ou numéro · "
        "q quitter",
        "ecran_convert": "conversion",
        "ecran_levels": "niveaux convertis",
        "ecran_journal": "journal des conversions",
        "ecran_wad": "choisir un fichier WAD",
        "touche_inconnue": "Touche inconnue : {touche}",
    },
    "cyber": {
        "titre": "CONVERTISSEUR // NIGHT CITY",
        "sous_titre": "piratage de niveaux Doom en secteurs de Night City",
        "groupe_conversion": "Piratage",
        "groupe_reglages": "Système",
        "convert": "Pirater des cartes",
        "convert_desc": "Recompile les cartes du WAD en secteurs de Night "
        "City dans {out}/<WAD>/ : une à une, ou plusieurs marquées, en "
        "tâche de fond.",
        "levels": "Secteurs compilés",
        "levels_desc": "Inspecte un secteur compilé, l'injecte dans NetHack "
        "ou s'y branche en mode debug.",
        "journal": "Journal des opérations",
        "journal_desc": "Rapport de chaque piratage de la session "
        "({n} pour l'instant).",
        "wad": "Brancher un autre WAD",
        "wad_desc": "WAD récents et navigation dans les fichiers, à partir "
        "du répertoire des WAD.",
        "restore": "Purger les branches Doom",
        "restore_desc": "Efface de dungeon.lua les branches Doom déclarées "
        "({n}) et réinstalle nhdat (convertDoom2Nethack.sh --restore).",
        "restore_none": "aucune branche",
        "quitter": "Déconnexion",
        "quitter_desc": "Couper la liaison et quitter le terminal ; les "
        "opérations en cours sont interrompues, après confirmation.",
        "aide": "↑/↓ naviguer · Entrée connexion · touche ou numéro · "
        "q déconnexion",
        "ecran_convert": "piratage",
        "ecran_levels": "secteurs compilés",
        "ecran_journal": "journal des opérations",
        "ecran_wad": "brancher un WAD",
        "touche_inconnue": "Commande inconnue : {touche}",
    },
}

# Menu principal : (entrée, touche, groupe).
MAIN_ENTRIES = [("convert", "c", "groupe_conversion"),
                ("levels", "n", "groupe_conversion"),
                ("journal", "l", "groupe_conversion"),
                ("wad", "w", "groupe_reglages"),
                ("restore", "r", "groupe_reglages")]
MAIN_WIDTH = 56             # largeur des séparateurs du menu principal
GROUP_WIDTH = 40            # largeur des titres de groupe


def game_language(env=None, rc=None):
    """Langue de NetHack (OPTIONS=language:...) lue dans ~/.nethackrc ou
    NETHACKOPTIONS, la dernière valeur l'emportant ; None si absente."""
    env = os.environ if env is None else env
    var = env.get("NETHACKOPTIONS", "")
    is_file = var.startswith(("@", "/"))
    path = os.path.expanduser(var.lstrip("@")) if is_file else \
        rc or os.path.expanduser("~/.nethackrc")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    if var and not is_file:
        lines.append(var)
    language = None
    for line in lines:
        if not line.lstrip().startswith("#"):
            for m in re.finditer(r"\blanguage:([^,\s]+)", line):
                language = m.group(1)
    return language


def universe(language):
    """Univers des textes : « cyber » pour la version cyberpunk."""
    return "cyber" if (language or "").endswith("@cyber") else "classique"


def choose_theme(name, language, colors=True):
    """Thème utilisé : `auto` suit l'univers ; sans couleurs, « sobre »."""
    if not colors:
        return "sobre"
    if name == "auto":
        return universe(language)
    return name


def group_title(name, width=GROUP_WIDTH):
    """Titre de groupe, « ── nom ───── », de largeur `width`."""
    start = f"── {name} "
    return start + "─" * max(width - len(start), 3)


def help_groups(line):
    """Groupes « touche action » d'une ligne d'aide (séparés par au moins
    3 espaces) : liste de (touche, action)."""
    return [tuple(g.partition(" ")[::2]) for g in re.split(r" {3,}",
                                                           line.strip()) if g]


def cursor_visible(visible):
    """Affiche ou masque le curseur, si le terminal le permet."""
    try:
        curses.curs_set(visible)
    except curses.error:
        pass


class App:
    def __init__(self, scr, wad=None, theme="auto", mouse=True):
        self.scr = scr
        self.wad = wad
        self.opts = load_options()
        self.jobs = Jobs()
        self.seen = 0               # dernière version de self.jobs affichée
        cursor_visible(0)
        language = game_language()
        self.texts = TEXTS[universe(language)]
        self.colors = curses.has_colors() and "NO_COLOR" not in os.environ
        self.init_theme(choose_theme(theme, language, self.colors))
        if mouse:
            # clic : choisir une ligne ; double-clic : valider ; molette
            curses.mousemask(curses.BUTTON1_CLICKED
                             | curses.BUTTON1_DOUBLE_CLICKED
                             | curses.BUTTON4_PRESSED
                             | getattr(curses, "BUTTON5_PRESSED", 0))
        # attributs de l'aperçu des cartes, par nature de case
        colors = {"door": curses.COLOR_YELLOW, "water": curses.COLOR_BLUE,
                  "lava": curses.COLOR_RED, "bars": curses.COLOR_CYAN,
                  "monster": curses.COLOR_RED, "invisible": curses.COLOR_RED,
                  "object": curses.COLOR_CYAN, "stair": curses.COLOR_MAGENTA}
        self.cell_attr = {k: curses.A_BOLD for k in colors}
        if self.colors:
            for i, (k, color) in enumerate(colors.items(), 10):
                curses.init_pair(i, color, self.background)
                self.cell_attr[k] = curses.color_pair(i)
        for k in ("monster", "stair", "invisible"):
            self.cell_attr[k] |= curses.A_BOLD
        self.cell_attr["invisible"] |= curses.A_UNDERLINE

    def init_theme(self, name):
        """Attributs curses de chaque élément de l'affichage pour le thème
        `name` (classique, cyber ou sobre)."""
        self.background = curses.COLOR_BLACK
        if self.colors:
            try:
                curses.use_default_colors()
                self.background = -1
            except curses.error:
                pass
        pairs, t = {}, {}
        for elt, (color, *attrs) in {**COMMON_STYLES,
                                     **THEMES[name]}.items():
            attr = 0
            for a in attrs:
                attr |= ATTR_NAMES[a]
            if color and self.colors:
                if color not in pairs:
                    n = 20 + len(pairs)
                    curses.init_pair(n, COLOR_NAMES[color], self.background)
                    pairs[color] = curses.color_pair(n)
                attr |= pairs[color]
            t[elt] = attr
        self.theme_name = name
        self.theme = t
        self.section = t["accent"]
        self.done = t["ok"]
        self.error = t["error"]

    def tx(self, key, **values):
        """Texte de l'interface dans l'univers choisi."""
        text = self.texts[key]
        return text.format(**values) if values else text

    # dessin

    def draw(self, y, x, parts, attr=0):
        """Écrit un texte (str) ou une suite de (texte, attribut) ;
        retourne la colonne suivante."""
        if isinstance(parts, str):
            parts = [(parts, 0)]
        for part in parts:
            text, a = part if isinstance(part, tuple) else (part, 0)
            self.put(y, x, text, a | attr)
            x += len(text)
        return x

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            n = w - x - (1 if y == h - 1 else 0)    # pas la dernière case
            try:
                self.scr.addnstr(y, x, text, n, attr)
            except curses.error:
                pass

    def header(self, title):
        """Titre de l'écran, WAD utilisé et séparateur ; retourne la
        première ligne libre."""
        self.scr.erase()
        w = self.scr.getmaxyx()[1]
        t = self.theme
        self.seen = self.jobs.version
        x = self.draw(0, 1, [("◆ Doom2NetHack", t["logo"]), (" › ", t["dim"]),
                             (title, t["titre"])])
        status, attr = self.jobs_status()
        if status:
            self.put(0, max(w - len(status) - 1, x + 2), status, attr)
        self.draw(1, 1, [("Fichier WAD  ", t["label"]),
                         (rel(self.wad) if self.wad else "(aucun)",
                          t["path"])])
        self.put(2, 0, "=" * (w - 1), t["separateur"])
        return 3

    def footer(self, text, attr=None):
        """Aide en bas de l'écran (plusieurs lignes séparées par \\n).
        Sans `attr`, chaque groupe « touche action » (séparés par 3
        espaces) montre la touche en couleur, les groupes séparés par
        « · »."""
        h, w = self.scr.getmaxyx()
        t = self.theme
        lines = text.split("\n")
        for k, line in enumerate(lines):
            y = h - len(lines) + k
            self.put(y, 0, " " * w)
            if attr is not None:
                self.put(y, 1, line, attr)
                continue
            x = 1
            for i, (key, label) in enumerate(help_groups(line)):
                x = self.draw(y, x, [(" · " if i else "", t["aide"]),
                                     (key, t["touche"]),
                                     (f" {label}" if label else "",
                                      t["aide"])])

    def status(self, text):
        self.footer(text, self.theme["invite"])
        self.scr.refresh()

    def jobs_status(self):
        """État des conversions pour l'en-tête : (texte, attribut)."""
        j = self.jobs
        if j.active():
            width = 10
            fill = width * j.done // max(j.total, 1)
            name = j.current[1] if j.current else ""
            return (f"⟳ {'█' * fill}{'░' * (width - fill)} "
                    f"{j.done}/{j.total} {name}", self.theme["busy"])
        if j.total:
            failed = f", {j.failed} échec(s)" if j.failed else ""
            return (f"✔ {j.done} conversion(s) terminée(s){failed} · "
                    "l journal", self.theme["warn" if j.failed else "ok"])
        return "", 0

    def key(self, wake=False):
        """Touche pressée.  Avec `wake`, retourne None quand l'état des
        conversions change, pour redessiner l'écran."""
        self.scr.timeout(250)
        while True:
            try:
                c = self.scr.get_wch()
            except curses.error:
                c = None
            if c is None:
                if wake and self.jobs.version != self.seen:
                    return None
            elif c != curses.KEY_RESIZE:
                return c
            elif wake:
                return None

    @staticmethod
    def mouse():
        """Événement souris : (ligne, action), action valant "clic",
        "double", "haut" ou "bas" (molette) ; None sinon."""
        try:
            _, _, y, _, buttons = curses.getmouse()
        except curses.error:
            return None
        if buttons & curses.BUTTON4_PRESSED:
            return y, "haut"
        if buttons & getattr(curses, "BUTTON5_PRESSED", 0):
            return y, "bas"
        if buttons & curses.BUTTON1_DOUBLE_CLICKED:
            return y, "double"
        if buttons & curses.BUTTON1_CLICKED:
            return y, "clic"
        return None

    def message(self, text):
        self.footer(f"{text}  (une touche pour continuer)",
                    self.theme["invite"])
        self.key()

    def confirm(self, question):
        self.footer(f"{question} [o/N]", self.theme["invite"])
        return self.key() in ("o", "O", "y", "Y")

    # listes

    def group_row(self, name, extra=""):
        """Ligne de titre de groupe d'une liste, non sélectionnable."""
        t = self.theme
        return ([(group_title(name), t["groupe"])]
                + ([(f" {extra}", t["dim"])] if extra else []), False, 0)

    def menu(self, title, rows, sel=0, footer="", keys="", info=(),
             live=False):
        """`rows` : (texte, sélectionnable, attribut).  Retourne (touche,
        index de la ligne choisie) ; touche "\\n" pour Entrée (ou
        double-clic), "q" pour retour.  Avec `live`, retourne "refresh"
        quand l'état des conversions change, pour que l'appelant refasse
        ses lignes."""
        ok = [i for i, r in enumerate(rows) if r[1]]
        if not ok:
            return "q", None
        if sel not in ok:
            sel = next((i for i in ok if i >= (sel or 0)), ok[-1])
        top = 0
        while True:
            y0 = self.header(title)
            for i, line in enumerate(info):
                self.draw(y0 + i, 1, line)
            y0 += len(info) + bool(info)
            h, w = self.scr.getmaxyx()
            n = max(h - 2 - footer.count("\n") - y0, 1)
            top = min(max(top, sel - n + 1), sel)
            if top == sel and sel > 0 and not rows[sel - 1][1]:
                top = sel - 1               # garder le titre de groupe
            for k, (text, selectable, attr) in enumerate(rows[top:top + n]):
                if top + k == sel:
                    plain = text if isinstance(text, str) else \
                        "".join(p[0] if isinstance(p, tuple) else p
                                for p in text)
                    self.put(y0 + k, 1, f"  {plain}"[:w - 2].ljust(w - 2),
                             self.theme["selection"])
                else:
                    self.draw(y0 + k, 1, [("  " if selectable else "", 0)] + (
                        [(text, attr)] if isinstance(text, str) else
                        [(p, attr) if isinstance(p, str) else p
                         for p in text]))
            self.footer(footer)
            c = self.key(wake=True)
            pos = ok.index(sel)
            if c == curses.KEY_MOUSE:
                event = self.mouse()
                if not event:
                    continue
                y, action = event
                if action in ("haut", "bas"):
                    c = UP[0] if action == "haut" else DOWN[0]
                elif 0 <= y - y0 < n and top + y - y0 in ok:
                    sel = top + y - y0
                    if action == "double":
                        return "\n", sel
                    continue
            if c is None:
                if live:
                    return "refresh", sel
            elif c == JOURNAL and JOURNAL not in keys:
                self.journal()
            elif c in UP:
                sel = ok[max(pos - 1, 0)]
            elif c in DOWN:
                sel = ok[min(pos + 1, len(ok) - 1)]
            elif c == curses.KEY_PPAGE:
                sel = next((i for i in ok if i >= sel - n), ok[0])
            elif c == curses.KEY_NPAGE:
                sel = next((i for i in reversed(ok) if i <= sel + n), ok[-1])
            elif c == curses.KEY_HOME:
                sel = ok[0]
            elif c == curses.KEY_END:
                sel = ok[-1]
            elif c in ENTER:
                return "\n", sel
            elif c in BACK:
                return "q", sel
            elif isinstance(c, str) and c in keys:
                return c, sel

    def pager(self, title, lines, footer="↑↓ défiler   q retour", keys=()):
        """Texte défilant ; `lines` : textes ou (texte, attribut).
        Retourne la touche de `keys` pressée, ou "q"."""
        top = 0
        while True:
            y0 = self.header(title)
            h, w = self.scr.getmaxyx()
            n = max(h - 2 - y0, 1)
            shown = []
            for line in lines:
                text, attr = line if isinstance(line, tuple) else (line, 0)
                parts = textwrap.wrap(text, w - 2, subsequent_indent="    ") \
                    if len(text) > w - 2 else [text]
                shown += [(t, attr) for t in parts]
            top = max(min(top, len(shown) - n), 0)
            for k, (text, attr) in enumerate(shown[top:top + n]):
                self.put(y0 + k, 1, text, attr)
            self.footer(footer)
            c = self.key(wake=True)
            if c is None:
                continue
            if c == curses.KEY_MOUSE:
                event = self.mouse()
                if event and event[1] in ("haut", "bas"):
                    top += 3 if event[1] == "bas" else -3
            elif c == JOURNAL and JOURNAL not in keys:
                self.journal()
            elif c in UP:
                top -= 1
            elif c in DOWN:
                top += 1
            elif c == curses.KEY_PPAGE:
                top -= n
            elif c in (curses.KEY_NPAGE, " "):
                top += n
            elif c in keys:
                return c
            elif c in BACK or c in ENTER:
                return "q"

    # écrans

    def main_entries(self):
        """Entrées du menu principal : (entrée, touche, groupe, libellé,
        description, problème qui l'empêche, ou "")."""
        counts = {"journal": len(self.jobs.results),
                  "restore": len(declared_branches())}
        entries = []
        for name, key, group in MAIN_ENTRIES:
            desc = self.tx(f"{name}_desc", out=rel(OUT_DIR),
                           n=counts.get(name, 0))
            problem = self.tx("restore_none") \
                if name == "restore" and not counts["restore"] else ""
            entries.append((name, key, group, self.tx(name), desc, problem))
        return entries

    def draw_main(self, entries, sel, message=""):
        """Menu principal à la manière du lanceur : logo, titre entre
        séparateurs, entrées numérotées par groupe, description de
        l'entrée choisie et aide.  Retourne {ligne : entrée}."""
        self.scr.erase()
        self.seen = self.jobs.version
        h, w = self.scr.getmaxyx()
        t = self.theme
        width = min(MAIN_WIDTH, w - 1)
        zones, y = {}, 0
        if h >= 25:
            for i, (doom, nethack) in enumerate(LOGO):
                self.draw(i, 2, [(doom, t["logo"]), ("   ", 0),
                                 ("━▶" if i else "  ", t["dim"]),
                                 ("   ", 0), (nethack, t["logo2"])])
            self.put(2, 2, self.tx("sous_titre"), t["dim"])
            y = 3
        self.put(y, 0, "=" * width, t["separateur"])
        self.put(y + 1, 0, self.tx("titre").center(width).rstrip(),
                 t["titre"])
        self.put(y + 2, 0, "=" * width, t["separateur"])
        y += 3
        group = None
        for i, (_, key, grp, label, _, problem) in enumerate(entries):
            if grp != group:
                self.put(y, 0, group_title(self.tx(grp), width), t["groupe"])
                group, y = grp, y + 1
            zones[y] = i
            if i == sel:
                text = f"  {i + 1} [{key}]  {label}" + \
                    (f"  ({problem})" if problem else "")
                self.put(y, 0, text.ljust(width), t["selection"])
            else:
                x = self.draw(y, 2, [(str(i + 1), t["numero"]), (" ", 0),
                                     (f"[{key}]", t["touche"]), ("  ", 0),
                                     (label, t["indisponible"] if problem
                                      else 0)])
                if problem:
                    self.put(y, x + 2, f"({problem})", t["error"])
            y += 1
        y += 1
        zones[y] = len(entries)
        if sel == len(entries):
            self.put(y, 0, f"    [q]  {self.tx('quitter')}".ljust(width),
                     t["selection"])
        else:
            self.draw(y, 4, [("[q]", t["touche"]), ("  ", 0),
                             (self.tx("quitter"), 0)])
        self.put(y + 1, 0, "=" * width, t["separateur"])
        y += 3
        self.draw(y, 0, [("Fichier WAD  ", t["label"]),
                         (rel(self.wad) if self.wad else "(aucun)",
                          t["path"])])
        status, attr = self.jobs_status()
        if status:
            y += 1
            self.put(y, 0, status, attr)
        y += 2
        # description de l'entrée choisie ; la place de la plus longue est
        # réservée pour que l'aide ne bouge pas d'une entrée à l'autre
        wrap = max(min(w - 1, 76), 20)
        descs = [e[4] for e in entries] + [self.tx("quitter_desc")]
        for k, line in enumerate(textwrap.wrap(descs[sel], wrap)):
            self.put(y + k, 0, line, t["description"])
        y += max(len(textwrap.wrap(d, wrap)) for d in descs) + 1
        self.put(y, 0, self.tx("aide"), t["aide"])
        if message:
            self.put(y + 1, 0, message, t["error"])
        return zones

    def run(self):
        if not self.wad:
            self.choose_wad()
        sel, message = 0, ""
        while True:
            entries = self.main_entries()
            keys = [e[1] for e in entries]
            count = len(entries) + 1            # « Quitter » en dernier
            zones = self.draw_main(entries, sel, message)
            message = ""
            c = self.key(wake=True)
            if c == curses.KEY_MOUSE:
                event = self.mouse()
                if not event:
                    continue
                y, action = event
                if action in ("haut", "bas"):
                    c = UP[0] if action == "haut" else DOWN[0]
                elif y in zones:
                    sel = zones[y]
                    if action != "double":
                        continue
                    c = "\n"
            if c is None:
                continue
            if c in UP:
                sel = (sel - 1) % count
                continue
            if c in DOWN:
                sel = (sel + 1) % count
                continue
            if c == curses.KEY_HOME:
                sel = 0
                continue
            if c == curses.KEY_END:
                sel = count - 1
                continue
            if c in BACK:
                sel = count - 1
            elif isinstance(c, str) and c.isdigit() and \
                    1 <= int(c) <= len(entries):
                sel = int(c) - 1
            elif isinstance(c, str) and c.lower() in keys:
                sel = keys.index(c.lower())
            elif c not in ENTER:
                if isinstance(c, str) and c.isprintable() and c != " ":
                    message = self.tx("touche_inconnue", touche=c)
                continue
            if sel == count - 1:
                n = self.jobs.active()
                if not n or self.confirm(f"{n} conversion(s) en cours ou en "
                                         "attente seront abandonnées. "
                                         "Quitter ?"):
                    self.jobs.stop()
                    return
                continue
            name, _, _, label, _, problem = entries[sel]
            if problem:
                message = f"{label} : {problem}"
            elif name == "restore":
                self.shell([SCRIPT, "--restore"])
            else:
                {"convert": self.convert_menu, "levels": self.converted_menu,
                 "journal": self.journal, "wad": self.choose_wad}[name]()

    def opts_lines(self):
        o = self.opts
        dark = f"sombre si lumière < {o['dark']}" if o["dark"] \
            else "tout éclairé"
        rooms = f"{o['rooms']} salles" if o["rooms"] else "salles auto"
        t = self.theme
        v = curses.A_BOLD
        dot = (" · ", t["dim"])
        return [[("Options      ", t["label"]), ("mode ", 0), (o["mode"], v),
                 dot, ("découpage ", 0), (o["parts"], v), dot,
                 ("difficulté ", 0), (o["skill"], v), dot, ("sols ", 0),
                 (o["hazards"], v), dot, (dark, v)],
                [("             ", 0), ("carte ", 0),
                 (f"{o['width']}x{o['height']}", v),
                 (" à échelle uniforme" if o["keep_aspect"] else " étirée",
                  0), dot, ("couverture ", 0), (str(o["coverage"]), v), dot,
                 (rooms, v)]]

    def options_menu(self):
        sel = 0
        while True:
            t = self.theme
            rows = [([(f"{label:<18} ", 0),
                      (f"{option_text(k, self.opts[k]):<18} ",
                       curses.A_BOLD if self.opts[k] == DEFAULT_OPTS[k]
                       else t["accent"]),
                      (help, t["dim"])], True, 0)
                    for k, label, _, help in OPTIONS]
            rows += [("", False, 0), ("Valeurs par défaut", True, 0)]
            key, sel = self.menu("options de conversion", rows, sel,
                                 "Entrée changer   q retour",
                                 info=[[("valeur modifiée", t["accent"]),
                                        (" : différente de la valeur par "
                                         "défaut · options gardées pour "
                                         "les prochaines sessions dans ",
                                         t["dim"]),
                                        (rel(OPTIONS_FILE), t["dim"])]])
            if key == "q":
                return
            if sel >= len(OPTIONS):
                self.opts = dict(DEFAULT_OPTS)
            else:
                k, label, spec, _ = OPTIONS[sel]
                if isinstance(spec, list):
                    i = spec.index(self.opts[k])
                    self.opts[k] = spec[(i + 1) % len(spec)]
                else:
                    text = self.prompt(f"{label} :", str(self.opts[k]))
                    if text is None:
                        continue
                    try:
                        self.opts[k] = parse_option(spec, text)
                    except ValueError as e:
                        self.message(str(e))
                        continue
            save_options(self.opts)

    def prompt(self, label, value="", complete=None):
        """Saisie d'une ligne dans la barre du bas ; None si Échap.
        `complete(texte)` -> (texte complété, candidats) : complétion par
        Tab, les candidats s'affichant au-dessus de la saisie."""
        cursor_visible(1)
        shown = []
        try:
            while True:
                h, w = self.scr.getmaxyx()
                text = f" {label} {value}"
                if shown:
                    line = "  ".join(shown)
                    self.put(h - 2, 0, f" {line}"[:w].ljust(w))
                self.put(h - 1, 0, text[-(w - 1):].ljust(w),
                         self.theme["invite"])
                try:
                    self.scr.move(h - 1, min(len(text), w - 2))
                except curses.error:
                    pass
                c = self.key()
                if c == "\t" and complete:
                    value, names = complete(value)
                    shown = names if len(names) > 1 else []
                    continue
                if c in ENTER:
                    return value
                if c == "\x1b":
                    return None
                if c in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    value = value[:-1]
                elif c == "\x15":                         # Ctrl-U
                    value = ""
                elif isinstance(c, str) and c.isprintable():
                    value += c
        finally:
            cursor_visible(0)

    def convert_menu(self):
        if not self.wad and not self.choose_wad():
            return
        try:
            names = Wad(self.wad).level_names()
        except (WadError, OSError) as e:
            self.message(f"Erreur : {e}")
            return
        d = wad_dir(self.wad)
        marked = set()
        sel = 0
        while True:
            rows = []
            t = self.theme
            for name in names:
                low = name.lower()
                parts = [("■ " if name in marked else "□ ",
                          t["accent"] if name in marked else t["dim"]),
                         (f"{name:<9}", curses.A_BOLD)]
                if os.path.isfile(os.path.join(d, f"{low}.lua")):
                    parts.append(("✔ converti  ", t["ok"]))
                if os.path.isdir(os.path.join(d, low)):
                    parts.append(("✔ branche  ", t["label"]))
                state = self.jobs.state(self.wad, name)
                if state:
                    parts.append((f"⟳ {state}" if state.startswith("conv")
                                  else f"… {state}",
                                  t["busy"] if state.startswith("conv")
                                  else t["warn"]))
                rows.append((parts, True, 0))
            count = [(f"{len(marked)} carte(s) cochée(s)", t["accent"]),
                     (" · ", t["dim"])] if marked else []
            key, sel = self.menu(
                self.tx("ecran_convert"), rows, sel,
                "Entrée convertir   Espace cocher   a tout cocher   "
                "c comparer   q retour\n"
                "o options   m mode   n découpage   s difficulté   h sols",
                keys=" aoc" + "".join(CYCLES), live=True,
                info=[[("Destination  ", t["label"]), (f"{rel(d)}/", t["path"])],
                      *self.opts_lines(),
                      [("Cartes       ", t["label"]), *count,
                       (f"{len(names)} dans le WAD", 0)]])
            if key == "q":
                return
            if key == "refresh":
                continue
            if key == " ":
                marked ^= {names[sel]}
                sel = min(sel + 1, len(names) - 1)
            elif key == "a":
                marked = set() if len(marked) == len(names) else set(names)
            elif key == "o":
                self.options_menu()
            elif key == "c":
                self.compare(names[sel])
            elif key in CYCLES:
                opt, values = CYCLES[key]
                i = values.index(self.opts[opt]) \
                    if self.opts[opt] in values else -1
                self.opts[opt] = values[(i + 1) % len(values)]
                save_options(self.opts)
            else:
                todo = [n for n in names if n in marked] or [names[sel]]
                if self.convert(todo):
                    marked = set()

    def target(self, name):
        """Fichier ou répertoire écrit par la conversion de `name`."""
        low = name.lower()
        return os.path.join(wad_dir(self.wad), f"{low}.lua"
                            if self.opts["parts"] == "1" else low)

    def convert(self, names):
        """Ajoute les cartes `names` à la file des conversions ; retourne
        False si l'utilisateur annule."""
        exist = [n for n in names if os.path.exists(self.target(n))]
        if exist:
            what = rel(self.target(exist[0])) if len(exist) == 1 \
                else f"{len(exist)} des {len(names)} cartes"
            if not self.confirm(f"{what} : déjà converti. Remplacer ?"):
                return False
        for name in names:
            self.jobs.add(self.wad, name, self.opts)
        return True

    def journal(self):
        """Résultats des conversions, les plus récentes d'abord."""
        sel = 0
        while True:
            results = list(reversed(self.jobs.results))
            rows = []
            for wad, name, ok, lines in results:
                carte = next((line.split(" : ", 1)[1] for line in lines
                              if " : carte " in line), "")
                rows.append(([(f"{name:<9}", curses.A_BOLD),
                              ("✔ ok     " if ok else "✘ ÉCHEC  ",
                               self.done if ok else self.error),
                              (f"{os.path.basename(wad):<16} ",
                               self.theme["label"]),
                              (carte, self.theme["dim"])], True, 0))
            waiting = [[("   ", 0), (f"{n:<9}", curses.A_BOLD),
                        (self.jobs.state(w, n), self.theme["busy"])]
                       for w, n in self.jobs.queued()]
            info = [[("Conversions en cours ou en attente",
                      self.theme["label"])], *waiting] if waiting else []
            if not rows:
                rows = [("(aucune conversion terminée)", True, 0)]
            key, sel = self.menu(
                self.tx("ecran_journal"), rows, sel,
                "Entrée détails   r tout résumer   x arrêter les "
                "conversions   e effacer   q retour",
                keys="rxe" + JOURNAL, info=info, live=True)
            if key in ("q", JOURNAL):
                return
            if key == "x" and self.jobs.active() and \
                    self.confirm("Arrêter les conversions en cours et en "
                                 "attente ?"):
                self.jobs.stop()
            elif key == "e":
                self.jobs.results.clear()
            elif key == "r" and results:
                self.pager("résumé des conversions",
                           summary_lines(results, self.error))
            elif key == "\n" and results:
                wad, name, ok, lines = results[sel]
                if not ok:
                    lines = [(line, self.error) for line in lines]
                self.pager(f"conversion de {name}"
                           + ("" if ok else " : ÉCHEC"), lines)

    def converted_menu(self):
        sel, current = 0, None
        while True:
            rows, entries = [], []
            branches = declared_branches()
            for s in converted_levels():
                if rows:
                    rows.append(("", False, 0))
                t = self.theme
                rows.append(self.group_row(s.name,
                                           rel(s.wad) if s.wad else ""))
                for lv in s.levels:
                    kind = f"branche de {len(lv.parts)} niveaux" \
                        if lv.split else "niveau simple"
                    state = install_state(lv, branches=branches)
                    rows.append(([(f"{lv.name:<9}", curses.A_BOLD),
                                  (f"{kind:<22} ", t["dim"]),
                                  (f"✔ {state}" if state == "installé"
                                   else f"! {state}" if state else "",
                                   t["ok"] if state == "installé"
                                   else t["warn"])], True, 0))
                    entries.append((s, lv))
            if not entries:
                self.message(f"Aucun niveau converti dans {rel(OUT_DIR)}/")
                return
            index = {i: e for i, e in zip(
                (i for i, r in enumerate(rows) if r[1]), entries)}
            sel = next((i for i, (_, lv) in index.items()
                        if lv.path == current), sel)
            info = [[("Jeu          ", self.theme["label"]),
                     (HACKDIR, self.theme["path"])],
                    [("dungeon.lua  ", self.theme["label"]),
                     (", ".join(branches) or "aucune branche Doom", 0)]]
            key, sel = self.menu(
                self.tx("ecran_levels"), rows, sel,
                "Entrée voir   p jouer   i installer dans NetHack   "
                "x supprimer   q retour", keys="pix", live=True, info=info)
            if key == "q":
                return
            s, lv = index[sel]
            current = lv.path
            if key == "refresh":
                continue
            if key == "\n":
                key = self.show_level(s, lv)
            if key == "p":
                self.play(s, lv)
            elif key == "i":
                self.install(s, lv)
            elif key == "x" and self.confirm(f"Supprimer {rel(lv.path)} ?"):
                delete_level(s, lv)

    def draw_map(self, y, x, view, cursor=None):
        """Dessine la carte en couleurs, avec la case `cursor` en vidéo
        inverse ; retourne la ligne suivante."""
        for j in range(len(view.grid)):
            for i in range(view.width):
                c, kind = view.cell(i, j)
                attr = self.cell_attr.get(kind, 0)
                if (i, j) in view.dark and kind in ("floor", "corridor",
                                                    "door", "wall"):
                    attr |= curses.A_DIM
                if (i, j) == cursor:
                    self.put(y + j, x + i, c, attr | curses.A_REVERSE)
                elif c != " ":
                    self.put(y + j, x + i, c, attr)
        return y + len(view.grid)

    @staticmethod
    def start_cursor(view):
        return view.branch or next(
            (p for p, c in view.stairs.items() if c == "<"),
            (view.width // 2, len(view.grid) // 2))

    @staticmethod
    def move_cursor(c, cursor, view):
        """Nouvelle position du curseur pour la touche `c` (None si ce
        n'est pas une touche de déplacement) : flèches (Maj : 8 cases),
        Tab / Maj-Tab : monstre ou objet suivant / précédent."""
        steps = {curses.KEY_LEFT: (-1, 0), curses.KEY_RIGHT: (1, 0),
                 curses.KEY_UP: (0, -1), curses.KEY_DOWN: (0, 1),
                 curses.KEY_SLEFT: (-8, 0), curses.KEY_SRIGHT: (8, 0),
                 curses.KEY_SR: (0, -8), curses.KEY_SF: (0, 8)}
        x, y = cursor
        if c in steps:
            dx, dy = steps[c]
            return (min(max(x + dx, 0), max(view.width - 1, 0)),
                    min(max(y + dy, 0), max(len(view.grid) - 1, 0)))
        if c in ("\t", curses.KEY_BTAB):
            points = view.points()
            if not points:
                return cursor
            key = (y, x)
            if c == "\t":
                return next((p for p in points if (p[1], p[0]) > key),
                            points[0])
            return next((p for p in reversed(points) if (p[1], p[0]) < key),
                        points[-1])
        return None

    def legend(self, y, x=1):
        items = [("|", "wall", "mur"), ("+", "door", "porte"),
                 ("}", "water", "eau"), ("L", "lava", "lave"),
                 ("F", "bars", "barreaux"), ("<>", "stair", "escaliers"),
                 ("Z", "monster", "monstre"),
                 ("Z", "invisible", "invisible"),
                 ("(", "object", "objet"), (".", "dark", "sombre")]
        for c, kind, label in items:
            attr = curses.A_DIM if kind == "dark" else \
                self.cell_attr.get(kind, 0)
            self.put(y, x, c, attr)
            self.put(y, x + len(c) + 1, label)
            x += len(c) + len(label) + 3

    def show_level(self, section, level):
        i, view, cursor = 0, None, None
        while True:
            path = level.parts[i]
            if view is None:
                view = parse_lua(path)
                cursor = self.start_cursor(view)
            part = f"niveau {i + 1}/{len(level.parts)} : " \
                if level.split else ""
            y = self.header(f"{section.name} / {level.name}")
            self.put(y, 1, f"{part}{rel(path)}", curses.A_BOLD)
            self.put(y + 1, 1, view.desc)
            self.put(y + 2, 1, view.describe(*cursor), self.section)
            y = self.draw_map(y + 4, 1, view, cursor)
            self.legend(y + 1)
            nav = "Page↑↓ niveau   " if level.split else ""
            self.footer(f"flèches curseur   Tab monstre ou objet suivant   "
                        f"{nav}p jouer   i installer   x supprimer   "
                        "q retour")
            c = self.key(wake=True)
            moved = self.move_cursor(c, cursor, view)
            if moved:
                cursor = moved
            elif c in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                n = i + (1 if c == curses.KEY_NPAGE else -1)
                if 0 <= n < len(level.parts):
                    i, view = n, None
            elif c in ("p", "i", "x"):
                return c
            elif c in BACK or c in ENTER:
                return "q"

    def compare(self, name):
        """Compare la conversion enregistrée de `name` à une conversion
        avec les options actuelles (non enregistrée)."""
        low = name.lower()
        d = wad_dir(self.wad)
        saved = [lv for s in converted_levels(os.path.dirname(d))
                 if s.path == d for lv in s.levels if lv.name == low]
        if not saved:
            self.message(f"{name} n'a pas encore été convertie")
            return
        split = self.opts["parts"] != "1"
        old = next((lv for lv in saved if lv.split == split), saved[0])
        conv = load_meta(d).get("levels", {}).get(os.path.basename(old.path))
        old_args = " ".join(conv["args"]) + (
            f" -n {conv['parts']}" if conv["parts"] != "1" else "") \
            if conv else "(options inconnues)"
        tmp = tempfile.mkdtemp(prefix="doom2nethack-")
        try:
            self.status(f"Conversion de {name} avec les options actuelles...")
            ok, lines = run_conversion(self.wad, name, self.opts, tmp)
            if not ok:
                self.pager(f"conversion de {name} : ÉCHEC",
                           [(line, self.error) for line in lines])
                return
            new = converted_levels(tmp)[0].levels[0]
            args = conversion_args(self.opts)
            new_args = " ".join(args) + \
                (f" -n {self.opts['parts']}" if split else "")
            key = self.compare_view(name, [
                ("conversion enregistrée", old_args, old.parts),
                ("options actuelles", new_args, new.parts)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if key == "g":
            self.convert([name])

    def compare_view(self, name, sides):
        """Deux conversions côte à côte (l'une après l'autre si l'écran est
        trop étroit), avec un même curseur ; retourne "g" pour garder la
        seconde, ou "q"."""
        i, shown, views, cursor = 0, 0, None, None
        n = max(len(parts) for *_, parts in sides)
        while True:
            if views is None:
                views = [parse_lua(parts[min(i, len(parts) - 1)])
                         for *_, parts in sides]
                cursor = cursor or self.start_cursor(views[0])
            w = self.scr.getmaxyx()[1]
            width = max(v.width for v in views) + 3
            both = w >= 2 * width + 1
            y = self.header(f"comparaison de {name}")
            cols = [(0, 1), (1, width + 1)] if both else [(shown, 1)]
            for k, x in cols:
                label, args, parts = sides[k]
                view = views[k]
                part = f" (niveau {min(i, len(parts) - 1) + 1}/" \
                    f"{len(parts)})" if n > 1 else ""
                cut = width - 2 if both else w - 2
                self.put(y, x, f"{'AB'[k]} : {label}{part}"[:cut],
                         curses.A_BOLD)
                self.put(y + 1, x, args[:cut])
                self.put(y + 2, x, view.desc[:cut])
                self.put(y + 3, x, view.describe(*cursor)[:cut],
                         self.section)
                end = self.draw_map(y + 5, x, view, cursor)
            self.legend(end + 1)
            nav = "Page↑↓ niveau   " if n > 1 else ""
            other = "Espace A/B   " if not both else ""
            self.footer(f"flèches curseur   Tab monstre ou objet suivant   "
                        f"{nav}{other}g garder B (remplace A)   q retour")
            c = self.key(wake=True)
            moved = self.move_cursor(c, cursor, views[shown if not both
                                                      else 0])
            if moved:
                cursor = moved
            elif c in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                m = i + (1 if c == curses.KEY_NPAGE else -1)
                if 0 <= m < n:
                    i, views = m, None
            elif c == " ":
                shown = 1 - shown
            elif c == "g":
                return c
            elif c in BACK:
                return "q"

    def install(self, section, level):
        if not level.split:
            if not os.path.isdir(HACKDIR):
                self.message(f"HACKDIR introuvable : {HACKDIR}")
                return
            if not self.confirm(f"Copier {level.name}.lua dans {HACKDIR} ?"):
                return
            shutil.copy(level.path, HACKDIR)
            self.pager("installation", INSTALL_TEXT.format(
                name=level.name, hackdir=HACKDIR,
                nethack=NETHACK).splitlines())
            return
        conv = load_meta(section.path).get("levels", {}).get(level.name)
        wad = section.wad
        if not conv or not wad or not os.path.isfile(wad):
            self.message("Branche convertie hors du menu : l'installer avec "
                         "convertDoom2Nethack.sh -n ...")
            return
        self.shell([SCRIPT, "-n", conv["parts"], *conv["args"], wad,
                    level.name.upper()])

    def play(self, section, level):
        """Lance NetHack en mode wizard sur le niveau (d2n/play.py)."""
        state = install_state(level, branches=declared_branches())
        if state != "installé":
            if level.split:
                self.message(f"Branche {state or 'non installée'} : "
                             "l'installer d'abord (i)")
                return
            if not os.path.isdir(HACKDIR):
                self.message(f"HACKDIR introuvable : {HACKDIR}")
                return
            if not self.confirm(f"Copier {level.name}.lua dans {HACKDIR} "
                                "et lancer NetHack ?"):
                return
            shutil.copy(level.path, HACKDIR)
        if not os.access(NETHACK, os.X_OK):
            self.message(f"NetHack introuvable : {NETHACK}")
            return
        name = os.path.basename(level.parts[0])[:-4]
        curses.endwin()
        try:
            error = play(NETHACK, HACKDIR, name, level.split)
        except OSError as e:
            error = str(e)
        self.redraw()
        if error:
            self.message(f"NetHack : {error}")

    def redraw(self):
        """Reprend l'écran après un programme lancé hors de curses."""
        self.scr.clear()
        self.scr.refresh()

    def shell(self, cmd):
        """Lance une commande dans le terminal, hors de curses."""
        curses.endwin()
        print("$ " + " ".join(shlex.quote(c) for c in cmd), flush=True)
        env = dict(os.environ, HACKDIR=HACKDIR, NETHACK=NETHACK,
                   NETHACK_SRC=NETHACK_SRC)
        try:
            subprocess.run(cmd, env=env)
            input("\nEntrée pour revenir au menu...")
        except (OSError, KeyboardInterrupt, EOFError) as e:
            print(e)
        self.redraw()

    def choose_wad(self):
        """Explorateur de fichiers, avec les WAD récents en tête ; retourne
        True si un WAD est choisi."""
        if self.wad:
            d = os.path.dirname(self.wad)
        else:
            d = WAD_DIR if os.path.isdir(WAD_DIR) else os.getcwd()
        came_from = None
        while True:
            try:
                entries = sorted(os.listdir(d), key=str.lower)
            except OSError as e:
                self.message(f"Erreur : {e}")
                d = os.path.dirname(d)
                continue
            dirs = [e for e in entries if not e.startswith(".")
                    and os.path.isdir(os.path.join(d, e))]
            wads = [e for e in entries if e.lower().endswith(".wad")
                    and os.path.isfile(os.path.join(d, e))]
            recent = recent_wads()
            rows, paths = [], []
            if recent:
                rows.append(self.group_row("WAD récents"))
                paths.append(None)
                for w in recent:
                    rows.append((f"◆ {rel(w)}", True, self.theme["accent"]))
                    paths.append(w)
                rows.append(("", False, 0))
                paths.append(None)
            rows.append(self.group_row("Répertoire", d))
            paths.append(None)
            first = len(rows)
            rows += [("▲ ../", True, self.theme["dim"])] + \
                [(f"▸ {e}/", True, self.theme["label"]) for e in dirs] + \
                [(f"◆ {e}", True, self.theme["accent"]) for e in wads]
            paths += [os.path.normpath(os.path.join(d, e))
                      for e in ["..", *dirs, *wads]]
            if came_from in paths[first:]:
                sel = first + paths[first:].index(came_from)
            elif self.wad in paths[first:]:
                sel = first + paths[first:].index(self.wad)
            else:
                sel = first + 1 + len(dirs) if wads else first
            key, sel = self.menu(
                self.tx("ecran_wad"), rows, sel,
                "Entrée ouvrir   / saisir un chemin   w répertoire des WAD   "
                "x oublier un WAD récent   q annuler", keys="/wx")
            if key == "q":
                return False
            came_from = None
            if key == "w":
                if os.path.isdir(WAD_DIR):
                    d = WAD_DIR
                else:
                    self.message(f"Répertoire des WAD introuvable : {WAD_DIR}")
                continue
            if key == "x":
                if sel < first:
                    forget_wad(paths[sel])
                continue
            if key == "/":
                text = self.prompt("Chemin (Tab : compléter) :",
                                   d.rstrip("/") + "/",
                                   lambda t: complete_path(t, d))
                if not text:
                    continue
                p = os.path.normpath(os.path.join(d,
                                                  os.path.expanduser(text)))
                if not os.path.exists(p):
                    self.message(f"Introuvable : {p}")
                    continue
            else:
                p = paths[sel]
            if os.path.isdir(p):
                if sel == first and key != "/":         # ../
                    came_from = d
                d = p
                continue
            try:
                if not Wad(p).level_names():
                    raise WadError("aucun niveau dans ce WAD")
            except (WadError, OSError) as e:
                self.message(f"Erreur : {e}")
                came_from = p
                continue
            self.wad = p
            remember_wad(p)
            return True

USAGE = f"""\
Usage : Doom2Nethack.py [--theme NOM] [--sans-souris] [WAD]

Menu interactif : conversion des cartes du WAD (défaut : le dernier
utilisé) et niveaux déjà convertis, rangés dans out/<WAD>/.
Un WAD introuvable est cherché dans WAD_DIR ({WAD_DIR}).

  --theme NOM     couleurs : {", ".join(THEME_NAMES)} (défaut : auto, qui
                  suit la langue de NetHack : cyber pour fr@cyber)
  --sans-souris   garder la sélection de texte du terminal à la souris

La variable d'environnement NO_COLOR désactive les couleurs."""


def parse_args(argv):
    """Arguments de la ligne de commande : (WAD ou None, thème, souris) ;
    ValueError si un argument est invalide."""
    wad, theme, mouse = None, "auto", True
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--theme" and args:
            theme = args.pop(0)
        elif a.startswith("--theme="):
            theme = a.split("=", 1)[1]
        elif a == "--sans-souris":
            mouse = False
        elif a.startswith("-") or wad:
            raise ValueError(f"argument inattendu : {a}")
        else:
            wad = a
    if theme not in THEME_NAMES:
        raise ValueError(f"thème inconnu : {theme} "
                         f"({', '.join(THEME_NAMES)})")
    return wad, theme, mouse


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in argv):
        print(USAGE)
        return 0
    try:
        wad, theme, mouse = parse_args(argv)
    except ValueError as e:
        print(f"Doom2Nethack : {e} (voir --help)", file=sys.stderr)
        return 1
    wad = os.path.abspath(find_wad(wad)) if wad else last_wad()
    if wad and not os.path.isfile(wad):
        print(f"Doom2Nethack : WAD introuvable : {wad}", file=sys.stderr)
        return 1
    if wad:
        remember_wad(wad)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Doom2Nethack : un terminal est nécessaire",
              file=sys.stderr)
        return 1
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(lambda scr: App(scr, wad, theme, mouse).run())
    return 0
