const { BlobServiceClient } = require("@azure/storage-blob");
const { CONTAINER, currentPhase, recomputeAndSave } = require("../shared/weights");

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
  // Stamped server-side so participants can't influence which phase they count toward.
  session.study_phase = currentPhase();
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

    // Phase 1 sessions refresh the weights; Phase 2 must not change them.
    // A full recompute (not an incremental update) keeps the mean order-independent
    // and means concurrent uploads can't drop each other's reports.
    if (session.study_phase === 1) {
      try {
        await recomputeAndSave(container, context.log);
      } catch (err) {
        context.log.warn("Weight update failed (session still saved):", err.message);
      }
    }

    context.res = {
      status: 201,
      body: { ok: true, blob: blobName, study_phase: session.study_phase },
      headers: { "Content-Type": "application/json" },
    };
  } catch (err) {
    context.log.error("Blob write failed:", err.message);
    context.res = { status: 500, body: { error: "Failed to store session" } };
  }
};
