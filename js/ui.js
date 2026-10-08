/* ui.js — Overlays, HUD, rendering, audio, input, login, and boot */

const el = id => document.getElementById(id);
const overlays = {
  login:el("loginOverlay"), intro:el("introOverlay"), tut:el("tutOverlay"), clue:el("clueOverlay"),
  level:el("levelOverlay"), bug:el("bugOverlay"), win:el("winOverlay"),
  over:el("overOverlay"),
};
function showOverlay(name){
  Object.values(overlays).forEach(o=>o.classList.remove("show"));
  if(name){ overlays[name].classList.add("show"); state.paused=true; }
  else state.paused=false;
}

function roomsFoundThisLevel(){
  return state.hiddenRooms.filter(r => r.entered).length;
}

function updateHUD(){
  el("hudLevel").textContent = state.levelIdx+1;
  el("hudHP").textContent = state.hp;
  const done = completedThisLevel();
  el("hudProgress").textContent = `${Math.round(done/7*100)}%`;
  el("hudKey").textContent = state.keyFound ? "✓" : "✕";
  el("hudKey").className = "key" + (state.keyFound?" on":"");
  el("hudRooms").textContent = roomsFoundThisLevel();
  el("hudScore").textContent = state.score;
  el("hudBugs").textContent = state.bugs.length;
  el("exportBtn").disabled = state.bugs.length===0;
}

// ---------- rendering ----------
function draw(){
  const {grid, TW, TH} = state.maze;
  const {ex, ey} = state.plan;
  ctx.clearRect(0,0,cv.width,cv.height);

  for(let y=0;y<TH;y++){
    for(let x=0;x<TW;x++){
      const gx=x*TILE, gy=y*TILE;
      const t = grid[y][x];
      if(t===TILE_WALL || (t===TILE_PASSAGE && !isCrackRoomEntered())){
        ctx.fillStyle="#242b38";
        ctx.fillRect(gx,gy,TILE,TILE);
        ctx.fillStyle="#39435a"; ctx.fillRect(gx,gy,TILE,3);
        ctx.fillStyle="#141821"; ctx.fillRect(gx,gy+TILE-3,TILE,3);
        if(t===TILE_PASSAGE){
          ctx.fillStyle="#2e3850";
          ctx.fillRect(gx+TILE/2-1, gy+4, 2, TILE-8);
        }
      } else {
        ctx.fillStyle="#1b2130";
        ctx.fillRect(gx,gy,TILE,TILE);
        ctx.fillStyle="#222a3c";
        ctx.fillRect(gx+4,gy+5,2,2);
        ctx.fillRect(gx+TILE-7,gy+TILE-8,2,2);
      }
    }
  }

  drawSprite(ctx, state.keyFound?SPR.doorOpen:SPR.doorLocked, ex*TILE, ey*TILE, TILE);

  for(const c of state.chests){
    if(c.revealed && !c.collected) drawSprite(ctx, SPR.chest, c.tx*TILE, c.ty*TILE, TILE);
  }

  if(state.decoyKey){
    drawSprite(ctx, SPR.chest, state.decoyKey.x*TILE, state.decoyKey.y*TILE, TILE);
  }

  if(state.potion && !state.potion.collected){
    drawSprite(ctx, SPR.potion, state.potion.x*TILE, state.potion.y*TILE, TILE);
  }

  const gemSprites = {ruby:SPR.gemRuby, emerald:SPR.gemEmerald, sapphire:SPR.gemSapphire};
  for(const gem of state.gems){
    if(!gem.collected && gem.x >= 0){
      drawSprite(ctx, gemSprites[gem.color], gem.x*TILE, gem.y*TILE, TILE);
    }
  }

  for(const hr of state.hiddenRooms){
    if(hr.revealed && !hr.entered){
      const gx = hr.passX*TILE, gy = hr.passY*TILE;
      ctx.fillStyle = "rgba(120,200,255,0.25)";
      ctx.fillRect(gx, gy, TILE, TILE);
      ctx.strokeStyle = "rgba(120,200,255,0.7)";
      ctx.lineWidth = 2;
      ctx.strokeRect(gx+2, gy+2, TILE-4, TILE-4);
    }
  }

  for(const hr of state.hiddenRooms){
    if(hr.entered && !hr.note.collected){
      drawSprite(ctx, SPR.pedestal, hr.note.x*TILE, hr.note.y*TILE, TILE);
    }
  }

  if(state.trophy && !state.trophy.collected){
    drawSprite(ctx, SPR.trophy, state.trophy.x*TILE, state.trophy.y*TILE, TILE);
  }

  const now = performance.now();
  for(const en of state.enemies){
    if(en.tough && en.hp > 0 && en.spotTime){
      const aimProg = Math.min(1, (now - en.spotTime) / BRUTE_AIM_DELAY);
      const speed = 150 - 100 * aimProg;
      const pulse = (0.2 + 0.2 * aimProg) + 0.15 * Math.sin(now / speed);
      ctx.fillStyle = `rgba(255,60,40,${pulse})`;
      ctx.fillRect(en.x*TILE - 3, en.y*TILE - 3, TILE + 6, TILE + 6);
    }
    const spr = en.green ? SPR.greenBoss : en.tough ? SPR.brute : SPR.enemy;
    drawSprite(ctx, spr, en.x*TILE, en.y*TILE, TILE);
    if(en.tough && en.hp>0){
      const maxHp = en.green ? GREEN_BOSS_HP : BRUTE_HP;
      const pipW = Math.floor(TILE/(maxHp+1));
      for(let h=0; h<en.hp; h++){
        ctx.fillStyle = en.green ? "#4ade80" : "#e2554e";
        ctx.fillRect(en.x*TILE + 2 + h*(pipW+1), en.y*TILE - 4, pipW, 3);
      }
    }
  }

  for(const p of state.projectiles){
    ctx.fillStyle = "#ff4433";
    const cx = p.x*TILE + TILE/2, cy = p.y*TILE + TILE/2;
    ctx.beginPath();
    ctx.arc(cx, cy, TILE/4, 0, Math.PI*2);
    ctx.fill();
    ctx.fillStyle = `rgba(255,100,60,${0.3 + 0.15*Math.sin(now/100)})`;
    ctx.beginPath();
    ctx.arc(cx, cy, TILE/3, 0, Math.PI*2);
    ctx.fill();
  }

  const iFrameActive = state.iFrameUntil && now < state.iFrameUntil;
  if(!iFrameActive || Math.floor(now / 80) % 2 === 0){
    drawSprite(ctx, SPR.player, state.px*TILE, state.py*TILE, TILE);
  }

  const hpBarW = TILE, hpBarH = 3;
  const hpBarX = state.px*TILE, hpBarY = state.py*TILE - 6;
  ctx.fillStyle = "#333";
  ctx.fillRect(hpBarX, hpBarY, hpBarW, hpBarH);
  const hpFrac = Math.max(0, state.hp) / 3;
  ctx.fillStyle = hpFrac > 0.5 ? "#4ade80" : hpFrac > 0.25 ? "#fbbf24" : "#ef4444";
  ctx.fillRect(hpBarX, hpBarY, Math.round(hpBarW * hpFrac), hpBarH);

  if(now < state.swingUntil){
    ctx.fillStyle="rgba(246,210,75,0.16)";
    for(const [x,y] of state.swingTiles){
      ctx.fillRect(x*TILE, y*TILE, TILE, TILE);
    }
    ctx.strokeStyle="rgba(255,240,180,0.95)"; ctx.lineWidth=3;
    ctx.beginPath();
    ctx.moveTo(state.px*TILE, (state.py+1)*TILE);
    ctx.lineTo((state.px+1)*TILE, state.py*TILE);
    ctx.stroke();
  }
}

function loop(t){
  if(state.paused || !state.alive){
    state.lastEnemyMove = t;
  } else {
    handleHeld(t);
    if(t - state.lastEnemyMove >= ENEMY_INTERVAL){ state.lastEnemyMove = t; stepEnemies(); }
    stepBossShoot(t);
    stepProjectiles(t);
    stepGems(t);
    draw();
  }
  requestAnimationFrame(loop);
}

// ---------- overlays ----------
function openChest(chest){
  if(chest.type==="key"){
    el("clueTitle").textContent = "Treasure — the Iron Key";
    el("clueText").textContent = KEY_TEXT;
  } else {
    el("clueTitle").textContent = "Treasure — a note";
    el("clueText").textContent = chest.content;
  }
  showOverlay("clue");
}

function openNote(content){
  el("clueTitle").textContent = "Wren's Journal";
  el("clueText").textContent = content;
  showOverlay("clue");
}

function winGame(){
  const TOTAL_NOTES = 12;
  const found = state.notesFound.length;
  const ul = el("winClues"); ul.innerHTML="";

  if(found === TOTAL_NOTES){
    el("winTitle").textContent = "The Mystery Resolved";
    el("winNarrative").innerHTML = "You collected every page of Wren's journal. The story is clear: <b>Wren mapped the vault, discovered it was alive, and chose to stay</b> — leaving notes so the next person could escape safely. Wren's sacrifice kept the village safe. You carry the truth home.";
  } else if(found > 0){
    el("winTitle").textContent = "You Escaped";
    el("winNarrative").textContent = "You turn the iron key. The last door groans open to daylight. You escaped the vault, but pieces of Wren's story remain hidden in the chambers behind you. The mystery is not yet solved.";
  } else {
    el("winTitle").textContent = "You Escaped";
    el("winNarrative").textContent = "You turn the iron key. The last door groans open to daylight. The Vault of Echoes falls silent behind you. You never found Wren's journal — the mystery of your mentor's disappearance remains unsolved.";
  }

  el("winNoteCount").textContent = `Journal pages found: ${found} / ${TOTAL_NOTES}`;
  const notes = state.notesFound.length ? state.notesFound
    : ["(You escaped without reading any of Wren's notes.)"];
  notes.forEach(c=>{
    const li=document.createElement("li"); li.textContent=c.replace(/\n/g," "); ul.appendChild(li);
  });
  const byImpact = state.bugs.reduce((a,b)=>(a[b.impact_rating]=(a[b.impact_rating]||0)+1,a),{});
  const impStr = Object.keys(byImpact).sort().map(s=>`impact${s}:${byImpact[s]}`).join("  ");
  el("winStats").textContent = `Score: ${state.score}  ·  Bugs reported: ${state.bugs.length}${impStr?"  ("+impStr+")":""}`;

  const bo = state.progression.branchOutcomes;
  const rf = state.progression.roomsFound || {};
  const branchLines = [];
  for(let lvl=1; lvl<=3; lvl++){
    const parts = [];
    const rooms = rf["l"+lvl];
    parts.push("Rooms:"+(rooms ? rooms.found+"/"+rooms.total : "?"));
    for(const phase of ["chest","boss"]){
      const nid = "l"+lvl+"."+phase;
      const outcome = bo[nid] || "never_approached";
      const label = phase==="chest"?"Gems":"Boss";
      parts.push(label+":"+outcome);
    }
    branchLines.push("L"+lvl+" "+parts.join(" "));
  }
  el("winBranches").textContent = branchLines.join("  ·  ");

  const session = buildSession();
  console.log("%c[VoE] Session complete — full data:", "color:#f2a03d;font-weight:bold");
  console.log(JSON.stringify(session, null, 2));
  showOverlay("win");
}

// ---------- bug reporting ----------
let bugSev = null;
function openBugForm(){
  if(state.paused) return;
  bugSev = null;
  el("bugDesc").value = "";
  el("bugCategory").value = "Movement/Collision";
  document.querySelectorAll("#sevGroup button").forEach(b=>b.classList.remove("sel"));
  el("sevHint").textContent = "";
  el("bugSubmit").disabled = true;
  const now = new Date();
  const done = completedNodes();
  el("bugCtx").innerHTML =
    `Chamber <b>${state.levelIdx+1}</b> · tile <b>(${state.px}, ${state.py})</b> · ` +
    `nodes <b>${done.length}/21</b> · key <b>${state.keyFound?"yes":"no"}</b><br>` +
    `${now.toLocaleTimeString()}`;
  showOverlay("bug");
  setTimeout(()=>el("bugDesc").focus(), 30);
}
function validateBug(){
  el("bugSubmit").disabled = !(el("bugDesc").value.trim() && bugSev);
}
function submitBug(){
  const bug = {
    id: state.bugs.length+1,
    bug_id: "b-"+(state.bugs.length+1)+"-l"+(state.levelIdx+1),
    chamber: state.levelIdx+1,
    seed: CHAMBERS[state.levelIdx].seed,
    tileX: state.px, tileY: state.py,
    category: el("bugCategory").value,
    impact_rating: bugSev,
    severity: bugSev,
    description: el("bugDesc").value.trim(),
    completed_nodes: completedNodes(),
    injectedBugs: activeBugsForLevel(state.levelIdx+1),
    timestamp: new Date().toISOString(),
  };
  state.bugs.push(bug);
  updateHUD();
  showOverlay(null);
  toast(`Bug #${bug.id} logged (impact ${bug.impact_rating}).`);
}

// ---------- audio ----------
let audioCtx = null;
function ensureAudio(){
  if(!audioCtx){
    try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch(e){ audioCtx = null; }
  }
  if(audioCtx && audioCtx.state === "suspended") audioCtx.resume();
}
function playCoin(){
  if(!audioCtx) return;
  const now = audioCtx.currentTime;
  const g = audioCtx.createGain();
  g.gain.setValueAtTime(0.0001, now);
  g.gain.exponentialRampToValueAtTime(0.22, now + 0.01);
  g.connect(audioCtx.destination);
  const o = audioCtx.createOscillator();
  o.type = "square";
  o.frequency.setValueAtTime(988, now);
  o.frequency.setValueAtTime(1319, now + 0.08);
  o.connect(g);
  o.start(now);
  g.gain.setValueAtTime(0.22, now + 0.08);
  g.gain.exponentialRampToValueAtTime(0.0001, now + 0.30);
  o.stop(now + 0.32);
}

function playRoomCue(count){
  if(!audioCtx) return;
  const now = audioCtx.currentTime;
  const g = audioCtx.createGain();
  g.gain.setValueAtTime(0.0001, now);
  g.gain.exponentialRampToValueAtTime(0.18, now + 0.02);
  g.connect(audioCtx.destination);
  const o = audioCtx.createOscillator();
  o.type = "sine";
  const freq = 220 * (1 + count * 0.5);
  o.frequency.setValueAtTime(freq, now);
  o.frequency.exponentialRampToValueAtTime(freq * 1.05, now + 0.3);
  o.connect(g);
  o.start(now);
  g.gain.setValueAtTime(0.18, now + 0.25);
  g.gain.exponentialRampToValueAtTime(0.0001, now + 0.6);
  o.stop(now + 0.62);
}

function playHeal(){
  if(!audioCtx) return;
  const now = audioCtx.currentTime;
  const g = audioCtx.createGain();
  g.gain.setValueAtTime(0.0001, now);
  g.gain.exponentialRampToValueAtTime(0.20, now + 0.02);
  g.connect(audioCtx.destination);
  const o = audioCtx.createOscillator();
  o.type = "sine";
  o.frequency.setValueAtTime(523, now);
  o.frequency.setValueAtTime(659, now + 0.1);
  o.frequency.setValueAtTime(784, now + 0.2);
  o.connect(g);
  o.start(now);
  g.gain.setValueAtTime(0.20, now + 0.25);
  g.gain.exponentialRampToValueAtTime(0.0001, now + 0.5);
  o.stop(now + 0.52);
}

function playRoomOpen(){
  if(!audioCtx) return;
  const now = audioCtx.currentTime;
  const g = audioCtx.createGain();
  g.gain.setValueAtTime(0.0001, now);
  g.gain.exponentialRampToValueAtTime(0.25, now + 0.03);
  g.connect(audioCtx.destination);
  const o = audioCtx.createOscillator();
  o.type = "triangle";
  o.frequency.setValueAtTime(440, now);
  o.frequency.exponentialRampToValueAtTime(880, now + 0.2);
  o.connect(g);
  o.start(now);
  g.gain.setValueAtTime(0.25, now + 0.2);
  g.gain.exponentialRampToValueAtTime(0.0001, now + 0.5);
  o.stop(now + 0.52);
}

// ---------- ambient music ----------
let ambientNodes = null;
let musicMuted = false;
function startMusic(level){
  stopMusic();
  if(!audioCtx || musicMuted) return;

  const master = audioCtx.createGain();
  master.gain.value = 0.18;
  master.connect(audioCtx.destination);

  // delay for echo
  const delay = audioCtx.createDelay(1.0);
  delay.delayTime.value = 0.4;
  const fb = audioCtx.createGain();
  fb.gain.value = 0.35;
  const delayGain = audioCtx.createGain();
  delayGain.gain.value = 0.25;
  delay.connect(fb); fb.connect(delay);
  delay.connect(delayGain); delayGain.connect(master);

  // low drone pad
  const droneGain = audioCtx.createGain();
  droneGain.gain.value = 0.12;
  droneGain.connect(master);
  const droneFilter = audioCtx.createBiquadFilter();
  droneFilter.type = "lowpass";
  droneFilter.frequency.value = 200;
  droneFilter.connect(droneGain);
  const droneFreqs = [55, 58.27, 51.91]; // A1, Bb1, Ab1
  const droneOscs = [];
  for(let i=0; i<2; i++){
    const o = audioCtx.createOscillator();
    o.type = i===0 ? "sawtooth" : "triangle";
    o.frequency.value = droneFreqs[level % droneFreqs.length] * (i===0 ? 1 : 1.002);
    o.connect(droneFilter);
    o.start();
    droneOscs.push(o);
  }

  // LFO on drone filter for slow sweep
  const lfo = audioCtx.createOscillator();
  lfo.type = "sine";
  lfo.frequency.value = 0.15;
  const lfoGain = audioCtx.createGain();
  lfoGain.gain.value = 80;
  lfo.connect(lfoGain);
  lfoGain.connect(droneFilter.frequency);
  lfo.start();

  // arpeggio sequencer — minor pentatonic
  const scales = [
    [130.81,155.56,174.61,196.00,233.08,261.63,311.13],  // C minor pent + octave
    [138.59,164.81,185.00,207.65,246.94,277.18,329.63],   // Db minor
    [123.47,146.83,164.81,185.00,220.00,246.94,293.66],   // B minor
  ];
  const notes = scales[level % scales.length];
  const patterns = [
    [0,2,4,5,3,1,2,4],
    [0,3,5,4,2,6,3,1],
    [0,4,2,5,1,3,6,2],
  ];
  const pat = patterns[level % patterns.length];
  const tempo = [0.55, 0.5, 0.45][level % 3];
  let step = 0;
  let arpRunning = true;

  function playArpNote(){
    if(!arpRunning || !audioCtx) return;
    const freq = notes[pat[step % pat.length]];
    const now = audioCtx.currentTime;

    const o = audioCtx.createOscillator();
    o.type = step % 3 === 0 ? "triangle" : "sine";
    o.frequency.value = freq;

    const g = audioCtx.createGain();
    g.gain.setValueAtTime(0.0001, now);
    g.gain.exponentialRampToValueAtTime(0.08, now + 0.03);
    g.gain.setValueAtTime(0.08, now + tempo * 0.6);
    g.gain.exponentialRampToValueAtTime(0.0001, now + tempo * 0.95);

    o.connect(g);
    g.connect(master);
    g.connect(delay);
    o.start(now);
    o.stop(now + tempo);

    // occasional high harmonic
    if(step % 7 === 3){
      const h = audioCtx.createOscillator();
      h.type = "sine";
      h.frequency.value = freq * 2;
      const hg = audioCtx.createGain();
      hg.gain.setValueAtTime(0.0001, now);
      hg.gain.exponentialRampToValueAtTime(0.03, now + 0.05);
      hg.gain.setValueAtTime(0.03, now + tempo * 0.5);
      hg.gain.exponentialRampToValueAtTime(0.0001, now + tempo * 0.9);
      h.connect(hg); hg.connect(master); hg.connect(delay);
      h.start(now); h.stop(now + tempo);
    }

    step++;
    ambientNodes._timer = setTimeout(playArpNote, tempo * 1000);
  }

  ambientNodes = {master, droneOscs, lfo, delay, fb, delayGain, droneGain, droneFilter, lfoGain, _timer:null,
    stop(){ arpRunning = false; clearTimeout(this._timer);
      droneOscs.forEach(o=>{ try{o.stop();}catch(e){} });
      try{lfo.stop();}catch(e){}
      master.disconnect();
    }};
  playArpNote();
}

function stopMusic(){
  if(ambientNodes){ ambientNodes.stop(); ambientNodes = null; }
}

function toggleMusic(){
  musicMuted = !musicMuted;
  el("musicBtn").textContent = musicMuted ? "♪ OFF" : "♪ ON";
  if(musicMuted) stopMusic();
  else if(!state.paused) startMusic(state.levelIdx);
}

// ---------- toast ----------
let toastTimer=null;
function toast(msg){
  const t=el("toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove("show"), 2200);
}

// ---------- input wiring ----------
const MOVE_KEYS = new Set(["ArrowUp","ArrowDown","ArrowLeft","ArrowRight","w","a","s","d","W","A","S","D"]);
window.addEventListener("keydown", e=>{
  ensureAudio();
  const anyOverlay = Object.values(overlays).some(o=>o.classList.contains("show"));
  if(e.key==="Escape"){
    if(overlays.bug.classList.contains("show")) showOverlay(null);
    return;
  }
  if(anyOverlay) return;
  const key = e.key.length===1 ? e.key.toLowerCase() : e.key;
  if(MOVE_KEYS.has(e.key)){ state.keys.add(key); e.preventDefault(); }
  if(key==="b"){ openBugForm(); e.preventDefault(); }
  if(key==="x"){ revealAllChests(); e.preventDefault(); }
  if(e.code==="Space"){ swingSword(); e.preventDefault(); }
});
window.addEventListener("keyup", e=>{
  const key = e.key.length===1 ? e.key.toLowerCase() : e.key;
  state.keys.delete(key);
});
function clearKeys(){ state.keys.clear(); }

// severity buttons
document.querySelectorAll("#sevGroup button").forEach(btn=>{
  btn.addEventListener("click", ()=>{
    bugSev = parseInt(btn.dataset.sev,10);
    document.querySelectorAll("#sevGroup button").forEach(b=>b.classList.remove("sel"));
    btn.classList.add("sel");
    el("sevHint").textContent = SEV_HINT[bugSev];
    validateBug();
  });
});
el("bugDesc").addEventListener("input", validateBug);
el("bugSubmit").addEventListener("click", submitBug);
el("bugCancel").addEventListener("click", ()=>showOverlay(null));
el("exportBtn").addEventListener("click", exportBugs);
el("musicBtn").addEventListener("click", toggleMusic);
el("winExport").addEventListener("click", exportBugs);

// ---------- login ----------
async function hashPlayerId(firstName, lastInitial, studentId){
  const raw = `${firstName.trim().toLowerCase()}|${lastInitial.trim().toUpperCase()}|${studentId.trim()}`;
  const buf = new TextEncoder().encode(raw);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  const arr = Array.from(new Uint8Array(hash));
  return arr.slice(0,8).map(b=>b.toString(16).padStart(2,"0")).join("");
}

el("loginBtn").addEventListener("click", async ()=>{
  const first = el("loginFirst").value.trim();
  const lastInit = el("loginLastInit").value.trim();
  const sid = el("loginStudentId").value.trim();
  if(!first || !lastInit || !sid){
    el("loginError").style.display = "";
    return;
  }
  el("loginError").style.display = "none";
  state.playerId = await hashPlayerId(first, lastInit, sid);
  state.playerName = first;
  showOverlay("intro");
});

// ---------- flow buttons ----------
el("introNext").addEventListener("click", ()=>{ showOverlay("tut"); });
el("startBtn").addEventListener("click", ()=>{
  ensureAudio();
  state.progression = resetProgression();
  state.notesFound = [];
  state.bugs = [];
  state.score = 0;
  loadLevel(0);
  clearKeys();
  showOverlay(null);
  startMusic(0);
});
el("clueBtn").addEventListener("click", ()=>{ clearKeys(); showOverlay(null); });
el("levelBtn").addEventListener("click", ()=>{
  if(state.levelIdx >= CHAMBERS.length-1){
    stopMusic();
    showOverlay(null);
    winGame();
  } else {
    loadLevel(state.levelIdx+1);
    clearKeys();
    showOverlay(null);
    startMusic(state.levelIdx);
  }
});
el("winReplay").addEventListener("click", ()=>{
  state.progression = resetProgression();
  state.notesFound=[]; state.bugs=[]; state.keyFound=false;
  state.score=0;
  loadLevel(0); clearKeys(); showOverlay(null);
  startMusic(0);
});
el("overRetry").addEventListener("click", ()=>{
  loadLevel(state.levelIdx); clearKeys(); showOverlay(null);
  startMusic(state.levelIdx);
});
el("overRestart").addEventListener("click", ()=>{
  state.progression = resetProgression();
  state.notesFound=[]; state.keyFound=false;
  state.score=0;
  loadLevel(0); clearKeys(); showOverlay(null);
});

// ---------- boot ----------
state.sessionId = (()=>{ try { if(crypto && crypto.randomUUID) return crypto.randomUUID(); } catch(e){} return "sess-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2,10); })();
state.sessionStart = new Date().toISOString();
state.progression.startTime = Date.now();
if(SHOW_QA_BADGE && anyBugConfigured()) el("qaBadge").style.display = "";
loadLevel(0);
draw();
requestAnimationFrame(loop);
