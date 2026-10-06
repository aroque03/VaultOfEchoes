"""Validation for the progression model.

Run:  python3 -m unittest discover -s progression/tests -t progression -v
"""

from __future__ import annotations

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import (  # noqa: E402
    BRANCH_NODES,
    BRANCH_WEIGHTS,
    NODES,
    PLAYER_TYPES,
    SPINE_NODES,
    all_weight_sets,
    node_id,
)
from scoring import (  # noqa: E402
    cais,
    pais,
    pais_by_enumeration,
    prioritize,
    reachable_nodes,
    remaining_paths,
)
from session import parse  # noqa: E402


class TestNodeModel(unittest.TestCase):
    def test_counts_match_the_spec(self):
        self.assertEqual(len(NODES), 21)
        self.assertEqual(len(SPINE_NODES), 12)
        self.assertEqual(len(BRANCH_NODES), 9)

    def test_all_weights_are_fibonacci(self):
        fib = {1, 2, 3, 5, 8, 13, 21}
        for ws in all_weight_sets().values():
            for nid, w in ws.weights.items():
                self.assertIn(w, fib, "{} has non-Fibonacci weight {}".format(nid, w))


class TestWeightSets(unittest.TestCase):
    def test_spine_is_identical_across_types(self):
        sets = all_weight_sets()
        for nid in SPINE_NODES:
            vals = {sets[t].weight(nid) for t in PLAYER_TYPES}
            self.assertEqual(len(vals), 1, "spine node {} differs across types".format(nid))

    def test_totals_are_equal_so_no_normalisation_is_needed(self):
        totals = {t: ws.total() for t, ws in all_weight_sets().items()}
        self.assertEqual(set(totals.values()), {126}, totals)

    def test_branch_weights_are_a_permutation_of_one_multiset(self):
        multisets = {tuple(sorted(v.values())) for v in BRANCH_WEIGHTS.values()}
        self.assertEqual(len(multisets), 1)
        self.assertEqual(multisets.pop(), (2, 3, 13))

    def test_each_type_values_its_own_branch_most(self):
        for t, ws in all_weight_sets().items():
            own = [n for n in BRANCH_NODES if NODES[n].player_type == t]
            other = [n for n in BRANCH_NODES if NODES[n].player_type != t]
            self.assertTrue(
                min(ws.weight(n) for n in own) > max(ws.weight(n) for n in other)
            )


class TestReachability(unittest.TestCase):
    def test_skipped_branches_are_lost_once_a_level_closes(self):
        done = ["l1.entry", "l1.nav", "l1.key", "l1.exit"]
        reach = reachable_nodes(done)
        self.assertNotIn("l1.room", reach, "level 1 branches survived its exit")
        self.assertNotIn("l1.chest", reach)
        self.assertIn("l2.room", reach)
        self.assertEqual(len(reach), 14)

    def test_open_level_keeps_all_its_incomplete_nodes(self):
        # Branch completed out of enumeration-chain order: chest before room.
        done = ["l1.entry", "l1.nav", "l1.chest"]
        self.assertIn("l1.room", reachable_nodes(done))

    def test_nothing_reachable_once_finished(self):
        every = list(NODES)
        self.assertEqual(reachable_nodes(every), ())
        for ws in all_weight_sets().values():
            self.assertEqual(pais(every, ws), 0.0)
            self.assertEqual(cais(every, ws), 126)


class TestPAIS(unittest.TestCase):
    """The closed form is the claim under test; enumeration is ground truth."""

    def _states(self):
        """A spread of realistic progression states."""
        order = [
            "l1.entry", "l1.nav", "l1.room", "l1.chest", "l1.boss", "l1.key", "l1.exit",
            "l2.entry", "l2.nav", "l2.boss", "l2.key", "l2.exit",
            "l3.entry", "l3.nav", "l3.room", "l3.key", "l3.exit",
        ]
        return [order[:i] for i in range(len(order) + 1)]

    def test_closed_form_matches_enumeration(self):
        for ws in all_weight_sets().values():
            for done in self._states():
                self.assertAlmostEqual(
                    pais(done, ws), pais_by_enumeration(done, ws), places=9,
                    msg="{} after {} nodes".format(ws.player_type, len(done)),
                )

    def test_closed_form_matches_enumeration_on_every_branch_subset(self):
        """Exhaustive over level 1: all 8 branch subsets, key found or not."""
        ws = all_weight_sets()["achiever"]
        branches = ["l1.room", "l1.chest", "l1.boss"]
        for k in range(4):
            for subset in itertools.combinations(branches, k):
                for tail in ([], ["l1.key"]):
                    done = ["l1.entry", "l1.nav"] + list(subset) + tail
                    self.assertAlmostEqual(
                        pais(done, ws), pais_by_enumeration(done, ws), places=9
                    )

    def test_path_count_is_one_per_subset_not_per_ordering(self):
        # Fresh run: 3 levels x 3 optional branches = 2^9 completion subsets.
        self.assertEqual(len(remaining_paths([])), 512)
        # One level in, 6 branches left.
        self.assertEqual(len(remaining_paths(["l1.entry", "l1.nav", "l1.key", "l1.exit"])), 64)

    def test_every_optional_node_lies_on_exactly_half_the_paths(self):
        paths = remaining_paths([])
        for nid in BRANCH_NODES:
            hits = sum(1 for p in paths if nid in p)
            self.assertEqual(hits, len(paths) // 2, nid)

    def test_pais_is_monotonically_non_increasing(self):
        for ws in all_weight_sets().values():
            vals = [pais(d, ws) for d in self._states()]
            for a, b in zip(vals, vals[1:]):
                self.assertLessEqual(b, a)

    def test_cais_plus_pais_bounds(self):
        """A player can never have banked plus expect more than the maximum."""
        for ws in all_weight_sets().values():
            for done in self._states():
                self.assertLessEqual(cais(done, ws) + pais(done, ws), ws.total())


class TestWeightSetDivergence(unittest.TestCase):
    def test_zero_branch_players_score_identically_under_every_set(self):
        """The designed null: no branch behaviour means no differentiated claim."""
        done = ["l1.entry", "l1.nav", "l1.key", "l1.exit", "l2.entry", "l2.nav"]
        sets = all_weight_sets()
        caises = {sets[t].player_type: cais(done, sets[t]) for t in PLAYER_TYPES}
        self.assertEqual(len(set(caises.values())), 1, caises)

    def test_branch_completion_separates_the_sets(self):
        done = ["l1.entry", "l1.nav", "l1.room", "l1.key", "l1.exit"]
        sets = all_weight_sets()
        self.assertGreater(cais(done, sets["explorer"]), cais(done, sets["achiever"]))
        self.assertGreater(cais(done, sets["explorer"]), cais(done, sets["killer"]))


class TestWorkedExample(unittest.TestCase):
    """The example in the design discussion, pinned so the numbers cannot drift."""

    DONE = ["l1.entry", "l1.nav", "l1.key", "l1.exit", "l2.entry", "l2.nav", "l2.room"]

    def test_values(self):
        sets = all_weight_sets()
        expected = {
            "explorer": (45, 51.5),
            "achiever": (34, 57.0),
            "killer": (34, 57.0),
        }
        for t, (c, p) in expected.items():
            self.assertEqual(cais(self.DONE, sets[t]), c, t)
            self.assertAlmostEqual(pais(self.DONE, sets[t]), p, places=9, msg=t)


class TestPrioritisation(unittest.TestCase):
    def test_sorts_by_cais_then_pais_descending(self):
        reports = [
            {"bug_id": "late", "completed_nodes": ["l1.entry", "l1.nav", "l1.key", "l1.exit", "l2.entry"]},
            {"bug_id": "early", "completed_nodes": ["l1.entry"]},
            {"bug_id": "mid", "completed_nodes": ["l1.entry", "l1.nav", "l1.key"]},
        ]
        ranked = prioritize(reports, all_weight_sets()["killer"])
        self.assertEqual([r["bug_id"] for r in ranked], ["late", "mid", "early"])

    def test_pais_breaks_cais_ties(self):
        """Equal CAIS, different futures.

        The explorer weights give both players 24 banked. But the rusher took
        the key and left, burning level 1's three branches for good; the
        wanderer is still inside level 1 with everything ahead of them. Equal
        CAIS, so PAIS decides -- and the wanderer, who stands to lose more,
        outranks the rusher.
        """
        ws = all_weight_sets()["explorer"]
        rusher = {"bug_id": "rusher",
                  "completed_nodes": ["l1.entry", "l1.nav", "l1.key", "l1.exit"]}
        wanderer = {"bug_id": "wanderer",
                    "completed_nodes": ["l1.entry", "l1.nav", "l1.room", "l1.chest"]}
        ranked = prioritize([rusher, wanderer], ws)
        self.assertEqual(ranked[0]["cais"], ranked[1]["cais"], "fixture no longer ties on CAIS")
        self.assertEqual(ranked[0]["cais"], 24)
        self.assertGreater(ranked[0]["pais"], ranked[1]["pais"])
        self.assertEqual(ranked[0]["bug_id"], "wanderer")


class TestSessionLoader(unittest.TestCase):
    def test_reconstructs_completed_nodes_from_timestamps(self):
        data = {
            "schema": "vault-of-echoes.study-session/v1",
            "node_completions": [
                {"node": "l1.entry", "timestamp": "2026-09-23T10:00:00Z"},
                {"node": "l1.nav", "timestamp": "2026-09-23T10:05:00Z"},
                {"node": "l1.key", "timestamp": "2026-09-23T10:20:00Z"},
            ],
            "bug_reports": [{"bug_id": "b1", "timestamp": "2026-09-23T10:06:00Z"}],
        }
        sess = parse(data)
        self.assertEqual(sess.bug_reports[0]["completed_nodes"], ["l1.entry", "l1.nav"])
        self.assertTrue(any("reconstructed" in w for w in sess.warnings))

    def test_flags_unknown_nodes_and_bad_ratings(self):
        sess = parse({
            "node_completions": [{"node": "l9.entry", "timestamp": "x"}],
            "bug_reports": [{"bug_id": "b1", "impact_rating": 7, "completed_nodes": ["nope"]}],
        })
        joined = " ".join(sess.warnings)
        self.assertIn("unknown node id", joined)
        self.assertIn("out of range", joined)
        self.assertIn("unknown nodes", joined)

    def test_counts_unreported_encounters(self):
        sess = parse({"bug_encounters": [
            {"bug_id": "a", "reported": True}, {"bug_id": "b", "reported": False},
        ]})
        self.assertEqual(len(sess.unreported_encounters()), 1)


class TestAsymmetricSensitivitySet(unittest.TestCase):
    def test_loads_and_still_favours_own_branch(self):
        for t, ws in all_weight_sets(asymmetric=True).items():
            own = [n for n in BRANCH_NODES if NODES[n].player_type == t]
            other = [n for n in BRANCH_NODES if NODES[n].player_type != t]
            self.assertTrue(min(ws.weight(n) for n in own) > max(ws.weight(n) for n in other))

    def test_totals_differ_so_normalisation_matters_here(self):
        totals = {t: ws.total() for t, ws in all_weight_sets(asymmetric=True).items()}
        self.assertGreater(len(set(totals.values())), 1, totals)

    def test_closed_form_still_matches_enumeration(self):
        for ws in all_weight_sets(asymmetric=True).values():
            done = ["l1.entry", "l1.nav", "l1.room", "l1.key", "l1.exit", "l2.entry"]
            self.assertAlmostEqual(pais(done, ws), pais_by_enumeration(done, ws), places=9)


if __name__ == "__main__":
    unittest.main()
