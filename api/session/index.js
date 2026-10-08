const { BlobServiceClient } = require("@azure/storage-blob");

const CONTAINER = "sessions";

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
