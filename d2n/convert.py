"""Rasterisation d'un niveau Doom sur une grille NetHack.

Les hauteurs sont ignorées : seul le plan vu de dessus est conservé.
"""

from collections import Counter, deque
from dataclasses import dataclass, field

from . import tables

# Taille maximale d'une carte des.map centrée (cf. dat/bigrm-1.lua et
# lspo_map() dans src/sp_lev.c ; COLNO = 80, ROWNO = 21).
MAX_WIDTH = 75
MAX_HEIGHT = 19

FLOOR, DOOR, WALL, STONE, HAZARD = ".", "+", "W", " ", "}"


@dataclass
class Options:
    width: int = MAX_WIDTH
    height: int = MAX_HEIGHT
    samples: int = 3            # échantillons par case et par axe
    coverage: float = 0.34      # fraction d'échantillons pour faire un sol
    keep_aspect: bool = False   # échelle uniforme (case 2x plus haute)
    hazards: str = "none"       # none | water | lava
    skill: str = "medium"       # easy | medium | hard


@dataclass
class Result:
    name: str
    grid: list                  # grid[y][x] : caractère des.map
    doors: list = field(default_factory=list)       # (x, y, état)
    upstair: tuple = None
    downstair: tuple = None
    # (x, y, nom, invisible, endormi)
    monsters: list = field(default_factory=list)
    objects: list = field(default_factory=list)     # (x, y, classe, nom)
    scale: tuple = (0.0, 0.0)
    warnings: list = field(default_factory=list)

    @property
    def width(self):
        return len(self.grid[0])

    @property
    def height(self):
        return len(self.grid)


# Position d'escalier déduite du niveau Doom (départ joueur / sortie).
AUTO = "auto"


def doom_start(level):
    """Départ du joueur : (x, y, None), ou None."""
    for t in level.things:
        if t.type == tables.PLAYER_START:
            return (t.x, t.y, None)
    return None


def doom_exit(level):
    """Milieu de la première ligne de sortie : (x, y, secteur), ou None."""
    for ld in level.linedefs:
        if ld.special in tables.EXIT_LINEDEFS:
            a, b = level.vertices[ld.v1], level.vertices[ld.v2]
            return ((a.x + b.x) / 2, (a.y + b.y) / 2,
                    level.side_sector(ld.right))
    return None


class Converter:
    """Convertit un niveau Doom, ou seulement les secteurs `sectors`.

    `up_at` / `down_at` placent les escaliers : AUTO (départ joueur /
    sortie Doom), None (choix automatique sur la grille) ou un point Doom
    (x, y, secteur préféré ou None).
    """

    def __init__(self, level, opts=None, sectors=None, up_at=AUTO,
                 down_at=AUTO, name=None):
        self.lvl = level
        self.opts = opts or Options()
        self.sectors = sectors
        self.up_at = doom_start(level) if up_at == AUTO else up_at
        self.down_at = doom_exit(level) if down_at == AUTO else down_at
        self.auto_stairs = (up_at == AUTO, down_at == AUTO)
        self.name = name or level.name
        self.warnings = []

    # --- géométrie -------------------------------------------------------

    def _sector_edges(self):
        """Arêtes délimitant chaque secteur (lignes à deux faces internes
        à un même secteur exclues, elles fausseraient la règle pair/impair).
        """
        edges = {i: [] for i in range(len(self.lvl.sectors))}
        for ld in self.lvl.linedefs:
            if ld.v1 >= len(self.lvl.vertices) or \
                    ld.v2 >= len(self.lvl.vertices):
                continue
            a, b = self.lvl.vertices[ld.v1], self.lvl.vertices[ld.v2]
            seg = (a.x, a.y, b.x, b.y)
            sr = self.lvl.side_sector(ld.right)
            sl = self.lvl.side_sector(ld.left)
            if sr == sl:
                continue
            for s in (sr, sl):
                if s is not None:
                    edges[s].append(seg)
        self.edges = edges
        self.sbbox = {}
        for s, segs in edges.items():
            if segs and (self.sectors is None or s in self.sectors):
                xs = [c for e in segs for c in (e[0], e[2])]
                ys = [c for e in segs for c in (e[1], e[3])]
                self.sbbox[s] = (min(xs), min(ys), max(xs), max(ys))

    def sector_at(self, px, py):
        best, best_area = None, None
        for s, (x0, y0, x1, y1) in self.sbbox.items():
            if not (x0 <= px <= x1 and y0 <= py <= y1):
                continue
            inside = False
            for ax, ay, bx, by in self.edges[s]:
                if (ay > py) != (by > py):
                    xi = ax + (py - ay) * (bx - ax) / (by - ay)
                    if xi > px:
                        inside = not inside
            if inside:
                # secteurs mal formés qui se chevauchent : le plus petit
                area = (x1 - x0) * (y1 - y0)
                if best is None or area < best_area:
                    best, best_area = s, area
        return best

    def _setup_transform(self):
        o = self.opts
        if not self.sbbox:
            raise ValueError(f"{self.name} : aucun secteur")
        x0, y0, x1, y1 = bbox_union(self.sbbox.values())
        self.minx, self.maxy = x0, y1
        spanx = max(x1 - x0, 1)
        spany = max(y1 - y0, 1)
        # une rangée de murs tout autour
        iw, ih = o.width - 2, o.height - 2
        sx, sy = spanx / iw, spany / ih
        if o.keep_aspect:
            # une case de terminal est environ 2 fois plus haute que large
            u = max(sx, sy / 2)
            sx, sy = u, 2 * u
            iw = max(1, min(iw, round(spanx / sx)))
            ih = max(1, min(ih, round(spany / sy)))
        self.sx, self.sy = sx, sy
        self.w, self.h = iw + 2, ih + 2

    def to_doom(self, cx, cy):
        """Centre de la case (cx, cy) en coordonnées Doom."""
        return (self.minx + (cx - 1 + 0.5) * self.sx,
                self.maxy - (cy - 1 + 0.5) * self.sy)

    def to_cell(self, x, y):
        cx = int((x - self.minx) / self.sx) + 1
        cy = int((self.maxy - y) / self.sy) + 1
        return (min(max(cx, 1), self.w - 2), min(max(cy, 1), self.h - 2))

    # --- rasterisation ---------------------------------------------------

    def _rasterize(self):
        n = self.opts.samples
        need = max(1, round(self.opts.coverage * n * n))
        self.sec = [[None] * self.w for _ in range(self.h)]
        for cy in range(1, self.h - 1):
            for cx in range(1, self.w - 1):
                hits = Counter()
                for j in range(n):
                    py = self.maxy - (cy - 1 + (j + 0.5) / n) * self.sy
                    for i in range(n):
                        px = self.minx + (cx - 1 + (i + 0.5) / n) * self.sx
                        s = self.sector_at(px, py)
                        if s is not None:
                            hits[s] += 1
                if hits and sum(hits.values()) >= need:
                    self.sec[cy][cx] = hits.most_common(1)[0][0]

    def floor(self, x, y):
        return 0 <= y < self.h and 0 <= x < self.w and \
            self.sec[y][x] is not None

    def cells_of(self, sector):
        return [(x, y) for y in range(self.h) for x in range(self.w)
                if self.sec[y][x] == sector]

    def nearest(self, x, y, cells):
        return min(cells, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2,
                   default=None)

    def _components(self):
        comp = [[-1] * self.w for _ in range(self.h)]
        n = 0
        for y in range(self.h):
            for x in range(self.w):
                if self.floor(x, y) and comp[y][x] < 0:
                    comp[y][x] = n
                    todo = deque([(x, y)])
                    while todo:
                        a, b = todo.popleft()
                        for c, d in ((a+1, b), (a-1, b), (a, b+1), (a, b-1)):
                            if self.floor(c, d) and comp[d][c] < 0:
                                comp[d][c] = n
                                todo.append((c, d))
                    n += 1
        return comp

    def _carve(self, a, b, sector):
        """Creuse un couloir en L entre les cases a et b."""
        (x0, y0), (x1, y1) = a, b
        step = 1 if x1 >= x0 else -1
        for x in range(x0, x1 + step, step):
            if self.sec[y0][x] is None:
                self.sec[y0][x] = sector
        step = 1 if y1 >= y0 else -1
        for y in range(y0, y1 + step, step):
            if self.sec[y][x1] is None:
                self.sec[y][x1] = sector

    def _links(self):
        """Paires de secteurs visibles reliés dans Doom, directement ou à
        travers des secteurs trop petits pour occuper une case (marches,
        ascenseurs...) : (secteur a, linedef côté a, secteur b, linedef
        côté b)."""
        adj = {}
        for ld in self.lvl.linedefs:
            sr = self.lvl.side_sector(ld.right)
            sl = self.lvl.side_sector(ld.left)
            if sr is None or sl is None or sr == sl or \
                    ld.flags & tables.ML_BLOCKING:
                continue
            adj.setdefault(sr, []).append((sl, ld))
            adj.setdefault(sl, []).append((sr, ld))
        visible = {s for row in self.sec for s in row if s is not None}
        links, seen_pairs = [], set()
        for a in sorted(visible & adj.keys()):
            for b, ld in adj[a]:
                if b in visible:
                    if (b, a) not in seen_pairs:
                        seen_pairs.add((a, b))
                        links.append((a, ld, b, ld))
                    continue
                # parcours des secteurs invisibles à partir de b
                seen, todo = {a, b}, deque([b])
                while todo:
                    s = todo.popleft()
                    for c, ld2 in adj.get(s, []):
                        if c in seen:
                            continue
                        seen.add(c)
                        if c in visible:
                            if (c, a) not in seen_pairs and \
                                    (a, c) not in seen_pairs:
                                seen_pairs.add((a, c))
                                links.append((a, ld, c, ld2))
                        else:
                            todo.append(c)
        return links

    def _connect(self):
        """Garantit que deux secteurs reliés dans Doom par des lignes
        franchissables le sont aussi sur la grille."""
        carved = 0
        cells = {}
        for y in range(self.h):
            for x in range(self.w):
                if self.sec[y][x] is not None:
                    cells.setdefault(self.sec[y][x], []).append((x, y))
        comp = self._components()
        for sa, lda, sb, ldb in self._links():
            a = self.nearest(*self._midcell(lda), cells[sa])
            b = self.nearest(*self._midcell(ldb), cells[sb])
            if comp[a[1]][a[0]] != comp[b[1]][b[0]]:
                self._carve(a, b, sb)
                comp = self._components()
                carved += 1
        # Zones encore isolées (téléporteurs, sols mobiles, rambardes...) :
        # on les relie à la plus grande zone pour que tout soit accessible.
        while True:
            groups = {}
            for y in range(self.h):
                for x in range(self.w):
                    if comp[y][x] >= 0:
                        groups.setdefault(comp[y][x], []).append((x, y))
            if len(groups) <= 1:
                break
            main = max(groups.values(), key=len)
            other = min((g for g in groups.values() if g is not main),
                        key=len)
            a, b = min(((p, q) for p in other for q in main),
                       key=lambda pq: (pq[0][0] - pq[1][0]) ** 2 +
                       (pq[0][1] - pq[1][1]) ** 2)
            self._carve(a, b, self.sec[b[1]][b[0]])
            comp = self._components()
            carved += 1
        if carved:
            self.warnings.append(f"{carved} passage(s) creusé(s) pour "
                                 "préserver la connectivité")

    def _midcell(self, ld):
        a, b = self.lvl.vertices[ld.v1], self.lvl.vertices[ld.v2]
        return self.to_cell((a.x + b.x) / 2, (a.y + b.y) / 2)

    # --- portes ----------------------------------------------------------

    def _doorway(self, x, y):
        """Orientation de passage si la case peut accueillir une porte."""
        l, r = self.floor(x - 1, y), self.floor(x + 1, y)
        u, d = self.floor(x, y - 1), self.floor(x, y + 1)
        if not l and not r and (u or d):
            return "v"          # murs à gauche et à droite
        if not u and not d and (l or r):
            return "h"
        return None

    def _place_doors(self):
        door_secs = {}
        for ld in self.lvl.linedefs:
            state = tables.DOOR_LINEDEFS.get(ld.special)
            ds = self.lvl.side_sector(ld.left)
            if state and ds in self.sbbox:
                door_secs.setdefault(ds, (state, []))[1].append(ld)
        doors, placed = [], set()
        for ds, (state, lines) in sorted(door_secs.items()):
            cells = self.cells_of(ds)
            if not cells:
                # porte trop fine : on cherche près des linedefs
                mids = [self._midcell(ld) for ld in lines]
                cells = [(x, y) for mx, my in mids
                         for x in range(mx - 1, mx + 2)
                         for y in range(my - 1, my + 2) if self.floor(x, y)]
            # plusieurs secteurs porte peuvent tomber sur la même case
            cells = [c for c in cells if c not in placed]
            if not cells:
                self.warnings.append(f"porte du secteur {ds} non placée")
                continue
            cx = sum(c[0] for c in cells) / len(cells)
            cy = sum(c[1] for c in cells) / len(cells)
            x, y = self.nearest(cx, cy, cells)
            # Les linedefs de porte sont transversaux au passage : des
            # lignes verticales donnent un passage horizontal, que la
            # porte ferme en bouchant sa colonne (et inversement).
            vx = vy = 0
            for ld in lines:
                a, b = self.lvl.vertices[ld.v1], self.lvl.vertices[ld.v2]
                vx += abs(b.x - a.x)
                vy += abs(b.y - a.y)
            x0, y0, x1, y1 = self.sbbox[ds]
            if vy >= vx:
                step, lo, hi = (0, 1), y0 - self.sy, y1 + self.sy
            else:
                step, lo, hi = (1, 0), x0 - self.sx, x1 + self.sx
            # Une porte NetHack fait une case : on mure le reste de la
            # largeur du passage, dans l'emprise du secteur porte.
            for sgn in (1, -1):
                px, py = x + sgn * step[0], y + sgn * step[1]
                while self.floor(px, py) and (px, py) not in placed:
                    pos = self.to_doom(px, py)[step[1]]
                    if not lo <= pos <= hi:
                        break
                    self.sec[py][px] = None
                    px, py = px + sgn * step[0], py + sgn * step[1]
            if not self._doorway(x, y):
                self.warnings.append(f"porte du secteur {ds} en (x={x}, "
                                     f"y={y}) mal entourée de murs")
            doors.append((x, y, state))
            placed.add((x, y))
        return doors

    # --- assemblage ------------------------------------------------------

    def run(self):
        self._sector_edges()
        self._setup_transform()
        self._rasterize()
        doors = self._place_doors()
        self._connect()
        door_xy = {(x, y) for x, y, _ in doors}

        grid = [[STONE] * self.w for _ in range(self.h)]
        hazard = {"water": "}", "lava": "L"}.get(self.opts.hazards)
        for y in range(self.h):
            for x in range(self.w):
                s = self.sec[y][x]
                if (x, y) in door_xy:
                    grid[y][x] = DOOR
                elif s is not None:
                    special = self.lvl.sectors[s].special
                    if hazard and special in tables.DAMAGE_SECTORS:
                        grid[y][x] = hazard
                    else:
                        grid[y][x] = FLOOR
        # murs : même règle que wallify_map() de sp_lev.c, la
        # wallification finale de NetHack corrige ensuite les coins
        for y in range(self.h):
            for x in range(self.w):
                if grid[y][x] != STONE:
                    continue
                for yy in range(max(y - 1, 0), min(y + 2, self.h)):
                    if any(self.floor(xx, yy)
                           for xx in range(max(x - 1, 0),
                                           min(x + 2, self.w))):
                        grid[y][x] = WALL
                        break
        # aspect : '|' pour un mur vertical, '-' sinon (coins compris)
        def wall(x, y):
            return 0 <= y < self.h and 0 <= x < self.w and \
                grid[y][x] in (WALL, DOOR, "-", "|")
        for y in range(self.h):
            for x in range(self.w):
                if grid[y][x] == WALL:
                    vert = wall(x, y - 1) or wall(x, y + 1)
                    horiz = wall(x - 1, y) or wall(x + 1, y)
                    grid[y][x] = "|" if vert and not horiz else "-"

        res = Result(self.name, ["".join(r) for r in grid], doors,
                     scale=(self.sx, self.sy))
        self._place_things(res, door_xy)
        res.warnings = self.warnings
        return res

    def _walkable(self):
        return [(x, y) for y in range(self.h) for x in range(self.w)
                if self.floor(x, y)]

    def _place_things(self, res, door_xy):
        busy = set(door_xy)
        free = [c for c in self._walkable() if c not in busy]
        if not free:
            self.warnings.append("aucune case de sol")
            return

        def spot(x, y, prefer=None):
            cells = [c for c in (prefer or []) if c not in busy] or \
                [c for c in free if c not in busy]
            c = self.nearest(x, y, cells)
            if c:
                busy.add(c)
            return c

        def at(point):
            x, y, s = point
            prefer = self.cells_of(s) if s is not None else None
            return spot(*self.to_cell(x, y), prefer=prefer)

        if self.up_at:
            res.upstair = at(self.up_at)
        else:
            if self.auto_stairs[0]:
                self.warnings.append("pas de départ joueur (thing 1)")
            res.upstair = spot(1, 1)
        if self.down_at:
            res.downstair = at(self.down_at)
        else:
            if self.auto_stairs[1]:
                self.warnings.append("pas de sortie : escalier descendant "
                                     "placé au plus loin du départ")
            res.downstair = self._farthest(res.upstair, busy)
            busy.add(res.downstair)

        skipped = Counter()
        for t in self.lvl.things:
            if t.flags & tables.MTF_MULTI or t.type == tables.PLAYER_START \
                    or not t.flags & tables.SKILL_FLAGS[self.opts.skill] \
                    or self.sector_at(t.x, t.y) is None:
                continue        # hors de la zone convertie
            if t.type in tables.MONSTERS:
                c = spot(*self.to_cell(t.x, t.y))
                if c:
                    name, invis = tables.MONSTERS[t.type]
                    res.monsters.append((*c, name, invis,
                                         bool(t.flags & tables.MTF_AMBUSH)))
            elif t.type in tables.OBJECTS:
                c = spot(*self.to_cell(t.x, t.y))
                if c:
                    res.objects.append((*c, *tables.OBJECTS[t.type]))
            else:
                skipped[t.type] += 1
        if skipped:
            self.warnings.append("things ignorés (type: nombre) : " +
                                 ", ".join(f"{k}: {v}" for k, v in
                                           sorted(skipped.items())))

    def _farthest(self, start, busy):
        dist = {start: 0}
        todo = deque([start])
        while todo:
            a, b = todo.popleft()
            for c in ((a+1, b), (a-1, b), (a, b+1), (a, b-1)):
                if self.floor(*c) and c not in dist:
                    dist[c] = dist[(a, b)] + 1
                    todo.append(c)
        cand = [c for c in dist if c not in busy]
        return max(cand, key=dist.get) if cand else start


def bbox_union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def convert(level, opts=None):
    return Converter(level, opts).run()

