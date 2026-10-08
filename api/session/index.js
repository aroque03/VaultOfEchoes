const { BlobServiceClient } = require("@azure/storage-blob");

const CONTAINER = "sessions";
const WEIGHTS_BLOB = "_weights.json";

function defaultWeights() {
  const nodes = [
    "l1.entry","l1.room","l1.chest","l1.boss","l1.key","l1.exit",
    "l2.entry","l2.room","l2.chest","l2.boss","l2.key","l2.exit",
    "l3.entry","l3.room","l3.chest","l3.boss","l3.greenBoss","l3.key","l3.exit",
  ];
  const w = {};
  nodes.forEach(n => w[n] = 1);
  return { explorer: { ...w }, achiever: { ...w }, killer: { ...w } };
}

async function streamToString(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf-8");
}

async function updateWeights(container, session, context) {
  const playerType = session.player_classification?.player_type?.dominant;
  if (!playerType) return;

  const encounters = session.bug_encounters || [];
  const reports = session.bug_reports || [];
  if (reports.length === 0) return;

  const blob = container.getBlockBlobClient(WEIGHTS_BLOB);
  let weights;
  try {
    const exists = await blob.exists();
    if (exists) {
      const dl = await blob.download(0);
      weights = JSON.parse(await streamToString(dl.readableStreamBody));
    } else {
      weights = defaultWeights();
    }
  } catch (e) {
    weights = defaultWeights();
  }

  if (!weights[playerType]) weights[playerType] = { ...defaultWeights().explorer };
  const typeWeights = weights[playerType];

  // Build a set of nodes from encounters for this session
  const encounterNodes = new Set(encounters.map(e => e.node));

  // For each bug report, find the matching encounter node and apply severity
  for (const report of reports) {
    const severity = report.impact_rating || report.severity;
    if (!severity) continue;

    // Match report to encounter by chamber and timing
    const chamber = report.chamber;
    const matchedEncounters = encounters.filter(e => e.chamber === chamber);

    if (matchedEncounters.length > 0) {
      // Apply severity to each encountered node in this chamber
      for (const enc of matchedEncounters) {
        if (typeWeights[enc.node] !== undefined) {
          typeWeights[enc.node] = (typeWeights[enc.node] + severity) / 2;
        }
      }
    }
  }

  const content = JSON.stringify(weights, null, 2);
  await blob.upload(content, Buffer.byteLength(content), {
    blobHTTPHeaders: { blobContentType: "application/json" },
  });
  context.log("Weights updated for player type:", playerType);
}

module.exports = async function (context, req) {
  if (!req.body || !req.body.schema) {
    context.res = { status: 400, body: { error: "Missing session payload" } };
    return;
  }

  const connStr = process.env.STORAGE_CONNECTION_STRING;
  if (!connStr) {
    context.res = { status: 500, body: { error: "Storage not configured" } };
    return;
  }

  const session = req.body;
  const playerId = session.player?.id || "anon";
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const blobName = `${playerId}/${ts}.json`;

  try {
    const client = BlobServiceClient.fromConnectionString(connStr);
    const container = client.getContainerClient(CONTAINER);
    await container.createIfNotExists();
    const blob = container.getBlockBlobClient(blobName);
    const content = JSON.stringify(session, null, 2);
    await blob.upload(content, Buffer.byteLength(content), {
      blobHTTPHeaders: { blobContentType: "application/json" },
    });

    // Update running weight averages
    try {
      await updateWeights(container, session, context);
    } catch (err) {
      context.log.warn("Weight update failed (session still saved):", err.message);
    }

    context.res = {
      status: 201,
      body: { ok: true, blob: blobName },
      headers: { "Content-Type": "application/json" },
    };
  } catch (err) {
    context.log.error("Blob write failed:", err.message);
    context.res = { status: 500, body: { error: "Failed to store session" } };
  }
};
