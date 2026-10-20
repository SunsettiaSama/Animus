// 感知协议层 · 无头采集端（类银河恶魔城《星陨之痕》）
// 在 Node 中以桩 DOM/canvas 运行整个游戏，帧级 diff 产出事件流。
//
// 运行（从 demos/metroidvania 目录）：node perception/harness.js [--scenario story]
//
// stdout（NDJSON，协议见 src/agent/perception/protocol.py）：
//   {"type":"event","kind":"player_hurt","ts":"...","frame":123,"detail":{...}}
//   {"type":"scene","ts":"...","frame":150,"room":"c1_1","room_name":"...","player_hp":5,...}
//   {"type":"npc_wait","name":"守灯人"}        — 已发出 npc_talk，等待台词回注
//   {"type":"log","text":"..."}               — 人类可读进度
//   {"type":"done","reason":"...","errors":0}
// stdin（NDJSON）：
//   {"type":"npc_line","name":"守灯人","text":"...","mode":"popup"|"toast"}
const fs = require('fs');
const vm = require('vm');
const readline = require('readline');

// —— 万能代理 canvas（同 test/smoke.js）——
function makeUniversal() {
  const fn = function () { return universal; };
  const universal = new Proxy(fn, {
    get: (t, p) => {
      if (p === Symbol.toPrimitive) return () => 0;
      return universal;
    },
    set: () => true,
    apply: () => universal
  });
  return universal;
}

const handlers = {};
let rafCb = null;
let simTime = 0;
const fakeCanvas = { width: 960, height: 540, style: {}, getContext: () => makeUniversal() };

const sandbox = {
  console, Math, Object, Array, JSON, String, Number, Set, Map, RegExp, Date, Promise,
  isNaN, parseInt, parseFloat, Symbol,
  setInterval: () => 0, clearInterval: () => {}, setTimeout: () => 0, clearTimeout: () => {},
  addEventListener: (t, fn) => { handlers[t] = fn; },
  removeEventListener: () => {},
  requestAnimationFrame: (cb) => { rafCb = cb; },
  performance: { now: () => simTime },
  innerWidth: 1280, innerHeight: 720,
  document: { getElementById: () => fakeCanvas }
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const f of ['js/audio.js', 'js/input.js', 'js/levels.js', 'js/particles.js',
                 'js/player.js', 'js/enemies.js', 'js/npc.js', 'js/boss.js', 'js/game.js']) {
  vm.runInContext(fs.readFileSync(f, 'utf8'), sandbox, { filename: f });
}

const dbg = sandbox.window.__dbg;
const G = dbg.G;
const World = dbg.World;
const T = 32;

const errors = [];
let frameNo = 0;

// —— 基础驱动 ——
function pump(n) {
  for (let i = 0; i < n; i++) {
    simTime += 1000 / 60;
    try { rafCb(simTime); }
    catch (e) { errors.push('PUMP EXC: ' + e.stack.split('\n').slice(0, 3).join(' | ')); return; }
  }
}
function key(code, down) {
  const h = handlers[down ? 'keydown' : 'keyup'];
  if (h) h({ code, repeat: false, preventDefault: () => {} });
}
const yieldLoop = () => new Promise((r) => setImmediate(r));

function write(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }
function log(text) { write({ type: 'log', text }); }
function emitEvent(kind, detail) {
  write({ type: 'event', kind, ts: new Date().toISOString(), frame: frameNo, detail: detail || {} });
}

// —— 感知：帧级 diff ——
const ENEMY_NAMES = { Crawler: '爬行者', Flyer: '飞翼', Shooter: '炮手' };
let prev = null;
let prevEnemyRefs = [];
let started = false;

function snap() {
  const p = G.player;
  return {
    state: G.state, room: G.roomId, roomName: (World.def && World.def.name) || '',
    chapter: G.chapter, hp: p.hp, deaths: G.deaths,
    dash: G.abilities.dash, dj: G.abilities.dj,
    boss1: G.flags.boss1, boss2: G.flags.boss2,
    enemies: G.enemies.length, fightOn: G.fightOn,
    bossActive: !!(G.boss && G.boss.active && !G.boss.dead),
    cpRoom: G.checkpoint.room, cpX: G.checkpoint.x, cpY: G.checkpoint.y
  };
}

function perceive() {
  const cur = snap();
  if (!started && cur.state === 'play') {
    started = true;
    emitEvent('game_start', { room: cur.room, room_name: cur.roomName });
    emitEvent('room_enter', { room: cur.room, room_name: cur.roomName });
  }
  if (prev && started) {
    if (cur.room !== prev.room)
      emitEvent('room_enter', { room: cur.room, room_name: cur.roomName, from: prev.room });
    if (cur.chapter !== prev.chapter) {
      const card = G.chapterCards[cur.chapter];
      emitEvent('chapter_begin', { chapter: cur.chapter, title: card ? card.title : '' });
    }
    if (cur.hp < prev.hp)
      emitEvent('player_hurt', { hp: cur.hp, hp_max: 5, room_name: cur.roomName });
    if (cur.hp > prev.hp)
      emitEvent('player_heal', { hp: cur.hp, hp_max: 5, room_name: cur.roomName });
    if (cur.deaths > prev.deaths)
      emitEvent('player_death', { deaths: cur.deaths, room_name: cur.roomName });
    if (cur.room === prev.room && cur.enemies < prev.enemies) {
      const gone = prevEnemyRefs.filter((e) => e.dead || !G.enemies.includes(e));
      const ctor = gone.length ? gone[0].constructor.name : '';
      emitEvent('enemy_killed', { enemy_name: ENEMY_NAMES[ctor] || '敌影', room_name: cur.roomName });
    }
    if (cur.fightOn && !prev.fightOn)
      emitEvent('boss_fight_start', { boss_name: G.boss ? G.boss.name : '强敌', room_name: cur.roomName });
    if (cur.boss1 && !prev.boss1) emitEvent('boss_defeated', { boss_name: '矿洞魔像' });
    if (cur.boss2 && !prev.boss2) emitEvent('boss_defeated', { boss_name: '星核守望者' });
    if (cur.dash && !prev.dash) emitEvent('ability_gain', { ability: 'dash', item_name: '疾行之靴' });
    if (cur.dj && !prev.dj) emitEvent('ability_gain', { ability: 'dj', item_name: '星羽' });
    if (cur.cpRoom !== prev.cpRoom || cur.cpX !== prev.cpX || cur.cpY !== prev.cpY)
      emitEvent('checkpoint_lit', { room: cur.cpRoom, x: cur.cpX, y: cur.cpY });
    if (cur.state === 'ending' && prev.state !== 'ending') emitEvent('game_clear', {});
  }
  prev = cur;
  prevEnemyRefs = G.enemies.slice();
  if (cur.state === 'play' && frameNo % 30 === 0) {
    const p = G.player;
    write({
      type: 'scene', ts: new Date().toISOString(), frame: frameNo,
      room: cur.room, room_name: cur.roomName, chapter: cur.chapter,
      player_hp: p.hp, player_hp_max: p.hpMax, deaths: G.deaths,
      pos_x: Math.round(p.x), pos_y: Math.round(p.y),
      enemies_alive: G.enemies.length, boss_active: cur.bossActive,
      abilities: Object.entries(G.abilities).filter(([, v]) => v).map(([k]) => k)
    });
  }
}

async function waitFrames(n) {
  for (let i = 0; i < n; i++) {
    pump(1); frameNo++; perceive();
    if ((i & 31) === 31) await yieldLoop();
  }
}
async function hold(frames, codes) {
  codes.forEach((c) => key(c, true));
  await waitFrames(frames);
  codes.forEach((c) => key(c, false));
}
async function walkUntil(cond, maxFrames, codes) {
  codes.forEach((c) => key(c, true));
  for (let i = 0; i < maxFrames; i++) {
    await waitFrames(1);
    if (cond()) break;
  }
  codes.forEach((c) => key(c, false));
}
// 向右走并自动跳沟（同 smoke.js，异步+感知版）
async function walkRight(maxFrames) {
  const startRoom = G.roomId;
  let jumpHold = 0;
  key('ArrowRight', true);
  for (let i = 0; i < maxFrames; i++) {
    const p = G.player;
    if (p.grounded && jumpHold <= 0) {
      const ax = Math.floor((p.x + p.w + 36) / T);
      const fy = Math.floor((p.y + p.h + 8) / T);
      const my = Math.floor((p.y + p.h - 12) / T);
      const wall = World.isSolid(ax, my);
      const gap = !World.isSolid(ax, fy) && !World.isSolid(ax + 1, fy) && !World.isSolid(ax - 1, fy);
      if (gap || wall) { key('KeyZ', true); jumpHold = 24; }
    }
    if (jumpHold > 0) { jumpHold--; if (jumpHold === 0) key('KeyZ', false); }
    await waitFrames(1);
    if (G.roomId !== startRoom && G.state === 'play') break;
  }
  key('ArrowRight', false); key('KeyZ', false);
}

// —— NPC 桥接 ——
const inbox = [];
sandbox.window.__perception = {
  onNpcTalk(npc) {
    emitEvent('npc_talk', { npc_name: npc.name, room_name: (World.def && World.def.name) || '' });
    write({ type: 'npc_wait', name: npc.name, frame: frameNo });
  }
};
sandbox.window.__npcSay = (name, text, mode) => {
  const npc = G.npcs && G.npcs[0];
  if (npc && mode !== 'toast') npc.say(String(text || ''));
  else G.toast(String(name || '守灯人') + '：「' + String(text || '').replace(/\n/g, ' ') + '」');
  emitEvent('npc_line', { npc_name: name, text: String(text || '') });
};
const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on('line', (line) => {
  line = line.trim();
  if (!line) return;
  try {
    const msg = JSON.parse(line);
    if (msg.type === 'npc_line') inbox.push(msg);
  } catch (e) { log('stdin 无法解析: ' + line.slice(0, 60)); }
});

async function waitNpcLine(timeoutMs) {
  const t0 = Date.now();
  while (!inbox.length) {
    if (Date.now() - t0 > timeoutMs) return null;
    pump(1); frameNo++; perceive();   // 世界保持运转（弹窗占位冻结中）
    await yieldLoop();                // 让 stdin 事件得以处理
  }
  return inbox.shift();
}

// —— 剧本 ——
async function scenarioStory() {
  log('场景 story：开局 → 灯台 → 与守灯人交谈 → 战斗 → 能力 → 魔像 → 通关');

  await waitFrames(30);
  key('KeyZ', true); await waitFrames(8); key('KeyZ', false);
  await waitFrames(300);                                    // game_start + room_enter(c1_1)

  // 点亮出生点旁的灯台
  await walkUntil(() => G.lanterns.some((l) => l.active), 300, ['ArrowLeft']);
  await waitFrames(30);                                     // checkpoint_lit

  // 走到守灯人（c1_1 col10）并按 Enter 交谈
  const npc = () => (G.npcs && G.npcs[0]);
  await walkUntil(() => npc() && npc().near(), 400, ['ArrowRight']);
  await waitFrames(6);
  key('Enter', true); await waitFrames(2); key('Enter', false);
  const line = await waitNpcLine(30000);
  if (line) {
    log('守灯人台词已回注: ' + String(line.text).slice(0, 40));
    await waitFrames(50);
    key('Enter', true); await waitFrames(6); key('Enter', false);   // 关闭弹窗
    await waitFrames(10);
  } else {
    log('等待台词超时，继续剧本');
  }

  // 受一次伤（脚本触发，等价被敌人所伤）
  G.player.inv = 0; G.player.hurt(1, G.player.x + 12);
  await waitFrames(30);                                     // player_hurt

  // 消灭附近的爬行者（贴脸连击，避免巡逻位置不确定）
  const crawler = () => G.enemies.find((e) => e.constructor.name === 'Crawler');
  for (let s = 0; s < 60 && crawler(); s++) {
    const c = crawler();
    G.player.inv = 70;                       // 连击期间免受接触伤害
    G.player.x = c.x - 42; G.player.y = c.y - 6;
    G.player.face = 1;
    key('KeyX', true); await waitFrames(5); key('KeyX', false); await waitFrames(6);
  }
  await waitFrames(20);                                     // enemy_killed

  // 走入传送门 → 回声竖井
  await walkRight(900);
  await waitFrames(60);                                     // room_enter(c1_2)

  // 拾取疾行之靴（同 smoke：传送到 orb 旁磁吸）
  G.player.x = 4.5 * T; G.player.y = 4 * T;
  await waitFrames(90);                                     // ability_gain(dash)
  key('KeyZ', true); await waitFrames(6); key('KeyZ', false); await waitFrames(10);

  // 魔像战
  dbg.loadRoom('c1_3', { x: 3, y: 15 });
  G.player.hp = 5;                                          // player_heal
  await walkRight(400);                                     // boss_fight_start
  if (G.boss) G.boss.hp = 1;
  for (let s = 0; s < 60 && !G.flags.boss1; s++) {
    G.player.inv = 80;
    if (G.boss) { G.player.x = G.boss.x - 46; G.player.y = G.boss.y + G.boss.h - G.player.h; }
    G.player.face = 1;
    key('KeyX', true); await waitFrames(8); key('KeyX', false); await waitFrames(4);
  }
  await waitFrames(160);                                    // boss_defeated(魔像)

  // 第二章 → 星核守望者 → 星门
  dbg.loadRoom('c2_1', { x: 2, y: 13 });
  await waitFrames(60);                                     // chapter_begin + room_enter
  dbg.loadRoom('c2_3', { x: 3, y: 13 });
  G.player.hp = 5;
  await walkRight(400);                                     // boss_fight_start
  if (G.boss) G.boss.hp = 1;
  for (let s = 0; s < 80 && !G.flags.boss2; s++) {
    G.player.inv = 80;
    if (G.boss) { G.player.x = G.boss.cx - G.player.w / 2; G.player.y = G.boss.y + 90; }
    key('ArrowUp', true);
    key('KeyX', true); await waitFrames(6);
    key('KeyX', false); key('ArrowUp', false); await waitFrames(4);
  }
  await waitFrames(160);                                    // boss_defeated(守望者)
  if (G.portal) {
    G.player.x = G.portal.x - G.player.w / 2;
    G.player.y = G.portal.y - G.player.h / 2;
    G.player.inv = 200;
    await waitFrames(140);                                  // game_clear
  }
}

(async () => {
  try {
    await scenarioStory();
  } catch (e) {
    errors.push('SCENARIO EXC: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : String(e)));
  }
  if (errors.length) errors.slice(0, 6).forEach((e) => log(e));
  write({ type: 'done', reason: 'scenario finished', errors: errors.length });
  await new Promise((res) => process.stdout.write('', res));   // 排空管道（Windows）
  process.exit(errors.length ? 1 : 0);
})();
