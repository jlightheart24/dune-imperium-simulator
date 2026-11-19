$ python3 -m dune_sim cases --file cases/evaluation.json --save results/evaluation/cases_revised

| case | kind | terminal status | success condition (agent finishes first) | VP | rank | decisions | ms / decision | near-ties | fallbacks | as expected |
|---|---|---|---|---|---|---|---|---|---|---|
| c1_supported_vs_random | supported | 10 VP reached after 8 rounds | met | 10 | 1 | 16 | 5.84 | 40.0% | 0 | yes |
| c2_supported_vs_baseline | supported | 10 VP reached after 9 rounds | not met | 6 | 2 | 22 | 6.12 | 36.4% | 0 | yes |
| c3_unsuccessful_weak_strategy | unsuccessful | 10 VP reached after 8 rounds | met | 10 | 1 | 20 | 7.46 | 10.0% | 0 | yes |
| c4_boundary_two_players | boundary | 10 VP reached after 9 rounds | met | 12 | 1 | 20 | 5.69 | 42.1% | 0 | yes |
| c5_failure_faulty_agent | failure handling | 10 VP reached after 10 rounds | not met | 2 | 4 | 14 | 0.0 | - | 6 | yes |
| c6_unsupported_unknown_strategy | unsupported input | rejected: unknown or unloadable strategy 'no_such_strategy' (unknown strategy 'no_such_strategy'). Run `python3 -m dune_sim list` to see the built-in names | not applicable (no game) | - | - | - | - | - | - | yes |
| c7_unsupported_five_players | unsupported input | rejected: unsupported table size: 5 players given, the game supports 2 to 4 | not applicable (no game) | - | - | - | - | - | - | yes |
| c8_difficult_top_four | difficult | 10 VP reached after 8 rounds | met | 10 | 1 | 19 | 5.6 | 17.6% | 0 | yes |
| c9_supported_leader_reserve | supported | 10 VP reached after 9 rounds | not met | 8 | 2 | 22 | 9.25 | 25.0% | 0 | yes |
| c10_unsuccessful_rush_council | unsuccessful | 10 VP reached after 10 rounds | not met | 8 | 2 | 22 | 7.26 | 38.1% | 0 | yes |
