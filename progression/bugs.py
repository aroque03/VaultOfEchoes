"""Bug coding sheet: which bug each report is about.

    python3 progression/bugs.py export vault-sessions.json --out bug-coding.csv
    python3 progression/bugs.py export vault-sessions.json --out bug-coding.csv --labels bug-coding.csv
    python3 progression/bugs.py summary bug-coding.csv

    python3 progression/bugs.py planted          # the Planted Bug IDs to code against

A report doesn't record which bug it describes. The coding sheet has one row per
report; researchers read each description and fill `bug_label`:
  - the Planted Bug ID it matches (e.g. PB-L2-GEM), when it describes a planted bug;
  - otherwise a short new label, the same one for every report that means the same
    thing (that is the merge).
A blank label leaves the report out of the bug-level analysis.

`inferred_planted_id` is metadata only: the planted bug of the last encounter logged in
the same chamber before the report, with `seconds_after_encounter`. It helps the coder
and cross-checks the labels (`summary`), but never sets them. The game logs only the
first encounter of each bug at each node, so a later repeat of a bug isn't seen.

`--labels` carries labels over from an earlier sheet by `report_key`, so the sheet can
be re-exported as more sessions arrive without losing coding work.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session import Session, load_all  # noqa: E402
from validate import BUG_TABLE, planted_bug_id, planted_bugs  # noqa: E402

COLUMNS = ["report_key", "player_id", "study_phase", "player_type", "chamber", "bug_id", "timestamp",
           "category", "impact_rating", "last_completed", "injected_bugs", "inferred_planted_id",
           "seconds_after_encounter", "description", "bug_label"]


def report_key(sess: Session, index: int, report: dict) -> str:
    """Stable id for a report: its session (blob name in an export) + its bug id."""
    return "{}#{}".format(sess.source, report.get("bug_id") or index + 1)


def _when(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def infer_bug(sess: Session, report: dict) -> Tuple[str, str]:
    """Planted Bug ID of the last encounter in the report's chamber at or before it, and seconds since."""
    ts, chamber = report.get("timestamp"), report.get("chamber")
    best = None
    for e in sess.bug_encounters:
        if e.get("type") is None or e.get("chamber") != chamber:
            continue
        if ts is not None and str(e.get("timestamp", "")) > str(ts):
            continue
        if best is None or str(e.get("timestamp", "")) >= str(best.get("timestamp", "")):
            best = e
    if best is None:
        return "", ""
    a, b = _when(best.get("timestamp")), _when(ts)
    gap = "" if a is None or b is None else str(int((b - a).total_seconds()))
    pid = best.get("planted_id")  # older sessions predate the field: derive it
    if not pid and best["type"] in BUG_TABLE and isinstance(chamber, int):
        pid = planted_bug_id(best["type"], chamber)
    return pid or best["type"], gap


def rows(sessions: List[Session], phase: Optional[int]) -> List[Dict[str, str]]:
    out = []
    for sess in sessions:
        if phase is not None and sess.study_phase != phase:
            continue
        for i, r in enumerate(sess.bug_reports):
            done = r.get("completed_nodes") or []
            inferred, gap = infer_bug(sess, r)
            out.append({
                "report_key": report_key(sess, i, r), "player_id": sess.player_id,
                "study_phase": str(sess.study_phase), "player_type": sess.classified_type,
                "chamber": str(r.get("chamber", "")), "bug_id": str(r.get("bug_id", "")),
                "timestamp": str(r.get("timestamp", "")), "category": str(r.get("category", "")),
                "impact_rating": str(r.get("impact_rating", "")), "last_completed": done[-1] if done else "",
                "injected_bugs": " ".join(r.get("injectedBugs") or []), "inferred_planted_id": inferred,
                "seconds_after_encounter": gap, "description": str(r.get("description", "")),
                "bug_label": "",
            })
    return out


def load_labels(path: str) -> Dict[str, str]:
    """report_key -> bug_label, for rows with a non-blank label."""
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["report_key"]: r["bug_label"].strip() for r in csv.DictReader(fh)
                if r.get("bug_label", "").strip()}


def export(sessions: List[Session], out_path: str, phase: Optional[int], labels_path: Optional[str]) -> Tuple[int, int]:
    previous = load_labels(labels_path) if labels_path and os.path.exists(labels_path) else {}
    data = rows(sessions, phase)
    for r in data:
        r["bug_label"] = previous.get(r["report_key"], "")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(data)
    return len(data), sum(1 for r in data if r["bug_label"])


def summary(path: str) -> None:
    """Each label against the encounter-based guesses, to catch coding slips."""
    with open(path, newline="", encoding="utf-8") as fh:
        data = list(csv.DictReader(fh))
    labelled = [r for r in data if r["bug_label"].strip()]
    planted = {p[0] for p in planted_bugs()}
    labels = {r["bug_label"].strip() for r in labelled}
    agree = sum(1 for r in labelled if r["bug_label"].strip() == r["inferred_planted_id"])
    print("{} reports · {} labelled · {} labels ({} planted, {} new) · label = inferred in {}/{}".format(
        len(data), len(labelled), len(labels), len(labels & planted), len(labels - planted), agree, len(labelled)))
    table: Dict[str, Dict[str, int]] = {}
    for r in labelled:
        row = table.setdefault(r["bug_label"].strip(), {})
        guess = r["inferred_planted_id"] or "(no encounter)"
        row[guess] = row.get(guess, 0) + 1
    for label in sorted(table):
        guesses = ", ".join("{} {}".format(g, n) for g, n in sorted(table[label].items(), key=lambda x: -x[1]))
        print("  {:28} {}".format(label[:28], guesses))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bug coding sheet for reports.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write the coding sheet")
    ex.add_argument("sessions", nargs="+", help="session JSON file(s) or /api/export file")
    ex.add_argument("--out", required=True, help="CSV to write")
    ex.add_argument("--labels", help="earlier sheet whose bug_label values to keep")
    ex.add_argument("--phase", type=int, default=2, help="study phase to export (default 2; 0 = all)")
    sm = sub.add_parser("summary", help="labels against encounter guesses")
    sm.add_argument("sheet", help="coding sheet CSV")
    sub.add_parser("planted", help="list the Planted Bug IDs")
    args = ap.parse_args(argv)

    if args.cmd == "planted":
        for pid, bug, chamber, node in planted_bugs():
            print("{:14} {:16} chamber {}  {}".format(pid, bug, chamber, node))
        return 0
    if args.cmd == "export":
        sessions = [s for path in args.sessions for s in load_all(path)]
        n, kept = export(sessions, args.out, args.phase or None, args.labels)
        print("{} reports -> {} ({} labels kept)".format(n, args.out, kept))
    else:
        summary(args.sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
