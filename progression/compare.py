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
  1. Framework vs ratings: per-type tau-b under that type's own weight set, combined
     weighted by reports, against a permutation baseline (ratings shuffled within
     each type).
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

Stdlib only.
"""

from __future__ import annotations

import argparse
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
        def ci(xs):
            xs = sorted(xs)
            return [xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))]]
        types[t] = {
            "sessions": len(group), "reports": len(ratings), "skipped": False,
            "tau": taus,
            "vs": {o: {"diff": taus[t] - taus[o], "ci95": ci(diffs[o]),
                       "share_positive": sum(1 for d in diffs[o] if d > 0) / float(bootstrap)}
                   for o in diffs},
        }

    used = {t: v for t, v in types.items() if not v["skipped"]}
    result = {"phase": phase, "sessions_in_phase": len(in_phase), "types": types,
              "within_session": {"sessions": len(within), "mean_tau": sum(within) / len(within) if within else None},
              "replication": replication(in_phase, wsets)}
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
    result["framework"] = {"mean_tau": observed, "permutations": permutations,
                           "p": (hits + 1) / (permutations + 1)}
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
        return
    f = res["framework"]
    print("1. Framework vs ratings   tau-b {} (own sets, weighted by reports) · permutation p {} ({} shuffles)".format(
        _fmt(f["mean_tau"]), _p(f["p"]), f["permutations"]))
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
    if verbose:
        print()
        for t, v in res["types"].items():
            if v["skipped"]:
                print("  {:9} {} sessions, {} reports: skipped".format(t, v["sessions"], v["reports"]))
                continue
            print("  {:9} {} sessions, {} reports · tau-b by set: {}".format(
                t, v["sessions"], v["reports"],
                "  ".join("{} {}".format(k, _fmt(x)) for k, x in v["tau"].items())))


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
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-type detail")
    args = ap.parse_args(argv)

    sessions = [s for path in args.sessions for s in load_all(path)]
    labels = bugs.load_labels(args.bug_labels) if args.bug_labels else None
    res = analyze(sessions, load_weights(args.weights), args.phase, args.min_reports,
                  args.permutations, args.bootstrap, args.seed, labels)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print_report(res, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
