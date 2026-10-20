// 主循环：状态机（title / card / play / pause / dead / trans / ending）+ 渲染 + HUD
(() => {
const cvs = document.getElementById('game');
const ctx = cvs.getContext('2d');
const W = cvs.width, H = cvs.height;
const FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif';

// 每章配色
const PAL = {
  1: {
    bgTop: '#191422', bgBot: '#0d0a12',
    rock: '#453b4e', rockTop: '#6e5f7c', rockDark: '#2b2433',
    accent: '#ffb454', accentSoft: 'rgba(255,180,84,0.5)',
    enemyBody: '#8a5a3c', enemyDark: '#5c3a26', enemyEye: '#ffcf6e',
    far: '#171320', near: '#211a2c'
  },
  2: {
    bgTop: '#0d0a24', bgBot: '#060410',
    rock: '#3c3560', rockTop: '#6c66b8', rockDark: '#252042',
    accent: '#7ff0ff', accentSoft: 'rgba(127,240,255,0.5)',
    enemyBody: '#5a4a8a', enemyDark: '#3a2f5e', enemyEye: '#b9a6ff',
    far: '#141033', near: '#1b1644'
  }
};
window.PAL = PAL;

const G = {
  state: 'title', time: 0, playT: 0,
  chapter: 1,
  abilities: { dash: false, dj: false },
  flags: { boss1: false, boss2: false },
  collected: new Set(),
  checkpoint: { room: 'c1_1', x: 7, y: 14 },
  deaths: 0,
  player: new Player(),
  enemies: [], bullets: [], shocks: [], rocks: [], healMotes: [], pickups: [], lanterns: [],
  npcs: [],
  boss: null, portal: null, fightOn: false,
  cam: { x: 0, y: 0 },
  shake: 0, hitstop: 0,
  trans: null, card: null, popup: null, toastMsg: null, toastT: 0,
  hintShow: 0, hintCur: '',
  roomTitleT: 0, sawCh2: false,
  deathT: 0, endT: 0, titleT: 0,
  chapterCards: {
    1: { title: '第一章 · 幽暗矿脉', sub: '矿灯熄灭已久，而回声仍在。' },
    2: { title: '第二章 · 星坠回廊', sub: '坠落的星辰，在高处低语。' }
  }
};
window.G = G;

// —— 工具 ——
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function hash2(a, b) {
  let n = a * 374761393 + b * 668265263;
  n = (n ^ (n >>> 13)) * 1274126177;
  return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
}
function text(str, x, y, size, col, align, weight, glow) {
  ctx.font = (weight || 600) + ' ' + size + 'px ' + FONT;
  ctx.textAlign = align || 'center';
  ctx.textBaseline = 'middle';
  if (glow) { ctx.shadowColor = glow; ctx.shadowBlur = 14; }
  ctx.fillStyle = col;
  ctx.fillText(str, x, y);
  ctx.shadowBlur = 0;
}

// —— 房间加载 ——
function loadRoom(id, spawn) {
  const def = ROOMS[id];
  World.load(def, id, G.flags);
  G.roomId = id;
  G.chapter = def.chapter;
  G.enemies = []; G.bullets = []; G.shocks = []; G.rocks = [];
  G.healMotes = []; G.pickups = []; G.lanterns = [];
  G.npcs = [];
  G.boss = null; G.portal = null; G.fightOn = false;

  const rows = World.rows;
  for (let ty = 0; ty < rows.length; ty++) {
    for (let tx = 0; tx < rows[ty].length; tx++) {
      const ch = rows[ty][tx];
      if (ch === 'k') G.lanterns.push(new Checkpoint(tx, ty));
      else if (ch === 'N') G.npcs.push(new NPC(tx, ty));
      else if (ch === 'c') G.enemies.push(new Crawler(tx, ty));
      else if (ch === 'f') G.enemies.push(new Flyer(tx, ty));
      else if (ch === 's') G.enemies.push(new Shooter(tx, ty));
      else if (ch === 'd' || ch === 'j') {
        const pid = id + '#' + tx + ',' + ty;
        if (!G.collected.has(pid)) G.pickups.push(new Pickup(tx, ty, ch === 'd' ? 'dash' : 'dj'));
      } else if (ch === 'W') {
        if (!G.flags.boss1) G.boss = new Boss1(tx, ty);
      } else if (ch === 'V') {
        if (!G.flags.boss2) G.boss = new Boss2(tx, ty);
      }
    }
  }

  // 已激活的灯台保持点亮
  if (G.checkpoint.room === id) {
    for (const l of G.lanterns)
      if (l.tx === G.checkpoint.x && l.ty === G.checkpoint.y) l.active = true;
  }

  const sp = spawn || { x: 2, y: 2 };
  const wasHp = G.player.hp;
  G.player.spawnAt(sp.x, sp.y);
  G.player.hp = clamp(wasHp, 1, G.player.hpMax);

  G.cam.x = clamp(G.player.cx - W / 2, 0, Math.max(0, World.w * T - W));
  G.cam.y = clamp(G.player.cy - H / 2, 0, Math.max(0, World.h * T - H));
  G.roomTitleT = 160;
  AudioSys.setMusic(def.chapter === 1 ? 'ch1' : 'ch2');
}

function startGame() {
  G.abilities = { dash: false, dj: false };
  G.flags = { boss1: false, boss2: false };
  G.collected = new Set();
  G.checkpoint = { room: 'c1_1', x: 7, y: 14 };
  G.deaths = 0; G.playT = 0;
  G.sawCh2 = false;
  G.player = new Player();
  loadRoom('c1_1', { x: 7, y: 14 });
  G.card = Object.assign({ t: 150 }, G.chapterCards[1]);
  G.state = 'card';
  AudioSys.sfx('select');
}

// —— 事件回调 ——
G.onAbilityGet = function (type) {
  AudioSys.sfx('pickup');
  G.shake = 6;
  if (type === 'dash') {
    G.abilities.dash = true;
    G.collected.add(World.id + '#d');
    G.popup = { title: '疾行之靴', desc: '按 C / L / Shift 冲刺\n空中亦可冲刺一次', t: 0 };
    Particles.ring(G.player.cx, G.player.cy, 'rgba(255,190,110,0.95)', 10, 120);
  } else {
    G.abilities.dj = true;
    G.collected.add(World.id + '#j');
    G.popup = { title: '星羽', desc: '空中再按一次跳跃\n展翅，触星而上', t: 0 };
    Particles.ring(G.player.cx, G.player.cy, 'rgba(140,225,255,0.95)', 10, 120);
  }
};

G.onBossDefeated = function (boss) {
  if (boss instanceof Boss1) G.flags.boss1 = true;
  else G.flags.boss2 = true;
  World.bossDefeated = true;
  World.gateClosed = false;
  G.fightOn = false;
  G.player.hp = G.player.hpMax;
  AudioSys.sfx('gate');
  AudioSys.setMusic(G.chapter === 1 ? 'ch1' : 'ch2');
  G.toast(boss.name + ' 已被击败 — 封印开启，生命恢复');
  if (boss instanceof Boss2) {
    G.portal = new Portal(World.w * T / 2, 8 * T);
    G.toast('圣殿核心已然开启……');
  }
};

G.onPortal = function () {
  if (G.state !== 'play') return;
  G.state = 'ending';
  G.endT = 0;
  AudioSys.sfx('portal');
};

G.toast = function (msg) { G.toastMsg = msg; G.toastT = 190; };

function startFight() {
  G.fightOn = true;
  World.gateClosed = true;
  if (G.boss) G.boss.active = true;
  G.shake = 7;
  AudioSys.sfx('gate');
  AudioSys.sfx('roar');
  AudioSys.setMusic('boss');
  G.toast(G.boss.name + ' 苏醒了！');
}

// —— 每帧逻辑 ——
function tickPlay() {
  if (Input.hit('mute')) AudioSys.toggleMute();
  if (Input.hit('pause')) { G.state = 'pause'; AudioSys.sfx('select'); return; }

  // 能力获得弹窗：冻结世界
  if (G.popup) {
    G.popup.t++;
    Particles.update();
    if (Input.hit('confirm') && G.popup.t > 24) G.popup = null;
    return;
  }
  if (G.hitstop > 0) { G.hitstop--; Particles.update(); return; }

  G.playT++;
  const p = G.player;
  p.update();

  if (p.dead) {
    G.state = 'dead'; G.deathT = 80;
    AudioSys.sfx('die');
    G.shake = 10;
    Particles.shards(p.cx, p.cy, 18, '#d1493f');
    Particles.sparks(p.cx, p.cy, 14, '#fff');
    return;
  }

  // 实体更新
  for (const e of G.enemies) e.update();
  G.enemies = G.enemies.filter((e) => !e.dead);
  for (const b of G.bullets) b.update();
  G.bullets = G.bullets.filter((b) => !b.dead);
  for (const s of G.shocks) s.update();
  G.shocks = G.shocks.filter((s) => !s.dead);
  for (const r of G.rocks) r.update();
  G.rocks = G.rocks.filter((r) => !r.dead);
  for (const m of G.healMotes) m.update();
  G.healMotes = G.healMotes.filter((m) => !m.dead);
  for (const k of G.lanterns) k.update();
  for (const n of G.npcs) n.update();
  for (const it of G.pickups) it.update();
  G.pickups = G.pickups.filter((it) => !it.dead);
  if (G.boss) G.boss.update();
  if (G.portal) G.portal.update();

  // 战斗开始判定
  const def = World.def;
  if (def.bossTriggerX && G.boss && !G.boss.active && !World.bossDefeated &&
      p.cx > def.bossTriggerX * T) startFight();

  // 玩家攻击判定
  const box = p.getAttackBox();
  if (box) {
    const targets = [...G.enemies, ...G.shocks, ...G.rocks, ...G.bullets];
    if (G.boss && !G.boss.dead) targets.push(G.boss);
    for (const e of targets) {
      if (e.dead || e.lastHitSwing === p.swingId) continue;
      if (aabb(box, e.rect())) {
        e.lastHitSwing = p.swingId;
        if (e.hurt) e.hurt(1, p.cx);
        else if (e.kill) e.kill();
        G.hitstop = Math.max(G.hitstop, 3);
        Particles.sparks(p.cx + p.face * 30, e.cy || e.y, 7, PAL[G.chapter].accent);
        if (p.atkDir === 'down' && !p.pogoDone) { p.pogoDone = true; p.pogo(); }
      }
    }
    // 下劈地刺弹跳
    if (p.atkDir === 'down' && !p.pogoDone &&
        World.overlapsTile('^', box.x, box.y, box.w, box.h, 2)) {
      p.pogoDone = true;
      p.pogo();
      Particles.sparks(box.x + box.w / 2, box.y + box.h, 6, '#cfd6e0');
    }
  }

  // 接触伤害
  if (p.inv <= 0 && !p.dead) {
    const pr = { x: p.x + 3, y: p.y + 3, w: p.w - 6, h: p.h - 6 };
    const harms = [...G.enemies, ...G.shocks, ...G.rocks];
    if (G.boss && G.boss.harmful && !G.boss.dead) harms.push(G.boss);
    for (const e of harms) {
      if (!e.dead && aabb(pr, e.rect())) {
        if (p.hurt(1, e.cx !== undefined ? e.cx : e.x)) {
          AudioSys.sfx('hurt');
          G.hitstop = Math.max(G.hitstop, 6);
          G.shake = Math.max(G.shake, 6);
          Particles.sparks(p.cx, p.cy, 8, '#ff6a5a');
        }
        break;
      }
    }
    for (const b of G.bullets) {
      if (!b.dead && aabb(pr, b.rect())) {
        b.dead = true;
        if (p.hurt(1, b.cx)) {
          AudioSys.sfx('hurt');
          G.shake = Math.max(G.shake, 5);
        }
        break;
      }
    }
  }

  // 房间传送触发
  if (p.trigArm && p.overlapsTrigger()) {
    const x0 = Math.floor(p.x / T), x1 = Math.floor((p.x + p.w) / T);
    const y0 = Math.floor(p.y / T), y1 = Math.floor((p.y + p.h) / T);
    let digit = null;
    outer:
    for (let ty = y0; ty <= y1; ty++)
      for (let tx = x0; tx <= x1; tx++) {
        const c = World.tileAt(tx, ty);
        if (c >= '1' && c <= '9') { digit = c; break outer; }
      }
    const ex = def.exits[digit];
    if (ex) {
      G.state = 'trans';
      G.trans = { t: 0, phase: 'out', target: ex };
      AudioSys.sfx('select');
      return;
    }
  }

  // 提示区
  let inHint = false;
  for (const hz of def.hints || []) {
    if (p.cx > hz.x * T && p.cx < (hz.x + hz.w) * T && p.cy > (hz.y - 2) * T && p.cy < (hz.y + 4) * T) {
      inHint = true;
      if (G.hintCur !== hz.text) G.hintShow = 0;
      G.hintCur = hz.text;
    }
  }
  G.hintShow = clamp(G.hintShow + (inHint ? 0.06 : -0.05), 0, 1);

  // 环境粒子
  if (Math.random() < 0.12) {
    const mx = G.cam.x + Math.random() * W, my = G.cam.y + Math.random() * H;
    if (G.chapter === 1) Particles.mote(mx, my + 30, 'rgba(200,170,140,0.35)');
    else Particles.mote(mx, my, 'rgba(150,200,255,' + (0.25 + Math.random() * 0.3) + ')');
  }

  if (G.toastT > 0) G.toastT--;
  if (G.roomTitleT > 0) G.roomTitleT--;
  updateCamera();
  Particles.update();
}

function updateCamera() {
  const p = G.player;
  const roomW = World.w * T, roomH = World.h * T;
  const tx = clamp(p.cx - W / 2 + p.face * 60, 0, Math.max(0, roomW - W));
  const ty = clamp(p.cy - H / 2 + clamp(p.vy * 5, -30, 40), 0, Math.max(0, roomH - H));
  G.cam.x += (tx - G.cam.x) * 0.11;
  G.cam.y += (ty - G.cam.y) * 0.1;
  G.shake *= 0.87;
}

function tick() {
  G.time++;
  switch (G.state) {
    case 'title':
      G.titleT++;
      Particles.update();
      if (Math.random() < 0.2) Particles.mote(Math.random() * W, H + 10, 'rgba(200,170,140,0.3)');
      if (Input.hit('confirm') && G.titleT > 20) startGame();
      break;

    case 'card':
      G.card.t--;
      Particles.update();
      if (G.card.t <= 0 || Input.hit('confirm')) { G.card = null; G.state = 'play'; }
      break;

    case 'play':
      tickPlay();
      break;

    case 'pause':
      if (Input.hit('pause')) { G.state = 'play'; AudioSys.sfx('select'); }
      if (Input.hit('restart')) {
        G.state = 'play';
        G.player.hp = G.player.hpMax;
        loadRoom(G.checkpoint.room, { x: G.checkpoint.x, y: G.checkpoint.y });
        G.player.inv = 60;
        AudioSys.sfx('checkpoint');
      }
      if (Input.hit('quit')) { G.state = 'title'; G.titleT = 0; AudioSys.setMusic('none'); }
      if (Input.hit('mute')) AudioSys.toggleMute();
      break;

    case 'dead':
      G.deathT--;
      Particles.update();
      if (G.deathT <= 0) {
        G.deaths++;
        G.player.hp = G.player.hpMax;
        loadRoom(G.checkpoint.room, { x: G.checkpoint.x, y: G.checkpoint.y });
        G.player.inv = 80;
        G.state = 'play';
      }
      break;

    case 'trans': {
      const tr = G.trans;
      tr.t++;
      if (tr.phase === 'out' && tr.t >= 14) {
        loadRoom(tr.target.room, { x: tr.target.x, y: tr.target.y });
        tr.phase = 'in'; tr.t = 0;
      } else if (tr.phase === 'in' && tr.t >= 14) {
        G.trans = null;
        if (World.id === 'c2_1' && !G.sawCh2) {
          G.sawCh2 = true;
          G.card = Object.assign({ t: 160 }, G.chapterCards[2]);
          G.state = 'card';
        } else G.state = 'play';
      }
      Particles.update();
      break;
    }

    case 'ending':
      G.endT++;
      Particles.update();
      if (Math.random() < 0.3) Particles.mote(Math.random() * W, Math.random() * H, 'rgba(150,220,255,0.5)');
      if (G.endT > 220 && Input.hit('confirm')) {
        G.state = 'title'; G.titleT = 0;
        AudioSys.setMusic('none');
      }
      break;
  }
}

// —— 渲染 ——
function drawParallax() {
  const pal = PAL[G.chapter];
  const camX = G.cam.x, camY = G.cam.y;
  if (G.chapter === 1) {
    // 远景：钟乳石与石笋剪影
    ctx.fillStyle = pal.far;
    for (let i = 0; i < 26; i++) {
      const bx = ((i * 173 + hash2(i, 7) * 90) - camX * 0.25) % (W + 300) - 150;
      const top = hash2(i, 1) > 0.5;
      const len = 60 + hash2(i, 2) * 130;
      if (top) {
        ctx.beginPath();
        ctx.moveTo(bx - 30, -camY * 0.15);
        ctx.lineTo(bx + 30, -camY * 0.15);
        ctx.lineTo(bx, len - camY * 0.15);
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.moveTo(bx - 45, H - camY * 0.1 + 40);
        ctx.lineTo(bx + 45, H - camY * 0.1 + 40);
        ctx.lineTo(bx, H - len * 0.7 - camY * 0.1);
        ctx.fill();
      }
    }
    // 近景柱
    ctx.fillStyle = pal.near;
    for (let i = 0; i < 14; i++) {
      const bx = ((i * 320 + hash2(i, 3) * 160) - camX * 0.5) % (W + 400) - 200;
      const w2 = 40 + hash2(i, 4) * 50;
      ctx.fillRect(bx, -50 - camY * 0.3, w2, H + 200);
    }
  } else {
    // 星空
    for (let i = 0; i < 90; i++) {
      const sx = ((i * 197 + hash2(i, 11) * 120) - camX * 0.12) % (W + 100);
      const sy = (hash2(i, 12) * H * 1.4 - camY * 0.1 + H) % (H + 40);
      const tw = 0.35 + Math.sin(G.time * 0.03 + i * 1.7) * 0.3;
      ctx.globalAlpha = tw;
      ctx.fillStyle = i % 7 === 0 ? '#aef' : '#dde6ff';
      ctx.fillRect((sx + W + 100) % (W + 100) - 50, sy, 2, 2);
    }
    ctx.globalAlpha = 1;
    // 月亮
    const mx = W * 0.72 - camX * 0.06, my = 110 - camY * 0.05;
    const gr = ctx.createRadialGradient(mx, my, 10, mx, my, 130);
    gr.addColorStop(0, 'rgba(190,180,255,0.32)');
    gr.addColorStop(1, 'rgba(190,180,255,0)');
    ctx.fillStyle = gr;
    ctx.fillRect(mx - 140, my - 140, 280, 280);
    ctx.fillStyle = '#cfc8ff';
    ctx.beginPath(); ctx.arc(mx, my, 42, 0, 7); ctx.fill();
    ctx.fillStyle = '#b2a8ea';
    ctx.beginPath(); ctx.arc(mx - 12, my - 8, 9, 0, 7); ctx.arc(mx + 14, my + 10, 6, 0, 7); ctx.fill();
    // 浮岛剪影
    ctx.fillStyle = pal.near;
    for (let i = 0; i < 8; i++) {
      const bx = ((i * 390 + hash2(i, 5) * 200) - camX * 0.4) % (W + 500) - 250;
      const by = 90 + hash2(i, 6) * 300 - camY * 0.25;
      const w2 = 90 + hash2(i, 8) * 130;
      ctx.beginPath();
      ctx.moveTo(bx, by);
      ctx.quadraticCurveTo(bx + w2 / 2, by - 34, bx + w2, by);
      ctx.quadraticCurveTo(bx + w2 / 2, by + 52, bx, by);
      ctx.fill();
    }
  }
}

function drawVignette() {
  const g = ctx.createRadialGradient(W / 2, H / 2, H * 0.42, W / 2, H / 2, H * 0.85);
  g.addColorStop(0, 'rgba(0,0,0,0)');
  g.addColorStop(1, 'rgba(0,0,0,0.42)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}

function drawHUD() {
  const p = G.player;
  // 生命面具
  for (let i = 0; i < p.hpMax; i++) {
    const x = 30 + i * 32, y = 30;
    const filled = i < p.hp;
    ctx.beginPath(); ctx.arc(x, y, 11, 0, 7);
    if (filled) {
      const low = p.hp <= 2 && (G.time >> 4) % 2 === 0;
      ctx.fillStyle = low ? '#ff8a7a' : '#e8574a';
      ctx.shadowColor = '#e8574a'; ctx.shadowBlur = 10;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#ffb3a8';
      ctx.beginPath(); ctx.arc(x - 3, y - 3, 3.5, 0, 7); ctx.fill();
    } else {
      ctx.strokeStyle = 'rgba(120,60,60,0.7)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }
  // 能力图标
  const icons = [
    { has: G.abilities.dash, draw: (x, y) => { ctx.beginPath(); ctx.moveTo(x - 5, y - 7); ctx.lineTo(x + 4, y); ctx.lineTo(x - 5, y + 7); ctx.lineTo(x - 2, y); ctx.closePath(); ctx.fill(); } },
    { has: G.abilities.dj, draw: (x, y) => { ctx.beginPath(); ctx.moveTo(x - 6, y + 2); ctx.quadraticCurveTo(x, y - 9, x + 6, y + 2); ctx.quadraticCurveTo(x, y - 2, x - 6, y + 2); ctx.fill(); ctx.beginPath(); ctx.moveTo(x - 6, y + 7); ctx.quadraticCurveTo(x, y - 3, x + 6, y + 7); ctx.quadraticCurveTo(x, y + 3, x - 6, y + 7); ctx.fill(); } }
  ];
  icons.forEach((ic, i) => {
    const x = 34 + i * 30, y = 66;
    ctx.globalAlpha = ic.has ? 1 : 0.18;
    ctx.fillStyle = i === 0 ? '#ffb454' : '#7ff0ff';
    ic.draw(x, y);
    ctx.globalAlpha = 1;
  });

  // 房间名
  if (G.roomTitleT > 0) {
    const a = Math.min(1, G.roomTitleT / 40, (160 - G.roomTitleT) / 30 + 0.2);
    ctx.globalAlpha = clamp(a, 0, 1);
    text(World.def.name, W / 2, 34, 20, 'rgba(230,225,240,0.9)', 'center', 600);
    ctx.globalAlpha = 1;
  }

  // Boss 血条
  if (G.fightOn && G.boss && !G.boss.dead) {
    const bw = Math.min(430, W - 220), bx = (W - bw) / 2, by = H - 44;
    text(G.boss.name, W / 2, by - 14, 15, '#e8d8c8', 'center', 700);
    ctx.fillStyle = 'rgba(10,8,16,0.75)';
    ctx.fillRect(bx - 3, by - 3, bw + 6, 14);
    ctx.fillStyle = '#3a2030';
    ctx.fillRect(bx, by, bw, 8);
    const r = clamp(G.boss.hp / G.boss.hpMax, 0, 1);
    const fg = ctx.createLinearGradient(bx, 0, bx + bw, 0);
    fg.addColorStop(0, '#c93a3a'); fg.addColorStop(1, '#ff7a5a');
    ctx.fillStyle = G.boss.flash > 0 ? '#fff' : fg;
    ctx.fillRect(bx, by, bw * r, 8);
  }

  // 提示文字
  if (G.hintShow > 0.01 && G.hintCur) {
    ctx.globalAlpha = G.hintShow;
    ctx.fillStyle = 'rgba(8,6,14,0.72)';
    ctx.fillRect(W / 2 - 300, H - 92, 600, 34);
    text(G.hintCur, W / 2, H - 75, 16, '#d8d2e8', 'center', 500);
    ctx.globalAlpha = 1;
  }

  // Toast
  if (G.toastT > 0) {
    const a = Math.min(1, G.toastT / 40);
    ctx.globalAlpha = a;
    text(G.toastMsg, W / 2, 84, 17, '#ffd9a0', 'center', 600, '#b47a30');
    ctx.globalAlpha = 1;
  }

  // 能力弹窗
  if (G.popup) {
    ctx.fillStyle = 'rgba(4,3,8,0.72)';
    ctx.fillRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2;
    ctx.fillStyle = 'rgba(16,12,26,0.95)';
    ctx.strokeStyle = PAL[G.chapter].accent;
    ctx.lineWidth = 2;
    ctx.fillRect(cx - 230, cy - 90, 460, 180);
    ctx.strokeRect(cx - 230, cy - 90, 460, 180);
    text('— 获 得 —', cx, cy - 56, 15, 'rgba(200,190,220,0.75)');
    text(G.popup.title, cx, cy - 18, 30, PAL[G.chapter].accent, 'center', 800, PAL[G.chapter].accent);
    const lines = G.popup.desc.split('\n');
    lines.forEach((ln, i) => text(ln, cx, cy + 22 + i * 24, 17, '#d8d2e8', 'center', 500));
    if (G.popup.t > 24 && (G.time >> 4) % 2 === 0)
      text('按 Z / 空格 继续', cx, cy + 66, 14, 'rgba(160,150,180,0.8)');
  }
}

function drawWorld() {
  // 背景
  const pal = PAL[G.chapter];
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, pal.bgTop);
  g.addColorStop(1, pal.bgBot);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  drawParallax();

  const shx = (Math.random() - 0.5) * G.shake * 2;
  const shy = (Math.random() - 0.5) * G.shake * 2;
  ctx.save();
  ctx.translate(Math.round(-G.cam.x + shx), Math.round(-G.cam.y + shy));
  drawTilesAt(0, 0);
  for (const k of G.lanterns) k.draw(ctx);
  for (const n of G.npcs) n.draw(ctx);
  for (const it of G.pickups) it.draw(ctx);
  if (G.portal) G.portal.draw(ctx);
  for (const m of G.healMotes) m.draw(ctx);
  for (const e of G.enemies) e.draw(ctx);
  for (const s of G.shocks) s.draw(ctx);
  for (const r of G.rocks) r.draw(ctx);
  if (G.boss) G.boss.draw(ctx);
  for (const b of G.bullets) b.draw(ctx);
  if (G.state !== 'dead') G.player.draw(ctx);
  Particles.draw(ctx, 0, 0);
  ctx.restore();
}

// 世界坐标版瓦片绘制（与 drawTiles 合并，cam 由 translate 处理）
function drawTilesAt() {
  const pal = PAL[G.chapter];
  const camX = G.cam.x, camY = G.cam.y;
  const x0 = Math.max(0, Math.floor(camX / T)), x1 = Math.min(World.w - 1, Math.floor((camX + W) / T) + 1);
  const y0 = Math.max(0, Math.floor(camY / T)), y1 = Math.min(World.h - 1, Math.floor((camY + H) / T) + 1);
  for (let ty = y0; ty <= y1; ty++) {
    for (let tx = x0; tx <= x1; tx++) {
      const t = World.rows[ty][tx];
      const px = tx * T, py = ty * T;
      if (t === '#') {
        ctx.fillStyle = pal.rock;
        ctx.fillRect(px, py, T, T);
        if (World.tileAt(tx, ty - 1) !== '#') {
          ctx.fillStyle = pal.rockTop;
          ctx.fillRect(px, py, T, 4);
          if (hash2(tx, ty) > 0.88) {
            ctx.fillStyle = pal.accent;
            ctx.globalAlpha = 0.8;
            const cx2 = px + 6 + hash2(tx, ty + 9) * 20;
            ctx.beginPath();
            ctx.moveTo(cx2 - 3, py); ctx.lineTo(cx2, py - 8 - hash2(ty, tx) * 6); ctx.lineTo(cx2 + 3, py);
            ctx.fill();
            ctx.globalAlpha = 1;
          }
        }
        if (World.tileAt(tx, ty + 1) !== '#') {
          ctx.fillStyle = pal.rockDark;
          ctx.fillRect(px, py + T - 3, T, 3);
        }
        if (hash2(tx * 3, ty * 7) > 0.93) {
          ctx.fillStyle = pal.rockDark;
          ctx.fillRect(px + 8, py + 12, 8, 3);
          ctx.fillRect(px + 18, py + 22, 6, 3);
        }
      } else if (t === '=') {
        ctx.fillStyle = pal.rockTop;
        ctx.fillRect(px, py, T, 7);
        ctx.fillStyle = pal.rockDark;
        ctx.fillRect(px, py + 7, T, 2);
        ctx.fillRect(px + 6, py + 9, 4, 5);
        ctx.fillRect(px + 22, py + 9, 4, 5);
      } else if (t === '^') {
        ctx.fillStyle = '#3a3a46';
        ctx.fillRect(px, py + T - 4, T, 4);
        ctx.fillStyle = '#9aa2b4';
        for (let i = 0; i < 2; i++) {
          ctx.beginPath();
          ctx.moveTo(px + i * 16, py + T);
          ctx.lineTo(px + 8 + i * 16, py + 6);
          ctx.lineTo(px + 16 + i * 16, py + T);
          ctx.closePath(); ctx.fill();
        }
        ctx.fillStyle = '#e8ecf4';
        ctx.fillRect(px + 7, py + 6, 2, 8);
        ctx.fillRect(px + 23, py + 6, 2, 8);
      } else if (t === 'G') {
        if (World.gateClosed) {
          ctx.fillStyle = 'rgba(20,16,28,0.85)';
          ctx.fillRect(px, py, T, T);
          ctx.strokeStyle = pal.accent;
          ctx.lineWidth = 3;
          ctx.globalAlpha = 0.65 + Math.sin(G.time * 0.15 + tx) * 0.25;
          ctx.beginPath();
          ctx.moveTo(px + 8, py + 2); ctx.lineTo(px + 8, py + T - 2);
          ctx.moveTo(px + 20, py + 2); ctx.lineTo(px + 20, py + T - 2);
          ctx.stroke();
          ctx.globalAlpha = 1;
        } else {
          ctx.strokeStyle = 'rgba(150,140,170,0.22)';
          ctx.lineWidth = 2;
          ctx.strokeRect(px + 4, py + 2, T - 8, T - 4);
        }
      } else if (t === 'H') {
        if (!World.bossDefeated) {
          ctx.fillStyle = '#332b44';
          ctx.fillRect(px, py, T, T);
          ctx.strokeStyle = pal.accent;
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.5 + Math.sin(G.time * 0.07 + ty) * 0.3;
          ctx.strokeRect(px + 5, py + 5, T - 10, T - 10);
          ctx.beginPath();
          ctx.arc(px + T / 2, py + T / 2, 6, 0, 7);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      } else if (t >= '1' && t <= '9') {
        ctx.globalAlpha = 0.14 + Math.sin(G.time * 0.06 + tx * 2 + ty) * 0.08;
        ctx.fillStyle = pal.accent;
        ctx.fillRect(px - 4, py - 8, T + 8, T + 16);
        ctx.globalAlpha = 0.7;
        ctx.strokeStyle = pal.accent;
        ctx.lineWidth = 2;
        ctx.strokeRect(px + 3, py - 6, T - 6, T + 12);
        ctx.globalAlpha = 1;
      }
    }
  }
}

function fmtTime(f) {
  const s = Math.floor(f / 60), m = Math.floor(s / 60);
  return m + ':' + String(s % 60).padStart(2, '0');
}

function render() {
  ctx.clearRect(0, 0, W, H);

  if (G.state === 'title') {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, '#191422'); g.addColorStop(1, '#0b0910');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    // 装饰剪影
    ctx.fillStyle = '#171320';
    for (let i = 0; i < 16; i++) {
      const bx = i * 70 + hash2(i, 21) * 40;
      ctx.beginPath();
      ctx.moveTo(bx - 40, H); ctx.lineTo(bx, H - 120 - hash2(i, 22) * 160); ctx.lineTo(bx + 40, H);
      ctx.fill();
    }
    Particles.draw(ctx, 0, 0);
    const pulse = 0.75 + Math.sin(G.titleT * 0.03) * 0.25;
    ctx.globalAlpha = pulse;
    text('星 陨 之 痕', W / 2, H / 2 - 70, 62, '#f0ead8', 'center', 900, '#ffb454');
    ctx.globalAlpha = 1;
    text('S T A R F A L L   E C H O E S', W / 2, H / 2 - 18, 16, 'rgba(200,190,220,0.75)');
    text('— 类银河恶魔城 · 双章节 Demo —', W / 2, H / 2 + 14, 15, 'rgba(170,160,190,0.6)');

    if ((G.titleT >> 5) % 2 === 0)
      text('按 Z / 空格 开始探索', W / 2, H / 2 + 78, 21, '#ffd9a0', 'center', 700, '#b47a30');

    const ctrl = [
      '移动 ←→/AD　跳跃 Z/K/空格　攻击 X/J　冲刺 C/L/Shift',
      '蹬墙跳：贴墙时按跳跃　二段跳：空中再按跳跃　下劈弹跳：空中 ↓+攻击',
      'Esc 暂停　M 静音'
    ];
    ctrl.forEach((ln, i) => text(ln, W / 2, H - 74 + i * 22, 14, 'rgba(160,150,180,0.7)'));
    drawVignette();
    return;
  }

  if (G.state === 'ending') {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, '#0d0a24'); g.addColorStop(1, '#060410');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    Particles.draw(ctx, 0, 0);
    const t = G.endT;
    if (t > 40) text('星核重归寂静', W / 2, 130, 40, '#e8e4ff', 'center', 800, '#7ff0ff');
    if (t > 100) text('矿脉的回声与星海的低语，都归于你的剑下。', W / 2, 190, 19, 'rgba(210,205,235,0.9)');
    if (t > 150) {
      text('— 冒险纪录 —', W / 2, 258, 16, 'rgba(170,160,200,0.8)');
      text('用时　' + fmtTime(G.playT) + '　　阵亡　' + G.deaths + ' 次', W / 2, 292, 19, '#d8d2e8');
      text('击败：矿洞魔像 ✓　星核守望者 ✓', W / 2, 326, 19, '#d8d2e8');
    }
    if (t > 220 && (G.time >> 4) % 2 === 0)
      text('感谢游玩《星陨之痕》Demo — 按 Z 返回标题', W / 2, 420, 17, '#ffd9a0');
    drawVignette();
    return;
  }

  drawWorld();
  drawVignette();

  if (G.state === 'play' || G.state === 'pause' || G.state === 'dead') drawHUD();

  if (G.state === 'card' && G.card) {
    const c = G.card;
    const a = Math.min(1, c.t / 30, (150 - c.t) / 25 + 0.15);
    ctx.fillStyle = 'rgba(4,3,9,' + (0.78 * clamp(a, 0, 1)) + ')';
    ctx.fillRect(0, 0, W, H);
    text(c.title, W / 2, H / 2 - 20, 44, '#f0ead8', 'center', 900, PAL[G.chapter].accent);
    text(c.sub, W / 2, H / 2 + 34, 19, 'rgba(200,192,220,0.85)');
  }

  if (G.state === 'pause') {
    ctx.fillStyle = 'rgba(4,3,9,0.72)';
    ctx.fillRect(0, 0, W, H);
    text('— 暂 停 —', W / 2, 120, 34, '#f0ead8', 'center', 800);
    const lines = [
      '继续游戏　Esc',
      '回到灯台　R',
      '返回标题　Q',
      '音乐开关　M',
      '',
      '移动 ←→/AD　跳跃 Z/K/空格　攻击 X/J　冲刺 C/L/Shift',
      '蹬墙跳 · 二段跳 · 下劈弹跳（↓+攻击）'
    ];
    lines.forEach((ln, i) => text(ln, W / 2, 190 + i * 30, 18, i < 4 ? '#ffd9a0' : 'rgba(170,160,190,0.7)'));
  }

  if (G.state === 'dead') {
    const a = clamp((80 - G.deathT) / 30, 0, 1);
    ctx.fillStyle = 'rgba(30,4,8,' + a * 0.75 + ')';
    ctx.fillRect(0, 0, W, H);
    if (G.deathT < 55) text('你 陨 落 了', W / 2, H / 2, 36, '#ff8a7a', 'center', 800);
  }

  if (G.state === 'trans' && G.trans) {
    const tr = G.trans;
    const a = tr.phase === 'out' ? tr.t / 14 : 1 - tr.t / 14;
    ctx.fillStyle = 'rgba(3,2,6,' + clamp(a, 0, 1) + ')';
    ctx.fillRect(0, 0, W, H);
  }
}

// —— 启动 ——
Input.init();
G.player.spawnAt(7, 14);
// 调试/测试句柄
window.__dbg = { loadRoom, startGame, G, World };

function fit() {
  const s = Math.min(innerWidth / W, innerHeight / H) * 0.985;
  cvs.style.width = Math.floor(W * s) + 'px';
  cvs.style.height = Math.floor(H * s) + 'px';
}
addEventListener('resize', fit);
fit();

let last = 0, acc = 0;
function frame(ts) {
  requestAnimationFrame(frame);
  if (!last) last = ts;
  const dt = Math.min(100, ts - last);
  last = ts;
  acc += dt;
  let n = 0;
  while (acc >= 1000 / 60 && n < 4) { tick(); Input.end(); acc -= 1000 / 60; n++; }
  render();
}
requestAnimationFrame(frame);
})();
