import os
import sys
import tempfile
import unittest
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from d2n.convert import Options, convert          # noqa: E402
from d2n.lua_out import dungeon_snippet, to_lua   # noqa: E402
from d2n.split import auto_parts, convert_parts, plan  # noqa: E402
from d2n.wad import Wad                           # noqa: E402
import make_test_wad                              # noqa: E402

YADEX_WAD = os.path.join(os.path.dirname(__file__), "..", "..",
                         "YadexEditor", "test.wad")


def reachable(res, start):
    seen, todo = {start}, deque([start])
    while todo:
        x, y = todo.popleft()
        for c in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
            if c not in seen and 0 <= c[1] < res.height and \
                    0 <= c[0] < res.width and res.grid[c[1]][c[0]] in ".+}#":
                seen.add(c)
                todo.append(c)
    return seen


def walkable(res):
    return sum(row.count(".") + row.count("+") + row.count("#")
               for row in res.grid)


class TestThreeRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "t3.wad")
        make_test_wad.write_wad(path, make_test_wad.build())
        cls.level = Wad(path).load_level("MAP01")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_read(self):
        self.assertEqual(len(self.level.sectors), 7)
        self.assertEqual(len(self.level.things), 7)

    def check(self, res):
        self.assertLessEqual(res.width, 75)
        self.assertLessEqual(res.height, 19)
        self.assertEqual(len(res.doors), 1)
        self.assertEqual(len(res.monsters), 3)
        self.assertEqual(len(res.objects), 2)
        self.assertIsNotNone(res.upstair)
        self.assertIn(res.downstair, reachable(res, res.upstair))
        for x, y, _ in res.doors:
            self.assertEqual(res.grid[y][x], "+")
        self.assertIn("des.map(", to_lua(res))

    def test_stretch(self):
        self.check(convert(self.level))

    def test_keep_aspect(self):
        self.check(convert(self.level, Options(keep_aspect=True)))

    def test_lighting(self):
        res = convert(self.level)
        # salle C (en haut, lumière 96) sombre, salles A et B éclairées
        self.assertIn(res.downstair, res.dark)
        self.assertNotIn(res.upstair, res.dark)
        self.assertIn('des.region(dark, "unlit")', to_lua(res))
        self.assertFalse(convert(self.level, Options(dark_below=0)).dark)
        rooms = convert(self.level, Options(mode="rooms"))
        self.assertIn(rooms.downstair, rooms.dark)
        self.assertNotIn(rooms.upstair, rooms.dark)

    def test_hazards(self):
        res = convert(self.level, Options(hazards="water"))
        self.assertTrue(any("}" in row for row in res.grid))
        self.assertFalse(any("}" in row for row in convert(self.level).grid))


@unittest.skipUnless(os.path.exists(YADEX_WAD), "test.wad de Yadex absent")
class TestYadex(unittest.TestCase):
    def test_single_room(self):
        res = convert(Wad(YADEX_WAD).load_level("MAP01"))
        self.assertIn(res.downstair, reachable(res, res.upstair))


def check_parts(test, results, n):
    # la bissection peut produire moins de morceaux que demandé
    test.assertTrue(1 <= len(results) <= n)
    test.assertEqual(len({r.name for r in results}), len(results))
    for res in results:
        seen = reachable(res, res.upstair)
        test.assertIn(res.downstair, seen)
        test.assertEqual(walkable(res), len(seen))


class TestRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "t3.wad")
        make_test_wad.write_wad(path, make_test_wad.build())
        cls.level = Wad(path).load_level("MAP01")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_three_rooms(self):
        res = convert(self.level, Options(mode="rooms"))
        # salles A (avec pilier), B (avec flaque), C ; deux couloirs Doom
        self.assertEqual(res.info[0].split(",")[:2],
                         ["3 salle(s)", " 2 couloir(s) Doom"])
        self.assertTrue(any("#" in row for row in res.grid))
        self.assertIn("closed", [s for _, _, s in res.doors])
        seen = reachable(res, res.upstair)
        self.assertIn(res.downstair, seen)
        self.assertEqual(walkable(res), len(seen))
        self.assertEqual(len(res.monsters), 3)
        self.assertEqual(len(res.objects), 2)
        # escaliers et things dans des salles, pas dans les couloirs
        for x, y in (res.upstair, res.downstair):
            self.assertEqual(res.grid[y][x], ".")
        for x, y, *_ in res.monsters + res.objects:
            self.assertEqual(res.grid[y][x], ".")

    def test_rooms_split(self):
        results = convert_parts(self.level, 2, Options(mode="rooms"))
        self.assertEqual(len(results), 2)
        check_parts(self, results, 2)


class TestSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "t3.wad")
        make_test_wad.write_wad(path, make_test_wad.build())
        cls.level = Wad(path).load_level("MAP01")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_plan_covers_all_sectors(self):
        parts = plan(self.level, 3)
        secs = [s for p in parts for s in p.sectors]
        self.assertEqual(len(secs), len(set(secs)))
        self.assertEqual(set(secs), set(range(len(self.level.sectors))))
        # départ Doom dans le premier morceau, chaîne d'escaliers continue
        self.assertIsNotNone(parts[0].up_at)
        for a, b in zip(parts, parts[1:]):
            self.assertIsNotNone(a.down_at)
            self.assertIsNotNone(b.up_at)

    def test_convert_parts(self):
        for n in (2, 3):
            with self.subTest(parts=n):
                results = convert_parts(self.level, n)
                self.assertEqual(len(results), n)
                check_parts(self, results, n)
                self.assertEqual([r.name for r in results][:2],
                                 ["map01a", "map01b"])
                # les monstres sont répartis, pas dupliqués
                self.assertEqual(sum(len(r.monsters) for r in results), 3)

    def test_branch_lua(self):
        res = convert_parts(self.level, 2)
        first = to_lua(res[0], branch=True)
        self.assertIn('type = "branch"', first)
        self.assertNotIn('des.stair("up"', first)
        snippet = dungeon_snippet("Doom MAP01", [r.name for r in res])
        self.assertIn('{ name = "map01b", base = 2 }', snippet)


NETHACK = os.path.join(os.path.dirname(__file__), "..", "..",
                       "Nethack500_Lubuntu2604", "include")


@unittest.skipUnless(os.path.isdir(NETHACK), "sources NetHack absentes")
class TestTables(unittest.TestCase):
    def test_names_exist_in_nethack(self):
        from d2n import tables
        with open(os.path.join(NETHACK, "monsters.h")) as f:
            monsters = f.read()
        with open(os.path.join(NETHACK, "objects.h")) as f:
            objects = f.read()
        for name, _ in tables.MONSTERS.values():
            self.assertIn(f'MON(NAM("{name}")', monsters)
        for _, name in tables.OBJECTS.values():
            self.assertIn(f'("{name}"', objects)


DUNGEON_LUA = os.path.join(NETHACK, "..", "dat", "dungeon.lua")


@unittest.skipUnless(os.path.exists(DUNGEON_LUA), "dungeon.lua absent")
class TestDungeonPatch(unittest.TestCase):
    def test_patch_unpatch(self):
        from d2n.dungeon import patch, unpatch
        with open(DUNGEON_LUA) as f:
            orig = f.read()
        once = patch(orig, "Doom E1M1", ["e1m1a", "e1m1b"])
        self.assertEqual(patch(once, "Doom E1M1", ["e1m1a", "e1m1b"]), once)
        self.assertIn('{ name = "e1m1b", base = 2 }', once)
        # la branche est déclarée dans les Dungeons of Doom
        main = once.index('name = "The Dungeons of Doom"')
        gnomes = once.index('name = "The Gnomish Mines"')
        self.assertTrue(main < once.index('name = "Doom E1M1"') < gnomes)
        both = patch(once, "Doom MAP01", ["map01a"])
        self.assertEqual(unpatch(both, "Doom MAP01"), once)
        self.assertEqual(unpatch(both), orig)


FREEDOOM = os.path.join(os.path.dirname(__file__), "..", "..",
                        "freedoom-0.13.0")


@unittest.skipUnless(os.path.isdir(FREEDOOM), "Freedoom absent")
class TestFreedoom(unittest.TestCase):
    def test_all_levels_connected(self):
        for wad_name in ("freedoom1.wad", "freedoom2.wad"):
            wad = Wad(os.path.join(FREEDOOM, wad_name))
            for name in wad.level_names():
                with self.subTest(level=name):
                    res = convert(wad.load_level(name))
                    seen = reachable(res, res.upstair)
                    self.assertIn(res.downstair, seen)
                    self.assertEqual(walkable(res), len(seen))

    def test_rooms_all_levels(self):
        opts = Options(mode="rooms")
        for wad_name in ("freedoom1.wad", "freedoom2.wad"):
            wad = Wad(os.path.join(FREEDOOM, wad_name))
            for name in wad.level_names():
                with self.subTest(level=name):
                    res = convert(wad.load_level(name), opts)
                    seen = reachable(res, res.upstair)
                    self.assertIn(res.downstair, seen)
                    self.assertEqual(walkable(res), len(seen))

    def test_rooms_split_levels(self):
        opts = Options(mode="rooms")
        for wad_name, name in (("freedoom1.wad", "E1M1"),
                               ("freedoom2.wad", "MAP12"),
                               ("freedoom2.wad", "MAP20")):
            level = Wad(os.path.join(FREEDOOM, wad_name)).load_level(name)
            n = auto_parts(level, opts)
            with self.subTest(level=name, parts=n):
                check_parts(self, convert_parts(level, n, opts), n)

    def test_split_levels(self):
        for wad_name, name in (("freedoom1.wad", "E1M1"),
                               ("freedoom1.wad", "E1M8"),
                               ("freedoom2.wad", "MAP01"),
                               ("freedoom2.wad", "MAP20")):
            level = Wad(os.path.join(FREEDOOM, wad_name)).load_level(name)
            n = auto_parts(level, Options())
            with self.subTest(level=name, parts=n):
                check_parts(self, convert_parts(level, n), n)


if __name__ == "__main__":
    unittest.main()
