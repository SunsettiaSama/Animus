// 程序化音频：全部用 WebAudio 合成，无外部资源
const AudioSys = {
  ctx: null,
  master: null,
  musicGain: null,
  muted: false,
  musicTimer: null,
  musicStep: 0,
  musicMode: 'none',

  unlock() {
    if (this.ctx) { if (this.ctx.state === 'suspended') this.ctx.resume(); return; }
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.5;
      this.master.connect(this.ctx.destination);
      this.musicGain = this.ctx.createGain();
      this.musicGain.gain.value = 0.14;
      this.musicGain.connect(this.master);
    } catch (e) { /* 无音频环境时静默失败 */ }
  },

  toggleMute() {
    if (!this.master) return;
    this.muted = !this.muted;
    this.master.gain.value = this.muted ? 0 : 0.5;
  },

  tone(freq, dur, type, vol, slide, delay, dest) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime + (delay || 0);
    const o = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    o.type = type || 'square';
    o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), t + dur);
    g.gain.setValueAtTime(vol || 0.15, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g);
    g.connect(dest || this.master);
    o.start(t);
    o.stop(t + dur + 0.05);
  },

  noise(dur, vol, cutoff, delay) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime + (delay || 0);
    const len = Math.max(1, Math.floor(this.ctx.sampleRate * dur));
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    const f = this.ctx.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = cutoff || 1200;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(vol || 0.12, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(f); f.connect(g); g.connect(this.master);
    src.start(t);
  },

  sfx(name) {
    if (!this.ctx) return;
    switch (name) {
      case 'jump':    this.tone(300, 0.13, 'square', 0.09, 240); break;
      case 'djump':   this.tone(420, 0.15, 'square', 0.09, 320); this.tone(630, 0.12, 'sine', 0.06, 260, 0.02); break;
      case 'walljump':this.tone(260, 0.1, 'square', 0.09, 180); this.noise(0.06, 0.05, 2400); break;
      case 'dash':    this.noise(0.16, 0.14, 3200); this.tone(220, 0.14, 'sawtooth', 0.07, -140); break;
      case 'attack':  this.noise(0.05, 0.1, 5200); this.tone(760, 0.06, 'triangle', 0.07, -420); break;
      case 'hit':     this.tone(190, 0.07, 'square', 0.12, -60); this.noise(0.05, 0.1, 2600); break;
      case 'pogo':    this.tone(240, 0.16, 'sine', 0.11, 330); break;
      case 'hurt':    this.tone(320, 0.28, 'sawtooth', 0.13, -220); this.noise(0.12, 0.08, 900); break;
      case 'die':     this.tone(400, 0.7, 'sawtooth', 0.13, -360); this.tone(200, 0.9, 'triangle', 0.1, -160, 0.1); break;
      case 'pickup':  [523, 659, 784, 1047].forEach((f, i) => this.tone(f, 0.22, 'sine', 0.11, 0, i * 0.09)); break;
      case 'checkpoint': [392, 523, 659].forEach((f, i) => this.tone(f, 0.5, 'triangle', 0.09, 0, i * 0.12)); this.noise(0.3, 0.04, 800, 0.1); break;
      case 'land':    this.noise(0.05, 0.06, 500); break;
      case 'shoot':   this.tone(820, 0.09, 'sawtooth', 0.07, -420); break;
      case 'boom':    this.noise(0.4, 0.2, 700); this.tone(120, 0.35, 'sine', 0.14, -70); break;
      case 'roar':    this.tone(90, 0.6, 'sawtooth', 0.16, 30); this.tone(60, 0.7, 'square', 0.1, 18, 0.05); this.noise(0.5, 0.1, 500); break;
      case 'gate':    this.noise(0.35, 0.14, 320); this.tone(70, 0.4, 'square', 0.1, -25); break;
      case 'portal':  [440, 554, 659, 880, 1109].forEach((f, i) => this.tone(f, 0.6, 'sine', 0.08, 20, i * 0.1)); break;
      case 'select':  this.tone(600, 0.07, 'square', 0.08, 120); break;
      case 'heal':    this.tone(660, 0.2, 'sine', 0.1, 200); break;
    }
  },

  // —— 极简程序化 BGM：琶音 + 低音，按章节/战斗切换音色与音阶 ——
  setMusic(mode) {
    this.musicMode = mode;
    this.musicStep = 0;
    if (this.musicTimer || !this.ctx) return;
    this.musicTimer = setInterval(() => this._musicTick(), 150);
  },

  _mf(m) { return 440 * Math.pow(2, (m - 69) / 12); },

  _musicTick() {
    if (!this.ctx || this.musicMode === 'none' || this.muted) return;
    const s = this.musicStep++;
    let arp = null, bass = null, every = 2, arpType = 'triangle';
    if (this.musicMode === 'ch1') {
      arp = [57, 60, 64, 60, 55, 59, 62, 59, 53, 57, 60, 57, 52, 55, 59, 64];
      bass = [33, 31, 28, 31];
    } else if (this.musicMode === 'ch2') {
      arp = [69, 76, 72, 79, 67, 74, 71, 78, 65, 72, 69, 76, 67, 74, 71, 78];
      bass = [45, 43, 40, 43];
      arpType = 'sine';
    } else if (this.musicMode === 'boss') {
      arp = [45, 45, 48, 45, 51, 48, 46, 43, 45, 45, 48, 52, 51, 48, 46, 44];
      bass = [33, 33, 32, 31];
      every = 1;
      arpType = 'square';
    }
    if (!arp) return;
    if (s % every === 0) {
      const n = arp[(s / every) % arp.length];
      this.tone(this._mf(n), 0.26, arpType, 0.05, 0, 0, this.musicGain);
    }
    if (s % 16 === 0) {
      const b = bass[(s / 16) % bass.length];
      this.tone(this._mf(b), 1.6, 'sine', 0.09, 0, 0, this.musicGain);
      this.tone(this._mf(b + 12), 1.2, 'triangle', 0.03, 0, 0.05, this.musicGain);
    }
  }
};
