"""Consistency checks for study session data.

    python3 progression/validate.py vault-sessions.json        # export from the admin page
    python3 progression/validate.py session.json -v            # list every finding

Errors mean the data contradicts how the game is supposed to record it; warnings
are things worth a look (incomplete runs, reconstructed fields). Exit code is 1
if any session has errors.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import LEVELS, NODES, PLAYER_TYPES, node_id  # noqa: E402
from session import BRANCH_OUTCOMES, Session, load_all  # noqa: E402

# Expected bug placement: bug -> (node phase, chambers). Mirrors BUG_CATALOG in
# js/config.js, i.e. the agreed study table. Keep the two in sync.
BUG_TABLE: Dict[str, Tuple[str, Tuple[int, ...]]] = {
    "wallClip":    ("entry", (1, 2, 3)),
    "phantomWall": ("room",  (1, 3)),
    "missingNote": ("room",  (1, 2)),
    "phantomGem":  ("chest", (2,)),
    "corruptNote": ("chest", (3,)),
    "undeadBoss":  ("boss",  (2, 3)),
    "fakeHeal":    ("key",   (2, 3)),
    "stuckKey":    ("key",   (3,)),
}


def expected_bugs(chamber: int) -> List[str]:
    return sorted(b for b, (_, lv) in BUG_TABLE.items() if chamber in lv)


def level_of(nid: str) -> int:
    return NODES[nid].level


def check(sess: Session) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = list(sess.warnings)
    raw = sess.raw

    # --- identity / metadata ---
    if not sess.player_id:
        errors.append("missing player.id")
    if "study_phase" not in raw:
        warnings.append("no study_phase (stored before phases existed; counted as 1)")
    meta = raw.get("session", {}) or {}
    started, ended = meta.get("started_at"), meta.get("ended_at")
    if not started or not ended:
        errors.append("missing session.started_at / ended_at")
    elif str(ended) < str(started):
        errors.append("session ended before it started")
    if sess.classified_type not in PLAYER_TYPES:
        errors.append("player type {!r} is not one of {}".format(
            sess.classified_type, ", ".join(PLAYER_TYPES)))

    # --- node completions form a valid path ---
    raw_completions = ((raw.get("progression_graph") or {}).get("node_completions")
                       or raw.get("node_completions") or [])
    timeline: List[Tuple[str, str]] = []  # (node, timestamp) in recorded order
    seen = set()
    prev_ts, prev_ms = "", -1
    for c in raw_completions:
        nid = c.get("node")
        if nid not in NODES:
            continue  # already reported by the loader
        if nid in seen:
            errors.append("{} completed twice".format(nid))
        ts, ms = str(c.get("timestamp", "")), c.get("elapsed_ms")
        if ts < prev_ts:
            errors.append("{} timestamp goes backwards".format(nid))
        if isinstance(ms, (int, float)):
            if ms < prev_ms:
                errors.append("{} elapsed_ms goes backwards".format(nid))
            prev_ms = ms
        prev_ts = ts
        lv = level_of(nid)
        phase = NODES[nid].phase
        if phase != "entry" and node_id(lv, "entry") not in seen:
            errors.append("{} completed before its chamber's entry".format(nid))
        if phase == "exit" and node_id(lv, "key") not in seen:
            errors.append("{} completed without the key".format(nid))
        if phase == "entry" and lv > 1 and node_id(lv - 1, "exit") not in seen:
            errors.append("{} reached without leaving chamber {}".format(nid, lv - 1))
        seen.add(nid)
        timeline.append((nid, ts))
    if node_id(LEVELS[-1], "exit") not in seen:
        reached = max([level_of(n) for n in seen] or [0])
        warnings.append("incomplete run (reached chamber {})".format(reached))

    # --- branch outcomes agree with completions ---
    for nid, outcome in sess.branch_outcomes.items():
        if nid not in NODES or outcome not in BRANCH_OUTCOMES:
            continue  # already reported by the loader
        if outcome == "found" and nid not in seen:
            errors.append("{} outcome 'found' but node never completed".format(nid))
        if outcome != "found" and nid in seen:
            errors.append("{} completed but outcome is {!r}".format(nid, outcome))
    for nid in seen:
        if not NODES[nid].mandatory and nid not in sess.branch_outcomes:
            errors.append("{} completed but has no branch outcome".format(nid))

    # --- injected bug configuration ---
    injected = raw.get("injectedConfig")
    if injected is None:
        warnings.append("no injectedConfig")
    else:
        for lv in LEVELS:
            got = sorted(injected.get(str(lv), injected.get(lv, [])) or [])
            if got != expected_bugs(lv):
                errors.append("chamber {} injected {} (expected {})".format(
                    lv, ",".join(got) or "none", ",".join(expected_bugs(lv))))

    # --- bug encounters happen only where bugs were placed ---
    enc_seen = set()
    for e in sess.bug_encounters:
        bug, nid, ch = e.get("type"), e.get("node"), e.get("chamber")
        if bug is None:
            continue  # non-game format, nothing to check
        if bug not in BUG_TABLE:
            errors.append("encounter of unknown bug {!r}".format(bug))
            continue
        phase, chambers = BUG_TABLE[bug]
        if ch not in chambers:
            errors.append("{} encountered in chamber {} (placed in {})".format(
                bug, ch, ",".join(map(str, chambers))))
        if not isinstance(ch, int) or nid != node_id(ch, phase):
            errors.append("{} encounter at {} (expected {}.{})".format(
                bug, nid, "l{}".format(ch), phase))
        if (bug, nid) in enc_seen:
            errors.append("{} at {} recorded twice".format(bug, nid))
        enc_seen.add((bug, nid))

    # --- bug reports ---
    for i, r in enumerate(sess.bug_reports):
        rid = r.get("bug_id", "#{}".format(i + 1))
        rating = r.get("impact_rating")
        if rating is None:
            errors.append("report {} has no impact_rating".format(rid))
        completed = r.get("completed_nodes", [])
        ts = r.get("timestamp")
        if ts is not None:
            expected = [n for n, t in timeline if t <= str(ts)]
            if completed != expected:
                errors.append("report {} completed_nodes don't match completions up to its timestamp".format(rid))
        ch = r.get("chamber")
        if completed and isinstance(ch, int):
            last_lv = level_of(completed[-1]) if completed[-1] in NODES else None
            if last_lv is not None and last_lv != ch:
                warnings.append("report {} filed in chamber {} but last node is in chamber {}".format(
                    rid, ch, last_lv))
        inj = r.get("injectedBugs")
        if inj is not None and isinstance(ch, int) and sorted(inj) != expected_bugs(ch):
            errors.append("report {} lists injected bugs {} for chamber {}".format(
                rid, ",".join(sorted(inj)) or "none", ch))

    return errors, warnings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check study sessions for consistency.")
    ap.add_argument("sessions", nargs="+", help="session JSON file(s) or /api/export file")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every finding")
    args = ap.parse_args(argv)

    sessions = [s for path in args.sessions for s in load_all(path)]
    bad = 0
    for sess in sessions:
        errors, warnings = check(sess)
        bad += bool(errors)
        status = "FAIL" if errors else "ok  "
        print("{} {} · {} · phase {} · {} errors, {} warnings".format(
            status, sess.source, sess.classified_type or "?", sess.study_phase,
            len(errors), len(warnings)))
        if args.verbose:
            for e in errors:
                print("     ✗ " + e)
            for w in warnings:
                print("     ! " + w)
    print("{} sessions, {} with errors".format(len(sessions), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
