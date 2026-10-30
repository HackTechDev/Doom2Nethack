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
from .tables import SYMBOLS
from .wad import Wad, WadError

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT, "out")
CLI = os.path.join(PROJECT, "doom2nethack.py")
SCRIPT = os.path.join(PROJECT, "convertDoom2Nethack.sh")
HACKDIR = os.environ.get("HACKDIR", os.path.expanduser(
    "~/nh/install/games/lib/nethackdir"))
NETHACK = os.environ.get("NETHACK", os.path.join(
    os.path.dirname(os.path.dirname(HACKDIR)), "nethack"))
NETHACK_SRC = os.environ.get("NETHACK_SRC",
                             "/home/sgond/app/Nethack500_Lubuntu2604")
DUNGEON_LUA = os.path.join(NETHACK_SRC, "dat", "dungeon.lua")
META = "doom2nethack.json"
RECENT_WADS = os.path.join(OUT_DIR, ".recent-wads.json")
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
    monsters: dict      # (x, y) -> (nom, invisible)
    objects: dict       # (x, y) -> (classe, nom)
    doors: int

    @property
    def width(self):
        return max((len(r) for r in self.grid), default=0)

    @property
    def desc(self):
        return (f"carte {self.width}x{len(self.grid)}, {self.doors} porte(s), "
                f"{len(self.monsters)} monstre(s), "
                f"{len(self.objects)} objet(s), {len(self.dark)} case(s) "
                f"sombre(s)")

    def cell(self, x, y):
        """(caractère, nature) de la case : escalier, monstre, objet, ou
        le terrain de la carte."""
        if (x, y) in self.stairs:
            return self.stairs[x, y], "stair"
        if (x, y) in self.monsters:
            name, invisible = self.monsters[x, y]
            return SYMBOLS.get(name, "M"), "invisible" if invisible \
                else "monster"
        if (x, y) in self.objects:
            return self.objects[x, y][0], "object"
        row = self.grid[y] if y < len(self.grid) else ""
        c = row[x] if x < len(row) else " "
        return c, TERRAIN.get(c, "floor")


TERRAIN = {"-": "wall", "|": "wall", " ": "rock", "+": "door", "#": "corridor",
           "}": "water", "L": "lava", "F": "bars", "S": "door"}


def parse_lua(path):
    with open(path) as f:
        text = f.read()
    m = re.search(r"map = \[\[\n(.*?)\n\]\]", text, re.S)
    grid = m.group(1).split("\n") if m else []
    stairs = {}
    for c, pattern in (("<", r'des\.stair\("up", (\d+),(\d+)\)'),
                       ("<", r"region = \{(\d+),(\d+),"),
                       (">", r'des\.stair\("down", (\d+),(\d+)\)')):
        for x, y in re.findall(pattern, text):
            stairs[int(x), int(y)] = c
    dark = set()
    for x1, y, x2 in re.findall(r"dark = dark \| selection\.area\((\d+),(\d+),"
                                r"(\d+),\d+\)", text):
        dark.update((x, int(y)) for x in range(int(x1), int(x2) + 1))
    monsters = {}
    for line in re.findall(r"des\.monster\(.*", text):
        m = re.search(r'id = "([^"]+)", x = (\d+), y = (\d+)', line)
        if m:
            monsters[int(m.group(2)), int(m.group(3))] = \
                (m.group(1), "invisible = 1" in line)
    objects = {(int(x), int(y)): (cls, name) for name, cls, x, y in
               re.findall(r'des\.object\(\{ id = "([^"]+)", class = "(.)", '
                          r'x = (\d+), y = (\d+)', text)}
    return LevelView(grid, dark, stairs, monsters, objects,
                     text.count("des.door("))


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

UP = (curses.KEY_UP,)
DOWN = (curses.KEY_DOWN,)
JOURNAL = "l"
ENTER = ("\n", "\r", curses.KEY_ENTER)
BACK = ("q", "Q", "\x1b")


class App:
    def __init__(self, scr, wad=None):
        self.scr = scr
        self.wad = wad
        self.opts = dict(DEFAULT_OPTS)
        self.jobs = Jobs()
        self.seen = 0               # dernière version de self.jobs affichée
        curses.curs_set(0)
        self.title = curses.A_REVERSE | curses.A_BOLD
        self.section = self.done = self.error = curses.A_BOLD
        if curses.has_colors():
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_YELLOW, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_RED, -1)
            self.section = curses.color_pair(1) | curses.A_BOLD
            self.done = curses.color_pair(2)
            self.error = curses.color_pair(3) | curses.A_BOLD
        # attributs de l'aperçu des cartes, par nature de case
        colors = {"door": curses.COLOR_YELLOW, "water": curses.COLOR_BLUE,
                  "lava": curses.COLOR_RED, "bars": curses.COLOR_CYAN,
                  "monster": curses.COLOR_RED, "invisible": curses.COLOR_RED,
                  "object": curses.COLOR_CYAN, "stair": curses.COLOR_MAGENTA}
        self.cell_attr = {k: curses.A_BOLD for k in colors}
        if curses.has_colors():
            for i, (k, color) in enumerate(colors.items(), 10):
                curses.init_pair(i, color, -1)
                self.cell_attr[k] = curses.color_pair(i)
        for k in ("monster", "stair", "invisible"):
            self.cell_attr[k] |= curses.A_BOLD
        self.cell_attr["invisible"] |= curses.A_UNDERLINE

    # dessin

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            n = w - x - (1 if y == h - 1 else 0)    # pas la dernière case
            try:
                self.scr.addnstr(y, x, text, n, attr)
            except curses.error:
                pass

    def header(self, title):
        self.scr.erase()
        w = self.scr.getmaxyx()[1]
        self.seen = self.jobs.version
        status = self.jobs_status()
        self.put(0, 0, f" Doom2NetHack : {title}".ljust(w), self.title)
        if status:
            self.put(0, max(w - len(status) - 1, len(title) + 18), status,
                     self.title)
        self.put(1, 1, "Fichier WAD : ", curses.A_BOLD)
        self.put(1, 15, rel(self.wad) if self.wad else "(aucun)")
        return 3

    def footer(self, text, attr=curses.A_REVERSE):
        """Barre du bas (plusieurs lignes séparées par \\n)."""
        h, w = self.scr.getmaxyx()
        lines = text.split("\n")
        for k, line in enumerate(lines):
            self.put(h - len(lines) + k, 0, f" {line}".ljust(w), attr)

    def status(self, text):
        self.footer(text)
        self.scr.refresh()

    def jobs_status(self):
        j = self.jobs
        if j.active():
            width = 10
            fill = width * j.done // max(j.total, 1)
            name = j.current[1] if j.current else ""
            return (f"[{'#' * fill}{'.' * (width - fill)}] "
                    f"{j.done}/{j.total} {name} ")
        if j.total:
            failed = f", {j.failed} échec(s)" if j.failed else ""
            return f"{j.done} conversion(s) terminée(s){failed} · l journal "
        return ""

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

    def message(self, text):
        self.footer(f"{text}  (une touche pour continuer)")
        self.key()

    def confirm(self, question):
        self.footer(f"{question} [o/N]")
        return self.key() in ("o", "O", "y", "Y")

    # listes

    def menu(self, title, rows, sel=0, footer="", keys="", info=(),
             live=False):
        """`rows` : (texte, sélectionnable, attribut).  Retourne (touche,
        index de la ligne choisie) ; touche "\\n" pour Entrée, "q" pour
        retour.  Avec `live`, retourne "refresh" quand l'état des
        conversions change, pour que l'appelant refasse ses lignes."""
        ok = [i for i, r in enumerate(rows) if r[1]]
        if not ok:
            return "q", None
        if sel not in ok:
            sel = next((i for i in ok if i >= (sel or 0)), ok[-1])
        top = 0
        while True:
            y0 = self.header(title)
            for i, line in enumerate(info):
                self.put(y0 + i, 1, line)
            y0 += len(info) + bool(info)
            h, w = self.scr.getmaxyx()
            n = max(h - 1 - footer.count("\n") - y0, 1)
            top = min(max(top, sel - n + 1), sel)
            if top == sel and sel > 0 and not rows[sel - 1][1]:
                top = sel - 1               # garder le titre de section
            for k, (text, selectable, attr) in enumerate(rows[top:top + n]):
                if top + k == sel:
                    self.put(y0 + k, 1, f" {text}".ljust(w - 2),
                             attr | curses.A_REVERSE)
                else:
                    self.put(y0 + k, 1, f" {text}", attr)
            self.footer(footer)
            c = self.key(wake=True)
            pos = ok.index(sel)
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
            n = max(h - 1 - y0, 1)
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
            if c == JOURNAL and JOURNAL not in keys:
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

    def run(self):
        if not self.wad:
            self.choose_wad()
        sel = 0
        while True:
            branches = declared_branches()
            rows = [("Convertir une carte du WAD", True, 0),
                    ("Niveaux convertis", True, 0),
                    ("Journal des conversions", True, 0),
                    ("Choisir un autre fichier WAD", True, 0),
                    (f"Retirer les branches Doom de NetHack "
                     f"({len(branches)} déclarée(s))", bool(branches), 0
                     if branches else curses.A_DIM),
                    ("Quitter", True, 0)]
            key, sel = self.menu("menu principal", rows, sel,
                                 "↑↓ choisir   Entrée valider   "
                                 "l journal   q quitter")
            if sel == 4 and key == "\n":
                self.shell([SCRIPT, "--restore"])
                continue
            if key == "q" or sel == 5:
                n = self.jobs.active()
                if not n or self.confirm(f"{n} conversion(s) en cours ou en "
                                         "attente seront abandonnées. "
                                         "Quitter ?"):
                    self.jobs.stop()
                    return
                continue
            (self.convert_menu, self.converted_menu, self.journal,
             self.choose_wad)[sel]()

    def opts_lines(self):
        o = self.opts
        dark = f"sombre si lumière < {o['dark']}" if o["dark"] \
            else "tout éclairé"
        rooms = f"{o['rooms']} salles" if o["rooms"] else "salles auto"
        return [f"Options : mode {o['mode']} · découpage {o['parts']} · "
                f"difficulté {o['skill']} · sols {o['hazards']} · {dark}",
                f"          carte {o['width']}x{o['height']} "
                f"{'à échelle uniforme' if o['keep_aspect'] else 'étirée'} · "
                f"couverture {o['coverage']} · {rooms}"]

    def options_menu(self):
        sel = 0
        while True:
            rows = [(f"{label:<18} {option_text(k, self.opts[k]):<18} {help}",
                     True, 0 if self.opts[k] == DEFAULT_OPTS[k]
                     else curses.A_BOLD) for k, label, _, help in OPTIONS]
            rows += [("", False, 0), ("Valeurs par défaut", True, 0)]
            key, sel = self.menu("options de conversion", rows, sel,
                                 "Entrée changer   q retour",
                                 info=["En gras : valeur modifiée."])
            if key == "q":
                return
            if sel >= len(OPTIONS):
                self.opts = dict(DEFAULT_OPTS)
                continue
            k, label, spec, _ = OPTIONS[sel]
            if isinstance(spec, list):
                i = spec.index(self.opts[k])
                self.opts[k] = spec[(i + 1) % len(spec)]
                continue
            text = self.prompt(f"{label} :", str(self.opts[k]))
            if text is not None:
                try:
                    self.opts[k] = parse_option(spec, text)
                except ValueError as e:
                    self.message(str(e))

    def prompt(self, label, value="", complete=None):
        """Saisie d'une ligne dans la barre du bas ; None si Échap.
        `complete(texte)` -> (texte complété, candidats) : complétion par
        Tab, les candidats s'affichant au-dessus de la saisie."""
        curses.curs_set(1)
        shown = []
        try:
            while True:
                h, w = self.scr.getmaxyx()
                text = f" {label} {value}"
                if shown:
                    line = "  ".join(shown)
                    self.put(h - 2, 0, f" {line}"[:w].ljust(w))
                self.put(h - 1, 0, text[-(w - 1):].ljust(w), curses.A_REVERSE)
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
            curses.curs_set(0)

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
            for name in names:
                low = name.lower()
                marks = []
                if os.path.isfile(os.path.join(d, f"{low}.lua")):
                    marks.append("converti")
                if os.path.isdir(os.path.join(d, low)):
                    marks.append("branche")
                state = self.jobs.state(self.wad, name)
                if state:
                    marks.append(state)
                star = "*" if name in marked else " "
                rows.append((f"{star} {name:<8} {', '.join(marks)}", True,
                             self.done if marks else 0))
            count = f"{len(marked)} carte(s) cochée(s) · " if marked else ""
            key, sel = self.menu(
                "conversion", rows, sel,
                "Entrée convertir   Espace cocher   a tout cocher   "
                "c comparer   q retour\n"
                "o options   m mode   n découpage   s difficulté   h sols",
                keys=" aoc" + "".join(CYCLES), live=True,
                info=[f"Destination : {rel(d)}/", *self.opts_lines(),
                      f"{count}{len(names)} carte(s) dans le WAD"])
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
                rows.append((f"{name:<8} {'ok   ' if ok else 'ÉCHEC'}  "
                             f"{os.path.basename(wad):<16} {carte}", True,
                             0 if ok else self.error))
            waiting = [f"   {n:<8} {self.jobs.state(w, n)}"
                       for w, n in self.jobs.queued()]
            info = ["Conversions en cours ou en attente :", *waiting] \
                if waiting else []
            if not rows:
                rows = [("(aucune conversion terminée)", True, 0)]
            key, sel = self.menu(
                "journal des conversions", rows, sel,
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
                wad = f"   ({rel(s.wad)})" if s.wad else ""
                rows.append((f"{s.name}{wad}", False, self.section))
                for lv in s.levels:
                    kind = f"branche de {len(lv.parts)} niveaux" \
                        if lv.split else "niveau simple"
                    state = install_state(lv, branches=branches)
                    attr = self.done if state == "installé" else \
                        curses.A_BOLD if state else 0
                    rows.append((f"   {lv.name:<8} {kind:<22} {state or ''}",
                                 True, attr))
                    entries.append((s, lv))
            if not entries:
                self.message(f"Aucun niveau converti dans {rel(OUT_DIR)}/")
                return
            index = {i: e for i, e in zip(
                (i for i, r in enumerate(rows) if r[1]), entries)}
            sel = next((i for i, (_, lv) in index.items()
                        if lv.path == current), sel)
            info = [f"Répertoire de jeu : {HACKDIR}",
                    "Branches Doom dans dungeon.lua : "
                    + (", ".join(branches) or "aucune")]
            key, sel = self.menu(
                "niveaux convertis", rows, sel,
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

    def draw_map(self, y, x, view):
        """Dessine la carte en couleurs ; retourne la ligne suivante."""
        for j in range(len(view.grid)):
            for i in range(view.width):
                c, kind = view.cell(i, j)
                attr = self.cell_attr.get(kind, 0)
                if (i, j) in view.dark and kind in ("floor", "corridor",
                                                    "door", "wall"):
                    attr |= curses.A_DIM
                if c != " ":
                    self.put(y + j, x + i, c, attr)
        return y + len(view.grid)

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
        i = 0
        while True:
            path = level.parts[i]
            view = parse_lua(path)
            part = f"niveau {i + 1}/{len(level.parts)} : " \
                if level.split else ""
            y = self.header(f"{section.name} / {level.name}")
            self.put(y, 1, f"{part}{rel(path)}", curses.A_BOLD)
            self.put(y + 1, 1, view.desc)
            y = self.draw_map(y + 3, 1, view)
            self.legend(y + 1)
            nav = "←→ niveau   " if level.split else ""
            self.footer(f"{nav}p jouer   i installer   x supprimer   "
                        "q retour")
            c = self.key(wake=True)
            if c == curses.KEY_LEFT:
                i = max(i - 1, 0)
            elif c == curses.KEY_RIGHT:
                i = min(i + 1, len(level.parts) - 1)
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
        trop étroit) ; retourne "g" pour garder la seconde, ou "q"."""
        i, shown = 0, 0
        n = max(len(parts) for *_, parts in sides)
        while True:
            views = [parse_lua(parts[min(i, len(parts) - 1)])
                     for *_, parts in sides]
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
                end = self.draw_map(y + 4, x, view)
            self.legend(end + 1)
            nav = "←→ niveau   " if n > 1 else ""
            other = "Tab A/B   " if not both else ""
            self.footer(f"{nav}{other}g garder B (remplace A)   q retour")
            c = self.key(wake=True)
            if c == curses.KEY_LEFT:
                i = max(i - 1, 0)
            elif c == curses.KEY_RIGHT:
                i = min(i + 1, n - 1)
            elif c == "\t":
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
        d = os.path.dirname(self.wad) if self.wad else os.getcwd()
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
                rows.append(("WAD récents", False, self.section))
                paths.append(None)
                for w in recent:
                    rows.append((f"  {rel(w)}", True, curses.A_BOLD))
                    paths.append(w)
                rows.append(("", False, 0))
                paths.append(None)
            rows.append((f"Répertoire {d}", False, self.section))
            paths.append(None)
            first = len(rows)
            rows += [("  ../", True, 0)] + \
                [(f"  {e}/", True, 0) for e in dirs] + \
                [(f"  {e}", True, curses.A_BOLD) for e in wads]
            paths += [os.path.normpath(os.path.join(d, e))
                      for e in ["..", *dirs, *wads]]
            if came_from in paths[first:]:
                sel = first + paths[first:].index(came_from)
            elif self.wad in paths[first:]:
                sel = first + paths[first:].index(self.wad)
            else:
                sel = first + 1 + len(dirs) if wads else first
            key, sel = self.menu(
                "choisir un fichier WAD", rows, sel,
                "Entrée ouvrir   / saisir un chemin   x oublier un WAD "
                "récent   q annuler", keys="/x")
            if key == "q":
                return False
            came_from = None
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

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print("Usage : menuDoom2Nethack.py [WAD]\n\nMenu interactif : "
              "conversion des cartes du WAD (défaut : le dernier utilisé)\n"
              "et niveaux déjà convertis, rangés dans out/<WAD>/.")
        return 0
    wad = os.path.abspath(argv[0]) if argv else last_wad()
    if wad and not os.path.isfile(wad):
        print(f"menuDoom2Nethack : WAD introuvable : {wad}", file=sys.stderr)
        return 1
    if wad:
        remember_wad(wad)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("menuDoom2Nethack : un terminal est nécessaire",
              file=sys.stderr)
        return 1
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(lambda scr: App(scr, wad).run())
    return 0
