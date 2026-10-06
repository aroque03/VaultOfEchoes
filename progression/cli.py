"""Command line entry point.

    python3 progression/cli.py fixtures/sample-session.json
    python3 progression/cli.py session.json --asymmetric   # sensitivity weights
    python3 progression/cli.py session.json --verify       # closed form vs enumeration
    python3 progression/cli.py session.json -v             # outcomes + warnings
    python3 progression/cli.py session.json --json         # machine-readable

Weight sets live in model.py and are editable without touching anything here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model import PLAYER_TYPES, all_weight_sets  # noqa: E402
from scoring import pais_by_enumeration, prioritize, score_all_types  # noqa: E402
from session import load  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compute CAIS/PAIS for a study session.")
    ap.add_argument("session", help="path to a session JSON file")
    ap.add_argument("--asymmetric", action="store_true",
                    help="use the asymmetric sensitivity weight sets")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--verify", action="store_true",
                    help="cross-check closed-form PAIS against path enumeration")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show branch outcomes and warning detail")
    args = ap.parse_args(argv)

    sess = load(args.session)
    wsets = all_weight_sets(asymmetric=args.asymmetric)
    label = "asymmetric" if args.asymmetric else "symmetric"

    rows = []
    for rep in sess.bug_reports:
        done = rep.get("completed_nodes", [])
        scores = score_all_types(done, wsets)
        if args.verify:
            for t, ws in wsets.items():
                exact = pais_by_enumeration(done, ws)
                if abs(exact - scores[t]["pais"]) > 1e-9:
                    raise AssertionError(
                        "PAIS mismatch for {} on {}: {} vs {}".format(
                            t, rep.get("bug_id"), scores[t]["pais"], exact))
        rows.append({"bug_id": rep.get("bug_id"), "node": rep.get("node"),
                     "impact_rating": rep.get("impact_rating"),
                     "description": rep.get("description", ""), "scores": scores})

    own = sess.classified_type if sess.classified_type in PLAYER_TYPES else None
    ranked = prioritize(sess.bug_reports, wsets[own]) if own else []

    if args.json:
        print(json.dumps({
            "player_id": sess.player_id, "classified_type": sess.classified_type,
            "weight_set": label, "reports": rows,
            "ranking": [{"rank": r["rank"], "bug_id": r.get("bug_id"),
                         "cais": r["cais"], "pais": r["pais"]} for r in ranked],
            "warnings": sess.warnings,
        }, indent=2))
        return 0

    unrep = len(sess.unreported_encounters())
    print("{} · {} · seed {} · {} · {} nodes · {} reports{}".format(
        sess.player_id or "(no id)", sess.classified_type or "(unclassified)",
        sess.seed if sess.seed is not None else "-", label,
        len(sess.node_completions), len(sess.bug_reports),
        " · {} unreported".format(unrep) if unrep else ""))

    w = max([10] + [len(str(r["bug_id"])) for r in rows])
    print()
    print("{:<{w}} {:<8} {:>2} {:>10} {:>10} {:>10}".format(
        "bug", "node", "r", *PLAYER_TYPES, w=w))
    for row in rows:
        line = "{:<{w}} {:<8} {:>2}".format(
            str(row["bug_id"]), str(row["node"] or ""),
            row["impact_rating"] if row["impact_rating"] is not None else "-", w=w)
        for t in PLAYER_TYPES:
            s = row["scores"][t]
            line += " {:>10}".format("{:.0f}/{:.1f}".format(s["cais"], s["pais"]))
        print(line)

    if ranked:
        print()
        print("priority ({}): ".format(own) + " > ".join(
            "{} ({:.0f}/{:.1f})".format(r.get("bug_id"), r["cais"], r["pais"])
            for r in ranked))

    if args.verbose and sess.branch_outcomes:
        print()
        for k, val in sorted(sess.branch_outcomes.items()):
            print("  {:<10} {}".format(k, val))

    if sess.warnings:
        print()
        if args.verbose:
            for warning in sess.warnings:
                print("  ! " + warning)
        else:
            print("{} warning{} (-v to show)".format(
                len(sess.warnings), "s" if len(sess.warnings) != 1 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
