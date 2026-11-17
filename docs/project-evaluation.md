# Agent Evaluation and Refinement

**Project:** A strategy-testing agent for the board game *Dune: Imperium*

| | |
|---|---|
| Name | Jonny Lightheart |
| Repository | https://github.com/jlightheart24/dune-imperium-simulator |
| Submitted commit | COMMIT_HASH_IN_PDF |
| Date | November 16, 2026 |

---

## 1. Summary

The agent plays *Dune: Imperium* by scoring each legal turn one step ahead with a weighted
value function. A "strategy" is a set of weights and rules for that agent. The project's
purpose is to find out which strategies are better.

Since the vertical slice (U0-HW-11) the main refinement was a **strategy search**: new
strategies were added, every strategy was tested against three copies of the fixed
baseline strategy `balanced`, the leaders were re-tested at 1,000 games, and the best four
then played each other. A smaller refinement, the **water cap**, completes a set of three
resource caps that stop the agent hoarding. A third refinement, **blocking**, makes the
agent act against opponents' victory points.

Main results, all without leaders and at 1,000 games per row unless stated:

- Three strategies beat the baseline with a 95% interval above the 25% fair share:
  `bene_gesserit_faction` (30.0%), `rush_swordmaster` (29.5%) and `rush_both` (28.5%).
  At the HW-11 checkpoint one strategy did. This meets the target HW-11 set.
- Against each other the top three are close (25% to 28%) and cannot be ranked.
- The water cap cut the water an agent holds at game end from 3.88 to 2.94, but did
  **not** raise the win rate: the capped `balanced` won 23.4% against three uncapped
  copies (95% interval 20.9 to 26.1).
- Blocking did **not** help. Blocking every opponent point made `balanced` worse (21.5%,
  95% interval 19.1 to 24.2). Blocking only the point that would take an opponent to
  10 VP made no measurable difference to any strategy.
- All ten retained cases behaved as defined under both the baseline and the revised
  configuration. No built-in agent needed a fallback turn.

## 2. Commands

**Setup.** Python 3.9 or later. No packages, credentials or network access.

```
git clone https://github.com/jlightheart24/dune-imperium-simulator.git
cd dune-imperium-simulator
python3 -m unittest          # 30 tests, about 30 seconds
```

**Exact evaluation command.** One script runs every result in this report, in order
(about 5 hours on 10 cores). Each line of it can also be run on its own.

```
./results/evaluation/run_all.sh
```

The two commands for the retained cases, baseline then revised:

```
python3 -m dune_sim cases --file cases/evaluation.json --water flat \
    --save results/evaluation/cases_baseline
python3 -m dune_sim cases --file cases/evaluation.json \
    --save results/evaluation/cases_revised
```

Every run is fully determined by its strategies, seed, game count and settings, so
re-running a command reproduces its numbers. Only time per decision varies.

## 3. Refinements

### 3.1 Strategy search (the main refinement)

**Evidence from HW-11.** The HW-11 benchmark (200 games per strategy) found one strategy
out of 17 that beat the baseline, and its 95% interval was wide (25.5 to 38.2). HW-11 set
this target for the next checkpoint: a win rate against three `balanced` whose 95%
interval lies above 25%.

**Change of plan.** HW-11 proposed reaching that target with Monte Carlo rollouts for
near-tie decisions. I did not build rollouts. Adding and testing strategies answers the
project's question, which strategies are better, more directly, and it costs nothing at
decision time. Near-ties are still 37% of decisions (section 5.5), so the HW-11 finding
stands and rollouts remain possible later work.

**What was added.**

- Four strategies: `rush_council` (buy a High Council seat as fast as possible, never the
  Swordmaster), `rush_swordmaster` (the reverse), `rush_both`, and `card_draw`.
- A strategy setting, `avoid_spaces`, for board spaces a strategy never uses.
- A `benchmark` option to test a named group, and a `tournament` command.

**Method.** Three stages, each a saved command:

1. *Screen*: each strategy in one seat against three `balanced`, 200 games.
2. *Confirm*: the same test at 1,000 games, which narrows the 95% interval from about
   plus or minus 6 points to about plus or minus 2.7.
3. *Head-to-head*: the best four at one table, 1,000 games.

**Expected effect.** More strategies with a win rate reliably above 25%, and a ranking
that holds up when the strong strategies meet each other.

### 3.2 Resource caps: solari, spice and water

The value function scores resources the agent holds. If every unit is worth the same, the
agent keeps collecting a resource it has no use for. Three caps limit this. Each values
a resource fully up to what the agent can spend, and little beyond that.

| Resource | Full value up to | Value beyond | Reason for the limit | Added |
|---|---|---|---|---|
| Solari | 8 | 20% | The most expensive space (Swordmaster) costs 8 | Before HW-11 |
| Spice | 10 | 30% | Heighliner (6) plus Conspire (4) | Before HW-11 |
| Water | 4 | 15% | Two 2-water spaces | This checkpoint |

The solari and spice caps were already in the HW-11 baseline, so the baseline-to-revised
comparison in this report tests the **water cap only**.

**Evidence for the water cap.** Under the HW-11 configuration `balanced` ended games
holding 3.88 water on average, and 37% of players ended with 5 or more, although no space
costs more than 2.

**Expected effect.** Less water held; possibly a higher win rate from turns no longer
spent collecting water.

**Evidence for the earlier two caps.** The `legacy` strategy values solari, spice and
water at a flat rate. It won 7.0% against three `balanced`. It also uses an older way of
valuing extra agents, so this is not a clean test of the caps alone.

### 3.3 Leaders

The environment now includes the eight base-game leaders. Each player gets a different
random leader with a passive ability and a signet ability. Leaders are on by default and
`--no-leaders` plays without them. One leader, Helena Richese, reserves a card from the
Imperium row that only she can buy that round, for 1 persuasion less. The leader draw
depends on the seed and the line-up, so each leader appears about equally often.

The baseline comparison in this report is run without leaders, because HW-11 had none.
Leader results are reported separately in section 5.6.

### 3.4 Blocking opponents' victory points

**Evidence.** The value function scored only the agent's own position. Yet about four
games in five end because a player reaches 10 VP, so an opponent's last point decides
most games, and the agent did nothing about it.

**What was added.** A weight, `deny`, that subtracts a share of the value of opponents'
victory points from the agent's score for a position. It counts three things the agent
can change with its own turn:

- the VP on this round's conflict card, if an opponent is placed to win it (send enough
  troops to out-fight them);
- a VP an opponent would gain from a free faction space (take the space first);
- points already held (an alliance can be taken away).

A point that would take an opponent to 10 VP counts three times as much. `deny` is 0 by
default, so `balanced` and every earlier strategy play exactly as before.

Two forms were tested. *Block all* counts every opponent point. *Block the winning point
only* ignores opponents until one is a point from 10 VP. Each was added to `balanced` and
to the three leading strategies, so each blocking strategy has an identical strategy
without blocking to compare against.

**Expected effect.** A higher win rate from stopping opponents' deciding points.

### 3.5 The preserved baseline

`--water flat` gives every unit of water full value, as in HW-11. With it, and without
leaders, the seven HW-11 cases reproduce their saved HW-11 results exactly (VP, rank,
number of decisions, options and near-ties), and the 200-game HW-11 aggregate reproduces
(win rate 25.0%, average VP 7.48, 23.0 decisions per game). An automated test checks the
case reproduction. `strategies/balanced_flat_water.json` is the HW-11 `balanced` as a
strategy, so the old and new versions can play in the same game.

## 4. Measures

| Measure | Definition | Better is |
|---|---|---|
| Success status | The agent under test finishes first (ties count) | Met |
| Win rate | Share of games the strategy wins; fair share is 25% with 4 players | Higher |
| 95% interval | Wilson interval on the win rate | Narrower |
| Average VP | Victory points at game end, averaged over games | Higher |
| Average rank | Finishing place, 1 to 4, averaged over games | Lower |
| Water at game end | Water the player still holds when the game ends | Lower |
| Decisions per game | Turns where the agent had more than one legal option | Reported |
| Time per decision | Wall-clock milliseconds to choose a turn | Lower |
| Near-ties | Share of scored decisions with the top two options within 0.5 utility | Lower |
| Fallbacks | Turns replaced by a reveal after an illegal action or agent error | 0 |

A strategy is called *better* or *worse* than the baseline only when its 95% interval
excludes 25%. One VP is worth 10 utility points, so a near-tie margin is 1/20 of a VP.

## 5. Results

### 5.1 Retained cases

Ten cases in `cases/evaluation.json`, each one full game with seed 7. Cases c1 to c7 are
the HW-11 cases; c8 to c10 are new. "Baseline" is the HW-11 configuration (`--water
flat`); "revised" is the current default.

| Case | Kind | Players (agent under test first) |
|---|---|---|
| c1 | Supported | `balanced` vs 3 `random` |
| c2 | Supported | `bene_gesserit_faction` vs 3 `balanced` |
| c3 | Unsuccessful | `fremen_faction` vs 3 `balanced` |
| c4 | Boundary | `balanced` vs `balanced` (2 players) |
| c5 | Failure handling | `FaultyAgent` vs 3 `balanced` |
| c6 | Unsupported input | Unknown strategy name |
| c7 | Unsupported input | 5 players |
| c8 | Difficult | `rush_both` vs the other three top strategies, random leaders |
| c9 | Supported | `balanced` as Helena Richese vs 3 `balanced` with leaders |
| c10 | Unsuccessful | `rush_council` vs 3 `balanced` |

Outcome and success status (agent finishes first):

| Case | Baseline outcome | Baseline VP, rank | Revised outcome | Revised VP, rank |
|---|---|---|---|---|
| c1 | **Met**, ended round 8 | 10, 1st | **Met**, ended round 8 | 10, 1st |
| c2 | **Met**, full 10 rounds | 8, 1st | **Not met**, ended round 9 | 6, 2nd |
| c3 | **Not met**, ended round 9 | 4, 4th | **Met**, ended round 8 | 10, 1st |
| c4 | **Met**, ended round 9 | 10, 1st | **Met**, ended round 9 | 12, 1st |
| c5 | **Not met**, 10 rounds | 2, 4th | **Not met**, 10 rounds | 2, 4th |
| c6 | Rejected, exit code 2 | no game | Rejected, exit code 2 | no game |
| c7 | Rejected, exit code 2 | no game | Rejected, exit code 2 | no game |
| c8 | **Not met**, 10 rounds | 7, 4th | **Not met**, 10 rounds | 8, 3rd |
| c9 | **Not met**, 10 rounds | 9, 2nd | **Not met**, ended round 9 | 8, 2nd |
| c10 | **Not met**, 10 rounds | 8, 2nd | **Not met**, 10 rounds | 8, 2nd |

All ten cases behaved as their definition expects in both configurations: games ran to an
explicit end, the faulty agent was contained, and bad input was rejected without a game.

Cases c2 and c3 changed outcome between configurations. Each case is one game, and a
small change in valuation changes the whole game from the first differing turn. A single
case shows that a path works; it does not measure a strategy. Over 1,000 games c2's
strategy wins 30.0% and c3's wins 11.2% (section 5.2).

Cost and reliability for the agent under test, revised configuration:

| Case | Turn decisions | Options per decision | ms per decision | Near-ties | Fallbacks |
|---|---|---|---|---|---|
| c1 | 16 | 13.6 | 8.74 | 40.0% | 0 |
| c2 | 22 | 12.4 | 7.44 | 36.4% | 0 |
| c3 | 20 | 15.3 | 8.78 | 10.0% | 0 |
| c4 | 20 | 15.2 | 6.58 | 42.1% | 0 |
| c5 | 14 | 13.3 | 0.0 | n/a | 6 |
| c8 | 28 | 11.9 | 6.93 | 38.5% | 0 |
| c9 | 22 | 17.8 | 10.59 | 25.0% | 0 |
| c10 | 22 | 14.6 | 8.71 | 38.1% | 0 |

c5's agent is random apart from its faults, so it reports no scores. Its six faults were
each replaced by a reveal turn and the game finished.

### 5.2 Every strategy against three `balanced`

1,000 games per strategy, seeds 1 to 1000, seating shuffled, no leaders. In each column
the three opponents are that configuration's own `balanced`.

| Strategy | Baseline win % | Revised win % | Revised 95% interval | Revised avg VP | Revised verdict |
|---|---|---|---|---|---|
| `bene_gesserit_faction` | 29.6 | **30.0** | 27.2 to 32.9 | 7.98 | Better |
| `rush_swordmaster` (new) | 29.1 | **29.5** | 26.8 to 32.4 | 7.69 | Better |
| `rush_both` (new) | 29.8 | **28.5** | 25.8 to 31.4 | 7.90 | Better |
| `deckbuilder` | 26.5 | 25.8 | 23.2 to 28.6 | 7.88 | No clear difference |
| `card_draw` (new) | 22.7 | 25.7 | 23.1 to 28.5 | 7.66 | No clear difference |
| `alliances` | 25.0 | 25.2 | 22.6 to 28.0 | 7.71 | No clear difference |
| `emperor_faction` | 26.4 | 24.7 | 22.1 to 27.5 | 7.35 | No clear difference |
| `factions` | 23.7 | 23.2 | 20.7 to 25.9 | 7.65 | No clear difference |
| `emperor_cards` | 22.4 | 22.6 | 20.1 to 25.3 | 7.37 | No clear difference |
| `bene_gesserit_cards` | 21.7 | 22.1 | 19.6 to 24.8 | 7.45 | Worse |
| `military` | 22.4 | 20.7 | 18.3 to 23.3 | 6.98 | Worse |
| `guild_cards` | 19.8 | 20.4 | 18.0 to 23.0 | 7.18 | Worse |
| `guild_faction` | 18.7 | 19.8 | 17.4 to 22.4 | 7.30 | Worse |
| `fremen_cards` | 17.4 | 19.2 | 16.9 to 21.8 | 6.99 | Worse |
| `spice` | 19.2 | 17.5 | 15.3 to 20.0 | 6.78 | Worse |
| `rush_council` (new) | 17.1 | 17.3 | 15.1 to 19.8 | 7.23 | Worse |
| `spice_must_flow` | 17.5 | 17.1 | 14.9 to 19.6 | 7.36 | Worse |
| `thin_deck` | 18.7 | 14.8 | 12.7 to 17.1 | 7.18 | Worse |
| `fremen_faction` | 9.5 | 11.2 | 9.4 to 13.3 | 6.40 | Worse |
| `legacy` | 8.4 | 7.0 | 5.6 to 8.8 | 5.58 | Worse |
| `random` | 0.0 | 0.0 | 0.0 to 0.4 | 2.16 | Worse |

- **The HW-11 target is met.** Three strategies have a 95% interval above 25%, in both
  configurations. Two of the three are new in this checkpoint.
- **The same three lead under both configurations**, so the finding does not depend on
  the water cap.
- **Buying the third agent matters more than the council seat.** `rush_swordmaster` and
  `rush_both` are better than the baseline; `rush_council`, which refuses the
  Swordmaster, is clearly worse.
- **Most baseline-to-revised differences are within noise.** The largest are `thin_deck`
  (18.7 to 14.8) and `card_draw` (22.7 to 25.7).

**Screening at 200 games misled.** These strategies looked strong at 200 games and fell
back to the fair share at 1,000:

| Strategy | 200 games | 1,000 games |
|---|---|---|
| `card_draw` | 31.0% | 25.7% |
| `deckbuilder` | 30.5% | 25.8% |
| `alliances` | 29.5% | 25.2% |
| `rush_council` | 26.5% | 17.3% |

### 5.3 The best four against each other

1,000 games at one table, seating shuffled, no leaders.

| Strategy | Baseline win % | Revised win % | Revised 95% interval | Revised avg VP | Avg rank |
|---|---|---|---|---|---|
| `bene_gesserit_faction` | 29.7 | 27.7 | 25.0 to 30.6 | 7.85 | 2.36 |
| `rush_swordmaster` | 23.6 | 25.8 | 23.2 to 28.6 | 7.38 | 2.56 |
| `rush_both` | 25.0 | 25.4 | 22.8 to 28.2 | 7.49 | 2.51 |
| `deckbuilder` | 21.7 | 21.1 | 18.7 to 23.7 | 7.57 | 2.57 |

`bene_gesserit_faction` has the highest win rate in both configurations, but its interval
overlaps the two rush strategies, so the top three cannot be ranked from this run.
`deckbuilder` is clearly below the fair share: it was level with `balanced` but loses
ground against stronger opponents.

### 5.4 The water cap

| Measure | Baseline (flat) | Revised (capped) |
|---|---|---|
| Water held at game end, `balanced` mirror, 800 player-games | 3.88 | 2.94 |
| Players ending with 5 or more water | 37.2% | 16.9% |
| Water held at the end of round 8 | 3.70 | 3.03 |
| Average VP, `balanced` mirror | 7.48 | 7.75 |
| Win rate of capped `balanced` vs 3 uncapped (1,000 games) | 25.0% by definition | 23.4% (20.9 to 26.1) |
| Average VP in that head-to-head | 7.58 (uncapped) | 7.63 (capped) |

The cap did what it was built to do: agents hold about one water less and half as many
end with a stockpile. It did **not** make the agent win more. The head-to-head interval
includes 25%, so the capped agent is neither better nor worse than the uncapped one. The
expected win-rate gain did not appear. The likely reason is that the hoarded water came
mostly as a side effect of turns the agent wanted for other reasons, so not hoarding
frees few turns.

### 5.5 Cost and reliability

`balanced` against itself, 200 games, 800 player-games per column.

| Measure | Baseline | Revised |
|---|---|---|
| Games completing legally | 200 of 200 | 200 of 200 |
| Fallbacks per game | 0.00 | 0.00 |
| Turn decisions per player per game | 23.0 | 23.3 |
| Legal options per decision | 13.6 | 13.6 |
| Time per decision (all cores busy) | 14.7 ms | 13.4 ms |
| Near-tie decisions | 38% | 37% |
| Games ending early at 10 VP before round 10 | 26% | 18% |

The refinements did not change the agent's cost: it is the same one-step search. Every
aggregate run without leaders finished all of its games (54,400 in total). Fallbacks are
counted only in the two runs above and in the cases.

### 5.6 Leaders

With random leaders, 2,000 games each. Leaders are a new part of the environment, so
there is no HW-11 baseline for these.

Four `balanced` players, win rate by leader (each leader played about 1,000 times):

| Leader | Win % | 95% interval |
|---|---|---|
| Baron Vladimir Harkonnen | 34.4 | 31.5 to 37.4 |
| Count Ilban Richese | 27.1 | 24.5 to 29.9 |
| Glossu "The Beast" Rabban | 26.6 | 24.0 to 29.5 |
| Count Memnon Thorvald | 25.7 | 23.0 to 28.5 |
| Duke Leto Atreides | 24.2 | 21.7 to 27.0 |
| Paul Atreides | 23.1 | 20.7 to 25.8 |
| Helena Richese | 20.1 | 17.7 to 22.7 |
| Countess Ariana Thorvald | 18.7 | 16.4 to 21.3 |

The best four strategies with random leaders:

| Strategy | Win % | 95% interval | Avg VP |
|---|---|---|---|
| `rush_both` | 28.2 | 26.3 to 30.3 | 7.93 |
| `rush_swordmaster` | 27.6 | 25.7 to 29.7 | 7.68 |
| `bene_gesserit_faction` | 26.1 | 24.3 to 28.1 | 7.96 |
| `deckbuilder` | 17.9 | 16.3 to 19.7 | 7.50 |

The strategy picture is the same with leaders: three close strategies and `deckbuilder`
behind. The leader a player draws matters about as much as the strategy: the gap between
the best and worst leader (16 points) is larger than the gap between the top three
strategies.

### 5.7 Blocking

One strategy against three `balanced`, 1,000 games each, seeds 1 to 1000, no leaders,
revised configuration. The "no blocking" column is the same strategy from section 5.2 on
the same seeds. 95% intervals in brackets.

| Strategy | No blocking | Block all points | Block the winning point only |
|---|---|---|---|
| `balanced` | 25.0 (fair share) | **21.5** (19.1 to 24.2) | 23.0 (20.5 to 25.7) |
| `balanced`, double weight | 25.0 (fair share) | **20.6** (18.2 to 23.2) | not run |
| `bene_gesserit_faction` | 30.0 | 27.3 (24.6 to 30.1) | 30.3 (27.5 to 33.2) |
| `rush_swordmaster` | 29.5 | 30.8 (28.0 to 33.7) | 29.7 (26.9 to 32.6) |
| `rush_both` | 28.5 | 25.1 (22.5 to 27.9) | 28.7 (26.0 to 31.6) |

The expected gain did not appear.

- **Blocking all points made the agent worse.** `balanced` with blocking is below the
  fair share at both weights, and two of the three leading strategies lost their lead:
  their intervals now include 25%.
- **Blocking only the winning point changed nothing measurable.** The three leading
  strategies are within 0.3 points of their results without it.

A likely reason, not tested: with four players, troops or a turn spent stopping one
opponent help the other two as much as the blocker. Blocking is kept in the code, off by
default, and no strategy in the focus set uses it.

## 6. Representative examples

All from `results/evaluation/cases_revised/`. Each case folder holds `trace.txt`,
`trace.json`, `result.json` and a step-through `replay.html`.

**Successful 1: case c1, the baseline agent beats three random players.** Last line of
`c1_supported_vs_random/trace.txt`:

```
RESULT: 10 VP reached after 8 rounds; P1 [balanced] 10 VP (rank 1), P2 [random] 2 VP
(rank 2), P3 [random] 1 VP (rank 4), P4 [random] 2 VP (rank 3)
```

**Successful 2: case c4, the two-player boundary.**

```
RESULT: 10 VP reached after 9 rounds; P1 [balanced] 12 VP (rank 1), P2 [balanced] 10 VP
(rank 2)
```

**Successful path, lost game: case c9, a leader ability.** Helena's first decision, from
`c9_supported_leader_reserve/trace.txt`. She reserves Chani and buys it in her reveal:

```
[step 3] round 1
  options  : 13 legal, decided in 7.28 ms
      >>   20.76  Signet Ring -> Carthag
           20.18  Signet Ring -> Secure Contract
           19.38  Dune, The Desert Planet -> Secure Contract
         ... 10 more
  action   : P1 plays Signet Ring -> Carthag, reserves Chani from the Imperium row,
             deploys 1
  ...
  action   : P1 reveals Dune, The Desert Planet, Dune, The Desert Planet, Convincing
             Argument (swords 0); buys Chani
```

**Unsuccessful 1: case c10, a strategy that loses.** `rush_council` took its council seat
and never the Swordmaster, as designed, and finished second:

```
RESULT: 10 VP reached after 10 rounds; P1 [rush_council] 8 VP (rank 2), P2 [balanced]
7 VP (rank 3), P3 [balanced] 7 VP (rank 4), P4 [balanced] 10 VP (rank 1)
```

**Unsuccessful 2: case c5, a faulty agent.** Its illegal action is replaced by a reveal
turn, counted and logged, and the game continues:

```
  FALLBACK : illegal action ('agent', 99, 'No Such Space') -> replaced by a reveal turn
  action   : P1 reveals Reconnaissance, Diplomacy, Convincing Argument, Dagger, Seek
             Allies (swords 1)
...
RESULT: 10 VP reached after 10 rounds; P1 [faulty] 2 VP (rank 4), P2 [balanced] 5 VP
(rank 2), P3 [balanced] 14 VP (rank 1), P4 [balanced] 4 VP (rank 3)
```

**Unsupported: case c6, bad input.** `c6_unsupported_unknown_strategy/error.txt`:

```
error: unknown or unloadable strategy 'no_such_strategy' (unknown strategy
'no_such_strategy'). Run `python3 -m dune_sim list` to see the built-in names
exit code 2, no game run
```

**Limited: case c2, one game is not a measure.** The strongest strategy over 1,000 games
loses this single game in the revised configuration and wins it in the baseline:

```
RESULT: 10 VP reached after 9 rounds; P1 [bene_gesserit_faction] 6 VP (rank 2),
P2 [balanced] 11 VP (rank 1), P3 [balanced] 4 VP (rank 3), P4 [balanced] 3 VP (rank 4)
```

## 7. Variation, failures and limitations

- **Sampling variation.** At 1,000 games a win rate has a 95% interval of about plus or
  minus 2.7 points; at 200 games, about plus or minus 6. Differences smaller than that
  are not findings. The 200-game screen produced four false leads (section 5.2).
- **Single games vary widely.** Two of ten cases changed outcome when one weight changed.
- **The top three strategies are not ranked.** Their intervals overlap in every run.
- **The baseline moved.** The water cap changed `balanced` itself, the fixed opponent.
  Every comparison here is run against one stated version of `balanced`.
- **The water cap did not improve the win rate.** It is kept because it removes
  behaviour that made no sense, not because it wins more.
- **Blocking did not improve the win rate** in either form (section 5.7). How often the
  agent had a chance to block the winning point was not measured, so "no difference" for
  that form may partly mean it rarely applies. Only one weight (and one doubled) was tried.
- **Rollouts were not built.** The HW-11 plan changed (section 3.1). Near-ties are still
  37% of decisions.
- **Helena's reserve did not help her.** She won 21.8% with a simplified ability and
  20.1% with the real one, which is within noise.
- **Leaders are unbalanced in the simulator.** Baron wins 34.4% with identical play.
  Leader abilities were written from memory and simplified, and have not been checked
  against the physical game.
- **Cards are approximations.** Imperium cards, conflict rewards and intrigue cards keep
  their names with simplified effects.
- **Time per decision** depends on the machine and on how many cores are busy.
- **Saved metadata.** The runs were made on the working tree that became the submitted
  commit. Their `results.json` files therefore record the previous commit with
  `code_differs_from_commit: true`. Re-running the commands at the submitted commit
  reproduces the numbers.
- **Scope of the conclusions.** Results hold for this engine, these simplified cards,
  four-player games (plus one two-player case), opponents that are copies of `balanced`
  or of the top strategies, and the seeds used. They say nothing about human opponents.

## 8. Provisional recommendation evidence

| Recommendation | Evidence for it now |
|---|---|
| **Use within a defined scope** | As a tool for comparing strategies inside this simulator. All 54,400 no-leader evaluation games completed. No built-in agent fell back. Runs are repeatable from a command. At 1,000 games it separates better, level and worse strategies, and the top three held up under both configurations and with leaders. |
| **Revise before use** | For conclusions about leaders, or about fine rankings. Leader abilities are unverified and one leader dominates. The top three strategies cannot be ranked. 37% of decisions are near-ties. |
| **Do not use** | For predicting the real board game or advising human players. Card effects are approximations and nothing has been validated against real play. |

Provisional assessment: **use within a defined scope**, as a strategy-comparison tool for
this simulator, with the leader results marked as unverified.

## 9. Final-completion plan

Work before December 3, in priority order. Each item comes from a result above.

| Priority | Work | Evidence behind it |
|---|---|---|
| 1 | Check the eight leader abilities against the physical game and correct them | Baron wins 34.4% with identical play (5.6) |
| 2 | Run the controlled strategy-by-leader test for the three focus strategies | The leader matters as much as the strategy (5.6); the first attempt was stopped before it finished |
| 3 | Look at `rush_swordmaster` ending games with about 10 unspent solari | It never buys the council seat, so its solari has no use (5.3 raw results) |
| 4 | Count how often the winning point could be blocked, and how often it was | Blocking only the winning point made no measurable difference (5.7), and it is not known whether it rarely applies or does not work |
| 5 | Final report and presentation | Required |

Not planned: rollouts, new strategies, or expansions. The week of Thanksgiving is kept for
items 1 to 4; documentation and presentation follow.

## 10. Retained files

| Path | Contents |
|---|---|
| `cases/evaluation.json` | The ten case definitions |
| `results/evaluation/run_all.sh` | Every evaluation command |
| `results/evaluation/cases_baseline/`, `cases_revised/` | Case tables and one folder per case with trace, result and replay |
| `results/evaluation/benchmark_baseline/`, `benchmark_revised/` | Section 5.2: summary, JSON, one CSV of games per strategy |
| `results/evaluation/top4_baseline/`, `top4_revised/` | Section 5.3 |
| `results/evaluation/h2h_revised_vs_baseline/` | Section 5.4 head-to-head |
| `results/evaluation/mirror_baseline/`, `mirror_revised/` | Sections 5.4 and 5.5 |
| `results/leaders_balanced_mirror_helena/`, `results/top4_leaders/` | Section 5.6 |
| `results/benchmark_water_cap/` | The 200-game screen quoted in section 5.2 |
| `results/vertical_slice/` | The HW-11 results the baseline reproduces |
| `results/benchmark_blocking_1000/`, `results/benchmark_blocking_win_1000/` | Section 5.7 |
| `tests/test_repeatable.py` | 30 automated tests |
