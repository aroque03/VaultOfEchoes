"""Validation for the progression model.

Run:  python3 -m unittest discover -s progression/tests -t progression -v
"""

from __future__ import annotations

import csv
import itertools
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

from model import (  # noqa: E402
    BRANCH_NODES,
    EDGES,
    END,
    NODES,
    PLAYER_TYPES,
    SPINE_NODES,
    START,
    WeightSet,
    load_weights,
    weight_sets_from_dict,
)
from scoring import (  # noqa: E402
    cais,
    pais,
    pais_by_enumeration,
    prioritize,
    reachable_nodes,
    remaining_paths,
)
from session import load_all, parse  # noqa: E402
import cli  # noqa: E402
import validate  # noqa: E402

SAMPLE_WEIGHTS = os.path.join(PKG, "fixtures", "sample-weights.json")
SAMPLE_SESSION = os.path.join(PKG, "fixtures", "sample-session.json")

# Hand-checkable weights: spine 2, room 4, chest 3, boss 1, greenBoss 1.5.
PHASE_W = {"entry": 2.0, "key": 2.0, "exit": 2.0,
           "room": 4.0, "chest": 3.0, "boss": 1.0, "greenBoss": 1.5}
SIMPLE = WeightSet("explorer", {n: PHASE_W[v.phase] for n, v in NODES.items()})


def sample_sets():
    return load_weights(SAMPLE_WEIGHTS)


class TestNodeModel(unittest.TestCase):
    def test_counts_match_the_game(self):
        self.assertEqual(len(NODES), 19)
        self.assertEqual(len(SPINE_NODES), 9)
        self.assertEqual(len(BRANCH_NODES), 10)

    def test_node_ids_match_the_game_dag(self):
        # Same ids as DAG_EDGES in js/progression.js and api/shared/weights.js.
        expected = {"l{}.{}".format(lv, p) for lv in (1, 2)
                    for p in ("entry", "room", "chest", "boss", "key", "exit")}
        expected |= {"l3." + p for p in
                     ("entry", "room", "chest", "boss", "greenBoss", "key", "exit")}
        self.assertEqual(set(NODES), expected)

    def test_green_boss_is_a_killer_branch(self):
        self.assertFalse(NODES["l3.greenBoss"].mandatory)
        self.assertEqual(NODES["l3.greenBoss"].player_type, "killer")

    def test_edges_form_a_dag_from_start_to_end(self):
        seen, stack = set(), [START]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(EDGES[n])
        self.assertEqual(seen, set(NODES) | {START, END})


class TestWeights(unittest.TestCase):
    def test_loads_sample_file_with_counts(self):
        sets = sample_sets()
        self.assertEqual(set(sets), set(PLAYER_TYPES))
        self.assertEqual(sets["explorer"].weight("l1.room"), 4.5)
        self.assertEqual(sets["killer"].counts["l3.greenBoss"], 4)

    def test_accepts_weights_without_counts(self):
        data = {t: {n: 1 for n in NODES} for t in PLAYER_TYPES}
        sets = weight_sets_from_dict(data)
        self.assertIsNone(sets["achiever"].counts)

    def test_missing_nodes_are_rejected(self):
        partial = {n: 1 for n in NODES if n != "l3.greenBoss"}
        with self.assertRaises(ValueError) as ctx:
            WeightSet("explorer", partial)
        self.assertIn("l3.greenBoss", str(ctx.exception))

    def test_ignores_extra_keys_like_metadata(self):
        data = {t: {n: 2 for n in NODES} for t in PLAYER_TYPES}
        data["_computed_at"] = "2026-10-14T00:00:00Z"
        data["explorer"]["l2.nav"] = 99  # stale node from an old model
        self.assertEqual(weight_sets_from_dict(data)["explorer"].total(), 2 * 19)


class TestReachability(unittest.TestCase):
    def test_skipped_branches_are_lost_once_a_level_closes(self):
        done = ["l1.entry", "l1.key", "l1.exit"]
        reach = reachable_nodes(done)
        self.assertNotIn("l1.room", reach, "level 1 branches survived its exit")
        self.assertNotIn("l1.chest", reach)
        self.assertIn("l2.room", reach)
        self.assertEqual(len(reach), 13)

    def test_open_level_keeps_all_its_incomplete_nodes(self):
        # Branch completed out of enumeration-chain order: chest before room.
        done = ["l1.entry", "l1.chest"]
        self.assertIn("l1.room", reachable_nodes(done))

    def test_nothing_reachable_once_finished(self):
        every = list(NODES)
        self.assertEqual(reachable_nodes(every), ())
        self.assertEqual(pais(every, SIMPLE), 0.0)
        self.assertEqual(cais(every, SIMPLE), SIMPLE.total())


class TestPAIS(unittest.TestCase):
    """The closed form is the claim under test; enumeration is ground truth."""

    def _states(self):
        """A spread of realistic progression states."""
        order = [
            "l1.entry", "l1.room", "l1.chest", "l1.boss", "l1.key", "l1.exit",
            "l2.entry", "l2.boss", "l2.key", "l2.exit",
            "l3.entry", "l3.greenBoss", "l3.room", "l3.key", "l3.exit",
        ]
        return [order[:i] for i in range(len(order) + 1)]

    def test_closed_form_matches_enumeration(self):
        for ws in list(sample_sets().values()) + [SIMPLE]:
            for done in self._states():
                self.assertAlmostEqual(
                    pais(done, ws), pais_by_enumeration(done, ws), places=9,
                    msg="{} after {} nodes".format(ws.player_type, len(done)),
                )

    def test_closed_form_matches_enumeration_on_every_level3_subset(self):
        """Exhaustive over level 3: all 16 branch subsets, key found or not."""
        ws = sample_sets()["killer"]
        opened = ["l1.entry", "l1.key", "l1.exit", "l2.entry", "l2.key", "l2.exit", "l3.entry"]
        branches = ["l3.room", "l3.chest", "l3.boss", "l3.greenBoss"]
        for k in range(5):
            for subset in itertools.combinations(branches, k):
                for tail in ([], ["l3.key"]):
                    done = opened + list(subset) + tail
                    self.assertAlmostEqual(
                        pais(done, ws), pais_by_enumeration(done, ws), places=9
                    )

    def test_path_count_is_one_per_subset_not_per_ordering(self):
        # Fresh run: 3 + 3 + 4 optional branches = 2^10 completion subsets.
        self.assertEqual(len(remaining_paths([])), 1024)
        # Level 1 closed: 3 + 4 branches left.
        self.assertEqual(len(remaining_paths(["l1.entry", "l1.key", "l1.exit"])), 128)

    def test_every_optional_node_lies_on_exactly_half_the_paths(self):
        paths = remaining_paths([])
        for nid in BRANCH_NODES:
            hits = sum(1 for p in paths if nid in p)
            self.assertEqual(hits, len(paths) // 2, nid)

    def test_pais_is_monotonically_non_increasing(self):
        for ws in sample_sets().values():
            vals = [pais(d, ws) for d in self._states()]
            for a, b in zip(vals, vals[1:]):
                self.assertLessEqual(b, a)

    def test_cais_plus_pais_bounds(self):
        """A player can never have banked plus expect more than the maximum."""
        for ws in sample_sets().values():
            for done in self._states():
                self.assertLessEqual(cais(done, ws) + pais(done, ws), ws.total() + 1e-9)


class TestWorkedExample(unittest.TestCase):
    """Pinned by hand with SIMPLE weights so the numbers cannot drift.

    Done: l1 spine (2+2+2) + l2.entry (2) + l2.room (4)            -> CAIS 12
    Left: L1 closed. Mandatory l2.key, l2.exit, l3 entry/key/exit -> 10
          Optional l2 chest 3, boss 1; l3 room 4, chest 3, boss 1, greenBoss 1.5
          -> 13.5 / 2 = 6.75                                       -> PAIS 16.75
    """

    DONE = ["l1.entry", "l1.key", "l1.exit", "l2.entry", "l2.room"]

    def test_values(self):
        self.assertEqual(cais(self.DONE, SIMPLE), 12)
        self.assertAlmostEqual(pais(self.DONE, SIMPLE), 16.75, places=9)
        self.assertAlmostEqual(pais_by_enumeration(self.DONE, SIMPLE), 16.75, places=9)


class TestPrioritisation(unittest.TestCase):
    def test_sorts_by_cais_then_pais_descending(self):
        reports = [
            {"bug_id": "late", "completed_nodes": ["l1.entry", "l1.key", "l1.exit", "l2.entry"]},
            {"bug_id": "early", "completed_nodes": ["l1.entry"]},
            {"bug_id": "mid", "completed_nodes": ["l1.entry", "l1.key"]},
        ]
        ranked = prioritize(reports, SIMPLE)
        self.assertEqual([r["bug_id"] for r in ranked], ["late", "mid", "early"])

    def test_pais_breaks_cais_ties(self):
        """Equal CAIS, different futures.

        Both players have 6 banked. The rusher took the key and left, burning
        level 1's branches for good; the wanderer is still inside level 1 with
        everything ahead. Equal CAIS, so PAIS decides -- and the wanderer, who
        stands to lose more, outranks the rusher.
        """
        rusher = {"bug_id": "rusher", "completed_nodes": ["l1.entry", "l1.key", "l1.exit"]}
        wanderer = {"bug_id": "wanderer", "completed_nodes": ["l1.entry", "l1.room"]}
        ranked = prioritize([rusher, wanderer], SIMPLE)
        self.assertEqual(ranked[0]["cais"], ranked[1]["cais"], "fixture no longer ties on CAIS")
        self.assertEqual(ranked[0]["cais"], 6)
        self.assertGreater(ranked[0]["pais"], ranked[1]["pais"])
        self.assertEqual(ranked[0]["bug_id"], "wanderer")


class TestSessionLoader(unittest.TestCase):
    def test_reads_the_game_schema(self):
        sess = load_all(SAMPLE_SESSION)[0]
        self.assertEqual(sess.player_id, "P07")
        self.assertEqual(sess.classified_type, "explorer")
        self.assertEqual(sess.study_phase, 2)
        self.assertEqual(len(sess.node_completions), 12)
        self.assertEqual(sess.branch_outcomes["l3.greenBoss"], "never_approached")

    def test_reads_an_export_array(self):
        with open(SAMPLE_SESSION) as fh:
            one = json.load(fh)
        legacy = dict(one)
        del legacy["study_phase"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([dict(one, _blob="a/1.json"), dict(legacy, _blob="b/1.json")], fh)
        try:
            sessions = load_all(fh.name)
        finally:
            os.unlink(fh.name)
        self.assertEqual([s.source for s in sessions], ["a/1.json", "b/1.json"])
        self.assertEqual([s.study_phase for s in sessions], [2, 1], "missing phase must mean 1")

    def test_reconstructs_completed_nodes_from_timestamps(self):
        data = {
            "schema": "vault-of-echoes.study-session/v1",
            "progression_graph": {"node_completions": [
                {"node": "l1.entry", "timestamp": "2026-09-23T10:00:00Z"},
                {"node": "l1.room", "timestamp": "2026-09-23T10:05:00Z"},
                {"node": "l1.key", "timestamp": "2026-09-23T10:20:00Z"},
            ]},
            "bug_reports": [{"bug_id": "b1", "timestamp": "2026-09-23T10:06:00Z"}],
        }
        sess = parse(data)
        self.assertEqual(sess.bug_reports[0]["completed_nodes"], ["l1.entry", "l1.room"])
        self.assertTrue(any("reconstructed" in w for w in sess.warnings))

    def test_flags_unknown_nodes_and_bad_ratings(self):
        sess = parse({
            "node_completions": [{"node": "l1.nav", "timestamp": "x"}],
            "bug_reports": [{"bug_id": "b1", "impact_rating": 7, "completed_nodes": ["nope"]}],
        })
        joined = " ".join(sess.warnings)
        self.assertIn("unknown node id", joined)
        self.assertIn("out of range", joined)
        self.assertIn("unknown nodes", joined)

    def test_counts_only_explicitly_unreported_encounters(self):
        sess = parse({"bug_encounters": [
            {"bug_id": "a", "reported": True}, {"bug_id": "b", "reported": False},
            {"type": "wallClip", "node": "l1.entry"},  # game format: no flag yet
        ]})
        self.assertEqual(len(sess.unreported_encounters()), 1)


class TestCSV(unittest.TestCase):
    def test_one_row_per_report_with_scores_for_every_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "reports.csv")
            cli.main([SAMPLE_SESSION, "--weights", SAMPLE_WEIGHTS, "--csv", out])
            with open(out, newline="") as fh:
                rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 3)
        first = rows[0]
        self.assertEqual(first["bug_id"], "b-1-l1")
        self.assertEqual(first["study_phase"], "2")
        self.assertEqual(float(first["cais_explorer"]), 2.0)
        self.assertAlmostEqual(float(first["pais_explorer"]), 32.25)
        for t in PLAYER_TYPES:
            self.assertIn("pais_" + t, first)



class TestValidator(unittest.TestCase):
    def _sample(self):
        with open(SAMPLE_SESSION) as fh:
            return json.load(fh)

    def _errors(self, data):
        return validate.check(parse(data))[0]

    def test_sample_session_is_clean(self):
        self.assertEqual(self._errors(self._sample()), [])

    def test_catches_a_branch_completed_by_the_wrong_trigger(self):
        # A note chest used to complete l1.room without a hidden room: no outcome recorded.
        data = self._sample()
        del data["progression_graph"]["branch_outcomes"]["l1.room"]
        self.assertTrue(any("l1.room completed but has no branch outcome" in e
                            for e in self._errors(data)))

    def test_catches_found_outcome_without_completion(self):
        data = self._sample()
        data["progression_graph"]["branch_outcomes"]["l1.boss"] = "found"
        self.assertTrue(any("l1.boss outcome 'found'" in e for e in self._errors(data)))

    def test_catches_exit_without_key(self):
        data = self._sample()
        comps = data["progression_graph"]["node_completions"]
        data["progression_graph"]["node_completions"] = [c for c in comps if c["node"] != "l1.key"]
        data["bug_reports"][2]["completed_nodes"].remove("l1.key")
        self.assertTrue(any("l1.exit completed without the key" in e for e in self._errors(data)))

    def test_catches_bug_encountered_where_it_was_not_placed(self):
        data = self._sample()
        data["bug_encounters"].append({"type": "stuckKey", "node": "l1.key", "chamber": 1})
        self.assertTrue(any("stuckKey encountered in chamber 1" in e for e in self._errors(data)))

    def test_catches_wrong_injected_config(self):
        data = self._sample()
        data["injectedConfig"] = {str(lv): sorted(validate.BUG_TABLE) for lv in (1, 2, 3)}
        self.assertTrue(any(e.startswith("chamber 1 injected") for e in self._errors(data)))

    def test_accepts_the_agreed_injected_config(self):
        data = self._sample()
        data["injectedConfig"] = {str(lv): validate.expected_bugs(lv) for lv in (1, 2, 3)}
        self.assertEqual(self._errors(data), [])

    def test_catches_report_snapshot_that_disagrees_with_completions(self):
        data = self._sample()
        data["bug_reports"][0]["completed_nodes"] = ["l1.entry", "l1.room"]
        self.assertTrue(any("b-1-l1 completed_nodes" in e for e in self._errors(data)))

    def test_bug_table_matches_the_game_config(self):
        """BUG_TABLE must mirror BUG_CATALOG in js/config.js."""
        import re
        with open(os.path.join(os.path.dirname(PKG), "js", "config.js")) as fh:
            js = fh.read()
        found = {}
        for m in re.finditer(r'(\w+):\s*\{[^}]*node:"(\w+)",\s*levels:\[([\d,]+)\]', js):
            found[m.group(1)] = (m.group(2), tuple(int(x) for x in m.group(3).split(",")))
        self.assertEqual(found, validate.BUG_TABLE)
        overrides = {}
        for m in re.finditer(r'(\w+):\s*\{[^\n]*nodeByLevel:\{(\d+):"(\w+)"\}', js):
            overrides[m.group(1)] = {int(m.group(2)): m.group(3)}
        self.assertEqual(overrides, validate.BUG_NODE_BY_LEVEL)

    def test_green_boss_undead_encounter_is_at_green_boss_node(self):
        data = self._sample()
        data["bug_encounters"] = [{"type": "undeadBoss", "node": "l3.greenBoss", "chamber": 3}]
        self.assertEqual(self._errors(data), [])
        data["bug_encounters"] = [{"type": "undeadBoss", "node": "l3.boss", "chamber": 3}]
        self.assertTrue(any("expected l3.greenBoss" in e for e in self._errors(data)))


if __name__ == "__main__":
    unittest.main()
