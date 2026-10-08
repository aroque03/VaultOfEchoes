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

async function streamToString(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf-8");
}
