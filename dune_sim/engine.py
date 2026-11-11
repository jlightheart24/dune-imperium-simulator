"""Rules engine: game state, round structure, effect interpreter, replay recording."""
from __future__ import annotations

import copy
import random
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
        # statistics (do not affect play)
        self.earned = {"spice": 0, "solari": 0, "water": 0, "troops": 0}
        self.conflict_wins = 0
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


class GameOver(Exception):
    pass


class Game:
    def __init__(self, strategies: list, seed: Optional[int] = None,
                 names: Optional[List[str]] = None, record: bool = False):
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.strategies = strategies
        n = len(strategies)
        names = names or [f"P{i + 1}" for i in range(n)]
        self.players = [Player(i, names[i], getattr(s, "name", type(s).__name__))
                        for i, s in enumerate(strategies)]
        for p in self.players:
            self.rng.shuffle(p.deck)

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

        self.recording = record
        self.frames: Optional[list] = [] if record else None
        self._record("Game start", None)

    # ------------------------------------------------------------------ utils
    @property
    def n(self) -> int:
        return len(self.players)

    def strat(self, p: Player):
        return self.strategies[p.idx]

    def clone(self, hide_for: Optional[int] = None) -> "Game":
        """Deep copy for lookahead. Hidden information (deck orders) is reshuffled."""
        frames, self.frames = self.frames, None
        g = copy.deepcopy(self)
        self.frames = frames
        g.recording = False
        g.rng = random.Random(self.rng.getrandbits(32))
        for p in g.players:
            g.rng.shuffle(p.deck)
        g.rng.shuffle(g.imperium_deck)
        g.rng.shuffle(g.intrigue_deck)
        return g

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

    def ops_affordable(self, p: Player, ops: list) -> bool:
        cost: Dict[str, int] = {}
        for op in ops:
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
            p.mentat = True
            p.mentat_uses += 1
        elif name == "swordmaster":
            p.agents_total = 3
        elif name == "high_council":
            p.seat = True
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
    def space_ok(self, p: Player, s: dict) -> bool:
        if self.occupied[s["name"]] is not None:
            return False
        for f, v in s["requires"].items():
            if p.influence[f] < v:
                return False
        if not self.can_pay(p, s["cost"]):
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
        self.occupied[space_name] = pi
        self.pay(p, s["cost"])
        ctx = {"space": s, "card": card, "recruited": 0}
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
        self.apply_ops(p, card.agent, ctx)
        deployed = 0
        if s["combat"]:
            max_n = min(p.garrison, 2 + ctx["recruited"])
            if max_n > 0:
                deployed = max(0, min(max_n, int(self.strat(p).choose_deploy(self, p, max_n))))
                p.garrison -= deployed
                p.conflict += deployed
        msg = f"{p.name} plays {card.name} -> {space_name}"
        if deployed:
            msg += f", deploys {deployed}"
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
            options += [RESERVE_CARDS[n] for n in data.BUYABLE_RESERVE
                        if self.reserve[n] > 0 and RESERVE_CARDS[n].cost <= budget]
            if not options:
                break
            c = self.strat(p).choose_purchase(self, p, options, budget)
            if c is None:
                break
            budget -= c.cost
            if c in self.imperium_row:
                self.imperium_row.remove(c)
                if self.imperium_deck:
                    self.imperium_row.append(self.imperium_deck.pop())
            else:
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

        # Player turns
        self.phase = "player turns"
        order = [(self.first_player + i) % self.n for i in range(self.n)]
        guard = 0
        while not all(p.revealed for p in self.players):
            for pi in order:
                p = self.players[pi]
                if p.revealed:
                    continue
                self.active = pi
                self.play_plots(pi)
                acts = self.legal_actions(p)
                if len(acts) == 1:
                    action = acts[0]
                else:
                    action = self.strat(p).choose_turn(self, p, acts)
                    if action not in acts:
                        action = ("reveal",)
                self.do_action(pi, action)
            guard += 1
            if guard > 20:
                raise RuntimeError("turn loop did not terminate")
        self.active = None

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
            "winners": winners,
            "players": [{
                "name": q.name, "strategy": q.strategy_name, "vp": self.total_vp(q),
                "rank": standings.index(q) + 1, "spice": q.spice, "solari": q.solari,
                "water": q.water, "deck_size": len(q.all_cards()),
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
        self.frames.append({"msg": msg, "actor": actor, "state": self.snapshot()})

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
                "deck": len(p.deck), "discard": len(p.discard),
                "deck_total": len(p.all_cards()),
            } for p in self.players],
        }


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
