// 全量冒烟测试：在 Node 中以桩 DOM/canvas 运行整个游戏（含渲染调用）
// node test/smoke.js
const fs = require('fs');
const vm = require('vm');

// —— 万能代理：任何属性访问/调用都返回自身（模拟 2D context 与任意链式调用）——
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
                 'js/player.js', 'js/enemies.js', 'js/boss.js', 'js/game.js']) {
  vm.runInContext(fs.readFileSync(f, 'utf8'), sandbox, { filename: f });
}

const dbg = sandbox.window.__dbg;
const G = dbg.G;
const World = dbg.World;
const T = 32;

const errors = [];

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
function hold(frames, codes) {
  for (let i = 0; i < frames; i++) {
    if (i === 0) codes.forEach((c) => key(c, true));
    pump(1);
  }
  codes.forEach((c) => key(c, false));
}
// 向右走并自动跳过沟壑
function walkRight(maxFrames) {
  const startRoom = G.roomId;
  let jumpHold = 0;
  for (let i = 0; i < maxFrames; i++) {
    key('ArrowRight', true);
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
    pump(1);
    if (G.roomId !== startRoom && G.state === 'play') break;
  }
  key('ArrowRight', false); key('KeyZ', false);
}
function check(name, cond, info) {
  console.log((cond ? '  PASS ' : '✗ FAIL ') + name + (info ? '  — ' + info : ''));
  if (!cond) process.exitCode = 1;
}

// ============ 场景 ============
pump(30);
check('启动进入标题', G.state === 'title', 'state=' + G.state);

key('KeyZ', true); pump(10); key('KeyZ', false);
pump(260);
check('Z 开始游戏进入 c1_1', G.state === 'play' && G.roomId === 'c1_1', G.state + '/' + G.roomId);

// 移动 + 攻击 + 跳跃
const px0 = G.player.x;
hold(40, ['ArrowRight']);
key('KeyX', true); pump(6); key('KeyX', false);
key('KeyZ', true); pump(24); key('KeyZ', false);
hold(40, ['ArrowRight']);
check('角色可以向右移动并跳跃攻击', G.player.x > px0 + 100, 'dx=' + Math.round(G.player.x - px0));

// 靠近灯台激活检查点
hold(240, ['ArrowLeft']);
pump(60);
check('灯台检查点可激活', G.lanterns.some((l) => l.active) && G.checkpoint.room === 'c1_1',
  JSON.stringify(G.checkpoint));

// 死亡与重生
G.player.hurt(99, G.player.cx + 10);
pump(200);
check('死亡后回到检查点满血', G.state === 'play' && G.player.hp === 5 && G.roomId === 'c1_1' && G.deaths === 1,
  'state=' + G.state + ' hp=' + G.player.hp + ' room=' + G.roomId + ' deaths=' + G.deaths);

// 传送触发：向右走到 '1'
walkRight(900);
pump(80);
check('走入出口传送至 c1_2', G.roomId === 'c1_2', 'room=' + G.roomId);

// 返回触发：向左走回 '1'
hold(140, ['ArrowLeft']);
pump(80);
check('反向传送回 c1_1', G.roomId === 'c1_1', 'room=' + G.roomId);

// 所有房间逐一加载运行（含敌人/Boss AI 与渲染）
const spawns = { c1_1: [7, 14], c1_2: [2, 38], c1_3: [3, 15], c2_1: [2, 13], c2_2: [2, 36], c2_3: [3, 13] };
for (const [id, sp] of Object.entries(spawns)) {
  for (let s = 0; s < 6; s++) {
    dbg.loadRoom(id, { x: sp[0], y: sp[1] });
    G.player.hp = 5;
    hold(15, ['ArrowRight', 'KeyX']);
    key('KeyZ', true); pump(15); key('KeyZ', false);
    hold(10, []);
    if (errors.length) break;
  }
  check('房间运行无异常 ' + id, G.roomId === id && !errors.length);
}

// 暂停 / 恢复
key('Escape', true); pump(5); key('Escape', false);
check('Esc 暂停', G.state === 'pause', 'state=' + G.state);
key('Escape', true); pump(5); key('Escape', false);
check('Esc 恢复', G.state === 'play', 'state=' + G.state);

// —— 冲刺能力拾取 → 弹窗 → 确认 ——
dbg.loadRoom('c1_2', { x: 2, y: 38 });
G.player.x = 4.5 * 32; G.player.y = 4 * 32; // 传送到 orb 旁（磁吸抓取）
pump(80);
check('拾取冲刺道具并弹出提示', !!G.popup && G.abilities.dash, 'popup=' + (G.popup && G.popup.title));
key('KeyZ', true); pump(6); key('KeyZ', false); pump(10);
check('确认关闭能力弹窗', !G.popup, 'abilities=' + JSON.stringify(G.abilities));

// —— Boss1 战斗流程 ——
dbg.loadRoom('c1_3', { x: 3, y: 15 });
G.player.hp = 5;
walkRight(400);
check('魔像战开启（闸门落下）', G.fightOn && World.gateClosed === true,
  'fightOn=' + G.fightOn + ' bossActive=' + (G.boss && G.boss.active));
G.boss.hp = 1;
for (let s = 0; s < 60 && !G.flags.boss1; s++) {
  G.player.inv = 80;
  G.player.x = G.boss.x - 46; G.player.y = G.boss.y + G.boss.h - G.player.h;
  G.player.face = 1;
  key('KeyX', true); pump(8); key('KeyX', false); pump(4);
}
pump(140);
check('魔像被击败', G.flags.boss1 === true, 'bossDead=' + (G.boss && G.boss.dead));
check('击败后封印闸门开启', World.bossDefeated === true && World.gateClosed === false);

// —— Boss2 战斗 + 结局 ——
dbg.loadRoom('c2_3', { x: 3, y: 13 });
G.player.hp = 5;
walkRight(400);
check('守望者战开启', G.fightOn && G.boss && G.boss.active, 'fightOn=' + G.fightOn);
G.boss.hp = 1;
for (let s = 0; s < 80 && !G.flags.boss2; s++) {
  G.player.inv = 80;
  G.player.x = G.boss.cx - G.player.w / 2; G.player.y = G.boss.y + 90;
  key('ArrowUp', true);
  key('KeyX', true); pump(6);
  key('KeyX', false); key('ArrowUp', false); pump(4);
}
pump(160);
check('守望者被击败', G.flags.boss2 === true);
check('星门生成', !!G.portal, 'portal=' + !!G.portal);
if (G.portal) {
  G.player.x = G.portal.x - G.player.w / 2;
  G.player.y = G.portal.y - G.player.h / 2;
  G.player.inv = 200;
  pump(140);
  check('触碰星门进入结局', G.state === 'ending', 'state=' + G.state);
  pump(260);
  key('KeyZ', true); pump(10); key('KeyZ', false);
  check('结局后返回标题', G.state === 'title', 'state=' + G.state);
}

if (errors.length) {
  console.log('\n捕获错误 ' + errors.length + ' 条:');
  errors.slice(0, 10).forEach((e) => console.log('  ' + e));
  process.exitCode = 1;
} else console.log('\n无运行时错误，冒烟测试完成');
