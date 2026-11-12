"""Repeatability and sanity checks.  Run:  python3 -m unittest -v"""
import unittest

from dune_sim.cli import (UsageError, check_players, main, run_games, run_one, run_trace,
                          summarize, wilson)
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


class FailureHandling(unittest.TestCase):
    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(UsageError):
            check_players(["balanced", "no_such_strategy"])

    def test_table_size_is_checked(self):
        for specs in (["balanced"], ["balanced"] * 5):
            with self.assertRaises(UsageError):
                check_players(specs)

    def test_cli_returns_exit_code_2_without_running(self):
        self.assertEqual(main(["batch", "-n", "1", "-p", "balanced", "no_such_strategy"]), 2)

    def test_faulty_agent_is_contained(self):
        specs = ["dune_sim.faulty:FaultyAgent", "balanced", "balanced", "balanced"]
        game = Game([make_strategy(s) for s in specs], seed=7, record=True)
        res = game.play()
        self.assertGreater(res["players"][0]["fallbacks"], 0)       # faults happened
        self.assertEqual(sum(p["fallbacks"] for p in res["players"][1:]), 0)
        self.assertTrue(res["winners"])                              # and the game still finished
        notes = [n for f in game.frames for n in f.get("notes", [])]
        self.assertTrue(any(n.startswith("FALLBACK") for n in notes))

    def test_builtin_agents_never_fall_back(self):
        res = run_one((SPECS, 4, True))
        self.assertEqual(sum(p["fallbacks"] for p in res["players"]), 0)


class Trace(unittest.TestCase):
    def test_decisions_are_recorded_with_scores(self):
        summary, replay = run_trace(["balanced", "random", "random", "random"], 7, 0, None)
        decisions = [f["decision"] for f in replay["frames"] if f.get("decision", {}).get("actor") == 0]
        self.assertEqual(len(decisions), summary["measures"]["decisions"])
        for d in decisions:
            self.assertEqual(sum(o["chosen"] for o in d["options"]), 1)
            self.assertEqual(len(d["options"]), d["n_options"])
            if not d["rule"]:
                self.assertTrue(all(o["score"] is not None for o in d["options"]))
                best = max(o["score"] for o in d["options"])
                self.assertEqual(next(o for o in d["options"] if o["chosen"])["score"], best)

    def test_terminal_status_is_explicit(self):
        res = run_one((SPECS, 2, True))
        self.assertIn(res["end_reason"], ("10 VP reached", "conflict deck exhausted"))
        if res["end_reason"] == "conflict deck exhausted":
            self.assertEqual(res["rounds"], 10)


if __name__ == "__main__":
    unittest.main()
