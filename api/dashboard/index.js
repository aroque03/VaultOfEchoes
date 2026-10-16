const { BlobServiceClient } = require("@azure/storage-blob");
const { currentPhase, sessionPhase } = require("../shared/weights");

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

    const players = new Map();
    let totalSessions = 0;
    let totalBugs = 0;
    const bugsByCategory = {};
    const bugsBySeverity = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
    const playerTypes = { explorer: 0, achiever: 0, killer: 0, runner: 0 };
    const sessionsByDate = {};
    const bugsByLevel = { 1: 0, 2: 0, 3: 0 };
    const bugEncounters = {}; // { bugType: { node: count } }
    const sessionsByPhase = { 1: 0, 2: 0 };
    let totalDuration = 0;
    let completedAll3 = 0;

    for await (const blob of container.listBlobsFlat()) {
      if (blob.name === WEIGHTS_BLOB) continue;
      if (!blob.name.endsWith(".json")) continue;

      const parts = blob.name.split("/");
      if (parts.length < 2) continue;

      const playerId = parts[0];
      totalSessions++;

      try {
        const dl = await container.getBlockBlobClient(blob.name).download(0);
        const session = JSON.parse(await streamToString(dl.readableStreamBody));

        if (!players.has(playerId)) {
          players.set(playerId, {
            name: session.player?.name || "Unknown",
            email: session.player?.email || null,
            sessions: 0,
          });
        }
        players.get(playerId).sessions++;
        sessionsByPhase[sessionPhase(session)]++;

        const bugs = session.bug_reports || [];
        totalBugs += bugs.length;
        for (const bug of bugs) {
          const cat = bug.category || "Other";
          bugsByCategory[cat] = (bugsByCategory[cat] || 0) + 1;
          const sev = bug.impact_rating || bug.severity;
          if (sev >= 1 && sev <= 5) bugsBySeverity[sev]++;
          const ch = bug.chamber;
          if (ch >= 1 && ch <= 3) bugsByLevel[ch]++;
        }

        for (const enc of session.bug_encounters || []) {
          if (!enc.type || !enc.node) continue;
          const byNode = bugEncounters[enc.type] = bugEncounters[enc.type] || {};
          byNode[enc.node] = (byNode[enc.node] || 0) + 1;
        }

        const pt = session.player_classification?.player_type?.dominant;
        if (pt && playerTypes[pt] !== undefined) playerTypes[pt]++;

        const started = session.session?.started_at;
        if (started) {
          const day = started.slice(0, 10);
          sessionsByDate[day] = (sessionsByDate[day] || 0) + 1;
        }

        const dur = session.session?.duration_ms;
        if (dur) totalDuration += dur;

        const completions = session.progression_graph?.node_completions || [];
        const hasL3Exit = completions.some(c => c.node === "l3.exit");
        if (hasL3Exit) completedAll3++;
      } catch (e) {
        context.log.warn("Failed to parse blob:", blob.name, e.message);
      }
    }

    // Read current weights
    let weights = null;
    try {
      const wb = container.getBlockBlobClient(WEIGHTS_BLOB);
      if (await wb.exists()) {
        const dl = await wb.download(0);
        weights = JSON.parse(await streamToString(dl.readableStreamBody));
      }
    } catch (e) { /* no weights yet */ }

    const avgSeverity = totalBugs > 0
      ? Math.round(Object.entries(bugsBySeverity).reduce((s, [k, v]) => s + k * v, 0) / totalBugs * 100) / 100
      : 0;

    context.res = {
      status: 200,
      body: {
        uniquePlayers: players.size,
        totalSessions,
        completedAll3,
        totalBugs,
        avgSeverity,
        avgDurationMin: totalSessions > 0 ? Math.round(totalDuration / totalSessions / 60000 * 10) / 10 : 0,
        bugsByCategory,
        bugsBySeverity,
        bugsByLevel,
        bugEncounters,
        currentPhase: currentPhase(),
        sessionsByPhase,
        playerTypes,
        sessionsByDate,
        players: Array.from(players.entries()).map(([id, p]) => ({
          id: id.slice(0, 8),
          name: p.name,
          email: p.email,
          sessions: p.sessions,
        })),
        weights,
      },
      headers: { "Content-Type": "application/json" },
    };
  } catch (err) {
    context.log.error("Admin read failed:", err.message);
    context.res = { status: 500, body: { error: "Failed to read data" } };
  }
};
