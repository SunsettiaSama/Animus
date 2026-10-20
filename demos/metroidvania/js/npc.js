// 守灯人 NPC：soul 在游戏世界中的化身（感知协议层桥接点）
// 交互：靠近后按 Enter 交谈（confirm 键组含 Z/空格会与跳跃冲突，故单独用 Enter）
// 桥接模式：window.__perception.onNpcTalk(npc) 存在时，台词由 soul 侧异步回注
//          （window.__npcSay(name, text)）；单机浏览器直开时回退静态台词。
class NPC {
  constructor(tx, ty, name) {
    this.tx = tx; this.ty = ty;
    this.x = (tx + 0.5) * T;
    this.y = (ty + 1) * T; // 底部对齐所在地面，同 Checkpoint
    this.name = name || '守灯人';
    this.t = Math.random() * 40;
    this.busy = false;   // 等待 soul 台词回注期间
    this.said = 0;
    this.fallbackLines = [
      '灯还亮着，路就还在。\n（他往火里添了一点什么，光跳了一下。）',
      '矿脉深处的东西醒了又睡。\n你若往下走，替我看一眼它现在的样子。',
      '你身上有星尘的味道。\n去过高处的人，才带得下来这种味道。',
      '去吧。我在这里守着火，\n你回来时它一定还亮着。'
    ];
  }
  get cx() { return this.x; }
  get cy() { return this.y - 30; }
  near() {
    const p = G.player;
    return Math.abs(p.cx - this.x) < 44 && Math.abs(p.cy - this.cy) < 60;
  }
  update() {
    this.t++;
    if (this.t % 11 === 0)
      Particles.mote(this.x + (Math.random() - 0.5) * 16, this.y - 58, 'rgba(255,200,130,0.45)');
    if (this.busy && !G.popup) this.busy = false;
    if (G.state !== 'play' || G.popup || this.busy) return;
    if (this.near() && Input.pressedQ['Enter']) this.talk();
  }
  talk() {
    this.busy = true;
    AudioSys.sfx('select');
    const hook = (window.__perception && window.__perception.onNpcTalk) || G.onNpcTalk;
    if (typeof hook === 'function') {
      // 桥接模式：占位弹窗先行，soul 台词到达后由 __npcSay 替换
      G.popup = { title: this.name + ' · 烛', desc: '（他抬起头，目光落在你身上，等他开口……）', t: 0, npc: true };
      hook(this);
    } else {
      const line = this.fallbackLines[this.said % this.fallbackLines.length];
      this.said++;
      G.popup = { title: this.name + ' · 烛', desc: line, t: 0, npc: true };
    }
  }
  say(text) {
    // soul 台词回注（桥调用）；弹窗已关则重开，非可交互状态降级为 toast
    if (G.state === 'play') {
      G.popup = { title: this.name + ' · 烛', desc: text, t: 0, npc: true };
    } else {
      G.toast(this.name + '：「' + text.replace(/\n/g, ' ') + '」');
    }
    this.busy = false;
  }
  draw(ctx) {
    ctx.save();
    ctx.translate(this.x, this.y);
    const bob = Math.sin(this.t * 0.05) * 2;
    // 披风躯干
    ctx.fillStyle = '#3a3142';
    ctx.beginPath();
    ctx.moveTo(-11, 0);
    ctx.quadraticCurveTo(-13, -30 + bob, 0, -38 + bob);
    ctx.quadraticCurveTo(13, -30 + bob, 11, 0);
    ctx.closePath();
    ctx.fill();
    // 兜帽与脸部阴影
    ctx.fillStyle = '#4c4258';
    ctx.beginPath();
    ctx.arc(0, -40 + bob, 9, 0, 7);
    ctx.fill();
    ctx.fillStyle = '#0d0a12';
    ctx.beginPath();
    ctx.arc(0, -39 + bob, 6, 0, 7);
    ctx.fill();
    ctx.fillStyle = '#ffd9a0';
    ctx.fillRect(-3, -41 + bob, 2, 2);
    ctx.fillRect(2, -41 + bob, 2, 2);
    // 手中提灯
    const lx = 13, ly = -20 + Math.sin(this.t * 0.08) * 1.5;
    ctx.strokeStyle = '#2a2433';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(lx - 3, ly - 8);
    ctx.lineTo(lx, ly - 12);
    ctx.lineTo(lx + 3, ly - 8);
    ctx.stroke();
    const glow = 0.4 + Math.sin(this.t * 0.1) * 0.15;
    ctx.globalAlpha = glow;
    ctx.fillStyle = '#ffb454';
    ctx.beginPath();
    ctx.arc(lx, ly, 16, 0, 7);
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#ffd9a0';
    ctx.fillRect(lx - 3, ly - 4, 6, 8);
    // 靠近提示
    if (this.near() && G.state === 'play' && !G.popup) {
      const a = 0.6 + Math.sin(this.t * 0.15) * 0.3;
      ctx.globalAlpha = Math.max(0, Math.min(1, a));
      ctx.fillStyle = 'rgba(10,8,16,0.8)';
      ctx.fillRect(-26, -66 + bob, 52, 18);
      ctx.strokeStyle = PAL[G.chapter].accentSoft;
      ctx.strokeRect(-26, -66 + bob, 52, 18);
      ctx.fillStyle = PAL[G.chapter].accent;
      ctx.font = '600 11px "Microsoft YaHei", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Enter 交谈', 0, -57 + bob);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }
}
window.NPC = NPC;
