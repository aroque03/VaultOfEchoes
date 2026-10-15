const { BlobServiceClient } = require("@azure/storage-blob");
const { CONTAINER, WEIGHTS_BLOB, defaultWeights, streamToString } = require("../shared/weights");

module.exports = async function (context, req) {
  const connStr = process.env.STORAGE_CONNECTION_STRING;
  if (!connStr) {
    context.res = {
      status: 200,
      body: defaultWeights(),
      headers: { "Content-Type": "application/json" },
    };
    return;
  }

  try {
    const client = BlobServiceClient.fromConnectionString(connStr);
    const container = client.getContainerClient(CONTAINER);
    const blob = container.getBlockBlobClient(WEIGHTS_BLOB);
    const exists = await blob.exists();

    if (exists) {
      const dl = await blob.download(0);
      const text = await streamToString(dl.readableStreamBody);
      context.res = {
        status: 200,
        body: JSON.parse(text),
        headers: { "Content-Type": "application/json" },
      };
    } else {
      context.res = {
        status: 200,
        body: defaultWeights(),
        headers: { "Content-Type": "application/json" },
      };
    }
  } catch (err) {
    context.log.error("Weights read failed:", err.message);
    context.res = {
      status: 200,
      body: defaultWeights(),
      headers: { "Content-Type": "application/json" },
    };
  }
};

