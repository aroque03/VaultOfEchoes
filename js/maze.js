/* maze.js — Maze generation and chamber planning */

function generateMaze(cols, rows, seed){
  const rnd = mulberry32(seed);
  const cells = Array.from({length:rows}, ()=>Array.from({length:cols}, ()=>({v:false,N:false,S:false,E:false,W:false})));
  const stack = [[0,0]];
  cells[0][0].v = true;
  const dirs = [["N",0,-1],["S",0,1],["E",1,0],["W",-1,0]];
  const opp = {N:"S",S:"N",E:"W",W:"E"};
  while(stack.length){
    const [cx,cy] = stack[stack.length-1];
    const nbrs = [];
    for(const [d,dx,dy] of dirs){
      const nx=cx+dx, ny=cy+dy;
      if(nx>=0&&nx<cols&&ny>=0&&ny<rows&&!cells[ny][nx].v) nbrs.push([d,nx,ny]);
    }
    if(nbrs.length===0){ stack.pop(); continue; }
    const [d,nx,ny] = nbrs[Math.floor(rnd()*nbrs.length)];
    cells[cy][cx][d]=true;
    cells[ny][nx][opp[d]]=true;
    cells[ny][nx].v=true;
    stack.push([nx,ny]);
  }
  const TW = cols*2+1, TH = rows*2+1;
  const grid = Array.from({length:TH}, ()=>Array(TW).fill(TILE_WALL));
  for(let cy=0;cy<rows;cy++){
    for(let cx=0;cx<cols;cx++){
      const tx=cx*2+1, ty=cy*2+1;
      grid[ty][tx]=TILE_FLOOR;
      if(cells[cy][cx].N) grid[ty-1][tx]=TILE_FLOOR;
      if(cells[cy][cx].S) grid[ty+1][tx]=TILE_FLOOR;
      if(cells[cy][cx].E) grid[ty][tx+1]=TILE_FLOOR;
      if(cells[cy][cx].W) grid[ty][tx-1]=TILE_FLOOR;
    }
  }
  return { grid, TW, TH, cols, rows, cells };
}

function bfs(grid, sx, sy){
  const H=grid.length, W=grid[0].length;
  const dist=Array.from({length:H},()=>Array(W).fill(-1));
  const par=Array.from({length:H},()=>Array(W).fill(null));
  const q=[[sx,sy]]; dist[sy][sx]=0;
  const dirs=[[1,0],[-1,0],[0,1],[0,-1]];
  while(q.length){
    const [x,y]=q.shift();
    for(const [dx,dy] of dirs){
      const nx=x+dx, ny=y+dy;
      if(nx<0||ny<0||nx>=W||ny>=H) continue;
      if(grid[ny][nx]===TILE_WALL||dist[ny][nx]!==-1) continue;
      dist[ny][nx]=dist[y][x]+1; par[ny][nx]=[x,y]; q.push([nx,ny]);
    }
  }
  return {dist, par};
}

function planChamber(maze){
  const {grid, TW, TH} = maze;
  const startTx=1, startTy=1;
  const {dist, par} = bfs(grid, startTx, startTy);

  let ex=startTx, ey=startTy, best=-1;
  for(let y=0;y<TH;y++)for(let x=0;x<TW;x++){
    if(grid[y][x]===TILE_FLOOR && dist[y][x]>best){best=dist[y][x];ex=x;ey=y;}
  }

  const onPath=new Set();
  let cur=[ex,ey];
  while(cur){ onPath.add(cur[0]+","+cur[1]); cur=par[cur[1]][cur[0]]; }

  const deadEnds=[];
  for(let y=0;y<TH;y++)for(let x=0;x<TW;x++){
    if(grid[y][x]!==TILE_FLOOR) continue;
    let n=0;
    for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]])
      if(grid[y+dy]&&grid[y+dy][x+dx]===TILE_FLOOR) n++;
    if(n===1) deadEnds.push([x,y]);
  }

  const isBlocked = (x,y) => (x===startTx&&y===startTy) || (x===ex&&y===ey);
  const chDist = (a,b) => Math.max(Math.abs(a[0]-b[0]), Math.abs(a[1]-b[1]));

  let pool = deadEnds.filter(([x,y]) => !isBlocked(x,y) && !onPath.has(x+","+y));
  if(pool.length < SPINE_CHESTS_PER_LEVEL + 2){
    pool = deadEnds.filter(([x,y]) => !isBlocked(x,y));
  }
  pool.sort((a,b) => dist[b[1]][b[0]] - dist[a[1]][a[0]]);

  const usedSpots = [];
  function pickSpot(minDist){
    for(const cand of pool){
      if(usedSpots.some(c => chDist(c, cand) < (minDist||3))) continue;
      usedSpots.push(cand);
      return cand;
    }
    for(const cand of pool){
      if(!usedSpots.some(c => c[0]===cand[0] && c[1]===cand[1])){
        usedSpots.push(cand);
        return cand;
      }
    }
    return null;
  }

  const chestTiles = [];
  for(let i=0; i<SPINE_CHESTS_PER_LEVEL; i++){
    const s = pickSpot(3);
    if(s) chestTiles.push(s);
  }

  let bruteSpot = null;
  for(const cand of pool){
    if(usedSpots.some(c => c[0]===cand[0] && c[1]===cand[1])) continue;
    if(onPath.has(cand[0]+","+cand[1])) continue;
    if(usedSpots.every(c => chDist(c, cand) >= 3)){
      bruteSpot = cand; usedSpots.push(cand); break;
    }
  }
  if(!bruteSpot){
    for(const cand of pool){
      if(usedSpots.some(c => c[0]===cand[0] && c[1]===cand[1])) continue;
      if(!onPath.has(cand[0]+","+cand[1])){
        bruteSpot = cand; usedSpots.push(cand); break;
      }
    }
  }

  function triggerFor(tx, ty){
    let trigX=tx, trigY=ty, bd=Infinity;
    for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){
      const nx=tx+dx, ny=ty+dy;
      if(grid[ny] && grid[ny][nx]===TILE_FLOOR && dist[ny][nx]>=0 && dist[ny][nx]<bd){
        bd=dist[ny][nx]; trigX=nx; trigY=ny;
      }
    }
    return { tx, ty, trigX, trigY };
  }

  const chestSpots = chestTiles.map(([tx,ty]) => triggerFor(tx, ty));

  let brute = null;
  if(bruteSpot){
    const [bx,by] = bruteSpot;
    let ax=bx, ay=by, bd=Infinity;
    for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){
      const nx=bx+dx, ny=by+dy;
      if(grid[ny] && grid[ny][nx]===TILE_FLOOR && dist[ny][nx]>=0 && dist[ny][nx]<bd){
        bd=dist[ny][nx]; ax=nx; ay=ny;
      }
    }
    brute = { x:ax, y:ay, dx:ax-bx, dy:ay-by, trophyX:bx, trophyY:by };
  }

  // Hidden rooms (Explorer branch): 2 per level
  const rnd = mulberry32(maze.cols * maze.rows);

  const deep3 = [];
  const deep2 = [];
  for(let y=2; y<TH-2; y++){
    for(let x=2; x<TW-2; x++){
      if(grid[y][x] !== TILE_WALL) continue;
      for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){
        const fx=x-dx, fy=y-dy;
        if(fx<0||fy<0||fx>=TW||fy>=TH) continue;
        if(grid[fy][fx]!==TILE_FLOOR) continue;
        const w1x=x+dx, w1y=y+dy;
        if(w1x<1||w1y<1||w1x>=TW-1||w1y>=TH-1) continue;
        if(grid[w1y][w1x]!==TILE_WALL) continue;
        const px2=dy, py2=dx;
        const perpOk2 = (!grid[w1y+py2] || grid[w1y+py2][w1x+px2]!==TILE_FLOOR)
                      && (!grid[w1y-py2] || grid[w1y-py2][w1x-px2]!==TILE_FLOOR);
        if(perpOk2){
          deep2.push({passX:x, passY:y, floorX:fx, floorY:fy,
                      roomX:w1x, roomY:w1y, dx, dy, depth:2});
        }
        const w2x=x+2*dx, w2y=y+2*dy;
        if(w2x<1||w2y<1||w2x>=TW-1||w2y>=TH-1) continue;
        if(grid[w2y][w2x]!==TILE_WALL) continue;
        const px3=dy, py3=dx;
        const perpOk3 = (!grid[w2y+py3] || grid[w2y+py3][w2x+px3]!==TILE_FLOOR)
                      && (!grid[w2y-py3] || grid[w2y-py3][w2x-px3]!==TILE_FLOOR);
        if(perpOk3){
          deep3.push({passX:x, passY:y, floorX:fx, floorY:fy,
                      roomX:w2x, roomY:w2y, dx, dy, depth:3});
        }
      }
    }
  }

  function shuffle(arr){
    for(let i=arr.length-1; i>0; i--){
      const j=Math.floor(rnd()*(i+1));
      [arr[i],arr[j]]=[arr[j],arr[i]];
    }
  }
  shuffle(deep3); shuffle(deep2);

  const hiddenRooms = [];
  const usedPassages = new Set();

  function pickRoom(pool){
    for(const wc of pool){
      if(usedPassages.has(wc.passX+","+wc.passY)) continue;
      const farEnough = usedSpots.every(s => chDist(s, [wc.passX, wc.passY]) >= 2)
        && hiddenRooms.every(h => chDist([h.passX, h.passY], [wc.passX, wc.passY]) >= 3);
      if(farEnough){ usedPassages.add(wc.passX+","+wc.passY); return wc; }
    }
    for(const wc of pool){
      if(usedPassages.has(wc.passX+","+wc.passY)) continue;
      usedPassages.add(wc.passX+","+wc.passY);
      return wc;
    }
    return null;
  }

  const crack = pickRoom(deep3) || pickRoom(deep2);
  if(crack){
    crack.type = "crack";
    hiddenRooms.push(crack);
    grid[crack.passY][crack.passX] = TILE_PASSAGE;
    if(crack.depth === 3){
      const midX = crack.passX + crack.dx, midY = crack.passY + crack.dy;
      grid[midY][midX] = TILE_FLOOR;
    }
    grid[crack.roomY][crack.roomX] = TILE_FLOOR;
  }

  const audio = pickRoom(deep2) || pickRoom(deep3);
  if(audio){
    audio.type = "audio";
    hiddenRooms.push(audio);
    if(audio.depth === 3){
      const midX = audio.passX + audio.dx, midY = audio.passY + audio.dy;
      grid[midY][midX] = TILE_FLOOR;
    }
    grid[audio.roomY][audio.roomX] = TILE_FLOOR;
    audio.triggerX = audio.floorX;
    audio.triggerY = audio.floorY;
  }

  return { startTx, startTy, ex, ey, chestSpots, brute, hiddenRooms, dist };
}
