# Agent Evaluation and Refinement

**Project:** A strategy-testing agent for the board game *Dune: Imperium*

| | |
|---|---|
| Name | Jonny Lightheart |
| Repository | https://github.com/jlightheart24/dune-imperium-simulator |
| Submitted commit | COMMIT_HASH_IN_PDF |
| Date | November 18, 2026 |

---

## 1. Summary

The agent plays *Dune: Imperium* by scoring each legal turn one step ahead with a weighted
value function. A "strategy" is a set of weights and rules for that agent. The project's
purpose is to find out which strategies are better.

Refinements since the vertical slice (U0-HW-11), the previous checkpoint. The vertical
slice built the first complete agent, measured it against three copies of `balanced`, and
proposed Monte Carlo rollouts on near-tie decisions as the next change:

1. **Strategy search** (main refinement): new strategies, each tested against three
   copies of the fixed baseline `balanced`, then the best four against each other.
2. **Monte Carlo rollouts** on near-tie decisions: the close turns are played forward
   several times and the one with the best average result is taken.
3. **Resource caps** on solari, spice and water, which stop the agent hoarding. The water
   cap is new.
4. **Blocking**, which makes the agent act against opponents' victory points.
5. **Leader abilities**: the game is played with 8 leaders who have distinct abilities
   and signet rings.

Main results, without leaders and at 1,000 games per row unless stated:

- Three strategies beat the baseline with a 95% interval above the 25% fair share:
  `bene_gesserit_faction` (30.0%), `rush_swordmaster` (29.5%) and `rush_both` (28.5%).
  At the vertical slice only one strategy out of 17 did, and only at 200 games. The
  vertical slice's bar for a better agent was a 95% interval above 25%; three now clear it.
- Against each other the top three are close (25% to 28%) and cannot be ranked.
- **Rollouts worked.** `balanced` with rollouts won 29.0% against three `balanced`
  without (95% interval 26.3 to 31.9), meeting the target the vertical slice set for this
  change. Added to the three leading strategies, rollouts raised them from 28.5-30.0% to
  35.0-37.4%. The cost is time: a decision settled by rollouts takes about 1 second, against 13 ms.
- **The resource caps work as a set.** With all three caps, `balanced` won 30.8%
  against three copies with none (95% interval 28.0 to 33.7). Without caps, players end
  games holding 14.6 solari, against 6.0 with them. The water cap on its own cut water
  held from 3.88 to 2.94 but did not change the win rate (23.4%, 20.9 to 26.1).
- Blocking did **not** help: blocking every opponent point made `balanced` worse (21.5%).
- Correcting two leader abilities cut the gap between the best and worst leader from 16
  points to 8. Baron Harkonnen still leads (29.5%).
- All ten retained cases behaved as defined under both configurations. No built-in agent
  needed a fallback turn.

Every table below shows the rows that matter for its point. The complete output of every
run (all strategies, all leaders, per-game CSVs) is saved in the repository; section 10
lists where.

## 2. Commands

**Setup.** Python 3.9 or later. No packages, credentials or network access.

```
git clone https://github.com/jlightheart24/dune-imperium-simulator.git
cd dune-imperium-simulator
python3 -m unittest          # 36 tests, about 30 seconds
```

**Exact evaluation command.** One script runs every result in this report, in order
(about 9 hours on 10 cores). Each line of it can also be run on its own.

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

**Evidence from the vertical slice.** It tested 17 strategies against three `balanced`,
200 games each. Only one beat the baseline, and its 95% interval was wide (25.5 to 38.2).
Its bar for a better agent was a win rate against three `balanced` whose 95% interval
lies above 25%.

**What was added.** Four strategies: `rush_council` (buy a High Council seat as fast as
possible, never the Swordmaster), `rush_swordmaster` (the reverse), `rush_both`, and
`card_draw`; a setting, `avoid_spaces`, for board spaces a strategy never uses; and a
`tournament` command.

**Method.** (1) *Screen*: each strategy against three `balanced`, 200 games. (2)
*Confirm*: the same at 1,000 games, which narrows the 95% interval from about plus or
minus 6 points to about 2.7. (3) *Head-to-head*: the best four at one table, 1,000 games.

**Expected effect.** More strategies reliably above 25%, and a ranking that holds up when
the strong strategies meet.

### 3.2 Monte Carlo rollouts on near-ties

**Evidence from the vertical slice.** It found that in 38% of scored turn decisions the
best two turns were within 0.5 utility (1/20 of a VP) of each other, and concluded that
at that margin the one-step evaluation is effectively guessing. It proposed rollouts for
exactly these decisions: play each close turn forward to the end of the round several
times and take the best average. Its target for the change was a win rate against three
`balanced` with a 95% interval above 25%, no fallbacks, and time per decision reported.

**What was added.** A strategy setting, `rollouts`. When it is above 0 and the best two
or three turns are within 0.5 of each other, the agent:

1. makes a copy of the game from its own point of view (below);
2. plays each close turn in the copy, then lets every player continue to the end of the
   round with its normal one-step play, through combat;
3. scores its own position after the round with the same value function;
4. repeats this 8 times per turn and takes the turn with the best average.

Every close turn is tried on the same 8 copies, so the comparison is between turns, not
between copies. Rollouts stop at the end of the round because a full-game rollout would
cost about a second each. There are no rollouts inside rollouts.

**Hidden information.** The agent must not see opponents' hands. In *Dune: Imperium*
every card a player owns is public (starting deck, purchases, discard pile, cards played
this round), so only the split between hand and draw deck is hidden. Each copy therefore
pools each opponent's hand with their draw deck, shuffles, and deals back a hand of the
same size: one random guess at what they could hold. Intrigue cards are secret, so each
opponent's intrigue cards are pooled with the intrigue deck and re-dealt the same way.
Draw-deck orders and the order of the remaining conflict cards are also reshuffled.
Averaging over 8 copies averages over 8 guesses.

Four strategies use it: `balanced_rollout` and the three leading strategies with
`_rollout`. Each is identical to its base strategy apart from rollouts, so its result
against three `balanced` isolates the effect. Rollouts are off by default.

**Expected effect.** Better choices on near-ties and a higher win rate, at a higher cost
per decision.

### 3.3 Resource caps: solari, spice and water

The value function scores resources the agent holds. If every unit is worth the same, the
agent keeps collecting a resource it has no use for. Each cap values a resource fully up
to what the agent can spend, and little beyond that.

| Resource | Full value up to | Value beyond | Reason for the limit | Added |
|---|---|---|---|---|
| Solari | 8 | 20% | The most expensive space (Swordmaster) costs 8 | Before the vertical slice |
| Spice | 10 | 30% | Heighliner (6) plus Conspire (4) | Before the vertical slice |
| Water | 4 | 15% | Two 2-water spaces | This checkpoint |

The three caps are one idea, applied to each resource the agent can stockpile, so they
are evaluated together. The water cap, the one added in this checkpoint, is also tested
on its own.

**Evidence.** The solari and spice caps were already part of the agent at the vertical
slice, but had never been tested. The vertical slice showed the problem they
address in water, the one resource without a cap: `balanced` ended games holding 3.88 water on average,
and 37% of players held 5 or more, although no space costs more than 2. The water cap
completes the set.

**How they are tested.** The solari and spice caps are already in the vertical slice's
baseline, so the baseline-to-revised comparison isolates the water cap. To judge the caps
as a whole, `strategies/balanced_no_caps.json` is `balanced` with all three turned off
(every unit of every resource at full value). It plays against three `balanced`, and four
copies play each other to measure what they hold.

**Expected effect.** Less of each resource left unspent at game end, and possibly more
wins from turns no longer spent collecting what cannot be used.

### 3.4 Blocking opponents' victory points

**Evidence.** About four games in five end because a player reaches 10 VP, yet the value
function scored only the agent's own position.

**What was added.** A weight, `deny`, that subtracts a share of the value of opponents'
victory points: the point on this round's conflict card if an opponent is placed to win
it, a point waiting on a free faction space, and points already held. A point that would
take an opponent to 10 VP counts three times as much. Two forms were tested: *block all*
and *block the winning point only*. Off by default.

**Expected effect.** A higher win rate from stopping opponents' deciding points.

### 3.5 Leaders

The environment includes the eight base-game leaders, assigned at random (`--no-leaders`
plays without). The abilities were first written from memory. During this checkpoint I
read all eight against the game and corrected two; the other six matched.

| Leader | Ability | As first written | Corrected |
|---|---|---|---|
| Duke Leto Atreides | Prudent Diplomacy | 1 spice for 1 influence with any faction | Only where another player has more influence than he does |
| Baron Vladimir Harkonnen | Masterstroke | Free at the start of round 2 | Once per game, on a turn where he deploys 4 or more troops |

The baseline comparison is run without leaders, because the vertical slice had none.

## 4. Measures

| Measure | Definition | Better is |
|---|---|---|
| Success status | The agent under test finishes first (ties count) | Met |
| Win rate | Share of games the strategy wins; fair share is 25% with 4 players | Higher |
| 95% interval | Wilson interval on the win rate | Narrower |
| Average VP | Victory points at game end, averaged over games | Higher |
| Time per decision | Wall-clock milliseconds to choose a turn | Lower |
| Near-ties | Share of scored decisions with the top two options within 0.5 utility | Lower |
| Rollout changes | Share of rolled-out decisions where rollouts picked a different turn | Reported |
| Fallbacks | Turns replaced by a reveal after an illegal action or agent error | 0 |

A strategy is called *better* or *worse* than the baseline only when its 95% interval
excludes 25%. One VP is worth 10 utility points.

## 5. Results

### 5.1 Retained cases

Ten cases in `cases/evaluation.json`, each one full game with seed 7. Cases c1 to c7 are
the vertical slice's cases; c8 to c10 are new. "Baseline" is the vertical slice's
configuration (`--water flat`); "revised" is the current default.

| Case | Kind | Players (agent under test first) | Baseline | Revised |
|---|---|---|---|---|
| c1 | Supported | `balanced` vs 3 `random` | **Met**, 10 VP | **Met**, 10 VP |
| c2 | Supported | `bene_gesserit_faction` vs 3 `balanced` | **Met**, 8 VP | Not met, 6 VP, 2nd |
| c3 | Unsuccessful | `fremen_faction` vs 3 `balanced` | Not met, 4 VP, 4th | **Met**, 10 VP |
| c4 | Boundary | `balanced` vs `balanced` (2 players) | **Met**, 10 VP | **Met**, 12 VP |
| c5 | Failure handling | `FaultyAgent` vs 3 `balanced` | Not met, 4th | Not met, 4th |
| c6 | Unsupported input | Unknown strategy name | Rejected, exit 2 | Rejected, exit 2 |
| c7 | Unsupported input | 5 players | Rejected, exit 2 | Rejected, exit 2 |
| c8 | Difficult | `rush_both` vs the other top strategies, leaders | Not met, 8 VP, 2nd | **Met**, 10 VP |
| c9 | Supported | `balanced` as Helena Richese, leaders | Not met, 9 VP, 2nd | Not met, 8 VP, 2nd |
| c10 | Unsuccessful | `rush_council` vs 3 `balanced` | Not met, 8 VP, 2nd | Not met, 8 VP, 2nd |

All ten behaved as their definition expects in both configurations: games ran to an
explicit end, the faulty agent's six faults were each replaced by a reveal turn, and bad
input was rejected without a game. Every built-in agent made 16 to 22 decisions at 5.6
to 9.3 ms each, with no fallbacks. The per-case cost table is in
`results/evaluation/cases_revised/cases.md`.

Cases c2, c3 and c8 changed outcome between configurations. One game changes from the
first differing turn, so a single case shows that a path works; it does not measure a
strategy. Over 1,000 games c2's strategy wins 30.0% and c3's 11.2% (section 5.2).

### 5.2 Every strategy against three `balanced`

21 strategies, 1,000 games each, seeds 1 to 1000, seating shuffled, no leaders. Three
were better than the baseline, six showed no clear difference and twelve were worse. The
table shows the three better ones and the strategies discussed below; the full table is
in `results/evaluation/benchmark_revised/summary.txt`.

| Strategy | Baseline win % | Revised win % | Revised 95% interval | Revised verdict |
|---|---|---|---|---|
| `bene_gesserit_faction` | 29.6 | **30.0** | 27.2 to 32.9 | Better |
| `rush_swordmaster` (new) | 29.1 | **29.5** | 26.8 to 32.4 | Better |
| `rush_both` (new) | 29.8 | **28.5** | 25.8 to 31.4 | Better |
| `deckbuilder` | 26.5 | 25.8 | 23.2 to 28.6 | No clear difference |
| `card_draw` (new) | 22.7 | 25.7 | 23.1 to 28.5 | No clear difference |
| `rush_council` (new) | 17.1 | 17.3 | 15.1 to 19.8 | Worse |
| `fremen_faction` | 9.5 | 11.2 | 9.4 to 13.3 | Worse |

- **The vertical slice's bar is met**: three strategies have a 95% interval above 25%, in
  both configurations. Two of the three are new.
- **The same three lead under both configurations**, so the finding does not depend on
  the water cap.
- **The third agent matters more than the council seat.** Both strategies that rush the
  Swordmaster are better; `rush_council`, which refuses it, is clearly worse.

**Screening at 200 games misled.** Four strategies looked strong at 200 games and fell
back at 1,000: `card_draw` (31.0% to 25.7%), `deckbuilder` (30.5% to 25.8%), `alliances`
(29.5% to 25.2%) and `rush_council` (26.5% to 17.3%).

### 5.3 The best four against each other

1,000 games at one table, seating shuffled, no leaders.

| Strategy | Baseline win % | Revised win % | Revised 95% interval |
|---|---|---|---|
| `bene_gesserit_faction` | 29.7 | 27.7 | 25.0 to 30.6 |
| `rush_swordmaster` | 23.6 | 25.8 | 23.2 to 28.6 |
| `rush_both` | 25.0 | 25.4 | 22.8 to 28.2 |
| `deckbuilder` | 21.7 | 21.1 | 18.7 to 23.7 |

`bene_gesserit_faction` has the highest win rate in both configurations, but its interval
overlaps the two rush strategies, so the top three cannot be ranked. `deckbuilder` was
level with `balanced` but falls below the fair share against stronger opponents.

### 5.4 Monte Carlo rollouts

Each rollout strategy in one seat against three `balanced` (no rollouts), 1,000 games,
seeds 1 to 1000, seating shuffled, no leaders, revised configuration. The "without"
column is the same strategy without rollouts on the same seeds (section 5.2).

| Strategy | Without rollouts | With rollouts | With: 95% interval | With: avg VP |
|---|---|---|---|---|
| `balanced` | 25.0 (fair share) | **29.0** | 26.3 to 31.9 | 8.04 |
| `bene_gesserit_faction` | 30.0 | **35.0** | 32.1 to 38.0 | 8.25 |
| `rush_swordmaster` | 29.5 | **37.3** | 34.4 to 40.3 | 8.29 |
| `rush_both` | 28.5 | **37.4** | 34.5 to 40.4 | 8.44 |

- **The vertical slice's target is met.** `balanced` with rollouts, against three copies
  of itself without, has a 95% interval above 25%. The only difference between the seats
  is rollouts, so the gain is from rollouts.
- **Rollouts add to the strategy search.** All three leading strategies gained 5 to 9
  points. For the two rush strategies the intervals with and without rollouts do not
  overlap; for `bene_gesserit_faction` they overlap by under a point.
- **The answer to the vertical slice's question.** It asked whether the weights or the
  search depth limit the agent. Rollouts on only the near-tie decisions gave a gain as
  large as the whole strategy search, so search depth was a real limit.

Cost and behaviour, `balanced` with rollouts against three `balanced`, 200 games
(`results/evaluation/cost_rollout/`):

| Measure | Without rollouts | With rollouts |
|---|---|---|
| Time per decision, average over all decisions | 13.0 ms | 343 ms |
| Time per decision settled by rollouts (derived) | n/a | about 990 ms |
| Decisions settled by rollouts, per game | 0 | 7.8 of 23.1 |
| ... where rollouts chose a different turn | n/a | 50% |
| Fallbacks per game | 0.00 | 0.00 |

Rollouts settle about a third of the agent's decisions and change half of those, about
four turns per game. A game with one rollout agent takes about 8 seconds of processor
time, against about 1 second without. Every game finished legally.

### 5.5 Resource caps

Three versions of `balanced`: no caps (`strategies/balanced_no_caps.json`), the
solari and spice caps only (the vertical slice), and all three (revised). Holdings are
from four copies playing each other, 200 games (800 player-games) each; win rates from
one capped `balanced` against three copies of the other version, 1,000 games.

| Measure | No caps | Solari and spice caps | All three caps |
|---|---|---|---|
| Solari held at game end | 14.6 | 5.8 | 6.0 |
| Players ending with 9 or more solari | 64.9% | 23.2% | 26.2% |
| Spice held at game end | 5.9 | 7.7 | 8.0 |
| Players ending with 10 or more spice | 19.5% | 31.6% | 34.5% |
| Water held at game end | 3.02 | 3.88 | 2.94 |
| Players ending with 5 or more water | 25.2% | 37.2% | 16.9% |
| Average VP, four copies | 7.38 | 7.48 | 7.75 |
| Win rate of all three caps against three of this version | **30.8%** (28.0 to 33.7) | 23.4% (20.9 to 26.1) | 25.0% by definition |

- **As a set, the caps make the agent better.** All three caps against none wins
  30.8%, and the 95% interval lies wholly above 25%.
- **Most of the effect is the solari cap.** Without caps the agent ends games with 14.6
  solari, more than any space costs, and two players in three hold 9 or more. Those solari
  came from turns that could have earned something it could use.
- **A cap moves hoarding to the next uncapped resource.** With no caps the agent hoards
  solari and water stays low (3.02). Capping solari and spice pushed the surplus into
  water (3.88), which is the problem the vertical slice showed. Capping water too brings
  it down to 2.94.
- **The water cap on its own did what it was built to do but did not win more.** The
  likely reason is that the extra water came as a side effect of turns the agent wanted
  for other reasons, so not hoarding it frees few turns. It is kept because it completes
  the set and removes a stockpile that made no sense.

### 5.6 Blocking

The blocking strategy against three `balanced`, 1,000 games, same seeds as section 5.2. 95%
intervals in brackets.

| Strategy | No blocking | Block all points | Block the winning point only |
|---|---|---|---|
| `balanced` | 25.0 (fair share) | **21.5** (19.1 to 24.2) | 23.0 (20.5 to 25.7) |
| `bene_gesserit_faction` | 30.0 | 27.3 (24.6 to 30.1) | 30.3 (27.5 to 33.2) |
| `rush_swordmaster` | 29.5 | 30.8 (28.0 to 33.7) | 29.7 (26.9 to 32.6) |
| `rush_both` | 28.5 | 25.1 (22.5 to 27.9) | 28.7 (26.0 to 31.6) |

Blocking all points made `balanced` worse, and two of the three leading strategies lost
their lead. Blocking only the winning point changed nothing measurable. A doubled weight
was also tried and was worse (`results/benchmark_blocking_1000/`). A likely reason, not
tested: with four players, a turn spent stopping one opponent helps the other two as much
as the blocker. Blocking stays in the code, off by default.

### 5.7 Leaders

Four `balanced` players with random leaders, 2,000 games (each leader about 1,000 times),
before and after the two corrections, same seeds. The three leaders below are the best,
the worst and the other corrected one; all eight are in
`results/leaders_balanced_mirror_corrected/summary.txt`.

| Leader | Before correction | Corrected | Corrected 95% interval |
|---|---|---|---|
| Baron Vladimir Harkonnen (corrected) | 34.4 | 29.5 | 26.7 to 32.4 |
| Duke Leto Atreides (corrected) | 24.2 | 23.6 | 21.1 to 26.4 |
| Paul Atreides | 23.1 | 21.5 | 19.0 to 24.1 |

The gap between the best and worst leader fell from 16 points to 8. Baron is still the
only leader whose interval lies above 25%, and Paul the only one whose interval lies
below. In a separate 300-game check, not
retained, Baron triggered Masterstroke in every game, on average by round 2, so the new
condition rarely holds him back.

With leaders, the best four strategies give the same picture as without: the top three
are within 3 points of each other (25.6% to 28.3%) and `deckbuilder` is behind (19.8%).
The leader a player draws matters more than the choice among the top three strategies.

### 5.8 Cost and reliability

`balanced` against itself, 200 games, 800 player-games per column.

| Measure | Baseline | Revised |
|---|---|---|
| Games completing legally | 200 of 200 | 200 of 200 |
| Fallbacks per game | 0.00 | 0.00 |
| Turn decisions per player per game | 23.0 | 23.3 |
| Time per decision (all cores busy) | 14.7 ms | 13.4 ms |
| Near-tie decisions | 38% | 37% |

Every aggregate run finished all of its games. The cost of rollouts is in section 5.4.

## 6. Representative examples

From `results/evaluation/cases_revised/` unless stated. Each case folder holds
`trace.txt`, `trace.json`, `result.json` and a step-through `replay.html`; the examples
below are the last lines or one decision. The other cases are in the same folder.

**Successful: case c1, the baseline agent beats three random players.**

```
RESULT: 10 VP reached after 8 rounds; P1 [balanced] 10 VP (rank 1), P2 [random] 2 VP
(rank 2), P3 [random] 1 VP (rank 4), P4 [random] 2 VP (rank 3)
```

**Successful: a rollout decision** (`results/evaluation/trace_rollout/`, `balanced`
with rollouts, seed 7). The one-step score cannot separate the two best turns, so both
are rolled out 8 times to the end of the round. Secrets ends the round better on average,
and its +1 Bene Gesserit influence is a victory point:

```
  options  : 21 legal, decided in 1062.67 ms by rule (rollouts (8 each):
             Diplomacy -> Wealth 48.25, Diplomacy -> Secrets 52.91)
           46.69  Diplomacy -> Wealth
      >>   46.69  Diplomacy -> Secrets
           40.73  Signet Ring -> Hagga Basin
         ... 18 more
  action   : P1 plays Diplomacy -> Secrets
  effect   : vp +1, bene_gesserit influence +1
```

This game is also a reminder that one game is not a measure: the rollout agent finished
third with 6 VP.

**Unsuccessful: case c10, a strategy that loses.** `rush_council` took its council seat
and never the Swordmaster, as designed, and finished second:

```
RESULT: 10 VP reached after 10 rounds; P1 [rush_council] 8 VP (rank 2), P2 [balanced]
7 VP (rank 3), P3 [balanced] 7 VP (rank 4), P4 [balanced] 10 VP (rank 1)
```

**Failure handling: case c5, a faulty agent.** Its illegal action is replaced by a
reveal turn, counted and logged, and the game continues:

```
  FALLBACK : illegal action ('agent', 99, 'No Such Space') -> replaced by a reveal turn
...
RESULT: 10 VP reached after 10 rounds; P1 [faulty] 2 VP (rank 4), P2 [balanced] 5 VP
(rank 2), P3 [balanced] 14 VP (rank 1), P4 [balanced] 4 VP (rank 3)
```

**Unsupported: case c6, bad input.**

```
error: unknown or unloadable strategy 'no_such_strategy' (unknown strategy
'no_such_strategy'). Run `python3 -m dune_sim list` to see the built-in names
exit code 2, no game run
```

## 7. Variation, failures and limitations

- **Sampling variation.** At 1,000 games a win rate has a 95% interval of about plus or
  minus 2.7 points; at 200, about 6. The 200-game screen produced four false leads.
- **Single games vary widely.** Three of ten cases changed outcome when one weight changed.
- **The top three strategies are not ranked.** Their intervals overlap in every run.
- **The baseline moved.** The water cap changed `balanced` itself, the fixed opponent.
  Every comparison is run against one stated version of `balanced`.
- **Rollouts were tested at one setting.** 8 rollouts per turn, the top 3 turns, the
  0.5 near-tie margin, ending at the end of the round, without leaders and only against
  opponents without rollouts. Inside a rollout, opponents play their real strategy, so
  the agent is assumed to know how opponents play, though not what they hold. The guess
  at opponents' hands is uniform: it ignores what their earlier turns suggest.
- **The solari and spice caps were not tested one at a time.** The caps were judged as
  a set and the water cap alone, so how much of the 30.8% comes from each is not
  measured; the holdings suggest most comes from solari.
- **Blocking did not improve the win rate.** How often the agent could block the winning
  point was not measured, so "no difference" may partly mean it rarely applies.
- **Leaders are still unbalanced.** After two corrections Baron wins 29.5% with identical
  play. The abilities were checked by reading them against the game, not by comparing
  play. Two details of Masterstroke are assumptions: the agent chooses the two factions,
  and only troops deployed from the agent turn count toward the four.
- **Cards are approximations.** Imperium, conflict and intrigue cards keep their names
  with simplified effects.
- **Time per decision** depends on the machine and how many cores are busy.
- **Saved metadata.** The runs were made on the working tree that became the submitted
  commit, so their `results.json` files record the previous commit with
  `code_differs_from_commit: true`. Re-running at the submitted commit reproduces them.
- **Scope.** Results hold for this engine, these simplified cards, four-player games
  (plus one two-player case), opponents that are copies of `balanced` or of the top
  strategies, and the seeds used. They say nothing about human opponents.

## 8. Provisional recommendation evidence

| Recommendation | Evidence for it now |
|---|---|
| **Use within a defined scope** | As a tool for comparing strategies inside this simulator. All evaluation games completed and no built-in agent fell back. Runs are repeatable from a command. At 1,000 games it separates better, level and worse strategies, and the top three held up under both configurations and with leaders. |
| **Revise before use** | For conclusions about leaders, or about fine rankings. Leader abilities were checked only by reading, and one leader still leads. The top three strategies cannot be ranked. Rollouts were tested at one setting and only against opponents without them. |
| **Do not use** | For predicting the real board game or advising human players. Card effects are approximations and nothing has been validated against real play. |

Provisional assessment: **use within a defined scope**, as a strategy-comparison tool for
this simulator, with the leader results marked as provisional.

## 9. Final-completion plan

Work before December 3, in priority order. Each item comes from a result above.

| Priority | Work | Evidence behind it |
|---|---|---|
| 1 | Test rollouts further: the top four with rollouts against each other, with leaders, and at more rollouts or a wider margin | Rollouts gave the largest gain in this checkpoint (5.4) but were tested at one setting and only against opponents without them |
| 2 | Settle the two open details of Masterstroke and find out why Baron still leads | Baron wins 29.5% with identical play after the correction (5.7) |
| 3 | Run the controlled strategy-by-leader test for the three focus strategies | The leader a player draws matters more than the choice among the top three (5.7) |
| 4 | Count how often the winning point could be blocked, and how often it was | Blocking only the winning point made no measurable difference (5.6) |
| 5 | Final report and presentation | Required |

Not planned: new strategies or expansions. The week of Thanksgiving is kept for items 1
to 4; documentation and presentation follow.

## 10. Retained files

Everything a table above summarises is saved in full here.

| Path | Contents |
|---|---|
| `cases/evaluation.json` | The ten case definitions |
| `results/evaluation/run_all.sh` | Every evaluation command |
| `results/evaluation/cases_baseline/`, `cases_revised/` | Section 5.1: case tables with cost per case, one folder per case with trace, result and replay |
| `results/evaluation/benchmark_baseline/`, `benchmark_revised/` | Section 5.2: all 21 strategies, one CSV of games per strategy |
| `results/benchmark_water_cap/` | The 200-game screen quoted in section 5.2 |
| `results/evaluation/top4_baseline/`, `top4_revised/` | Section 5.3 |
| `results/benchmark_rollout_1000/`, `results/evaluation/cost_rollout/`, `results/evaluation/trace_rollout/` | Section 5.4 |
| `results/evaluation/h2h_revised_vs_baseline/`, `mirror_baseline/`, `mirror_revised/` | Sections 5.5 and 5.8 |
| `strategies/balanced_no_caps.json`, `results/evaluation/h2h_caps_vs_no_caps/`, `mirror_no_caps/` | Section 5.5, the caps as a set |
| `results/benchmark_blocking_1000/`, `results/benchmark_blocking_win_1000/` | Section 5.6 |
| `results/leaders_balanced_mirror_corrected/`, `results/top4_leaders_corrected/` | Section 5.7: all eight leaders |
| `results/leaders_balanced_mirror_helena/`, `results/top4_leaders/` | Section 5.7, before the corrections |
| `results/vertical_slice/` | The vertical slice's results, which the baseline reproduces |
| `tests/test_repeatable.py` | 36 automated tests |
