"""Repeatability and sanity checks.  Run:  python3 -m unittest -v"""
import unittest

from dune_sim.cli import run_games, run_one, summarize, wilson
from dune_sim.engine import Game
from dune_sim.strategies import PROFILES, make_strategy

SPECS = ["balanced", "military", "spice", "random"]


def strip(res):
    return [(p["strategy"], p["vp"], p["spice"], p["solari"], p["water"], p["deck_size"])
            for p in res["players"]] + [res["rounds"], res["winners"]]


class Repeatable(unittest.TestCase):
    def test_same_seed_same_game(self):
        self.assertEqual(strip(run_one((SPECS, 11, True))), strip(run_one((SPECS, 11, True))))

    def test_different_seed_differs(self):
        self.assertNotEqual(strip(run_one((SPECS, 11, True))), strip(run_one((SPECS, 12, True))))

    def test_workers_do_not_change_results(self):
        a = run_games(SPECS, 6, seed=3, workers=1)
        b = run_games(SPECS, 6, seed=3, workers=3)
        self.assertEqual([strip(r) for r in a], [strip(r) for r in b])


class Sanity(unittest.TestCase):
    def test_game_ends_within_ten_rounds(self):
        for seed in range(5):
            res = run_one((SPECS, seed, True))
            self.assertLessEqual(res["rounds"], 10)
            self.assertTrue(res["winners"])

    def test_every_profile_plays_a_full_game(self):
        for name in PROFILES:
            res = Game([make_strategy(name), make_strategy("random", 1)], seed=5).play()
            self.assertTrue(res["winners"], name)

    def test_balanced_beats_random(self):
        results = run_games(["balanced", "random", "random", "random"], 12, seed=1, workers=1)
        rows, _ = summarize(results, ["balanced", "random", "random", "random"])
        self.assertEqual(rows[0]["strategy"], "balanced")
        self.assertGreaterEqual(rows[0]["win_pct"], 90)

    def test_wilson_interval(self):
        lo, hi = wilson(100, 400)
        self.assertAlmostEqual(lo, 21.0, delta=0.3)
        self.assertAlmostEqual(hi, 29.5, delta=0.3)


if __name__ == "__main__":
    unittest.main()
