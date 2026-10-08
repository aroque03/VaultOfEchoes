/* progression.js — Node tracking, player type classification, session export */

let loadedWeights = null;

function loadWeights(){
  fetch("/api/weights")
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => { if(data && data.explorer) loadedWeights = data; })
    .catch(() => {
      fetch("/data/weights.json")
        .then(r => r.ok ? r.json() : null)
        .then(data => { if(data && data.explorer) loadedWeights = data; })
        .catch(() => {});
    });
}

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

function computeCAIS(playerType){
  if(!loadedWeights || !playerType) return null;
  const w = loadedWeights[playerType];
  if(!w) return null;
  const done = state.progression.completions.map(c => c.node);
  let score = 0;
  for(const node of done) score += (w[node] || 0);
  return Math.round(score * 100) / 100;
}

function computePAIS(playerType){
  if(!loadedWeights || !playerType) return null;
  const w = loadedWeights[playerType];
  if(!w) return null;
  const done = new Set(state.progression.completions.map(c => c.node));
  const remaining = Object.keys(DAG_EDGES).filter(n => !done.has(n));
  if(remaining.length === 0) return 0;
  let total = 0;
  for(const node of remaining) total += (w[node] || 0);
  return Math.round((total / remaining.length) * 100) / 100;
}

function nodeId(phase){ return "l"+(state.levelIdx+1)+"."+phase; }

function completeNode(nid){
  if(state.progression.completions.some(c => c.node === nid)) return;
  state.progression.completions.push({
    node: nid,
    timestamp: new Date().toISOString(),
    elapsed_ms: Date.now() - state.progression.startTime,
  });
  updateHUD();
}

function completedNodes(){
  return state.progression.completions.map(c => c.node);
}

function completedThisLevel(){
  const prefix = "l"+(state.levelIdx+1)+".";
  return state.progression.completions.filter(c => c.node.startsWith(prefix)).length;
}

function markBranchOutcome(nid, outcome){
  if(outcome === "attempted" && state.progression.branchOutcomes[nid] === "found") return;
  state.progression.branchOutcomes[nid] = outcome;
}

function finalizeBranchOutcomes(){
  const lvl = state.levelIdx + 1;
  const phases = ["room","chest","boss"];
  if(lvl === 3) phases.push("greenBoss");
  for(const phase of phases){
    const nid = "l"+lvl+"."+phase;
    if(!state.progression.branchOutcomes[nid]){
      state.progression.branchOutcomes[nid] = "never_approached";
    }
  }
  if(!state.progression.roomsFound) state.progression.roomsFound = {};
  state.progression.roomsFound["l"+lvl] = {
    found: state.hiddenRooms.filter(r=>r.entered).length,
    total: state.hiddenRooms.length,
    types: state.hiddenRooms.map(r=>({type:r.type, entered:r.entered, noteCollected:r.note.collected})),
  };

  const roomsEntered = state.hiddenRooms.filter(r => r.entered).length;
  const wallBumpsNearRoom = state.progression.branchOutcomes["l"+lvl+".room"] === "attempted";
  let explorerTier = 0;
  if(roomsEntered >= 2) explorerTier = 3;
  else if(roomsEntered === 1) explorerTier = 2;
  else if(wallBumpsNearRoom) explorerTier = 1;

  const gemsCollected = state.gems.filter(g => g.collected).length;
  let achieverTier = Math.min(gemsCollected, 3);

  let killerTier = 0;
  if(state.progression.bossKilled) killerTier = 3;
  else if(state.progression.enemiesKilled > 0) killerTier = 2;
  else if(state.progression.swordSwung) killerTier = 1;

  state.progression.levelEngagement["l"+lvl] = {
    explorer: explorerTier,
    achiever: achieverTier,
    killer: killerTier,
  };
}

function classifyPlayerType(){
  const totals = {explorer:0, achiever:0, killer:0};
  for(let lvl=1; lvl<=3; lvl++){
    const eng = state.progression.levelEngagement["l"+lvl];
    if(!eng) continue;
    totals.explorer += eng.explorer;
    totals.achiever += eng.achiever;
    totals.killer += eng.killer;
  }
  const max = Math.max(totals.explorer, totals.achiever, totals.killer);
  const tied = Object.keys(totals).filter(t => totals[t] === max);
  let dominant;
  if(tied.length === 1){
    dominant = tied[0];
  } else {
    const branchPhase = {explorer:"room", achiever:"chest", killer:"boss"};
    let earliest = null, earliestType = tied[0];
    for(const t of tied){
      const phase = branchPhase[t];
      const comp = state.progression.completions.find(c => c.node.endsWith("."+phase));
      if(comp){
        if(!earliest || comp.elapsed_ms < earliest){
          earliest = comp.elapsed_ms;
          earliestType = t;
        }
      }
    }
    dominant = earliestType;
  }
  return {dominant, totals, tiebroken: tied.length > 1};
}

function injectedConfigAll(){
  const out = {};
  [1,2,3].forEach(l => { out[l] = activeBugsForLevel(l); });
  return out;
}

function buildSession(){
  return {
    schema: "vault-of-echoes.study-session/v1",
    player: {
      id: state.playerId || state.sessionId,
      name: state.playerName || null,
    },
    session: {
      build: "voe-study-1.0",
      seed: CHAMBERS[0].seed,
      started_at: state.sessionStart,
      ended_at: new Date().toISOString(),
      duration_ms: Date.now() - state.progression.startTime,
    },
    progression_graph: {
      nodes_per_level: {
        l1: ["entry","room","chest","boss","key","exit"],
        l2: ["entry","room","chest","boss","key","exit"],
        l3: ["entry","room","chest","boss","greenBoss","key","exit"],
      },
      node_completions: state.progression.completions,
      branch_outcomes: state.progression.branchOutcomes,
      rooms_found: state.progression.roomsFound || {},
    },
    player_classification: {
      level_engagement: state.progression.levelEngagement || {},
      player_type: classifyPlayerType(),
    },
    bug_reports: state.bugs,
    bug_encounters: state.progression.encounters,
    injectedConfig: injectedConfigAll(),
    finalScore: state.score,
    scoring: (() => {
      const pt = classifyPlayerType().dominant;
      const cais = computeCAIS(pt);
      const pais = computePAIS(pt);
      if(cais === null) return { weights_loaded: false };
      return {
        weights_loaded: true,
        player_type: pt,
        weights_used: loadedWeights ? loadedWeights[pt] : null,
        cais: cais,
        pais: pais,
      };
    })(),
  };
}

function submitSession(){
  const session = buildSession();
  fetch("/api/session", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(session),
  }).then(r => {
    if(r.ok) console.log("[VoE] Session saved to server");
    else console.warn("[VoE] Server save failed:", r.status);
  }).catch(err => {
    console.warn("[VoE] Server save error:", err.message);
  });
}

function exportBugs(){
  if(state.bugs.length===0 && state.progression.completions.length===0){
    toast("Nothing to export yet."); return;
  }
  const blob = new Blob([JSON.stringify(buildSession(), null, 2)], {type:"application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "vault-of-echoes-session-" + (state.sessionId||"session").slice(0,8) + ".json";
  a.click();
  URL.revokeObjectURL(url);
}
