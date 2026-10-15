# Vault of Echoes — Pre-study Test Plan

Goal: before Phase 1, prove that (1) the game records what the study needs,
(2) Phase 1 turns reports into the right weights, and (3) Phase 2 leaves those
weights alone and the ranking comparison works.

Testing runs against the live site. Phase 1 has not started, and **all data is
wiped before it does** (stage 5).

Site: `https://nice-desert-0e3e7100f.1.azurestaticapps.net` · admin: `/admin.html`

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
| 3 | Killer | kill the purple boss each chamber, green boss in L3 | enter rooms, collect gems | killer (killer total 9) | all `boss`, `l3.greenBoss` |
| 4 | Speedrunner | key → exit only | everything else | **explorer by default** (0/0/0 tie, see finding below) | none |
| 5 | Dies in L2 | play normally in L1, let enemies kill you in L2 | — | any | session uploads on death, `incomplete run` warning |
| 6 | Heavy reporter | report every bug you hit (B), 3+ per chamber; press X to find rooms fast | — | any | many reports; each report's `completed_nodes` matches the moment it was filed |

While playing, confirm each seeded bug appears where the agreed table says, and
nowhere else:

| Bug | Chamber | How to see it |
|---|---|---|
| wallClip | 1, 2, 3 | some wall tiles let you walk through (1/2/3 per chamber) |
| phantomWall | 1, 3 | an invisible wall at a dead end |
| missingNote | 1, 2 | the chest inside a hidden room opens empty ("The chest is empty...") |
| phantomGem | 2 | after all 3 gems, one reappears |
| corruptNote | 3 | first note chest shows a fake error stack trace |
| undeadBoss | 2, 3 | L2 purple boss / L3 **green** boss survives at 1 HP (L3 purple dies normally) |
| fakeHeal | 2, 3 | the potion (dropped by first kill) says "Healed" but HP doesn't rise |
| stuckKey | 3 | a decoy key in a dead end won't come out |

Also check the HUD progress reaches **100%** in every completed chamber, and
that killing a regular enemy or opening a main-path note chest does **not**
raise it.

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

- **Zero-engagement players are classified as explorer.** With 0/0/0 totals the
  tiebreak finds no branch completion and falls back to the first type listed.
  Decide: exclude them from the analysis, or add an "unclassified" type.
- **X key is an undocumented reveal cheat** available to every participant. It
  opens all hidden rooms, which makes anyone look like an Explorer. Recommend
  gating it behind a QA URL flag for the study.
- **Bug report form says `nodes x/21`**; the graph has 19 nodes.
- **Known issue — simultaneous uploads can leave weights briefly stale.** Each
  upload recalculates from all sessions, but a slower recalculation that started
  earlier can finish last and overwrite a newer one. Nothing is lost (sessions
  are all stored) and the next upload or RECOMPUTE corrects it. Before freezing
  weights for Phase 2, **always press RECOMPUTE**, then DOWNLOAD WEIGHTS.
