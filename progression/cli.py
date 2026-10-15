"""Command line entry point.

    python3 progression/cli.py session.json --weights weights.json
    python3 progression/cli.py vault-sessions.json --weights w.json --csv out.csv   # Phase 2 table
    python3 progression/cli.py session.json --weights w.json --verify   # closed form vs enumeration
    python3 progression/cli.py session.json --weights w.json -v         # outcomes + warnings
    python3 progression/cli.py session.json --weights w.json --json     # machine-readable

Session files can be single sessions or the /api/export array (DOWNLOAD JSON).
Weights are the measured Phase 1 weights (admin DOWNLOAD WEIGHTS, or _weights.json).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import PLAYER_TYPES, load_weights  # noqa: E402
from scoring import pais_by_enumeration, prioritize, score_all_types  # noqa: E402
from session import load_all  # noqa: E402


def score_reports(sess, wsets, verify=False):
    rows = []
    for rep in sess.bug_reports:
        done = rep.get("completed_nodes", [])
        scores = score_all_types(done, wsets)
        if verify:
            for t, ws in wsets.items():
                exact = pais_by_enumeration(done, ws)
                if abs(exact - scores[t]["pais"]) > 1e-9:
                    raise AssertionError(
                        "PAIS mismatch for {} on {}: {} vs {}".format(
                            t, rep.get("bug_id"), scores[t]["pais"], exact))
        rows.append({"bug_id": rep.get("bug_id"), "chamber": rep.get("chamber"),
                     "impact_rating": rep.get("impact_rating"),
                     "description": rep.get("description", ""), "scores": scores})
    return rows


def write_csv(path, sessions, wsets):
    """One row per bug report: identifiers, the player's rating, CAIS/PAIS under each type."""
    cols = ["source", "player_id", "study_phase", "classified_type", "bug_id", "chamber",
            "impact_rating", "completed_count"]
    for t in PLAYER_TYPES:
        cols += ["cais_" + t, "pais_" + t]
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for sess in sessions:
            for row in score_reports(sess, wsets):
                line = [sess.source, sess.player_id, sess.study_phase, sess.classified_type,
                        row["bug_id"], row["chamber"], row["impact_rating"],
                        row["scores"][PLAYER_TYPES[0]]["completed_count"]]
                for t in PLAYER_TYPES:
                    line += [row["scores"][t]["cais"], round(row["scores"][t]["pais"], 4)]
                w.writerow(line)
                n += 1
    return n


def print_session(sess, wsets, rows, verbose):
    own = sess.classified_type if sess.classified_type in PLAYER_TYPES else None
    ranked = prioritize(sess.bug_reports, wsets[own]) if own else []

    unrep = len(sess.unreported_encounters())
    print("{} · phase {} · {} · seed {} · {} nodes · {} reports{}".format(
        sess.player_id or "(no id)", sess.study_phase, sess.classified_type or "(unclassified)",
        sess.seed if sess.seed is not None else "-",
        len(sess.node_completions), len(sess.bug_reports),
        " · {} unreported".format(unrep) if unrep else ""))

    w = max([10] + [len(str(r["bug_id"])) for r in rows])
    print()
    print("{:<{w}} {:>2} {:>2} {:>12} {:>12} {:>12}".format(
        "bug", "ch", "r", *PLAYER_TYPES, w=w))
    for row in rows:
        line = "{:<{w}} {:>2} {:>2}".format(
            str(row["bug_id"]), row["chamber"] if row["chamber"] is not None else "-",
            row["impact_rating"] if row["impact_rating"] is not None else "-", w=w)
        for t in PLAYER_TYPES:
            s = row["scores"][t]
            line += " {:>12}".format("{:.1f}/{:.1f}".format(s["cais"], s["pais"]))
        print(line)

    if ranked:
        print()
        print("priority ({}): ".format(own) + " > ".join(
            "{} ({:.1f}/{:.1f})".format(r.get("bug_id"), r["cais"], r["pais"])
            for r in ranked))

    if verbose and sess.branch_outcomes:
        print()
        for k, val in sorted(sess.branch_outcomes.items()):
            print("  {:<12} {}".format(k, val))

    if sess.warnings:
        print()
        if verbose:
            for warning in sess.warnings:
                print("  ! " + warning)
        else:
            print("{} warning{} (-v to show)".format(
                len(sess.warnings), "s" if len(sess.warnings) != 1 else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compute CAIS/PAIS for study sessions.")
    ap.add_argument("sessions", nargs="+", help="session JSON file(s) or /api/export file")
    ap.add_argument("--weights", required=True, help="measured weights JSON")
    ap.add_argument("--csv", metavar="PATH", help="write one row per bug report to PATH")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--verify", action="store_true",
                    help="cross-check closed-form PAIS against path enumeration")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show branch outcomes and warning detail")
    args = ap.parse_args(argv)

    wsets = load_weights(args.weights)
    sessions = [s for path in args.sessions for s in load_all(path)]

    if args.csv:
        n = write_csv(args.csv, sessions, wsets)
        print("{} reports from {} sessions -> {}".format(n, len(sessions), args.csv))
        return 0

    if args.json:
        out = []
        for sess in sessions:
            own = sess.classified_type if sess.classified_type in PLAYER_TYPES else None
            ranked = prioritize(sess.bug_reports, wsets[own]) if own else []
            out.append({
                "source": sess.source, "player_id": sess.player_id,
                "study_phase": sess.study_phase, "classified_type": sess.classified_type,
                "reports": score_reports(sess, wsets, args.verify),
                "ranking": [{"rank": r["rank"], "bug_id": r.get("bug_id"),
                             "cais": r["cais"], "pais": r["pais"]} for r in ranked],
                "warnings": sess.warnings,
            })
        print(json.dumps(out[0] if len(out) == 1 else out, indent=2))
        return 0

    for i, sess in enumerate(sessions):
        if i:
            print("\n" + "-" * 60 + "\n")
        print_session(sess, wsets, score_reports(sess, wsets, args.verify), args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
