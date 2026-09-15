// 无头物理/关卡校验：node test/sim.js
// 用桩替浏览器 API，加载真实 levels/particles/player 代码做仿真
const fs = require('fs');
const vm = require('vm');

const sandbox = {
  console, Math, Object, Array, JSON, String, Number,
  setInterval: () => 0, clearInterval: () => {}
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

vm.runInContext(`
  var AudioSys = { unlock(){}, sfx(){}, setMusic(){}, tone(){}, noise(){} };
  var PAL = { 1:{accent:'#fff',enemyBody:'#fff',enemyDark:'#111',enemyEye:'#fff'},
              2:{accent:'#fff',enemyBody:'#fff',enemyDark:'#111',enemyEye:'#fff'} };
  var G = { chapter:1, abilities:{dash:false,dj:false}, shake:0, hitstop:0,
            bullets:[], shocks:[], rocks:[], healMotes:[], popup:null, toast(){} };
  var Input = { keys:{}, pressed:{},
    down(a){ return !!this.keys[a]; },
    hit(a){ return !!this.pressed[a]; },
    end(){ this.pressed = {}; },
    set(a,v){ this.keys[a]=v; if(v) this.pressed[a]=true; },
    clear(){ this.keys={}; this.pressed={}; } };
`, sandbox);

for (const f of ['js/levels.js', 'js/particles.js', 'js/player.js']) {
  vm.runInContext(fs.readFileSync(f, 'utf8'), sandbox, { filename: f });
}

const results = [];
function test(name, fn) {
  try { const r = fn(); results.push({ name, ...r }); }
  catch (e) { results.push({ name, pass: false, info: 'EXC ' + e.message }); }
}

vm.runInContext(fs.readFileSync('test/sim-body.js', 'utf8'), sandbox, { filename: 'test/sim-body.js' });

const out = vm.runInContext('runAllTests()', sandbox);
let fail = 0;
for (const r of out) {
  console.log((r.pass ? '  PASS ' : '✗ FAIL ') + r.name + (r.info ? '  — ' + r.info : ''));
  if (!r.pass) fail++;
}
console.log(fail ? ('\n' + fail + ' 个测试失败') : '\n全部通过');
process.exit(fail ? 1 : 0);
