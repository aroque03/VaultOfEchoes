"""Node model and weight sets for the Vault of Echoes progression study.

The progression graph is a weighted DAG of 21 achievement nodes plus a START and
an END sentinel. Nodes are defined in terms of game events, never maze
coordinates, so the graph stays stable across procedural seeds.

Per level (3 levels), 7 nodes:

    entry -> nav -> [room] -> [chest] -> [boss] -> key -> exit
                      |_________|_________|  (each optional, bypassable)

The four spine nodes are mandatory: every path to the end passes through all of
them. The three branch nodes are optional and each is associated with a Bartle
player type.

IMPORTANT -- the room/chest/boss order in that chain is an artefact of
enumeration, not a rule the game enforces. In play a player may complete any
subset of the branches in any order. Fixing an arbitrary order and giving each
optional node a bypass edge makes a depth-first search enumerate exactly one
path per completion *subset* (8 per level) instead of one per *ordering* (49
per level). Since achievements are one-time and weights sum, ordering cannot
change a path's score, so averaging over orderings would weight "completed
every branch" 24x more heavily than "went straight for the exit" for purely
combinatorial reasons. See pais() in scoring.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

LEVELS: Tuple[int, ...] = (1, 2, 3)

START = "start"
END = "end"

# Phase id -> whether it is mandatory (spine) or optional (branch).
SPINE_PHASES: Tuple[str, ...] = ("entry", "nav", "key", "exit")
BRANCH_PHASES: Tuple[str, ...] = ("room", "chest", "boss")

# The order branches occupy in the bypass chain. Arbitrary; see module docstring.
BRANCH_CHAIN_ORDER: Tuple[str, ...] = ("room", "chest", "boss")

# Bartle type associated with each branch. Socializers are excluded: the game is
# single-player, and the paper says so explicitly.
BRANCH_TYPE: Dict[str, str] = {
    "room": "explorer",
    "chest": "achiever",
    "boss": "killer",
}

PLAYER_TYPES: Tuple[str, ...] = ("explorer", "achiever", "killer")


@dataclass(frozen=True)
class NodeWeights:
    """Per-player-type weight triplet stored on each node."""

    explorer: int
    achiever: int
    killer: int

    def for_type(self, player_type: str) -> int:
        return getattr(self, player_type)

    def as_dict(self) -> "Dict[str, int]":
        return {"explorer": self.explorer, "achiever": self.achiever, "killer": self.killer}


@dataclass(frozen=True)
class Node:
    """One achievement in the progression graph."""

    id: str
    level: int
    phase: str
    mandatory: bool
    trigger: str
    weights: NodeWeights

    @property
    def player_type(self) -> str:
        """Bartle type this node is associated with, or '' for spine nodes."""
        return BRANCH_TYPE.get(self.phase, "")


TRIGGERS: Dict[str, str] = {
    "entry": "chamber loaded",
    "nav": "exit tile located",
    "room": "hidden room entered and story note collected",
    "chest": "hidden chest found via back-and-forth traversal, bonus awarded",
    "boss": "boss arena entered and boss defeated",
    "key": "key chest collected",
    "exit": "door opened, chamber cleared",
}

# Chain order within a level, which is also the order nodes are listed.
PHASE_ORDER: Tuple[str, ...] = ("entry", "nav") + BRANCH_CHAIN_ORDER + ("key", "exit")


# ---------------------------------------------------------------------------
# Weight tables (must precede _build_nodes which embeds them as NodeWeights)
# ---------------------------------------------------------------------------
# Every weight set shares an identical spine, so the sets differ ONLY on the
# optional content -- which is the study's actual hypothesis. Letting the spine
# vary would confound the branch preference with the value of the mandatory
# backbone, and would make a player who found zero branches score differently
# under each set as a pure weighting artefact.
#
# The branch weights are a permutation of the same multiset {13, 3, 2}, each
# type's own branch at 13. Consequently every weight set totals 126 over a full
# run, and raw CAIS is directly comparable across types with no normalisation.
#
# All values are Fibonacci-scale (1, 2, 3, 5, 8, 13, 21).

SPINE_WEIGHTS: Dict[str, int] = {"entry": 3, "nav": 5, "key": 8, "exit": 8}

BRANCH_WEIGHTS: Dict[str, Dict[str, int]] = {
    "explorer": {"room": 13, "chest": 3, "boss": 2},
    "achiever": {"room": 2, "chest": 13, "boss": 3},
    "killer": {"room": 2, "chest": 3, "boss": 13},
}


def node_id(level: int, phase: str) -> str:
    return "l{}.{}".format(level, phase)


def _build_nodes() -> "Dict[str, Node]":
    nodes: Dict[str, Node] = {}
    for level in LEVELS:
        for phase in PHASE_ORDER:
            nid = node_id(level, phase)
            if phase in SPINE_PHASES:
                w = SPINE_WEIGHTS[phase]
                weights = NodeWeights(explorer=w, achiever=w, killer=w)
            else:
                weights = NodeWeights(
                    explorer=BRANCH_WEIGHTS["explorer"][phase],
                    achiever=BRANCH_WEIGHTS["achiever"][phase],
                    killer=BRANCH_WEIGHTS["killer"][phase],
                )
            nodes[nid] = Node(
                id=nid,
                level=level,
                phase=phase,
                mandatory=phase in SPINE_PHASES,
                trigger=TRIGGERS[phase],
                weights=weights,
            )
    return nodes


NODES: Dict[str, Node] = _build_nodes()

SPINE_NODES: Tuple[str, ...] = tuple(n for n, v in NODES.items() if v.mandatory)
BRANCH_NODES: Tuple[str, ...] = tuple(n for n, v in NODES.items() if not v.mandatory)


def level_nodes(level: int) -> Tuple[str, ...]:
    return tuple(node_id(level, p) for p in PHASE_ORDER)


# ---------------------------------------------------------------------------
# Asymmetric weight set (sensitivity analysis)
# ---------------------------------------------------------------------------
# An asymmetric alternative for sensitivity analysis. It deliberately breaks the
# permutation symmetry -- Explorers get flatter preferences, Killers sharper --
# so the analysis can report that conclusions do not depend on the symmetry
# assumption. Totals differ here by design, so cross-type comparison under this
# set must use the normalised score.
BRANCH_WEIGHTS_ASYMMETRIC: Dict[str, Dict[str, int]] = {
    "explorer": {"room": 8, "chest": 5, "boss": 3},
    "achiever": {"room": 3, "chest": 13, "boss": 5},
    "killer": {"room": 1, "chest": 2, "boss": 21},
}


class WeightSet:
    """A view over the node triplets for one player type."""

    def __init__(
        self,
        player_type: str,
        branch_weights: "Dict[str, Dict[str, int]]" = None,
        label: str = "symmetric",
    ) -> None:
        if player_type not in PLAYER_TYPES:
            raise ValueError(
                "unknown player type {!r}; expected one of {}".format(
                    player_type, ", ".join(PLAYER_TYPES)
                )
            )
        self.player_type = player_type
        self.label = label
        if branch_weights is not None and branch_weights is not BRANCH_WEIGHTS:
            table = branch_weights
            self.weights: Dict[str, int] = {}
            for nid, node in NODES.items():
                if node.mandatory:
                    self.weights[nid] = SPINE_WEIGHTS[node.phase]
                else:
                    self.weights[nid] = table[player_type][node.phase]
        else:
            self.weights = {nid: node.weights.for_type(player_type)
                           for nid, node in NODES.items()}

    def weight(self, node_id_: str) -> int:
        return self.weights.get(node_id_, 0)

    def total(self) -> int:
        """Maximum achievable score: every node completed."""
        return sum(self.weights.values())

    def mandatory_total(self) -> int:
        return sum(self.weights[n] for n in SPINE_NODES)

    def optional_total(self) -> int:
        return sum(self.weights[n] for n in BRANCH_NODES)

    def __repr__(self) -> str:
        return "<WeightSet {} ({}) total={}>".format(
            self.player_type, self.label, self.total()
        )


def all_weight_sets(asymmetric: bool = False) -> "Dict[str, WeightSet]":
    table = BRANCH_WEIGHTS_ASYMMETRIC if asymmetric else BRANCH_WEIGHTS
    label = "asymmetric" if asymmetric else "symmetric"
    return {t: WeightSet(t, table, label) for t in PLAYER_TYPES}


# ---------------------------------------------------------------------------
# Graph edges (used only by the DFS validator)
# ---------------------------------------------------------------------------
def build_edges() -> "Dict[str, List[str]]":
    """Adjacency list for the full DAG, with bypass edges on optional nodes."""
    edges: Dict[str, List[str]] = {START: [node_id(LEVELS[0], "entry")]}
    for i, level in enumerate(LEVELS):
        chain = [node_id(level, p) for p in PHASE_ORDER]
        # entry -> nav is a plain edge
        edges[chain[0]] = [chain[1]]
        # From nav, and from each optional node, you may jump to any later node
        # in the chain -- that jump is what "skipping a branch" means.
        optional_span = list(range(1, 2 + len(BRANCH_CHAIN_ORDER)))  # nav..boss
        for idx in optional_span:
            targets = [chain[j] for j in range(idx + 1, 2 + len(BRANCH_CHAIN_ORDER) + 1)]
            edges[chain[idx]] = targets
        key_i = PHASE_ORDER.index("key")
        edges[chain[key_i]] = [chain[PHASE_ORDER.index("exit")]]
        nxt = node_id(LEVELS[i + 1], "entry") if i + 1 < len(LEVELS) else END
        edges[chain[PHASE_ORDER.index("exit")]] = [nxt]
    edges[END] = []
    return edges


EDGES: Dict[str, List[str]] = build_edges()
