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

module.exports = async function (context, req) {
  const adminKey = process.env.ADMIN_KEY;
  if (adminKey && req.headers["x-admin-key"] !== adminKey) {
    context.res = { status: 401, body: { error: "Unauthorized" } };
    return;
  }

  const connStr = process.env.STORAGE_CONNECTION_STRING;
  if (!connStr) {
    context.res = { status: 500, body: { error: "Storage not configured" } };
    return;
  }

  try {
    const client = BlobServiceClient.fromConnectionString(connStr);
    const container = client.getContainerClient(CONTAINER);

    const weights = defaultWeights();
    let sessionsProcessed = 0;
    let updatesApplied = 0;
    const details = [];

    for await (const blob of container.listBlobsFlat()) {
      if (blob.name === WEIGHTS_BLOB) continue;
      if (!blob.name.endsWith(".json")) continue;

      try {
        const dl = await container.getBlockBlobClient(blob.name).download(0);
        const session = JSON.parse(await streamToString(dl.readableStreamBody));
        sessionsProcessed++;

        const playerType = session.player_classification?.player_type?.dominant;
        if (!playerType || !weights[playerType]) continue;

        const reports = session.bug_reports || [];
        if (reports.length === 0) continue;

        const typeWeights = weights[playerType];
        const sessionDetail = {
          blob: blob.name, playerType,
          reports: reports.length,
          updates: [],
        };

        for (const report of reports) {
          const severity = report.impact_rating || report.severity;
          if (!severity) continue;

          const completed = report.completed_nodes || [];
          if (completed.length === 0) continue;

          const lastNode = completed[completed.length - 1];
          if (typeWeights[lastNode] !== undefined) {
            const oldW = typeWeights[lastNode];
            typeWeights[lastNode] = (oldW + severity) / 2;
            updatesApplied++;
            sessionDetail.updates.push({
              node: lastNode,
              severity,
              completedCount: completed.length,
              oldW,
              newW: typeWeights[lastNode],
            });
          }
        }

        if (sessionDetail.updates.length > 0) details.push(sessionDetail);
      } catch (e) {
        context.log.warn("Skipped blob:", blob.name, e.message);
      }
    }

    const content = JSON.stringify(weights, null, 2);
    const wb = container.getBlockBlobClient(WEIGHTS_BLOB);
    await wb.upload(content, Buffer.byteLength(content), {
      blobHTTPHeaders: { blobContentType: "application/json" },
    });

    context.res = {
      status: 200,
      body: {
        ok: true,
        sessionsProcessed,
        updatesApplied,
        weights,
        details,
      },
      headers: { "Content-Type": "application/json" },
    };
  } catch (err) {
    context.log.error("Recompute failed:", err.message);
    context.res = { status: 500, body: { error: "Failed to recompute weights" } };
  }
};
