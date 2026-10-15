const { BlobServiceClient } = require("@azure/storage-blob");
const { CONTAINER, recomputeAndSave } = require("../shared/weights");

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
    const result = await recomputeAndSave(container, context.log);

    context.res = {
      status: 200,
      body: { ok: true, ...result },
      headers: { "Content-Type": "application/json" },
    };
  } catch (err) {
    context.log.error("Recompute failed:", err.message);
    context.res = { status: 500, body: { error: "Failed to recompute weights" } };
  }
};
