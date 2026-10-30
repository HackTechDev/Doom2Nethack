"""Menu interactif (curses) : conversion des cartes d'un WAD et niveaux déjà
convertis.

Les niveaux convertis sont rangés dans out/<WAD sans .wad>/ : un fichier
<carte>.lua par niveau simple, un répertoire <carte>/ par niveau découpé en
branche.  Le fichier doom2nethack.json de ce répertoire garde le chemin du
WAD et les options de chaque conversion, pour réinstaller une branche avec
convertDoom2Nethack.sh."""

import curses
import json
import locale
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass

from .wad import Wad, WadError

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT, "out")
CLI = os.path.join(PROJECT, "doom2nethack.py")
SCRIPT = os.path.join(PROJECT, "convertDoom2Nethack.sh")
HACKDIR = os.environ.get("HACKDIR", os.path.expanduser(
    "~/nh/install/games/lib/nethackdir"))
NETHACK = os.environ.get("NETHACK", os.path.join(
    os.path.dirname(os.path.dirname(HACKDIR)), "nethack"))
META = "doom2nethack.json"
LAST_WAD = os.path.join(OUT_DIR, ".last-wad")

DEFAULT_OPTS = {"mode": "raster", "parts": "1", "skill": "medium",
                "hazards": "none", "dark": 144}
# Touche -> (option, valeurs parcourues en boucle).
CYCLES = {
    "m": ("mode", ["raster", "rooms"]),
    "n": ("parts", ["1", "2", "3", "4", "auto"]),
    "s": ("skill", ["easy", "medium", "hard"]),
    "h": ("hazards", ["none", "water", "lava"]),
    "l": ("dark", [144, 0]),
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
    return ["--mode", opts["mode"], "--skill", opts["skill"],
            "--hazards", opts["hazards"], "--dark-below", str(opts["dark"])]


def run_conversion(wad, mapname, opts, outdir=OUT_DIR):
    """Convertit une carte avec doom2nethack.py.  Retourne (réussite,
    lignes affichées par la commande)."""
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
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        meta = load_meta(d)
        meta["wad"] = os.path.abspath(wad)
        meta.setdefault("levels", {})[key] = {"parts": opts["parts"],
                                              "args": args}
        save_meta(d, meta)
    return r.returncode == 0, (r.stdout + r.stderr).splitlines()


def delete_level(section, level):
    if level.split:
        shutil.rmtree(level.path)
    else:
        os.remove(level.path)
    meta = load_meta(section.path)
    if meta.get("levels", {}).pop(os.path.basename(level.path), None):
        save_meta(section.path, meta)


def summary_lines(results, error_attr=0):
    """Résumé de plusieurs conversions : (carte, réussite, lignes)."""
    out = []
    for name, ok, lines in results:
        if ok:
            out.append((f"{name:<8} ok", curses.A_BOLD))
            out += [f"    {line.strip()}" for line in lines
                    if re.match(r"\s*(\w+ : carte|info|attention)", line)]
        else:
            out.append((f"{name:<8} ÉCHEC", error_attr | curses.A_BOLD))
            out += [(f"    {line}", error_attr) for line in lines[-3:]]
    return out


def lua_summary(path):
    """(description, carte avec les escaliers) d'un niveau .lua."""
    with open(path) as f:
        text = f.read()
    m = re.search(r"map = \[\[\n(.*?)\n\]\]", text, re.S)
    grid = [list(row) for row in m.group(1).split("\n")] if m else []
    stairs = [("<", x, y) for x, y in re.findall(
        r'des\.stair\("up", (\d+),(\d+)\)', text)]
    stairs += [("<", x, y) for x, y in re.findall(
        r"region = \{(\d+),(\d+),", text)]
    stairs += [(">", x, y) for x, y in re.findall(
        r'des\.stair\("down", (\d+),(\d+)\)', text)]
    for c, x, y in stairs:
        x, y = int(x), int(y)
        if y < len(grid) and x < len(grid[y]):
            grid[y][x] = c
    width = max((len(r) for r in grid), default=0)
    desc = (f"carte {width}x{len(grid)}, "
            f"{text.count('des.door(')} porte(s), "
            f"{text.count('des.monster(')} monstre(s), "
            f"{text.count('des.object(')} objet(s)")
    return desc, ["".join(r) for r in grid]


def rel(path):
    """Chemin relatif au projet quand il s'y trouve."""
    r = os.path.relpath(path, PROJECT)
    return path if r.startswith("..") else r


def last_wad():
    try:
        with open(LAST_WAD) as f:
            p = f.read().strip()
        return p if os.path.isfile(p) else None
    except OSError:
        return None


def remember_wad(path):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(LAST_WAD, "w") as f:
        f.write(path + "\n")


# --- interface --------------------------------------------------------------

UP = (curses.KEY_UP, "k")
DOWN = (curses.KEY_DOWN, "j")
ENTER = ("\n", "\r", curses.KEY_ENTER)
BACK = ("q", "Q", "\x1b")


class App:
    def __init__(self, scr, wad=None):
        self.scr = scr
        self.wad = wad
        self.opts = dict(DEFAULT_OPTS)
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
        self.put(0, 0, f" Doom2NetHack : {title}".ljust(w), self.title)
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

    def key(self):
        while True:
            c = self.scr.get_wch()
            if c != curses.KEY_RESIZE:
                return c

    def message(self, text):
        self.footer(f"{text}  (une touche pour continuer)")
        self.key()

    def confirm(self, question):
        self.footer(f"{question} [o/N]")
        return self.key() in ("o", "O", "y", "Y")

    # listes

    def menu(self, title, rows, sel=0, footer="", keys="", info=()):
        """`rows` : (texte, sélectionnable, attribut).  Retourne (touche,
        index de la ligne choisie) ; touche "\\n" pour Entrée, "q" pour
        retour."""
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
            c = self.key()
            pos = ok.index(sel)
            if c in UP:
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
            c = self.key()
            if c in UP:
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
            rows = [("Convertir une carte du WAD", True, 0),
                    ("Niveaux convertis", True, 0),
                    ("Choisir un autre fichier WAD", True, 0),
                    ("Quitter", True, 0)]
            key, sel = self.menu("menu principal", rows, sel,
                                 "↑↓ choisir   Entrée valider   q quitter")
            if key == "q" or sel == 3:
                return
            (self.convert_menu, self.converted_menu, self.choose_wad)[sel]()

    def opts_line(self):
        o = self.opts
        dark = f"sombre si lumière < {o['dark']}" if o["dark"] \
            else "tout éclairé"
        return (f"Options : mode {o['mode']} · découpage {o['parts']} · "
                f"difficulté {o['skill']} · sols {o['hazards']} · {dark}")

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
                star = "*" if name in marked else " "
                rows.append((f"{star} {name:<8} {', '.join(marks)}", True,
                             self.done if marks else 0))
            count = f"{len(marked)} carte(s) cochée(s) · " if marked else ""
            key, sel = self.menu(
                "conversion", rows, sel,
                "Entrée convertir   Espace cocher   a tout cocher   q retour\n"
                "m mode   n découpage   s difficulté   h sols   l lumière",
                keys=" a" + "".join(CYCLES),
                info=[f"Destination : {rel(d)}/", self.opts_line(),
                      f"{count}{len(names)} carte(s) dans le WAD"])
            if key == "q":
                return
            if key == " ":
                marked ^= {names[sel]}
                sel = min(sel + 1, len(names) - 1)
            elif key == "a":
                marked = set() if len(marked) == len(names) else set(names)
            elif key in CYCLES:
                opt, values = CYCLES[key]
                i = values.index(self.opts[opt])
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
        """Convertit les cartes `names` ; retourne False si l'utilisateur
        annule avant la première conversion."""
        exist = [n for n in names if os.path.exists(self.target(n))]
        if exist:
            what = rel(self.target(exist[0])) if len(exist) == 1 \
                else f"{len(exist)} des {len(names)} cartes"
            if not self.confirm(f"{what} : déjà converti. Remplacer ?"):
                return False
        results = []
        self.scr.nodelay(True)
        try:
            for i, name in enumerate(names):
                self.progress(i, len(names), name, results)
                results.append((name, *run_conversion(self.wad, name,
                                                      self.opts)))
                if self.pressed_back():
                    break
        finally:
            self.scr.nodelay(False)
        if len(names) == 1:
            name, ok, lines = results[0]
            if not ok:
                lines = [(line, self.error) for line in lines]
            self.pager(f"conversion de {name}" + ("" if ok else " : ÉCHEC"),
                       lines)
            return True
        failed = sum(not ok for _, ok, _ in results)
        title = f"{len(results)} carte(s) convertie(s)"
        if failed:
            title += f", {failed} échec(s)"
        if len(results) < len(names):
            title += f", {len(names) - len(results)} abandonnée(s)"
        self.pager(title, summary_lines(results, self.error))
        return True

    def pressed_back(self):
        """Vrai si q ou Échap a été pressé (en mode nodelay)."""
        try:
            while True:
                if self.scr.get_wch() in BACK:
                    return True
        except curses.error:
            return False

    def progress(self, done, total, name, results):
        y = self.header("conversion en cours")
        w = self.scr.getmaxyx()[1]
        width = max(min(w - 20, 60), 10)
        fill = width * done // total
        self.put(y, 1, f"[{'#' * fill}{'.' * (width - fill)}] "
                 f"{done}/{total}", curses.A_BOLD)
        self.put(y + 2, 1, f"Conversion de {name}...")
        for k, (n, ok, _) in enumerate(results[-(self.rows_left(y + 4)):]):
            self.put(y + 4 + k, 3, f"{n:<8} {'ok' if ok else 'ÉCHEC'}",
                     self.done if ok else self.error)
        self.footer("q interrompre après la carte en cours")
        self.scr.refresh()

    def rows_left(self, y):
        return max(self.scr.getmaxyx()[0] - 1 - y, 1)

    def converted_menu(self):
        sel = 0
        while True:
            rows, entries = [], []
            for s in converted_levels():
                if rows:
                    rows.append(("", False, 0))
                wad = f"   ({rel(s.wad)})" if s.wad else ""
                rows.append((f"{s.name}{wad}", False, self.section))
                for lv in s.levels:
                    kind = f"branche de {len(lv.parts)} niveaux" \
                        if lv.split else "niveau simple"
                    rows.append((f"   {lv.name:<8} {kind}", True, 0))
                    entries.append((s, lv))
            if not entries:
                self.message(f"Aucun niveau converti dans {rel(OUT_DIR)}/")
                return
            index = {i: e for i, e in zip(
                (i for i, r in enumerate(rows) if r[1]), entries)}
            key, sel = self.menu(
                "niveaux convertis", rows, sel,
                "Entrée voir   i installer dans NetHack   x supprimer   "
                "q retour", keys="ix")
            if key == "q":
                return
            s, lv = index[sel]
            if key == "\n":
                key = self.show_level(s, lv)
            if key == "i":
                self.install(s, lv)
            elif key == "x" and self.confirm(f"Supprimer {rel(lv.path)} ?"):
                delete_level(s, lv)

    def show_level(self, section, level):
        i = 0
        while True:
            path = level.parts[i]
            desc, grid = lua_summary(path)
            part = f"niveau {i + 1}/{len(level.parts)} : " \
                if level.split else ""
            lines = [(f"{part}{rel(path)}", curses.A_BOLD), desc, "",
                     *grid]
            nav = "←→ niveau   " if level.split else ""
            key = self.pager(
                f"{section.name} / {level.name}", lines,
                f"{nav}↑↓ défiler   i installer   x supprimer   q retour",
                keys=("i", "x", curses.KEY_LEFT, curses.KEY_RIGHT))
            if key == curses.KEY_LEFT:
                i = max(i - 1, 0)
            elif key == curses.KEY_RIGHT:
                i = min(i + 1, len(level.parts) - 1)
            else:
                return key

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

    def shell(self, cmd):
        """Lance une commande dans le terminal, hors de curses."""
        curses.endwin()
        print("$ " + " ".join(shlex.quote(c) for c in cmd), flush=True)
        try:
            subprocess.run(cmd)
            input("\nEntrée pour revenir au menu...")
        except (OSError, KeyboardInterrupt, EOFError) as e:
            print(e)
        self.scr.refresh()

    def choose_wad(self):
        """Explorateur de fichiers ; retourne True si un WAD est choisi."""
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
            names = ["..", *dirs, *wads]
            rows = [("../", True, 0)] + \
                [(f"{e}/", True, self.section) for e in dirs] + \
                [(e, True, curses.A_BOLD) for e in wads]
            if came_from in names:
                sel = names.index(came_from)
            elif self.wad and os.path.dirname(self.wad) == d and \
                    os.path.basename(self.wad) in names:
                sel = names.index(os.path.basename(self.wad))
            else:
                sel = 1 + len(dirs) if wads else 0
            key, sel = self.menu("choisir un fichier WAD", rows, sel,
                                 "Entrée ouvrir   q annuler",
                                 info=[f"Répertoire : {d}"])
            if key == "q":
                return False
            p = os.path.normpath(os.path.join(d, names[sel]))
            if os.path.isdir(p):
                came_from = os.path.basename(d) if names[sel] == ".." \
                    else None
                d = p
                continue
            try:
                if not Wad(p).level_names():
                    raise WadError("aucun niveau dans ce WAD")
            except (WadError, OSError) as e:
                self.message(f"Erreur : {e}")
                came_from = names[sel]
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
