# progression — CAIS/PAIS scoring for the Vault of Echoes study

Computes Completed and Potential Achievement Impact Scores from a study session
JSON, under all three Bartle weight sets at once.

Stdlib only, no install step, no dependencies. Tested on the macOS system
Python (3.9). The point is that this still runs unchanged when you come back to
it after writing the paper.

## Use

    python3 progression/cli.py progression/fixtures/sample-session.json
    python3 progression/cli.py session.json --verify       # check closed form vs enumeration
    python3 progression/cli.py session.json --asymmetric   # sensitivity weight set
    python3 progression/cli.py session.json --json         # machine-readable

    python3 -m unittest discover -s progression/tests -t progression

## Files

| File | What it holds |
|---|---|
| `model.py` | the 21 nodes, the three weight sets, the DAG edges |
| `scoring.py` | CAIS, PAIS (closed form + enumeration), prioritisation |
| `session.py` | session JSON loader, tolerant, warns instead of failing |
| `cli.py` | the command line report |
| `tests/` | 26 tests, including the pinned worked example |

Weights live only in `model.py`. Edit them there and every score moves; nothing
else needs touching. That is deliberate — the spec asks that CAIS and PAIS be
computed offline precisely so the weights stay revisable after the study has run.

## The model in one paragraph

21 nodes plus start and end: 12 spine (mandatory) and 9 branch (optional), four
and three per level across three levels. Spine weights are identical across all
three weight sets; branch weights are a permutation of {13, 3, 2} with each
type's own branch at 13. Every set therefore totals 126 over a full run, so raw
CAIS is comparable across types without normalisation.

## Two decisions worth knowing about

**PAIS averages over completion sets, not path orderings.** Modelling the three
branches as parallel edges would make a naive DFS enumerate 49 orderings per
level — 24 of them for "did everything", 1 for "went straight out" — inflating
PAIS toward full completion for purely combinatorial reasons. Each optional node
instead gets a bypass edge in a fixed arbitrary order, so enumeration yields
exactly one path per subset (8 per level, 512 per run). Ordering cannot change a
score anyway, since achievements are one-time and weights sum.

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

Relatedly, a player who finds no branches scores identically under all three
weight sets (`test_zero_branch_players_score_identically_under_every_set`). That
is the honest null rather than a bug: no branch behaviour, no differentiated
prediction. It does mean statistical power depends directly on branch discovery
rates.
