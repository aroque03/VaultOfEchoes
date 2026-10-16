/* config.js — Constants, sprites, level data, bug injection, and text content */

// ---------- seeded RNG (mulberry32) ----------
function mulberry32(seed){
  return function(){
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

// ---------- chamber definitions (cells, not tiles) ----------
const CHAMBERS = [
  { seed: 1207, cols: 8,  rows: 7  },
  { seed: 4519, cols: 11, rows: 9  },
  { seed: 9021, cols: 14, rows: 11 },
];

const SPINE_CHESTS_PER_LEVEL = 3;
const TILE_WALL = 1;
const TILE_FLOOR = 0;
const TILE_PASSAGE = 2;
const TILE = 22;

const GEMS_PER_LEVEL = 3;
const GEM_VISIBLE_MS = 4000;      // how long a gem stays in one spot
const GEM_FLEE_DIST = 2;          // gem jumps away when the player gets this close...
const GEM_FLEE_GRACE_MS = 1500;   // ...but not during this long after it appears
const GEM_COLORS = ["ruby","emerald","sapphire"];
const GEM_POINTS = [100, 150, 200];

const BONUS_POINTS = 250;
const BRUTE_HP = 3;
const BRUTE_SHOOT_CD = 1200;
const BRUTE_AIM_DELAY = 400;
const PROJECTILE_SPEED = 180;

const enemyCountFor = (cols, rows) => Math.max(1, Math.round((cols*rows)/28));
const ENEMY_INTERVAL = 340;
const SWORD_RANGE = 1;
const SWORD_COOLDOWN = 260;
const SWORD_FLASH = 200;

// ---------- story text ----------
const SPINE_NOTES = [
  [
    "Wren's journal: \"The village asked me to chart these tunnels after the third disappearance. I told them I would be back by morning.\"",
    "Wren's journal: \"My apprentice would laugh at me — I always said 'never map alone.' I can hear my own advice echoing off these walls.\"",
  ],
  [
    "Wren's journal: \"The walls shifted behind me. I am certain now: this vault rearranges itself. My maps from yesterday are already wrong.\"",
    "Wren's journal: \"I found old bones near a locked door. Someone else's torch. They got this far, too. They did not get further.\"",
  ],
  [
    "Wren's journal: \"I understand now. The vault does not trap people — it tests them. Every room is a question. Every key is an answer.\"",
    "Wren's journal: \"I could leave. The final door is open. But if I go, the vault resets and the next person walks in blind. So I am leaving these notes instead.\"",
  ],
];

const ROOM_NOTES_CRACK = [
  "Wren's journal: \"I pressed my hand against a crack in the wall and it gave way. Behind it, a small chamber with air that tasted old. The vault has rooms it hides even from itself.\"",
  "Wren's journal: \"More hidden rooms. I think these are the vault's mistakes — places it forgot to seal. I am mapping every one. Mistakes are how you find the truth.\"",
  "Wren's journal: \"The deepest hidden room had carvings on the floor. A name I could not read, and below it: 'I stayed so you could leave.' Someone chose this before me.\"",
];

const ROOM_NOTES_AUDIO = [
  "Wren's journal: \"The stones hum where they are thin. I walked over the same tile three times before the wall opened. The vault listens to footsteps.\"",
  "Wren's journal: \"Every chamber has a frequency — a tone the walls respond to. Walk with patience and the vault reveals what it keeps hidden from those who rush.\"",
  "Wren's journal: \"The final humming stone played a note I recognized. It was the lullaby my mother sang. The vault knows things it should not know. I am not afraid. I am awed.\"",
];

const KEY_TEXT = "An iron key, warm from the dark. This chamber's door will open now.";

const SEV_HINT = {
  1:"Very little impact on my enjoyment.",
  2:"Little impact on my enjoyment.",
  3:"Moderate impact on my enjoyment.",
  4:"High impact on my enjoyment.",
  5:"Extremely high impact on my enjoyment.",
};

// ---------- QA bug injection ----------
// Default placement follows the study's bug table (`levels` per bug). Override via URL:
//   all chambers: ?bugs=all   ?bugs=wall,gem   (only those)   ?bugs=none   (disable all)
//   per chamber:  ?l1=wall,gem&l2=none&l3=all
const GREEN_BOSS_HP = 5;
const INVISIBLE_STEPS = 5;   // invisiblePlayer: avatar reappears after this many steps

// Single source of truth for injected bugs (also read by admin.html).
const BUG_CATALOG = {
  wallClip:    { key:"wall",    node:"entry", levels:[1,2,3], desc:"Some wall tiles can be walked through (1 per chamber number)." },
  phantomWall: { key:"pwall",   node:"room",  levels:[1,3],   desc:"Invisible wall blocks a dead-end corridor tile (3 in chamber 3)." },
  invisiblePlayer: { key:"invis", node:"room", levels:[1,2], desc:"Opening the chest in the hidden room furthest from the start makes the avatar invisible on the main map for the next 5 steps (HP bar stays)." },
  phantomGem:  { key:"gem",     node:"chest", levels:[2],     desc:"After all 3 gems are collected, one reappears uncollected." },
  corruptNote: { key:"corrupt", node:"chest", levels:[3],     desc:"First chest note shows a fake error stack trace instead of its text." },
  undeadBoss:  { key:"boss",    node:"boss",  levels:[2,3],   nodeByLevel:{3:"greenBoss"}, desc:"Boss survives at 1 HP after being killed (chamber 3: Green Boss only)." },
  fakeHeal:    { key:"heal",    node:"key",   levels:[2,3],   desc:"Potion says \"Healed 1 bar\" but restores no health." },
  stuckKey:    { key:"key",     node:"key",   levels:[3],     desc:"Decoy key in a dead end that is jammed and can't be picked up." },
};

const BUGS = {};
[1,2,3].forEach(l => {
  BUGS[l] = {};
  for(const [b, info] of Object.entries(BUG_CATALOG)) BUGS[l][b] = info.levels.includes(l);
});
(function applyBugQuery(){
  try {
    const p = new URLSearchParams(location.search);
    const setFlags = (lvl, list) => {
      const s = list.map(x=>x.trim()).filter(Boolean);
      const all = s.includes("all") || s.includes("1");
      for(const [b, info] of Object.entries(BUG_CATALOG)) lvl[b] = all || s.includes(info.key);
    };
    const g = p.get("bugs");
    if(g){ const list = g.toLowerCase().split(","); [1,2,3].forEach(l => setFlags(BUGS[l], list)); }
    [1,2,3].forEach(l => {
      const v = p.get("l"+l);
      if(v) setFlags(BUGS[l], v.toLowerCase().split(","));
    });
  } catch(e){}
})();
// Node an encounter is recorded at; nodeByLevel overrides it per chamber.
const bugNode = (bug, level) => (BUG_CATALOG[bug].nodeByLevel || {})[level] || BUG_CATALOG[bug].node;
const activeBugsForLevel = n => { const b = BUGS[n] || {}; return Object.keys(b).filter(k => b[k]); };
const anyBugConfigured = () => [1,2,3].some(l => activeBugsForLevel(l).length > 0);
const SHOW_QA_BADGE = false;

// ---------- sprites (8x8) ----------
const PAL = {
  h:"#8a3b2a", s:"#e6b48a", e:"#141821", b:"#3f6bb0", l:"#5b3d24",
  L:"#a06a3a", Y:"#f6d24b", W:"#6e4728", K:"#f6d24b",
  d:"#4a5470", w:"#6e4f2e", k:"#f6d24b", g:"#5fbf7d",
  o:"#c0392b", i:"#f2e04a",
  u:"#7d3cae", c:"#35d0e6", C:"#c9f7ff",
  t:"#d4a017", T:"#ffe066",
  p:"#a08060", P:"#e8dcc0",
  R:"#e2554e", r:"#ff8888",
  G:"#3da868", F:"#7fffaa",
  B:"#4a7de0", A:"#88bbff",
  V:"#4ade80", v:"#86efac",
  H:"#e74c3c", J:"#ff6b6b", j:"#f9f9f9",
};
const SPR = {
  player:[
    "..hhhh..",".hhhhhh.","..ssss..","..sese..","..ssss..",".bbbbbb.",".b.bb.b.","..l..l..",
  ],
  chest:[
    "........",".LLLLLL.",".LYYYYL.",".LLLLLL.",".WWWWWW.",".WWKKWW.",".WWWWWW.","........",
  ],
  doorLocked:[
    ".dddddd.","dwwwwwwd","dwwwwwwd","dwwwwwwd","dwwkkwwd","dwwkkwwd","dwwwwwwd","dwwwwwwd",
  ],
  doorOpen:[
    ".gggggg.","gwwwwwwg","gw....wg","gw....wg","gw....wg","gw....wg","gw....wg","gwwwwwwg",
  ],
  enemy:[
    "..oooo..",".oooooo.",".oiooio.",".oooooo.",".o.oo.o.",".oooooo.",".oo..oo.",".o....o.",
  ],
  brute:[
    "u.u..u.u",".uuuuuu.",".uiuuiu.",".uuuuuu.",".u.uu.u.",".uuuuuu.",".uu..uu.","u.u..u.u",
  ],
  trophy:[
    "..tTTt..",".tTTTTt.",".tTTTTt.","..tTTt..","...tt...","...tt...","..tttt..",".tttttt.",
  ],
  pedestal:[
    "........","..PPPP..","..PppP..","..PppP..","..PPPP..","...pp...","..pppp..",".pppppp.",
  ],
  gemRuby:[
    "........","...rr...","..rRRr..",".rRRRRr.",".rRRRRr.","..rRRr..","...rr...","........",
  ],
  gemEmerald:[
    "........","...FF...","..FGGF..",".FGGGFF.",".FGGGGF.","..FGGF..","...FF...","........",
  ],
  gemSapphire:[
    "........","...AA...","..ABBA..",".ABBBBA.",".ABBBBA.","..ABBA..","...AA...","........",
  ],
  greenBoss:[
    "V.V..V.V",".VVVVVV.",".ViVViV.",".VVVVVV.",".V.VV.V.",".VVVVVV.",".VV..VV.","V.V..V.V",
  ],
  potion:[
    "........","...jj...","..jHHj..","..HHHH..","..HJJH..","..HHHH..","..jHHj..","...jj...",
  ],
  whiteChest:[
    "........",".CCCCCC.",".CjjjjC.",".CCCCCC.",".jjjjjj.",".jjKKjj.",".jjjjjj.","........",
  ],
};

function drawSprite(ctx, spr, px, py, size){
  const p = size/8;
  for(let y=0;y<8;y++){
    const row=spr[y];
    for(let x=0;x<8;x++){
      const c=row[x];
      if(c==="."||c===" ") continue;
      ctx.fillStyle=PAL[c]||"#fff";
      ctx.fillRect(Math.floor(px+x*p), Math.floor(py+y*p), Math.ceil(p), Math.ceil(p));
    }
  }
}
