"""Rules engine: game state, round structure, effect interpreter, replay recording."""
from __future__ import annotations

import copy
import random
import time
from typing import Any, Dict, List, Optional

from . import data
from .data import FACTIONS, SPACE_BY_NAME, SPACES


class Card:
    """Immutable card definition. Shared between game clones."""
    __slots__ = ("name", "cost", "icons", "agent", "reveal", "acquire", "faction", "kind")

    def __init__(self, d: dict, kind: str):
        self.name = d["name"]
        self.cost = d.get("cost", 0)
        self.icons = frozenset(d.get("icons", ()))
        self.agent = d.get("agent", [])
        self.reveal = d.get("reveal", [])
        self.acquire = d.get("acquire", [])
        self.faction = d.get("faction")
        self.kind = kind

    def __deepcopy__(self, memo):
        return self

    def __repr__(self):
        return f"<{self.name}>"


class Intrigue:
    __slots__ = ("name", "kind", "effects")

    def __init__(self, d: dict):
        self.name, self.kind, self.effects = d["name"], d["kind"], d["effects"]

    def __deepcopy__(self, memo):
        return self

    def __repr__(self):
        return f"<Intrigue {self.name}>"


def _expand(defs, factory):
    out = []
    for d in defs:
        out.extend(factory(d) for _ in range(d.get("count", 1)))
    return out


STARTER = [Card(d, "starter") for d in data.STARTER_DECK for _ in range(d.get("count", 1))]
RESERVE_CARDS = {d["name"]: Card(d, "reserve") for d in data.RESERVE}


class Player:
    def __init__(self, idx: int, name: str, strategy_name: str):
        self.idx = idx
        self.name = name
        self.strategy_name = strategy_name
        r = data.STARTING_RESOURCES
        self.spice, self.solari, self.water = r["spice"], r["solari"], r["water"]
        self.garrison, self.conflict = r["garrison"], 0
        self.vp = r["vp"]  # VP from cards/conflicts; influence & alliance VP are derived
        self.influence = {f: 0 for f in FACTIONS}
        self.bonus_claimed: set = set()
        self.deck: List[Card] = list(STARTER)
        self.hand: List[Card] = []
        self.discard: List[Card] = []
        self.in_play: List[Card] = []      # cards played with agents this round
        self.revealed_cards: List[Card] = []
        self.intrigue: List[Intrigue] = []
        self.agents_total = 2
        self.agents_used = 0
        self.mentat = False
        self.mentat_uses = 0
        self.leader: Optional[dict] = None   # entry from data.LEADERS, or None (no leaders)
        self.visited: set = set()            # spaces this player has used this round
        self.masterstroke_used = False
        self.held: Optional[Card] = None     # card set aside by Manipulate; only this player may buy it
        # statistics (do not affect play)
        self.earned = {"spice": 0, "solari": 0, "water": 0, "troops": 0, "draw": 0}
        self.conflict_wins = 0
        # decision statistics for choose_turn (the main decision point)
        self.decisions = 0          # times the agent was asked to choose a turn
        self.decision_time = 0.0    # seconds spent choosing
        self.options_total = 0      # legal options offered, summed
        self.scored = 0             # decisions where the agent reported utility scores
        self.near_ties = 0          # ... of which best and second-best were within NEAR_TIE
        self.fallbacks = 0          # illegal actions or agent errors replaced by a reveal turn
        self.rollout_decisions = 0  # near-ties settled by rollouts (strategies with rollouts > 0)
        self.rollout_changed = 0    # ... where rollouts picked a different turn than the one-step score
        self.trashed = 0
        self.history: List[dict] = []   # one entry per round
        self._round_conflict = (0, 0)
        self._round_place = 0           # 1/2/3 = reward rank earned this round, 0 = nothing
        self.seat = False
        self.revealed = False
        self.persuasion = 0
        self.swords = 0

    def all_cards(self) -> List[Card]:
        return self.deck + self.hand + self.discard + self.in_play + self.revealed_cards

    def troops_total(self) -> int:
        return self.garrison + self.conflict


NEAR_TIE = 0.5   # utility margin below which two options count as a near-tie (1 VP = 10)


class Game:
    def __init__(self, strategies: list, seed: Optional[int] = None,
                 names: Optional[List[str]] = None, record: bool = False, leaders=None):
        """leaders: None (no leaders, Signet Ring gives 1 solari), "random" (each player gets
        a different random leader), or a list of leader names, one per seat."""
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.strategies = strategies
        n = len(strategies)
        names = names or [f"P{i + 1}" for i in range(n)]
        self.players = [Player(i, names[i], getattr(s, "name", type(s).__name__))
                        for i, s in enumerate(strategies)]
        for p in self.players:
            self.rng.shuffle(p.deck)
        if leaders:
            if leaders == "random":
                # separate generator so the rest of the game's randomness is unaffected
                pick = random.Random(f"leaders|{self.seed}").sample(data.LEADERS, n)
            else:
                pick = [data.LEADER_BY_NAME[nm] for nm in leaders]
            for p, ld in zip(self.players, pick):
                p.leader = ld

        self.occupied: Dict[str, Optional[int]] = {s["name"]: None for s in SPACES}
        self.bonus_spice = {s["name"]: 0 for s in SPACES if s["maker"]}
        self.control: Dict[str, Optional[int]] = {s["name"]: None for s in SPACES if s["control"]}
        self.alliance: Dict[str, Optional[int]] = {f: None for f in FACTIONS}

        self.imperium_deck = _expand(data.IMPERIUM_DECK, lambda d: Card(d, "imperium"))
        self.rng.shuffle(self.imperium_deck)
        self.imperium_row: List[Card] = [self.imperium_deck.pop()
                                         for _ in range(data.IMPERIUM_ROW_SIZE)]
        self.reserve = {d["name"]: d.get("count", 1) for d in data.RESERVE}

        self.intrigue_deck = _expand(data.INTRIGUE, Intrigue)
        self.rng.shuffle(self.intrigue_deck)
        self.intrigue_discard: List[Intrigue] = []

        deck = []
        for level in (3, 2, 1):  # bottom to top; pop() draws from the end
            pool = [c for c in data.CONFLICTS if c["level"] == level]
            self.rng.shuffle(pool)
            deck.extend(pool[:data.CONFLICTS_PER_LEVEL[level]])
        self.conflict_deck = deck
        self.conflict_card: Optional[dict] = None

        self.round = 0
        self.first_player = 0
        self.active: Optional[int] = None
        self.phase = "setup"
        self.finished = False
        self.result: Optional[dict] = None

        # Set by an agent inside choose_turn so the engine can record why it chose:
        self.last_scores: Optional[dict] = None   # {action: utility}
        self.last_rule: Optional[str] = None      # e.g. "priority space: Swordmaster"
        self._pending_decision: Optional[dict] = None
        self.recording = record
        self.in_rollout = False   # True in a rollout's copies: no rollouts inside rollouts
        self.frames: Optional[list] = [] if record else None
        for p in self.players:
            if p.leader and p.leader.get("start"):
                self.apply_ops(p, p.leader["start"], {})
        self._record("Game start", None)

    # ------------------------------------------------------------------ utils
    @property
    def n(self) -> int:
        return len(self.players)

    def strat(self, p: Player):
        return self.strategies[p.idx]

    def clone(self, hide_for: Optional[int] = None, seed: Optional[int] = None) -> "Game":
        """Deep copy for lookahead. Hidden information (deck orders) is reshuffled.

        hide_for: the seat whose point of view the copy takes. Everything that seat
        cannot see is then re-dealt at random from what it could be (see `redeal_hidden`).
        Without it the copy keeps every hand as it is (the one-step lookahead).
        seed: the copy's random seed; by default it is drawn from this game's generator."""
        frames, self.frames = self.frames, None
        g = copy.deepcopy(self)
        self.frames = frames
        g.recording = False
        g.rng = random.Random(self.rng.getrandbits(32) if seed is None else seed)
        if hide_for is not None:
            g.redeal_hidden(hide_for)
            return g
        for p in g.players:
            if p.leader and p.leader.get("prescience") and p.deck:
                top = p.deck.pop()          # this leader knows their next card
                g.rng.shuffle(p.deck)
                p.deck.append(top)
            else:
                g.rng.shuffle(p.deck)
        g.rng.shuffle(g.imperium_deck)
        g.rng.shuffle(g.intrigue_deck)
        return g

    def redeal_hidden(self, viewer: int):
        """Replace what `viewer` cannot see with one random guess consistent with what it
        can. Every card a player owns is public (starting deck, purchases, discard pile,
        cards played this round), so for each opponent only the split between hand and
        draw deck is hidden: their hand and deck are pooled, shuffled and a hand of the
        same size dealt back. Intrigue cards are secret: each opponent's intrigue cards are
        pooled with the intrigue deck and the same number dealt back. The viewer's own
        hand and intrigue stay as they are; its deck order, the Imperium deck and the
        order of the remaining conflict cards within each level are reshuffled."""
        rng = self.rng
        intrigue_pool = list(self.intrigue_deck)
        dealt = {}
        for q in self.players:
            if q.idx == viewer:
                if q.leader and q.leader.get("prescience") and q.deck:
                    top = q.deck.pop()          # this leader knows their next card
                    rng.shuffle(q.deck)
                    q.deck.append(top)
                else:
                    rng.shuffle(q.deck)
                continue
            pool = q.hand + q.deck
            rng.shuffle(pool)
            k = len(q.hand)
            q.hand, q.deck = pool[:k], pool[k:]
            intrigue_pool += q.intrigue
            dealt[q.idx] = len(q.intrigue)
        rng.shuffle(intrigue_pool)
        for qi, k in dealt.items():
            self.players[qi].intrigue = [intrigue_pool.pop() for _ in range(k)]
        self.intrigue_deck = intrigue_pool
        rng.shuffle(self.imperium_deck)
        by_level: Dict[int, list] = {}
        for c in self.conflict_deck:
            by_level.setdefault(c["level"], []).append(c)
        for cards in by_level.values():
            rng.shuffle(cards)
        # the deck is bottom to top: level 3, then 2, then 1
        self.conflict_deck = [c for lv in sorted(by_level, reverse=True) for c in by_level[lv]]

    def total_vp(self, p: Player) -> int:
        return (p.vp + sum(1 for f in FACTIONS if p.influence[f] >= 2)
                + sum(1 for f in FACTIONS if self.alliance[f] == p.idx))

    def strength(self, p: Player) -> int:
        if p.conflict <= 0:
            return 0
        return 2 * p.conflict + p.swords

    def agents_left(self, p: Player) -> int:
        return p.agents_total + (1 if p.mentat else 0) - p.agents_used

    def can_pay(self, p: Player, cost: dict) -> bool:
        for k, v in cost.items():
            if k == "troops":
                if p.garrison < v:
                    return False
            elif getattr(p, k) < v:
                return False
        return True

    def pay(self, p: Player, cost: dict):
        for k, v in cost.items():
            if k == "troops":
                p.garrison -= v
            else:
                setattr(p, k, getattr(p, k) - v)

    def draw(self, p: Player, n: int):
        for _ in range(n):
            if not p.deck:
                if not p.discard:
                    return
                p.deck, p.discard = p.discard, []
                self.rng.shuffle(p.deck)
            p.hand.append(p.deck.pop())

    def draw_intrigue(self, p: Player, n: int = 1):
        for _ in range(n):
            if not self.intrigue_deck:
                if not self.intrigue_discard:
                    return
                self.intrigue_deck, self.intrigue_discard = self.intrigue_discard, []
                self.rng.shuffle(self.intrigue_deck)
            p.intrigue.append(self.intrigue_deck.pop())

    # ------------------------------------------------------------- influence
    def change_influence(self, p: Player, f: str, delta: int):
        before = p.influence[f]
        p.influence[f] = max(0, min(6, before + delta))
        if before < 4 <= p.influence[f] and f not in p.bonus_claimed:
            p.bonus_claimed.add(f)
            self.apply_ops(p, data.FACTION_BONUS_AT_4[f], {})
        holder = self.alliance[f]
        if holder is None:
            if p.influence[f] >= 4:
                self.alliance[f] = p.idx
        elif holder != p.idx:
            if p.influence[f] > self.players[holder].influence[f]:
                self.alliance[f] = p.idx
        else:
            best = max(self.players, key=lambda q: q.influence[f])
            if p.influence[f] < 4 or best.influence[f] > p.influence[f]:
                self.alliance[f] = best.idx if best.influence[f] >= 4 else None

    # ----------------------------------------------------- effect interpreter
    def apply_ops(self, p: Player, ops: list, ctx: dict):
        for op in ops:
            self.apply_op(p, op, ctx)

    def trailing_factions(self, p: Player) -> List[str]:
        """Factions where some other player has more influence than p."""
        return [f for f in FACTIONS
                if any(q.influence[f] > p.influence[f] for q in self.players if q is not p)]

    def ops_affordable(self, p: Player, ops: list) -> bool:
        cost: Dict[str, int] = {}
        for op in ops:
            if op.get("influence") == "trailing" and not self.trailing_factions(p):
                return False
            if "pay" in op:
                for k, v in op["pay"].items():
                    cost[k] = cost.get(k, 0) + v
        return self.can_pay(p, cost)

    def apply_op(self, p: Player, op: dict, ctx: dict):
        if "gain" in op:
            for k, v in op["gain"].items():
                self.gain(p, k, v, ctx)
        elif "pay" in op:
            self.pay(p, op["pay"])
        elif "influence" in op:
            n = op.get("n", 1)
            f = op["influence"]
            if f == "space":
                f = (ctx.get("space") or {}).get("faction")
                if f is None:
                    return
            if f == "trailing":
                options = self.trailing_factions(p)
                if not options:
                    return
                pick = self.strat(p).choose_influence(self, p, list(options))
                f = pick if pick in options else options[0]
            if f == "any":
                f = self.strat(p).choose_influence(self, p, list(FACTIONS))
            self.change_influence(p, f, n)
        elif "trash" in op:
            for _ in range(op["trash"]):
                pool = p.hand + p.discard + p.in_play
                if not pool:
                    return
                c = self.strat(p).choose_trash(self, p, pool)
                if c is None:
                    return
                for zone in (p.hand, p.discard, p.in_play):
                    if c in zone:
                        zone.remove(c)
                        break
                p.trashed += 1
                self._log(f"{p.name} trashes {c.name}", p.idx)
        elif "trash_self" in op:
            c = ctx.get("card")
            for zone in (p.in_play, p.revealed_cards, p.hand):
                if c in zone:
                    zone.remove(c)
                    break
        elif "acquire" in op:
            name = op["acquire"]
            if self.reserve.get(name, 0) > 0:
                self.reserve[name] -= 1
                p.discard.append(RESERVE_CARDS[name])
        elif "optional" in op:
            if self.ops_affordable(p, op["optional"]) and \
                    self.strat(p).choose_option(self, p, [[], op["optional"]]) == 1:
                self.apply_ops(p, op["optional"], ctx)
        elif "choice" in op:
            branches = [b for b in op["choice"] if self.ops_affordable(p, b)]
            if branches:
                i = self.strat(p).choose_option(self, p, branches)
                self.apply_ops(p, branches[i], ctx)
        elif "if_influence" in op:
            if all(p.influence[f] >= v for f, v in op["if_influence"].items()):
                self.apply_ops(p, op["then"], ctx)
        elif "if_bond" in op:
            f, me = op["if_bond"], ctx.get("card")
            played = p.in_play + p.revealed_cards
            if any(c.faction == f and c is not me for c in played):
                self.apply_ops(p, op["then"], ctx)
        elif "if_any_alliance" in op:
            if any(v == p.idx for v in self.alliance.values()):
                self.apply_ops(p, op["then"], ctx)
        elif "if_seat" in op:
            if p.seat:
                self.apply_ops(p, op["then"], ctx)
        elif "special" in op:
            self.special(p, op["special"], ctx)
        else:
            raise ValueError(f"Unknown op {op}")

    def gain(self, p: Player, k: str, v: int, ctx: dict):
        if k == "troops":
            v = min(v, data.TROOP_SUPPLY - p.troops_total())
            p.garrison += v
            p.earned["troops"] += v
            ctx["recruited"] = ctx.get("recruited", 0) + v
        elif k == "conflict_troops":
            v = min(v, data.TROOP_SUPPLY - p.troops_total())
            p.conflict += v
            p.earned["troops"] += v
        elif k == "draw":
            self.draw(p, v)
            p.earned["draw"] += v
        elif k == "intrigue":
            self.draw_intrigue(p, v)
        elif k in ("spice", "solari", "water", "vp", "persuasion", "swords"):
            setattr(p, k, getattr(p, k) + v)
            if k in p.earned:
                p.earned[k] += v
        else:
            raise ValueError(f"Unknown resource {k}")

    def special(self, p: Player, name: str, ctx: dict):
        if name == "mentat":
            self.draw(p, 1)
            p.earned["draw"] += 1
            p.mentat = True
            p.mentat_uses += 1
        elif name == "swordmaster":
            p.agents_total = 3
        elif name == "high_council":
            p.seat = True
            if p.leader and p.leader.get("on_high_council"):
                self.apply_ops(p, p.leader["on_high_council"], ctx)
        elif name == "manipulate":
            # take a card out of the Imperium row; the row refills. The card can be bought
            # only by this player, this round, for 1 persuasion less. A card that is not
            # bought (or is displaced by a second Manipulate) leaves the game.
            if self.imperium_row:
                c = self.strat(p).choose_reserve(self, p, list(self.imperium_row))
                if not any(c is x for x in self.imperium_row):
                    c = self.imperium_row[0]
                self.imperium_row.remove(c)
                if self.imperium_deck:
                    self.imperium_row.append(self.imperium_deck.pop())
                p.held = c
                ctx["reserved"] = c.name
        elif name == "secrets":
            self.draw_intrigue(p, 1)
            for q in self.players:
                if q is not p and len(q.intrigue) >= 4:
                    stolen = q.intrigue.pop(self.rng.randrange(len(q.intrigue)))
                    p.intrigue.append(stolen)
        elif name == "plans_within_plans":
            k = sum(1 for f in FACTIONS if p.influence[f] >= 3)
            p.vp += 2 if k >= 4 else (1 if k >= 3 else 0)
        elif name == "corner_the_market":
            k = sum(1 for c in p.all_cards() if c.name == "The Spice Must Flow")
            p.vp += 1 if k >= 2 else 0
        else:
            raise ValueError(f"Unknown special {name}")

    # ------------------------------------------------------------ legality
    def space_cost(self, p: Player, s: dict) -> dict:
        d = p.leader.get("space_discount") if p.leader else None
        if d and s["icon"] == d["icon"] and s["cost"].get("solari"):
            cost = dict(s["cost"])
            cost["solari"] = max(0, cost["solari"] - d["solari"])
            return cost
        return s["cost"]

    def space_ok(self, p: Player, s: dict) -> bool:
        occ = self.occupied[s["name"]]
        if occ is not None:
            shared = p.leader.get("ignore_occupied", ()) if p.leader else ()
            if occ == p.idx or s["icon"] not in shared or s["name"] in p.visited:
                return False
        for f, v in s["requires"].items():
            if p.influence[f] < v:
                return False
        if not self.can_pay(p, self.space_cost(p, s)):
            return False
        if s["name"] == "High Council" and p.seat:
            return False
        if s["name"] == "Swordmaster" and p.agents_total >= 3:
            return False
        return True

    def legal_actions(self, p: Player) -> list:
        """('agent', hand_index, space_name) or ('reveal',)."""
        if p.revealed:
            return []
        acts = []
        if self.agents_left(p) > 0:
            seen = set()
            for hi, c in enumerate(p.hand):
                for s in SPACES:
                    if s["icon"] in c.icons and (c.name, s["name"]) not in seen \
                            and self.space_ok(p, s):
                        seen.add((c.name, s["name"]))
                        acts.append(("agent", hi, s["name"]))
        acts.append(("reveal",))
        return acts

    # --------------------------------------------------------------- turns
    def do_action(self, pi: int, action: tuple):
        if action[0] == "agent":
            self.agent_turn(pi, action[1], action[2])
        else:
            self.reveal_turn(pi)

    def agent_turn(self, pi: int, hand_index: int, space_name: str):
        p = self.players[pi]
        s = SPACE_BY_NAME[space_name]
        card = p.hand.pop(hand_index)
        p.in_play.append(card)
        p.agents_used += 1
        if self.occupied[space_name] is None:   # a leader sharing a space does not displace
            self.occupied[space_name] = pi
        p.visited.add(space_name)
        cost = self.space_cost(p, s)
        self.pay(p, cost)
        ctx = {"space": s, "card": card, "recruited": 0}
        ld = p.leader or {}
        if cost.get("solari") and ld.get("on_pay_solari"):
            self.apply_ops(p, ld["on_pay_solari"], ctx)
        if s["faction"]:
            self.change_influence(p, s["faction"], 1)
        if s["control"] and self.control.get(space_name) is not None:
            owner = self.players[self.control[space_name]]
            self.apply_ops(owner, [{"gain": s["control"]}], {})
        if s["maker"] and self.bonus_spice[space_name]:
            p.spice += self.bonus_spice[space_name]
            p.earned["spice"] += self.bonus_spice[space_name]
            self.bonus_spice[space_name] = 0
        self.apply_ops(p, s["effects"], ctx)
        if s["maker"] and ld.get("maker_tax"):
            tax = min(p.spice, ld["maker_tax"]["spice"])
            p.spice -= tax
            p.earned["spice"] -= tax
            self.gain(p, "draw", ld["maker_tax"]["draw"], ctx)
        # with leaders in play, the Signet Ring triggers the leader's signet ability
        signet = card.name == "Signet Ring" and p.leader is not None
        self.apply_ops(p, p.leader["signet"] if signet else card.agent, ctx)
        deployed = 0
        if s["combat"]:
            max_n = min(p.garrison, 2 + ctx["recruited"])
            if max_n > 0:
                deployed = max(0, min(max_n, int(self.strat(p).choose_deploy(self, p, max_n))))
                p.garrison -= deployed
                p.conflict += deployed
        ms = ld.get("masterstroke")
        masterstroke = bool(ms) and not p.masterstroke_used and deployed >= ms["deploy"]
        if masterstroke:
            p.masterstroke_used = True
            left = list(FACTIONS)
            for _ in range(ms["factions"]):
                f = self.strat(p).choose_influence(self, p, list(left))
                f = f if f in left else left[0]
                left.remove(f)
                self.change_influence(p, f, 1)
        msg = f"{p.name} plays {card.name} -> {space_name}"
        if ctx.get("reserved"):
            msg += f", reserves {ctx['reserved']} from the Imperium row"
        if deployed:
            msg += f", deploys {deployed}"
        if masterstroke:
            msg += ", plays Masterstroke"
        self._record(msg, pi)

    def reveal_turn(self, pi: int):
        p = self.players[pi]
        p.revealed = True
        cards, p.hand = p.hand, []
        p.revealed_cards = cards
        for c in cards:
            self.apply_ops(p, c.reveal, {"card": c})
        budget = p.persuasion + (2 if p.seat else 0)
        bought = []
        while True:
            options = [c for c in self.imperium_row if c.cost <= budget]
            if p.held is not None and held_price(p.held) <= budget and p.held not in options:
                options.append(p.held)
            options += [RESERVE_CARDS[n] for n in data.BUYABLE_RESERVE
                        if self.reserve[n] > 0 and RESERVE_CARDS[n].cost <= budget]
            if not options:
                break
            c = self.strat(p).choose_purchase(self, p, options, budget)
            if c is None:
                break
            if c is p.held:               # the reserved copy is always the cheaper one
                budget -= held_price(c)
                p.held = None
            elif c in self.imperium_row:
                budget -= c.cost
                self.imperium_row.remove(c)
                if self.imperium_deck:
                    self.imperium_row.append(self.imperium_deck.pop())
            else:
                budget -= c.cost
                self.reserve[c.name] -= 1
            p.discard.append(c)
            self.apply_ops(p, c.acquire, {"card": c})
            bought.append(c.name)
        p.persuasion = 0
        msg = f"{p.name} reveals {', '.join(c.name for c in cards) or 'nothing'}"
        msg += f" (swords {p.swords})"
        if bought:
            msg += f"; buys {', '.join(bought)}"
        self._record(msg, pi)

    def play_plots(self, pi: int):
        p = self.players[pi]
        while True:
            plots = [c for c in p.intrigue if c.kind == "plot"]
            if not plots:
                return
            c = self.strat(p).choose_plot_intrigue(self, p, plots)
            if c is None:
                return
            p.intrigue.remove(c)
            self.intrigue_discard.append(c)
            self.apply_ops(p, c.effects, {})
            self._record(f"{p.name} plays intrigue {c.name}", pi)

    # -------------------------------------------------------------- rounds
    def play(self) -> dict:
        while not self.finished:
            self.play_round()
        return self.result

    def play_round(self):
        self.round += 1
        self.phase = "round start"
        self.conflict_card = self.conflict_deck.pop()
        for p in self.players:
            self.draw(p, data.HAND_SIZE)
        self._record(f"Round {self.round}: conflict {self.conflict_card['name']}", None)
        self.player_turns(self.first_player)
        self.finish_round()

    def player_turns(self, start: int):
        """Players take turns in seat order from `start` until everyone has revealed.
        A rollout calls this mid-round with the seat after the player who just acted."""
        self.phase = "player turns"
        pi, steps = start % self.n, 0
        while not all(p.revealed for p in self.players):
            p = self.players[pi]
            if not p.revealed:
                self.active = pi
                self.play_plots(pi)
                acts = self.legal_actions(p)
                if len(acts) == 1:
                    action = acts[0]
                else:
                    action = self.decide_turn(p, acts)
                self.do_action(pi, action)
            pi = (pi + 1) % self.n
            steps += 1
            if steps > 20 * self.n:
                raise RuntimeError("turn loop did not terminate")
        self.active = None

    def finish_round(self):
        """Combat, makers, recall and the end-of-game check."""
        order = [(self.first_player + i) % self.n for i in range(self.n)]
        self.combat_phase(order)

        # Makers
        for name in self.bonus_spice:
            if self.occupied[name] is None:
                self.bonus_spice[name] += 1

        # Recall
        for p in self.players:
            p.discard.extend(p.hand + p.in_play + p.revealed_cards)
            p.hand, p.in_play, p.revealed_cards = [], [], []
            p.agents_used = 0
            p.visited = set()
            p.held = None            # an unbought reserved card leaves the game
            p.mentat = False
            p.revealed = False
            p.persuasion = 0
            p.swords = 0
        for k in self.occupied:
            self.occupied[k] = None
        self.first_player = (self.first_player + 1) % self.n
        self.phase = "recall"
        for p in self.players:
            p.history.append({
                "vp": self.total_vp(p), "spice": p.spice, "solari": p.solari,
                "water": p.water, "garrison": p.garrison, "cards": len(p.all_cards()),
                "conflict_troops": p._round_conflict[0], "strength": p._round_conflict[1], "place": p._round_place,
                "intrigue": len(p.intrigue),
            })

        if not self.conflict_deck or any(self.total_vp(p) >= data.VP_TO_END for p in self.players):
            self.end_game()
        else:
            self._record(f"End of round {self.round}", None)

    def action_label(self, p: Player, action) -> str:
        if isinstance(action, tuple) and len(action) == 3 and action[0] == "agent":
            return f"{p.hand[action[1]].name} -> {action[2]}"
        return "Reveal hand"

    def decide_turn(self, p: Player, acts: list) -> tuple:
        """Ask the agent for its turn. An illegal action or an exception from the agent is an
        expected failure: it is replaced by a reveal turn (always legal), counted and logged,
        so one faulty agent cannot corrupt or stall the game."""
        self.last_scores, self.last_rule = None, None
        fallback = None
        t0 = time.perf_counter()
        try:
            action = self.strat(p).choose_turn(self, p, acts)
        except Exception as e:  # noqa: BLE001 - any agent failure is handled the same way
            action, fallback = None, f"agent error {type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        if fallback is None and action not in acts:
            fallback = f"illegal action {action!r}"
        if fallback:
            p.fallbacks += 1
            action = ("reveal",)
        p.decisions += 1
        p.decision_time += dt
        p.options_total += len(acts)
        scores = self.last_scores or {}
        if len(scores) >= 2:
            top = sorted(scores.values(), reverse=True)
            p.scored += 1
            p.near_ties += (top[0] - top[1]) < NEAR_TIE
        if self.recording:
            opts = [{"label": self.action_label(p, a),
                     "score": None if a not in scores else round(scores[a], 2),
                     "chosen": a == action} for a in acts]
            opts.sort(key=lambda o: (o["score"] is None, -(o["score"] or 0)))
            self._pending_decision = {
                "actor": p.idx, "options": opts, "n_options": len(acts),
                "ms": round(dt * 1000, 2), "rule": self.last_rule, "fallback": fallback,
            }
        return action

    def combat_phase(self, order: List[int]):
        self.phase = "combat"
        passes = 0
        i = 0
        while passes < self.n:
            p = self.players[order[i % self.n]]
            i += 1
            cards = [c for c in p.intrigue if c.kind == "combat"] if p.conflict > 0 else []
            c = self.strat(p).choose_combat_intrigue(self, p, cards) if cards else None
            if c is None:
                passes += 1
                continue
            passes = 0
            p.intrigue.remove(c)
            self.intrigue_discard.append(c)
            self.apply_ops(p, c.effects, {})
            self._record(f"{p.name} plays combat intrigue {c.name}", p.idx)

        for p in self.players:
            p._round_conflict = (p.conflict, self.strength(p))
            p._round_place = 0
        card = self.conflict_card
        ranks = 3 if self.n >= 4 else 2
        rewards = card["rewards"][:ranks]
        contenders = sorted([p for p in self.players if self.strength(p) > 0],
                            key=lambda q: -self.strength(q))
        pos = 0
        results = []
        j = 0
        while j < len(contenders) and pos < ranks:
            st = self.strength(contenders[j])
            group = [q for q in contenders[j:] if self.strength(q) == st]
            j += len(group)
            if len(group) == 1:
                q = group[0]
                self.apply_ops(q, rewards[pos], {})
                q._round_place = pos + 1
                if pos == 0:
                    q.conflict_wins += 1
                if pos == 0 and card.get("control"):
                    self.control[card["control"]] = q.idx
                results.append(f"{q.name} #{pos + 1} ({st})")
            else:
                # tie: everyone tied gets the next rank's reward
                if pos + 1 < ranks:
                    for q in group:
                        self.apply_ops(q, rewards[pos + 1], {})
                        q._round_place = pos + 2
                results.append("tie " + "/".join(q.name for q in group) + f" ({st})")
            pos += len(group)
        self._record(f"Combat {card['name']}: " + (", ".join(results) or "no contenders"), None)
        for p in self.players:
            p.conflict = 0

    def end_game(self):
        self.phase = "endgame"
        for p in self.players:
            for c in [c for c in p.intrigue if c.kind == "endgame"]:
                p.intrigue.remove(c)
                self.apply_ops(p, c.effects, {})
        key = lambda q: (self.total_vp(q), q.spice, q.solari, q.water, q.garrison)  # noqa: E731
        standings = sorted(self.players, key=key, reverse=True)
        top = key(standings[0])
        winners = [q.idx for q in standings if key(q) == top]
        self.finished = True
        self.result = {
            "seed": self.seed,
            "rounds": self.round,
            "end_reason": ("10 VP reached" if any(self.total_vp(q) >= data.VP_TO_END for q in self.players)
                           else "conflict deck exhausted"),
            "winners": winners,
            "players": [{
                "name": q.name, "strategy": q.strategy_name, "vp": self.total_vp(q),
                "leader": q.leader["name"] if q.leader else None,
                "rank": standings.index(q) + 1, "spice": q.spice, "solari": q.solari,
                "water": q.water, "deck_size": len(q.all_cards()),
                "decisions": q.decisions, "decision_ms": 1000 * q.decision_time,
                "options_total": q.options_total, "scored": q.scored,
                "near_ties": q.near_ties, "fallbacks": q.fallbacks,
                "rollout_decisions": q.rollout_decisions, "rollout_changed": q.rollout_changed,
                "earned": dict(q.earned), "conflict_wins": q.conflict_wins, "trashed": q.trashed,
                "smf": sum(1 for c in q.all_cards() if c.name == "The Spice Must Flow"),
                "history": q.history, "intrigue": len(q.intrigue),
                "card_types": _count_types(q), "agents": q.agents_total, "seat": q.seat, "mentat_uses": q.mentat_uses,
                "influence": dict(q.influence),
                "alliances": [f for f in FACTIONS if self.alliance[f] == q.idx],
            } for q in self.players],
        }
        self._record("Game over: " + ", ".join(
            f"{q.name} {self.total_vp(q)}VP" for q in standings), None)

    # ------------------------------------------------------------ recording
    def _log(self, msg: str, actor: Optional[int]):
        if self.recording and self.frames is not None and self.frames:
            self.frames[-1].setdefault("notes", []).append(msg)

    def _record(self, msg: str, actor: Optional[int]):
        if not self.recording:
            return
        frame = {"msg": msg, "actor": actor, "state": self.snapshot()}
        d = self._pending_decision
        if d is not None and d["actor"] == actor:
            frame["decision"] = d
            self._pending_decision = None
            if d["fallback"]:
                frame["notes"] = [f"FALLBACK: {d['fallback']} -> replaced by a reveal turn"]
        self.frames.append(frame)

    def snapshot(self) -> Dict[str, Any]:
        cc = self.conflict_card
        return {
            "round": self.round,
            "phase": self.phase,
            "first": self.first_player,
            "conflict": None if cc is None else {
                "name": cc["name"], "level": cc["level"], "control": cc.get("control"),
                "rewards": [fmt_ops(r) for r in cc["rewards"][:3 if self.n >= 4 else 2]],
            },
            "conflicts_left": len(self.conflict_deck),
            "board": {s["name"]: {"agent": self.occupied[s["name"]],
                                  "bonus": self.bonus_spice.get(s["name"], 0),
                                  "control": self.control.get(s["name"])}
                      for s in SPACES},
            "row": [{"name": c.name, "cost": c.cost, "type": c.faction}
                    for c in self.imperium_row],
            "reserve": dict(self.reserve),
            "alliance": dict(self.alliance),
            "players": [{
                "name": p.name, "strategy": p.strategy_name, "vp": self.total_vp(p),
                "leader": None if not p.leader else {
                    "name": p.leader["name"], "ability": p.leader["ability"],
                    "signet": p.leader["signet_text"]},
                "spice": p.spice, "solari": p.solari, "water": p.water,
                "garrison": p.garrison, "conflict": p.conflict,
                "strength": self.strength(p), "swords": p.swords,
                "persuasion": p.persuasion, "influence": dict(p.influence),
                "seat": p.seat, "agents_total": p.agents_total + (1 if p.mentat else 0),
                "agents_used": p.agents_used, "revealed": p.revealed,
                "hand": [c.name for c in p.hand],
                "in_play": [c.name for c in p.in_play],
                "revealed_cards": [c.name for c in p.revealed_cards],
                "intrigue": [c.name for c in p.intrigue],
                "held": None if p.held is None else {"name": p.held.name, "cost": held_price(p.held)},
                "deck": len(p.deck), "discard": len(p.discard),
                "deck_total": len(p.all_cards()),
            } for p in self.players],
        }


def held_price(c: Card) -> int:
    """Persuasion price of a card its owner reserved with Manipulate."""
    return max(0, c.cost - 1)


def _count_types(p: Player) -> Dict[str, int]:
    """Bought cards per type (faction, or 'none')."""
    out: Dict[str, int] = {}
    for c in p.all_cards():
        if c.kind != "starter":
            k = c.faction or "none"
            out[k] = out.get(k, 0) + 1
    return out


def fmt_ops(ops: list) -> str:
    parts = []
    for op in ops:
        if "gain" in op:
            parts += [f"+{v} {k.replace('_', ' ')}" for k, v in op["gain"].items()]
        elif "pay" in op:
            parts += [f"-{v} {k}" for k, v in op["pay"].items()]
        elif "influence" in op:
            parts.append(f"+{op.get('n', 1)} influence ({op['influence']})")
        elif "optional" in op:
            parts.append("may: " + fmt_ops(op["optional"]))
        elif "choice" in op:
            parts.append(" OR ".join(fmt_ops(b) for b in op["choice"]))
        elif "trash" in op:
            parts.append(f"trash {op['trash']}")
        elif "acquire" in op:
            parts.append(f"gain {op['acquire']}")
        elif "special" in op:
            parts.append(op["special"].replace("_", " "))
        else:
            parts.append(str(op))
    return ", ".join(parts)
