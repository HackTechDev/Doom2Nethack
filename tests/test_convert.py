import os
import sys
import tempfile
import unittest
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from d2n.convert import Options, convert          # noqa: E402
from d2n.lua_out import to_lua                    # noqa: E402
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
                    0 <= c[0] < res.width and res.grid[c[1]][c[0]] in ".+}":
                seen.add(c)
                todo.append(c)
    return seen


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

    def test_hazards(self):
        res = convert(self.level, Options(hazards="water"))
        self.assertTrue(any("}" in row for row in res.grid))
        self.assertFalse(any("}" in row for row in convert(self.level).grid))


@unittest.skipUnless(os.path.exists(YADEX_WAD), "test.wad de Yadex absent")
class TestYadex(unittest.TestCase):
    def test_single_room(self):
        res = convert(Wad(YADEX_WAD).load_level("MAP01"))
        self.assertIn(res.downstair, reachable(res, res.upstair))


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
                    walkable = sum(row.count(".") + row.count("+")
                                   for row in res.grid)
                    self.assertEqual(walkable, len(seen))


if __name__ == "__main__":
    unittest.main()
