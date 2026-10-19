"""Node model and weight sets for the Vault of Echoes progression study.

The progression graph is a weighted DAG of 19 achievement nodes plus a START and
an END sentinel, mirroring the game (js/progression.js). Nodes are defined in
terms of game events, never maze coordinates, so the graph stays stable across
procedural seeds.

Per level, levels 1-2 have 6 nodes and level 3 has 7:

    entry -> [room] -> [chest] -> [boss] -> key -> exit            (L1, L2)
    entry -> [room] -> [chest] -> [boss] -> [greenBoss] -> key -> exit   (L3)
               |_________|_________|___________|  (each optional, bypassable)

Spine nodes (entry, key, exit) are mandatory: every path to the end passes
through all of them. Branch nodes are optional and each is associated with a
Bartle player type.

IMPORTANT -- the branch order in that chain is an artefact of enumeration, not
a rule the game enforces. In play a player may complete any subset of the
branches in any order. Fixing an arbitrary order and giving each optional node
a bypass edge makes a depth-first search enumerate exactly one path per
completion *subset* instead of one per *ordering*. Since achievements are
one-time and weights sum, ordering cannot change a path's score, so averaging
over orderings would weight "completed every branch" far more heavily than
"went straight for the exit" for purely combinatorial reasons. See pais() in
scoring.py.

The progression graph the study reports (js/progression.js) connects each optional
node to every other optional node in its chamber and to the key, since they can be
completed in any order. Drawn that way it contains 2-cycles, but no traversal can
repeat a node (achievements are one-time), so the progression *states* -- sets of
completed nodes -- form a DAG. The bypass chain below is how that state space is
enumerated; it is not a claim about play order.

Weights are measured, not assigned: each node's weight for a player type is the
mean Phase 1 severity attributed to it (api/shared/weights.js). They are loaded
from the weights JSON the admin page exports -- see load_weights().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

LEVELS: Tuple[int, ...] = (1, 2, 3)

START = "start"
END = "end"

SPINE_PHASES: Tuple[str, ...] = ("entry", "key", "exit")
BRANCH_PHASES: Tuple[str, ...] = ("room", "chest", "boss", "greenBoss")

# Chain order within each level, which is also the order nodes are listed.
# The branch order is arbitrary; see module docstring.
LEVEL_PHASES: Dict[int, Tuple[str, ...]] = {
    1: ("entry", "room", "chest", "boss", "key", "exit"),
    2: ("entry", "room", "chest", "boss", "key", "exit"),
    3: ("entry", "room", "chest", "boss", "greenBoss", "key", "exit"),
}

# Bartle type associated with each branch. Socializers are excluded: the game is
# single-player, and the paper says so explicitly.
BRANCH_TYPE: Dict[str, str] = {
    "room": "explorer",
    "chest": "achiever",
    "boss": "killer",
    "greenBoss": "killer",
}

# Runner: players whose highest engagement total stays below 3 (js/progression.js) -- mostly
# straight to key and exit. Named after the "Runners" cluster in Drachen, Canossa &
# Yannakakis (2009). Runners have no branch of their own, only a weight set.
PLAYER_TYPES: Tuple[str, ...] = ("explorer", "achiever", "killer", "runner")

# What fires each node in the game (js/game.js), as of 2026-10-14.
TRIGGERS: Dict[str, str] = {
    "entry": "chamber loaded",
    "room": "hidden room entered",
    "chest": "first gem collected",
    "boss": "purple boss defeated",
    "greenBoss": "green boss defeated (level 3 only)",
    "key": "key chest opened",
    "exit": "door opened, chamber cleared",
}


@dataclass(frozen=True)
class Node:
    """One achievement in the progression graph."""

    id: str
    level: int
    phase: str
    mandatory: bool
    trigger: str

    @property
    def player_type(self) -> str:
        """Bartle type this node is associated with, or '' for spine nodes."""
        return BRANCH_TYPE.get(self.phase, "")


def node_id(level: int, phase: str) -> str:
    return "l{}.{}".format(level, phase)


def level_nodes(level: int) -> Tuple[str, ...]:
    return tuple(node_id(level, p) for p in LEVEL_PHASES[level])


def _build_nodes() -> "Dict[str, Node]":
    nodes: Dict[str, Node] = {}
    for level in LEVELS:
        for phase in LEVEL_PHASES[level]:
            nid = node_id(level, phase)
            nodes[nid] = Node(
                id=nid,
                level=level,
                phase=phase,
                mandatory=phase in SPINE_PHASES,
                trigger=TRIGGERS[phase],
            )
    return nodes


NODES: Dict[str, Node] = _build_nodes()

SPINE_NODES: Tuple[str, ...] = tuple(n for n, v in NODES.items() if v.mandatory)
BRANCH_NODES: Tuple[str, ...] = tuple(n for n, v in NODES.items() if not v.mandatory)


class WeightSet:
    """Node weights for one player type."""

    def __init__(
        self,
        player_type: str,
        weights: "Dict[str, float]",
        counts: "Optional[Dict[str, int]]" = None,
        label: str = "measured",
    ) -> None:
        if player_type not in PLAYER_TYPES:
            raise ValueError(
                "unknown player type {!r}; expected one of {}".format(
                    player_type, ", ".join(PLAYER_TYPES)
                )
            )
        missing = [n for n in NODES if n not in weights]
        if missing:
            raise ValueError(
                "{} weights missing nodes: {}".format(player_type, ", ".join(missing))
            )
        self.player_type = player_type
        self.label = label
        self.weights: Dict[str, float] = {n: float(weights[n]) for n in NODES}
        # Number of Phase 1 reports behind each weight (0 = default placeholder).
        self.counts: Optional[Dict[str, int]] = (
            {n: int(counts.get(n, 0)) for n in NODES} if counts is not None else None
        )

    def weight(self, node_id_: str) -> float:
        return self.weights.get(node_id_, 0.0)

    def total(self) -> float:
        """Maximum achievable score: every node completed."""
        return sum(self.weights.values())

    def mandatory_total(self) -> float:
        return sum(self.weights[n] for n in SPINE_NODES)

    def optional_total(self) -> float:
        return sum(self.weights[n] for n in BRANCH_NODES)

    def __repr__(self) -> str:
        return "<WeightSet {} ({}) total={:.2f}>".format(
            self.player_type, self.label, self.total()
        )


def weight_sets_from_dict(data: "Dict") -> "Dict[str, WeightSet]":
    """Build every type's weight set from {explorer: {...}, achiever: {...}, killer: {...}, runner: {...}}.

    Accepts both _weights.json and the admin DOWNLOAD WEIGHTS file; the optional
    `_counts` block (reports per node) is carried along when present.
    """
    counts = data.get("_counts") or {}
    return {
        t: WeightSet(t, data[t], counts.get(t) if counts else None)
        for t in PLAYER_TYPES
    }


def load_weights(path: str) -> "Dict[str, WeightSet]":
    with open(path, "r", encoding="utf-8") as fh:
        return weight_sets_from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# Graph edges (used only by the DFS validator)
# ---------------------------------------------------------------------------
def build_edges() -> "Dict[str, List[str]]":
    """Adjacency list for the full DAG, with bypass edges on optional nodes."""
    edges: Dict[str, List[str]] = {START: [node_id(LEVELS[0], "entry")]}
    for i, level in enumerate(LEVELS):
        chain = list(level_nodes(level))
        key_i = LEVEL_PHASES[level].index("key")
        # From entry, and from each optional node, you may jump to any later
        # node up to and including the key -- that jump is "skipping a branch".
        for idx in range(0, key_i):
            edges[chain[idx]] = chain[idx + 1:key_i + 1]
        edges[chain[key_i]] = [chain[key_i + 1]]
        nxt = node_id(LEVELS[i + 1], "entry") if i + 1 < len(LEVELS) else END
        edges[chain[-1]] = [nxt]
    edges[END] = []
    return edges


EDGES: Dict[str, List[str]] = build_edges()
