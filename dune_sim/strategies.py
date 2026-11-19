"""Strategies (AI players).

A strategy is any object implementing the methods of `Strategy`. The engine
calls them at each decision point. To write your own, subclass `Strategy`
(or `HeuristicStrategy` and tweak weights / override single decisions) and
reference it from the CLI as `module.path:ClassName`.
"""
from __future__ import annotations

import importlib
import json
import os
import random
from typing import Dict, List, Optional

from .data import FACTIONS, SPACES, VP_TO_END


class Strategy:
    name = "base"

    def __deepcopy__(self, memo):  # strategies are shared across lookahead clones
        return self

    # --- decision points -------------------------------------------------
    def choose_turn(self, game, p, actions: list) -> tuple:
        """Pick from ('agent', hand_index, space) / ('reveal',)."""
        raise NotImplementedError

    def choose_deploy(self, game, p, max_n: int) -> int:
        return max_n

    def choose_purchase(self, game, p, options: list, budget: int):
        return None

    def choose_reserve(self, game, p, row: list):
        """Manipulate: pick the Imperium-row card to set aside (must be one of `row`)."""
        return row[0]

    def choose_influence(self, game, p, factions: List[str]) -> str:
        return factions[0]

    def choose_trash(self, game, p, cards: list):
        return None

    def choose_option(self, game, p, branches: List[list]) -> int:
        return len(branches) - 1

    def choose_plot_intrigue(self, game, p, cards: list):
        return None

    def choose_combat_intrigue(self, game, p, cards: list):
        return None


class RandomStrategy(Strategy):
    """Uniformly random legal play. A baseline every strategy should crush."""

    def __init__(self, seed: Optional[int] = None):
        self.name = "random"
        self.rng = random.Random(seed)

    def choose_turn(self, game, p, actions):
        agents = [a for a in actions if a[0] == "agent"]
        # reveal early only occasionally, otherwise random agents never get used
        if agents and self.rng.random() < 0.9:
            return self.rng.choice(agents)
        return ("reveal",)

    def choose_deploy(self, game, p, max_n):
        return self.rng.randint(0, max_n)

    def choose_purchase(self, game, p, options, budget):
        return self.rng.choice(options) if self.rng.random() < 0.8 else None

    def choose_reserve(self, game, p, row):
        return self.rng.choice(row)

    def choose_influence(self, game, p, factions):
        return self.rng.choice(factions)

    def choose_trash(self, game, p, cards):
        return self.rng.choice(cards) if self.rng.random() < 0.5 else None

    def choose_option(self, game, p, branches):
        return self.rng.randrange(len(branches))

    def choose_plot_intrigue(self, game, p, cards):
        return self.rng.choice(cards) if self.rng.random() < 0.5 else None

    def choose_combat_intrigue(self, game, p, cards):
        return self.rng.choice(cards) if self.rng.random() < 0.5 else None


# ---------------------------------------------------------------------------
# Heuristic strategy: one-ply lookahead over a weighted value function.
# Different weight profiles produce different play styles.
# ---------------------------------------------------------------------------

BASE_WEIGHTS: Dict = {
    "vp": 10.0,
    "spice": 1.6, "solari": 1.0, "water": 2.2, "troop": 1.3, "intrigue": 2.0,
    "influence": {"emperor": 1.5, "guild": 1.5, "bene_gesserit": 1.5, "fremen": 1.5},
    "influence_threshold_bonus": 2.0,  # extra pull toward 2 (VP) and 4 (alliance)
    "persuasion": 0.8, "swords": 0.35, "draw": 1.5, "trash": 1.2,
    "deck": 0.9,           # weight of total deck quality (scaled by rounds left)
    "card_baseline": 1.3,  # cards weaker than this make the deck worse
    "icon": 0.35,          # value of each agent icon on a card
    "agent": 7.0,          # legacy only: flat value of a permanent extra agent
    "agent_turn": 3.0,     # value of one agent placement (prices Swordmaster and Mentat)
    "solari_need_max": 8,  # never value more than this many solari at full value
    "solari_excess": 0.2,  # value multiplier for solari beyond what there is left to buy
    "mentat_float": 1.4,   # multiplier on the first 2 solari (keeps Mentat affordable)
    "spice_need": 10,      # spice worth holding at full value (Heighliner + Conspire)
    "spice_excess": 0.3,   # value multiplier for spice beyond that (1.0 = flat valuation)
    "water_need": 4,       # water worth holding at full value (two 2-water spaces)
    "water_excess": 0.15,  # value multiplier for water beyond that
    "legacy": False,       # True = old linear solari / flat agent valuation
    # Spaces to take whenever legal and affordable, in priority order (skipped in the
    # final round, when they can no longer pay off). Empty = decide by evaluation only.
    "alliance": 0.0,       # extra value per alliance held, and pull toward winnable ones
    "priority_spaces": [],
    # Spaces this strategy never uses.
    "avoid_spaces": [],
    # Cards to buy whenever they are affordable, in priority order.
    "priority_cards": [],
    "card_persuasion": 1.0,  # value of each persuasion on a card when judging what to buy/keep
    # Extra value for owning a card of each type (its faction; "none" = unaffiliated).
    # Positive = prioritise buying that type, negative = avoid it. A typical card is worth 2-5.
    "card_type": {"emperor": 0.0, "guild": 0.0, "bene_gesserit": 0.0, "fremen": 0.0, "none": 0.0},
    "seat": 8.0,           # value of a High Council seat (early)
    "conflict": 1.0,       # multiplier on expected conflict reward value
    "conflict_confidence": 0.7,
    "opponent_margin": 2,  # assumed hidden strength per opponent still to act
    "aggression": 0.3,     # 0 = only fight if cheap, 1 = always throw troops in
    "control": 4.0,
    # Blocking: how much an opponent's victory point counts against this player, as a
    # share of the value of one of its own (0 = ignore opponents, the HW-11 behaviour).
    "deny": 0.0,
    "deny_win": 3.0,       # multiplier when the point would take that opponent to 10 VP
    "deny_other": 1.0,     # multiplier for every other point (0 = block only the winning one)
    # Rollouts: on a near-tie, play each close turn forward to the end of the round several
    # times, on copies where opponents' hands and intrigue are a random guess, and take the
    # turn with the best average end-of-round value. 0 = off (the one-step agent).
    "rollouts": 0,         # rollouts per close turn
    "rollout_top": 3,      # at most this many of the best one-step turns are rolled out
    "rollout_margin": 0.5, # a turn is close if within this of the best (the near-tie margin)
}

PROFILES: Dict[str, Dict] = {
    "balanced": {"priority_spaces": ["Swordmaster", "High Council"]},
    "legacy": {"legacy": True},  # the original valuation, kept for A/B comparisons
    "military": {
        "troop": 1.5, "conflict": 1.8, "aggression": 0.9, "swords": 0.8,
        "influence": {"emperor": 2.0, "guild": 1.5, "bene_gesserit": 1.0, "fremen": 2.0},
    },
    "spice": {
        "spice": 2.4, "solari": 1.4, "water": 2.6, "conflict": 0.6, "aggression": 0.1,
        "persuasion": 1.0,
    },
    "factions": {
        "influence": {"emperor": 3.2, "guild": 3.2, "bene_gesserit": 3.2, "fremen": 3.2},
        "influence_threshold_bonus": 4.0, "conflict": 0.8,
    },
    "fremen_faction": {
        "influence": {"emperor": 1.0, "guild": 1.0, "bene_gesserit": 1.0, "fremen": 4.5},
        "water": 2.8, "conflict": 1.3, "aggression": 0.6,
        "card_type": {"fremen": 1.5},
    },
    "deckbuilder": {
        "deck": 1.8, "trash": 2.5, "draw": 2.2, "persuasion": 1.2, "seat": 11.0,
        "conflict": 0.7,
    },
}


# Thin deck: trash weak cards at every chance and be picky about what gets bought.
PROFILES["thin_deck"] = {
    "trash": 4.0, "card_baseline": 2.0, "deck": 1.3,
    "influence": {"bene_gesserit": 2.5},  # Selective Breeding is the main trash space
    "priority_spaces": ["Selective Breeding"],
}
# Spice Must Flow rush: draw as many cards as possible, keep persuasion in hand,
# and buy The Spice Must Flow (9 persuasion, 1 VP) every time it is affordable.
PROFILES["spice_must_flow"] = {
    "priority_cards": ["The Spice Must Flow"],
    "priority_spaces": ["High Council"],      # +2 persuasion every reveal
    "draw": 3.5, "persuasion": 1.5, "card_persuasion": 1.7, "seat": 12.0,
    "trash": 2.0, "water": 2.6,               # Research Station (draw 3) costs 2 water
    "conflict": 0.6, "aggression": 0.1,
}
# Single-faction profiles, matching fremen_faction: heavy influence on one faction,
# a preference for its cards, and a lean toward what its board spaces need or give.
PROFILES["emperor_faction"] = {
    "influence": {"emperor": 4.5, "guild": 1.0, "bene_gesserit": 1.0, "fremen": 1.0},
    "card_type": {"emperor": 1.5},
    "spice": 1.9, "troop": 1.5, "conflict": 1.3, "aggression": 0.6,  # Conspire: 4 spice -> solari, troops, intrigue
}
PROFILES["guild_faction"] = {
    "influence": {"emperor": 1.0, "guild": 4.5, "bene_gesserit": 1.0, "fremen": 1.0},
    "card_type": {"guild": 1.5},
    "spice": 2.0, "troop": 1.5, "conflict": 1.3, "aggression": 0.6,  # Heighliner: 6 spice -> 5 troops, 2 water
}
PROFILES["bene_gesserit_faction"] = {
    "influence": {"emperor": 1.0, "guild": 1.0, "bene_gesserit": 4.5, "fremen": 1.0},
    "card_type": {"bene_gesserit": 1.5},
    "intrigue": 2.8, "trash": 2.0, "draw": 2.0,  # Secrets: intrigue; Selective Breeding: trash + draw
}
# Alliances: race to 4 influence where the alliance is still winnable, then hold it.
PROFILES["alliances"] = {
    "alliance": 6.0, "influence_threshold_bonus": 3.0,
    "influence": {"emperor": 2.2, "guild": 2.2, "bene_gesserit": 2.2, "fremen": 2.2},
    "conflict": 0.8,
}
# Card draw: see as many cards per round as possible. Favours Research Station (draw 3),
# Arrakeen, Mentat, Selective Breeding and cards whose agent effect draws.
PROFILES["card_draw"] = {
    "draw": 4.0, "water": 2.7,   # Research Station costs 2 water
    "persuasion": 1.1,           # more cards in hand at reveal is the payoff
    "conflict": 0.8,
}
# Rush profiles: save solari hard for the named purchase(s) and take them the moment they
# are affordable. Solari is valued above the default until the purchases are made.
PROFILES["rush_council"] = {      # High Council as fast as possible, never Swordmaster
    "priority_spaces": ["High Council"], "avoid_spaces": ["Swordmaster"],
    "solari": 1.6, "solari_need_max": 7,
}
PROFILES["rush_swordmaster"] = {  # Swordmaster as fast as possible, never High Council
    "priority_spaces": ["Swordmaster"], "avoid_spaces": ["High Council"],
    "solari": 1.6, "solari_need_max": 10,
}
PROFILES["rush_both"] = {         # Swordmaster first, then High Council, both as fast as possible
    "priority_spaces": ["Swordmaster", "High Council"],
    "solari": 1.6, "solari_need_max": 15,
}
# Blocking profiles: the same play as the named strategy, plus a penalty for victory
# points opponents hold or are about to gain (see HeuristicStrategy.threat). `blocker`
# is `balanced` with blocking, so its result against three `balanced` isolates the effect.
PROFILES["blocker"] = dict(PROFILES["balanced"], deny=0.5)
PROFILES["blocker_hard"] = dict(PROFILES["balanced"], deny=1.0)
# `_win` variants block only the point that would take an opponent to 10 VP.
PROFILES["blocker_win"] = dict(PROFILES["balanced"], deny=0.5, deny_other=0.0)
for _n in ("bene_gesserit_faction", "rush_swordmaster", "rush_both"):
    PROFILES[_n + "_block"] = dict(PROFILES[_n], deny=0.5)
    PROFILES[_n + "_win"] = dict(PROFILES[_n], deny=0.5, deny_other=0.0)
# Rollout profiles: the same play as the named strategy, but near-ties are settled by
# rollouts (see HeuristicStrategy.rollout_choice). Against three of the base strategy,
# the result isolates the effect of rollouts.
PROFILES["balanced_rollout"] = dict(PROFILES["balanced"], rollouts=8)
for _n in ("bene_gesserit_faction", "rush_swordmaster", "rush_both"):
    PROFILES[_n + "_rollout"] = dict(PROFILES[_n], rollouts=8)
ROLLOUT = ["balanced_rollout"] + [n + "_rollout" for n in
                                  ("bene_gesserit_faction", "rush_swordmaster", "rush_both")]
# One profile per card type: strongly prefers buying that faction's cards.
for _f in FACTIONS:
    PROFILES[_f + "_cards"] = {"card_type": {_f: 3.0}}


# The focus set: strategies whose 95% interval on win rate against three `balanced`
# was above the 25% fair share at 1,000 games each, no leaders, with the water cap
# (results/benchmark_water_cap_1000). Chosen by the project owner as the group to study.
# Use the word `focus` wherever the CLI takes strategy names, e.g. `benchmark focus`.
FOCUS = ["bene_gesserit_faction", "rush_swordmaster", "rush_both"]

# The blocking variants. They are left out of a default `benchmark` (which tests the base
# strategies) and run as a group with the word `blocking`, e.g. `benchmark blocking`.
BLOCKING = ["blocker", "blocker_hard", "blocker_win"] + [
    n + suffix for suffix in ("_block", "_win") for n in FOCUS]


def merged_weights(overrides: Dict) -> Dict:
    w = json.loads(json.dumps(BASE_WEIGHTS))
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(w.get(k), dict):
            w[k].update(v)
        else:
            w[k] = v
    return w


class HeuristicStrategy(Strategy):
    """Evaluates every legal action by simulating it on a clone of the game and
    scoring the resulting position with `evaluate`. Sub-decisions (deploy,
    purchases, influence picks, ...) use quick rules driven by the same weights."""

    def __init__(self, weights: Optional[Dict] = None, name: str = "heuristic",
                 noise: float = 0.0, seed: Optional[int] = None):
        self.w = merged_weights(weights or {})
        self.name = name
        self.noise = noise
        self.rng = random.Random(seed)

    # ------------------------------------------------------------ helpers
    def rounds_left(self, game) -> int:
        lead = max(game.total_vp(q) for q in game.players)
        by_vp = max(1, (10 - lead + 1))
        return max(1, min(len(game.conflict_deck) + 1, by_vp))

    def solari_need(self, game, p) -> int:
        """Solari the player still has a use for: Mentat float plus unbought sinks."""
        rl = self.rounds_left(game)
        need = 2                       # Mentat, every round
        avoid = self.w["avoid_spaces"]
        if not p.seat and rl >= 3 and "High Council" not in avoid:
            need += 5                  # High Council seat
        if p.agents_total < 3 and rl >= 3 and "Swordmaster" not in avoid:
            need += 8                  # Swordmaster
        if rl >= 2:
            need += 2                  # small float toward Rally Troops / card costs
        return min(need, self.w["solari_need_max"])

    def solari_value(self, game, p, n: int) -> float:
        """Total value of holding n solari. Full value up to what can still be
        bought, a premium on the first 2 (Mentat), steep discount beyond."""
        w = self.w
        if w["legacy"]:
            return n * w["solari"]
        need = self.solari_need(game, p)
        first = min(n, 2)
        useful = max(0, min(n, need) - 2)
        excess = max(0, n - need)
        return w["solari"] * (first * w["mentat_float"] + useful + excess * w["solari_excess"])

    def spice_value(self, game, p, n: int) -> float:
        """Total value of holding n spice: full value up to the biggest spice cost,
        discounted beyond, so stockpiles get spent or stop growing."""
        w = self.w
        if w["legacy"]:
            return n * w["spice"]
        need = w["spice_need"]
        return w["spice"] * (min(n, need) + max(0, n - need) * w["spice_excess"])

    def water_value(self, game, p, n: int) -> float:
        """Total value of holding n water: full value up to water_need, heavily
        discounted beyond, so a player holding 4 has little reason to take more."""
        w = self.w
        if w["legacy"]:
            return n * w["water"]
        need = w["water_need"]
        return w["water"] * (min(n, need) + max(0, n - need) * w["water_excess"])

    def spice_delta(self, game, p, n: int) -> float:
        cur = p.spice
        return self.spice_value(game, p, max(0, cur + n)) - self.spice_value(game, p, cur)

    def solari_delta(self, game, p, n: int) -> float:
        """Value of gaining (or, negative n, paying) n solari from the current holding."""
        cur = p.solari
        return self.solari_value(game, p, max(0, cur + n)) - self.solari_value(game, p, cur)

    def ops_value(self, game, p, ops: list, mult_vp: float = 1.0) -> float:
        w = self.w
        v = 0.0
        for op in ops:
            if "gain" in op:
                for k, n in op["gain"].items():
                    if k == "troops":
                        v += n * w["troop"]
                    elif k == "conflict_troops":
                        v += n * (w["troop"] + 1.0 * w["conflict"])
                    elif k == "vp":
                        v += n * w["vp"] * mult_vp
                    elif k == "solari":
                        v += self.solari_delta(game, p, n)
                    elif k == "spice":
                        v += self.spice_delta(game, p, n)
                    else:
                        v += n * w.get(k, 1.0)
            elif "pay" in op:
                for k, n in op["pay"].items():
                    if k == "solari":
                        v += self.solari_delta(game, p, -n)
                    elif k == "spice":
                        v += self.spice_delta(game, p, -n)
                    else:
                        v -= n * w.get("troop" if k == "troops" else k, 1.0)
            elif "influence" in op:
                f = op["influence"]
                n = op.get("n", 1)
                if f in FACTIONS:
                    v += n * self.influence_value(game, p, f)
                elif f == "trailing":
                    v += n * max([self.influence_value(game, p, g)
                                  for g in game.trailing_factions(p)] or [0.0])
                else:
                    v += n * max(self.influence_value(game, p, g) for g in FACTIONS)
            elif "trash" in op:
                v += w["trash"] * op["trash"]
            elif "optional" in op:
                v += max(0.0, self.ops_value(game, p, op["optional"], mult_vp))
            elif "choice" in op:
                v += max(self.ops_value(game, p, b, mult_vp) for b in op["choice"])
            elif "then" in op:
                v += 0.5 * self.ops_value(game, p, op["then"], mult_vp)
            elif "acquire" in op:
                v += 1.0
            elif "special" in op:
                v += 1.5
        return v

    def influence_value(self, game, p, f: str) -> float:
        cur = p.influence[f]
        if cur >= 6:
            return 0.0
        v = self.w["influence"][f]
        if cur + 1 == 2:
            v += self.w["vp"] * 0.9 + self.w["influence_threshold_bonus"]
        if cur + 1 >= 4:
            holder = game.alliance[f]
            if holder is None or (holder != p.idx and
                                  game.players[holder].influence[f] <= cur):
                v += self.w["influence_threshold_bonus"] * 1.5
        return v

    def alliance_value(self, game, p) -> float:
        """Value of alliances held plus progress toward ones that can still be won."""
        wa = self.w["alliance"]
        if not wa:
            return 0.0
        v = 0.0
        for f in FACTIONS:
            holder, mine = game.alliance[f], p.influence[f]
            if holder == p.idx:
                # held: worth more the bigger the lead over the closest rival
                rival = max(q.influence[f] for q in game.players if q is not p)
                v += wa * (1.0 + 0.15 * min(2, mine - rival))
            else:
                target = 4 if holder is None else game.players[holder].influence[f] + 1
                gap = target - mine
                if target <= 6 and gap <= 3:
                    v += wa * 0.2 * (4 - gap)   # closer = more valuable
        return v

    def card_power(self, game, p, card) -> float:
        w = self.w
        r = 0.0
        for op in card.reveal:
            if "gain" in op:
                g = op["gain"]
                r += g.get("persuasion", 0) * w["card_persuasion"] + g.get("swords", 0) * w["swords"] * 1.5
                rest = {k: v for k, v in g.items() if k not in ("persuasion", "swords")}
                r += self.ops_value(game, p, [{"gain": rest}]) if rest else 0
            else:
                r += self.ops_value(game, p, [op])
        a = self.ops_value(game, p, card.agent) * 0.6 + len(card.icons) * w["icon"]
        # type preference applies to Imperium-deck cards only; reserve piles such as
        # Arrakis Liaison are judged on their effects like any other card
        bonus = w["card_type"].get(card.faction or "none", 0.0) if card.kind == "imperium" else 0.0
        return r + a + bonus

    def deck_score(self, game, p) -> float:
        base = self.w["card_baseline"]
        return sum(self.card_power(game, p, c) - base for c in p.all_cards())

    def hand_reveal_value(self, game, p) -> float:
        tot = 0.0
        for c in p.hand:
            for op in c.reveal:
                if "gain" in op:
                    g = op["gain"]
                    tot += g.get("persuasion", 0) * self.w["persuasion"]
                    tot += g.get("swords", 0) * self.w["swords"]
                    rest = {k: v for k, v in g.items() if k not in ("persuasion", "swords")}
                    if rest:
                        tot += self.ops_value(game, p, [{"gain": rest}])
                else:
                    tot += 0.5 * self.ops_value(game, p, [op])
        return tot

    def estimated_strength(self, game, q) -> int:
        """An opponent's strength in this round's conflict, with an allowance for what
        they may still add before revealing."""
        s = game.strength(q)
        hidden = 0
        if not q.revealed:
            hidden += self.w["opponent_margin"] * max(1, game.agents_left(q))
        if q.conflict == 0 and hidden:
            hidden = hidden // 2  # they still might jump in
        return s + hidden

    def opponent_strengths(self, game, p) -> List[int]:
        return [self.estimated_strength(game, q) for q in game.players if q is not p]

    # -------------------------------------------------------------- blocking
    def influence_vp(self, game, q, f: str) -> int:
        """Victory points player q would gain from one more influence with faction f."""
        cur = q.influence[f]
        if cur >= 6:
            return 0
        vp = 1 if cur + 1 == 2 else 0
        holder = game.alliance[f]
        if holder is None:
            vp += 1 if cur + 1 >= 4 else 0
        elif holder != q.idx and cur + 1 > game.players[holder].influence[f]:
            vp += 1
        return vp

    def ops_vp(self, game, q, ops: list) -> int:
        """Victory points player q would gain from a list of effects."""
        vp = 0
        for op in ops:
            vp += op.get("gain", {}).get("vp", 0)
            f = op.get("influence")
            if f == "any":
                vp += max(self.influence_vp(game, q, x) for x in FACTIONS)
            elif f in FACTIONS:
                vp += self.influence_vp(game, q, f)
        return vp

    def threat(self, game, p, my_strength: int) -> float:
        """Penalty for victory points opponents hold or are about to gain. Three things
        this player can change are counted: points already held (an alliance can be
        taken away), the point on this round's conflict card (out-fight them), and a
        point waiting on an open faction space (occupy it first). A point that would
        take an opponent to 10 VP counts `deny_win` times as much."""
        w = self.w
        if not w["deny"]:
            return 0.0
        my_vp = game.total_vp(p)
        card = game.conflict_card
        fighting = card is not None and game.phase in ("player turns", "combat")
        placing = game.phase == "player turns"
        ranks = 3 if game.n >= 4 else 2
        est = {q.idx: (my_strength if q is p else self.estimated_strength(game, q))
               for q in game.players}
        total = 0.0
        for q in game.players:
            if q is p:
                continue
            held = game.total_vp(q)
            coming = 0.0
            if fighting and est[q.idx] > 0:
                rank = 1 + sum(1 for i, s in est.items() if i != q.idx and s >= est[q.idx])
                if rank <= ranks:
                    conf = w["conflict_confidence"] if placing else 1.0
                    coming += conf * self.ops_vp(game, q, card["rewards"][rank - 1])
            if placing and not q.revealed and game.agents_left(q) > 0:
                # their hand is hidden, so each open scoring space is a coin flip
                open_spaces = sum(1 for s in SPACES if s["faction"]
                                  and self.influence_vp(game, q, s["faction"])
                                  and game.space_ok(q, s))
                if open_spaces:
                    coming += 1.0 - 0.5 ** open_spaces
            urgency = w["deny_other"]
            if held + 1 >= VP_TO_END:
                urgency = w["deny_win"]
            elif held < my_vp - 2:
                urgency *= 0.5  # well behind: less worth spending a turn on
            if not urgency:
                continue
            total += urgency * (held + coming)
        return w["deny"] * w["vp"] * total

    def expected_conflict_value(self, game, p, my_strength: int) -> float:
        card = game.conflict_card
        if card is None or my_strength <= 0 or game.phase not in ("player turns", "combat"):
            return 0.0
        ranks = 3 if game.n >= 4 else 2
        rank = 1 + sum(1 for s in self.opponent_strengths(game, p) if s >= my_strength)
        if rank > ranks:
            return 0.0
        reward = card["rewards"][rank - 1]
        v = self.ops_value(game, p, reward, mult_vp=1.0)
        if rank == 1 and card.get("control"):
            v += self.w["control"]
        conf = self.w["conflict_confidence"] if game.phase == "player turns" else 1.0
        return v * conf * self.w["conflict"]

    def my_projected_strength(self, game, p, extra_troops: int = 0) -> int:
        troops = p.conflict + extra_troops
        if troops <= 0:
            return 0
        swords = p.swords
        if not p.revealed:
            for c in p.hand:
                for op in c.reveal:
                    if "gain" in op:
                        swords += op["gain"].get("swords", 0)
        return 2 * troops + swords

    # ----------------------------------------------------------- evaluation
    def evaluate(self, game, p) -> float:
        w = self.w
        rl = self.rounds_left(game)
        legacy = w["legacy"]
        if legacy:
            res_mult = 0.35 + 0.65 * min(1.0, rl / 3.0)
        else:  # leftovers are only a tiebreaker: fade to ~0 in the final round
            res_mult = min(1.0, 0.1 + 0.3 * (rl - 1))
        deck_mult = min(1.0, rl / 8.0)
        v = game.total_vp(p) * w["vp"]
        v += res_mult * (self.spice_value(game, p, p.spice) + self.solari_value(game, p, p.solari)
                         + self.water_value(game, p, p.water)
                         + p.garrison * w["troop"] + len(p.intrigue) * w["intrigue"])
        for f in FACTIONS:
            v += p.influence[f] * w["influence"][f] * res_mult
        v += w["deck"] * deck_mult * self.deck_score(game, p)
        v += self.alliance_value(game, p)
        v += self.hand_reveal_value(game, p)
        if p.held is not None:   # a reserved card: worth its 1-persuasion discount if we want it
            v += w["persuasion"] * (1.0 if self.purchase_value(game, p, p.held) > 0 else 0.25)
        v += p.persuasion * w["persuasion"]
        if legacy:
            v += (p.agents_total - 2) * w["agent"] * min(1.0, rl / 5.0)
        else:
            # a third agent is worth one placement per remaining future round
            v += (p.agents_total - 2) * w["agent_turn"] * 0.8 * (rl - 1)
            # placements still available this round (what Mentat adds, what an early reveal forfeits)
            if not p.revealed:
                v += min(game.agents_left(p), len(p.hand)) * w["agent_turn"]
        v += (w["seat"] * min(1.0, rl / 6.0)) if p.seat else 0.0
        mine = self.my_projected_strength(game, p)
        v += self.expected_conflict_value(game, p, mine)
        v -= self.threat(game, p, mine)
        return v

    # ------------------------------------------------------------ decisions
    def choose_turn(self, game, p, actions):
        if self.w["avoid_spaces"]:
            actions = [a for a in actions
                       if not (a[0] == "agent" and a[2] in self.w["avoid_spaces"])]
        if self.w["priority_spaces"] and self.rounds_left(game) > 1:
            for space in self.w["priority_spaces"]:
                picks = [a for a in actions if a[0] == "agent" and a[2] == space]
                if picks:
                    game.last_rule = f"priority space: {space}"
                    # several cards can reach it: give up the one worth least at reveal
                    return min(picks, key=lambda a: self.card_power(game, p, p.hand[a[1]]))
        best, best_v = actions[-1], -1e18
        scores = {}
        for a in actions:
            g = game.clone()
            g.do_action(p.idx, a)
            v = self.evaluate(g, g.players[p.idx])
            if self.noise:
                v += self.rng.gauss(0, self.noise)
            scores[a] = v
            if v > best_v:
                best, best_v = a, v
        game.last_scores = scores   # lets the engine record why this action was chosen
        if self.w["rollouts"] and not game.in_rollout:
            margin = self.w["rollout_margin"]
            ranked = sorted(scores, key=lambda a: -scores[a])[:self.w["rollout_top"]]
            close = [a for a in ranked if best_v - scores[a] < margin]
            if len(close) >= 2:
                best = self.rollout_choice(game, p, close)
        return best

    def rollout_choice(self, game, p, candidates: list) -> tuple:
        """Play each candidate turn forward to the end of the round `rollouts` times and
        return the one with the best average value for p. Each rollout is a copy from p's
        point of view: opponents' hands and intrigue cards are re-dealt at random from what
        they could be (Game.redeal_hidden). Every candidate is tried on the same guesses,
        so the comparison is between turns, not between guesses. Inside a rollout every
        player, p included, plays its own strategy one step ahead, without rollouts."""
        n = self.w["rollouts"]
        seeds = [game.rng.getrandbits(32) for _ in range(n)]
        totals = dict.fromkeys(candidates, 0.0)
        for s in seeds:
            for a in candidates:
                g = game.clone(hide_for=p.idx, seed=s)
                g.in_rollout = True
                g.do_action(p.idx, a)
                g.player_turns(p.idx + 1)
                g.finish_round()
                totals[a] += self.evaluate(g, g.players[p.idx])
        pick = max(candidates, key=lambda a: totals[a])   # a tie keeps the one-step order
        p.rollout_decisions += 1
        p.rollout_changed += pick != candidates[0]
        game.last_rule = "rollouts ({} each): ".format(n) + ", ".join(
            "{} {:.2f}".format(game.action_label(p, a), totals[a] / n) for a in candidates)
        return pick

    def choose_deploy(self, game, p, max_n):
        best_n, best_v = 0, -1e18
        for n in range(max_n + 1):
            st = self.my_projected_strength(game, p, n)
            v = self.expected_conflict_value(game, p, st) - self.threat(game, p, st)
            ms = p.leader.get("masterstroke") if p.leader else None
            if ms and not p.masterstroke_used and n >= ms["deploy"]:
                # Baron: this deployment triggers Masterstroke
                gains = sorted((self.influence_value(game, p, f) for f in FACTIONS), reverse=True)
                v += sum(gains[:ms["factions"]])
            v -= n * self.w["troop"] * (1.0 - self.w["aggression"])
            if v > best_v + 1e-9:
                best_n, best_v = n, v
        return best_n

    def choose_purchase(self, game, p, options, budget):
        for name in self.w["priority_cards"]:
            for c in options:
                if c.name == name:
                    return c
        best, best_v = None, 0.0
        for c in options:
            v = self.purchase_value(game, p, c)
            if v > best_v:
                best, best_v = c, v
        return best

    def purchase_value(self, game, p, c) -> float:
        deck_mult = min(1.0, self.rounds_left(game) / 6.0)
        v = (self.card_power(game, p, c) - self.w["card_baseline"] * 0.5) * deck_mult
        return v + self.ops_value(game, p, c.acquire)

    def expected_persuasion(self, game, p) -> int:
        """Persuasion this player would have if they revealed their current hand now."""
        n = p.persuasion + (2 if p.seat else 0)
        for c in p.hand:
            for op in c.reveal:
                if "gain" in op:
                    n += op["gain"].get("persuasion", 0)
        return n

    def choose_reserve(self, game, p, row):
        """Take the card we most want and can expect to afford at the discount;
        if there is none, take the strongest card so nobody else gets it."""
        budget = self.expected_persuasion(game, p)
        mine = [c for c in row if max(0, c.cost - 1) <= budget]
        for name in self.w["priority_cards"]:
            for c in mine:
                if c.name == name:
                    return c
        if mine:
            best = max(mine, key=lambda c: self.purchase_value(game, p, c))
            if self.purchase_value(game, p, best) > 0:
                return best
        return max(row, key=lambda c: self.card_power(game, p, c))

    def choose_influence(self, game, p, factions):
        return max(factions, key=lambda f: self.influence_value(game, p, f))

    def choose_trash(self, game, p, cards):
        worst = min(cards, key=lambda c: self.card_power(game, p, c))
        if self.card_power(game, p, worst) < self.w["card_baseline"]:
            return worst
        return None

    def choose_option(self, game, p, branches):
        vals = [self.ops_value(game, p, b) for b in branches]
        return max(range(len(branches)), key=lambda i: vals[i])

    def choose_plot_intrigue(self, game, p, cards):
        for c in cards:
            if "persuasion" in json.dumps(c.effects) and game.agents_left(p) > 0:
                continue  # hold persuasion boosts until the reveal turn
            if game.ops_affordable(p, c.effects) and self.ops_value(game, p, c.effects) > 0:
                return c
        return None

    def choose_combat_intrigue(self, game, p, cards):
        base = (self.expected_conflict_value(game, p, game.strength(p))
                - self.threat(game, p, game.strength(p)))
        best, best_gain = None, 0.5
        for c in cards:
            g = game.clone()
            q = g.players[p.idx]
            q.intrigue = [x for x in q.intrigue if x.name != c.name] + []
            g.apply_ops(q, c.effects, {})
            gain = (self.expected_conflict_value(g, q, g.strength(q))
                    - self.threat(g, q, g.strength(q)) - base)
            if gain > best_gain:
                best, best_gain = c, gain
        return best


# ---------------------------------------------------------------------------
WATER_MODES = ("capped", "flat")


def set_water_mode(mode: str) -> None:
    """`capped` (default): water beyond water_need is worth water_excess of its value.
    `flat`: every water at full value, as in the U0-HW-11 baseline. Stored in the
    environment as well so worker processes started later use the same setting."""
    if mode not in WATER_MODES:
        raise ValueError(f"unknown water mode {mode!r}; choose from {WATER_MODES}")
    os.environ["DUNE_WATER"] = mode
    BASE_WEIGHTS["water_excess"] = 1.0 if mode == "flat" else _CAPPED_WATER_EXCESS


_CAPPED_WATER_EXCESS = BASE_WEIGHTS["water_excess"]
if os.environ.get("DUNE_WATER") == "flat":
    BASE_WEIGHTS["water_excess"] = 1.0


def available_strategies() -> List[str]:
    return ["random"] + [f"heuristic:{k}" for k in PROFILES]


def make_strategy(spec: str, seed: Optional[int] = None) -> Strategy:
    """Build a strategy from a spec string:
         random | <profile> | heuristic:<profile> | weights:path.json | module.path:ClassName
    """
    if spec == "random":
        return RandomStrategy(seed)
    if spec in PROFILES:
        spec = "heuristic:" + spec
    if spec.startswith("heuristic:"):
        prof = spec.split(":", 1)[1]
        if prof not in PROFILES:
            raise ValueError(f"unknown profile {prof!r}; choose from {list(PROFILES)}")
        return HeuristicStrategy(PROFILES[prof], name=prof, seed=seed)
    if spec.startswith("weights:"):
        path = spec.split(":", 1)[1]
        with open(path) as fh:
            w = json.load(fh)
        name = w.pop("name", path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        return HeuristicStrategy(w, name=name, seed=seed)
    if ":" in spec:
        mod, cls = spec.rsplit(":", 1)
        obj = getattr(importlib.import_module(mod), cls)()
        if not getattr(obj, "name", None) or obj.name == "base":
            obj.name = cls
        return obj
    raise ValueError(f"unknown strategy {spec!r}")
