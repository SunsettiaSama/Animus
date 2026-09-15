// 轻量粒子系统
const Particles = {
  list: [],
  MAX: 700,

  add(p) {
    if (this.list.length >= this.MAX) this.list.shift();
    p.t = 0;
    p.maxLife = p.life;
    this.list.push(p);
  },

  dust(x, y, n, spread) {
    for (let i = 0; i < n; i++)
      this.add({ kind: 'dot', x, y, vx: (Math.random() - 0.5) * (spread || 2), vy: -Math.random() * 1.2 - 0.2,
        grav: 0.04, fric: 0.96, life: 20 + Math.random() * 18, r: 2 + Math.random() * 3, col: 'rgba(180,170,200,0.5)' });
  },

  sparks(x, y, n, col) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = 2 + Math.random() * 4;
      this.add({ kind: 'spark', x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 1,
        grav: 0.18, fric: 0.92, life: 14 + Math.random() * 14, r: 1.5 + Math.random() * 2, col: col || '#ffe9a0' });
    }
  },

  shards(x, y, n, col) {
    for (let i = 0; i < n; i++) {
      const a = -Math.PI / 2 + (Math.random() - 0.5) * 2.4, s = 2 + Math.random() * 4.5;
      this.add({ kind: 'shard', x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s,
        grav: 0.3, fric: 0.99, life: 30 + Math.random() * 25, r: 2 + Math.random() * 3.5, col: col || '#c98a5a', rot: Math.random() * 6 });
    }
  },

  ghost(x, y, w, h, face, col) {
    this.add({ kind: 'ghost', x, y, w, h, face, vx: 0, vy: 0, grav: 0, fric: 1, life: 12, col: col || 'rgba(140,170,255,0.35)' });
  },

  mote(x, y, col) {
    this.add({ kind: 'dot', x, y, vx: (Math.random() - 0.5) * 0.3, vy: -0.15 - Math.random() * 0.25,
      grav: -0.002, fric: 1, life: 90 + Math.random() * 90, r: 1 + Math.random() * 1.6, col: col });
  },

  ring(x, y, col, r0, r1) {
    this.add({ kind: 'ring', x, y, vx: 0, vy: 0, grav: 0, fric: 1, life: 22, r0: r0 || 6, r1: r1 || 46, col: col || 'rgba(255,220,150,0.8)' });
  },

  update() {
    const L = this.list;
    for (let i = L.length - 1; i >= 0; i--) {
      const p = L[i];
      p.t++;
      p.life--;
      p.vx *= p.fric;
      p.vy = p.vy * p.fric + p.grav;
      p.x += p.vx;
      p.y += p.vy;
      if (p.life <= 0) L.splice(i, 1);
    }
  },

  draw(ctx, camX, camY) {
    for (const p of this.list) {
      const a = Math.max(0, Math.min(1, p.life / p.maxLife));
      const x = p.x - camX, y = p.y - camY;
      if (x < -60 || x > 1020 || y < -60 || y > 600) continue;
      if (p.kind === 'dot') {
        ctx.globalAlpha = a * 0.8;
        ctx.fillStyle = p.col;
        ctx.beginPath(); ctx.arc(x, y, p.r, 0, 7); ctx.fill();
      } else if (p.kind === 'spark') {
        ctx.globalAlpha = a;
        ctx.strokeStyle = p.col;
        ctx.lineWidth = p.r * 0.8;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - p.vx * 2.2, y - p.vy * 2.2); ctx.stroke();
      } else if (p.kind === 'shard') {
        ctx.globalAlpha = a;
        ctx.fillStyle = p.col;
        ctx.save(); ctx.translate(x, y); ctx.rotate((p.rot || 0) + p.t * 0.15);
        ctx.fillRect(-p.r, -p.r * 0.6, p.r * 2, p.r * 1.2);
        ctx.restore();
      } else if (p.kind === 'ghost') {
        ctx.globalAlpha = a * 0.7;
        ctx.fillStyle = p.col;
        ctx.fillRect(x - p.w / 2, y, p.w, p.h);
      } else if (p.kind === 'ring') {
        const r = p.r0 + (p.r1 - p.r0) * (1 - a);
        ctx.globalAlpha = a * 0.8;
        ctx.strokeStyle = p.col;
        ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }
};
