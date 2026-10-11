const { BlobServiceClient } = require("@azure/storage-blob");

const CONTAINER = "sessions";
const WEIGHTS_BLOB = "_weights.json";

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
    const sessions = [];

    for await (const blob of container.listBlobsFlat()) {
      if (blob.name === WEIGHTS_BLOB) continue;
      if (!blob.name.endsWith(".json")) continue;

      try {
        const dl = await container.getBlockBlobClient(blob.name).download(0);
        const data = JSON.parse(await streamToString(dl.readableStreamBody));
        sessions.push({ _blob: blob.name, ...data });
      } catch (e) {
        context.log.warn("Skipped blob:", blob.name, e.message);
      }
    }

    context.res = {
      status: 200,
      body: JSON.stringify(sessions, null, 2),
      headers: {
        "Content-Type": "application/json",
        "Content-Disposition": "attachment; filename=\"vault-sessions.json\"",
      },
    };
  } catch (err) {
    context.log.error("Export failed:", err.message);
    context.res = { status: 500, body: { error: "Failed to export data" } };
  }
};
