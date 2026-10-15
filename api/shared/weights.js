// Shared weight computation for the session upload and recompute endpoints.
//
// Weight of a node for a player type = mean severity of all Phase 1 bug reports
// attributed to it. A report is attributed to the NEXT node(s) after the
// player's last completed node, since the completed node can't be affected.
// Nodes with no reports keep the default weight of 1 (see `counts` for n).

const CONTAINER = "sessions";
const WEIGHTS_BLOB = "_weights.json";
const PLAYER_TYPES = ["explorer", "achiever", "killer"];

const DAG_EDGES = {
  "l1.entry":["l1.room","l1.chest","l1.boss","l1.key"],
  "l1.room":["l1.key"], "l1.chest":["l1.key"], "l1.boss":["l1.key"],
  "l1.key":["l1.exit"], "l1.exit":["l2.entry"],
  "l2.entry":["l2.room","l2.chest","l2.boss","l2.key"],
  "l2.room":["l2.key"], "l2.chest":["l2.key"], "l2.boss":["l2.key"],
  "l2.key":["l2.exit"], "l2.exit":["l3.entry"],
  "l3.entry":["l3.room","l3.chest","l3.boss","l3.greenBoss","l3.key"],
  "l3.room":["l3.key"], "l3.chest":["l3.key"], "l3.boss":["l3.key"],
  "l3.greenBoss":["l3.key"], "l3.key":["l3.exit"], "l3.exit":[],
};
const NODES = Object.keys(DAG_EDGES);

// Phase the study is currently in, set via the STUDY_PHASE app setting (default 1).
function currentPhase() {
  return process.env.STUDY_PHASE === "2" ? 2 : 1;
}

// Sessions stored before the phase field existed are treated as Phase 1.
function sessionPhase(session) {
  return session.study_phase === 2 ? 2 : 1;
}

function defaultWeights() {
  const w = {};
  NODES.forEach(n => w[n] = 1);
  return { explorer: { ...w }, achiever: { ...w }, killer: { ...w } };
}

async function streamToString(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf-8");
}

// Reads every Phase 1 session and returns per-type mean weights plus report counts.
async function computeWeights(container, log) {
  const sums = {}, counts = {};
  for (const t of PLAYER_TYPES) {
    sums[t] = {}; counts[t] = {};
    NODES.forEach(n => { sums[t][n] = 0; counts[t][n] = 0; });
  }
  let sessionsProcessed = 0, phase2Skipped = 0, updatesApplied = 0;
  const details = [];

  for await (const blob of container.listBlobsFlat()) {
    if (blob.name === WEIGHTS_BLOB || !blob.name.endsWith(".json")) continue;
    try {
      const dl = await container.getBlockBlobClient(blob.name).download(0);
      const session = JSON.parse(await streamToString(dl.readableStreamBody));
      if (sessionPhase(session) !== 1) { phase2Skipped++; continue; }
      sessionsProcessed++;

      const playerType = session.player_classification?.player_type?.dominant;
      if (!PLAYER_TYPES.includes(playerType)) continue;

      const updates = [];
      for (const report of session.bug_reports || []) {
        const severity = report.impact_rating || report.severity;
        const completed = report.completed_nodes || [];
        if (!severity || completed.length === 0) continue;

        const lastNode = completed[completed.length - 1];
        for (const next of DAG_EDGES[lastNode] || []) {
          sums[playerType][next] += severity;
          counts[playerType][next]++;
          updatesApplied++;
          updates.push({ lastCompleted: lastNode, impactedNode: next, severity });
        }
      }
      if (updates.length > 0) details.push({ blob: blob.name, playerType, updates });
    } catch (e) {
      if (log) log.warn("Skipped blob:", blob.name, e.message);
    }
  }

  const weights = defaultWeights();
  for (const t of PLAYER_TYPES) {
    for (const n of NODES) {
      if (counts[t][n] > 0) weights[t][n] = sums[t][n] / counts[t][n];
    }
  }
  return { weights, counts, sessionsProcessed, phase2Skipped, updatesApplied, details };
}

// Recomputes from all Phase 1 sessions and stores the result as _weights.json.
async function recomputeAndSave(container, log) {
  const result = await computeWeights(container, log);
  const content = JSON.stringify({
    ...result.weights,
    _counts: result.counts,
    _computed_at: new Date().toISOString(),
    _sessions: result.sessionsProcessed,
  }, null, 2);
  await container.getBlockBlobClient(WEIGHTS_BLOB).upload(content, Buffer.byteLength(content), {
    blobHTTPHeaders: { blobContentType: "application/json" },
  });
  return result;
}

module.exports = {
  CONTAINER, WEIGHTS_BLOB, DAG_EDGES,
  currentPhase, sessionPhase, defaultWeights, streamToString, recomputeAndSave,
};
