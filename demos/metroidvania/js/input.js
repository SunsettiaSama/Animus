// 键盘输入：hit = 本帧刚按下，down = 持续按住
const Input = {
  keys: Object.create(null),
  pressedQ: Object.create(null),
  map: {
    left:    ['ArrowLeft', 'KeyA'],
    right:   ['ArrowRight', 'KeyD'],
    up:      ['ArrowUp', 'KeyW'],
    down:    ['ArrowDown', 'KeyS'],
    jump:    ['KeyZ', 'KeyK', 'Space'],
    attack:  ['KeyX', 'KeyJ'],
    dash:    ['KeyC', 'KeyL', 'ShiftLeft', 'ShiftRight'],
    pause:   ['Escape', 'KeyP'],
    mute:    ['KeyM'],
    confirm: ['Enter', 'KeyZ', 'Space', 'KeyJ'],
    restart: ['KeyR'],
    quit:    ['KeyQ']
  },

  init() {
    addEventListener('keydown', (e) => {
      if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) e.preventDefault();
      if (!e.repeat && !this.keys[e.code]) this.pressedQ[e.code] = true;
      this.keys[e.code] = true;
      AudioSys.unlock();
    });
    addEventListener('keyup', (e) => { this.keys[e.code] = false; });
    addEventListener('blur', () => { this.keys = Object.create(null); });
  },

  down(a) { return (this.map[a] || []).some((c) => this.keys[c]); },
  hit(a) { return (this.map[a] || []).some((c) => this.pressedQ[c]); },
  end() { this.pressedQ = Object.create(null); }
};
