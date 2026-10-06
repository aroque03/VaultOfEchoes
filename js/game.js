/* game.js — Game state, level loading, movement, combat, enemies, items */

const cv = document.getElementById("game");
const ctx = cv.getContext("2d");

const state = {
  levelIdx:0, maze:null, plan:null,
  px:1, py:1,
  chests:[], keyFound:false, notesFound:[],
  paused:true, bugs:[],
  keys:new Set(), lastMove:0, moveHist:[],
  enemies:[], alive:true,
  lastEnemyMove:0, swingUntil:0, lastSwing:0, swingTiles:[],
  bugsThisLevel:{}, score:0,
  trophy:null, hiddenRooms:[], gems:[], bruteAlive:true,
  hp:3, iFrameUntil:0, projectiles:[],
  wallClipTile:null, decoyKey:null,
  progression: {
    completions:[], encounters:[], branchOutcomes:{}, branchAttempts:{},
    startTime:0, enemiesKilled:0, bossKilled:false, swordSwung:false,
    levelEngagement:{},
  },
  sessionId:null, sessionStart:null, playerId:null, playerName:null,
};

function resetProgression(){
  return {completions:[], encounters:[], branchOutcomes:{}, branchAttempts:{},
    startTime:Date.now(), enemiesKilled:0, bossKilled:false, swordSwung:false, levelEngagement:{}};
}

// ---------- level loading ----------
function loadLevel(i){
  const c = CHAMBERS[i];
  state.levelIdx = i;
  state.maze = generateMaze(c.cols, c.rows, c.seed);
  state.plan = planChamber(state.maze);
  state.px = state.plan.startTx;
  state.py = state.plan.startTy;
  state.keyFound = false;
  state.moveHist = [[state.px, state.py]];
  state.progression.enemiesKilled = 0;
  state.progression.bossKilled = false;
  state.progression.swordSwung = false;

  const rnd = mulberry32(c.seed ^ 0x5f3759df);
  const spots = state.plan.chestSpots;
  const keyIndex = Math.floor(rnd() * spots.length);
  const lvlNotes = SPINE_NOTES[i];
  let noteIdx = 0;
  state.chests = spots.map((s, idx) => {
    const base = {tx:s.tx, ty:s.ty, trigX:s.trigX, trigY:s.trigY, revealed:false, collected:false, branch:null};
    if(idx === keyIndex) return {...base, type:"key", content:KEY_TEXT, revealed:true};
    return {...base, type:"note", content:lvlNotes[noteIdx++]};
  });

  state.gems = GEM_COLORS.map((color, idx) => ({
    color, idx, x:-1, y:-1, collected:false, spawnTime:0,
  }));

  state.enemies = spawnEnemies(state.maze, state.plan, enemyCountFor(c.cols, c.rows), c.seed);

  const pl = state.plan;
  state.trophy = null;
  state.bruteAlive = false;
  if(pl.brute){
    state.enemies = state.enemies.filter(e => !(e.x===pl.brute.x && e.y===pl.brute.y));
    state.enemies.push({x:pl.brute.x, y:pl.brute.y, dx:pl.brute.dx, dy:pl.brute.dy, hp:BRUTE_HP, tough:true});
    state.bruteAlive = true;
  }

  const noteContents = [ROOM_NOTES_CRACK[i], ROOM_NOTES_AUDIO[i]];
  state.hiddenRooms = state.plan.hiddenRooms.map((hr, idx) => ({
    type: hr.type, entered: false,
    opened: hr.type === "crack",
    revealed: false,
    passX: hr.passX, passY: hr.passY,
    roomX: hr.roomX, roomY: hr.roomY,
    floorX: hr.floorX, floorY: hr.floorY,
    dx: hr.dx, dy: hr.dy,
    triggerX: hr.triggerX || 0, triggerY: hr.triggerY || 0,
    triggerCount: 0,
    note: { x: hr.roomX, y: hr.roomY, content: noteContents[idx], collected: false },
  }));

  state.alive = true;
  state.hp = 3;
  state.iFrameUntil = 0;
  state.projectiles = [];
  state.lastEnemyMove = 0;
  state.swingUntil = 0;
  state.lastSwing = 0;

  // Injected defects
  state.bugsThisLevel = BUGS[i+1] || {};
  state.wallClipTile = null;
  if(state.bugsThisLevel.wallClip){
    const g = state.maze.grid;
    const rng = mulberry32(c.seed ^ 0xBEEF);
    const candidates = [];
    for(let y=1;y<state.maze.TH-1;y++){
      for(let x=1;x<state.maze.TW-1;x++){
        if(g[y][x]!==TILE_WALL) continue;
        let floorNeighbors = 0;
        if(g[y-1][x]===TILE_FLOOR) floorNeighbors++;
        if(g[y+1][x]===TILE_FLOOR) floorNeighbors++;
        if(g[y][x-1]===TILE_FLOOR) floorNeighbors++;
        if(g[y][x+1]===TILE_FLOOR) floorNeighbors++;
        if(floorNeighbors >= 2) candidates.push({x,y});
      }
    }
    if(candidates.length){
      state.wallClipTile = candidates[Math.floor(rng()*candidates.length)];
    }
  }
  if(state.bugsThisLevel.undeadBoss){
    const boss = state.enemies.find(e => e.tough);
    if(boss) boss.buggyUndead = true;
  }
  if(state.bugsThisLevel.stuckKey){
    const rng = mulberry32(c.seed ^ 0xDEAD);
    const g = state.maze.grid;
    const deadEnds = [];
    for(let y=1;y<state.maze.TH-1;y++){
      for(let x=1;x<state.maze.TW-1;x++){
        if(g[y][x]!==TILE_FLOOR) continue;
        if(x===state.maze.sx&&y===state.maze.sy) continue;
        if(x===state.maze.ex&&y===state.maze.ey) continue;
        if(state.chests.some(ch=>ch.tx===x&&ch.ty===y)) continue;
        let n=0;
        if(g[y-1][x]===TILE_FLOOR) n++;
        if(g[y+1][x]===TILE_FLOOR) n++;
        if(g[y][x-1]===TILE_FLOOR) n++;
        if(g[y][x+1]===TILE_FLOOR) n++;
        if(n===1) deadEnds.push({x,y});
      }
    }
    if(deadEnds.length){
      const spot = deadEnds[Math.floor(rng()*deadEnds.length)];
      state.decoyKey = {x:spot.x, y:spot.y, interacted:false};
    } else {
      state.decoyKey = null;
    }
  } else {
    state.decoyKey = null;
  }

  cv.width  = state.maze.TW * TILE;
  cv.height = state.maze.TH * TILE;
  completeNode(nodeId("entry"));
  updateHUD();
}

// ---------- gem system ----------
function randomFloorTile(){
  const {grid, TW, TH} = state.maze;
  const {startTx, startTy, ex, ey} = state.plan;
  const floors = [];
  for(let y=1; y<TH-1; y++){
    for(let x=1; x<TW-1; x++){
      if(grid[y][x] !== TILE_FLOOR) continue;
      if(x===startTx && y===startTy) continue;
      if(x===ex && y===ey) continue;
      floors.push([x,y]);
    }
  }
  return floors[Math.floor(Math.random()*floors.length)];
}

function spawnGem(gem, now){
  const [x,y] = randomFloorTile();
  gem.x = x; gem.y = y;
  gem.spawnTime = now;
}

function stepGems(t){
  for(const gem of state.gems){
    if(gem.collected) continue;
    if(gem.x < 0){
      spawnGem(gem, t);
    } else if(t - gem.spawnTime >= GEM_VISIBLE_MS){
      spawnGem(gem, t);
    } else {
      const dist = Math.abs(state.px - gem.x) + Math.abs(state.py - gem.y);
      if(dist <= GEM_FLEE_DIST && dist > 0 && t - gem.spawnTime >= 500){
        spawnGem(gem, t);
      }
    }
  }
}

function collectGem(gem){
  if(gem.phantom) return;
  gem.collected = true;
  const pts = GEM_POINTS[gem.idx] * (state.levelIdx+1);
  state.score += pts;
  playCoin();
  const names = {ruby:"Ruby", emerald:"Emerald", sapphire:"Sapphire"};
  toast(`${names[gem.color]}! +${pts} points`);
  completeNode(nodeId("chest"));
  markBranchOutcome(nodeId("chest"), "found");
  const collectedCount = state.gems.filter(g => g.collected).length;
  if(state.bugsThisLevel.phantomGem && collectedCount >= 3){
    gem.collected = false;
    gem.phantom = true;
    gem.spawnTime = performance.now();
  }
  updateHUD();
}

// ---------- hidden room helpers ----------
function isCrackRoomEntered(){
  const cr = state.hiddenRooms.find(r => r.type === "crack");
  return cr && cr.entered;
}

function enterHiddenRoom(hr){
  hr.entered = true;
  playCoin();
  toast("You found a hidden room!");
  completeNode(nodeId("room"));
  markBranchOutcome(nodeId("room"), "found");
  updateHUD();
}

// ---------- movement ----------
function isWalkable(x, y){
  const g = state.maze.grid;
  if(!g[y]) return false;
  const t = g[y][x];
  if(t === TILE_FLOOR || t === TILE_PASSAGE) return true;
  if(state.wallClipTile && x===state.wallClipTile.x && y===state.wallClipTile.y) return true;
  return false;
}

function handleHeld(t){
  if(t - state.lastMove < 115) return;
  let dx=0, dy=0;
  const k = state.keys;
  if(k.has("ArrowUp")||k.has("w")) dy=-1;
  else if(k.has("ArrowDown")||k.has("s")) dy=1;
  else if(k.has("ArrowLeft")||k.has("a")) dx=-1;
  else if(k.has("ArrowRight")||k.has("d")) dx=1;
  if(dx===0&&dy===0) return;
  const nx=state.px+dx, ny=state.py+dy;
  if(isWalkable(nx, ny)){
    state.px=nx; state.py=ny; state.lastMove=t;
    recordMove();
    onEnterTile();
    checkEnemyCollision();
  } else {
    logWallBump(nx, ny);
  }
}

function logWallBump(wx, wy){
  for(const hr of state.hiddenRooms){
    if(hr.entered) continue;
    const dist = Math.abs(wx - hr.passX) + Math.abs(wy - hr.passY);
    if(dist <= 2) markBranchOutcome(nodeId("room"), "attempted");
  }
}

// ---------- enemies ----------
function spawnEnemies(maze, plan, count, seed){
  const {grid} = maze;
  const rnd = mulberry32(seed ^ 0x1234abcd);
  const F = (x,y) => isWalkableTile(grid, x, y);
  const cand = [];
  for(let y=1; y<maze.TH-1; y++){
    for(let x=1; x<maze.TW-1; x++){
      if(!F(x,y)) continue;
      const horiz = F(x-1,y) && F(x+1,y) && !F(x,y-1) && !F(x,y+1);
      const vert  = F(x,y-1) && F(x,y+1) && !F(x-1,y) && !F(x+1,y);
      if(horiz) cand.push({x,y,dx:1,dy:0});
      else if(vert) cand.push({x,y,dx:0,dy:1});
    }
  }
  const sx=plan.startTx, sy=plan.startTy;
  let candidatePool = cand.filter(c => Math.abs(c.x-sx)+Math.abs(c.y-sy) >= 5);
  if(candidatePool.length < count) candidatePool = cand.slice();
  for(let i=candidatePool.length-1; i>0; i--){
    const j=Math.floor(rnd()*(i+1));
    [candidatePool[i],candidatePool[j]]=[candidatePool[j],candidatePool[i]];
  }
  const chosen = [];
  const spaced = c => chosen.every(e => Math.abs(e.x-c.x)+Math.abs(e.y-c.y) >= 3);
  for(const c of candidatePool){
    if(chosen.length>=count) break;
    if(!spaced(c)) continue;
    if(rnd()<0.5){ c.dx=-c.dx; c.dy=-c.dy; }
    chosen.push({x:c.x, y:c.y, dx:c.dx, dy:c.dy, hp:1, tough:false});
  }
  for(const c of candidatePool){
    if(chosen.length>=count) break;
    if(!chosen.some(e => e.x===c.x && e.y===c.y))
      chosen.push({x:c.x, y:c.y, dx:c.dx, dy:c.dy, hp:1, tough:false});
  }
  return chosen;
}

function isWalkableTile(grid, x, y){
  if(!grid[y]) return false;
  return grid[y][x] === TILE_FLOOR;
}

function hasLineOfSight(ax, ay, bx, by){
  if(ax !== bx && ay !== by) return false;
  const dx = Math.sign(bx - ax), dy = Math.sign(by - ay);
  let cx = ax + dx, cy = ay + dy;
  while(cx !== bx || cy !== by){
    if(!isWalkableTile(state.maze.grid, cx, cy)) return false;
    cx += dx; cy += dy;
  }
  return true;
}

function stepBossShoot(t){
  for(const e of state.enemies){
    if(!e.tough || e.hp <= 0) continue;
    const los = hasLineOfSight(e.x, e.y, state.px, state.py);
    if(los){
      if(!e.spotTime){ e.spotTime = t; e.aiming = true; }
    } else {
      e.spotTime = 0; e.aiming = false; continue;
    }
    if(t - e.spotTime < BRUTE_AIM_DELAY) continue;
    if(!e.lastShot) e.lastShot = t;
    if(t - e.lastShot < BRUTE_SHOOT_CD) continue;
    e.lastShot = t;
    e.aiming = false;
    const dx = Math.sign(state.px - e.x), dy = Math.sign(state.py - e.y);
    state.projectiles.push({x: e.x + dx, y: e.y + dy, dx, dy, lastStep: t});
  }
}

function stepProjectiles(t){
  const alive = [];
  for(const p of state.projectiles){
    if(t - p.lastStep < PROJECTILE_SPEED){ alive.push(p); continue; }
    p.lastStep = t;
    p.x += p.dx; p.y += p.dy;
    if(!isWalkableTile(state.maze.grid, p.x, p.y)) continue;
    if(p.x === state.px && p.y === state.py){
      checkProjectileHit(); continue;
    }
    alive.push(p);
  }
  state.projectiles = alive;
}

function stepEnemies(){
  for(const e of state.enemies){
    if(e.aiming) continue;
    let nx=e.x+e.dx, ny=e.y+e.dy;
    if(!isWalkableTile(state.maze.grid, nx, ny)){
      e.dx=-e.dx; e.dy=-e.dy;
      nx=e.x+e.dx; ny=e.y+e.dy;
      if(!isWalkableTile(state.maze.grid, nx, ny)) continue;
    }
    e.x=nx; e.y=ny;
  }
  checkEnemyCollision();
}

function checkEnemyCollision(){
  if(!state.alive) return;
  if(state.iFrameUntil && performance.now() < state.iFrameUntil) return;
  const hit = state.enemies.some(e => e.x===state.px && e.y===state.py) ||
              state.projectiles.some(p => p.x===state.px && p.y===state.py);
  if(hit) takeDamage();
}

function checkProjectileHit(){
  if(!state.alive) return;
  if(state.iFrameUntil && performance.now() < state.iFrameUntil) return;
  if(state.projectiles.some(p => p.x===state.px && p.y===state.py)) takeDamage();
}

function takeDamage(){
  if(!state.alive) return;
  state.hp--;
  state.iFrameUntil = performance.now() + 800;
  if(state.hp <= 0) die();
  else toast(`Ouch! ${state.hp} HP remaining.`);
  updateHUD();
}

function die(){
  if(!state.alive) return;
  state.alive = false;
  state.hp = 0;
  state.keys.clear();
  finalizeBranchOutcomes();
  updateHUD();
  showOverlay("over");
}

function reachableTiles(sx, sy, maxDepth){
  const seen = new Set([sx+","+sy]);
  const tiles = [[sx,sy]];
  let frontier = [[sx,sy,0]];
  while(frontier.length){
    const [x,y,d] = frontier.shift();
    if(d>=maxDepth) continue;
    for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){
      const nx=x+dx, ny=y+dy, key=nx+","+ny;
      if(isWalkable(nx, ny) && !seen.has(key)){
        seen.add(key); tiles.push([nx,ny]); frontier.push([nx,ny,d+1]);
      }
    }
  }
  return { seen, tiles };
}

function swingSword(){
  if(state.paused || !state.alive) return;
  const t = performance.now();
  if(t - state.lastSwing < SWORD_COOLDOWN) return;
  state.lastSwing = t;
  state.swingUntil = t + SWORD_FLASH;
  const reach = reachableTiles(state.px, state.py, SWORD_RANGE);
  state.swingTiles = reach.tiles;
  let killed = 0, resisted = false;
  const survivors = [];
  for(const e of state.enemies){
    if(reach.seen.has(e.x+","+e.y)){
      state.progression.swordSwung = true;
      e.hp = (e.hp||1) - 1;
      if(e.hp <= 0){
        if(e.tough){
          killed++;
          state.progression.bossKilled = true;
          completeNode(nodeId("boss"));
          markBranchOutcome(nodeId("boss"), "found");
          if(e.buggyUndead){
            e.hp = 1;
            survivors.push(e);
          } else {
            state.bruteAlive = false;
            state.trophy = {x:e.x, y:e.y, collected:false};
          }
          continue;
        } else {
          killed++;
          state.progression.enemiesKilled++;
          completeNode(nodeId("boss"));
          markBranchOutcome(nodeId("boss"), "found");
          continue;
        }
      } else {
        resisted = true;
        if(e.tough) markBranchOutcome(nodeId("boss"), "attempted");
      }
    }
    survivors.push(e);
  }
  state.enemies = survivors;
  if(killed) toast(killed===1 ? "Enemy slain." : `${killed} enemies slain.`);
  else if(resisted) toast("The brute shrugs it off!");
}

function recordMove(){
  const h = state.moveHist;
  h.push([state.px, state.py]);
  if(h.length > 3) h.shift();
  checkProbeReveal();
}

function checkProbeReveal(){
  const h = state.moveHist;
  if(h.length < 3) return;
  const a=h[2], b=h[1], c=h[0];
  const returned = a[0]===c[0] && a[1]===c[1];
  const movedAway = a[0]!==b[0] || a[1]!==b[1];
  if(!(returned && movedAway)) return;
  for(const ch of state.chests){
    if(!ch.revealed && ch.trigX===a[0] && ch.trigY===a[1]){
      ch.revealed = true;
      playCoin();
      toast("Something shifts nearby — a chest appears.");
    }
  }
}

function revealAllChests(){
  if(state.paused) return;
  let any=false;
  for(const c of state.chests){ if(!c.revealed){ c.revealed=true; any=true; } }
  for(const hr of state.hiddenRooms){
    if(!hr.revealed){
      hr.opened = true; hr.revealed = true;
      state.maze.grid[hr.passY][hr.passX] = TILE_FLOOR;
      any = true;
    }
  }
  toast(any ? "All secrets exposed." : "All secrets already visible.");
}

function onEnterTile(){
  const {ex,ey} = state.plan;

  for(const hr of state.hiddenRooms){
    if(hr.type === "audio" && !hr.opened &&
       state.px === hr.triggerX && state.py === hr.triggerY){
      hr.triggerCount++;
      playRoomCue(hr.triggerCount);
      if(hr.triggerCount >= 3){
        hr.opened = true;
        state.maze.grid[hr.passY][hr.passX] = TILE_FLOOR;
        playRoomOpen();
        toast("A wall grinds open nearby!");
        markBranchOutcome(nodeId("room"), "attempted");
      } else {
        toast(`The stone hums... (${hr.triggerCount}/3)`);
        markBranchOutcome(nodeId("room"), "attempted");
      }
    }

    if(hr.opened && !hr.entered && state.px === hr.passX && state.py === hr.passY){
      enterHiddenRoom(hr);
    }

    if(hr.entered && !hr.note.collected &&
       state.px === hr.note.x && state.py === hr.note.y){
      if(state.bugsThisLevel.missingNote){
        toast("The pedestal is empty...");
      } else {
        hr.note.collected = true;
        if(!state.notesFound.includes(hr.note.content)) state.notesFound.push(hr.note.content);
        openNote(hr.note.content);
        return;
      }
    }
  }

  if(state.trophy && !state.trophy.collected &&
     state.px===state.trophy.x && state.py===state.trophy.y){
    state.trophy.collected = true;
    const pts = BONUS_POINTS * (state.levelIdx+1);
    state.score += pts;
    playCoin();
    toast(`Trophy! +${pts} points`);
    updateHUD();
    return;
  }

  for(const gem of state.gems){
    if(!gem.collected && gem.x===state.px && gem.y===state.py){
      collectGem(gem); return;
    }
  }
  for(const gem of state.gems){
    if(!gem.collected && gem.x >= 0){
      const gd = Math.abs(state.px-gem.x) + Math.abs(state.py-gem.y);
      if(gd <= 2) markBranchOutcome(nodeId("chest"), "attempted");
    }
  }

  if(state.decoyKey && state.px===state.decoyKey.x && state.py===state.decoyKey.y){
    if(!state.decoyKey.interacted){
      state.decoyKey.interacted = true;
      toast("A key! But it's jammed — you can't pull it free.");
    }
  }

  const chest = state.chests.find(c => c.revealed && !c.collected && c.tx===state.px && c.ty===state.py);
  if(chest){
    chest.collected = true;
    if(chest.type==="key"){
      state.keyFound = true;
      completeNode(nodeId("key"));
    } else {
      if(!state.notesFound.includes(chest.content)) state.notesFound.push(chest.content);
      completeNode(nodeId("room"));
      markBranchOutcome(nodeId("room"), "found");
    }
    updateHUD();
    openChest(chest);
    return;
  }

  if(state.px===ex && state.py===ey){
    if(!state.keyFound) toast("The door is locked — find the key.");
    else levelComplete();
  }
}

function levelComplete(){
  completeNode(nodeId("exit"));
  finalizeBranchOutcomes();
  if(state.levelIdx < CHAMBERS.length-1){
    el("levelTitle").textContent = "Chamber Cleared";
    el("levelText").textContent = "The floor opens beneath the door. You descend to the next chamber, deeper into the vault.";
    showOverlay("level");
  } else {
    winGame();
  }
}
