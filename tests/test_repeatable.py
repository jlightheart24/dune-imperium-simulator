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


class Leaders(unittest.TestCase):
    def test_random_leaders_are_distinct_and_repeatable(self):
        a = run_one((SPECS, 9, True, True))
        b = run_one((SPECS, 9, True, True))
        names = [p["leader"] for p in a["players"]]
        self.assertEqual(len(set(names)), 4)
        self.assertEqual(names, [p["leader"] for p in b["players"]])
        self.assertEqual(strip(a), strip(b))

    def test_leader_draw_varies_by_matchup_and_is_even(self):
        from collections import Counter
        from dune_sim.cli import draw_leaders
        a = draw_leaders(5, ["balanced", "military", "spice", "random"])
        b = draw_leaders(5, ["balanced", "military", "spice", "alliances"])
        self.assertNotEqual(a, b)                         # same seed, different line-up
        self.assertEqual(a, draw_leaders(5, ["balanced", "military", "spice", "random"]))
        counts = Counter(l for s in range(400) for l in draw_leaders(s, ["a", "b", "c", "d"]))
        self.assertEqual(len(counts), 8)
        for c in counts.values():                         # expected 200 each
            self.assertTrue(140 < c < 260, counts)

    def test_fixed_leader_gives_same_opponent_leaders_for_any_strategy(self):
        from dune_sim.cli import draw_leaders
        fixed = {0: "Paul Atreides"}
        a = draw_leaders(3, ["military", "balanced", "balanced", "balanced"], fixed)
        b = draw_leaders(3, ["rush_both", "balanced", "balanced", "balanced"], fixed)
        self.assertEqual(a, b)
        self.assertEqual(a[0], "Paul Atreides")
        self.assertEqual(len(set(a)), 4)

    def test_no_leaders_by_default_in_engine(self):
        self.assertTrue(all(p["leader"] is None for p in run_one((SPECS, 9, True))["players"]))

    def test_every_leader_plays_full_games_without_fallbacks(self):
        from dune_sim import data
        names = [ld["name"] for ld in data.LEADERS]
        for i in range(0, 8, 4):
            for seed in (1, 2):
                g = Game([make_strategy("balanced") for _ in range(4)], seed=seed, leaders=names[i:i + 4])
                res = g.play()
                self.assertTrue(res["winners"])
                self.assertEqual(sum(p["fallbacks"] for p in res["players"]), 0)

    def test_leader_abilities(self):
        from dune_sim import data
        from dune_sim.data import SPACE_BY_NAME
        mk = lambda nm: Game([make_strategy("random", 1), make_strategy("random", 2)], seed=1,  # noqa: E731
                             leaders=[nm, "Paul Atreides" if nm != "Paul Atreides" else "Count Ilban Richese"])
        g = mk('Glossu "The Beast" Rabban')
        self.assertEqual((g.players[0].spice, g.players[0].solari), (1, 1))      # starting bonus
        self.assertEqual((g.players[1].spice, g.players[1].solari), (0, 0))
        g = mk("Duke Leto Atreides")                                             # Landsraad discount
        self.assertEqual(g.space_cost(g.players[0], SPACE_BY_NAME["High Council"]), {"solari": 4})
        self.assertEqual(g.space_cost(g.players[1], SPACE_BY_NAME["High Council"]), {"solari": 5})
        self.assertEqual(g.space_cost(g.players[0], SPACE_BY_NAME["Conspire"]), {"spice": 4})
        g = mk("Helena Richese")                                                 # shares Landsraad/city spaces
        g.occupied["Arrakeen"] = 1
        g.occupied["Wealth"] = 1
        self.assertTrue(g.space_ok(g.players[0], SPACE_BY_NAME["Arrakeen"]))
        self.assertFalse(g.space_ok(g.players[0], SPACE_BY_NAME["Wealth"]))
        g = mk("Count Memnon Thorvald")                                          # influence with the council seat
        before = sum(g.players[0].influence.values())
        g.special(g.players[0], "high_council", {})
        self.assertEqual(sum(g.players[0].influence.values()), before + 1)
        self.assertEqual(len(data.LEADERS), 8)

    def test_leto_gains_influence_only_where_he_trails(self):
        from dune_sim.data import LEADER_BY_NAME
        class Keen(type(make_strategy("balanced"))):
            def choose_option(self, game, p, branches):   # always takes the "you may"
                return len(branches) - 1
        g = Game([Keen(), make_strategy("balanced")], seed=1,
                 leaders=["Duke Leto Atreides", "Paul Atreides"])
        leto, other = g.players
        signet = LEADER_BY_NAME["Duke Leto Atreides"]["signet"]
        leto.spice = 3
        g.apply_ops(leto, signet, {})                      # nobody is ahead: nothing happens
        self.assertEqual((sum(leto.influence.values()), leto.spice), (0, 3))
        other.influence["guild"] = 1
        g.apply_ops(leto, signet, {})                      # only the Guild qualifies
        self.assertEqual((leto.influence["guild"], sum(leto.influence.values()), leto.spice),
                         (1, 1, 2))
        g.apply_ops(leto, signet, {})                      # level again: nothing happens
        self.assertEqual((sum(leto.influence.values()), leto.spice), (1, 2))

    def test_baron_masterstroke_needs_four_troops_in_one_turn(self):
        class Deploy(type(make_strategy("balanced"))):
            n = 0
            def choose_deploy(self, game, p, max_n):
                return min(self.n, max_n)
        def turn(n, garrison=6):
            st = Deploy()
            st.n = n
            g = Game([st, make_strategy("balanced")], seed=1,
                     leaders=["Baron Vladimir Harkonnen", "Paul Atreides"])
            g.round, g.phase = 3, "player turns"
            b = g.players[0]
            b.garrison, b.water = garrison, 1
            card = next(c for c in b.all_cards() if "fremen" in c.icons)
            b.hand = [card]
            return g, b, 0
        g, b, hi = turn(3)
        g.agent_turn(0, hi, "Hardy Warriors")              # 3 troops: no Masterstroke
        self.assertEqual((sum(b.influence.values()), b.masterstroke_used), (1, False))
        g, b, hi = turn(4)
        g.agent_turn(0, hi, "Hardy Warriors")              # 4 troops: +1 with two factions
        self.assertEqual((b.conflict, sum(b.influence.values()), b.masterstroke_used),
                         (4, 3, True))
        before = sum(b.influence.values())                 # once per game
        card = next(c for c in b.all_cards() if "fremen" in c.icons)
        b.hand, b.agents_used, b.garrison = [card], 0, 6
        g.agent_turn(0, 0, "Stillsuits")
        self.assertEqual(sum(b.influence.values()), before + 1)

    def test_helena_reserves_a_card_and_buys_it_cheaper(self):
        from dune_sim.engine import held_price
        g = Game([make_strategy("balanced"), make_strategy("balanced")], seed=3,
                 leaders=["Helena Richese", "Paul Atreides"])
        p = g.players[0]
        row_before = list(g.imperium_row)
        g.apply_ops(p, p.leader["signet"], {})
        c = p.held
        self.assertIn(c, row_before)
        self.assertEqual(len(g.imperium_row), len(row_before))        # the row refilled
        self.assertEqual(sum(x is c for x in g.imperium_row),
                         sum(x is c for x in row_before) - 1)         # one copy left the row
        # with exactly the discounted price in persuasion she can buy it
        p.hand, p.persuasion, p.seat = [], held_price(c), False
        owned = len(p.all_cards())
        g.strategies[0].choose_purchase = lambda game, pl, options, budget: (
            c if any(o is c for o in options) else None)
        g.reveal_turn(0)
        self.assertIsNone(p.held)
        self.assertEqual(len(p.all_cards()), owned + 1)
        self.assertIn(c, p.discard)

    def test_unbought_reserved_card_leaves_the_game(self):
        g = Game([make_strategy("balanced") for _ in range(4)], seed=5,
                 leaders=["Helena Richese", "Paul Atreides", "Duke Leto Atreides", "Count Ilban Richese"])
        g.play()
        self.assertTrue(all(p.held is None for p in g.players))


class WaterSetting(unittest.TestCase):
    def tearDown(self):
        from dune_sim.strategies import set_water_mode
        set_water_mode("capped")

    def test_flat_water_reproduces_the_hw11_cases(self):
        import json, os, tempfile
        from dune_sim.strategies import set_water_mode
        set_water_mode("flat")
        old = json.load(open(os.path.join(os.path.dirname(__file__), "..", "results",
                                          "vertical_slice", "cases.json")))["cases"]
        for c in old[:5]:
            spec = json.load(open(os.path.join(os.path.dirname(__file__), "..", "cases",
                                               "vertical_slice.json")))
            players = next(x for x in spec if x["id"] == c["id"])["players"]
            summary, _ = run_trace(players, 7, 0, None)
            self.assertEqual(summary["final_vp"][0], c["vp"], c["id"])
            self.assertEqual(summary["measures"]["decisions"], c["decisions"], c["id"])

    def test_capped_water_is_worth_less_beyond_four(self):
        from dune_sim.strategies import set_water_mode
        g = Game([make_strategy("balanced"), make_strategy("balanced")], seed=1)
        s = make_strategy("balanced")
        step = lambda n: s.water_value(g, g.players[0], n + 1) - s.water_value(g, g.players[0], n)  # noqa: E731
        self.assertGreater(step(3), 5 * step(4))
        set_water_mode("flat")
        s = make_strategy("balanced")
        self.assertAlmostEqual(step(3), step(4))


class Blocking(unittest.TestCase):
    """`deny` makes opponents' victory points count against the player."""

    def game(self):
        g = Game([make_strategy("blocker")] + [make_strategy("balanced")] * 3, seed=3)
        g.phase = "player turns"
        g.conflict_card = {"name": "t", "rewards": [[{"gain": {"vp": 1}}],
                                                    [{"gain": {"solari": 4}}],
                                                    [{"gain": {"solari": 2}}]]}
        for q in g.players:
            q.revealed, q.conflict, q.swords = True, 0, 0
        return g

    def test_balanced_ignores_opponents(self):
        g = self.game()
        g.players[1].vp, g.players[1].conflict = 9, 3
        self.assertEqual(make_strategy("balanced").threat(g, g.players[0], 0), 0.0)

    def test_outfighting_an_opponent_lowers_the_threat(self):
        g = self.game()
        g.players[1].conflict = 2             # strength 4, winning the VP
        s = make_strategy("blocker")
        self.assertGreater(s.threat(g, g.players[0], 0), s.threat(g, g.players[0], 6))

    def test_the_winning_point_counts_for_more(self):
        s = make_strategy("blocker")
        saved = []
        for vp in (5, 9):
            g = self.game()
            g.players[0].vp = 5
            g.players[1].vp, g.players[1].conflict = vp, 2
            saved.append(s.threat(g, g.players[0], 0) - s.threat(g, g.players[0], 6))
        self.assertGreater(saved[1], 2 * saved[0])

    def test_blocker_sends_troops_to_stop_the_winning_point(self):
        g = self.game()
        me, rival = g.players[0], g.players[1]
        me.vp, rival.vp, rival.conflict = 9, 9, 1      # rival strength 2
        me.garrison = 3
        g.conflict_card["rewards"][0] = [{"gain": {"vp": 1}}]
        self.assertGreaterEqual(make_strategy("blocker").choose_deploy(g, me, 2), 2)

    def test_open_scoring_space_is_a_threat_until_taken(self):
        g = self.game()
        g.conflict_card = None
        rival = g.players[1]
        rival.revealed, rival.influence["emperor"] = False, 1
        for q in g.players[2:]:
            q.influence = {f: 0 for f in q.influence}
        rival.influence.update({"guild": 0, "bene_gesserit": 0, "fremen": 0})
        s = make_strategy("blocker")
        before = s.threat(g, g.players[0], 0)
        g.occupied["Wealth"] = 0
        g.occupied["Conspire"] = 0
        self.assertGreater(before, s.threat(g, g.players[0], 0))

    def test_blocking_strategies_play_full_games(self):
        res = run_one((["blocker", "rush_both_block", "balanced", "balanced"], 5, True))
        self.assertEqual(sum(p["fallbacks"] for p in res["players"]), 0)


class Rollouts(unittest.TestCase):
    def mid_round_game(self, seed=4):
        """A four-player game stopped in round 3 after a few turns, with intrigue in hand."""
        g = Game([make_strategy(s, seed=k) for k, s in enumerate(["balanced"] * 4)], seed=seed)
        g.play_round()
        g.play_round()
        g.round += 1
        g.conflict_card = g.conflict_deck.pop()
        for p in g.players:
            g.draw(p, 5)
        g.phase = "player turns"
        for pi in range(3):
            g.do_action(pi, g.legal_actions(g.players[pi])[0])
        return g

    def test_redeal_keeps_what_the_viewer_can_see(self):
        g = self.mid_round_game()
        names = lambda cards: sorted(c.name for c in cards)  # noqa: E731
        changed = 0
        for s in range(10):
            c = g.clone(hide_for=0, seed=s)
            self.assertEqual([x.name for x in c.players[0].hand], [x.name for x in g.players[0].hand])
            self.assertEqual(names(c.players[0].intrigue), names(g.players[0].intrigue))
            for p, q in zip(g.players, c.players):
                self.assertEqual(len(q.hand), len(p.hand))
                self.assertEqual(names(q.hand + q.deck), names(p.hand + p.deck))
                self.assertEqual(names(q.discard), names(p.discard))
                self.assertEqual(names(q.in_play), names(p.in_play))
                self.assertEqual(len(q.intrigue), len(p.intrigue))
                if p.idx and names(q.hand) != names(p.hand):
                    changed += 1
            all_intrigue = lambda x: names(x.intrigue_deck + [i for q in x.players for i in q.intrigue])  # noqa: E731
            self.assertEqual(all_intrigue(c), all_intrigue(g))
            self.assertEqual([x["level"] for x in c.conflict_deck], [x["level"] for x in g.conflict_deck])
        self.assertGreater(changed, 0, "opponents' hands were never re-dealt")

    def test_same_seed_same_guess(self):
        g = self.mid_round_game()
        a, b = g.clone(hide_for=0, seed=9), g.clone(hide_for=0, seed=9)
        self.assertEqual([[x.name for x in q.hand] for q in a.players],
                         [[x.name for x in q.hand] for q in b.players])

    def test_rollout_agent_plays_repeatable_games_without_fallbacks(self):
        specs = ["balanced_rollout", "balanced", "balanced", "balanced"]
        a, b = run_one((specs, 3, True)), run_one((specs, 3, True))
        self.assertEqual(strip(a), strip(b))
        self.assertEqual(sum(p["fallbacks"] for p in a["players"]), 0)
        for p in a["players"]:   # seats are shuffled
            if p["strategy"] == "balanced_rollout":
                self.assertGreater(p["rollout_decisions"], 0)
            else:
                self.assertEqual(p["rollout_decisions"], 0)

    def test_rollouts_are_off_by_default(self):
        for name in ("balanced", "bene_gesserit_faction", "rush_swordmaster", "rush_both"):
            self.assertEqual(make_strategy(name).w["rollouts"], 0)


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
