"""Command line interface.

  python -m dune_sim batch -n 500 -p military spice factions balanced
  python -m dune_sim watch -p military spice factions random --seed 7 --open
  python -m dune_sim benchmark -n 400 --save benchmark_v1
  python -m dune_sim list
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import itertools
import json
import math
import os
import platform
import random
import subprocess
import sys
import textwrap
import webbrowser
from collections import defaultdict
from multiprocessing import Pool

from .data import LEADERS
from .engine import Game, SPACES, fmt_ops
from .strategies import BLOCKING, FOCUS, ROLLOUT, WATER_MODES, available_strategies, make_strategy, set_water_mode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_PLAYERS, MAX_PLAYERS = 2, 4


class UsageError(Exception):
    """Unsupported input. Reported as a one-line error with exit code 2; no game is run."""


def check_players(specs):
    """Validate a player list before any game starts. Raises UsageError with the reason."""
    if not MIN_PLAYERS <= len(specs) <= MAX_PLAYERS:
        raise UsageError(f"unsupported table size: {len(specs)} players given, "
                         f"the game supports {MIN_PLAYERS} to {MAX_PLAYERS}")
    for spec in specs:
        try:
            make_strategy(spec, seed=0)
        except FileNotFoundError as e:
            raise UsageError(f"cannot load strategy {spec!r}: weights file not found ({e.filename})")
        except (ValueError, ImportError, AttributeError, TypeError) as e:
            raise UsageError(f"unknown or unloadable strategy {spec!r} ({e}). "
                             "Run `python3 -m dune_sim list` to see the built-in names")
VIEWER_TEMPLATE = os.path.join(ROOT, "viewer", "viewer.html")


def draw_leaders(seed, specs, fixed=None):
    """One distinct leader per entry of `specs` (same order as specs, before seating).

    The draw depends on the seed AND the line-up, so the same seed gives different leaders
    in different matchups, and a strategy's position in the list does not tie it to one
    leader per seed. `fixed` maps a spec index to a leader name that must be used there;
    the remaining players get distinct random leaders from the rest.
    """
    if fixed:
        # controlled tests: the other leaders depend only on the seed and the fixed leaders,
        # so every strategy tested in the fixed slot faces the same opponents' leaders
        rng = random.Random(f"leaders|{seed}|{len(specs)}|{sorted(fixed.items())}")
    else:
        fixed = {}
        rng = random.Random(f"leaders|{seed}|{'|'.join(specs)}")
    pool = [ld["name"] for ld in LEADERS if ld["name"] not in fixed.values()]
    rest = rng.sample(pool, len(specs) - len(fixed))
    return [fixed[i] if i in fixed else rest.pop() for i in range(len(specs))]


def run_one(args):
    """args = (specs, seed, rotate[, leaders]); leaders is False/None (no leaders), True
    (random distinct leaders), or a dict {spec index: leader name} to fix some of them."""
    specs, seed, rotate = args[:3]
    leaders = args[3] if len(args) > 3 else None
    rng = random.Random(seed)
    order = list(range(len(specs)))
    if rotate:
        rng.shuffle(order)  # random seating so first-player advantage averages out
    seated = [specs[i] for i in order]
    seat_leaders = None
    if leaders:
        drawn = draw_leaders(seed, specs, leaders if isinstance(leaders, dict) else None)
        seat_leaders = [drawn[i] for i in order]
    strategies = [make_strategy(s, seed=seed * 31 + k) for k, s in enumerate(seated)]
    names = [f"P{k + 1}" for k in range(len(seated))]
    g = Game(strategies, seed=seed, names=names, leaders=seat_leaders)
    res = g.play()
    res["specs"] = seated
    return res


def run_games(specs, games, seed, fixed_seats=False, workers=0, leaders=False):
    """Play `games` seeded games (seeds seed .. seed+games-1). Deterministic for a given
    (specs, games, seed, fixed_seats), whatever the number of worker processes."""
    jobs = [(specs, seed + i, not fixed_seats, leaders) for i in range(games)]
    results = []
    workers = workers or os.cpu_count() or 1
    if workers > 1 and games > 1:
        with Pool(workers) as pool:
            for i, r in enumerate(pool.imap_unordered(run_one, jobs, chunksize=4)):
                results.append(r)
                _progress(i + 1, games)
    else:
        for i, j in enumerate(jobs):
            results.append(run_one(j))
            _progress(i + 1, games)
    if sys.stderr.isatty():
        sys.stderr.write("\n")
    results.sort(key=lambda r: r["seed"])
    return results


def wilson(wins, n, z=1.96):
    """95% Wilson score interval for a win proportion, as percentages."""
    if n == 0:
        return (0.0, 0.0)
    ph = wins / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return (100 * max(0.0, (c - h) / d), 100 * min(1.0, (c + h) / d))


def summarize(results, specs):
    """Per-strategy aggregate rows (dicts), best win rate first, plus win share by seat."""
    stats = defaultdict(lambda: defaultdict(float))
    vps = defaultdict(list)
    seat_wins = defaultdict(float)
    for r in results:
        share = 1.0 / len(r["winners"])
        for seat, (spec, pr) in enumerate(zip(r["specs"], r["players"])):
            s = stats[spec]
            s["seats"] += 1
            vps[spec].append(pr["vp"])
            s["rank"] += pr["rank"]
            s["alliances"] += len(pr["alliances"])
            s["deck"] += pr["deck_size"]
            s["solari"] += pr["solari"]
            s["sword"] += pr["agents"] >= 3
            s["seat"] += pr["seat"]
            s["mentat"] += pr["mentat_uses"]
            if seat in r["winners"]:
                s["wins"] += share
                seat_wins[seat] += share
    rows = []
    for spec, s in stats.items():
        n = s["seats"]
        lo, hi = wilson(s["wins"], n)
        v = vps[spec]
        mean = sum(v) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in v) / max(1, n - 1))
        rows.append({
            "strategy": spec, "seats": int(n), "wins": round(s["wins"], 3),
            "win_pct": 100 * s["wins"] / n, "ci_low": lo, "ci_high": hi,
            "avg_vp": mean, "vp_sd": sd, "vp_se": sd / math.sqrt(n),
            "avg_rank": s["rank"] / n, "alliances": s["alliances"] / n,
            "deck": s["deck"] / n, "end_solari": s["solari"] / n,
            "swordmaster_pct": 100 * s["sword"] / n, "council_pct": 100 * s["seat"] / n,
            "mentats": s["mentat"] / n,
        })
    rows.sort(key=lambda r: -r["win_pct"])
    seats = {f"P{k + 1}": 100 * seat_wins[k] / len(results) for k in range(len(specs))}
    return rows, seats


def print_leaders(results, n_players):
    """Win rate by leader, pooled over every strategy that played them."""
    st = defaultdict(lambda: defaultdict(float))
    for r in results:
        share = 1.0 / len(r["winners"])
        for seat, pr in enumerate(r["players"]):
            if pr.get("leader"):
                s = st[pr["leader"]]
                s["n"] += 1
                s["vp"] += pr["vp"]
                s["rank"] += pr["rank"]
                s["wins"] += share if seat in r["winners"] else 0
    if not st:
        return []
    fair = 100.0 / n_players
    print(f"\nby leader (randomly assigned each game; fair share {fair:.1f}%)")
    hdr = f"{'leader':<30}{'games':>7}{'win %':>8}{'95% CI':>14}{'avg VP':>9}{'avg rank':>10}"
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for name, s in sorted(st.items(), key=lambda kv: -kv[1]["wins"] / kv[1]["n"]):
        lo, hi = wilson(s["wins"], s["n"])
        rows.append({"leader": name, "games": int(s["n"]), "win_pct": 100 * s["wins"] / s["n"],
                     "ci_low": lo, "ci_high": hi, "avg_vp": s["vp"] / s["n"], "avg_rank": s["rank"] / s["n"]})
        ci = f"{lo:.1f}-{hi:.1f}"
        print(f"{name:<30}{int(s['n']):>7}{rows[-1]['win_pct']:>7.1f}%{ci:>14}"
              f"{rows[-1]['avg_vp']:>9.2f}{rows[-1]['avg_rank']:>10.2f}")
    return rows


def print_table(rows, n_players, games, avg_rounds):
    print(f"\n{games} games, {n_players} players, avg {avg_rounds:.1f} rounds\n")
    sw = max(28, max(len(r["strategy"]) for r in rows) + 2)
    hdr = (f"{'strategy':<{sw}}{'win %':>8}{'95% CI':>14}{'avg VP':>9}{'avg rank':>10}{'alliances':>11}"
           f"{'deck':>7}{'end $':>7}{'3rd agent':>11}{'council':>9}{'mentats':>9}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ci = f"{r['ci_low']:.1f}-{r['ci_high']:.1f}"
        print(f"{r['strategy']:<{sw}}{r['win_pct']:>7.1f}%{ci:>14}{r['avg_vp']:>9.2f}{r['avg_rank']:>10.2f}"
              f"{r['alliances']:>11.2f}{r['deck']:>7.1f}{r['end_solari']:>7.1f}"
              f"{r['swordmaster_pct']:>10.0f}%{r['council_pct']:>8.0f}%{r['mentats']:>9.1f}")
    print(f"\n(fair share = {100 / n_players:.1f}% per seat; 95% CI = Wilson interval on win %;"
          " end $ = solari left at game end; mentats = Mentat uses per game)")


def write_games_csv(path, results):
    with open(path, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["seed", "rounds", "seat", "strategy", "vp", "rank", "won",
                     "spice", "solari", "water", "deck_size", "alliances", "leader"])
        for r in sorted(results, key=lambda r: r["seed"]):
            for seat, (spec, pr) in enumerate(zip(r["specs"], r["players"])):
                wr.writerow([r["seed"], r["rounds"], seat + 1, spec, pr["vp"], pr["rank"],
                             int(seat in r["winners"]), pr["spice"], pr["solari"],
                             pr["water"], pr["deck_size"], "|".join(pr["alliances"]),
                             pr.get("leader") or ""])


class _Tee:
    """Mirror stdout into a buffer so a run's printed report can be saved verbatim."""
    def __init__(self, stream):
        self.stream, self.buf = stream, io.StringIO()

    def write(self, s):
        self.stream.write(s)
        self.buf.write(s)

    def flush(self):
        self.stream.flush()


def run_meta(a, extra=None):
    commit = None
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        pass
    dirty = None
    try:
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", "dune_sim"],
                                             cwd=ROOT, stderr=subprocess.DEVNULL).strip())
    except Exception:
        pass
    meta = {
        "command": "python3 -m dune_sim " + " ".join(sys.argv[1:]),
        "code_differs_from_commit": dirty,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(), "platform": platform.platform(),
        "git_commit": commit, "seed": a.seed, "games": a.games,
        "leaders": "random" if getattr(a, "leaders", False) else "none",
        "water": getattr(a, "water", "capped"),
    }
    meta.update(extra or {})
    return meta


def save_run(name, text, payload, results_by_file):
    """Write results/<name>/{summary.txt, results.json, *.csv}."""
    out = name if os.path.isabs(name) or os.sep in name else os.path.join(ROOT, "results", name)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "summary.txt"), "w") as fh:
        fh.write("$ " + payload["meta"]["command"] + "\n" + text)
    with open(os.path.join(out, "results.json"), "w") as fh:
        json.dump(payload, fh, indent=1)
    for fname, results in results_by_file.items():
        write_games_csv(os.path.join(out, fname), results)
    print(f"\nsaved to {out}/ (summary.txt, results.json, {', '.join(results_by_file)})")


def cmd_batch(a):
    specs = a.players
    check_players(specs)
    tee = _Tee(sys.stdout) if a.save else None
    if tee:
        sys.stdout = tee
    try:
        results = run_games(specs, a.games, a.seed, a.fixed_seats, a.workers, a.leaders)
        rows, seats = summarize(results, specs)
        avg_rounds = sum(r["rounds"] for r in results) / len(results)
        print_table(rows, len(specs), a.games, avg_rounds)
        by_vp = sum(r["end_reason"] == "10 VP reached" for r in results)
        print(f"games ended by: 10 VP reached {100 * by_vp / len(results):.0f}%, "
              f"conflict deck exhausted {100 - 100 * by_vp / len(results):.0f}%")
        leader_rows = print_leaders(results, len(specs))
        if a.detail:
            print_detail(results)
        if a.fixed_seats:
            print("win % by seat: " + ", ".join(f"{k} {v:.1f}%" for k, v in seats.items()))
    finally:
        if tee:
            sys.stdout = tee.stream
    if a.csv:
        write_games_csv(a.csv, results)
        print(f"per-game results written to {a.csv}")
    if a.save:
        meta = run_meta(a, {"players": specs, "fixed_seats": a.fixed_seats, "avg_rounds": avg_rounds})
        save_run(a.save, tee.buf.getvalue(), {"meta": meta, "strategies": rows, "win_pct_by_seat": seats,
                                               "leaders": leader_rows},
                 {"games.csv": results})


def cmd_benchmark(a):
    """Each strategy in one seat against (n-1) copies of the baseline, same seeds for all."""
    base = a.baseline
    targets = a.strategies or [s.split(":", 1)[-1] for s in available_strategies()
                               if s.split(":", 1)[-1] != base
                               and s.split(":", 1)[-1] not in BLOCKING + ROLLOUT]
    if targets == ["focus"]:
        targets = list(FOCUS)
    if targets == ["blocking"]:
        targets = list(BLOCKING)
    if targets == ["rollout"]:
        targets = list(ROLLOUT)
    check_players([base] * a.table)
    for t in targets:
        check_players([t, base])
    fair = 100.0 / a.table
    tee = _Tee(sys.stdout) if a.save else None
    if tee:
        sys.stdout = tee
    out_rows, per_file = [], {}
    try:
        print(f"Benchmark: 1 x <strategy> vs {a.table - 1} x {base}, {a.games} games each, "
              f"seeds {a.seed}..{a.seed + a.games - 1}, seating shuffled per game")
        print(f"fair share = {fair:.1f}%\n")
        hdr = (f"{'strategy':<28}{'win %':>8}{'95% CI':>14}{'avg VP':>9}{'+/-SE':>7}"
               f"{'base VP':>9}{'avg rank':>10}  verdict")
        print(hdr)
        print("-" * len(hdr))
        for t in targets:
            specs = [t] + [base] * (a.table - 1)
            results = run_games(specs, a.games, a.seed, False, a.workers, a.leaders)
            rows, _ = summarize(results, specs)
            row = next(r for r in rows if r["strategy"] == t)
            brow = next((r for r in rows if r["strategy"] == base), row)
            verdict = ("better than baseline" if row["ci_low"] > fair else
                       "worse than baseline" if row["ci_high"] < fair else "no clear difference")
            row = dict(row, baseline_avg_vp=brow["avg_vp"], verdict=verdict)
            out_rows.append(row)
            per_file[f"games_{t.replace(':', '_').replace('/', '_')}.csv"] = results
            ci = f"{row['ci_low']:.1f}-{row['ci_high']:.1f}"
            print(f"{t:<28}{row['win_pct']:>7.1f}%{ci:>14}{row['avg_vp']:>9.2f}{row['vp_se']:>7.2f}"
                  f"{brow['avg_vp']:>9.2f}{row['avg_rank']:>10.2f}  {verdict}")
            sys.stdout.flush()
        print("\nverdict: 'better'/'worse' when the 95% interval on win % excludes the fair share.")
    finally:
        if tee:
            sys.stdout = tee.stream
    if a.save:
        meta = run_meta(a, {"baseline": base, "table": a.table, "fair_share_pct": fair})
        save_run(a.save, tee.buf.getvalue(), {"meta": meta, "strategies": out_rows}, per_file)


def print_detail(results):
    """Per-game economy/conflict averages and a round-by-round profile, per strategy."""
    tot = defaultdict(lambda: defaultdict(float))
    rnd = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in results:
        for spec, pr in zip(r["specs"], r["players"]):
            t = tot[spec]
            t["n"] += 1
            for k, v in pr["earned"].items():
                t["e_" + k] += v
            t["wins"] += pr["conflict_wins"]
            t["cards"] += pr["deck_size"]
            t["trashed"] += pr["trashed"]
            t["smf"] += pr["smf"]
            for k, v in pr["card_types"].items():
                t["ct_" + k] += v
            t["intrigue"] += pr["intrigue"]
            for k in ("decisions", "decision_ms", "options_total", "scored", "near_ties", "fallbacks"):
                t[k] += pr[k]
            for k in ("rollout_decisions", "rollout_changed"):
                t[k] += pr.get(k, 0)
            for i, h in enumerate(pr["history"]):
                d = rnd[spec][i]
                d["n"] += 1
                t["rounds"] += 1
                t["sent"] += h["conflict_troops"]
                t["fought"] += h["conflict_troops"] > 0
                if h["conflict_troops"] > 0:
                    t["place%d" % h["place"]] += 1
                    if h["place"] == 0:
                        t["wasted"] += h["conflict_troops"]
                for k, v in h.items():
                    d[k] += v
    for spec, t in tot.items():
        n = t["n"]
        print(f"\n== {spec}: averages per player per game ==")
        print(f"  earned over the game : spice {t['e_spice'] / n:.1f}, solari {t['e_solari'] / n:.1f}, "
              f"water {t['e_water'] / n:.1f}, troops recruited {t['e_troops'] / n:.1f}, "
              f"extra cards drawn {t['e_draw'] / n:.1f}")
        print(f"  conflict             : troops sent {t['sent'] / n:.1f} per game "
              f"({t['sent'] / t['rounds']:.2f} per round), fought in {100 * t['fought'] / t['rounds']:.0f}% of rounds, "
              f"won {t['wins'] / n:.2f} conflicts outright")
        f_ = max(1, t["fought"])
        print(f"  when they fought     : 1st {100 * t['place1'] / f_:.0f}%, 2nd {100 * t['place2'] / f_:.0f}%, "
              f"3rd {100 * t['place3'] / f_:.0f}%, no reward {100 * t['place0'] / f_:.0f}% "
              f"({t['wasted'] / n:.1f} troops per game lost for nothing)")
        print(f"  at game end          : {t['cards'] / n:.1f} cards owned, {t['trashed'] / n:.1f} trashed, "
              f"{t['smf'] / n:.2f} Spice Must Flow, "
              f"{t['intrigue'] / n:.1f} intrigue in hand")
        dn = max(1, t["decisions"])
        print(f"  turn decisions       : {t['decisions'] / n:.1f} per game, {t['options_total'] / dn:.1f} legal options each, "
              f"{t['decision_ms'] / dn:.1f} ms each, near-ties {100 * t['near_ties'] / max(1, t['scored']):.0f}% "
              f"of scored decisions, {t['fallbacks'] / n:.2f} fallbacks per game")
        if t["rollout_decisions"]:
            print(f"  rollouts             : {t['rollout_decisions'] / n:.1f} near-ties per game settled by rollouts, "
                  f"{100 * t['rollout_changed'] / t['rollout_decisions']:.0f}% of them changed the choice")
        ct = {k[3:]: v for k, v in t.items() if k.startswith("ct_")}
        tot_ct = max(1, sum(ct.values()))
        print("  bought cards by type : " + ", ".join(
            f"{k} {100 * v / tot_ct:.0f}%" for k, v in sorted(ct.items(), key=lambda kv: -kv[1])))
        print("  by round (held at end of round; troops/strength = committed to that round's conflict):")
        print(f"  {'round':>5}{'VP':>7}{'spice':>7}{'solari':>8}{'water':>7}{'garrison':>10}"
              f"{'cards':>7}{'troops':>8}{'strength':>10}{'games':>7}")
        for i in sorted(rnd[spec]):
            d = rnd[spec][i]
            m = d["n"]
            print(f"  {i + 1:>5}{d['vp'] / m:>7.2f}{d['spice'] / m:>7.2f}{d['solari'] / m:>8.2f}"
                  f"{d['water'] / m:>7.2f}{d['garrison'] / m:>10.2f}{d['cards'] / m:>7.1f}"
                  f"{d['conflict_troops'] / m:>8.2f}{d['strength'] / m:>10.2f}{int(m / max(1, 1)):>7}")


def _progress(i, n):
    if sys.stderr.isatty():
        sys.stderr.write(f"\r{i}/{n} games")
        sys.stderr.flush()


def build_replay(specs, seed, names=None, leaders=False):
    strategies = [make_strategy(s, seed=seed * 31 + k) for k, s in enumerate(specs)]
    names = names or [f"P{k + 1}" for k in range(len(specs))]
    # leaders: False/None = none, True = random, or a list of leader names, one per seat
    lead = "random" if leaders is True else (list(leaders) if leaders else None)
    g = Game(strategies, seed=seed, names=names, record=True, leaders=lead)
    res = g.play()
    return {
        "meta": {"seed": seed, "specs": specs, "result": res},
        "spaces": [{"name": s["name"], "area": s["area"], "icon": s["icon"],
                    "cost": s["cost"], "combat": s["combat"], "maker": s["maker"],
                    "requires": s["requires"], "effect": fmt_ops(s["effects"]),
                    "faction": s["faction"]} for s in SPACES],
        "frames": g.frames,
    }


def write_viewer(replay, out_path):
    with open(VIEWER_TEMPLATE) as fh:
        html = fh.read()
    payload = json.dumps(replay, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("/*__REPLAY__*/null", payload, 1)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(html)


def cmd_tournament(a):
    """Every combination of `table` distinct strategies plays `games` games. Reports each
    strategy's overall record and a head-to-head matrix (how often A finished ahead of B)."""
    names = list(FOCUS) if a.strategies in ([], ["focus"]) else a.strategies
    if len(set(names)) != len(names) or len(names) < a.table:
        raise UsageError(f"need at least {a.table} distinct strategies")
    check_players(names[:a.table])
    for nm in names:
        check_players([nm, nm])
    matchups = list(itertools.combinations(names, a.table))
    fair = 100.0 / a.table
    tee = _Tee(sys.stdout) if a.save else None
    if tee:
        sys.stdout = tee
    tot = {nm: defaultdict(float) for nm in names}
    vps = {nm: [] for nm in names}
    ahead = {x: {y: [0, 0] for y in names} for x in names}   # [times x ahead of y, games together]
    match_rows, all_results = [], []
    try:
        print(f"Tournament: {len(names)} strategies, every combination of {a.table} "
              f"({len(matchups)} matchups), {a.games} games each = {len(matchups) * a.games} games; "
              f"seeds {a.seed}..{a.seed + a.games - 1} per matchup, seating shuffled per game")
        for mi, specs in enumerate(matchups):
            results = run_games(list(specs), a.games, a.seed, False, a.workers, a.leaders)
            wins = defaultdict(float)
            for r in results:
                r["matchup"] = mi + 1
                share = 1.0 / len(r["winners"])
                rank = {}
                for seat, (spec, pr) in enumerate(zip(r["specs"], r["players"])):
                    t = tot[spec]
                    t["games"] += 1
                    t["rank"] += pr["rank"]
                    vps[spec].append(pr["vp"])
                    rank[spec] = pr["rank"]
                    if seat in r["winners"]:
                        t["wins"] += share
                        wins[spec] += share
                for x in specs:
                    for y in specs:
                        if x != y:
                            ahead[x][y][1] += 1
                            ahead[x][y][0] += rank[x] < rank[y]
            all_results.extend(results)
            match_rows.append({"matchup": mi + 1, "players": list(specs),
                               "win_pct": {s: round(100 * wins[s] / a.games, 1) for s in specs}})
            if sys.stderr.isatty():
                sys.stderr.write(f"\rmatchup {mi + 1}/{len(matchups)}   ")
        rows = []
        for nm in names:
            t, n = tot[nm], tot[nm]["games"]
            lo, hi = wilson(t["wins"], n)
            rows.append({"strategy": nm, "games": int(n), "win_pct": 100 * t["wins"] / n,
                         "ci_low": lo, "ci_high": hi, "avg_vp": sum(vps[nm]) / n,
                         "avg_rank": t["rank"] / n})
        rows.sort(key=lambda r: -r["win_pct"])
        order = [r["strategy"] for r in rows]
        print(f"\nOverall (fair share {fair:.1f}%)\n")
        hdr = f"{'#':>2} {'strategy':<24}{'games':>7}{'win %':>8}{'95% CI':>14}{'avg VP':>9}{'avg rank':>10}  verdict"
        print(hdr)
        print("-" * len(hdr))
        for i, r in enumerate(rows):
            r["verdict"] = ("above fair share" if r["ci_low"] > fair else
                            "below fair share" if r["ci_high"] < fair else "no clear difference")
            ci = f"{r['ci_low']:.1f}-{r['ci_high']:.1f}"
            print(f"{i + 1:>2} {r['strategy']:<24}{r['games']:>7}{r['win_pct']:>7.1f}%{ci:>14}"
                  f"{r['avg_vp']:>9.2f}{r['avg_rank']:>10.2f}  {r['verdict']}")
        print("\nHead-to-head: % of shared games in which the ROW strategy finished ahead of the COLUMN strategy")
        print(f"(columns numbered as in the table above; each pair shared {ahead[order[0]][order[1]][1]} games)\n")
        print(f"{'':>2} {'':<24}" + "".join(f"{i + 1:>7}" for i in range(len(order))))
        h2h = {}
        for i, x in enumerate(order):
            cells = []
            h2h[x] = {}
            for y in order:
                if x == y:
                    cells.append(f"{'-':>7}")
                else:
                    pct = 100 * ahead[x][y][0] / ahead[x][y][1]
                    h2h[x][y] = round(pct, 1)
                    cells.append(f"{pct:>6.0f}%")
            print(f"{i + 1:>2} {x:<24}" + "".join(cells))
        leader_rows = print_leaders(all_results, a.table)
        print("\nBest and worst matchup for each strategy (its win % in that matchup):")
        for x in order:
            mine = [(m["win_pct"][x], [p for p in m["players"] if p != x]) for m in match_rows if x in m["players"]]
            best, worst = max(mine), min(mine)
            print(f"  {x:<24} best {best[0]:>5.1f}% vs {', '.join(best[1])}")
            print(f"  {'':<24} worst {worst[0]:>4.1f}% vs {', '.join(worst[1])}")
    finally:
        if tee:
            sys.stdout = tee.stream
    if a.save:
        meta = run_meta(a, {"strategies": names, "table": a.table, "matchups": len(matchups),
                            "fair_share_pct": fair})
        save_run(a.save, tee.buf.getvalue(),
                 {"meta": meta, "overall": rows, "head_to_head": h2h, "matchups": match_rows,
                  "leaders": leader_rows},
                 {"games.csv": all_results})


def cmd_leader_fit(a):
    """Controlled test of which leaders suit which strategies.

    For every (strategy, leader) pair: the strategy plays as that leader against three copies
    of the baseline, whose leaders are random but distinct. The same seeds, seating and
    opponent leaders are used for every strategy with a given leader, so each cell can be
    compared directly with the baseline playing that same leader (a paired comparison).
    fit = strategy's result with leader L  -  baseline's result with leader L
    """
    base = a.baseline
    targets = list(FOCUS) if a.strategies in ([], ["focus"]) else a.strategies
    names = [base] + [t for t in targets if t != base]
    for nm in names:
        check_players([nm, base])
    leaders = [ld["name"] for ld in LEADERS]
    if a.leader:
        leaders = [l for l in leaders if l in a.leader]
    tee = _Tee(sys.stdout) if a.save else None
    if tee:
        sys.stdout = tee
    cells, per_file = {}, {}
    try:
        print(f"Leader fit: each strategy plays each leader vs {a.table - 1} x {base} "
              f"(random distinct leaders), {a.games} games per pair, seeds {a.seed}.."
              f"{a.seed + a.games - 1}; {len(names) * len(leaders) * a.games} games in total")
        for li, L in enumerate(leaders):
            for nm in names:
                specs = [nm] + [base] * (a.table - 1)
                # fixing index 0 to L; the opponents' leaders come from the seed and L only,
                # so they are identical for every strategy tested with L
                jobs_leaders = {0: L}
                results = run_games_fixed(specs, a.games, a.seed, a.workers, jobs_leaders)
                vps, wins, ranks = [], 0.0, 0
                for r in results:
                    me = next(i for i, p in enumerate(r["players"]) if p["leader"] == L)
                    vps.append(r["players"][me]["vp"])
                    ranks += r["players"][me]["rank"]
                    if me in r["winners"]:
                        wins += 1.0 / len(r["winners"])
                cells[(nm, L)] = {"vps": vps, "wins": wins, "rank": ranks / len(results)}
                per_file[f"games_{L.split()[-1].strip(chr(34)).lower()}_{nm}.csv"] = results
                if sys.stderr.isatty():
                    sys.stderr.write(f"\r{li + 1}/{len(leaders)} leaders  {nm:<24}")
        if sys.stderr.isatty():
            sys.stderr.write("\n")
        short = {L: L.replace('Glossu "The Beast" ', "").split()[-1] if "Rabban" in L
                 else L.split()[1] if L.split()[0] in ("Baron", "Count", "Countess", "Duke") else L.split()[0]
                 for L in leaders}
        n = a.games

        def wp(nm, L):
            return 100 * cells[(nm, L)]["wins"] / n

        def mvp(nm, L):
            return sum(cells[(nm, L)]["vps"]) / n

        lead_order = sorted(leaders, key=lambda L: -wp(base, L))
        hdr = f"{'':<24}" + "".join(f"{short[L]:>9}" for L in lead_order) + f"{'all':>9}"
        print(f"\nWin % as each leader (fair share {100 / a.table:.0f}%; each cell {n} games,"
              f" 95% interval about +/-{196 * (0.25 * 0.75 / n) ** 0.5:.0f} points)\n")
        print(hdr)
        print("-" * len(hdr))
        rows_out = []
        for nm in names:
            allw = sum(cells[(nm, L)]["wins"] for L in leaders) / (n * len(leaders))
            print(f"{nm:<24}" + "".join(f"{wp(nm, L):>9.1f}" for L in lead_order) + f"{100 * allw:>9.1f}")
        print(f"\nFit: average VP as the leader minus {base}'s average VP as the same leader, same games")
        print("(+ = this leader suits the strategy better than it suits the baseline; * = 95% interval excludes 0)\n")
        print(hdr)
        print("-" * len(hdr))
        for nm in names:
            line = f"{nm:<24}"
            for L in lead_order:
                d = [x - y for x, y in zip(cells[(nm, L)]["vps"], cells[(base, L)]["vps"])]
                m = sum(d) / n
                sd = (sum((x - m) ** 2 for x in d) / max(1, n - 1)) ** 0.5
                se = sd / n ** 0.5
                sig = "*" if nm != base and abs(m) > 1.96 * se else " "
                line += f"{m:>+8.2f}{sig}"
                rows_out.append({"strategy": nm, "leader": L, "games": n, "win_pct": wp(nm, L),
                                 "avg_vp": mvp(nm, L), "avg_rank": cells[(nm, L)]["rank"],
                                 "vp_vs_baseline": m, "vp_vs_baseline_se": se,
                                 "significant": sig == "*"})
            allm = sum(mvp(nm, L) - mvp(base, L) for L in leaders) / len(leaders)
            print(line + f"{allm:>+9.2f}")
        print("\nBest and worst leader for each strategy, by fit (VP vs baseline with that leader):")
        for nm in names:
            if nm == base:
                continue
            mine = [r for r in rows_out if r["strategy"] == nm]
            best = max(mine, key=lambda r: r["vp_vs_baseline"])
            worst = min(mine, key=lambda r: r["vp_vs_baseline"])
            print(f"  {nm:<24} best {short[best['leader']]:<8} {best['vp_vs_baseline']:+.2f} VP"
                  f"{' *' if best['significant'] else ''}   worst {short[worst['leader']]:<8}"
                  f" {worst['vp_vs_baseline']:+.2f} VP{' *' if worst['significant'] else ''}")
    finally:
        if tee:
            sys.stdout = tee.stream
    if a.save:
        meta = run_meta(a, {"baseline": base, "strategies": names, "leaders_tested": leaders,
                            "table": a.table})
        save_run(a.save, tee.buf.getvalue(), {"meta": meta, "cells": rows_out}, per_file)


def run_games_fixed(specs, games, seed, workers, fixed):
    """Like run_games, but with some leaders fixed: {spec index: leader name}."""
    jobs = [(specs, seed + i, True, fixed) for i in range(games)]
    workers = workers or os.cpu_count() or 1
    if workers > 1 and games > 1:
        with Pool(workers) as pool:
            results = list(pool.imap_unordered(run_one, jobs, chunksize=4))
    else:
        results = [run_one(j) for j in jobs]
    results.sort(key=lambda r: r["seed"])
    return results


# --------------------------------------------------------------------------- traces
def player_measures(pr):
    d = max(1, pr["decisions"])
    return {
        "vp": pr["vp"], "rank": pr["rank"], "decisions": pr["decisions"],
        "avg_options": round(pr["options_total"] / d, 1),
        "ms_per_decision": round(pr["decision_ms"] / d, 2),
        "near_tie_pct": round(100 * pr["near_ties"] / pr["scored"], 1) if pr["scored"] else None,
        "fallbacks": pr["fallbacks"],
    }


def trace_text(replay, agent):
    """Human-readable trace of one seat: what it saw, what it could do, what it chose, what changed."""
    frames, out = replay["frames"], []
    res = replay["meta"]["result"]
    name = res["players"][agent]["name"]
    if res["players"][agent].get("leader"):
        name += " as " + res["players"][agent]["leader"]
    out.append(f"TRACE of {name} [{res['players'][agent]['strategy']}], seed {replay['meta']['seed']}, "
               f"players: {', '.join(replay['meta']['specs'])}")
    keys = ["vp", "spice", "solari", "water", "garrison", "conflict", "persuasion"]
    for k in range(1, len(frames)):
        f, prev = frames[k], frames[k - 1]["state"]
        if f["msg"].startswith(("Round ", "Combat ", "Game over")):
            out.append(f"\n=== {f['msg']} ===")
            continue
        if f["actor"] != agent:
            continue
        me, now = prev["players"][agent], f["state"]["players"][agent]
        out.append(f"\n[step {k + 1}] round {f['state']['round']}")
        wrap = lambda label, text: textwrap.fill(  # noqa: E731
            label + text, 100, initial_indent=" " * 13, subsequent_indent=" " * 19)
        out.append("  percepts : " + ", ".join(f"{x} {me[x]}" for x in keys)
                   + f", agents left {me['agents_total'] - me['agents_used']}")
        out.append("             influence: " + ", ".join(f"{k_} {v}" for k_, v in me["influence"].items()))
        out.append(wrap("hand: ", ", ".join(me["hand"]) or "-"))
        out.append(wrap("occupied spaces: ", ", ".join(
            s for s, b in prev["board"].items() if b["agent"] is not None) or "none"))
        d = f.get("decision")
        if d:
            out.append(f"  options  : {d['n_options']} legal, decided in {d['ms']} ms"
                       + (f" by rule ({d['rule']})" if d["rule"] else ""))
            for o in d["options"][:6]:
                score = "   n/a" if o["score"] is None else f"{o['score']:7.2f}"
                out.append(f"      {'>>' if o['chosen'] else '  '} {score}  {o['label']}")
            if d["n_options"] > 6:
                out.append(f"         ... {d['n_options'] - 6} more")
            if d["fallback"]:
                out.append(f"  FALLBACK : {d['fallback']} -> replaced by a reveal turn")
        elif "intrigue" in f["msg"]:
            out.append("  options  : intrigue card played (a sub-decision; only turn choices are scored)")
        else:
            out.append("  options  : 1 legal (forced)")
        out.append("  action   : " + f["msg"])
        delta = [f"{x} {now[x] - me[x]:+d}" for x in keys if now[x] != me[x]]
        delta += [f"{fa} influence {now['influence'][fa] - me['influence'][fa]:+d}"
                  for fa in me["influence"] if now["influence"][fa] != me["influence"][fa]]
        out.append("  effect   : " + (", ".join(delta) or "no change to tracked values"))
        for note in f.get("notes", []):
            if not note.startswith("FALLBACK"):
                out.append("             " + note)
    out.append(f"\nRESULT: {res['end_reason']} after {res['rounds']} rounds; "
               + ", ".join(f"{p['name']} [{p['strategy']}] {p['vp']} VP (rank {p['rank']})" for p in res["players"]))
    return "\n".join(out) + "\n"


def run_trace(specs, seed, agent, out_dir, leaders=False):
    """Play one fully recorded game and write trace.txt, trace.json, replay.html, result.json."""
    check_players(specs)
    if not 0 <= agent < len(specs):
        raise UsageError(f"--agent must be between 1 and {len(specs)}")
    replay = build_replay(specs, seed, leaders=leaders)
    res = replay["meta"]["result"]
    pr = res["players"][agent]
    summary = {
        "players": specs, "seed": seed, "agent_seat": agent + 1, "agent_strategy": pr["strategy"],
        "terminal_status": f"{res['end_reason']} after {res['rounds']} rounds",
        "agent_won": agent in res["winners"],
        "final_vp": [p["vp"] for p in res["players"]],
        "measures": player_measures(pr),
        "total_fallbacks": sum(p["fallbacks"] for p in res["players"]),
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "trace.txt"), "w") as fh:
            fh.write(trace_text(replay, agent))
        with open(os.path.join(out_dir, "trace.json"), "w") as fh:
            json.dump([{"step": k + 1, "round": f["state"]["round"], "actor": f["actor"], "msg": f["msg"],
                        "decision": f.get("decision"), "notes": f.get("notes", [])}
                       for k, f in enumerate(replay["frames"])], fh, indent=1)
        with open(os.path.join(out_dir, "result.json"), "w") as fh:
            json.dump(summary, fh, indent=1)
        write_viewer(replay, os.path.join(out_dir, "replay.html"))
    return summary, replay


def cmd_trace(a):
    out = None
    if a.save:
        out = a.save if os.path.isabs(a.save) or os.sep in a.save else os.path.join(ROOT, "results", a.save)
    summary, replay = run_trace(a.players, a.seed, a.agent - 1, out, a.leaders)
    if not out:
        print(trace_text(replay, a.agent - 1))
    m = summary["measures"]
    print(f"terminal status : {summary['terminal_status']}")
    print(f"agent under test: seat {a.agent} [{summary['agent_strategy']}] "
          f"{'WON' if summary['agent_won'] else 'did not win'} with {m['vp']} VP (rank {m['rank']})")
    print(f"measures        : {m['decisions']} decisions, {m['avg_options']} options each, "
          f"{m['ms_per_decision']} ms each, near-ties {m['near_tie_pct']}%, fallbacks {m['fallbacks']}")
    if out:
        print(f"saved to {out}/ (trace.txt, trace.json, result.json, replay.html)")


def cmd_cases(a):
    """Run the retained cases from a JSON file and write a result table plus per-case evidence."""
    with open(a.file) as fh:
        cases = json.load(fh)
    out = a.save if os.path.isabs(a.save) or os.sep in a.save else os.path.join(ROOT, "results", a.save)
    os.makedirs(out, exist_ok=True)
    rows = []
    for c in cases:
        row = {"id": c["id"], "kind": c["kind"], "players": c["players"], "seed": c.get("seed"),
               "expect": c["expect"], "what": c.get("what", "")}
        try:
            summary, _ = run_trace(c["players"], c.get("seed", 1), c.get("agent", 1) - 1,
                                   os.path.join(out, c["id"]), c.get("leaders", False))
            row.update(status=summary["terminal_status"], agent=summary["agent_strategy"],
                       agent_won=summary["agent_won"], total_fallbacks=summary["total_fallbacks"],
                       **summary["measures"])
            observed = "win" if summary["agent_won"] else "loss"
        except UsageError as e:
            os.makedirs(os.path.join(out, c["id"]), exist_ok=True)
            with open(os.path.join(out, c["id"], "error.txt"), "w") as fh:
                fh.write(f"error: {e}\nexit code 2, no game run\n")
            row.update(status=f"rejected: {e}", agent_won=None)
            observed = "rejected"
        # a case 'passes' when the system did what the case says it should
        row["observed"] = observed
        row["as_expected"] = (observed == c["expect"] or
                              (c["expect"] == "completes" and observed in ("win", "loss")))
        rows.append(row)

    lines = ["| case | kind | terminal status | success condition (agent finishes first) | VP | rank | decisions | ms / decision | near-ties | fallbacks | as expected |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["agent_won"] is None:
            lines.append(f"| {r['id']} | {r['kind']} | {r['status']} | not applicable (no game) | - | - | - | - | - | - | {'yes' if r['as_expected'] else 'NO'} |")
        else:
            nt = "-" if r["near_tie_pct"] is None else f"{r['near_tie_pct']}%"
            lines.append(f"| {r['id']} | {r['kind']} | {r['status']} | {'met' if r['agent_won'] else 'not met'} | {r['vp']} | {r['rank']} | "
                         f"{r['decisions']} | {r['ms_per_decision']} | {nt} | {r['fallbacks']} | {'yes' if r['as_expected'] else 'NO'} |")
    table = "\n".join(lines)
    print(table)
    meta = run_meta(argparse.Namespace(seed=None, games=len(cases), water=a.water), {"cases_file": a.file})
    with open(os.path.join(out, "cases.md"), "w") as fh:
        fh.write("$ " + meta["command"] + "\n\n" + table + "\n")
    with open(os.path.join(out, "cases.json"), "w") as fh:
        json.dump({"meta": meta, "cases": rows}, fh, indent=1)
    print(f"\nsaved to {out}/ (cases.md, cases.json, one folder per case)")
    if not all(r["as_expected"] for r in rows):
        raise UsageError("one or more cases did not behave as expected")


def cmd_watch(a):
    check_players(a.players)
    replay = build_replay(a.players, a.seed, leaders=a.leaders)
    out = a.out or os.path.join(ROOT, "replays", f"game_{a.seed}.html")
    write_viewer(replay, out)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(replay, fh)
    res = replay["meta"]["result"]
    print(f"seed {a.seed}: " + ", ".join(
        f"{p['name']} [{p['strategy']}{', ' + p['leader'] if p.get('leader') else ''}] {p['vp']}VP"
        + (" *WIN*" if i in res["winners"] else "")
        for i, p in enumerate(res["players"])))
    print(f"replay: {out}  ({len(replay['frames'])} steps)")
    if a.open:
        webbrowser.open("file://" + os.path.abspath(out))


def cmd_list(_a):
    print("Built-in strategies:")
    for s in available_strategies():
        print("  " + s + ("   [focus]" if s.split(":", 1)[-1] in FOCUS else ""))
    print("\n[focus] = clearly beat three balanced over 1,000 games; run them with `benchmark focus`")
    print("\nAlso: weights:path/to/weights.json   or   your.module:YourStrategyClass")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dune_sim", description="Dune: Imperium strategy simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("batch", help="run many games and compare strategies")
    b.add_argument("-p", "--players", nargs="+", required=True, help="strategy spec per seat")
    b.add_argument("-n", "--games", type=int, default=200)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("-w", "--workers", type=int, default=0, help="processes (default: all cores)")
    b.add_argument("--fixed-seats", action="store_true", help="don't shuffle seating each game")
    b.add_argument("--csv", help="write per-game results to this CSV")
    b.add_argument("--detail", action="store_true",
                   help="also print economy/conflict averages and a round-by-round profile")
    b.add_argument("--save", metavar="NAME",
                   help="save the report, per-strategy stats and per-game CSV to results/NAME/")
    b.set_defaults(func=cmd_batch)

    k = sub.add_parser("benchmark", help="run each strategy against copies of a baseline")
    k.add_argument("strategies", nargs="*",
                   help="strategies to test (default: all built-ins; `focus` = the focus set)")
    k.add_argument("--baseline", default="balanced")
    k.add_argument("--table", type=int, default=4, help="players per game")
    k.add_argument("-n", "--games", type=int, default=400)
    k.add_argument("--seed", type=int, default=1)
    k.add_argument("-w", "--workers", type=int, default=0)
    k.add_argument("--save", metavar="NAME", help="save everything to results/NAME/")
    k.set_defaults(func=cmd_benchmark)

    w = sub.add_parser("watch", help="simulate one game and write an HTML replay")
    w.add_argument("-p", "--players", nargs="+", required=True)
    w.add_argument("--seed", type=int, default=1)
    w.add_argument("-o", "--out", help="output .html (default replays/game_<seed>.html)")
    w.add_argument("--json", help="also save the raw replay JSON here")
    w.add_argument("--open", action="store_true", help="open in your browser")
    w.set_defaults(func=cmd_watch)

    tn = sub.add_parser("tournament", help="every combination of strategies plays each other")
    tn.add_argument("strategies", nargs="*", help="strategies (default: the focus set)")
    tn.add_argument("--table", type=int, default=4, help="players per game")
    tn.add_argument("-n", "--games", type=int, default=60, help="games per matchup")
    tn.add_argument("--seed", type=int, default=1)
    tn.add_argument("-w", "--workers", type=int, default=0)
    tn.add_argument("--save", metavar="NAME", help="save everything to results/NAME/")
    tn.set_defaults(func=cmd_tournament)

    lf = sub.add_parser("leader-fit", help="which leaders suit which strategies (controlled test)")
    lf.add_argument("strategies", nargs="*", help="strategies to test (default: the focus set)")
    lf.add_argument("--baseline", default="balanced")
    lf.add_argument("--leader", action="append", help="limit to this leader (repeatable)")
    lf.add_argument("--table", type=int, default=4)
    lf.add_argument("-n", "--games", type=int, default=100, help="games per strategy-leader pair")
    lf.add_argument("--seed", type=int, default=1)
    lf.add_argument("-w", "--workers", type=int, default=0)
    lf.add_argument("--save", metavar="NAME", help="save everything to results/NAME/")
    lf.set_defaults(func=cmd_leader_fit, leaders=True)

    t = sub.add_parser("trace", help="play one game and record every decision of one seat")
    t.add_argument("-p", "--players", nargs="+", required=True)
    t.add_argument("--seed", type=int, default=1)
    t.add_argument("--agent", type=int, default=1, help="seat to trace, 1-based (default 1)")
    t.add_argument("--save", metavar="NAME", help="write trace, result and replay to results/NAME/")
    t.set_defaults(func=cmd_trace)

    c = sub.add_parser("cases", help="run the retained cases and write a result table")
    c.add_argument("--file", default=os.path.join(ROOT, "cases", "vertical_slice.json"))
    c.add_argument("--save", metavar="NAME", default="vertical_slice")
    c.set_defaults(func=cmd_cases)

    l_ = sub.add_parser("list", help="list strategies")
    l_.set_defaults(func=cmd_list)

    for sp in (b, k, tn, t, w):   # leaders are on by default wherever games are played
        sp.add_argument("--no-leaders", dest="leaders", action="store_false",
                        help="play without leaders (Signet Ring gives 1 solari), as before leaders were added")
        sp.set_defaults(leaders=True)
    for sp in (b, k, tn, t, w, c, lf):
        sp.add_argument("--water", choices=WATER_MODES, default="capped",
                        help="capped (default): water beyond 4 is worth little; "
                             "flat: every water at full value, as in the U0-HW-11 baseline")
    a = ap.parse_args(argv)
    set_water_mode(getattr(a, "water", "capped"))
    try:
        a.func(a)
    except UsageError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
