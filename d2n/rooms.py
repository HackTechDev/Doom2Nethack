"""Conversion « salles et couloirs » d'un niveau Doom.

Au lieu de décalquer le plan case par case, on garde quelles salles
existent et lesquelles communiquent, puis on redessine un niveau à la
manière de NetHack :

1. les secteurs sont regroupés en salles : un secteur presque entouré par
   un autre (flaque, estrade, zone de lumière) y est fusionné, puis les
   paires les plus liées sont fusionnées jusqu'au nombre de salles visé ;
2. les groupes longs et étroits deviennent des couloirs, et les secteurs
   porte des portes : ce sont des nœuds de passage, pas des salles ;
3. chaque salle devient un rectangle NetHack placé à la position projetée
   de son centre Doom, de taille proportionnelle à son emprise, puis les
   rectangles sont écartés jusqu'à ne plus se toucher ;
4. les salles reliées dans Doom (directement ou par des couloirs et des
   portes) sont reliées par des couloirs `#`, avec une porte `+` à chaque
   bout.
"""

import heapq
import math
from collections import deque
from dataclasses import dataclass, field

from . import tables
from .convert import (DOOR, FLOOR, STONE, Converter, Result, bbox_union,
                      doom_start)

CORRIDOR = "#"

# Un groupe est un couloir si sa largeur estimée (2 × aire / périmètre)
# est faible et sa forme allongée (périmètre² / aire ; 16 pour un carré).
CORRIDOR_WIDTH = 110
CORRIDOR_ELONGATION = 22
# Un secteur dont au moins cette part du périmètre touche un voisin est
# fusionné avec lui.
EMBEDDED = 0.5
# En dessous de cette part de l'aire totale, la zone accessible depuis le
# départ est jugée suspecte (départ enfermé, cf. E1M8) : rien n'est retiré.
MIN_REACHABLE = 0.5
# Un groupe plus petit (unités Doom²) est fusionné avec le voisin qui
# partage la plus grande frontière (marches, bandes de lumière...).
SMALL_AREA = 128 * 192
# Part de la carte occupée par les salles (murs compris), avant écartement.
ROOM_FILL = 0.45
MIN_ROOM = 2                    # côté intérieur minimal d'une salle


@dataclass
class Group:
    sectors: set
    area: float
    perim: float
    cx: float                   # centre Doom (centroïde des secteurs)
    cy: float
    bbox: tuple                 # emprise Doom (x0, y0, x1, y1)
    corridor: bool = False
    rect: list = field(default=None)    # intérieur [x0, y0, x1, y1]


def sector_areas(level):
    """Aire de chaque secteur (formule du lacet)."""
    acc = [0.0] * len(level.sectors)
    for ld in level.linedefs:
        if ld.v1 >= len(level.vertices) or ld.v2 >= len(level.vertices):
            continue
        a, b = level.vertices[ld.v1], level.vertices[ld.v2]
        cross = a.x * b.y - b.x * a.y
        sr, sl = level.side_sector(ld.right), level.side_sector(ld.left)
        if sr == sl:
            continue
        if sr is not None:
            acc[sr] -= cross
        if sl is not None:
            acc[sl] += cross
    return [abs(v) / 2 for v in acc]


def doom_reachable(level, start):
    """Secteurs accessibles depuis le point start : lignes franchissables
    et téléporteurs.  None si la zone accessible est suspecte."""
    adj = {}
    tagged = {}
    for i, sec in enumerate(level.sectors):
        if sec.tag:
            tagged.setdefault(sec.tag, []).append(i)
    for ld in level.linedefs:
        sr, sl = level.side_sector(ld.right), level.side_sector(ld.left)
        if sr is not None and sl is not None and \
                not ld.flags & tables.ML_BLOCKING:
            adj.setdefault(sr, set()).add(sl)
            adj.setdefault(sl, set()).add(sr)
        if ld.special in tables.TELEPORT_LINEDEFS:
            for s in (sr, sl):
                if s is not None:
                    adj.setdefault(s, set()).update(tagged.get(ld.tag, ()))
    conv = Converter(level)
    conv._sector_edges()
    first = conv.sector_at(start[0], start[1]) if start else None
    if first is None:
        return None
    seen, todo = {first}, deque([first])
    while todo:
        for n in adj.get(todo.popleft(), ()):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    areas = sector_areas(level)
    if sum(areas[s] for s in seen) < MIN_REACHABLE * sum(areas):
        return None
    return seen


class RoomConverter(Converter):
    """Même interface que Converter, avec un plan en salles et couloirs.

    Les secteurs inaccessibles depuis le départ Doom (décors vus par une
    fenêtre, placards à monstres) sont retirés, ainsi que leurs things.
    """

    def sector_at(self, px, py):
        s = super().sector_at(px, py)
        return None if s in getattr(self, "dropped", ()) else s

    # --- regroupement des secteurs ---------------------------------------

    def _sector_stats(self):
        """Aire, centroïde et périmètre exacts de chaque secteur actif
        (formule du lacet : dans Doom le secteur est à droite du linedef).
        """
        acc = {s: [0.0, 0.0, 0.0, 0.0] for s in self.sbbox}
        self.lines = []     # (secteur droit, gauche, longueur, franchissable)
        for ld in self.lvl.linedefs:
            if ld.v1 >= len(self.lvl.vertices) or \
                    ld.v2 >= len(self.lvl.vertices):
                continue
            a, b = self.lvl.vertices[ld.v1], self.lvl.vertices[ld.v2]
            sr = self.lvl.side_sector(ld.right)
            sl = self.lvl.side_sector(ld.left)
            if sr == sl:
                continue
            length = math.hypot(b.x - a.x, b.y - a.y)
            cross = a.x * b.y - b.x * a.y
            for s, sign in ((sr, -1), (sl, 1)):
                if s in acc:
                    st = acc[s]
                    st[0] += sign * cross
                    st[1] += sign * (a.x + b.x) * cross
                    st[2] += sign * (a.y + b.y) * cross
                    st[3] += length
            passable = sr is not None and sl is not None and \
                not ld.flags & tables.ML_BLOCKING
            self.lines.append((sr, sl, length, passable, ld))
        stats = {}
        for s, (a2, cx, cy, perim) in acc.items():
            x0, y0, x1, y1 = self.sbbox[s]
            if abs(a2) > 1e-6:
                stats[s] = (abs(a2) / 2, cx / (3 * a2), cy / (3 * a2), perim)
            else:
                stats[s] = (max((x1 - x0) * (y1 - y0), 1),
                            (x0 + x1) / 2, (y0 + y1) / 2, perim)
        return stats

    def _door_sectors(self):
        doors = {}
        for ld in self.lvl.linedefs:
            state = tables.DOOR_LINEDEFS.get(ld.special)
            ds = self.lvl.side_sector(ld.left)
            if state and ds in self.sbbox:
                doors[ds] = state
        return doors

    def _group(self, target):
        stats = self._sector_stats()
        self.door_secs = self._door_sectors()
        gid = {s: s for s in stats if s not in self.door_secs and
               s not in self.dropped}
        groups = {}
        for s in gid:
            area, cx, cy, perim = stats[s]
            groups[s] = Group({s}, area, perim, cx, cy, self.sbbox[s])
        # longueur de frontière entre groupes : franchissable / totale
        shared, shared_all = {}, {}
        for sr, sl, length, passable, _ in self.lines:
            if sr in gid and sl in gid:
                key = (min(sr, sl), max(sr, sl))
                shared_all[key] = shared_all.get(key, 0) + length
                if passable:
                    shared[key] = shared.get(key, 0) + length

        def merge(a, b):
            ga, gb = groups[a], groups.pop(b)
            key = (min(a, b), max(a, b))
            area = ga.area + gb.area
            ga.cx = (ga.cx * ga.area + gb.cx * gb.area) / area
            ga.cy = (ga.cy * ga.area + gb.cy * gb.area) / area
            ga.perim += gb.perim - 2 * shared_all.get(key, 0)
            ga.area = area
            ga.sectors |= gb.sectors
            ga.bbox = bbox_union((ga.bbox, gb.bbox))
            for s in gb.sectors:
                gid[s] = a
            for table in (shared, shared_all):
                for (p, q) in [k for k in table if b in k]:
                    v = table.pop((p, q))
                    other = q if p == b else p
                    if other == a:
                        continue
                    k = (min(a, other), max(a, other))
                    table[k] = table.get(k, 0) + v

        # 1) secteurs presque entourés par un voisin
        merged = True
        while merged:
            merged = False
            for (p, q), length in sorted(shared.items()):
                for small, big in ((p, q), (q, p)):
                    g = groups[small]
                    if length >= EMBEDDED * g.perim and \
                            g.area <= groups[big].area:
                        merge(big, small)
                        merged = True
                        break
                if merged:
                    break
        def nearest(g_id):
            g = groups[g_id]
            return min((k for k in groups if k != g_id), default=None,
                       key=lambda k: (groups[k].cx - g.cx) ** 2 +
                       (groups[k].cy - g.cy) ** 2)

        # 2) petits groupes : avec le voisin le plus lié, ou à défaut (ses
        #    voisins sont dans un autre morceau) avec le plus proche
        for g_id in sorted(groups, key=lambda k: groups[k].area):
            if g_id not in groups or groups[g_id].area >= SMALL_AREA:
                continue
            near = [(v, k) for k, v in shared.items() if g_id in k]
            if near:
                _, (p, q) = max(near)
                other = q if p == g_id else p
            else:
                other = nearest(g_id)
            if other is not None:
                merge(other, g_id)
        # 3) paires les plus liées jusqu'au nombre de salles visé
        #    (les couloirs ne comptent pas et ne sont pas fusionnés)
        def corridor(g):
            width = 2 * g.area / max(g.perim, 1)
            return width <= CORRIDOR_WIDTH and \
                g.perim ** 2 / max(g.area, 1) >= CORRIDOR_ELONGATION

        while sum(not corridor(g) for g in groups.values()) > target:
            pairs = [(k, v) for k, v in shared.items()
                     if not corridor(groups[k[0]]) and
                     not corridor(groups[k[1]])]
            # salles toutes séparées par des couloirs : on fusionne aussi
            # les couloirs, sinon le nombre de salles ne baisse plus
            pairs = pairs or list(shared.items())
            if pairs:
                (p, q), _ = max(pairs, key=lambda kv: kv[1] / math.sqrt(
                    min(groups[kv[0][0]].area, groups[kv[0][1]].area)))
            else:
                # plus aucune frontière : le plus petit avec le plus proche
                p = min(groups, key=lambda k: groups[k].area)
                q = nearest(p)
                if q is None:
                    break
            if groups[p].area < groups[q].area:
                p, q = q, p
            merge(p, q)
        for g in groups.values():
            g.corridor = corridor(g)
        if groups and all(g.corridor for g in groups.values()):
            max(groups.values(), key=lambda g: g.area).corridor = False
        self.groups, self.gid = groups, gid

    # --- liaisons entre salles -------------------------------------------

    def _links(self):
        """Paires de salles reliées dans Doom, à travers des couloirs et des
        portes : (salle a, salle b, état de porte, côté de la porte)."""
        adj = {}
        for sr, sl, _, passable, _ in self.lines:
            if not passable:
                continue
            a = self.gid.get(sr, ("door", sr) if sr in self.door_secs
                             else None)
            b = self.gid.get(sl, ("door", sl) if sl in self.door_secs
                             else None)
            if a is None or b is None or a == b:
                continue
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)

        def is_room(n):
            return not isinstance(n, tuple) and not self.groups[n].corridor

        links, seen = [], set()
        for a in sorted(n for n in adj if is_room(n)):
            # parcours des nœuds de passage (couloirs, portes) depuis a
            todo = deque((n, None) for n in adj[a])
            visited = {a}
            while todo:
                n, door = todo.popleft()
                if n in visited:
                    continue
                visited.add(n)
                if isinstance(n, tuple):
                    door = door or n
                if is_room(n):
                    key = (min(a, n), max(a, n))
                    if key not in seen:
                        seen.add(key)
                        links.append((a, n, *self._door_side(door, a, n,
                                                             adj)))
                    continue
                todo.extend((m, door) for m in adj.get(n, ()))
        return links

    def _door_side(self, door, a, b, adj):
        """(état, salle du côté de la porte) pour une liaison a-b passant
        par le nœud porte `door` (ou None : simple ouverture)."""
        if door is None:
            return ("nodoor", None)
        side = a if a in adj[door] else b if b in adj[door] else None
        return (self.door_secs[door[1]], side)

    # --- disposition des salles ------------------------------------------

    def _layout(self):
        rooms = [g for g in self.groups.values() if not g.corridor]
        W, H = self.w, self.h
        need = 0
        for g in rooms:
            x0, y0, x1, y1 = g.bbox
            g.pw, g.ph = (x1 - x0) / self.sx, (y1 - y0) / self.sy
            need += (g.pw + 2) * (g.ph + 2)
        f = min(1.0, math.sqrt(ROOM_FILL * W * H / max(need, 1)))
        for _ in range(12):
            for g in rooms:
                w = min(max(MIN_ROOM, round(g.pw * f)), W - 4)
                h = min(max(MIN_ROOM, round(g.ph * f)), H - 4)
                cx, cy = self._project(g.cx, g.cy)
                x0 = min(max(1, round(cx - w / 2)), W - 1 - w)
                y0 = min(max(1, round(cy - h / 2)), H - 1 - h)
                g.rect = [x0, y0, x0 + w - 1, y0 + h - 1]
            if self._separate(rooms):
                return rooms
            f *= 0.85
        return None

    def _project(self, x, y):
        return ((x - self.minx) / self.sx + 1, (self.maxy - y) / self.sy + 1)

    def _separate(self, rooms, iterations=400):
        """Écarte les salles : entre deux intérieurs, au moins 3 cases (mur,
        passage, mur).  Renvoie False si des chevauchements subsistent."""
        W, H = self.w, self.h
        for _ in range(iterations):
            moved = False
            for i, a in enumerate(rooms):
                for b in rooms[i + 1:]:
                    ra, rb = a.rect, b.rect
                    ox = min(ra[2], rb[2]) - max(ra[0], rb[0]) + 4
                    oy = min(ra[3], rb[3]) - max(ra[1], rb[1]) + 4
                    if ox <= 0 or oy <= 0:
                        continue
                    moved = True
                    # on écarte selon l'axe le moins chevauchant (une case
                    # verticale vaut environ deux cases horizontales)
                    if ox <= 2 * oy:
                        sgn = 1 if (ra[0] + ra[2]) <= (rb[0] + rb[2]) else -1
                        self._shift(a, -sgn * math.ceil(ox / 2), 0, W, H)
                        self._shift(b, sgn * math.ceil(ox / 2), 0, W, H)
                    else:
                        sgn = 1 if (ra[1] + ra[3]) <= (rb[1] + rb[3]) else -1
                        self._shift(a, 0, -sgn * math.ceil(oy / 2), W, H)
                        self._shift(b, 0, sgn * math.ceil(oy / 2), W, H)
            if not moved:
                return True
        return False

    @staticmethod
    def _shift(g, dx, dy, W, H):
        r = g.rect
        dx = min(max(dx, 1 - r[0]), W - 2 - r[2])
        dy = min(max(dy, 1 - r[1]), H - 2 - r[3])
        g.rect = [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]

    # --- dessin ----------------------------------------------------------

    def _draw(self, rooms):
        self.grid = [[STONE] * self.w for _ in range(self.h)]
        self.blocked = [[False] * self.w for _ in range(self.h)]
        for g in rooms:
            x0, y0, x1, y1 = g.rect
            for y in range(y0 - 1, y1 + 2):
                for x in range(x0 - 1, x1 + 2):
                    self.blocked[y][x] = True
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        self.grid[y][x] = FLOOR
                    elif y in (y0 - 1, y1 + 1):
                        self.grid[y][x] = "-"
                    else:
                        self.grid[y][x] = "|"

    def _door_spots(self, g, tx, ty):
        """Emplacements de porte sur les murs de g, du plus proche au plus
        éloigné de la cible (tx, ty) : (porte, case extérieure)."""
        x0, y0, x1, y1 = g.rect
        spots = []
        for x in range(x0, x1 + 1):
            spots.append(((x, y0 - 1), (x, y0 - 2)))
            spots.append(((x, y1 + 1), (x, y1 + 2)))
        for y in range(y0, y1 + 1):
            spots.append(((x0 - 1, y), (x0 - 2, y)))
            spots.append(((x1 + 1, y), (x1 + 2, y)))
        spots = [s for s in spots if self._outside_free(*s[1])]
        return sorted(spots, key=lambda s: (s[1][0] - tx) ** 2 +
                      (2 * (s[1][1] - ty)) ** 2)

    def _outside_free(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h and \
            (not self.blocked[y][x] or self.grid[y][x] == CORRIDOR)

    def _path(self, start, goal):
        """Plus court couloir de start à goal hors des salles ; les couloirs
        existants coûtent moins cher, pour qu'ils se rejoignent."""
        dist = {start: 0}
        prev = {}
        heap = [(0, start)]
        while heap:
            d, c = heapq.heappop(heap)
            if c == goal:
                path = [c]
                while c in prev:
                    c = prev[c]
                    path.append(c)
                return path
            if d > dist[c]:
                continue
            x, y = c
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not self._outside_free(*n):
                    continue
                cost = 0.5 if self.grid[n[1]][n[0]] == CORRIDOR else 1
                nd = d + cost
                if nd < dist.get(n, 1e9):
                    dist[n], prev[n] = nd, c
                    heapq.heappush(heap, (nd, n))
        return None

    def _connect_rooms(self, ga, gb, state_a, state_b):
        ca = ((ga.rect[0] + ga.rect[2]) / 2, (ga.rect[1] + ga.rect[3]) / 2)
        cb = ((gb.rect[0] + gb.rect[2]) / 2, (gb.rect[1] + gb.rect[3]) / 2)
        for da, oa in self._door_spots(ga, *cb)[:6]:
            for db, ob in self._door_spots(gb, *ca)[:6]:
                path = self._path(oa, ob)
                if path:
                    for x, y in path:
                        self.grid[y][x] = CORRIDOR
                    self._add_door(da, state_a)
                    self._add_door(db, state_b)
                    return True
        return False

    def _add_door(self, pos, state):
        x, y = pos
        old = self.doors.get(pos)
        # une vraie porte l'emporte sur une simple ouverture
        if old is None or old == "nodoor":
            self.doors[pos] = state
        self.grid[y][x] = DOOR

    def _reachable(self, start):
        seen, todo = {start}, deque([start])
        while todo:
            x, y = todo.popleft()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n not in seen and self.floor(*n):
                    seen.add(n)
                    todo.append(n)
        return seen

    # --- interface utilisée par Converter._place_things ------------------

    def floor(self, x, y):
        return 0 <= y < self.h and 0 <= x < self.w and \
            self.grid[y][x] in (FLOOR, CORRIDOR, DOOR)

    def _walkable(self):
        return [(x, y) for g in self.rooms
                for y in range(g.rect[1], g.rect[3] + 1)
                for x in range(g.rect[0], g.rect[2] + 1)]

    def _room_of(self, sector, x=None, y=None):
        """Salle d'un secteur ; pour un couloir, une porte ou un point hors
        secteur, la salle dont le centre Doom est le plus proche."""
        g = self.groups.get(self.gid.get(sector))
        if g is not None and not g.corridor:
            return g
        if x is None:
            if sector not in self.sbbox:
                return None
            b = self.sbbox[sector]
            x, y = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return min(self.rooms, key=lambda r: (r.cx - x) ** 2 +
                   (r.cy - y) ** 2, default=None)

    def _farthest(self, start, busy):
        """Case de salle la plus éloignée de start (pas un couloir)."""
        dist = {start: 0}
        todo = deque([start])
        while todo:
            x, y = todo.popleft()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if self.floor(*n) and n not in dist:
                    dist[n] = dist[(x, y)] + 1
                    todo.append(n)
        cand = [c for c in self._walkable() if c in dist and c not in busy]
        return max(cand, key=dist.get) if cand else start

    def cells_of(self, sector):
        g = self._room_of(sector)
        if g is None:
            return []
        return [(x, y) for y in range(g.rect[1], g.rect[3] + 1)
                for x in range(g.rect[0], g.rect[2] + 1)]

    def to_cell(self, x, y):
        """Position relative dans l'emprise Doom de la salle, reportée dans
        son rectangle NetHack."""
        g = self._room_of(self.sector_at(x, y), x, y)
        if g is None:
            return (1, 1)
        bx0, by0, bx1, by1 = g.bbox
        u = (x - bx0) / max(bx1 - bx0, 1)
        v = (by1 - y) / max(by1 - by0, 1)
        r = g.rect
        cx = r[0] + round(min(max(u, 0), 1) * (r[2] - r[0]))
        cy = r[1] + round(min(max(v, 0), 1) * (r[3] - r[1]))
        return (cx, cy)

    # --- assemblage ------------------------------------------------------

    def run(self):
        self._sector_edges()
        self._setup_transform()
        reach = doom_reachable(self.lvl, doom_start(self.lvl))
        self.dropped = set() if reach is None else \
            {s for s in self.sbbox if s not in reach}
        if not set(self.sbbox) - self.dropped:
            self.dropped = set()    # morceau entièrement décoratif
        # moins de salles si elles ne tiennent pas sur la carte
        target = self.opts.rooms or 12
        while True:
            self._group(target)
            self.rooms = self._layout()
            if self.rooms is not None or target <= 2:
                break
            target -= 2
        if self.rooms is None:
            raise ValueError(f"{self.name} : impossible de placer les "
                             "salles")
        self._draw(self.rooms)
        self.doors = {}
        failed = 0
        for a, b, state, side in self._links():
            ga, gb = self.groups[a], self.groups[b]
            sa = state if side in (a, None) else "nodoor"
            sb = state if side == b else "nodoor"
            if not self._connect_rooms(ga, gb, sa, sb):
                failed += 1
        # salles encore isolées : reliées à la salle accessible la plus
        # proche (téléporteurs, sols mobiles, rambardes...)
        extra = 0
        if self.rooms:
            start = self.rooms[0]
            reach = self._reachable((start.rect[0], start.rect[1]))
            for g in sorted(self.rooms[1:], key=lambda r: r.area,
                            reverse=True):
                if (g.rect[0], g.rect[1]) in reach:
                    continue
                cand = [r for r in self.rooms
                        if (r.rect[0], r.rect[1]) in reach]
                cand.sort(key=lambda r: (r.cx - g.cx) ** 2 +
                          (r.cy - g.cy) ** 2)
                if any(self._connect_rooms(g, r, "nodoor", "nodoor")
                       for r in cand):
                    extra += 1
                    reach = self._reachable((start.rect[0], start.rect[1]))
                else:
                    failed += 1
        if extra:
            self.warnings.append(f"{extra} salle(s) isolée(s) reliée(s) "
                                 "pour préserver la connectivité")
        if failed:
            self.warnings.append(f"{failed} liaison(s) impossible(s) à "
                                 "tracer")

        doors = [(x, y, s) for (x, y), s in sorted(self.doors.items())]
        res = Result(self.name, ["".join(r) for r in self.grid], doors,
                     scale=(self.sx, self.sy))
        ncorr = sum(g.corridor for g in self.groups.values())
        res.info.append(f"{len(self.rooms)} salle(s), {ncorr} couloir(s) "
                        f"Doom, {len(doors)} porte(s) ou ouverture(s)")
        if self.dropped:
            res.info.append(f"{len(self.dropped)} secteur(s) inaccessible(s) "
                            "depuis le départ retiré(s)")
        self._place_things(res, set(self.doors))
        res.warnings = self.warnings
        return res
