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
import json
import math
import os
import platform
import random
import subprocess
import sys
import webbrowser
from collections import defaultdict
from multiprocessing import Pool

from .engine import Game, SPACES, fmt_ops
from .strategies import available_strategies, make_strategy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER_TEMPLATE = os.path.join(ROOT, "viewer", "viewer.html")


def run_one(args):
    specs, seed, rotate = args
    rng = random.Random(seed)
    order = list(range(len(specs)))
    if rotate:
        rng.shuffle(order)  # random seating so first-player advantage averages out
    seated = [specs[i] for i in order]
    strategies = [make_strategy(s, seed=seed * 31 + k) for k, s in enumerate(seated)]
    names = [f"P{k + 1}" for k in range(len(seated))]
    g = Game(strategies, seed=seed, names=names)
    res = g.play()
    res["specs"] = seated
    return res


def run_games(specs, games, seed, fixed_seats=False, workers=0):
    """Play `games` seeded games (seeds seed .. seed+games-1). Deterministic for a given
    (specs, games, seed, fixed_seats), whatever the number of worker processes."""
    jobs = [(specs, seed + i, not fixed_seats) for i in range(games)]
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
                     "spice", "solari", "water", "deck_size", "alliances"])
        for r in sorted(results, key=lambda r: r["seed"]):
            for seat, (spec, pr) in enumerate(zip(r["specs"], r["players"])):
                wr.writerow([r["seed"], r["rounds"], seat + 1, spec, pr["vp"], pr["rank"],
                             int(seat in r["winners"]), pr["spice"], pr["solari"],
                             pr["water"], pr["deck_size"], "|".join(pr["alliances"])])


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
    meta = {
        "command": "python3 -m dune_sim " + " ".join(sys.argv[1:]),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(), "platform": platform.platform(),
        "git_commit": commit, "seed": a.seed, "games": a.games,
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
    tee = _Tee(sys.stdout) if a.save else None
    if tee:
        sys.stdout = tee
    try:
        results = run_games(specs, a.games, a.seed, a.fixed_seats, a.workers)
        rows, seats = summarize(results, specs)
        avg_rounds = sum(r["rounds"] for r in results) / len(results)
        print_table(rows, len(specs), a.games, avg_rounds)
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
        save_run(a.save, tee.buf.getvalue(), {"meta": meta, "strategies": rows, "win_pct_by_seat": seats},
                 {"games.csv": results})


def cmd_benchmark(a):
    """Each strategy in one seat against (n-1) copies of the baseline, same seeds for all."""
    base = a.baseline
    targets = a.strategies or [s.split(":", 1)[-1] for s in available_strategies()
                               if s.split(":", 1)[-1] != base]
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
            results = run_games(specs, a.games, a.seed, False, a.workers)
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
              f"water {t['e_water'] / n:.1f}, troops recruited {t['e_troops'] / n:.1f}")
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


def build_replay(specs, seed, names=None):
    strategies = [make_strategy(s, seed=seed * 31 + k) for k, s in enumerate(specs)]
    names = names or [f"P{k + 1}" for k in range(len(specs))]
    g = Game(strategies, seed=seed, names=names, record=True)
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


def cmd_watch(a):
    replay = build_replay(a.players, a.seed)
    out = a.out or os.path.join(ROOT, "replays", f"game_{a.seed}.html")
    write_viewer(replay, out)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(replay, fh)
    res = replay["meta"]["result"]
    print(f"seed {a.seed}: " + ", ".join(
        f"{p['name']} [{p['strategy']}] {p['vp']}VP" + (" *WIN*" if i in res["winners"] else "")
        for i, p in enumerate(res["players"])))
    print(f"replay: {out}  ({len(replay['frames'])} steps)")
    if a.open:
        webbrowser.open("file://" + os.path.abspath(out))


def cmd_list(_a):
    print("Built-in strategies:")
    for s in available_strategies():
        print("  " + s)
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
    k.add_argument("strategies", nargs="*", help="strategies to test (default: all built-ins)")
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

    l_ = sub.add_parser("list", help="list strategies")
    l_.set_defaults(func=cmd_list)

    a = ap.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
