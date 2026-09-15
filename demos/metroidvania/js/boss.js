// Boss 1：矿洞魔像（走位 / 跃击震波 / 落石 / 硬直）
// Boss 2：星核守望者（瞄准弹幕 / 环形爆发 / 瞬移 / 横扫冲锋）
class BossBase {
  constructor(tx, ty, w, h, hp) {
    this.w = w; this.h = h;
    this.x = (tx + 0.5) * T - w / 2;
    this.y = (ty + 1) * T - h;
    this.hpMax = hp; this.hp = hp;
    this.vx = 0; this.vy = 0;
    this.active = false; this.dead = false;
    this.flash = 0; this.t = 0;
    this.harmful = true;
    this.lastHitSwing = -1;
    this.dieT = 0;
  }
  get cx() { return this.x + this.w / 2; }
  get cy() { return this.y + this.h / 2; }
  rect() { return { x: this.x, y: this.y, w: this.w, h: this.h }; }

  hurt(dmg, fromX) {
    if (this.dead || this.dieT > 0) return false;
    this.hp -= dmg;
    this.flash = 7;
    AudioSys.sfx('hit');
    if (this.hp <= 0) {
      this.dieT = 1;
      this.harmful = false;
      G.hitstop = 26;
      G.shake = 12;
      AudioSys.sfx('boom');
      AudioSys.sfx('roar');
    }
    return true;
  }

  updateDeath() {
    this.dieT++;
    if (this.dieT % 6 === 0) {
      Particles.shards(this.cx + (Math.random() - 0.5) * this.w, this.cy + (Math.random() - 0.5) * this.h, 10, PAL[G.chapter].enemyBody);
      Particles.sparks(this.cx, this.cy, 6, PAL[G.chapter].accent);
      G.shake = Math.max(G.shake, 5);
    }
    if (this.dieT === 70) {
      this.dead = true;
      Particles.ring(this.cx, this.cy, 'rgba(255,230,160,0.95)', 10, 150);
      G.onBossDefeated(this);
    }
  }
}

class Boss1 extends BossBase {
  constructor(tx, ty) {
    super(tx, ty, 64, 72, 22);
    this.state = 'sleep';
    this.st = 0;
    this.slams = 0;
    this.face = -1;
    this.airborne = false;
    this.name = '矿洞魔像';
  }

  tileSolid(px, py) { return World.isSolid(Math.floor(px / T), Math.floor(py / T)); }

  update() {
    this.t++;
    if (this.flash > 0) this.flash--;
    if (this.dieT > 0) { this.updateDeath(); return; }
    if (this.dead) return;
    if (!this.active) { this.face = G.player.cx < this.cx ? -1 : 1; return; }

    const p = G.player;
    const enr = this.hp <= 8;
    const spd = enr ? 1.15 : 1;

    this.st--;
    switch (this.state) {
      case 'idle':
        this.vx *= 0.8;
        if (this.st <= 0) {
          this.face = p.cx < this.cx ? -1 : 1;
          if (this.slams % 3 === 2 && this.slams > 0) {
            this.state = 'stagger'; this.st = 120; this.slams = 0;
            AudioSys.sfx('gate');
          } else {
            this.state = 'walk'; this.st = (enr ? 48 : 70);
          }
        }
        break;
      case 'walk':
        this.vx = this.face * (enr ? 2.5 : 1.6);
        if (this.st <= 0) {
          this.state = 'crouch'; this.st = 26 * spd;
        }
        break;
      case 'crouch':
        this.vx *= 0.7;
        if (this.st <= 0) {
          // 跃向玩家
          this.state = 'leap';
          this.airborne = true;
          this.vy = -13;
          this.vx = Math.max(-6.5, Math.min(6.5, (p.cx - this.cx) / 42));
          AudioSys.sfx('jump');
        }
        break;
      case 'leap':
        if (this.vy > 0 && this.groundBelow()) {
          this.state = 'idle'; this.st = (enr ? 26 : 44);
          this.vy = 0; this.airborne = false;
          this.slams++;
          G.shake = 10;
          AudioSys.sfx('boom');
          Particles.dust(this.cx, this.y + this.h, 22, 6);
          G.shocks.push(new ShockWave(this.x - 10, this.y + this.h - 30, -1));
          G.shocks.push(new ShockWave(this.x + this.w - 16, this.y + this.h - 30, 1));
          // 落石（玩家在平台上时的压力）
          if (p.y < this.y - 40 || Math.random() < 0.3) {
            G.rocks.push(new Rock(p.cx + (Math.random() - 0.5) * 60));
            if (enr) G.rocks.push(new Rock(p.cx + (Math.random() - 0.5) * 120));
          }
        }
        break;
      case 'stagger':
        this.vx = 0;
        if (this.t % 10 === 0) Particles.sparks(this.cx, this.cy - 10, 3, '#ffd28a');
        if (this.st <= 0) { this.state = 'idle'; this.st = 30; }
        break;
    }

    // 物理
    this.vy = Math.min(this.vy + 0.5, 14);
    this.x += this.vx;
    // 撞墙停下
    if (this.tileSolid(this.vx > 0 ? this.x + this.w : this.x, this.y + this.h * 0.6)) {
      this.x -= this.vx; this.vx = 0;
      if (this.state === 'leap') { this.state = 'idle'; this.st = 30; this.vy = 0; this.airborne = false; }
    }
    this.x = Math.max(T, Math.min(World.w * T - T - this.w, this.x));
    this.y += this.vy;
    if (this.vy >= 0 && this.groundBelow()) {
      this.y = Math.floor((this.y + this.h) / T) * T - this.h - 0.01;
      this.vy = 0;
    }
  }

  groundBelow() {
    const yb = Math.floor((this.y + this.h + 1) / T);
    return this.tileSolid(this.x + 6, yb * T) || this.tileSolid(this.x + this.w - 6, yb * T);
  }

  draw(ctx) {
    if (this.dead) return;
    const pal = PAL[G.chapter];
    const flash = this.flash > 0;
    const sq = this.state === 'crouch' ? 0.82 : this.state === 'leap' ? 1.1 : 1;
    const dying = this.dieT > 0 && (this.dieT >> 2) % 2 === 0;
    ctx.save();
    ctx.translate(this.cx, this.y + this.h);
    ctx.scale((1 / sq) * (this.dieT > 0 ? 0.98 : 1), sq);
    if (dying) ctx.globalAlpha = 0.6;

    // 腿
    ctx.fillStyle = flash ? '#fff' : pal.enemyDark;
    ctx.fillRect(-24, -26, 18, 26);
    ctx.fillRect(6, -26, 18, 26);
    // 躯干
    ctx.fillStyle = flash ? '#fff' : pal.enemyBody;
    ctx.beginPath();
    ctx.moveTo(-30, -26);
    ctx.lineTo(-26, -58);
    ctx.lineTo(26, -58);
    ctx.lineTo(30, -26);
    ctx.closePath(); ctx.fill();
    // 裂纹
    ctx.strokeStyle = flash ? '#fff' : pal.enemyDark;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(-12, -56); ctx.lineTo(-6, -44); ctx.lineTo(-14, -34); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(14, -54); ctx.lineTo(10, -40); ctx.stroke();
    // 手臂
    ctx.fillStyle = flash ? '#fff' : pal.enemyDark;
    const armSw = this.state === 'leap' ? -8 : Math.sin(this.t * 0.1) * 3;
    ctx.fillRect(-38, -54 + armSw, 12, 30);
    ctx.fillRect(26, -54 - armSw, 12, 30);
    // 核心之眼
    const eyeCol = this.state === 'stagger' ? '#8a9aa8' : (this.hp <= 8 ? '#ff6a4a' : pal.enemyEye);
    ctx.fillStyle = eyeCol;
    ctx.shadowColor = eyeCol;
    ctx.shadowBlur = 12;
    ctx.beginPath(); ctx.arc(0, -44, 8 + (this.state === 'crouch' ? 2 : 0), 0, 7); ctx.fill();
    ctx.shadowBlur = 0;
    // 角
    ctx.fillStyle = flash ? '#fff' : pal.enemyDark;
    ctx.beginPath(); ctx.moveTo(-18, -58); ctx.lineTo(-26, -70); ctx.lineTo(-12, -60); ctx.fill();
    ctx.beginPath(); ctx.moveTo(18, -58); ctx.lineTo(26, -70); ctx.lineTo(12, -60); ctx.fill();

    ctx.restore();
    ctx.globalAlpha = 1;
  }
}

class Boss2 extends BossBase {
  constructor(tx, ty) {
    super(tx, ty, 56, 56, 34);
    this.name = '星核守望者';
    this.state = 'hover';
    this.st = 80;
    this.anchor = { x: this.cx, y: this.cy };
    this.anchorIdx = 0;
    this.queue = ['aim', 'move', 'radial', 'move', 'aim', 'sweep'];
    this.qi = 0;
    this.shots = 0;
    this.sweepDir = 1;
    this.tpT = 0;
  }

  anchors() {
    const W = World.w * T;
    return [
      { x: W * 0.25, y: 3.6 * T },
      { x: W * 0.5, y: 2.6 * T },
      { x: W * 0.75, y: 3.6 * T },
      { x: W * 0.35, y: 4.6 * T },
      { x: W * 0.65, y: 4.6 * T }
    ];
  }

  fireAt(ang, speed) {
    G.bullets.push(new Bullet(this.cx, this.cy, Math.cos(ang) * speed, Math.sin(ang) * speed, 8));
  }

  update() {
    this.t++;
    if (this.flash > 0) this.flash--;
    if (this.dieT > 0) { this.updateDeath(); return; }
    if (this.dead) return;
    if (!this.active) return;

    const p = G.player;
    const p2 = this.hp <= this.hpMax * 0.5;
    this.st--;

    switch (this.state) {
      case 'hover': {
        const bob = Math.sin(this.t * 0.05) * 6;
        this.x += (this.anchor.x - this.cx) * 0.06;
        this.y += (this.anchor.y + bob - this.cy) * 0.06;
        if (this.st <= 0) {
          const next = this.queue[this.qi % this.queue.length];
          this.qi++;
          this.state = next;
          this.shots = 0;
          if (next === 'aim') this.st = p2 ? 130 : 100;
          if (next === 'radial') { this.st = 40; AudioSys.sfx('roar'); }
          if (next === 'move') { this.st = 46; this.tpT = 20; Particles.ring(this.cx, this.cy, 'rgba(150,140,255,0.8)', 8, 60); }
          if (next === 'sweep') {
            this.sweepDir = p.cx < this.cx ? -1 : 1;
            this.st = p2 ? 30 : 40;
            AudioSys.sfx('gate');
          }
        }
        break;
      }
      case 'aim': {
        const bob = Math.sin(this.t * 0.06) * 3;
        this.y += (this.anchor.y + bob - this.cy) * 0.04;
        const interval = p2 ? 20 : 26;
        if (this.st % interval === 0 && this.st > 10) {
          const ang = Math.atan2(p.cy - this.cy, p.cx - this.cx);
          const n = p2 ? 3 : 1;
          for (let i = 0; i < n; i++) {
            const a2 = ang + (i - (n - 1) / 2) * 0.22;
            this.fireAt(a2, 4.3);
          }
          this.shots++;
          AudioSys.sfx('shoot');
          Particles.sparks(this.cx, this.cy, 4, '#b9a6ff');
        }
        if (this.st <= 0) { this.state = 'hover'; this.st = p2 ? 40 : 70; }
        break;
      }
      case 'radial': {
        if (this.st === 12) {
          const n = p2 ? 16 : 12;
          const off = Math.random() * Math.PI;
          for (let i = 0; i < n; i++) this.fireAt(off + (i / n) * Math.PI * 2, p2 ? 3.4 : 3.0);
          AudioSys.sfx('boom');
          G.shake = Math.max(G.shake, 5);
          Particles.ring(this.cx, this.cy, 'rgba(180,160,255,0.9)', 10, 90);
        }
        if (this.st <= 0) { this.state = 'hover'; this.st = 90; }
        break;
      }
      case 'move': {
        if (this.st === 20) {
          // 瞬移
          Particles.sparks(this.cx, this.cy, 14, '#b9a6ff');
          this.anchorIdx = (this.anchorIdx + 1 + Math.floor(Math.random() * 3)) % 5;
          this.anchor = this.anchors()[this.anchorIdx];
          // 贴近玩家的锚点更危险
          if (Math.random() < 0.4) {
            let best = 0, bd = 1e9;
            this.anchors().forEach((a, i) => { const d = Math.hypot(a.x - p.cx, a.y - p.cy); if (d < bd) { bd = d; best = i; } });
            this.anchor = this.anchors()[best]; this.anchorIdx = best;
          }
          this.x = this.anchor.x - this.w / 2;
          this.y = this.anchor.y - this.h / 2;
          Particles.ring(this.cx, this.cy, 'rgba(150,140,255,0.8)', 30, 4);
          AudioSys.sfx('dash');
        }
        if (this.st <= 0) { this.state = 'hover'; this.st = 50; }
        break;
      }
      case 'sweep': {
        if (this.st > 0) {
          // 蓄力：对准玩家高度
          this.y += (p.cy - this.cy) * 0.1;
          if (this.t % 4 === 0) Particles.mote(this.cx + this.sweepDir * 40, this.cy + (Math.random() - 0.5) * 30, 'rgba(255,120,120,0.9)');
        } else {
          this.x += this.sweepDir * 9.5;
          if (this.t % 2 === 0) Particles.ghost(this.cx, this.y, this.w, this.h, this.sweepDir, 'rgba(150,130,255,0.3)');
          const hitWall = this.sweepDir > 0 ? this.x + this.w > World.w * T - T : this.x < T;
          if (hitWall) {
            this.state = 'hover';
            this.st = 70;
            this.anchor = { x: this.cx, y: 3.4 * T };
            G.shake = 6;
            AudioSys.sfx('boom');
            Particles.sparks(this.cx + this.sweepDir * 20, this.cy, 12, '#b9a6ff');
            // 二连扫（狂暴）
            if (p2 && !this.doubleSwept) { this.doubleSwept = true; this.state = 'sweep'; this.st = 26; this.sweepDir *= -1; }
            else this.doubleSwept = false;
          }
        }
        break;
      }
    }
  }

  draw(ctx) {
    if (this.dead) return;
    const pal = PAL[G.chapter];
    const flash = this.flash > 0;
    const p = G.player;
    const dying = this.dieT > 0 && (this.dieT >> 2) % 2 === 0;
    ctx.save();
    ctx.translate(this.cx, this.cy);
    if (dying) ctx.globalAlpha = 0.6;

    // 旋转碎片环
    ctx.fillStyle = flash ? '#fff' : pal.enemyDark;
    for (let i = 0; i < 6; i++) {
      const a = this.t * 0.025 + (i / 6) * Math.PI * 2;
      const r = 34 + Math.sin(this.t * 0.05 + i) * 3;
      ctx.save();
      ctx.translate(Math.cos(a) * r, Math.sin(a) * r * 0.85);
      ctx.rotate(a);
      ctx.beginPath();
      ctx.moveTo(-5, 0); ctx.lineTo(0, -9); ctx.lineTo(5, 0);
      ctx.closePath(); ctx.fill();
      ctx.restore();
    }
    // 外核
    ctx.fillStyle = flash ? '#fff' : '#241f3f';
    ctx.beginPath(); ctx.arc(0, 0, 24, 0, 7); ctx.fill();
    ctx.strokeStyle = this.state === 'sweep' && this.st > 0 ? '#ff6a6a' : pal.enemyEye;
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(0, 0, 24, 0, 7); ctx.stroke();
    // 眼
    const ang = Math.atan2(p.cy - this.cy, p.cx - this.cx);
    const eyeCol = this.hp <= this.hpMax * 0.5 ? '#ff7a6a' : pal.enemyEye;
    ctx.fillStyle = eyeCol;
    ctx.shadowColor = eyeCol;
    ctx.shadowBlur = 16;
    ctx.beginPath(); ctx.arc(0, 0, 11, 0, 7); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#0c0a18';
    ctx.beginPath(); ctx.arc(Math.cos(ang) * 4.5, Math.sin(ang) * 4.5, 5, 0, 7); ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.beginPath(); ctx.arc(Math.cos(ang) * 6, Math.sin(ang) * 6, 1.8, 0, 7); ctx.fill();

    ctx.restore();
    ctx.globalAlpha = 1;
  }
}
