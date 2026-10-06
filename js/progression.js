/* progression.js — Node tracking, player type classification, session export */

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
  for(const phase of ["room","chest","boss"]){
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
    player: { id: state.playerId || state.sessionId },
    session: {
      build: "voe-study-1.0",
      seed: CHAMBERS[0].seed,
      started_at: state.sessionStart,
      ended_at: new Date().toISOString(),
    },
    node_completions: state.progression.completions,
    bug_encounters: state.progression.encounters,
    bug_reports: state.bugs,
    branch_outcomes: state.progression.branchOutcomes,
    rooms_found: state.progression.roomsFound || {},
    level_engagement: state.progression.levelEngagement || {},
    player_type: classifyPlayerType(),
    injectedConfig: injectedConfigAll(),
    finalScore: state.score,
  };
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
