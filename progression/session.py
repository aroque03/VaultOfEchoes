"""Loader for study session JSON.

Target schema (vault-of-echoes.study-session/v1), per the Study Modifications
spec. Every block is optional except bug_reports or node_completions -- the
loader fills in what it can and reports what was missing rather than failing.

    {
      "schema": "vault-of-echoes.study-session/v1",
      "player":  {"id": "...", "classified_type": "explorer",
                  "questionnaire": {...}, "telemetry": {...}},
      "session": {"build": "...", "seed": 1207,
                  "started_at": "...", "ended_at": "..."},
      "node_completions": [{"node": "l1.entry", "timestamp": "...",
                            "elapsed_ms": 1234}],
      "bug_encounters":   [{"bug_id": "b1", "node": "l2.boss",
                            "reported": true, "time_to_report_ms": 8000}],
      "bug_reports":      [{"bug_id": "b1", "description": "...",
                            "gherkin": "...", "impact_rating": 4,
                            "timestamp": "...", "completed_nodes": [...]}],
      "branch_outcomes":  {"l1.room": "found", "l1.chest": "attempted",
                           "l1.boss": "never_approached"}
    }

If a report omits completed_nodes, it is reconstructed from node_completions:
every node whose timestamp is at or before the report's timestamp. Recording it
directly in the game is still preferable -- the spec asks for it explicitly, and
reconstruction depends on clocks agreeing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from model import NODES

BRANCH_OUTCOMES = ("found", "attempted", "never_approached")


@dataclass
class Session:
    player_id: str = ""
    classified_type: str = ""
    seed: Optional[int] = None
    build: str = ""
    node_completions: List[dict] = field(default_factory=list)
    bug_encounters: List[dict] = field(default_factory=list)
    bug_reports: List[dict] = field(default_factory=list)
    branch_outcomes: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def completed_nodes(self) -> List[str]:
        """Every node completed over the whole session, in completion order."""
        return [c["node"] for c in self.node_completions]

    def unreported_encounters(self) -> List[dict]:
        return [e for e in self.bug_encounters if not e.get("reported")]


def _completed_at(node_completions: List[dict], timestamp: Optional[str]) -> List[str]:
    if timestamp is None:
        return [c["node"] for c in node_completions]
    return [c["node"] for c in node_completions if str(c.get("timestamp", "")) <= timestamp]


def load(path: str) -> Session:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return parse(data)


def parse(data: Dict[str, Any]) -> Session:
    warn: List[str] = []

    schema = data.get("schema", "")
    if schema and not schema.startswith("vault-of-echoes.study-session"):
        warn.append("unexpected schema {!r}".format(schema))

    player = data.get("player", {}) or {}
    meta = data.get("session", {}) or {}

    completions = list(data.get("node_completions", []) or [])
    for c in completions:
        if c.get("node") not in NODES:
            warn.append("unknown node id {!r} in node_completions".format(c.get("node")))
    completions.sort(key=lambda c: str(c.get("timestamp", "")))

    reports = []
    for i, r in enumerate(data.get("bug_reports", []) or []):
        row = dict(r)
        if "completed_nodes" not in row:
            row["completed_nodes"] = _completed_at(completions, row.get("timestamp"))
            warn.append(
                "report {} had no completed_nodes; reconstructed {} from timestamps".format(
                    row.get("bug_id", i), len(row["completed_nodes"])
                )
            )
        unknown = [n for n in row["completed_nodes"] if n not in NODES]
        if unknown:
            warn.append(
                "report {} lists unknown nodes: {}".format(
                    row.get("bug_id", i), ", ".join(sorted(unknown))
                )
            )
        rating = row.get("impact_rating")
        if rating is not None and not (1 <= rating <= 5):
            warn.append("report {} impact_rating {} out of range 1-5".format(row.get("bug_id", i), rating))
        reports.append(row)

    outcomes = dict(data.get("branch_outcomes", {}) or {})
    for nid, val in outcomes.items():
        if val not in BRANCH_OUTCOMES:
            warn.append("branch outcome {!r} for {} not one of {}".format(val, nid, BRANCH_OUTCOMES))

    ptype = str(player.get("classified_type", "") or "").lower()

    return Session(
        player_id=str(player.get("id", "")),
        classified_type=ptype,
        seed=meta.get("seed"),
        build=str(meta.get("build", "")),
        node_completions=completions,
        bug_encounters=list(data.get("bug_encounters", []) or []),
        bug_reports=reports,
        branch_outcomes=outcomes,
        warnings=warn,
        raw=data,
    )
