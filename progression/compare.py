"""Phase 2 analysis: does the framework's bug priority match players' impact ratings?

    python3 progression/compare.py vault-sessions.json --weights phase1-weights.json
    python3 progression/compare.py vault-sessions.json --weights w.json -v      # per-type detail
    python3 progression/compare.py vault-sessions.json --weights w.json --json  # machine-readable

Why reports are pooled across players: within one session the set of completed
achievements only grows and every weight is positive, so CAIS never decreases over
time. Ranking one player's reports by CAIS is therefore just time order, identical
under every weight set. Weight sets can only be told apart across players, whose
completion sets differ, which is also how the framework is used (triaging bugs
reported by many players). So reports are pooled per player type.

For each type, its players' reports are ranked by the framework (CAIS descending,
PAIS breaking ties) and compared with their 1-5 impact ratings using Kendall's
tau-b, which handles the many ties a 1-5 scale produces.

  0. Within-session order: mean per-session tau-b of ratings vs time order. The same
     for every weight set; it asks whether later bugs bother players more.
  1. Framework vs ratings (answers SP3): per-type tau-b under that type's own weight
     set, combined weighted by reports, against a permutation baseline (ratings
     shuffled within each type), with a bootstrap 95% interval (sessions resampled
     within each type).
  2. Own vs other weight sets: per type, tau-b(own) - tau-b(other) for each other
     set, with a bootstrap 95% interval from resampling that type's sessions.
  3. Own vs uniform weights: the same against every node weighted 1, i.e. CAIS = how
     far the player had progressed. Measured weights should beat it.
  4. Replication: Phase 2's own mean severity per node and type (attributed with the
     Phase 1 rule) against the Phase 1 weights, Spearman rho over nodes with data in
     both.
  5. Bug ranking (with --bug-labels, the coding sheet from bugs.py): per type, each
     labelled bug's mean CAIS / mean PAIS under the type's own weights against its mean
     rating; the framework's bug order vs the players' bug order, Kendall tau-b.
  6. Graph fit per player: which Phase 1 graph agreed most with each player. A graph
     predicts a report's rating as the mean of its weights on the nodes the report's
     severity goes to (nodes without Phase 1 data use that graph's mean weight). The
     graph with the smallest mean absolute error over the player's reports fits best.
     Summary: how often the player's own type's graph fits best, against a permutation
     baseline (types shuffled among players), for the derived and self-reported types.
  1b/6b. Which identity should pick a player's graph: their derived type (behavior)
     or their self-reported type (the post-game question)? Over players who answered,
     comparison 1 and comparison 6 are computed both ways on the same players, with a
     bootstrap 95% interval for the difference (players resampled).

Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import NODES, PLAYER_TYPES, WeightSet, load_weights, next_open_nodes  # noqa: E402
from scoring import cais, pais  # noqa: E402
from session import Session, load_all  # noqa: E402
import bugs  # noqa: E402


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _sign(v) -> int:
    return (v > 0) - (v < 0)


def kendall_tau_b(xs: Sequence, ys: Sequence) -> Optional[float]:
    """Kendall's tau-b between two sequences of comparable values; None if undefined."""
    n = len(xs)
    concordant = discordant = ties_x = ties_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            sx = _sign((xs[i] > xs[j]) - (xs[i] < xs[j]))
            sy = _sign((ys[i] > ys[j]) - (ys[i] < ys[j]))
            if sx == 0:
                ties_x += 1
            if sy == 0:
                ties_y += 1
            if sx and sy:
                if sx == sy:
                    concordant += 1
                else:
                    discordant += 1
    pairs = n * (n - 1) // 2
    denom = math.sqrt((pairs - ties_x) * (pairs - ties_y))
    return (concordant - discordant) / denom if denom else None


def _ranks(values: Sequence[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def uniform_weight_set() -> WeightSet:
    return WeightSet(PLAYER_TYPES[0], {n: 1 for n in NODES}, label="uniform")


def priority_key(completed: List[str], ws: WeightSet) -> Tuple[float, float]:
    """Framework priority: higher CAIS first, then higher PAIS."""
    return (round(cais(completed, ws), 9), round(pais(completed, ws), 9))


def rated_reports(sess: Session) -> List[dict]:
    return [r for r in sess.bug_reports
            if isinstance(r.get("impact_rating"), (int, float)) and r.get("completed_nodes")]


def _tau0(xs, ys) -> float:
    tau = kendall_tau_b(xs, ys)
    return 0.0 if tau is None else tau  # an ordering that ties everything predicts nothing


def _ci95(xs: List[float]) -> List[float]:
    xs = sorted(xs)
    return [xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))]]


def _pool(sessions: List[Session], ws: WeightSet) -> Tuple[List[float], List[Tuple[float, float]]]:
    ratings, keys = [], []
    for s in sessions:
        for r in rated_reports(s):
            ratings.append(r["impact_rating"])
            keys.append(priority_key(r["completed_nodes"], ws))
    return ratings, keys


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def analyze(sessions: List[Session], wsets: Dict[str, WeightSet], phase: int = 2,
            min_reports: int = 3, permutations: int = 2000, bootstrap: int = 1000, seed: int = 1,
            bug_labels: Optional[Dict[str, str]] = None) -> dict:
    rng = random.Random(seed)
    uniform = uniform_weight_set()
    in_phase = [s for s in sessions if s.study_phase == phase]
    by_type = {t: [s for s in in_phase if s.classified_type == t and rated_reports(s)] for t in PLAYER_TYPES}
    sets = dict(wsets, uniform=uniform)

    # 0. Within-session order (identical under every weight set).
    within = [kendall_tau_b([r["impact_rating"] for r in rated_reports(s)], list(range(len(rated_reports(s)))))
              for s in in_phase if len(rated_reports(s)) >= 2]
    within = [t for t in within if t is not None]

    types = {}
    own_sessions = {}  # type -> [(ratings, own-set priority keys)] per session, for comparison 1's interval
    for t, group in by_type.items():
        ratings, _ = _pool(group, wsets[t])
        if len(ratings) < min_reports or len(set(ratings)) < 2:
            types[t] = {"sessions": len(group), "reports": len(ratings), "skipped": True}
            continue
        # Precompute each report's priority under every set, per session, for resampling.
        per_session = []
        for s in group:
            reps = rated_reports(s)
            per_session.append(([r["impact_rating"] for r in reps],
                                {name: [priority_key(r["completed_nodes"], ws) for r in reps]
                                 for name, ws in sets.items()}))
        own_sessions[t] = [(rs, ks[t]) for rs, ks in per_session]
        def taus_for(sample):
            ys = [y for rs, _ in sample for y in rs]
            return {name: _tau0(ys, [k for _, ks in sample for k in ks[name]]) for name in sets}
        taus = taus_for(per_session)
        others = [o for o in PLAYER_TYPES if o != t]
        diffs = {o: [] for o in others + ["uniform"]}
        for _ in range(bootstrap):
            sample = [per_session[rng.randrange(len(per_session))] for _ in per_session]
            bt = taus_for(sample)
            for o in diffs:
                diffs[o].append(bt[t] - bt[o])
        types[t] = {
            "sessions": len(group), "reports": len(ratings), "skipped": False,
            "tau": taus,
            "vs": {o: {"diff": taus[t] - taus[o], "ci95": _ci95(diffs[o]),
                       "share_positive": sum(1 for d in diffs[o] if d > 0) / float(bootstrap)}
                   for o in diffs},
        }

    used = {t: v for t, v in types.items() if not v["skipped"]}
    result = {"phase": phase, "sessions_in_phase": len(in_phase), "types": types,
              "within_session": {"sessions": len(within), "mean_tau": sum(within) / len(within) if within else None},
              "replication": replication(in_phase, wsets),
              "graph_fit": graph_fit(in_phase, wsets, permutations, seed)}
    result["identity"] = identity_comparison(in_phase, wsets, result["graph_fit"], min_reports, bootstrap, seed)
    if bug_labels is not None:
        result["bug_ranking"] = bug_ranking(in_phase, wsets, bug_labels)
    if not used:
        return result

    # 1. Framework vs ratings (own sets), weighted by reports; shuffle ratings within each type.
    total_reports = sum(v["reports"] for v in used.values())
    observed = sum(v["tau"][t] * v["reports"] for t, v in used.items()) / total_reports
    pools = {t: _pool(by_type[t], wsets[t]) for t in used}
    hits = 0
    for _ in range(permutations):
        acc = 0.0
        for t, (ys, ks) in pools.items():
            sh = ys[:]
            rng.shuffle(sh)
            acc += _tau0(sh, ks) * len(ys)
        if acc / total_reports >= observed - 1e-12:
            hits += 1
    # Interval: resample sessions within each type, recombine weighted by reports.
    boot = []
    for _ in range(bootstrap):
        acc = n = 0.0
        for t in used:
            data = own_sessions[t]
            sample = [data[rng.randrange(len(data))] for _ in data]
            ys = [y for rs, _ in sample for y in rs]
            ks = [k for _, kk in sample for k in kk]
            acc += _tau0(ys, ks) * len(ys)
            n += len(ys)
        boot.append(acc / n)
    result["framework"] = {"mean_tau": observed, "ci95": _ci95(boot), "reports": total_reports,
                           "permutations": permutations, "p": (hits + 1) / (permutations + 1)}
    return result


def bug_ranking(sessions: List[Session], wsets: Dict[str, WeightSet], labels: Dict[str, str]) -> dict:
    """Per type: each labelled bug's mean CAIS, mean PAIS and mean rating; tau-b between the two orders."""
    acc: Dict[str, Dict[str, List[list]]] = {t: {} for t in PLAYER_TYPES}
    unlabelled = 0
    for s in sessions:
        if s.classified_type not in PLAYER_TYPES:
            continue
        for i, r in enumerate(s.bug_reports):
            if not isinstance(r.get("impact_rating"), (int, float)) or not r.get("completed_nodes"):
                continue
            label = labels.get(bugs.report_key(s, i, r))
            if not label:
                unlabelled += 1
                continue
            c, p = priority_key(r["completed_nodes"], wsets[s.classified_type])
            acc[s.classified_type].setdefault(label, []).append([c, p, r["impact_rating"]])
    out = {"unlabelled": unlabelled, "types": {}}
    for t, by_bug in acc.items():
        table = []
        for label, xs in by_bug.items():
            n = len(xs)
            table.append({"bug": label, "reports": n, "mean_cais": sum(x[0] for x in xs) / n,
                          "mean_pais": sum(x[1] for x in xs) / n, "mean_rating": sum(x[2] for x in xs) / n})
        table.sort(key=lambda b: (-b["mean_cais"], -b["mean_pais"]))
        tau = None
        if len(table) >= 3:
            tau = kendall_tau_b([b["mean_rating"] for b in table],
                                [(round(b["mean_cais"], 9), round(b["mean_pais"], 9)) for b in table])
        out["types"][t] = {"bugs": table, "tau": tau}
    return out


def predicted_rating(done: List[str], ws: WeightSet) -> float:
    """A graph's predicted rating for a report: mean weight on the nodes its severity goes to.

    Nodes with no Phase 1 reports (placeholder weight) count at the graph's mean weight
    over the nodes that have data, so missing data doesn't drag a prediction toward 1.
    """
    counts = ws.counts
    with_data = [n for n in NODES if counts is None or counts.get(n, 0) > 0]
    fallback = sum(ws.weight(n) for n in with_data) / len(with_data) if with_data else 1.0
    nodes = next_open_nodes(done[-1], done)
    if not nodes:
        return fallback
    vals = [ws.weight(n) if counts is None or counts.get(n, 0) > 0 else fallback for n in nodes]
    return sum(vals) / len(vals)


def graph_fit(sessions: List[Session], wsets: Dict[str, WeightSet], permutations: int = 2000,
              seed: int = 1) -> dict:
    """Per player: each graph's mean absolute error on their ratings, and the best-fitting graph."""
    players = []
    for s in sessions:
        reps = rated_reports(s)
        if not reps:
            continue
        mae = {t: sum(abs(r["impact_rating"] - predicted_rating(r["completed_nodes"], ws)) for r in reps) / len(reps)
               for t, ws in wsets.items()}
        low = min(mae.values())
        best = sorted(t for t, v in mae.items() if v - low < 1e-9)
        players.append({"source": s.source, "player_id": s.player_id, "reports": len(reps),
                        "derived": s.classified_type, "self_reported": s.self_reported_type,
                        "mae": mae, "best": best})

    def summary(key: str) -> dict:
        ps = [p for p in players if p[key] in PLAYER_TYPES]
        if not ps:
            return {"players": 0}
        decided = [p for p in ps if len(p["best"]) == 1]
        matches = sum(1 for p in decided if p["best"][0] == p[key])
        table = {t: {g: 0 for g in list(PLAYER_TYPES) + ["tie"]} for t in PLAYER_TYPES}
        for p in ps:
            table[p[key]][p["best"][0] if len(p["best"]) == 1 else "tie"] += 1
        # Chance: shuffle the types among the decided players, keep their best graphs.
        rng = random.Random(seed)
        types = [p[key] for p in decided]
        hits = 0
        for _ in range(permutations):
            rng.shuffle(types)
            if sum(1 for p, t in zip(decided, types) if p["best"][0] == t) >= matches:
                hits += 1
        return {"players": len(ps), "decided": len(decided), "matches": matches,
                "rate": matches / len(decided) if decided else None,
                "p": (hits + 1) / (permutations + 1) if decided else None, "table": table}

    return {"players": players, "derived": summary("derived"), "self_reported": summary("self_reported")}


def identity_comparison(sessions: List[Session], wsets: Dict[str, WeightSet], fit: dict,
                        min_reports: int = 3, bootstrap: int = 1000, seed: int = 1) -> dict:
    """Derived vs self-reported type as the way to choose a player's graph (1b and 6b)."""
    rng = random.Random(seed + 7)
    items = []  # (ratings, priority keys under every graph, derived type, self-reported type)
    for s in sessions:
        reps = rated_reports(s)
        if reps and s.classified_type in PLAYER_TYPES and s.self_reported_type in PLAYER_TYPES:
            items.append(([r["impact_rating"] for r in reps],
                          {t: [priority_key(r["completed_nodes"], ws) for r in reps] for t, ws in wsets.items()},
                          s.classified_type, s.self_reported_type))

    def weighted_tau(sample, which):
        pools: Dict[str, Tuple[list, list]] = {}
        for it in sample:
            t = it[which]
            ys, ks = pools.setdefault(t, ([], []))
            ys.extend(it[0])
            ks.extend(it[1][t])
        acc = n = 0
        for ys, ks in pools.values():
            if len(ys) >= min_reports and len(set(ys)) >= 2:
                acc += _tau0(ys, ks) * len(ys)
                n += len(ys)
        return acc / n if n else None

    out: dict = {"players": len(items)}
    d, sr = weighted_tau(items, 2), weighted_tau(items, 3)
    if d is not None and sr is not None:
        diffs = []
        for _ in range(bootstrap):
            sample = [items[rng.randrange(len(items))] for _ in items]
            bd, bs = weighted_tau(sample, 2), weighted_tau(sample, 3)
            if bd is not None and bs is not None:
                diffs.append(bs - bd)
        out["framework"] = {"derived": d, "self_reported": sr, "diff": sr - d,
                            "ci95": _ci95(diffs) if diffs else None}

    # 6b: each player's mean miss with the graph of their derived vs self-reported type.
    ps = [p for p in fit["players"] if p["derived"] in PLAYER_TYPES and p["self_reported"] in PLAYER_TYPES]
    if ps:
        diffs = [p["mae"][p["self_reported"]] - p["mae"][p["derived"]] for p in ps]
        boot = []
        for _ in range(bootstrap):
            sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
            boot.append(sum(sample) / len(sample))
        out["graph_fit"] = {
            "players": len(ps),
            "derived": sum(p["mae"][p["derived"]] for p in ps) / len(ps),
            "self_reported": sum(p["mae"][p["self_reported"]] for p in ps) / len(ps),
            "diff": sum(diffs) / len(diffs), "ci95": _ci95(boot),
            "self_better": sum(1 for x in diffs if x < -1e-9),
            "derived_better": sum(1 for x in diffs if x > 1e-9),
            "same_type": sum(1 for p in ps if p["derived"] == p["self_reported"]),
        }
    return out


def write_fit_csv(path: str, fit: dict) -> None:
    cols = ["source", "player_id", "reports", "derived", "self_reported", "best_graph"] + \
           ["mae_" + t for t in PLAYER_TYPES]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for p in fit["players"]:
            w.writerow([p["source"], p["player_id"], p["reports"], p["derived"], p["self_reported"],
                        "/".join(p["best"])] + [round(p["mae"][t], 4) for t in PLAYER_TYPES])


def replication(sessions: List[Session], wsets: Dict[str, WeightSet], min_n: int = 1) -> dict:
    """Phase 2 mean severity per node vs Phase 1 weight, per type, over nodes with data in both."""
    sums = {t: {} for t in PLAYER_TYPES}
    counts = {t: {} for t in PLAYER_TYPES}
    for s in sessions:
        if s.classified_type not in PLAYER_TYPES:
            continue
        for r in rated_reports(s):
            done = r["completed_nodes"]
            for n in next_open_nodes(done[-1], done):
                sums[s.classified_type][n] = sums[s.classified_type].get(n, 0) + r["impact_rating"]
                counts[s.classified_type][n] = counts[s.classified_type].get(n, 0) + 1
    out = {}
    for t in PLAYER_TYPES:
        p1_counts = wsets[t].counts
        nodes = [n for n, c in counts[t].items()
                 if c >= min_n and (p1_counts is None or p1_counts.get(n, 0) > 0)]
        p1 = [wsets[t].weight(n) for n in nodes]
        p2 = [sums[t][n] / counts[t][n] for n in nodes]
        out[t] = {"nodes": len(nodes), "rho": spearman(p1, p2)}
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _fmt(v: Optional[float], digits: int = 2) -> str:
    return "n/a" if v is None else "{:.{d}f}".format(v, d=digits)


def _p(v: float) -> str:
    return "<0.001" if v < 0.001 else "{:.3f}".format(v)


def print_report(res: dict, verbose: bool = False) -> None:
    used = {t: v for t, v in res["types"].items() if not v["skipped"]}
    skipped = [t for t, v in res["types"].items() if v["skipped"]]
    print("Phase {} · {} sessions · {} reports pooled by type{}".format(
        res["phase"], res["sessions_in_phase"], sum(v["reports"] for v in used.values()),
        " (too few reports: " + ", ".join(skipped) + ")" if skipped else ""))
    w = res["within_session"]
    print("0. Within-session order   mean tau-b {} over {} sessions (same for every weight set)".format(
        _fmt(w["mean_tau"]), w["sessions"]))
    if not used:
        print("No player type has enough rated reports to compare.")
        print_graph_fit(res["graph_fit"])  # per player, so it doesn't need the pooled minimum
        return
    f = res["framework"]
    print("1. Framework vs ratings   tau-b {} [95% CI {}, {}] over {} reports · permutation p {}   <- SP3".format(
        _fmt(f["mean_tau"]), _fmt(f["ci95"][0]), _fmt(f["ci95"][1]), f["reports"], _p(f["p"])))
    print("                          (own weight set per type, reports pooled per type; {} shuffles)".format(
        f["permutations"]))
    idf = res["identity"].get("framework")
    if idf:
        print("1b. Graph picked by        derived type tau-b {} · self-reported {} · difference (self \u2212 derived) {} [95% CI {}, {}] over {} players who answered".format(
            _fmt(idf["derived"]), _fmt(idf["self_reported"]), _fmt(idf["diff"]),
            _fmt(idf["ci95"][0] if idf["ci95"] else None), _fmt(idf["ci95"][1] if idf["ci95"] else None),
            res["identity"]["players"]))
    print("2. Own vs other sets      tau-b own minus other [95% CI]:")
    for t, v in used.items():
        parts = ["{} {} [{}, {}]".format(o, _fmt(x["diff"]), _fmt(x["ci95"][0]), _fmt(x["ci95"][1]))
                 for o, x in v["vs"].items() if o != "uniform"]
        print("   {:9} own {} · {}".format(t, _fmt(v["tau"][t]), " · ".join(parts)))
    print("3. Own vs uniform         " + " · ".join(
        "{} {} [{}, {}]".format(t, _fmt(v["vs"]["uniform"]["diff"]), _fmt(v["vs"]["uniform"]["ci95"][0]),
                                _fmt(v["vs"]["uniform"]["ci95"][1])) for t, v in used.items()))
    rep = res["replication"]
    print("4. Replication (rho)      " + " · ".join(
        "{} {} (k={})".format(t, _fmt(v["rho"]), v["nodes"]) for t, v in rep.items()))
    if "bug_ranking" in res:
        br = res["bug_ranking"]
        print("5. Bug ranking            framework order (mean CAIS, PAIS) vs mean rating{}".format(
            " · {} reports without a label left out".format(br["unlabelled"]) if br["unlabelled"] else ""))
        for t, v in br["types"].items():
            if not v["bugs"]:
                continue
            print("   {:9} tau-b {} over {} bugs".format(t, _fmt(v["tau"]), len(v["bugs"])))
            by_rating = sorted(v["bugs"], key=lambda b: -b["mean_rating"])
            for i, b in enumerate(v["bugs"], 1):
                print("     {}. {:24} CAIS {:6.2f}  PAIS {:6.2f}  rating {:4.2f} (rank {})  n={}".format(
                    i, b["bug"][:24], b["mean_cais"], b["mean_pais"], b["mean_rating"],
                    by_rating.index(b) + 1, b["reports"]))
    print_graph_fit(res["graph_fit"])
    igf = res["identity"].get("graph_fit")
    if igf:
        print("6b. Graph picked by        mean miss with derived-type graph {} · self-reported-type graph {} · difference (self \u2212 derived) {} [95% CI {}, {}]".format(
            _fmt(igf["derived"]), _fmt(igf["self_reported"]), _fmt(igf["diff"]), _fmt(igf["ci95"][0]), _fmt(igf["ci95"][1])))
        print("                          self-reported graph closer for {} players, derived closer for {}, same for {} ({} said the same type the rules found)".format(
            igf["self_better"], igf["derived_better"], igf["players"] - igf["self_better"] - igf["derived_better"], igf["same_type"]))
    if verbose:
        print()
        for t, v in res["types"].items():
            if v["skipped"]:
                print("  {:9} {} sessions, {} reports: skipped".format(t, v["sessions"], v["reports"]))
                continue
            print("  {:9} {} sessions, {} reports · tau-b by set: {}".format(
                t, v["sessions"], v["reports"],
                "  ".join("{} {}".format(k, _fmt(x)) for k, x in v["tau"].items())))


def print_graph_fit(fit: dict) -> None:
    print("6. Graph fit per player   graph with the smallest mean rating error (rating points):")
    for key, name in (("derived", "derived type"), ("self_reported", "self-reported type")):
        sm = fit[key]
        if not sm.get("decided"):
            print("   own graph fits best ({}): no players".format(name))
            continue
        print("   own graph fits best ({}): {}/{} players ({:.0f}%, chance about 25%) · permutation p {}{}".format(
            name, sm["matches"], sm["decided"], 100 * sm["rate"], _p(sm["p"]),
            " · {} ties".format(sm["players"] - sm["decided"]) if sm["players"] > sm["decided"] else ""))
        cols = list(PLAYER_TYPES) + ["tie"]
        print("     {:36} {}".format(name + " \u2193 / best graph \u2192", "".join(c[:8].rjust(9) for c in cols)))
        for t in PLAYER_TYPES:
            row = sm["table"][t]
            if sum(row.values()):
                print("     {:36} {}".format(t, "".join(str(row[c]).rjust(9) for c in cols)))
    print("   {:22} {:9} {:9} {:10} {}".format("player", "derived", "self", "best", "  ".join(t[:8].ljust(8) for t in PLAYER_TYPES)))
    for p in fit["players"]:
        print("   {:22} {:9} {:9} {:10} {}".format(
            (p["player_id"] or p["source"])[-22:], p["derived"] or "-", p["self_reported"] or "-",
            "/".join(p["best"])[:10], "  ".join("{:<8.2f}".format(p["mae"][t]) for t in PLAYER_TYPES)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 comparison of framework priority vs impact ratings.")
    ap.add_argument("sessions", nargs="+", help="session JSON file(s) or /api/export file")
    ap.add_argument("--weights", required=True, help="frozen Phase 1 weights JSON")
    ap.add_argument("--phase", type=int, default=2, help="study phase to analyze (default 2)")
    ap.add_argument("--min-reports", type=int, default=3, help="rated reports a type needs (default 3)")
    ap.add_argument("--permutations", type=int, default=2000, help="shuffles for the baseline (default 2000)")
    ap.add_argument("--bootstrap", type=int, default=1000, help="session resamples for intervals (default 1000)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for the shuffles")
    ap.add_argument("--bug-labels", help="coding sheet from bugs.py export, with bug_label filled")
    ap.add_argument("--fit-csv", help="write the per-player graph fit table (comparison 6) to this CSV")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-type detail")
    args = ap.parse_args(argv)

    sessions = [s for path in args.sessions for s in load_all(path)]
    labels = bugs.load_labels(args.bug_labels) if args.bug_labels else None
    res = analyze(sessions, load_weights(args.weights), args.phase, args.min_reports,
                  args.permutations, args.bootstrap, args.seed, labels)
    if args.fit_csv:
        write_fit_csv(args.fit_csv, res["graph_fit"])
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print_report(res, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
