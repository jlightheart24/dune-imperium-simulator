#!/bin/sh
# Every aggregate run in the U0 evaluation, in order. About 3.5 hours on 10 cores.
set -e
cd "$(dirname "$0")/../.."
F=weights:strategies/balanced_flat_water.json
python3 -m dune_sim batch -n 1000 --no-leaders -p balanced $F $F $F --save results/evaluation/h2h_revised_vs_baseline
python3 -m dune_sim batch -n 1000 --no-leaders --water flat -p rush_both rush_swordmaster bene_gesserit_faction deckbuilder --save results/evaluation/top4_baseline
python3 -m dune_sim batch -n 1000 --no-leaders -p rush_both rush_swordmaster bene_gesserit_faction deckbuilder --save results/evaluation/top4_revised
python3 -m dune_sim benchmark -n 1000 --no-leaders --water flat --save results/evaluation/benchmark_baseline
python3 -m dune_sim benchmark -n 1000 --no-leaders --save results/evaluation/benchmark_revised
python3 -m dune_sim batch -n 200 --detail --no-leaders --water flat -p balanced balanced balanced balanced --save results/evaluation/mirror_baseline
python3 -m dune_sim batch -n 200 --detail --no-leaders -p balanced balanced balanced balanced --save results/evaluation/mirror_revised
python3 -m dune_sim cases --file cases/evaluation.json --water flat --save results/evaluation/cases_baseline
python3 -m dune_sim cases --file cases/evaluation.json --save results/evaluation/cases_revised
# leaders (a new environment feature in this checkpoint)
python3 -m dune_sim batch -n 2000 -p balanced balanced balanced balanced --save leaders_balanced_mirror_helena
python3 -m dune_sim batch -n 2000 --detail -p bene_gesserit_faction rush_swordmaster rush_both deckbuilder --save top4_leaders
