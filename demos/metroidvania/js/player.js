// 玩家：小骑士。移动手感含土狼时间 / 跳跃缓冲 / 蹬墙跳 / 冲刺 / 二段跳 / 下劈弹跳
const PHYS = {
  grav: 0.55, maxFall: 13,
  run: 4.3, acc: 0.62, airAcc: 0.46, fric: 0.72,
  jumpV: -11.5, coyote: 6, buffer: 8, cut: 0.42,
  wjX: 6.8, wjY: -10.8, wallSlide: 2.6, wjLock: 9,
  dashV: 12, dashT: 10, dashCD: 30,
  djV: -10.4, pogoV: -10,
  atkTotal: 16, atkCD: 9
};

class Player {
  constructor() {
    this.w = 24; this.h = 42;
    this.hpMax = 5;
    this.spawnAt(2, 2);
    this.hp = this.hpMax;
  }

  spawnAt(tx, ty) {
    this.x = (tx + 0.5) * T - this.w / 2;
    this.y = (ty + 1) * T - this.h;
    this.vx = 0; this.vy = 0;
    this.face = 1;
    this.grounded = false; this.coyote = 0; this.jbuf = 0;
    this.jumps = 0; this.airDash = true;
    this.dashT = 0; this.dashCD = 0; this.wjLock = 0;
    this.dropT = 0;
    this.atkT = 0; this.atkCD = 0; this.atkDir = 'side';
    this.combo = 0; this.sinceAtk = 99; this.swingId = 0; this.pogoDone = false;
    this.inv = 0; this.dead = false;
    this.wallDir = 0; this.sliding = false;
    this.trigArm = false;
    this.lastSafe = { x: this.x, y: this.y }; this.safeT = 0;
    this.animT = 0; this.landT = 0; this.jumpCut = true;
  }

  get cx() { return this.x + this.w / 2; }
  get cy() { return this.y + this.h / 2; }
  rect() { return { x: this.x, y: this.y, w: this.w, h: this.h }; }

  solidBox(x, y, w, h) {
    const x0 = Math.floor(x / T), x1 = Math.floor((x + w - 0.01) / T);
    const y0 = Math.floor(y / T), y1 = Math.floor((y + h - 0.01) / T);
    for (let ty = y0; ty <= y1; ty++)
      for (let tx = x0; tx <= x1; tx++)
        if (World.isSolid(tx, ty)) return true;
    return false;
  }

  hurt(dmg, srcX) {
    if (this.inv > 0 || this.dead || this.hp <= 0) return false;
    this.hp -= dmg;
    this.inv = 75;
    this.dashT = 0;
    this.vx = (this.cx < srcX ? -1 : 1) * 5.5;
    this.vy = -4;
    if (this.hp <= 0) this.dead = true;
    return true;
  }

  heal(n) { this.hp = Math.min(this.hpMax, this.hp + n); }

  pogo() {
    this.vy = PHYS.pogoV;
    this.jumps = 1;
    this.airDash = true;
    AudioSys.sfx('pogo');
  }

  update() {
    if (this.dead) return;
    this.animT++;
    if (this.inv > 0) this.inv--;
    if (this.landT > 0) this.landT--;
    if (this.dashCD > 0) this.dashCD--;
    if (this.atkCD > 0) this.atkCD--;
    if (this.atkT > 0) this.atkT--;
    if (this.sinceAtk < 99) this.sinceAtk++;
    if (this.wjLock > 0) this.wjLock--;
    if (this.dropT > 0) this.dropT--;

    const ax = (Input.down('right') ? 1 : 0) - (Input.down('left') ? 1 : 0);
    if (ax !== 0 && this.dashT <= 0 && this.wjLock <= 0) this.face = ax;

    // —— 水平 ——
    if (this.dashT > 0) {
      this.vx = this.face * PHYS.dashV;
      this.vy = 0;
      this.dashT--;
      if (this.dashT === 0) { this.vx = this.face * PHYS.run * 0.65; this.dashCD = PHYS.dashCD; }
      if (this.animT % 2 === 0) Particles.ghost(this.x + this.w / 2, this.y, this.w, this.h, this.face);
    } else {
      const acc = this.grounded ? PHYS.acc : PHYS.airAcc;
      if (this.wjLock > 0) {
        // 蹬墙跳后的短暂锁操作
      } else if (ax !== 0) {
        this.vx += ax * acc;
        this.vx = Math.max(-PHYS.run, Math.min(PHYS.run, this.vx));
      } else if (this.grounded) {
        this.vx *= PHYS.fric;
        if (Math.abs(this.vx) < 0.1) this.vx = 0;
      } else {
        this.vx *= 0.985;
      }
    }

    // —— 蹬墙检测 ——
    this.wallDir = 0;
    if (!this.grounded && this.dashT <= 0) {
      if (ax > 0 && this.solidBox(this.x + 2, this.y + 6, this.w, this.h - 12)) this.wallDir = 1;
      else if (ax < 0 && this.solidBox(this.x - 2, this.y + 6, this.w, this.h - 12)) this.wallDir = -1;
    }
    this.sliding = false;
    if (this.wallDir !== 0 && this.vy > 0 && !this.grounded) {
      this.sliding = true;
      this.vy = Math.min(this.vy, PHYS.wallSlide);
      this.jumps = 1; this.airDash = true;   // 贴墙回充
      if (this.animT % 6 === 0) Particles.dust(this.x + (this.wallDir > 0 ? this.w : 0), this.y + this.h * 0.6, 1, 0.6);
    }

    // —— 跳跃 ——
    if (Input.hit('jump')) this.jbuf = PHYS.buffer;
    else if (this.jbuf > 0) this.jbuf--;
    const jumpHeld = Input.down('jump');

    if (this.grounded) { this.coyote = PHYS.coyote; } else if (this.coyote > 0) this.coyote--;

    // 站在单向平台上按 ↓+跳 下落穿板
    if (this.jbuf > 0 && this.grounded && Input.down('down') && !this.solidBox(this.x, this.y + 2, this.w, this.h)) {
      this.y += 3; this.dropT = 12; this.jbuf = 0; this.grounded = false;
    }

    if (this.jbuf > 0) {
      if (this.coyote > 0 && this.dashT <= 0) {
        this.vy = PHYS.jumpV; this.grounded = false; this.coyote = 0; this.jbuf = 0;
        this.jumpCut = false; AudioSys.sfx('jump');
        Particles.dust(this.cx, this.y + this.h, 5, 2.4);
      } else if ((this.sliding || this.wallDir !== 0) && this.dashT <= 0) {
        const d = this.wallDir || (this.solidBox(this.x + 2, this.y, this.w, this.h) ? 1 : -1);
        this.vy = PHYS.wjY; this.vx = -d * PHYS.wjX;
        this.face = -d; this.wjLock = PHYS.wjLock; this.jbuf = 0; this.jumpCut = false;
        this.jumps = 1; this.airDash = true;
        AudioSys.sfx('walljump');
        Particles.dust(this.x + (d > 0 ? this.w : 0), this.y + this.h * 0.5, 6, 2);
      } else if (G.abilities.dj && this.jumps > 0 && this.dashT <= 0) {
        this.vy = PHYS.djV; this.jumps--; this.jbuf = 0; this.jumpCut = false;
        AudioSys.sfx('djump');
        Particles.ring(this.cx, this.y + this.h - 4, 'rgba(150,220,255,0.7)', 4, 30);
      }
    }
    // 松开跳跃键截断上升
    if (!jumpHeld && this.vy < 0 && !this.jumpCut && this.dashT <= 0) {
      this.vy *= PHYS.cut; this.jumpCut = true;
    }

    // —— 重力 ——
    if (this.dashT <= 0) {
      this.vy += PHYS.grav;
      if (this.sliding) this.vy = Math.min(this.vy, PHYS.wallSlide);
      this.vy = Math.min(this.vy, PHYS.maxFall);
    }

    // —— 冲刺 ——
    if (Input.hit('dash') && G.abilities.dash && this.dashCD <= 0 && this.dashT <= 0 && (this.grounded || this.airDash)) {
      if (!this.grounded) this.airDash = false;
      this.dashT = PHYS.dashT;
      this.vy = 0;
      AudioSys.sfx('dash');
      Particles.dust(this.cx - this.face * 10, this.y + this.h - 4, 6, 2);
    }

    // —— 攻击 ——
    if (Input.hit('attack') && this.atkCD <= 0) {
      this.combo = (this.sinceAtk < 32) ? (this.combo % 3) + 1 : 1;
      this.sinceAtk = 0;
      this.atkT = PHYS.atkTotal;
      this.atkCD = PHYS.atkCD + (this.combo === 3 ? 8 : 0);
      this.swingId++;
      this.pogoDone = false;
      this.atkDir = (!this.grounded && Input.down('down')) ? 'down'
                  : (Input.down('up') && !this.grounded) ? 'up' : 'side';
      AudioSys.sfx('attack');
    }

    // —— 位移与碰撞 ——
    this.moveX(this.vx);
    this.moveY(this.vy);

    // 落地
    if (this.grounded) {
      if (this.landT === 0 && this.animT > 5) { /* noop */ }
      this.jumps = 1;
      this.airDash = true;
      // 记录安全点（不在地刺旁）
      if (!World.overlapsTile('^', this.x - T, this.y, this.w + 2 * T, this.h + 4, 0)) {
        this.safeT++;
        if (this.safeT > 8) this.lastSafe = { x: this.x, y: this.y };
      } else this.safeT = 0;
    } else this.safeT = 0;

    // —— 地刺 / 深渊 ——
    if (this.inv <= 0) {
      if (this.vy >= -2 && World.overlapsTile('^', this.x, this.y, this.w, this.h, 5)) {
        this.hurt(1, this.cx + (Math.random() < 0.5 ? -40 : 40));
        this.recover();
      }
      if (World.voidBottom && this.y > World.h * T + 90) {
        this.hurt(1, this.cx + 40);
        this.recover();
      }
    }

    // 触发器布防（离开触发瓦片后才能再次触发）
    if (!this.overlapsTrigger()) this.trigArm = true;
  }

  recover() {
    this.x = this.lastSafe.x;
    this.y = this.lastSafe.y;
    this.vx = 0; this.vy = 0;
    this.dashT = 0;
    G.shake = Math.max(G.shake, 5);
  }

  overlapsTrigger() {
    const r = this.rect();
    const x0 = Math.floor(r.x / T), x1 = Math.floor((r.x + r.w) / T);
    const y0 = Math.floor(r.y / T), y1 = Math.floor((r.y + r.h) / T);
    for (let ty = y0; ty <= y1; ty++)
      for (let tx = x0; tx <= x1; tx++) {
        const c = World.tileAt(tx, ty);
        if (c >= '1' && c <= '9') return true;
      }
    return false;
  }

  moveX(dx) {
    this.x += dx;
    if (dx > 0 && this.solidBox(this.x, this.y, this.w, this.h)) {
      this.x = Math.floor((this.x + this.w) / T) * T - this.w - 0.01;
      if (this.dashT > 0) { this.dashT = 0; this.dashCD = PHYS.dashCD; }
      this.vx = 0;
    } else if (dx < 0 && this.solidBox(this.x, this.y, this.w, this.h)) {
      this.x = (Math.floor(this.x / T) + 1) * T + 0.01;
      if (this.dashT > 0) { this.dashT = 0; this.dashCD = PHYS.dashCD; }
      this.vx = 0;
    }
  }

  moveY(dy) {
    const prevBottom = this.y + this.h;
    this.y += dy;
    this.grounded = false;
    if (dy > 0) {
      if (this.solidBox(this.x, this.y, this.w, this.h)) {
        this.y = Math.floor((this.y + this.h) / T) * T - this.h - 0.01;
        if (this.vy > 7) { Particles.dust(this.cx, this.y + this.h, 6, 3); AudioSys.sfx('land'); this.landT = 8; }
        this.vy = 0;
        this.grounded = true;
      } else if (this.dropT <= 0) {
        // 单向平台
        const y1t = Math.floor((this.y + this.h - 0.01) / T);
        const x0 = Math.floor(this.x / T), x1 = Math.floor((this.x + this.w - 0.01) / T);
        for (let tx = x0; tx <= x1; tx++) {
          if (World.tileAt(tx, y1t) === '=' && prevBottom <= y1t * T + 8) {
            this.y = y1t * T - this.h - 0.01;
            if (this.vy > 7) { Particles.dust(this.cx, this.y + this.h, 5, 3); AudioSys.sfx('land'); this.landT = 8; }
            this.vy = 0;
            this.grounded = true;
            break;
          }
        }
      }
    } else if (dy < 0 && this.solidBox(this.x, this.y, this.w, this.h)) {
      this.y = (Math.floor(this.y / T) + 1) * T + 0.01;
      this.vy = 0;
    }
  }

  // 当前挥剑的有效判定框（无则 null）
  getAttackBox() {
    if (this.atkT > 12 || this.atkT < 4) return null;
    const cx = this.cx;
    if (this.atkDir === 'down') return { x: cx - 22, y: this.y + this.h - 6, w: 44, h: 52 };
    if (this.atkDir === 'up')   return { x: cx - 24, y: this.y - 50, w: 48, h: 52 };
    return this.face > 0
      ? { x: this.x + this.w - 8, y: this.y - 10, w: 52, h: this.h + 18 }
      : { x: this.x - 44, y: this.y - 10, w: 52, h: this.h + 18 };
  }

  draw(ctx) {
    if (this.dead) return;
    if (this.inv > 0 && this.dashT <= 0 && ((this.inv >> 2) & 1) === 0) return;

    const pal = PAL[G.chapter];
    const bob = this.grounded && Math.abs(this.vx) > 0.5 ? Math.abs(Math.sin(this.animT * 0.25)) * 2.5 : 0;
    const squash = this.landT > 0 ? 1 - this.landT * 0.03 : 1;
    const stretch = this.dashT > 0 ? 1.3 : (!this.grounded ? 1 + Math.max(-0.12, Math.min(0.12, -this.vy * 0.012)) : 1);

    ctx.save();
    ctx.translate(this.cx, this.y + this.h);
    ctx.scale(this.face * (this.dashT > 0 ? 1.25 : squash), (this.dashT > 0 ? 0.78 : 1 / squash) * stretch);

    // 斗篷
    ctx.fillStyle = '#2e3a5c';
    ctx.beginPath();
    ctx.moveTo(-10, -6);
    ctx.quadraticCurveTo(-13 - Math.abs(this.vx), -22, -9, -34 - bob);
    ctx.lineTo(9, -34 - bob);
    ctx.quadraticCurveTo(13 - Math.max(0, -this.vx * 0.5), -20, 10, -6);
    ctx.quadraticCurveTo(0, -2, -10, -6);
    ctx.fill();
    // 围巾
    ctx.fillStyle = '#c04a3a';
    ctx.fillRect(-9, -30 - bob, 18, 5);
    ctx.beginPath();
    ctx.moveTo(-8, -28 - bob);
    ctx.lineTo(-16 - Math.abs(this.vx) * 1.6, -24 - bob + Math.sin(this.animT * 0.3) * 2);
    ctx.lineTo(-8, -22 - bob);
    ctx.fill();
    // 头
    ctx.fillStyle = '#e8e6df';
    ctx.beginPath();
    ctx.arc(1, -38 - bob, 9, 0, 7);
    ctx.fill();
    // 眼睛
    ctx.fillStyle = pal.accent;
    ctx.fillRect(3, -40 - bob, 3, 5);
    ctx.fillRect(-3, -40 - bob, 3, 5);
    // 腿
    if (this.grounded && Math.abs(this.vx) > 0.5) {
      const ph = Math.sin(this.animT * 0.35);
      ctx.fillStyle = '#232c46';
      ctx.fillRect(-6 + ph * 4, -6, 5, 7);
      ctx.fillRect(2 - ph * 4, -6, 5, 7);
    } else {
      ctx.fillStyle = '#232c46';
      ctx.fillRect(-6, -6, 5, 7);
      ctx.fillRect(2, -6, 5, 7);
    }
    ctx.restore();

    // 挥剑弧光
    if (this.atkT > 3 && this.atkT < 14) {
      const ph = (14 - this.atkT) / 11;
      const a = 1 - ph * 0.75;
      ctx.save();
      ctx.translate(this.cx, this.cy + 2);
      let rot = 0;
      if (this.atkDir === 'down') rot = Math.PI / 2;
      else if (this.atkDir === 'up') rot = -Math.PI / 2;
      else rot = (this.face > 0 ? 0 : Math.PI) + (ph - 0.5) * 1.6;
      ctx.rotate(rot);
      ctx.globalAlpha = a;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 8 * (1 - ph * 0.5);
      ctx.beginPath(); ctx.arc(-6, 0, 36, -0.9, 0.9); ctx.stroke();
      ctx.strokeStyle = pal.accent;
      ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(-6, 0, 42, -0.7, 0.7); ctx.stroke();
      ctx.restore();
      ctx.globalAlpha = 1;
    }
  }
}
