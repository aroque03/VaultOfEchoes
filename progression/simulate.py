"""Synthetic sessions for end-to-end testing of both study phases.

    python3 progression/simulate.py phase1 --url https://<site>      # needs STUDY_PHASE unset/1
    python3 progression/simulate.py phase2 --url https://<site>      # needs STUDY_PHASE=2
    add --dry-run to generate and check locally without uploading

phase1  Uploads 10 sessions concurrently. Each player type rates every bug at a
        fixed severity (explorer 5, achiever 3, killer 1), so the recovered
        weights must equal exactly that on every reported node. Also checks the
        server's weights against an independent calculation here.
phase2  Uploads 10 sessions whose ratings are planted to follow CAIS under the
        player's own weights. Checks the server stamps phase 2 and leaves the
        weights untouched, then checks the ranking comparison finds the planted
        relation (and finds none when ratings are shuffled).

Sessions are written to --out (default: a temp dir) so they can be inspected or
fed to validate.py / cli.py. Player names start with "SIM-" for easy cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import LEVELS, NODES, PLAYER_TYPES, level_nodes, node_id, weight_sets_from_dict  # noqa: E402
from scoring import prioritize  # noqa: E402
from session import parse  # noqa: E402
from validate import BUG_TABLE, check, expected_bugs  # noqa: E402

N_SESSIONS = 10
PHASE1_SEVERITY = {"explorer": 5, "achiever": 3, "killer": 1}
OWN_BRANCHES = {"explorer": {"room"}, "achiever": {"chest"}, "killer": {"boss", "greenBoss"}}

# Same edges as DAG_EDGES in js/progression.js / api/shared/weights.js.
DAG_EDGES: Dict[str, List[str]] = {}
for _lv in LEVELS:
    _nodes = level_nodes(_lv)
    _branches = [n for n in _nodes if not NODES[n].mandatory]
    DAG_EDGES[node_id(_lv, "entry")] = _branches + [node_id(_lv, "key")]
    for _b in _branches:
        DAG_EDGES[_b] = [node_id(_lv, "key")]
    DAG_EDGES[node_id(_lv, "key")] = [node_id(_lv, "exit")]
    DAG_EDGES[node_id(_lv, "exit")] = [node_id(_lv + 1, "entry")] if _lv < LEVELS[-1] else []


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def make_path(rng: random.Random, ptype: str, stop_level: int, finished: bool) -> List[str]:
    """Completion order: per level entry, some branches (own type likely), key, exit.

    An unfinished run ends partway through stop_level (no key or exit there).
    """
    path: List[str] = []
    for lv in LEVELS:
        if lv > stop_level:
            break
        path.append(node_id(lv, "entry"))
        branches = [n for n in level_nodes(lv) if not NODES[n].mandatory]
        rng.shuffle(branches)
        for b in branches:
            own = NODES[b].phase in OWN_BRANCHES[ptype]
            if rng.random() < (0.9 if own else 0.3):
                path.append(b)
        if lv < stop_level or finished:
            path += [node_id(lv, "key"), node_id(lv, "exit")]
    return path


def make_session(rng: random.Random, idx: int, ptype: str, phase: int,
                 rate=None) -> dict:
    """One session in the game's upload format. `rate(ptype, completed)` -> 1..5."""
    finished = idx % 5 != 0  # every 5th player dies partway through
    stop = LEVELS[-1] if finished else rng.choice([2, 3])
    path = make_path(rng, ptype, stop, finished)
    t0 = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc) + timedelta(hours=idx)
    iso = lambda s: (t0 + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    completions, clock = [], 3
    report_points: List[Tuple[int, int]] = []  # (index into path, seconds)
    for i, nid in enumerate(path):
        completions.append({"node": nid, "timestamp": iso(clock), "elapsed_ms": clock * 1000})
        if rng.random() < 0.35:
            report_points.append((i, clock + 20))
        clock += rng.randint(40, 120)
    end = clock

    reports = []
    for k, (i, secs) in enumerate(report_points, 1):
        done = path[:i + 1]
        ch = NODES[done[-1]].level
        sev = rate(ptype, done) if rate else PHASE1_SEVERITY[ptype]
        reports.append({
            "id": k, "bug_id": "b-{}-l{}".format(k, ch), "chamber": ch,
            "seed": 0, "tileX": 0, "tileY": 0, "category": "Other",
            "impact_rating": sev, "severity": sev,
            "description": "Synthetic report {} ({})".format(k, ptype),
            "completed_nodes": done, "injectedBugs": expected_bugs(ch),
            "timestamp": iso(secs),
        })

    reached = sorted({NODES[n].level for n in path})
    outcomes, encounters = {}, []
    for lv in reached:
        for n in level_nodes(lv):
            if not NODES[n].mandatory:
                outcomes[n] = "found" if n in path else rng.choice(["attempted", "never_approached"])
        for bug in expected_bugs(lv):
            nid = node_id(lv, BUG_TABLE[bug][0])
            if nid in path and rng.random() < 0.5:
                at = completions[path.index(nid)]
                encounters.append({"type": bug, "node": nid, "chamber": lv,
                                   "timestamp": at["timestamp"], "elapsed_ms": at["elapsed_ms"]})

    return {
        "schema": "vault-of-echoes.study-session/v1",
        "synthetic": True,
        "player": {"id": "sim-p{}-{:02d}".format(phase, idx), "name": "SIM-{:02d}".format(idx), "email": None},
        "session": {"build": "voe-study-1.0", "seed": 0, "started_at": iso(0),
                    "ended_at": iso(end), "duration_ms": end * 1000},
        "progression_graph": {"node_completions": completions, "branch_outcomes": outcomes,
                              "rooms_found": {}},
        "player_classification": {"level_engagement": {},
                                  "player_type": {"dominant": ptype, "totals": {}, "tiebroken": False}},
        "bug_reports": reports,
        "bug_encounters": encounters,
        "injectedConfig": {str(lv): expected_bugs(lv) for lv in LEVELS},
        "finalScore": 0,
        "scoring": {"weights_loaded": False},
    }


def generate(phase: int, rate=None, seed: int = 7) -> List[dict]:
    rng = random.Random(seed + phase)
    types = [PLAYER_TYPES[i % 3] for i in range(N_SESSIONS)]
    return [make_session(rng, i, t, phase, rate) for i, t in enumerate(types)]


# ---------------------------------------------------------------------------
# Independent weight calculation (cross-checks api/shared/weights.js)
# ---------------------------------------------------------------------------
def expected_weights(sessions: List[dict]):
    sums = {t: {n: 0.0 for n in NODES} for t in PLAYER_TYPES}
    counts = {t: {n: 0 for n in NODES} for t in PLAYER_TYPES}
    for s in sessions:
        if s.get("study_phase", 1) != 1:
            continue
        t = s["player_classification"]["player_type"]["dominant"]
        for r in s["bug_reports"]:
            for nxt in DAG_EDGES[r["completed_nodes"][-1]]:
                sums[t][nxt] += r["impact_rating"]
                counts[t][nxt] += 1
    weights = {t: {n: (sums[t][n] / counts[t][n] if counts[t][n] else 1.0) for n in NODES}
               for t in PLAYER_TYPES}
    return weights, counts


# ---------------------------------------------------------------------------
# Ranking comparison
# ---------------------------------------------------------------------------
def _ranks(values: List[float]) -> List[float]:
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


def spearman(x: List[float], y: List[float]) -> float:
    rx, ry = _ranks(x), _ranks(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else 0.0


def priority_vs_rating(sessions: List[dict], wsets) -> float:
    """Spearman between human rating and CAIS-desc/PAIS-desc priority (own weight set)."""
    ratings, priority = [], []
    for s in sessions:
        sess = parse(s)
        if not sess.bug_reports:
            continue
        ranked = prioritize(sess.bug_reports, wsets[sess.classified_type])
        n = len(ranked)
        for r in ranked:
            ratings.append(r["impact_rating"])
            # Normalised so 1.0 = top priority within the player's own reports.
            priority.append(1.0 if n == 1 else 1.0 - (r["rank"] - 1) / (n - 1))
    return spearman(ratings, priority)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def post(url: str, session: dict) -> dict:
    req = urllib.request.Request(url.rstrip("/") + "/api/session", method="POST",
                                 data=json.dumps(session).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def get_weights(url: str) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + "/api/weights", timeout=60) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
def save(sessions: List[dict], out: str) -> str:
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "sessions.json")
    with open(path, "w") as fh:
        json.dump(sessions, fh, indent=2)
    return path


def precheck(sessions: List[dict]) -> bool:
    bad = [(s["player"]["id"], e) for s in sessions for e in check(parse(s))[0]]
    for sid, e in bad:
        print("  ✗ generated {} invalid: {}".format(sid, e))
    return not bad


def run_phase1(args) -> int:
    sessions = generate(1)
    path = save(sessions, args.out)
    n_reports = sum(len(s["bug_reports"]) for s in sessions)
    print("generated {} sessions, {} reports -> {}".format(len(sessions), n_reports, path))
    if not precheck(sessions):
        return 1
    expected, counts = expected_weights(sessions)
    failures = 0

    # Planted signal: every reported node carries exactly its type's severity.
    for t in PLAYER_TYPES:
        for n in NODES:
            if counts[t][n] and abs(expected[t][n] - PHASE1_SEVERITY[t]) > 1e-9:
                print("  ✗ planted signal lost: {} {} = {}".format(t, n, expected[t][n]))
                failures += 1
    if args.dry_run:
        print("dry run: {}".format("ok" if not failures else "FAILED"))
        return 1 if failures else 0

    with ThreadPoolExecutor(max_workers=N_SESSIONS) as pool:  # concurrent, like a lab session
        results = list(pool.map(lambda s: post(args.url, s), sessions))
    phases = {r.get("study_phase") for r in results}
    print("uploaded {} sessions (server phase: {})".format(len(results), ",".join(map(str, phases))))
    if phases != {1}:
        print("  ✗ expected phase 1 — is STUDY_PHASE set to 2?")
        return 1

    time.sleep(2)
    server = get_weights(args.url)
    if server.get("_sessions") != N_SESSIONS:
        print("  ! server weights built from {} Phase 1 sessions, expected {}.".format(
            server.get("_sessions"), N_SESSIONS))
        print("    Either other sessions are in the container (clear it), or concurrent uploads")
        print("    left stale weights (press RECOMPUTE on the admin page and rerun the check).")
        failures += 1
    for t in PLAYER_TYPES:
        for n in NODES:
            got, want = server[t].get(n), expected[t][n]
            if got is None or abs(got - want) > 1e-9:
                print("  ✗ {} {}: server {} vs expected {}".format(t, n, got, want))
                failures += 1
            got_n = (server.get("_counts") or {}).get(t, {}).get(n)
            if got_n != counts[t][n]:
                print("  ✗ {} {} count: server {} vs expected {}".format(t, n, got_n, counts[t][n]))
                failures += 1
    with open(os.path.join(args.out, "weights.json"), "w") as fh:
        json.dump(server, fh, indent=2)
    print("phase 1: {}".format("ok — server weights match exactly" if not failures
                               else "{} problems".format(failures)))
    return 1 if failures else 0


def run_phase2(args) -> int:
    before = get_weights(args.url) if not args.dry_run else None
    if args.dry_run:
        # Stand-in weights: each type values its own branches most.
        data = {t: {n: (4.0 if NODES[n].phase in OWN_BRANCHES[t] else 2.0) for n in NODES}
                for t in PLAYER_TYPES}
    else:
        data = before
    wsets = weight_sets_from_dict(data)

    # Planted relation: rating rises with CAIS under the player's own weights.
    total = {t: wsets[t].total() for t in PLAYER_TYPES}
    def rate(ptype, done):
        cais = sum(wsets[ptype].weight(n) for n in set(done))
        return max(1, min(5, 1 + int(5 * cais / total[ptype])))

    sessions = generate(2, rate)
    for s in sessions:
        s["study_phase"] = 2  # what the server will stamp; lets local checks treat them as Phase 2
    path = save(sessions, args.out)
    print("generated {} sessions, {} reports -> {}".format(
        len(sessions), sum(len(s["bug_reports"]) for s in sessions), path))
    if not precheck(sessions):
        return 1

    failures = 0
    rho = priority_vs_rating(sessions, wsets)
    shuffled = json.loads(json.dumps(sessions))
    pool_r = [r["impact_rating"] for s in shuffled for r in s["bug_reports"]]
    random.Random(99).shuffle(pool_r)
    it = iter(pool_r)
    for s in shuffled:
        for r in s["bug_reports"]:
            r["impact_rating"] = next(it)
    rho_null = priority_vs_rating(shuffled, wsets)
    print("ranking vs rating: planted ρ = {:.2f}, shuffled ρ = {:.2f}".format(rho, rho_null))
    if rho < 0.6:
        print("  ✗ planted relation not recovered")
        failures += 1
    if abs(rho_null) > 0.4:
        print("  ✗ shuffled ratings still correlate — comparison is biased")
        failures += 1
    if args.dry_run:
        print("dry run: {}".format("ok" if not failures else "FAILED"))
        return 1 if failures else 0

    for s in sessions:
        del s["study_phase"]  # the server must stamp it, not trust the client
    probe = post(args.url, sessions[0])
    if probe.get("study_phase") != 2:
        print("  ✗ server stamped phase {} — set STUDY_PHASE=2 in Azure first.".format(
            probe.get("study_phase")))
        print("    Delete blob {} (it counts as Phase 1).".format(probe.get("blob")))
        return 1
    with ThreadPoolExecutor(max_workers=N_SESSIONS) as pool:
        results = [probe] + list(pool.map(lambda s: post(args.url, s), sessions[1:]))
    print("uploaded {} sessions (server phase: {})".format(
        len(results), ",".join(sorted({str(r.get('study_phase')) for r in results}))))

    time.sleep(2)
    after = get_weights(args.url)
    strip = lambda w: {k: v for k, v in w.items() if k != "_computed_at"}
    if strip(after) != strip(before):
        print("  ✗ weights changed during Phase 2")
        failures += 1
    else:
        print("weights unchanged by Phase 2 uploads")
    print("phase 2: {}".format("ok" if not failures else "{} problems".format(failures)))
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Synthetic end-to-end test for a study phase.")
    ap.add_argument("phase", choices=["phase1", "phase2"])
    ap.add_argument("--url", help="site base URL, e.g. https://<name>.azurestaticapps.net")
    ap.add_argument("--dry-run", action="store_true", help="generate and check locally only")
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "voe-sim"),
                    help="where to write generated sessions")
    args = ap.parse_args(argv)
    if not args.dry_run and not args.url:
        ap.error("--url is required unless --dry-run")
    args.out = os.path.join(args.out, args.phase)
    return run_phase1(args) if args.phase == "phase1" else run_phase2(args)


if __name__ == "__main__":
    raise SystemExit(main())
