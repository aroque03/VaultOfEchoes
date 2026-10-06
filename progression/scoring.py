"""CAIS and PAIS computation.

CAIS -- Completed Achievement Impact Score. The sum of the weights of every
achievement the player had completed at the moment the bug was encountered.

PAIS -- Potential Achievement Impact Score. The average score still available
across all remaining paths from that point to the end of the game.

Reachability
------------
Remaining does not mean "every incomplete node". Once a level's exit fires the
player descends, and any branch they skipped in that level is gone for good. So
a node is still reachable only if its level has not been closed, where a level
is closed exactly when its exit node is complete.

Within an open level every incomplete node is treated as reachable, including
branches that sit earlier in the enumeration chain than nodes already done. The
chain order in model.py is an enumeration artefact; the game imposes no order on
the branches, so nothing is lost by completing them out of chain order.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set, Tuple

from model import BRANCH_NODES, LEVELS, NODES, PHASE_ORDER, WeightSet, node_id


def closed_levels(completed: "Iterable[str]") -> "Set[int]":
    """Levels the player has already descended out of."""
    done = set(completed)
    return {lv for lv in LEVELS if node_id(lv, "exit") in done}


def reachable_nodes(completed: "Iterable[str]") -> "Tuple[str, ...]":
    """Incomplete nodes that can still be completed, in graph order."""
    done = set(completed)
    shut = closed_levels(done)
    out: List[str] = []
    for lv in LEVELS:
        if lv in shut:
            continue
        for phase in PHASE_ORDER:
            nid = node_id(lv, phase)
            if nid not in done:
                out.append(nid)
    return tuple(out)


def cais(completed: "Iterable[str]", ws: WeightSet) -> int:
    """Sum of the weights of completed achievements."""
    return sum(ws.weight(n) for n in set(completed))


def pais(completed: "Iterable[str]", ws: WeightSet) -> float:
    """Average remaining score over all paths to the end.

    Closed form. Every optional node lies on exactly half of the remaining
    paths, and every mandatory node on all of them, so the average is

        (remaining mandatory) + (remaining optional) / 2

    validated against an explicit path enumeration in pais_by_enumeration().
    """
    reach = reachable_nodes(completed)
    mandatory = sum(ws.weight(n) for n in reach if NODES[n].mandatory)
    optional = sum(ws.weight(n) for n in reach if not NODES[n].mandatory)
    return mandatory + optional / 2.0


def remaining_paths(completed: "Iterable[str]") -> "List[Tuple[str, ...]]":
    """Every distinct remaining path, as a tuple of node ids.

    Walks the bypass DAG: mandatory nodes are always taken, each optional node
    is either taken or skipped. Yields one path per completion subset -- 2^k
    paths for k reachable branch nodes, capped at 512 for a full run.
    """
    reach = reachable_nodes(completed)
    paths: List[Tuple[str, ...]] = [()]
    for nid in reach:
        if NODES[nid].mandatory:
            paths = [p + (nid,) for p in paths]
        else:
            paths = [p + (nid,) for p in paths] + [p for p in paths]
    return paths


def pais_by_enumeration(completed: "Iterable[str]", ws: WeightSet) -> float:
    """PAIS by explicit depth-first path enumeration. The slow ground truth."""
    paths = remaining_paths(completed)
    if not paths:
        return 0.0
    return sum(sum(ws.weight(n) for n in p) for p in paths) / float(len(paths))


def score(completed: "Iterable[str]", ws: WeightSet) -> "Dict[str, float]":
    """CAIS, PAIS and a normalised CAIS for one player type."""
    done = set(completed)
    c = cais(done, ws)
    return {
        "cais": c,
        "pais": pais(done, ws),
        # Identical scales make this redundant for the symmetric weight sets,
        # but the asymmetric sensitivity sets have different totals.
        "cais_pct": 100.0 * c / ws.total() if ws.total() else 0.0,
        "completed_count": len(done & set(NODES)),
        "reachable_count": len(reachable_nodes(done)),
    }


def score_all_types(
    completed: "Iterable[str]", weight_sets: "Dict[str, WeightSet]"
) -> "Dict[str, Dict[str, float]]":
    done = set(completed)
    return {t: score(done, ws) for t, ws in weight_sets.items()}


def prioritize(reports: "Sequence[dict]", ws: WeightSet) -> "List[dict]":
    """Rank bug reports by CAIS descending, then PAIS descending.

    Each report needs a 'completed_nodes' key. The returned dicts are copies
    carrying cais, pais and rank.
    """
    scored: List[dict] = []
    for r in reports:
        row = dict(r)
        s = score(r.get("completed_nodes", []), ws)
        row["cais"] = s["cais"]
        row["pais"] = s["pais"]
        scored.append(row)
    scored.sort(key=lambda r: (-r["cais"], -r["pais"]))
    for i, row in enumerate(scored, 1):
        row["rank"] = i
    return scored
