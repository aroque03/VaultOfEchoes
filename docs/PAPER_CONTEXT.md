# Paper context brief: progression-based bug impact

This file briefs a writing assistant on the study behind the paper. It records what
was built, what was decided and **why**, and what is still open. Treat it as the
source of truth for decisions and terminology. As of 2026-10-23, **no study data has
been collected**: Phase 1 and Phase 2 have not run, so there are no results to
report. Numbers from simulated test runs below are pipeline checks, never findings.

## 1. Research question and sub-problems

> Can we establish an agnostic framework to measure a bug's impact on a player's
> experience based on their game play progression?

| Sub-problem | Answered by | Result to report |
|---|---|---|
| **SP1** How can player progression be represented independently of genre and game? | The achievement graph, implemented for Vault of Echoes; a second game (Half-Life: Source, first 7 areas) mapped with the same rules (**on hold**) | Both graphs |
| **SP2** Given that representation, how can a bug encounter's impact be quantified and used to prioritize bugs? | CAIS and PAIS with weights measured in Phase 1; Phase 2 reports coded to Planted Bug IDs | Bugs ranked per player type (comparison 5) |
| **SP3** Does the computed impact agree with how human players perceive it? | Phase 2: framework priority vs each player's 1–5 impact rating (comparison 1, **alone**) | Kendall's rank correlation coefficient (τ-b) with 95% CI and permutation p; supported if τ-b > 0 and p < 0.05 |

Extension (not required by any SP): **persona alignment**. Do players' stated play
styles match their behavior, and which identity should pick a player's weight
graph? (comparisons 6, 1b, 6b). If the self-reported type works as well as behavior,
the framework needs no game-specific classification rules, which supports "agnostic".

## 2. Relation to the BIAS 2026 paper and the guidelines

- This paper continues **BIAS 2026** (bug impact on player experience). Keep the BIAS
  pipeline (bug description capture, Gherkin translation, semantic similarity) as the
  reporting front end; this work adds the progression dimension.
- The paper guidelines (`Progression paper guidelines_.docx`) define the sections:
  Introduction · Background · Related Work · Approach · Case Study · Limitations ·
  Conclusions. Follow that structure.
- **The study diverged from the guidelines in three ways. The paper must describe
  the study as run:**
  1. **Case study game.** The guidelines plan Half-Life: Source. The study runs on
     **Vault of Echoes**, a purpose-built browser game where progression, bugs and
     ratings can be instrumented. Half-Life is kept as a second mapping for SP1 only.
  2. **Weights.** The guidelines propose designer-assigned Fibonacci rubric weights
     (e.g. new ability 13, new narrative 8, new health/armor 5). The study **measures**
     weights from players (Phase 1). The rubric remains the framework's portable
     default for games without player data; whether the paper frames it that way is
     an open decision (section 10).
  3. **Human validation.** The guidelines plan a survey of students rating bugs with
     context. The study collects **in-game ratings** at the moment of the bug (Phase 2).
     The survey was not built; it remains a possible addition (section 10).

## 3. The framework

**Progression graph.** A game's progression is a directed graph of **achievements**
from game start to game end. Achievements are one-time: once completed, they can't
be completed again. Nodes are defined by game events, not map coordinates, so the
graph is stable across procedurally generated layouts.

- **Required (spine) nodes** lie on every path; **optional (branch) nodes** may be skipped.
- Optional achievements in the same area can be completed **in any order**, so each
  connects to every other optional achievement in its area (both directions) and to
  the next required node. The drawn graph therefore has two-way links. Because no
  achievement repeats, every traversal is a simple path, and the **progression states**
  (sets of completed achievements) form a **DAG**. Use this wording; don't call the
  drawn graph itself a DAG without the qualifier.

**Weights.** Each node has a weight per player type. In the study, a node's weight =
the **mean severity** (1–5) of all Phase 1 bug reports attributed to it, by players of
that type. Nodes with no reports keep a placeholder weight of 1, and the number of
reports behind each weight is recorded.

**Attribution rule.** A bug report's severity goes to the **next achievements still
open** after the player's last completed achievement, not to where the bug appeared.
Completed achievements are skipped, passing through to what lies beyond. For
example, an optional achievement finished after the key leads on to the exit.
Rationale: an achievement already completed can't be affected; the bug impedes what
is still ahead.

**CAIS** (Completed Achievement Impact Score): the sum of the weights of the
achievements completed when the bug was reported.

**PAIS** (Potential Achievement Impact Score): the average remaining score over all
remaining paths to the end. Computed in closed form:

    PAIS = (remaining required weight) + (remaining optional weight) / 2

- Paths are enumerated **one per set of completed optional achievements**, not one
  per ordering. Ordering can't change a path's score (weights sum), and averaging
  over orderings would weight "complete everything" far more heavily than "skip
  everything", since there are many more orderings of a full set, for purely
  combinatorial reasons.
- Each optional node lies on exactly half the remaining paths, hence the / 2.
- Optional nodes in an area the player has already left are unreachable and drop out.
- The closed form is checked against explicit path enumeration in the tests.

**Prioritization.** Rank bugs by CAIS descending, then PAIS descending.

## 4. The case study instrument: Vault of Echoes

A three-chamber dungeon crawler (browser, deployed on Azure Static Web Apps; sessions
stored in Azure Blob Storage). Fixed maze seeds: every player gets the same layout.

**Graph: 19 nodes** (9 required, 10 optional).

| Node | Chambers | Kind | Completed when |
|---|---|---|---|
| entry | 1–3 | required | chamber loads |
| room | 1–3 | optional · Explorer | player enters a hidden room |
| chest | 1–3 | optional · Achiever | first gem collected |
| boss | 1–3 | optional · Killer | purple boss defeated |
| greenBoss | 3 | optional · Killer | green boss defeated |
| key | 1–3 | required | key chest opened |
| exit | 1–3 | required | door opens, chamber cleared |

**Player types**, derived from behavior. Each chamber scores 0–3 per type, and the
totals are summed over three chambers (0–9):

| Score | Explorer | Achiever | Killer |
|---|---|---|---|
| 3 | entered both hidden rooms | 3 gems picked up | every boss killed |
| 2 | entered 1 room | 2 gems | ≥ half the bosses, or every regular monster |
| 1 | tried for a room (wall bump near a passage, or humming wall twice within 10 s) | 1 gem | ≥ half the regular monsters |

- If **no total reaches 3**, the player is a **Runner**. Otherwise the highest total
  wins, and a tie goes to the type whose optional node was completed first.
- **Why Runner and not "speedrunner":** the game has no timer, so a speed motive
  can't be shown. "Runner" describes the behavior and follows the "Runners" cluster
  in Drachen, Canossa & Yannakakis (2009). Runners have a weight set but no branch.
  Socializers are excluded (single-player); Runner takes that slot as the fourth type.
- **Rules were tuned against artefacts:** sword hits alone don't score; walking past
  the humming wall once doesn't count; gems count when picked up, even if a bug
  makes one reappear; main-path note chests and regular monsters don't complete
  `room` or `boss`.

**Self-reported type.** After chamber 3, before the session uploads, players must
answer "Which best describes how you played?" with one of four statements, shown in
random order and without type names:
- find every hidden room and secret (Explorer)
- collect all the gems and treasure (Achiever)
- fight and defeat the monsters and bosses (Killer)
- reach the exit as directly as I could (Runner)

The answer is stored next to the derived type and never replaces it.

**Seeded bugs**: 8 mechanics, 14 **Planted Bug IDs** (`PB-L<chamber>-<KEY>`). None
blocks progress.

| Bug | Planted Bug IDs | What players see |
|---|---|---|
| wallClip | PB-L1/2/3-WALL | 1/2/3 wall tiles can be walked through |
| phantomWall | PB-L1-PWALL, PB-L3-PWALL | invisible wall at a dead end |
| invisiblePlayer | PB-L1-INVIS, PB-L2-INVIS | avatar vanishes for 5 steps after the far hidden room's chest |
| phantomGem | PB-L2-GEM | after the 3rd gem, one reappears and can't be collected |
| corruptNote | PB-L3-CORRUPT | first note shows a fake error stack trace |
| undeadBoss | PB-L2-BOSS, PB-L3-BOSS | boss survives at 1 HP (green boss in chamber 3) |
| fakeHeal | PB-L2-HEAL, PB-L3-HEAL | potion says "Healed" but HP doesn't rise |
| stuckKey | PB-L3-KEY | decoy key in a dead end is jammed |

Design principle: bugs are **non-blocking** disruptions ("the action works, the
feedback breaks"). This keeps player behavior, and so classification, intact, and
limits how much a bug's own disruptiveness confounds the importance of its node.

## 5. Study design

- **Phase 1** (target about 60 players): play all three chambers and report any
  number of bugs with a 1–5 impact rating (the BIAS anchors, from "very little
  impact" to "extremely high impact on my enjoyment"). The weights are built from
  these reports.
- **Freeze:** the Phase 1 weights are recomputed, downloaded and archived. Then the
  setting `STUDY_PHASE` = 2 is applied, stamped on each session by the server.
- **Phase 2** (target about 60 new players): same game, weights frozen. Uploads never
  change them.
- **Data per session:** login (first name, last initial, email; the system ID is a
  hash of the three), node completions with timestamps, bug encounters (with Planted
  Bug ID), bug reports (rating, category, free-text description, completed nodes at
  report time), per-chamber engagement and kill counts, derived and self-reported
  type, and the phase.
- **Bug identity.** Reports don't record which bug they describe. Researchers
  **hand-code** each description to a Planted Bug ID, or to a new label for
  unplanted issues, merging reports with the same meaning. An encounter-based guess
  is kept as metadata only.

## 6. Analysis (all offline, Python standard library: `progression/compare.py`)

| # | Comparison | Role |
|---|---|---|
| 1 | Framework priority vs ratings: τ-b pooled within player type with that type's weights, combined weighted by reports; within-type permutation test; bootstrap 95% CI (players resampled) | **answers SP3** |
| 5 | Bug ranking: per type, each coded bug's mean CAIS (then PAIS) vs its mean rating | **SP2** prioritization |
| 6 | Graph fit per player: each graph predicts a report's rating as its mean weight on the nodes the severity goes to; smallest mean absolute error = best fit; own-graph match rate vs 25% chance (permutation) | persona extension |
| 1b / 6b | Comparisons 1 and 6 with the graph picked by derived vs self-reported type, same players, bootstrap CI of the difference | persona extension, "agnostic" |
| 0, 2, 3, 4 | within-session order; own vs other graphs; own vs uniform weights; replication (Spearman of Phase 2 node means vs Phase 1 weights) | context only, not needed for any SP |

**Key methodological finding: why reports are compared across players.** Within one
session the completed set only grows and every weight is positive, so CAIS never
decreases. Ranking one player's reports by CAIS is therefore just **time order**,
identical under every weight set. Weight sets can only be distinguished across
players, so comparison 1 pools reports per type. Even then, CAIS is driven mostly by
how far a player has progressed, so own-vs-other weight comparisons have low power.

**Statistics in plain terms:**
- **Kendall's τ-b:** pairwise agreement in order, with ties handled.
- **Permutation test:** shuffle ratings 2,000 times; the p-value is the share of
  shuffles that do as well as the real data.
- **Bootstrap 95% CI:** resample players 1,000 times; take the middle 95%.

**Power** (approximate, from τ's standard error ≈ 0.67/√n): about 90 reports detect
τ ≈ 0.2 at α = 0.05 with 80% power. 60 players × 2–3 reports is enough overall; per
type (about 15 players) only τ ≈ 0.3 or more is detectable.

## 7. Validation done so far (not results)

- Scripted bots played the **real live game** through its own code: 4 personas,
  then 16 Phase 1 testers (4 per type). All were classified as intended, and every
  server-computed weight and count matched an independent recalculation exactly.
- A simulator generates synthetic Phase 1 and Phase 2 sessions with known answers
  to check the pipeline end to end. 57 automated tests cover the scoring, PAIS
  closed form vs enumeration, attribution, validator, coding sheet and comparisons.
- **None of this is study evidence.** Don't report simulated τ or weights as findings.

## 8. Related work already checked (verified sources)

| Work | Use in the paper |
|---|---|
| Bartle (1996), player types (Achiever, Explorer, Socializer, Killer) | base typology; Socializer excluded (single-player) |
| Bartle (2003) 8 types, implicit/explicit axis | Limitations: planned vs instinctive play isn't observable |
| Drachen, Canossa & Yannakakis (2009), *Player Modeling using Self-Organization in Tomb Raider: Underworld*, IEEE CIG: 1,365 players, ESOM clusters Veterans, Solvers, Pacifists, Runners (245 players, fast completion, frequent deaths) | behavior-based typing in a single-player game; source of "Runner" |
| Nacke, Bateman & Mandryk, BrainHex (ICEC 2011; Entertainment Computing 2014): Seeker, Survivor, Daredevil, Mastermind, Conqueror, Socialiser, Achiever | independent support for the four-way split (Seeker ≈ Explorer, Achiever ≈ Achiever, Conqueror ≈ Killer, Daredevil ≈ Runner) |
| Marczewski, Hexad (gamification) | not used: domain mismatch |
| Bateman & Boon (2005), DGD1 | not used: survey/personality based |

Links: Drachen et al. https://www.um.edu.mt/library/oar/handle/123456789/22900 ·
BrainHex https://www.doi.org/10.1007/978-3-642-24500-8_31 ·
Bartle 8 types https://mud.co.uk/richard/selfware.htm

Related-work areas in the guidelines that still need sources: progression
measurement in enterprise software and in video game software.

## 9. Limitations to state

- **Low power for type-specific weights.** CAIS is dominated by progress depth (section 6).
- **PAIS assumes every remaining path is equally likely,** which the player types contradict.
- **Placeholder weights (1)** on nodes with no Phase 1 reports.
- **Attribution is a rule,** not an observation.
- **One purpose-built game;** the second-game mapping (Half-Life) is on paper only.
- **Fixed maze seeds** (comparability) vs procedural play.
- **Self-reported type** is collected only from players who finish.
- **Bartle's implicit/explicit split** is not observable; Socializers are excluded.
- **Hand-coding bug identity** is a researcher judgment; the encounter guess is only a cross-check.

## 10. Open items

- **SP1:** map Half-Life: Source (7 areas: Hazard Course, Black Mesa Inbound,
  Anomalous Materials, Unforeseen Consequences, Office Complex, "We've Got
  Hostiles!", Blast Pit). Undecided: rubric weights vs structure only; graph only
  vs graph plus scored real bugs from the Valve wiki.
- **Weights framing:** the rubric as the portable default and measured weights as
  per-game calibration?
- **Phase 2 tester count** per type: set once testers are identified.
- **Survey** (fixed contexts, time spent): not built; would test type-specific weights more directly.
- **Typing X Y Z** reveals all hidden rooms; it is still available to participants.
- Possible follow-up model: a classifier from behavior to self-reported type
  (multinomial logistic regression, cross-validated), or partial pooling of graph
  weights. These are statistical models; don't describe them as "AI".

## 11. Terminology (keep exact)

achievement graph (progression graph) · required / optional node (spine / branch) ·
CAIS · PAIS · attribution rule · measured weights · Fibonacci rubric · player type:
Explorer, Achiever, Killer, Runner · derived type vs self-reported type · Planted Bug ID ·
Phase 1 / Phase 2 · Kendall's rank correlation coefficient (τ-b, which accounts for ties).

## 12. Where the truth lives

- Code and data model: GitHub `aroque03/VaultOfEchoes`. The game is in `js/`; the
  analysis in `progression/` (README covers the model, PAIS and Phase 2 notes).
- Running the study: `docs/TEST_PLAN.md` and the study guide (Claude Docs, exported).
- Spec: `Vault of Echoes — Study Modifications.pdf`. Prior paper:
  `BIAS_2026__Camera_Ready_090626 (3).pdf`. Structure: `Progression paper guidelines_.docx`.
