"""Lecture des niveaux Doom / Doom II au format WAD « vanilla »."""

import os
import re
import struct
from dataclasses import dataclass, field

# Répertoire qui contient le projet.
_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
# Répertoire des WAD : un WAD introuvable depuis le répertoire courant y est
# cherché (défaut : ../Doom/Wad, à côté du projet).
WAD_DIR = os.environ.get("WAD_DIR", os.path.join(_PARENT, "Doom", "Wad"))
# Éditeur Yadex, dont le test.wad sert aux tests (défaut : ../YadexEditor).
YADEX_DIR = os.environ.get("YADEX_DIR", os.path.join(_PARENT, "YadexEditor"))

# Lumps qui suivent le marqueur d'un niveau (MAP01, E1M1...).
LEVEL_LUMPS = {
    "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS",
    "NODES", "SECTORS", "REJECT", "BLOCKMAP", "BEHAVIOR",
}
LEVEL_NAME_RE = re.compile(r"^(E\dM\d|MAP\d\d)$")

NO_SIDEDEF = 0xFFFF


def find_wad(path, wad_dir=None):
    """Chemin du WAD `path` : tel quel s'il existe, sinon dans le répertoire
    des WAD s'il s'y trouve."""
    wad_dir = WAD_DIR if wad_dir is None else wad_dir
    path = os.path.expanduser(path)
    if os.path.isfile(path) or os.path.isabs(path):
        return path
    candidate = os.path.join(wad_dir, path)
    return candidate if os.path.isfile(candidate) else path


@dataclass
class Vertex:
    x: int
    y: int


@dataclass
class Linedef:
    v1: int
    v2: int
    flags: int
    special: int
    tag: int
    right: int          # numéro de sidedef, NO_SIDEDEF si absent
    left: int


@dataclass
class Sidedef:
    sector: int


@dataclass
class Sector:
    floor: int
    ceiling: int
    light: int
    special: int
    tag: int


@dataclass
class Thing:
    x: int
    y: int
    angle: int
    type: int
    flags: int


@dataclass
class Level:
    name: str
    vertices: list = field(default_factory=list)
    linedefs: list = field(default_factory=list)
    sidedefs: list = field(default_factory=list)
    sectors: list = field(default_factory=list)
    things: list = field(default_factory=list)

    def side_sector(self, sidedef):
        """Secteur d'un sidedef, ou None."""
        if sidedef == NO_SIDEDEF or sidedef >= len(self.sidedefs):
            return None
        sec = self.sidedefs[sidedef].sector
        return sec if 0 <= sec < len(self.sectors) else None


class WadError(Exception):
    pass


class Wad:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        if len(self.data) < 12:
            raise WadError(f"{path} : fichier trop court")
        ident, count, offset = struct.unpack_from("<4sii", self.data, 0)
        if ident not in (b"IWAD", b"PWAD"):
            raise WadError(f"{path} : en-tête WAD invalide")
        if offset < 0 or offset + 16 * count > len(self.data):
            raise WadError(f"{path} : répertoire hors du fichier")
        self.lumps = []
        for i in range(count):
            pos, size, raw = struct.unpack_from("<ii8s", self.data,
                                                offset + 16 * i)
            name = raw.split(b"\0", 1)[0].decode("ascii", "replace").upper()
            self.lumps.append((name, pos, size))

    def level_names(self):
        return [n for n, _, _ in self.lumps if LEVEL_NAME_RE.match(n)]

    def _level_lumps(self, name):
        for i, (n, _, _) in enumerate(self.lumps):
            if n == name.upper():
                found = {}
                for n2, pos, size in self.lumps[i + 1:]:
                    if n2 not in LEVEL_LUMPS:
                        break
                    found[n2] = self.data[pos:pos + size]
                return found
        raise WadError(f"niveau {name} introuvable")

    def load_level(self, name):
        lumps = self._level_lumps(name)
        if "BEHAVIOR" in lumps:
            raise WadError(f"{name} : format Hexen non supporté")
        lvl = Level(name.upper())
        lvl.vertices = [Vertex(*v) for v in
                        _records(lumps, "VERTEXES", "<hh")]
        lvl.linedefs = [Linedef(*l) for l in
                        _records(lumps, "LINEDEFS", "<HHHHHHH")]
        lvl.sidedefs = [Sidedef(s[-1]) for s in
                        _records(lumps, "SIDEDEFS", "<hh8s8s8sH")]
        lvl.sectors = [Sector(s[0], s[1], s[4], s[5], s[6]) for s in
                       _records(lumps, "SECTORS", "<hh8s8shHH")]
        lvl.things = [Thing(*t) for t in
                      _records(lumps, "THINGS", "<hhHHH")]
        return lvl


def _records(lumps, name, fmt):
    data = lumps.get(name, b"")
    size = struct.calcsize(fmt)
    return [struct.unpack_from(fmt, data, i)
            for i in range(0, len(data) - size + 1, size)]
