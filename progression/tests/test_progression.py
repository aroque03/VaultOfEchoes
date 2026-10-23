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
import bugs  # noqa: E402
import compare  # noqa: E402
import validate  # noqa: E402
from model import PROGRESSION_EDGES, next_open_nodes  # noqa: E402

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

    def test_runner_is_a_weight_set_without_a_branch(self):
        sets = sample_sets()
        self.assertIn("runner", sets)
        self.assertNotIn("runner", {v.player_type for v in NODES.values()})

    def test_weights_file_must_include_runner(self):
        data = {t: {n: 1 for n in NODES} for t in ("explorer", "achiever", "killer")}
        with self.assertRaises(KeyError):
            weight_sets_from_dict(data)

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

    def test_reads_the_self_reported_type(self):
        sess = parse({"player_classification": {"player_type": {"dominant": "killer"},
                                                "self_reported": {"type": "Explorer", "statement": "..."}}})
        self.assertEqual(sess.self_reported_type, "explorer")
        self.assertEqual(parse({}).self_reported_type, "")

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



class TestProgressionGraph(unittest.TestCase):
    def test_matches_the_game_graph(self):
        """PROGRESSION_EDGES must mirror DAG_EDGES in js/progression.js."""
        import re
        with open(os.path.join(os.path.dirname(PKG), "js", "progression.js")) as fh:
            js = fh.read()
        block = js[js.index("const DAG_EDGES = {"):js.index("};", js.index("const DAG_EDGES = {"))]
        game = {m.group(1): re.findall(r'"([\w.]+)"', m.group(2))
                for m in re.finditer(r'"([\w.]+)":\[([^\]]*)\]', block)}
        self.assertEqual({k: sorted(v) for k, v in game.items()},
                         {k: sorted(v) for k, v in PROGRESSION_EDGES.items()})

    def test_next_open_skips_completed_and_passes_through(self):
        self.assertEqual(sorted(next_open_nodes("l1.chest", ["l1.entry", "l1.chest"])),
                         ["l1.boss", "l1.key", "l1.room"])
        self.assertEqual(sorted(next_open_nodes("l1.room", ["l1.entry", "l1.key", "l1.room"])),
                         ["l1.boss", "l1.chest", "l1.exit"])
        self.assertEqual(next_open_nodes("l1.exit", ["l1.entry", "l1.key", "l1.exit"]), ["l2.entry"])


class TestCompare(unittest.TestCase):
    def test_kendall_tau_b(self):
        self.assertAlmostEqual(compare.kendall_tau_b([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(compare.kendall_tau_b([1, 2, 3], [3, 2, 1]), -1.0)
        # One tie in y: C=2, D=0, pairs=3, ties_y=1 -> 2 / sqrt(3 * 2)
        self.assertAlmostEqual(compare.kendall_tau_b([1, 2, 3], [1, 1, 2]), 2 / (6 ** 0.5))
        self.assertIsNone(compare.kendall_tau_b([2, 2, 2], [1, 2, 3]))

    def test_within_a_session_every_weight_set_gives_time_order(self):
        """Completed sets only grow, so CAIS order is time order under any positive weights."""
        done = ["l1.entry", "l1.room", "l1.key", "l1.exit", "l2.entry", "l2.boss"]
        reports = [done[:k] for k in range(1, len(done) + 1)]
        for ws in list(sample_sets().values()) + [compare.uniform_weight_set()]:
            keys = [compare.priority_key(r, ws) for r in reports]
            self.assertEqual(keys, sorted(keys), ws.player_type)

    def _explorer_sessions(self, ratings):
        out = []
        for i, (branch, rating) in enumerate(ratings):
            out.append(parse({"study_phase": 2, "player": {"id": "p%d" % i},
                              "player_classification": {"player_type": {"dominant": "explorer"}},
                              "bug_reports": [{"bug_id": "b", "impact_rating": rating,
                                               "completed_nodes": ["l1.entry", "l1." + branch]}]}))
        return out

    def _type_weights(self):
        def w(high):
            return {n: (5 if NODES[n].phase == high else 1) for n in NODES}
        return weight_sets_from_dict({"explorer": w("room"), "achiever": w("chest"),
                                      "killer": w("boss"), "runner": w("none")})

    def test_own_weights_beat_others_when_ratings_follow_them(self):
        # Same point in the game; explorers rate bugs after the room branch highest.
        sessions = self._explorer_sessions([("room", 5), ("room", 4), ("chest", 2),
                                            ("chest", 1), ("boss", 2), ("boss", 1)])
        res = compare.analyze(sessions, self._type_weights(), permutations=200, bootstrap=100)
        tau = res["types"]["explorer"]["tau"]
        self.assertGreater(tau["explorer"], 0.7)
        self.assertLess(tau["achiever"], 0)
        self.assertEqual(tau["uniform"], 0.0)
        self.assertGreater(res["types"]["explorer"]["vs"]["achiever"]["diff"], 1.0)

    def test_framework_result_has_a_95_interval_around_tau(self):
        # 18 one-report players; ratings follow the explorer weights.
        sessions = self._explorer_sessions([("room", 5), ("room", 4), ("chest", 2),
                                            ("chest", 1), ("boss", 2), ("boss", 1)] * 3)
        f = compare.analyze(sessions, self._type_weights(), permutations=200, bootstrap=300)["framework"]
        lo, hi = f["ci95"]
        self.assertLessEqual(lo, f["mean_tau"])
        self.assertGreaterEqual(hi, f["mean_tau"])
        self.assertGreater(lo, 0)  # the whole interval is positive
        self.assertEqual(f["reports"], 18)

    def test_skips_phase_1_and_types_without_enough_reports(self):
        sessions = self._explorer_sessions([("room", 5), ("chest", 2)])
        res = compare.analyze(sessions, self._type_weights(), permutations=50, bootstrap=20)
        self.assertTrue(res["types"]["explorer"]["skipped"])  # 2 reports < min 3
        res1 = compare.analyze(sessions, self._type_weights(), phase=1, permutations=50, bootstrap=20)
        self.assertEqual(res1["sessions_in_phase"], 0)

    def test_replication_correlates_phase2_severities_with_phase1_weights(self):
        sessions = self._explorer_sessions([("room", 5), ("chest", 3), ("boss", 1)])
        wsets = sample_sets()
        res = compare.analyze(sessions, wsets, permutations=50, bootstrap=20)
        self.assertIn("rho", res["replication"]["explorer"])
        self.assertGreater(res["replication"]["explorer"]["nodes"], 0)



class TestPlantedBugs(unittest.TestCase):
    def test_keys_and_ids_match_the_game(self):
        """BUG_KEYS must mirror the `key` of each bug in BUG_CATALOG (js/config.js)."""
        import re
        with open(os.path.join(os.path.dirname(PKG), "js", "config.js")) as fh:
            js = fh.read()
        keys = dict(re.findall(r'(\w+):\s*\{\s*key:"(\w+)"', js))
        self.assertEqual(keys, validate.BUG_KEYS)
        self.assertIn('"PB-L" + level + "-" + BUG_CATALOG[bug].key.toUpperCase()', js)
        self.assertEqual(len(validate.planted_bugs()), 14)
        self.assertEqual(validate.planted_bug_id("phantomGem", 2), "PB-L2-GEM")

    def test_validator_checks_the_self_reported_type(self):
        data = json.load(open(SAMPLE_SESSION))
        data["player_classification"]["self_reported"] = {"type": "socializer"}
        self.assertTrue(any("self-reported type" in e for e in validate.check(parse(data))[0]))

    def test_validator_flags_a_wrong_planted_id(self):
        sess = parse({"study_phase": 2, "player": {"id": "p"},
                      "player_classification": {"player_type": {"dominant": "explorer"}},
                      "bug_encounters": [{"type": "phantomGem", "node": "l2.chest", "chamber": 2,
                                          "planted_id": "PB-L2-BOSS"}]})
        self.assertTrue(any("planted_id PB-L2-BOSS" in e for e in validate.check(sess)[0]))


class TestBugCoding(unittest.TestCase):
    def _session(self):
        return parse({"study_phase": 2, "player": {"id": "p1"},
                      "player_classification": {"player_type": {"dominant": "achiever"}},
                      "bug_encounters": [
                          {"type": "wallClip", "node": "l2.entry", "chamber": 2, "timestamp": "2026-10-20T10:00:00.000Z"},
                          {"type": "phantomGem", "node": "l2.chest", "chamber": 2, "timestamp": "2026-10-20T10:05:00.000Z"}],
                      "bug_reports": [
                          {"bug_id": "b-1-l2", "chamber": 2, "impact_rating": 4, "timestamp": "2026-10-20T10:05:20.000Z",
                           "description": "a gem came back", "completed_nodes": ["l1.entry", "l2.entry", "l2.chest"]},
                          {"bug_id": "b-2-l3", "chamber": 3, "impact_rating": 2, "timestamp": "2026-10-20T10:09:00.000Z",
                           "description": "music cut out", "completed_nodes": ["l3.entry"]}]})

    def test_infers_the_planted_bug_from_the_last_encounter_as_metadata(self):
        sess = self._session()
        rows = bugs.rows([sess], phase=2)
        self.assertEqual(rows[0]["inferred_planted_id"], "PB-L2-GEM")  # derived for sessions without planted_id
        self.assertEqual(rows[0]["seconds_after_encounter"], "20")
        self.assertEqual(rows[1]["inferred_planted_id"], "")  # no encounter in chamber 3
        self.assertEqual(rows[0]["bug_label"], "")  # labels are never filled automatically

    def test_reexport_keeps_coded_labels(self):
        sess = self._session()
        with tempfile.TemporaryDirectory() as tmp:
            sheet = os.path.join(tmp, "coding.csv")
            bugs.export([sess], sheet, 2, None)
            with open(sheet, newline="") as fh:
                data = list(csv.DictReader(fh))
            data[0]["bug_label"] = "PB-L2-GEM"
            data[1]["bug_label"] = "audio-dropout"
            with open(sheet, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=bugs.COLUMNS); w.writeheader(); w.writerows(data)
            n, kept = bugs.export([sess], os.path.join(tmp, "again.csv"), 2, sheet)
            self.assertEqual((n, kept), (2, 2))
            self.assertEqual(bugs.load_labels(sheet), {data[0]["report_key"]: "PB-L2-GEM",
                                                      data[1]["report_key"]: "audio-dropout"})

    def test_bug_ranking_orders_labelled_bugs_by_framework_and_by_rating(self):
        def sess(i, rating, done):
            s = parse({"study_phase": 2, "player": {"id": "p%d" % i},
                       "player_classification": {"player_type": {"dominant": "achiever"}},
                       "bug_reports": [{"bug_id": "b", "impact_rating": rating, "completed_nodes": done}]})
            s.source = "s%d" % i
            return s
        early, mid, late = ["l1.entry"], ["l1.entry", "l1.key"], ["l1.entry", "l1.key", "l1.exit", "l2.entry"]
        sessions = [sess(0, 2, early), sess(1, 3, mid), sess(2, 5, late), sess(3, 4, late)]
        labels = {"s0#b": "PB-L1-WALL", "s1#b": "PB-L1-PWALL", "s2#b": "PB-L2-WALL", "s3#b": "PB-L2-WALL"}
        res = compare.bug_ranking(sessions, sample_sets(), labels)
        table = res["types"]["achiever"]["bugs"]
        self.assertEqual([b["bug"] for b in table], ["PB-L2-WALL", "PB-L1-PWALL", "PB-L1-WALL"])
        self.assertEqual(table[0]["reports"], 2)
        self.assertAlmostEqual(table[0]["mean_rating"], 4.5)
        self.assertAlmostEqual(res["types"]["achiever"]["tau"], 1.0)


if __name__ == "__main__":
    unittest.main()
