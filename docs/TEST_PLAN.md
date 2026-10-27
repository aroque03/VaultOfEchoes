# Vault of Echoes — Pre-study Test Plan

Goal: before Phase 1, prove that (1) the game records what the study needs,
(2) Phase 1 turns reports into the right weights, and (3) Phase 2 leaves those
weights alone and the ranking comparison works.

Testing runs against the live site. Phase 1 has not started, and **all data is
wiped before it does** (stage 5).

Site: `https://nice-desert-0e3e7100f.1.azurestaticapps.net` · admin: `/admin.html`

## Experiments and the sub-problems they answer

Research question: can we establish an agnostic framework to measure a bug's impact on a
player's experience based on their game play progression?

| # | Experiment | Data | Answers | Result to report |
|---|---|---|---|---|
| 1 | Achievement graph for Vault of Echoes, plus Half-Life: Source mapped with the same rules (on hold) | game definitions | **SP1** representation independent of game | both graphs |
| 2 | Phase 1: ~60 players play and report bugs | ratings attributed to the next open achievements | input for SP2 | measured weights per player type (frozen) |
| 3 | Phase 2: ~60 new players play with the weights frozen | reports, 1–5 ratings, self-reported type | **SP3** agreement with players | comparison 1: τ-b, 95% interval, p-value |
| 4 | Bug coding: Phase 2 reports matched to Planted Bug IDs | report descriptions | **SP2** quantify and prioritize bugs | bugs ranked per type (comparison 5) |
| 5 | Persona alignment: stated vs observed type | self-report, behavior, ratings | extends SP1 and SP3 | which graph fits each player (comparison 6); derived vs self-reported type as the graph to use (1b, 6b) |

Comparisons 0, 2, 3 and 4 in `compare.py` are context; they aren't needed to answer the
sub-problems. If the self-reported type picks the graph as well as behavior does, the
framework needs no game-specific classification rules, which supports the "agnostic" claim.

| Stage | What | Who | Time |
|---|---|---|---|
| 0 | Clear the container | you (Azure portal) | 2 min |
| 1 | Scripted play-throughs | you | ~45 min |
| 2 | Synthetic Phase 1 (10 sessions) | `simulate.py` | 1 min |
| 3 | Synthetic Phase 2 (10 sessions) | you set `STUDY_PHASE=2`, then `simulate.py` | 2 min |
| 4 | Review results | you + scripts | 15 min |
| 5 | Reset for the real study | you (Azure portal) | 2 min |

---

## Stage 0 — Clear the container

Storage account → Containers → `sessions` → select all blobs (including
`_weights.json`) → Delete. Stages 1–3 assume an empty container, because the
weights are calculated from **every** Phase 1 session stored.

## Stage 1 — Scripted play-throughs

Purpose: check what the *real game* records. Six short runs, one persona each.
Use a distinct first name per run (e.g. `Explorer1`) so sessions are easy to tell
apart. After each run, press **EXPORT** (top bar) or **EXPORT BUG LOG** (win
screen) to save the session JSON, then:

    python3 progression/validate.py ~/Downloads/vault-of-echoes-session-*.json -v

Expected: `0 errors` for every run. Note the warnings — "incomplete run" is
expected only for persona 5.

Hints: hidden rooms are either visible wall cracks or "audio" rooms (bump the
humming wall 3 times). Gems flee when you get close. **X** reveals all secrets —
use it only in persona 6, it skews classification.

| # | Persona | Do | Don't | Expected type | Expected branch nodes |
|---|---|---|---|---|---|
| 1 | Explorer | enter every hidden room (≥2 per chamber) | collect gems, kill enemies | explorer (explorer total 9) | all `room` |
| 2 | Achiever | collect all 3 gems per chamber | enter rooms, kill enemies | achiever (achiever total 9) | all `chest` |
| 3 | Killer | kill the purple boss each chamber, **and** the green boss in L3 | enter rooms, collect gems | killer (killer total 9) | all `boss`, `l3.greenBoss` |
| 4 | Runner | key → exit only | everything else | runner (every total below 3) | none |
| 5 | Dies in L2 | play normally in L1, let enemies kill you in L2 | — | any | session uploads on death, `incomplete run` warning |
| 6 | Heavy reporter | report every bug you hit (B), 3+ per chamber; press X to find rooms fast | — | any | many reports; each report's `completed_nodes` matches the moment it was filed |

While playing, confirm each seeded bug appears where the agreed table says, and
nowhere else:

Each planted bug has a Planted Bug ID per chamber (`PB-L<chamber>-<KEY>`, e.g. `PB-L2-GEM`;
`python3 progression/bugs.py planted` lists all 14). Encounters record it as `planted_id`.

| Bug | Chamber | How to see it |
|---|---|---|
| wallClip | 1, 2, 3 | some wall tiles let you walk through (1/2/3 per chamber) |
| phantomWall | 1, 3 | an invisible wall at a dead end |
| invisiblePlayer | 1, 2 | after the chest in the hidden room **furthest from the start** (in either order), your avatar vanishes on the main map and reappears after 5 steps (HP bar stays); the nearer room is normal |
| phantomGem | 2 | after all 3 gems, one reappears |
| corruptNote | 3 | first note chest shows a fake error stack trace |
| undeadBoss | 2, 3 | L2 purple boss / L3 **green** boss survives at 1 HP (L3 purple dies normally) |
| fakeHeal | 2, 3 | the potion (dropped by first kill) says "Healed" but HP doesn't rise |
| stuckKey | 3 | a decoy key in a dead end won't come out |

Also check the HUD progress reaches **100%** in every completed chamber, and
that killing a regular enemy or opening a main-path note chest does **not**
raise it.

### Classification rules

Each chamber is scored 0–3 per type when the player leaves it or dies in it
(`finalizeBranchOutcomes()` in `js/progression.js`). Bosses are the purple and
green monsters; everything else is a regular monster.

| Score | Explorer | Achiever | Killer |
|---|---|---|---|
| 3 | entered both hidden rooms | 3 gems | every boss killed (purple; plus green in L3) |
| 2 | entered 1 hidden room | 2 gems | half or more of the bosses, **or** every regular monster |
| 1 | tried for a room (wall bump within 2 tiles of a passage, or made the humming wall hum twice within 10 s / opened it) | 1 gem | half or more of the regular monsters |
| 0 | none | none | none (sword hits alone don't score) |

Gems count when picked up, even if the phantomGem bug makes one reappear.
Monsters per chamber: L1 1 boss / 2 regulars, L2 1 / 4, L3 2 / 6. In L1–L2
killing the one boss already scores 3; the "half the bosses" rule only matters
in L3.

The three chamber scores are summed per type (0–9). If **no total reaches 3**
(`RUNNER_THRESHOLD`), the player is a **runner**: they mostly head straight for the
key and exit. The name follows the "Runners" cluster in Drachen, Canossa &
Yannakakis (2009). Otherwise the highest total wins, and ties go to the type whose
branch was completed first (`room`, first gem, purple boss). Runners have their
own weight set and graph. Each session's
`player_classification.level_engagement` holds the per-chamber scores and the
kill counts behind the Killer score, so every result can be checked by hand.

### Checking the graph

Optional achievements can follow each other in any order, so within a chamber
each of `room`, `chest`, `boss` (and `greenBoss` in L3) connects to the others and
to `key`. A report's severity goes to the **next achievements still open** after the
last completed node (shown as "last" on the report form), in the graph for the
player's classified type. Completed nodes are skipped, passing through to what lies
beyond them:

| Completed when reporting (chamber 1) | Nodes that get the severity |
|---|---|
| `entry` | `room`, `chest`, `boss`, `key` |
| `entry`, `chest` | `room`, `boss`, `key` |
| `entry`, `chest`, `room` | `boss`, `key` |
| `entry`, `key`, `room` (optional after the key) | `chest`, `boss`, `exit` |
| … `key` | `exit` |
| … `exit` | next chamber's `entry` |

Each node's weight is the mean of the severities it received; `n=` is the count.
After a persona run with 2–3 reports at different severities: RECOMPUTE →
REFRESH → SHOW GRAPHS. Only the predicted nodes in that type's graph should be
red, with the right `n=` and mean; the other two graphs stay unchanged.

## Stage 2 — Synthetic Phase 1

Requires `STUDY_PHASE` unset (or `1`). Clear the container again first if you
want the weights check to be exact — stage 1 sessions also count.

    python3 progression/simulate.py phase1 --url https://nice-desert-0e3e7100f.1.azurestaticapps.net

Uploads 10 sessions **at the same time** (like a lab). Each player type always
rates bugs at a fixed severity (explorer 5, achiever 3, killer 1), so every
reported node must come back at exactly that weight. It also recomputes the
weights independently in Python and compares every node and count with the
server. Pass = `phase 1: ok — server weights match exactly`.

If it reports the server used fewer than 10 sessions, simultaneous uploads left
stale weights: press RECOMPUTE on the admin page, then compare again (see
"Known issue" below).

## Stage 3 — Synthetic Phase 2

1. Azure portal → the Static Web App → Environment variables → add
   `STUDY_PHASE` = `2` → Save.
2. Run:

       python3 progression/simulate.py phase2 --url https://nice-desert-0e3e7100f.1.azurestaticapps.net

Checks: the server stamps every session as phase 2 (it ignores the client); the
weights are byte-for-byte unchanged afterwards; and the ranking comparison
recovers a planted relation (ratings follow CAIS → ρ ≥ 0.6) but finds nothing in
shuffled ratings (|ρ| ≤ 0.4). It sends one probe session first and stops if the
phase is still 1.

## Stage 4 — Review

- Admin page: phase card shows 2; sessions split P1/P2; graphs show `n=` per node;
  INJECTED BUGS shows encounter counts.
- DOWNLOAD JSON and DOWNLOAD WEIGHTS, then:

      python3 progression/validate.py vault-sessions-*.json
      python3 progression/cli.py vault-sessions-*.json --weights vault-weights-*.json --csv reports.csv

  Every session should validate; `reports.csv` should have one row per report
  with CAIS/PAIS for all three types.

## Stage 5 — Reset for the real study

1. Delete every blob in `sessions`, including `_weights.json`.
2. Set `STUDY_PHASE` back to `1` (or delete it).
3. Open the admin page: 0 sessions, phase 1.

---

## Findings to resolve (from building this plan)

- **The Killer tiebreak ignores the green boss.** It checks only the purple
  `boss` completion, so a tied player whose first branch was the green boss
  doesn't get Killer from the tiebreak.
- **Typing X Y Z is an undocumented reveal cheat** available to every participant. It
  opens all hidden rooms, which makes anyone look like an Explorer. Recommend
  gating it behind a QA URL flag for the study.
- **Known issue — simultaneous uploads can leave weights briefly stale.** Each
  upload recalculates from all sessions, but a slower recalculation that started
  earlier can finish last and overwrite a newer one. Nothing is lost (sessions
  are all stored) and the next upload or RECOMPUTE corrects it. Before freezing
  weights for Phase 2, **always press RECOMPUTE**, then DOWNLOAD WEIGHTS.
