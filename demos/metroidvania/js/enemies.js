// 敌人与实体：爬行者 / 飞翼 / 炮手 / 子弹 / 震荡波 / 落石 / 道具 / 灯台 / 传送门
function aabb(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

class Enemy {
  constructor(tx, ty, w, h) {
    this.w = w; this.h = h;
    this.x = (tx + 0.5) * T - w / 2;
    this.y = (ty + 1) * T - h;
    this.vx = 0; this.vy = 0;
    this.hp = 2; this.dead = false;
    this.flash = 0; this.t = Math.random() * 100;
    this.lastHitSwing = -1;
    this.harmful = true;
  }
  get cx() { return this.x + this.w / 2; }
  get cy() { return this.y + this.h / 2; }
  rect() { return { x: this.x, y: this.y, w: this.w, h: this.h }; }

  tileSolid(px, py) { return World.isSolid(Math.floor(px / T), Math.floor(py / T)); }

  hurt(dmg, fromX) {
    if (this.dead) return false;
    this.hp -= dmg;
    this.flash = 8;
    if (this.hp <= 0) {
      this.dead = true;
      const pal = PAL[G.chapter];
      Particles.shards(this.cx, this.cy, 14, pal.enemyBody);
      Particles.sparks(this.cx, this.cy, 8, pal.accent);
      AudioSys.sfx('boom');
      G.shake = Math.max(G.shake, 4);
      if (Math.random() < 0.25) G.healMotes.push(new HealMote(this.cx, this.cy));
    }
    return true;
  }
}

class Crawler extends Enemy {
  constructor(tx, ty) {
    super(tx, ty, 40, 24);
    this.hp = 2;
    this.dir = Math.random() < 0.5 ? -1 : 1;
    this.speed = 0.8 + Math.random() * 0.3;
  }
  update() {
    this.t++;
    if (this.flash > 0) this.flash--;
    this.vy = Math.min(this.vy + 0.5, 12);
    // 垂直碰撞（地面）
    let ny = this.y + this.vy;
    if (this.vy >= 0) {
      const yb = Math.floor((ny + this.h) / T);
      if (this.tileSolid(this.x + 2, yb * T + 1) || this.tileSolid(this.x + this.w - 2, yb * T + 1)) {
        ny = yb * T - this.h - 0.01;
        this.vy = 0;
      }
    }
    this.y = ny;
    // 水平：撞墙或走到边缘掉头
    const aheadX = this.dir > 0 ? this.x + this.w + 3 : this.x - 3;
    const floorAhead = this.tileSolid(aheadX, this.y + this.h + 6);
    const wallAhead = this.tileSolid(aheadX, this.y + this.h / 2);
    if (this.wallAheadLast !== wallAhead && wallAhead) this.dir *= -1;
    this.wallAheadLast = wallAhead;
    if (!floorAhead) this.dir *= -1;
    this.x += this.dir * this.speed;
    this.x = Math.max(T * 0.5, Math.min(World.w * T - T * 0.5 - this.w, this.x));
  }
  draw(ctx) {
    const pal = PAL[G.chapter];
    ctx.save();
    ctx.translate(this.cx, this.y + this.h);
    const wob = Math.sin(this.t * 0.2) * 1.5;
    ctx.fillStyle = this.flash > 0 ? '#ffffff' : pal.enemyBody;
    ctx.beginPath();
    ctx.ellipse(0, -10 + wob * 0.3, this.w / 2, 9, 0, 0, 7);
    ctx.fill();
    // 背刺
    ctx.fillStyle = this.flash > 0 ? '#ffffff' : pal.enemyDark;
    for (let i = -1; i <= 1; i++) {
      ctx.beginPath();
      ctx.moveTo(i * 10 - 3, -16 + wob * 0.3);
      ctx.lineTo(i * 10, -24 + wob * 0.3);
      ctx.lineTo(i * 10 + 3, -16 + wob * 0.3);
      ctx.fill();
    }
    // 腿
    ctx.strokeStyle = pal.enemyDark;
    ctx.lineWidth = 2.5;
    for (let i = -1; i <= 1; i++) {
      const ph = Math.sin(this.t * 0.25 + i * 2) * 3;
      ctx.beginPath();
      ctx.moveTo(i * 11, -8);
      ctx.lineTo(i * 11 + ph, 0);
      ctx.stroke();
    }
    // 眼
    ctx.fillStyle = pal.enemyEye;
    ctx.fillRect(this.dir * 12 - 3, -13, 4, 3);
    ctx.restore();
  }
}

class Flyer extends Enemy {
  constructor(tx, ty) {
    super(tx, ty, 34, 26);
    this.hp = 2;
    this.ax = this.x; this.ay = this.y;
  }
  update() {
    this.t++;
    if (this.flash > 0) this.flash--;
    const p = G.player;
    const dx = p.cx - this.cx, dy = p.cy - this.cy;
    const d = Math.hypot(dx, dy);
    if (d < 280 && !p.dead) {
      this.vx += Math.sign(dx) * 0.06;
      this.vy += Math.sign(dy) * 0.05;
    } else {
      this.vx += Math.sign(this.ax - this.x) * 0.03;
      this.vy += Math.sign(this.ay - this.y + Math.sin(this.t * 0.05) * 14 - this.vy * 2) * 0.02;
    }
    this.vx = Math.max(-2.3, Math.min(2.3, this.vx));
    this.vy = Math.max(-2.0, Math.min(2.0, this.vy));
    this.x += this.vx; this.y += this.vy;
    // 不钻进墙里
    if (this.tileSolid(this.cx, this.cy)) { this.x -= this.vx * 2; this.y -= this.vy * 2; this.vx *= -1; this.vy *= -1; }
  }
  draw(ctx) {
    const pal = PAL[G.chapter];
    ctx.save();
    ctx.translate(this.cx, this.cy);
    const flap = Math.sin(this.t * 0.45);
    // 翅膀
    ctx.fillStyle = this.flash > 0 ? '#fff' : pal.enemyDark;
    ctx.beginPath();
    ctx.moveTo(-6, 0); ctx.lineTo(-24, -10 - flap * 9); ctx.lineTo(-8, 5); ctx.fill();
    ctx.beginPath();
    ctx.moveTo(6, 0); ctx.lineTo(24, -10 - flap * 9); ctx.lineTo(8, 5); ctx.fill();
    // 身体
    ctx.fillStyle = this.flash > 0 ? '#fff' : pal.enemyBody;
    ctx.beginPath(); ctx.arc(0, 0, 10, 0, 7); ctx.fill();
    // 眼
    ctx.fillStyle = pal.enemyEye;
    ctx.beginPath(); ctx.arc(0, -1, 4, 0, 7); ctx.fill();
    // 尾光
    ctx.globalAlpha = 0.5;
    ctx.strokeStyle = pal.enemyEye;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, 8); ctx.lineTo(Math.sin(this.t * 0.1) * 6, 18); ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.restore();
  }
}

class Shooter extends Enemy {
  constructor(tx, ty) {
    super(tx, ty, 36, 40);
    this.hp = 3;
    this.cd = 60 + Math.random() * 60;
    this.tele = 0;
  }
  update() {
    this.t++;
    if (this.flash > 0) this.flash--;
    const p = G.player;
    const d = Math.hypot(p.cx - this.cx, p.cy - this.cy);
    if (this.tele > 0) {
      this.tele--;
      if (this.tele === 0) {
        const ang = Math.atan2(p.cy - this.cy, p.cx - this.cx);
        G.bullets.push(new Bullet(this.cx, this.cy - 6, Math.cos(ang) * 3.8, Math.sin(ang) * 3.8));
        AudioSys.sfx('shoot');
        this.cd = 110 + Math.random() * 40;
      }
    } else if (d < 460 && !p.dead) {
      this.cd--;
      if (this.cd <= 0) this.tele = 34;
    }
  }
  draw(ctx) {
    const pal = PAL[G.chapter];
    const p = G.player;
    ctx.save();
    ctx.translate(this.cx, this.y + this.h);
    ctx.fillStyle = this.flash > 0 ? '#fff' : pal.enemyDark;
    ctx.beginPath();
    ctx.moveTo(-16, 0); ctx.lineTo(-11, -34); ctx.lineTo(11, -34); ctx.lineTo(16, 0);
    ctx.closePath(); ctx.fill();
    // 眼
    const ang = Math.atan2(p.cy - (this.y + 12), p.cx - this.cx);
    const charge = this.tele > 0 ? 1 : 0.4;
    ctx.fillStyle = pal.enemyEye;
    ctx.globalAlpha = 0.35 + charge * 0.65 + Math.sin(this.t * 0.3) * 0.1;
    ctx.beginPath(); ctx.arc(0, -22, 8, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#1a1424';
    ctx.beginPath(); ctx.arc(0, -22, 4, 0, 7); ctx.fill();
    ctx.fillStyle = pal.enemyEye;
    ctx.beginPath(); ctx.arc(Math.cos(ang) * 2.5, -22 + Math.sin(ang) * 2.5, 2, 0, 7); ctx.fill();
    ctx.restore();
  }
}

class Bullet {
  constructor(x, y, vx, vy, r) {
    this.x = x; this.y = y; this.vx = vx; this.vy = vy;
    this.r = r || 7;
    this.w = this.r * 2; this.h = this.r * 2;
    this.life = 320; this.dead = false;
    this.t = 0;
    this.destructible = true;
    this.lastHitSwing = -1;
  }
  get cx() { return this.x; }
  get cy() { return this.y; }
  rect() { return { x: this.x - this.r, y: this.y - this.r, w: this.r * 2, h: this.r * 2 }; }
  update() {
    this.t++;
    this.x += this.vx; this.y += this.vy;
    this.life--;
    if (this.life <= 0) this.dead = true;
    if (World.isSolid(Math.floor(this.x / T), Math.floor(this.y / T))) {
      this.dead = true;
      Particles.sparks(this.x, this.y, 5, PAL[G.chapter].accent);
    }
  }
  kill() {
    this.dead = true;
    Particles.sparks(this.x, this.y, 6, '#cfe6ff');
    AudioSys.sfx('hit');
  }
  draw(ctx) {
    const pal = PAL[G.chapter];
    ctx.save();
    ctx.translate(this.x, this.y);
    ctx.globalAlpha = 0.35;
    ctx.fillStyle = pal.enemyEye;
    ctx.beginPath(); ctx.arc(0, 0, this.r + 4 + Math.sin(this.t * 0.4) * 1.5, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#f2f6ff';
    ctx.beginPath(); ctx.arc(0, 0, this.r, 0, 7); ctx.fill();
    ctx.fillStyle = pal.enemyEye;
    ctx.beginPath(); ctx.arc(0, 0, this.r * 0.5, 0, 7); ctx.fill();
    ctx.restore();
  }
}

// 魔像落地激起的地面震荡波
class ShockWave {
  constructor(x, y, dir) {
    this.x = x; this.y = y;
    this.vx = dir * 5.2;
    this.w = 26; this.h = 30;
    this.life = 130; this.dead = false;
    this.t = 0;
    this.harmful = true;
    this.lastHitSwing = -1;
    this.hp = 1;
  }
  get cx() { return this.x + this.w / 2; }
  get cy() { return this.y + this.h / 2; }
  rect() { return { x: this.x, y: this.y, w: this.w, h: this.h }; }
  update() {
    this.t++;
    this.x += this.vx;
    this.life--;
    if (this.life <= 0) this.dead = true;
    const tx = Math.floor((this.vx > 0 ? this.x + this.w : this.x) / T);
    if (World.isSolid(tx, Math.floor((this.y + this.h - 4) / T)) ||
        World.isSolid(tx, Math.floor((this.y + this.h / 2) / T))) {
      this.dead = true;
      Particles.dust(this.cx, this.y + this.h, 5, 2);
    }
    if (this.t % 3 === 0) Particles.dust(this.cx, this.y + this.h, 1, 1.4);
  }
  hurt() { this.dead = true; Particles.sparks(this.cx, this.cy, 6, '#ffd28a'); return true; }
  draw(ctx) {
    ctx.save();
    ctx.translate(this.cx, this.y + this.h);
    for (let i = 0; i < 3; i++) {
      const ph = (this.t * 0.3 + i * 1.1) % 2;
      ctx.globalAlpha = 0.7 * (1 - ph * 0.5);
      ctx.fillStyle = i === 2 ? '#ffe9a0' : '#d98a3c';
      ctx.beginPath();
      ctx.moveTo(-10 + i * 4, 0);
      ctx.lineTo(-4 + i * 4, -14 - ph * 12 - i * 5);
      ctx.lineTo(2 + i * 4, 0);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }
}

// 落石（魔像技能）：先显示阴影警示，再坠落
class Rock {
  constructor(x) {
    this.x = x - 14; this.y = 2 * T;
    this.w = 28; this.h = 28;
    this.vy = 0;
    this.warn = 42;
    this.dead = false;
    this.t = 0;
    this.harmful = true;
    this.lastHitSwing = -1;
    this.hp = 1;
  }
  get cx() { return this.x + this.w / 2; }
  get cy() { return this.y + this.h / 2; }
  rect() { return { x: this.x, y: this.y, w: this.w, h: this.h }; }
  update() {
    this.t++;
    if (this.warn > 0) {
      this.warn--;
      if (this.warn === 0) AudioSys.sfx('shoot');
      return;
    }
    this.vy = Math.min(this.vy + 0.5, 13);
    this.y += this.vy;
    if (World.isSolid(Math.floor(this.cx / T), Math.floor((this.y + this.h) / T))) {
      this.dead = true;
      Particles.shards(this.cx, this.y + this.h, 10, '#7a7484');
      Particles.dust(this.cx, this.y + this.h, 8, 3);
      AudioSys.sfx('boom');
      G.shake = Math.max(G.shake, 4);
    }
  }
  hurt() { this.dead = true; Particles.shards(this.cx, this.cy, 8, '#7a7484'); return true; }
  draw(ctx) {
    if (this.warn > 0) {
      ctx.globalAlpha = 0.35 + Math.sin(this.t * 0.5) * 0.2;
      ctx.fillStyle = '#ff5a4a';
      ctx.beginPath();
      ctx.arc(this.cx, this.y + 5 * T, 10, 0, 7);
      ctx.fill();
      ctx.globalAlpha = 1;
      return;
    }
    ctx.save();
    ctx.translate(this.cx, this.cy);
    ctx.rotate(this.t * 0.1);
    ctx.fillStyle = '#5c5668';
    ctx.beginPath();
    ctx.moveTo(-13, 4); ctx.lineTo(-9, -11); ctx.lineTo(6, -13); ctx.lineTo(13, 2); ctx.lineTo(4, 13); ctx.lineTo(-8, 12);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#7a7484';
    ctx.fillRect(-6, -6, 7, 5);
    ctx.restore();
  }
}

class HealMote {
  constructor(x, y) {
    this.x = x; this.y = y;
    this.w = 16; this.h = 16;
    this.vy = -2;
    this.life = 480; this.dead = false;
    this.t = 0;
  }
  get cx() { return this.x; }
  get cy() { return this.y; }
  rect() { return { x: this.x - 8, y: this.y - 8, w: 16, h: 16 }; }
  update() {
    this.t++;
    this.life--;
    if (this.life <= 0) this.dead = true;
    this.vy = Math.min(this.vy + 0.12, 1.2);
    this.y += this.vy;
    if (World.isSolid(Math.floor(this.x / T), Math.floor((this.y + 8) / T))) {
      this.y = Math.floor((this.y + 8) / T) * T - 8;
      this.vy = 0;
    }
    const p = G.player;
    if (aabb(this.rect(), p.rect())) {
      p.heal(1);
      this.dead = true;
      AudioSys.sfx('heal');
      Particles.ring(this.x, this.y, 'rgba(255,120,140,0.8)', 4, 26);
    }
  }
  draw(ctx) {
    const a = this.life < 90 ? (Math.sin(this.t * 0.4) > 0 ? 1 : 0.3) : 1;
    ctx.globalAlpha = a;
    ctx.save();
    ctx.translate(this.x, this.y + Math.sin(this.t * 0.1) * 3);
    ctx.fillStyle = '#ff7a8a';
    ctx.shadowColor = '#ff7a8a';
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.moveTo(0, -8); ctx.lineTo(6, 0); ctx.lineTo(0, 8); ctx.lineTo(-6, 0);
    ctx.closePath(); ctx.fill();
    ctx.restore();
    ctx.globalAlpha = 1;
  }
}

class Pickup {
  constructor(tx, ty, type) {
    this.type = type; // 'dash' | 'dj'
    this.x = (tx + 0.5) * T;
    this.y = (ty + 0.5) * T;
    this.t = Math.random() * 50;
    this.dead = false;
  }
  update() {
    this.t++;
    if (this.t % 5 === 0)
      Particles.mote(this.x + (Math.random() - 0.5) * 20, this.y + (Math.random() - 0.5) * 20,
        this.type === 'dash' ? 'rgba(255,180,90,0.8)' : 'rgba(130,225,255,0.8)');
    const p = G.player;
    const d = Math.hypot(p.cx - this.x, p.cy - this.y);
    if (d < 90) { // 磁吸
      this.x += (p.cx - this.x) * 0.1;
      this.y += (p.cy - this.y) * 0.1;
    }
    if (d < 30) {
      this.dead = true;
      G.onAbilityGet(this.type);
    }
  }
  draw(ctx) {
    const col = this.type === 'dash' ? '#ffb454' : '#7ff0ff';
    const r = 11 + Math.sin(this.t * 0.08) * 2;
    ctx.save();
    ctx.translate(this.x, this.y + Math.sin(this.t * 0.05) * 4);
    ctx.globalAlpha = 0.25;
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(0, 0, r + 12, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = col;
    ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.arc(0, 0, r + 6, this.t * 0.03, this.t * 0.03 + 4.6); ctx.stroke();
    ctx.fillStyle = col;
    ctx.shadowColor = col;
    ctx.shadowBlur = 14;
    if (this.type === 'dash') {
      ctx.beginPath();
      ctx.moveTo(-5, -7); ctx.lineTo(4, 0); ctx.lineTo(-5, 7);
      ctx.lineTo(-2, 0); ctx.closePath(); ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(-6, 2); ctx.quadraticCurveTo(0, -9, 6, 2);
      ctx.quadraticCurveTo(0, -2, -6, 2); ctx.fill();
    }
    ctx.restore();
  }
}

class Checkpoint {
  constructor(tx, ty) {
    this.tx = tx; this.ty = ty;
    this.x = (tx + 0.5) * T;
    this.y = (ty + 1) * T; // 底部
    this.active = false;
    this.t = Math.random() * 40;
  }
  update() {
    this.t++;
    const p = G.player;
    if (!this.active &&
        Math.abs(p.cx - this.x) < 34 && Math.abs(p.cy - (this.y - 40)) < 50) {
      this.active = true;
      G.checkpoint = { room: World.id, x: this.tx, y: this.ty };
      G.player.hp = G.player.hpMax;
      AudioSys.sfx('checkpoint');
      Particles.ring(this.x, this.y - 44, 'rgba(255,200,120,0.9)', 8, 70);
      G.toast('灯台已点亮 — 生命完全恢复');
    }
    if (this.active && this.t % 7 === 0)
      Particles.mote(this.x + (Math.random() - 0.5) * 10, this.y - 60, 'rgba(255,190,110,0.9)');
  }
  draw(ctx) {
    ctx.save();
    ctx.translate(this.x, this.y);
    // 灯柱
    ctx.fillStyle = '#2a2433';
    ctx.fillRect(-3, -52, 6, 52);
    ctx.fillRect(-10, -2, 20, 4);
    // 灯笼
    const lit = this.active;
    const glow = lit ? 0.55 + Math.sin(this.t * 0.1) * 0.15 : 0.18;
    ctx.globalAlpha = glow;
    ctx.fillStyle = lit ? '#ffb454' : '#4a6a9a';
    ctx.beginPath(); ctx.arc(0, -56, 26, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = lit ? '#ffd9a0' : '#5a7aa8';
    ctx.beginPath();
    ctx.moveTo(-7, -64); ctx.lineTo(7, -64); ctx.lineTo(9, -48); ctx.lineTo(-9, -48);
    ctx.closePath(); ctx.fill();
    if (lit) {
      ctx.fillStyle = '#fff2d0';
      ctx.beginPath(); ctx.arc(0, -56, 4 + Math.sin(this.t * 0.2) * 1.2, 0, 7); ctx.fill();
    }
    ctx.restore();
  }
}

class Portal {
  constructor(x, y) {
    this.x = x; this.y = y;
    this.t = 0;
  }
  update() {
    this.t++;
    if (this.t % 3 === 0) {
      const a = Math.random() * Math.PI * 2;
      Particles.mote(this.x + Math.cos(a) * 34, this.y + Math.sin(a) * 34, 'rgba(130,235,255,0.9)');
    }
    const p = G.player;
    if (Math.hypot(p.cx - this.x, p.cy - this.y) < 40 && this.t > 60) G.onPortal();
  }
  draw(ctx) {
    ctx.save();
    ctx.translate(this.x, this.y);
    for (let i = 0; i < 3; i++) {
      ctx.globalAlpha = 0.5;
      ctx.strokeStyle = '#7ff0ff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(0, 0, 34 - i * 9, this.t * (0.04 + i * 0.015), this.t * (0.04 + i * 0.015) + 4.2);
      ctx.stroke();
    }
    ctx.globalAlpha = 0.3 + Math.sin(this.t * 0.1) * 0.15;
    ctx.fillStyle = '#9df5ff';
    ctx.beginPath(); ctx.arc(0, 0, 16, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.restore();
  }
}
