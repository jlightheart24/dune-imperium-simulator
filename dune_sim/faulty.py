"""Deliberately faulty agents, used to exercise the engine's failure handling.

    python3 -m dune_sim trace -p dune_sim.faulty:FaultyAgent balanced balanced balanced --seed 3
"""
from .strategies import RandomStrategy


class FaultyAgent(RandomStrategy):
    """Plays randomly, but every 3rd turn returns an action that is not legal and every
    5th turn raises an exception. Deterministic: the faults depend only on the turn count."""

    def __init__(self):
        super().__init__(seed=0)
        self.name = "faulty"
        self.calls = 0

    def choose_turn(self, game, p, actions):
        self.calls += 1
        if self.calls % 5 == 0:
            raise RuntimeError("simulated agent crash")
        if self.calls % 3 == 0:
            return ("agent", 99, "No Such Space")
        return super().choose_turn(game, p, actions)
