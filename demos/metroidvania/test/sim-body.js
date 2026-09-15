// 在 vm 沙箱内执行的仿真测试体
function loadRoomForTest(id) {
  World.load(ROOMS[id], id, { boss1: false, boss2: false });
  G.chapter = ROOMS[id].chapter;
}

function freshPlayer(tx, ty, ab) {
  G.abilities = { dash: !!(ab && ab.dash), dj: !!(ab && ab.dj) };
  const p = new Player();
  p.spawnAt(tx, ty);
  p.hp = 5;
  // 稳定帧：落地、记录安全点
  for (let i = 0; i < 12; i++) { p.update(); Input.end(); }
  return p;
}

function feetY(p) { return p.y + p.h; }

function runAllTests() {
  const R = [];

  // —— 1. 地图完整性 ——
  {
    let info = [];
    let ok = true;
    const allowed = new Set('#=^kpcf sdjWVGH12345.'.split(''));
    for (const [id, def] of Object.entries(ROOMS)) {
      for (let y = 0; y < def.map.length; y++) {
        for (let x = 0; x < def.map[y].length; x++) {
          const c = def.map[y][x];
          if (!allowed.has(c)) { ok = false; info.push(id + ' 非法字符 ' + c + ' @' + x + ',' + y); }
        }
      }
      // 地面实体（f 飞行 / V 浮空Boss 除外）必须站在实心上
      for (let y = 0; y < def.map.length; y++) {
        for (let x = 0; x < def.map[y].length; x++) {
          const c = def.map[y][x];
          if ('kpcWs'.includes(c)) {
            const below = def.map[y + 1] && def.map[y + 1][x];
            if (!'#GH'.includes(below)) { ok = false; info.push(id + ' 实体' + c + ' 悬空 @' + x + ',' + y + ' 下方=' + below); }
          }
        }
      }
      for (const [d, ex] of Object.entries(def.exits || {})) {
        if (!ROOMS[ex.room]) { ok = false; info.push(id + ' 出口' + d + ' 指向不存在的 ' + ex.room); }
      }
      const digits = new Set();
      def.map.forEach(row => [...row].forEach(c => { if (c >= '1' && c <= '9') digits.add(c); }));
      for (const d of digits) if (!def.exits[d]) { ok = false; info.push(id + ' 触发 ' + d + ' 无出口表'); }
    }
    R.push({ name: '地图完整性（字符/落地/出口）', pass: ok, info: info.slice(0, 6).join('; ') || ('房间数 ' + Object.keys(ROOMS).length) });
  }

  // —— 2. 基础跳跃：原地满跳高度 & 平跳距离 ——
  {
    loadRoomForTest('c1_3');
    const p = freshPlayer(20, 15);
    const sfeet = feetY(p);
    let minY = sfeet;
    Input.keys.jump = true; Input.pressed.jump = true; // 全程按住
    for (let i = 0; i < 90; i++) {
      p.update(); Input.end();
      minY = Math.min(minY, feetY(p));
      if (i > 10 && p.grounded) break;
    }
    Input.clear();
    const hTiles = (sfeet - minY) / 32;
    R.push({ name: '满跳高度 3.2~4 瓦', pass: hTiles >= 3.2 && hTiles < 4, info: hTiles.toFixed(2) + ' 瓦' });

    const p2 = freshPlayer(5, 15);
    const sx2 = p2.x;
    Input.keys.right = true; Input.keys.jump = true; Input.pressed.jump = true;
    for (let i = 0; i < 120; i++) {
      p2.update(); Input.end();
      if (i > 8 && p2.grounded) break;
    }
    Input.clear();
    const d2 = (p2.x - sx2) / 32;
    R.push({ name: '平跳水平距离 4.5~5.8 瓦', pass: d2 >= 4.5 && d2 <= 5.8, info: d2.toFixed(2) + ' 瓦' });
  }

  // —— 3. 冲刺跳跃距离（c1_3 平地）——
  {
    loadRoomForTest('c1_3');
    const p = freshPlayer(5, 15, { dash: true });
    const sx = p.x;
    Input.keys.right = true; Input.keys.jump = true; Input.pressed.jump = true;
    let dashed = false;
    for (let i = 0; i < 150; i++) {
      if (i === 11 && !dashed) { Input.set('dash', true); dashed = true; }
      if (i === 12) Input.keys.dash = false;
      p.update(); Input.end();
      if (i > 20 && p.grounded) break;
    }
    Input.clear();
    const d = (p.x - sx) / 32;
    R.push({ name: '跳+冲刺 水平 6.3~8.5 瓦', pass: d >= 6.3 && d <= 8.5, info: d.toFixed(2) + ' 瓦' });
  }

  // —— 4. c1_1 尖刺坑（4瓦）可跳过、不受伤 ——
  {
    loadRoomForTest('c1_1');
    const p = freshPlayer(20, 14);
    Input.keys.right = true;
    for (let i = 0; i < 200 && !p.dead; i++) {
      if (p.grounded && p.x > 23 * 32 && p.x < 24.5 * 32) Input.set('jump', true);
      p.update(); Input.end();
      if (feetY(p) > 16 * 32) break;
    }
    Input.clear();
    const crossed = p.x > 29.5 * 32 && p.grounded && feetY(p) <= 15 * 32 + 1;
    R.push({ name: 'c1_1 跳过尖刺坑', pass: crossed && p.hp === 5, info: 'x=' + (p.x / 32).toFixed(1) + ' hp=' + p.hp });
  }

  // —— 5. c1_2 深沟（新几何）：有冲刺能过、无冲刺过不去 ——
  {
    loadRoomForTest('c1_2');
    const p = freshPlayer(8, 5, { dash: true });
    Input.keys.right = true; Input.keys.jump = true; Input.pressed.jump = true;
    let dashed = false, landed = false;
    for (let i = 0; i < 220; i++) {
      if (i === 11 && !dashed) { Input.set('dash', true); dashed = true; }
      if (i === 12) Input.keys.dash = false;
      p.update(); Input.end();
      if (p.grounded && i > 13) { landed = true; break; }
      if (feetY(p) > 8.5 * 32) break;
    }
    Input.clear();
    const okDash = landed && feetY(p) >= 6.9 * 32 && feetY(p) <= 7.1 * 32 && p.x >= 14.9 * 32;
    R.push({ name: 'c1_2 冲刺过沟（有冲刺）', pass: okDash, info: 'x=' + (p.x / 32).toFixed(2) + ' feet=' + (feetY(p) / 32).toFixed(2) + ' landed=' + landed });

    let noDashLanded = false;
    for (let jumpAt = 0; jumpAt <= 16; jumpAt += 2) {
      const q = freshPlayer(8, 5, { dash: false });
      Input.keys.right = true;
      for (let i = 0; i < 220; i++) {
        if (i === jumpAt) { Input.keys.jump = true; Input.set('jump', true); }
        if (i === jumpAt + 1) Input.keys.jump = false;
        q.update(); Input.end();
        if (q.grounded && i > jumpAt + 1) {
          if (feetY(q) >= 6.9 * 32 && feetY(q) <= 7.1 * 32 && q.x >= 14.9 * 32) noDashLanded = true;
          break;
        }
        if (feetY(q) > 8.5 * 32) break;
      }
      Input.clear();
      if (noDashLanded) break;
    }
    R.push({ name: 'c1_2 无冲刺过不去', pass: !noDashLanded, info: noDashLanded ? '无冲刺也能过！' : 'gating 成立' });
  }

  // —— 6. c1_2 烟囱蹬墙跳能爬到顶（新几何：通道 cols3-6）——
  {
    loadRoomForTest('c1_2');
    const p = freshPlayer(5, 14);
    let reached = false;
    for (let i = 0; i < 1200; i++) {
      if (p.grounded) Input.set('jump', true);
      else if (p.sliding && p.wjLock <= 0) Input.set('jump', true);
      Input.keys.right = p.face > 0;
      Input.keys.left = p.face < 0;
      p.update(); Input.end();
      if (p.y < 6 * 32) { reached = true; break; }
      if (p.y > 17 * 32 && i > 90) break;
    }
    Input.clear();
    R.push({ name: 'c1_2 蹬墙跳爬烟囱', pass: reached, info: reached ? '到顶 y=' + (p.y / 32).toFixed(1) : '卡在 y=' + (p.y / 32).toFixed(1) });
  }

  // —— 7. c2_2 高差 5 瓦：二段跳能上、单跳不能 ——
  {
    // 7a. 开阔场地（c1_3 中央无遮挡）测二段跳总高度
    loadRoomForTest('c1_3');
    const p0 = freshPlayer(20, 15, { dj: true });
    const s0 = feetY(p0);
    let min0 = s0;
    Input.keys.jump = true; Input.pressed.jump = true;
    for (let i = 0; i < 90; i++) {
      if (i === 20) Input.pressed.jump = true;
      p0.update(); Input.end();
      min0 = Math.min(min0, feetY(p0));
      if (i > 30 && p0.grounded) break;
    }
    Input.clear();
    const djH = (s0 - min0) / 32;
    R.push({ name: '二段跳总高度 ≥5.5 瓦', pass: djH >= 5.5 && djH < 8, info: djH.toFixed(2) + ' 瓦' });

    // 7b. c2_2 实际攀爬：在 L1 左侧边缘起跳→二段跳越过平台顶→横移落台
    loadRoomForTest('c2_2');
    const p = freshPlayer(2, 36, { dj: true });
    Input.keys.jump = true; Input.pressed.jump = true;
    let landed = false;
    for (let i = 0; i < 200; i++) {
      if (i === 18) Input.pressed.jump = true;   // 二段跳
      if (i === 32) Input.keys.jump = false;
      if (i >= 24) Input.keys.right = true;      // 越过台面后横移
      p.update(); Input.end();
      if (p.grounded && i > 22) { landed = true; break; }
    }
    Input.clear();
    const okUp = landed && Math.abs(feetY(p) - 32 * 32) < 4 && p.x >= 2.5 * 32 && p.x <= 13 * 32;
    R.push({ name: 'c2_2 二段跳上 5 瓦台', pass: okUp, info: 'feet=' + (feetY(p) / 32).toFixed(2) + ' landed=' + landed + ' x=' + (p.x / 32).toFixed(1) });

    // 7c. 原地单跳（无 DJ）上不去
    loadRoomForTest('c1_3');
    const q = freshPlayer(20, 15, { dj: false });
    const sfeet = feetY(q);
    let maxUp = sfeet;
    Input.keys.jump = true; Input.pressed.jump = true;
    for (let i = 0; i < 90; i++) {
      q.update(); Input.end();
      maxUp = Math.min(maxUp, feetY(q));
      if (i > 10 && q.grounded) break;
    }
    Input.clear();
    const singleH = (sfeet - maxUp) / 32;
    R.push({ name: '单跳 <4.6 瓦（挡住 5 瓦台阶）', pass: singleH < 4.6, info: '单跳最高 ' + singleH.toFixed(2) + ' 瓦' });
  }

  // —— 8. c2_1 平台连跳可行（起点岛→P_b）——
  {
    loadRoomForTest('c2_1');
    const p = freshPlayer(4, 13);
    Input.keys.right = true;
    for (let i = 0; i < 400; i++) {
      if (p.grounded && p.x > 7 * 32) Input.set('jump', true);
      p.update(); Input.end();
      if (p.grounded && p.x > 12 * 32) break;
      if (p.hp < 5 || p.dead) break;
    }
    Input.clear();
    R.push({ name: 'c2_1 跨第一断桥', pass: p.grounded && p.x >= 12 * 32 && p.hp === 5, info: 'x=' + (p.x / 32).toFixed(1) + ' hp=' + p.hp });
  }

  // —— 9. 玩家受伤/无敌帧 ——
  {
    loadRoomForTest('c1_1');
    const p = freshPlayer(7, 14);
    p.hurt(1, p.cx + 50);
    const inv1 = p.inv > 0 && p.hp === 4;
    p.hurt(1, p.cx + 50);
    const inv2 = p.hp === 4;
    R.push({ name: '受伤与无敌帧', pass: inv1 && inv2, info: 'hp=' + p.hp + ' inv=' + p.inv });
  }

  return R;
}
