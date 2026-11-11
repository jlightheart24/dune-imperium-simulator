"""Game content: board spaces, cards, conflicts and intrigue.

Everything here is plain data, so it can be tuned without touching the engine.

NOTE: the board and starter deck follow the base game closely. Imperium-deck
cards, conflict rewards and intrigue cards are *approximations* of the real
cards (names kept, effects simplified). Edit them to match your copy of the
game exactly -- the engine only cares about the effect DSL described below.

Effect DSL -- an effect list is a list of ops, each op is a small dict:
    {"gain": {"spice": 2, "solari": 1, "water": 1, "troops": 2, "vp": 1,
              "intrigue": 1, "draw": 1, "persuasion": 2, "swords": 3,
              "conflict_troops": 2}}          # conflict_troops: straight into the conflict
    {"pay": {"spice": 3}}                     # only valid inside optional/choice
    {"influence": "fremen" | "any" | "space", "n": 1}
    {"trash": 1}                              # may trash a card (hand/discard/in play)
    {"trash_self": True}
    {"acquire": "Foldspace"}                  # card from the reserve to your discard
    {"optional": [ops]}                       # "you may ..." (usually pay -> gain)
    {"choice": [[ops], [ops], ...]}           # pick one affordable branch
    {"if_influence": {"fremen": 2}, "then": [ops]}
    {"if_bond": "fremen", "then": [ops]}      # another card of that faction played this round
    {"if_seat": True, "then": [ops]}
    {"special": "mentat" | "swordmaster" | "high_council" | "secrets"}
"""

FACTIONS = ["emperor", "guild", "bene_gesserit", "fremen"]
ALL_ICONS = FACTIONS + ["landsraad", "city", "spice_trade"]

FACTION_LABEL = {
    "emperor": "Emperor",
    "guild": "Spacing Guild",
    "bene_gesserit": "Bene Gesserit",
    "fremen": "Fremen",
}

# One-time bonus when a player first reaches 4 influence with a faction.
FACTION_BONUS_AT_4 = {
    "emperor": [{"gain": {"troops": 2}}],
    "guild": [{"gain": {"solari": 3}}],
    "bene_gesserit": [{"gain": {"intrigue": 1}}],
    "fremen": [{"gain": {"water": 1}}],
}

STARTING_RESOURCES = {"spice": 0, "solari": 0, "water": 1, "garrison": 3, "vp": 0}
TROOP_SUPPLY = 12
VP_TO_END = 10
HAND_SIZE = 5


def _space(name, icon, area, effects, cost=None, faction=None, combat=False,
           maker=False, requires=None, control=None):
    return {
        "name": name, "icon": icon, "area": area, "effects": effects,
        "cost": cost or {}, "faction": faction, "combat": combat,
        "maker": maker, "requires": requires or {}, "control": control,
    }


SPACES = [
    # Emperor
    _space("Conspire", "emperor", "Emperor",
           [{"gain": {"solari": 5, "troops": 2, "intrigue": 1}}],
           cost={"spice": 4}, faction="emperor"),
    _space("Wealth", "emperor", "Emperor", [{"gain": {"solari": 2}}], faction="emperor"),
    # Spacing Guild
    _space("Heighliner", "guild", "Spacing Guild",
           [{"gain": {"troops": 5, "water": 2}}], cost={"spice": 6},
           faction="guild", combat=True),
    _space("Foldspace", "guild", "Spacing Guild", [{"acquire": "Foldspace"}], faction="guild"),
    # Bene Gesserit
    _space("Selective Breeding", "bene_gesserit", "Bene Gesserit",
           [{"trash": 1}, {"gain": {"draw": 2}}], cost={"spice": 2},
           faction="bene_gesserit"),
    _space("Secrets", "bene_gesserit", "Bene Gesserit",
           [{"special": "secrets"}], faction="bene_gesserit"),
    # Fremen
    _space("Hardy Warriors", "fremen", "Fremen", [{"gain": {"troops": 2}}],
           cost={"water": 1}, faction="fremen", combat=True),
    _space("Stillsuits", "fremen", "Fremen", [{"gain": {"water": 1}}],
           faction="fremen", combat=True),
    # Landsraad
    _space("High Council", "landsraad", "Landsraad", [{"special": "high_council"}],
           cost={"solari": 5}),
    _space("Mentat", "landsraad", "Landsraad", [{"special": "mentat"}],
           cost={"solari": 2}),
    _space("Swordmaster", "landsraad", "Landsraad", [{"special": "swordmaster"}],
           cost={"solari": 8}),
    _space("Rally Troops", "landsraad", "Landsraad", [{"gain": {"troops": 4}}],
           cost={"solari": 4}),
    _space("Hall of Oratory", "landsraad", "Landsraad",
           [{"gain": {"troops": 1, "persuasion": 1}}]),
    # CHOAM
    _space("Secure Contract", "spice_trade", "CHOAM", [{"gain": {"solari": 3}}]),
    _space("Sell Melange", "spice_trade", "CHOAM", [{"choice": [
        [{"pay": {"spice": 2}}, {"gain": {"solari": 6}}],
        [{"pay": {"spice": 3}}, {"gain": {"solari": 8}}],
        [{"pay": {"spice": 4}}, {"gain": {"solari": 10}}],
        [{"pay": {"spice": 5}}, {"gain": {"solari": 12}}],
    ]}]),
    # Cities
    _space("Arrakeen", "city", "Arrakis",
           [{"gain": {"troops": 1, "draw": 1}}], combat=True,
           control={"solari": 1}),
    _space("Carthag", "city", "Arrakis",
           [{"gain": {"troops": 1, "intrigue": 1}}], combat=True,
           control={"solari": 1}),
    _space("Research Station", "city", "Arrakis", [{"gain": {"draw": 3}}],
           cost={"water": 2}, combat=True),
    _space("Sietch Tabr", "city", "Arrakis",
           [{"gain": {"troops": 1, "water": 1}}], combat=True,
           requires={"fremen": 2}),
    # Desert (maker spaces accumulate bonus spice)
    _space("Imperial Basin", "spice_trade", "Desert", [{"gain": {"spice": 1}}],
           combat=True, maker=True, control={"spice": 1}),
    _space("Hagga Basin", "spice_trade", "Desert", [{"gain": {"spice": 2}}],
           cost={"water": 1}, combat=True, maker=True),
    _space("The Great Flat", "spice_trade", "Desert", [{"gain": {"spice": 3}}],
           cost={"water": 2}, combat=True, maker=True),
]
SPACE_BY_NAME = {s["name"]: s for s in SPACES}


def _card(name, cost=0, icons=(), agent=(), reveal=(), acquire=(),
          faction=None, count=1):
    return {"name": name, "cost": cost, "icons": list(icons), "agent": list(agent),
            "reveal": list(reveal), "acquire": list(acquire), "faction": faction,
            "count": count}


P = lambda n: {"gain": {"persuasion": n}}  # noqa: E731
S = lambda n: {"gain": {"swords": n}}      # noqa: E731
FAC = FACTIONS

STARTER_DECK = [
    _card("Convincing Argument", icons=[], reveal=[P(2)], count=2),
    _card("Dagger", icons=["landsraad"], reveal=[S(1)], count=2),
    _card("Diplomacy", icons=FAC, reveal=[P(1)]),
    _card("Dune, The Desert Planet", icons=["spice_trade"], reveal=[P(1)], count=2),
    _card("Reconnaissance", icons=["city"], reveal=[P(1)]),
    _card("Seek Allies", icons=FAC, agent=[{"trash_self": True}]),
    _card("Signet Ring", icons=["landsraad", "city", "spice_trade"],
          agent=[{"gain": {"solari": 1}}], reveal=[P(1)]),  # leader ability placeholder
]

# Always-available reserve piles. Foldspace is only gained via the Foldspace space.
RESERVE = [
    _card("Arrakis Liaison", cost=2, icons=["fremen", "city"], reveal=[P(2)],
          faction="fremen", count=8),
    _card("The Spice Must Flow", cost=9, acquire=[{"gain": {"vp": 1}}],
          reveal=[{"gain": {"spice": 1}}], count=10),
    _card("Foldspace", cost=0, icons=FAC, agent=[{"gain": {"draw": 1}}], count=6),
]
BUYABLE_RESERVE = ["Arrakis Liaison", "The Spice Must Flow"]

IMPERIUM_DECK = [
    _card("Arrakis Recruiter", 2, ["city"], agent=[{"gain": {"troops": 1}}],
          reveal=[P(1), S(1)], count=2),
    _card("Assassination Mission", 1, [], reveal=[S(1), {"gain": {"solari": 1}}], count=2),
    _card("Bene Gesserit Sister", 3, ["bene_gesserit", "landsraad"],
          reveal=[{"choice": [[P(2)], [S(2)]]}], faction="bene_gesserit", count=2),
    _card("Carryall", 5, ["spice_trade"], agent=[{"gain": {"spice": 1}}],
          reveal=[P(1), {"gain": {"spice": 1}}]),
    _card("Chani", 5, ["fremen", "city"], agent=[{"gain": {"water": 1}}],
          reveal=[P(2), S(2)], faction="fremen"),
    _card("Crysknife", 3, ["fremen", "spice_trade"],
          reveal=[S(1), {"if_bond": "fremen", "then": [{"influence": "fremen"}]}],
          faction="fremen"),
    _card("Duncan Idaho", 4, ["city"], agent=[{"gain": {"water": 1}}],
          reveal=[P(1), S(2)]),
    _card("Fedaykin Death Commando", 3, ["fremen", "spice_trade"],
          reveal=[P(1), {"if_bond": "fremen", "then": [S(3)]}], faction="fremen"),
    _card("Fremen Camp", 4, ["spice_trade"], reveal=[P(2), S(1)], faction="fremen", count=2),
    _card("Gun Thopter", 4, ["city", "spice_trade"],
          agent=[{"gain": {"conflict_troops": 1}}], reveal=[S(3)], count=2),
    _card("Gurney Halleck", 6, ["city"],
          reveal=[P(2), {"optional": [{"pay": {"solari": 3}}, {"gain": {"conflict_troops": 2}}]}]),
    _card("Imperial Spy", 2, ["emperor"], agent=[{"gain": {"intrigue": 1}}],
          reveal=[P(1), S(1)], faction="emperor", count=2),
    _card("Kwisatz Haderach", 8, ALL_ICONS, agent=[{"gain": {"draw": 1}}]),
    _card("Lady Jessica", 7, ["bene_gesserit", "landsraad", "city", "spice_trade"],
          agent=[{"influence": "any"}], reveal=[P(3), S(1)], faction="bene_gesserit"),
    _card("Liet Kynes", 5, ["emperor", "fremen"], agent=[{"influence": "fremen"}],
          reveal=[P(2)], faction="fremen"),
    _card("Missionaria Protectiva", 1, ["city"], reveal=[P(1)],
          faction="bene_gesserit", count=2),
    _card("Piter de Vries", 5, ["landsraad", "city"], agent=[{"gain": {"intrigue": 1}}],
          reveal=[P(3), S(1)]),
    _card("Power Play", 5, FAC, agent=[{"influence": "space"}]),
    _card("Reverend Mother Mohiam", 6, ["emperor", "bene_gesserit"],
          reveal=[P(2), {"gain": {"spice": 2}}], faction="bene_gesserit"),
    _card("Sardaukar Infantry", 1, [], reveal=[P(1), S(2)], faction="emperor", count=2),
    _card("Sardaukar Legion", 5, ["emperor", "landsraad"], agent=[{"gain": {"troops": 3}}],
          reveal=[P(1), S(2)], faction="emperor"),
    _card("Smuggler's Thopter", 4, ["spice_trade"], agent=[{"gain": {"spice": 1}}],
          reveal=[P(1), {"gain": {"spice": 1}}], faction="guild"),
    _card("Space Travel", 3, ["guild"], agent=[{"gain": {"draw": 1}}], reveal=[P(2)],
          faction="guild", count=2),
    _card("Spice Hunt", 3, ["fremen", "spice_trade"],
          agent=[{"influence": "fremen"}], reveal=[P(1), S(1)], faction="fremen"),
    _card("Stilgar", 5, ["fremen", "city", "spice_trade"], reveal=[P(2), S(3)],
          faction="fremen"),
    _card("Thufir Hawat", 5, ["emperor", "bene_gesserit", "landsraad", "city"],
          agent=[{"gain": {"intrigue": 1}}], reveal=[P(1)]),
    _card("Test of Humanity", 3, ["bene_gesserit", "landsraad"], reveal=[P(2)],
          faction="bene_gesserit"),
    _card("Opulence", 6, ["emperor"],
          reveal=[P(1), {"optional": [{"pay": {"solari": 6}}, {"gain": {"vp": 1}}]}],
          faction="emperor"),
    _card("Other Memory", 4, ["bene_gesserit"], agent=[{"gain": {"draw": 1}}],
          reveal=[P(2)], faction="bene_gesserit"),
    _card("Guild Administrator", 2, ["guild", "spice_trade"], agent=[{"trash": 1}],
          reveal=[P(1)], faction="guild", count=2),
    _card("Guild Ambassador", 4, ["landsraad"],
          reveal=[P(1), {"optional": [{"pay": {"spice": 3}}, {"influence": "any"}]}],
          faction="guild"),
    _card("Guild Bankers", 3, ["emperor", "guild", "landsraad"],
          agent=[{"gain": {"solari": 2}}], reveal=[P(1)], faction="guild"),
    _card("Jamis", 2, ["fremen"], reveal=[S(2)], faction="fremen"),
    _card("Firm Grip", 4, ["emperor", "landsraad"],
          agent=[{"optional": [{"pay": {"solari": 2}}, {"influence": "any"}]}],
          reveal=[P(2)], faction="emperor"),
    _card("Spice Smugglers", 2, ["city"],
          reveal=[P(1), {"if_influence": {"guild": 2}, "then": [{"gain": {"spice": 1}}]}],
          faction="guild"),
]

IMPERIUM_ROW_SIZE = 5


def _conflict(name, level, first, second, third, control=None):
    return {"name": name, "level": level, "rewards": [first, second, third],
            "control": control}


CONFLICTS = [
    # Level I -- one is used, first
    _conflict("Skirmish (A)", 1, [{"influence": "any"}, {"gain": {"solari": 2}}],
              [{"gain": {"solari": 2}}], [{"gain": {"solari": 1}}]),
    _conflict("Skirmish (B)", 1, [{"influence": "any"}, {"gain": {"spice": 1}}],
              [{"gain": {"spice": 1}}], [{"gain": {"solari": 1}}]),
    _conflict("Skirmish (C)", 1, [{"gain": {"intrigue": 1}, }, {"gain": {"solari": 2}}],
              [{"gain": {"water": 1}}], [{"gain": {"solari": 1}}]),
    _conflict("Skirmish (D)", 1, [{"influence": "any"}, {"gain": {"water": 1}}],
              [{"gain": {"spice": 1}}], [{"gain": {"spice": 1}}]),
    # Level II -- five are used
    _conflict("Desert Power", 2, [{"gain": {"vp": 1, "water": 1}}],
              [{"gain": {"intrigue": 1, "spice": 2}}], [{"gain": {"spice": 1}}]),
    _conflict("Raid Stockpiles", 2, [{"gain": {"intrigue": 1, "spice": 3}}],
              [{"gain": {"intrigue": 1, "spice": 2}}], [{"gain": {"spice": 1}}]),
    _conflict("Cloak and Dagger", 2, [{"influence": "any"}, {"gain": {"intrigue": 2}}],
              [{"gain": {"intrigue": 1}}], [{"gain": {"solari": 2}}]),
    _conflict("Machinations", 2, [{"influence": "any"}, {"influence": "any"}],
              [{"gain": {"water": 1, "solari": 2}}], [{"gain": {"spice": 1}}]),
    _conflict("Siege of Arrakeen", 2, [{"gain": {"vp": 1}}],
              [{"gain": {"solari": 4}}], [{"gain": {"solari": 2}}], control="Arrakeen"),
    _conflict("Siege of Carthag", 2, [{"gain": {"vp": 1}}],
              [{"gain": {"intrigue": 1, "spice": 1}}], [{"gain": {"spice": 1}}], control="Carthag"),
    _conflict("Secure Imperial Basin", 2, [{"gain": {"vp": 1}}],
              [{"gain": {"water": 2}}], [{"gain": {"spice": 1}}], control="Imperial Basin"),
    _conflict("Sort Through the Chaos", 2, [{"gain": {"intrigue": 1, "solari": 4}}],
              [{"gain": {"intrigue": 1, "solari": 2}}], [{"gain": {"solari": 1}}]),
    # Level III -- four are used, last
    _conflict("Grand Vision", 3, [{"influence": "any"}, {"influence": "any"}, {"gain": {"vp": 1}}],
              [{"gain": {"intrigue": 1, "spice": 3}}], [{"gain": {"spice": 3}}]),
    _conflict("Battle for Carthag", 3, [{"gain": {"vp": 2}}],
              [{"gain": {"intrigue": 1, "spice": 3}}], [{"gain": {"spice": 1}}], control="Carthag"),
    _conflict("Battle for Arrakeen", 3, [{"gain": {"vp": 2}}],
              [{"gain": {"intrigue": 1, "solari": 5}}], [{"gain": {"solari": 2}}], control="Arrakeen"),
    _conflict("Battle for Imperial Basin", 3, [{"gain": {"vp": 2}}],
              [{"gain": {"spice": 5}}], [{"gain": {"spice": 3}}], control="Imperial Basin"),
    _conflict("Economic Supremacy", 3, [{"gain": {"vp": 2}}],
              [{"gain": {"vp": 1}}], [{"gain": {"solari": 3}}]),
]
CONFLICTS_PER_LEVEL = {1: 1, 2: 5, 3: 4}


def _intrigue(name, kind, effects, count=1, needs_conflict=False):
    return {"name": name, "kind": kind, "effects": effects, "count": count}


# kind: "plot" (on your turn), "combat" (combat phase, needs units in conflict),
#       "endgame" (scored at game end).
INTRIGUE = [
    _intrigue("Windfall", "plot", [{"gain": {"solari": 2}}], count=2),
    _intrigue("Water Peddlers Union", "plot", [{"gain": {"water": 1}}], count=2),
    _intrigue("Bribery", "plot", [{"optional": [{"pay": {"solari": 2}}, {"influence": "any"}]}], count=2),
    _intrigue("Charisma", "plot", [{"gain": {"persuasion": 2}}], count=2),
    _intrigue("Recruitment Mission", "plot", [{"gain": {"troops": 2}}], count=2),
    _intrigue("Calculated Hire", "plot", [{"optional": [{"pay": {"spice": 1}}, {"gain": {"solari": 3}}]}]),
    _intrigue("Dispatch an Envoy", "plot", [{"influence": "any"}]),
    _intrigue("Ambush", "combat", [{"gain": {"swords": 4}}], count=2),
    _intrigue("Master Tactician", "combat", [{"gain": {"swords": 3}}], count=2),
    _intrigue("Reinforcements", "combat",
              [{"optional": [{"pay": {"solari": 3}}, {"gain": {"conflict_troops": 3}}]}], count=2),
    _intrigue("Siege Tactics", "combat", [{"gain": {"swords": 2}}], count=2),
    _intrigue("Plans Within Plans", "endgame", [{"special": "plans_within_plans"}], count=2),
    _intrigue("Corner the Market", "endgame", [{"special": "corner_the_market"}]),
    _intrigue("Tiebreaker", "endgame", [{"gain": {"spice": 2}}]),
]
