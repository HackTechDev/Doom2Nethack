#!/usr/bin/env python3
"""Génère un PWAD de test : 3 salles (la dernière sombre), un pilier, une
porte, un couloir fin, une flaque de nukage, une sortie et quelques
things."""

import struct
import sys


class LevelBuilder:
    def __init__(self):
        self.vertices = []
        self.vindex = {}
        self.lines = {}         # (v1, v2) -> [right, left, special]
        self.sectors = []
        self.things = []

    def _v(self, p):
        if p not in self.vindex:
            self.vindex[p] = len(self.vertices)
            self.vertices.append(p)
        return self.vindex[p]

    def sector(self, poly, special=0, outer=None, special_lines=0,
               light=160):
        """Ajoute un secteur (polygone en sens horaire, y vers le haut).
        Une arête déjà existante dans l'autre sens devient à deux faces ;
        `outer` est le secteur entourant un secteur intérieur."""
        s = len(self.sectors)
        self.sectors.append((special, light))
        for a, b in zip(poly, poly[1:] + poly[:1]):
            va, vb = self._v(a), self._v(b)
            if (vb, va) in self.lines:
                self.lines[(vb, va)][1] = s
                if special_lines:
                    self.lines[(vb, va)][2] = special_lines
            else:
                self.lines[(va, vb)] = [s, outer, 0]
        return s

    def hole(self, poly, sector):
        """Pilier (vide) à l'intérieur de `sector`."""
        for a, b in zip(poly, poly[1:] + poly[:1]):
            self.lines[(self._v(b), self._v(a))] = [sector, None, 0]

    def set_special(self, a, b, special):
        self.lines[(self._v(a), self._v(b))][2] = special

    def thing(self, x, y, t):
        self.things.append((x, y, 0, t, 7))

    def lumps(self):
        sides, lines = b"", b""
        for (va, vb), (r, l, sp) in self.lines.items():
            ids = []
            for s in (r, l):
                if s is None:
                    ids.append(0xFFFF)
                else:
                    ids.append(len(sides) // 30)
                    sides += struct.pack("<hh8s8s8sH", 0, 0, b"-", b"-",
                                         b"STARTAN3", s)
            flags = 0x0001 if l is None else 0x0004
            lines += struct.pack("<HHHHHHH", va, vb, flags, sp, 0, *ids)
        verts = b"".join(struct.pack("<hh", *p) for p in self.vertices)
        secs = b"".join(struct.pack("<hh8s8shHH", 0, 128, b"FLOOR4_8",
                                    b"CEIL3_5", light, sp, 0)
                        for sp, light in self.sectors)
        things = b"".join(struct.pack("<hhHHH", *t) for t in self.things)
        return [("MAP01", b""), ("THINGS", things), ("LINEDEFS", lines),
                ("SIDEDEFS", sides), ("VERTEXES", verts), ("SEGS", b""),
                ("SSECTORS", b""), ("NODES", b""), ("SECTORS", secs),
                ("REJECT", b""), ("BLOCKMAP", b"")]


def write_wad(path, lumps):
    data, dirs = b"", b""
    for name, blob in lumps:
        dirs += struct.pack("<ii8s", 12 + len(data), len(blob),
                            name.encode())
        data += blob
    with open(path, "wb") as f:
        f.write(struct.pack("<4sii", b"PWAD", len(lumps), 12 + len(data)))
        f.write(data + dirs)


def build():
    b = LevelBuilder()
    # salle A avec un pilier
    a = b.sector([(0, 0), (0, 768), (1024, 768), (1024, 448), (1024, 320),
                  (1024, 0)])
    b.hole([(384, 256), (384, 512), (640, 512), (640, 256)], a)
    # couloir vers la porte
    b.sector([(1024, 320), (1024, 448), (1536, 448), (1536, 320)])
    # salle B (avant la porte, pour que la porte soit côté gauche)
    rb = b.sector([(1600, 0), (1600, 320), (1600, 448), (1600, 1024),
                   (2048, 1024), (2112, 1024), (2560, 1024), (2560, 0)])
    b.sector([(1536, 320), (1536, 448), (1600, 448), (1600, 320)],
             special_lines=1)
    # flaque de nukage dans B
    b.sector([(2100, 500), (2100, 800), (2400, 800), (2400, 500)],
             special=7, outer=rb)
    # couloir fin (64 unités) vers la salle C
    b.sector([(2048, 1024), (2048, 1536), (2112, 1536), (2112, 1024)])
    b.sector([(1600, 1536), (1600, 2048), (2560, 2048), (2560, 1536),
              (2112, 1536), (2048, 1536)], light=96)     # salle C sombre
    b.set_special((1600, 2048), (2560, 2048), 11)   # sortie

    b.thing(200, 100, 1)        # départ joueur
    b.thing(800, 600, 3001)     # imp
    b.thing(1800, 200, 3004)    # zombieman
    b.thing(2000, 1900, 9)      # shotgun guy
    b.thing(2400, 1800, 2012)   # medikit
    b.thing(1300, 384, 5)       # carte bleue
    b.thing(100, 700, 2035)     # baril (ignoré)
    return b.lumps()


if __name__ == "__main__":
    write_wad(sys.argv[1] if len(sys.argv) > 1 else "test3rooms.wad",
              build())
