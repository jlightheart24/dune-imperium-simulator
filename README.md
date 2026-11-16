# Dune: Imperium strategy simulator

A pure-Python (3.9+, no dependencies) rules engine for testing AI strategies
against each other, plus a step-by-step HTML replay viewer.

## Quick start

```bash
# compare strategies over many games (seating is shuffled each game, runs on all cores)
python3 -m dune_sim batch -n 400 -p military spice factions balanced

# simulate one game and write a replay you can step through
python3 -m dune_sim watch -p military spice factions balanced --seed 7 --open

# list built-in strategies
python3 -m dune_sim list
```

`batch` options: `--seed`, `--workers`, `--fixed-seats` (measure seat advantage),
`--csv results.csv` (per-game rows for your own analysis).
You can put the same strategy in several seats, e.g. `-p military balanced balanced balanced`.

## Saved, repeatable evaluations

```bash
# every strategy in one seat against three copies of the baseline, saved to results/benchmark_v1/
python3 -m dune_sim benchmark -n 400 --save benchmark_v1

# save any batch run (report, per-strategy stats as JSON, per-game CSV)
python3 -m dune_sim batch -n 400 -p military balanced balanced balanced --save military_vs_balanced

# repeatability and sanity tests
python3 -m unittest
```

Tables show a 95% Wilson confidence interval on the win rate. A run is fully determined by
its strategies, `--seed` and `-n`, so re-running a saved command reproduces its numbers.
Each saved run records the command, date, Python version and git commit.
The course project definition is in `docs/project-definition.md`.

## Decision traces and retained cases

```bash
# one game with every turn decision of seat 1 recorded: percepts, options with scores, choice, effect
python3 -m dune_sim trace -p balanced random random random --seed 7 --save my_trace

# the retained cases in cases/vertical_slice.json (supported, unsuccessful, boundary, faulty agent, bad input)
python3 -m dune_sim cases
```

An agent that returns an illegal action or raises an exception has that turn replaced by a
reveal; the fallback is counted and logged. Unknown strategies and unsupported table sizes
are rejected with a one-line error and exit code 2. The replay viewer shows a decision panel
(options and utility scores) at each step, and `game.html#step=N` opens a replay at step N.
The vertical-slice write-up is in `docs/vertical-slice.md`.

## Evaluation (baseline and revised)

```bash
# every run in docs/project-evaluation.md, about 4 hours on 10 cores
./results/evaluation/run_all.sh

# the ten retained cases under the HW-11 baseline setting, then the current one
python3 -m dune_sim cases --file cases/evaluation.json --water flat --save results/evaluation/cases_baseline
python3 -m dune_sim cases --file cases/evaluation.json --save results/evaluation/cases_revised
```

`--water flat` values every unit of water fully, as the agent did at the vertical-slice
checkpoint; the default caps water's value beyond 4. With `--water flat --no-leaders`
the vertical-slice results reproduce exactly. `strategies/balanced_flat_water.json` is
that older `balanced`, so old and new can play in one game.

## Leaders

Every game played from the command line gives each player a different random leader
(the eight base-game leaders, defined in `LEADERS` in `dune_sim/data.py`). A leader has a
passive ability and a signet ability that the Signet Ring card triggers. Results tables
include a win rate by leader, and the viewer shows each player's leader.

```bash
python3 -m dune_sim batch -n 400 -p balanced balanced balanced balanced               # with leaders
python3 -m dune_sim batch -n 400 -p balanced balanced balanced balanced --no-leaders  # as before leaders existed
```

`--no-leaders` reproduces results saved before leaders were added. The retained cases in
`cases/vertical_slice.json` run without leaders. Helena Richese's signet reserves a card
from the Imperium row: only she can buy it, that round, for 1 persuasion less, and it
leaves the game if she does not. Leader abilities are simplified and were
written from memory, so check them against the physical game.

## Replay viewer

`watch` writes `replays/game_<seed>.html`, a single self-contained page. Controls:
←/→ step, Shift+←/→ jump a round, Space play/pause, click any log line to jump.
It shows the board (agents, bonus spice, control), the current conflict and
strengths, the Imperium row, and each player's resources, influence, alliances,
hand, played/revealed cards and intrigue. `--json` also saves the raw replay,
which the viewer can load with its file picker.

## Layout

| file | what it is |
|---|---|
| `dune_sim/data.py` | all game content: board spaces, cards, conflicts, intrigue, in a small effect language |
| `dune_sim/engine.py` | rules: rounds, agent/reveal turns, influence and alliances, combat, makers, endgame, replay frames |
| `dune_sim/strategies.py` | the `Strategy` interface, `RandomStrategy`, `HeuristicStrategy` and its profiles |
| `dune_sim/cli.py` | the commands: `batch`, `benchmark`, `tournament`, `leader-fit`, `trace`, `cases`, `watch`, `list` |
| `viewer/viewer.html` | replay viewer template |

## Writing strategies

**Weights only, no code:** copy `strategies/example_weights.json`, change the numbers, run it with
`-p weights:strategies/example_weights.json`. Any key you leave out uses the
default in `BASE_WEIGHTS` (`dune_sim/strategies.py`).

**Custom logic:** subclass `Strategy` (or `HeuristicStrategy` to override only
some decisions) and pass `module.path:ClassName`:

```python
# my_strats.py
from dune_sim.strategies import HeuristicStrategy

class AlwaysSwordmaster(HeuristicStrategy):
    def __init__(self):
        super().__init__(name="swordmaster-first")
    def choose_turn(self, game, p, actions):
        for a in actions:
            if a[0] == "agent" and a[2] == "Swordmaster":
                return a
        return super().choose_turn(game, p, actions)
```

```bash
python3 -m dune_sim batch -p my_strats:AlwaysSwordmaster balanced balanced balanced
```

Decision points: `choose_turn`, `choose_deploy`, `choose_purchase`,
`choose_influence`, `choose_trash`, `choose_option`, `choose_plot_intrigue`,
`choose_combat_intrigue`. Each gets the live `game` and the player `p`;
`game.clone()` gives you a copy to simulate moves on (deck orders are reshuffled
so lookahead can't peek at hidden cards).

## How the heuristic AI works

For each legal turn it simulates the move on a clone and scores the result with
a weighted value function: VP, resources, influence (with extra pull toward the
2-influence VP and the alliance at 4), deck quality, reveal value left in hand,
High Council seat, extra agents, and the expected conflict reward given current
troop strengths. Profiles (`military`, `spice`, `factions`, `fremen_faction`,
`deckbuilder`, `balanced`) are just different weights.

## Accuracy and simplifications

- The board, starter deck, resources, influence/alliance rules, combat ranking and ties,
  maker bonus spice, control, and end conditions (10 VP or conflict deck empty)
  follow the base game.
- **Imperium cards, conflict rewards and intrigue cards are approximations**: names kept,
  effects simplified. Edit `dune_sim/data.py` to match your copy; the engine only
  reads the effect DSL documented at the top of that file.
- Not modelled yet: the 2-player rival rules, expansions, and card effects that hit opponents.
  Some cards that hit opponents (e.g. Mohiam) only keep their effects on you.
