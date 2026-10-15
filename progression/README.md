# progression — CAIS/PAIS scoring for the Vault of Echoes study

The authoritative CAIS/PAIS implementation for the study. Scores every bug
report at the moment it was filed, under all three measured weight sets
(explorer, achiever, killer) at once. The in-game numbers in a session's
`scoring` block are a debug aid only.

Stdlib only, no install step, no dependencies. Tested on the macOS system
Python (3.9). The point is that this still runs unchanged when you come back to
it after writing the paper.

## Use

Weights come from the admin page's **DOWNLOAD WEIGHTS** (or `_weights.json`):
the mean Phase 1 severity per node per player type. Sessions can be a single
session file or the **DOWNLOAD JSON** export (an array of sessions).

    python3 progression/cli.py session.json --weights weights.json
    python3 progression/cli.py vault-sessions.json --weights weights.json --csv reports.csv
    python3 progression/cli.py session.json --weights weights.json --verify   # closed form vs enumeration
    python3 progression/cli.py session.json --weights weights.json --json     # machine-readable

    python3 -m unittest discover -s progression/tests -t progression

`--csv` writes the Phase 2 analysis table: one row per bug report with the
player's id, phase, classified type, impact rating, and CAIS/PAIS under each of
the three weight sets.

## Files

| File | What it holds |
|---|---|
| `model.py` | the 19 nodes, the DAG edges, weight loading |
| `scoring.py` | CAIS, PAIS (closed form + enumeration), prioritisation |
| `session.py` | session JSON loader (game schema + export arrays), tolerant, warns instead of failing |
| `cli.py` | the command line report and CSV export |
| `fixtures/` | a sample session in the game's format and illustrative (not real) weights |
| `tests/` | 26 tests, including a hand-pinned worked example |

## The model in one paragraph

19 nodes plus start and end, matching the game's DAG (`js/progression.js`):
9 spine (mandatory: entry, key, exit per level) and 10 branch (optional: room,
chest, boss per level, plus the green boss in level 3). Each branch is tied to a
Bartle type — room/explorer, chest/achiever, boss and green boss/killer.
Weights are measured, not assigned: Phase 1 attributes each report's severity to
the node(s) after the player's last completed node, and a node's weight is the
mean (`api/shared/weights.js`). Nodes nobody reported against keep a placeholder
weight of 1 — check `_counts` in the weights file.

## Two decisions worth knowing about

**PAIS averages over completion sets, not path orderings.** Modelling the
branches as parallel edges would make a naive DFS enumerate every ordering of
them, inflating PAIS toward full completion for purely combinatorial reasons.
Each optional node instead gets a bypass edge in a fixed arbitrary order, so
enumeration yields exactly one path per subset (1024 for a full run). Ordering
cannot change a score anyway, since achievements are one-time and weights sum.

That gives a closed form, which is what `pais()` actually evaluates:

    PAIS = (remaining mandatory weight) + (remaining optional weight) / 2

because every optional node lies on exactly half the remaining paths.
`pais_by_enumeration()` walks the paths explicitly and the tests hold the two
against each other; `--verify` does the same on real session data.

**Skipped branches die when a level closes.** "Remaining" is not "every
incomplete node". Once a level's exit fires the player descends and any branch
they skipped there is unreachable forever, so it drops out of PAIS. Within an
open level every incomplete node still counts, including branches earlier in the
enumeration chain than ones already done — the chain order is an enumeration
artefact and the game imposes no order on the branches.

## Known limitation, by design

The uniform average over paths assumes every player is equally likely to
complete every branch — which is exactly what the Bartle typing says is false.
Conditioning path probability on player type is the natural extension and
belongs in Limitations either way.

Measured weight sets also have different totals, so raw CAIS is not directly
comparable across player types; `score()` returns `cais_pct` for that.
