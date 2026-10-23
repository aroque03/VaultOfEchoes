"""Loader for study session JSON.

Reads the schema the game uploads (vault-of-echoes.study-session/v1, built by
buildSession() in js/progression.js). Fields it uses:

    {
      "schema": "vault-of-echoes.study-session/v1",
      "study_phase": 1,                       # stamped by api/session
      "player":  {"id": "...", "name": "...", "email": "..."},
      "session": {"build": "...", "seed": 1207, "started_at": "...", "ended_at": "..."},
      "progression_graph": {
        "node_completions": [{"node": "l1.entry", "timestamp": "...", "elapsed_ms": 1234}],
        "branch_outcomes":  {"l1.room": "found", "l1.chest": "attempted",
                             "l1.boss": "never_approached"}
      },
      "player_classification": {"player_type": {"dominant": "explorer", ...}},
      "bug_encounters": [{"type": "wallClip", "node": "l1.entry", ...}],
      "bug_reports":    [{"bug_id": "b-1-l1", "impact_rating": 4, "chamber": 1,
                          "timestamp": "...", "completed_nodes": [...]}]
    }

Top-level node_completions / branch_outcomes and player.classified_type are
also accepted. Every block is optional -- the loader fills in what it can and
reports what was missing rather than failing. load_all() also reads the
/api/export file, which is a JSON array of sessions.

If a report omits completed_nodes, it is reconstructed from node_completions:
every node whose timestamp is at or before the report's timestamp. Recording it
directly in the game is still preferable -- reconstruction depends on clocks
agreeing.
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
    study_phase: int = 1
    source: str = ""
    classified_type: str = ""
    self_reported_type: str = ""  # the player's own answer after chamber 3 ("" if none)
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
        # Only encounters that carry a reported flag can be judged; the game does not set it yet.
        return [e for e in self.bug_encounters if e.get("reported") is False]


def _completed_at(node_completions: List[dict], timestamp: Optional[str]) -> List[str]:
    if timestamp is None:
        return [c["node"] for c in node_completions]
    return [c["node"] for c in node_completions if str(c.get("timestamp", "")) <= timestamp]


def load(path: str) -> Session:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return parse(data)


def load_all(path: str) -> List[Session]:
    """Load a single session file or an /api/export array of sessions."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    items = data if isinstance(data, list) else [data]
    sessions = [parse(d) for d in items]
    for i, sess in enumerate(sessions):
        sess.source = str(items[i].get("_blob") or path)
    return sessions


def parse(data: Dict[str, Any]) -> Session:
    warn: List[str] = []

    schema = data.get("schema", "")
    if schema and not schema.startswith("vault-of-echoes.study-session"):
        warn.append("unexpected schema {!r}".format(schema))

    player = data.get("player", {}) or {}
    meta = data.get("session", {}) or {}
    graph = data.get("progression_graph", {}) or {}

    completions = list(graph.get("node_completions") or data.get("node_completions") or [])
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

    outcomes = dict(graph.get("branch_outcomes") or data.get("branch_outcomes") or {})
    for nid, val in outcomes.items():
        if val not in BRANCH_OUTCOMES:
            warn.append("branch outcome {!r} for {} not one of {}".format(val, nid, BRANCH_OUTCOMES))

    pc = data.get("player_classification", {}) or {}
    classification = pc.get("player_type", {}) or {}
    self_reported = str((pc.get("self_reported") or {}).get("type") or "").lower()
    ptype = str(classification.get("dominant") or player.get("classified_type") or "").lower()

    return Session(
        player_id=str(player.get("id", "")),
        study_phase=2 if data.get("study_phase") == 2 else 1,
        self_reported_type=self_reported,
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
