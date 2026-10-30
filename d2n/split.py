"""Découpage d'un grand niveau Doom en plusieurs niveaux NetHack reliés par
des escaliers.

Les secteurs sont répartis par bissections successives le long de l'axe le
plus comprimé, puis les morceaux sont ordonnés en chaîne (un niveau NetHack
n'a qu'un escalier montant et un descendant) : du départ du joueur vers la
sortie, en enchaînant de préférence des morceaux voisins dans Doom.
"""

import math
from dataclasses import dataclass
from itertools import permutations

from . import tables
from .convert import Converter, Options, bbox_union, doom_exit, doom_start

MAX_PARTS = 12
# Taille de case visée par --parts auto (unités Doom ; le joueur fait 32
# de large, une case de terminal est environ 2 fois plus haute que large).
TARGET_SCALE = (48, 96)


@dataclass
class Part:
    sectors: set
    up_at: tuple = None         # point Doom (x, y, secteur) ou None
    down_at: tuple = None


def _geometry(level):
    conv = Converter(level)
    conv._sector_edges()
    return conv.sbbox


def auto_parts(level, opts):
    """Nombre de morceaux pour approcher TARGET_SCALE."""
    x0, y0, x1, y1 = bbox_union(_geometry(level).values())
    sx = (x1 - x0) / (opts.width - 2) / TARGET_SCALE[0]
    sy = (y1 - y0) / (opts.height - 2) / TARGET_SCALE[1]
    return max(1, min(MAX_PARTS, math.ceil(max(sx, 1) * max(sy, 1))))


def _bisect(secs, k, sbbox, opts):
    if k == 1 or len(secs) < 2:
        return [set(secs)]
    x0, y0, x1, y1 = bbox_union(sbbox[s] for s in secs)
    # on coupe l'axe qui a le plus d'unités Doom par case
    axis = 0 if (x1 - x0) / opts.width >= (y1 - y0) / opts.height else 1

    def center(s):
        b = sbbox[s]
        return (b[axis] + b[axis + 2]) / 2

    def weight(s):
        b = sbbox[s]
        return max((b[2] - b[0]) * (b[3] - b[1]), 1)

    order = sorted(secs, key=center)
    total = sum(weight(s) for s in order)
    goal = total * (k // 2) / k
    acc, cut = 0, 1
    for i, s in enumerate(order[:-1]):
        acc += weight(s)
        cut = i + 1
        if acc >= goal:
            break
    return (_bisect(order[:cut], k // 2, sbbox, opts) +
            _bisect(order[cut:], k - k // 2, sbbox, opts))


def _boundaries(level, part_of):
    """Linedefs franchissables entre deux morceaux : {(p, q): [ld...]}."""
    links = {}
    for ld in level.linedefs:
        sr, sl = level.side_sector(ld.right), level.side_sector(ld.left)
        if sr is None or sl is None or ld.flags & tables.ML_BLOCKING:
            continue
        p, q = part_of.get(sr), part_of.get(sl)
        if p is None or q is None or p == q:
            continue
        links.setdefault((p, q), []).append(ld)
        links.setdefault((q, p), []).append(ld)
    return links


def _order(n, first, last, links):
    """Chaîne de morceaux commençant par `first`, qui maximise le nombre
    de morceaux consécutifs voisins dans Doom (et finit si possible par
    `last`)."""
    rest = [i for i in range(n) if i != first]

    def score(chain):
        adj = sum((a, b) in links for a, b in zip(chain, chain[1:]))
        return (adj, chain[-1] == last)

    if n <= 8:
        return max(([first, *p] for p in permutations(rest)), key=score)
    # glouton au-delà : morceau voisin non visité, sinon le premier libre
    chain, todo = [first], set(rest)
    while todo:
        nxt = [q for q in sorted(todo) if (chain[-1], q) in links and
               q != last] or [q for q in sorted(todo) if q != last] or \
            sorted(todo)
        chain.append(nxt[0])
        todo.discard(nxt[0])
    return chain


def plan(level, n, opts=None):
    """Répartit le niveau en `n` morceaux ordonnés, avec escaliers."""
    opts = opts or Options()
    sbbox = _geometry(level)
    groups = [g for g in _bisect(sorted(sbbox), n, sbbox, opts) if g]
    part_of = {s: i for i, g in enumerate(groups) for s in g}
    conv = Converter(level)
    conv._sector_edges()

    def part_at(point):
        if point is None:
            return None
        s = point[2] if point[2] is not None else \
            conv.sector_at(point[0], point[1])
        return part_of.get(s)

    start, exit_ = doom_start(level), doom_exit(level)
    first = part_at(start)
    if first is None:
        first = 0
    last = part_at(exit_)
    links = _boundaries(level, part_of)
    chain = _order(len(groups), first, last, links)

    parts = [Part(groups[i]) for i in chain]
    parts[0].up_at = start
    if last == chain[-1]:
        parts[-1].down_at = exit_
    for k, (p, q) in enumerate(zip(chain, chain[1:])):
        lines = links.get((p, q))
        if not lines:
            continue        # morceaux non voisins : escaliers automatiques
        # le passage le plus large entre les deux morceaux
        ld = max(lines, key=lambda l: _length(level, l))
        a, b = level.vertices[ld.v1], level.vertices[ld.v2]
        mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
        sides = (level.side_sector(ld.right), level.side_sector(ld.left))
        sp = next(s for s in sides if part_of[s] == p)
        sq = next(s for s in sides if part_of[s] == q)
        parts[k].down_at = (mx, my, sp)
        parts[k + 1].up_at = (mx, my, sq)
    return parts


def _length(level, ld):
    a, b = level.vertices[ld.v1], level.vertices[ld.v2]
    return math.hypot(b.x - a.x, b.y - a.y)


def part_name(base, i):
    """Nom du i-ème niveau NetHack (e1m1a, e1m1b...)."""
    return f"{base}{chr(ord('a') + i)}"


def convert_parts(level, n, opts=None):
    opts = opts or Options()
    base = level.name.lower()
    parts = plan(level, n, opts)
    results = []
    for i, part in enumerate(parts):
        conv = Converter(level, opts, part.sectors, part.up_at,
                         part.down_at, part_name(base, i))
        results.append(conv.run())
    if doom_exit(level) and parts[-1].down_at is None:
        results[-1].warnings.append("la sortie Doom n'est pas dans le "
                                    "dernier morceau")
    return results
