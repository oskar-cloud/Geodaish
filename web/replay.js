const timecode = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

export class ReplayPlayer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.replay = null;
    this.position = 0;
    this.speed = 1;
    this.playing = !matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.last = null;
    this.endedFor = 0;
    this.lastUi = 0;
    this.toggle = document.querySelector('#play-pause');
    this.seek = document.querySelector('#replay-seek');
    this.toggle.onclick = () => { this.playing = !this.playing; this.updateToggle(); };
    document.querySelector('#replay-reset').onclick = () => { this.position = 0; this.endedFor = 0; this.updateUi(); };
    this.seek.addEventListener('input', () => { this.position = Number(this.seek.value); this.endedFor = 0; this.updateUi(); });
    document.querySelector('#replay-speed').onchange = event => { this.speed = Number(event.target.value); };
    this.updateToggle();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(canvas);
    document.addEventListener('visibilitychange', () => { this.last = null; });
    requestAnimationFrame(time => this.tick(time));
  }

  setReplay(replay, key) {
    if (key === this.key) return;
    this.key = key;
    this.replay = replay;
    this.position = 0;
    this.endedFor = 0;
    this.seek.max = replay ? replay.frames.length - 1 : 1;
    document.querySelector('#replay-empty').hidden = !!replay;
    this.toggle.disabled = this.seek.disabled = !replay;
    document.querySelector('#replay-reset').disabled = !replay;
    document.querySelector('#replay-seed').textContent = replay ? `BANA ${replay.seed}` : 'BANA —';
    document.querySelector('#replay-model-step').textContent = replay ? `Modell: ${replay.modelStep.toLocaleString('sv-SE')} steg` : 'Modell: —';
    document.querySelector('#replay-label').textContent = replay?.modelLabel === 'Sparad demomodell' ? 'SPARAD PPO-MODELL' : 'PPO · SENASTE VALIDERING';
    this.updateUi();
  }

  updateToggle() {
    this.toggle.innerHTML = `<svg><use href="#i-${this.playing ? 'pause' : 'play'}"/></svg>`;
    this.toggle.setAttribute('aria-label', this.playing ? 'Pausa uppspelning' : 'Spela upp');
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.width = rect.width; this.height = rect.height;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(rect.width * ratio);
    this.canvas.height = Math.round(rect.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.draw();
  }

  tick(time) {
    const delta = this.last === null ? 0 : Math.min((time - this.last) / 1000, .1);
    this.last = time;
    const visible = !document.hidden && this.canvas.getBoundingClientRect().width > 0;
    if (visible && this.replay && this.playing) {
      if (this.position >= this.replay.frames.length - 1) {
        this.endedFor += delta;
        if (this.endedFor > 1.6) { this.position = 0; this.endedFor = 0; }
      } else this.position = Math.min(this.replay.frames.length - 1, this.position + delta * this.replay.fps * this.speed);
    }
    if (visible) {
      this.draw();
      if (time - this.lastUi > 100) { this.updateUi(); this.lastUi = time; }
    }
    requestAnimationFrame(next => this.tick(next));
  }

  updateUi() {
    const replay = this.replay;
    if (!replay) return;
    const frame = replay.frames[Math.min(Math.floor(this.position), replay.frames.length - 1)];
    document.querySelector('#replay-time').textContent = `${timecode(this.position / 60)} / ${timecode((replay.frames.length - 1) / 60)}`;
    this.seek.value = Math.floor(this.position);
    document.querySelector('#replay-progress').textContent = Math.min(100, Math.floor(frame[0] / replay.length * 100));
    document.querySelector('#action-key').classList.toggle('pressed', frame[2] === 1);
    document.querySelector('#action-label').textContent = frame[2] ? 'Håll hopp' : 'Släpp';
  }

  draw() {
    const c = this.ctx, w = this.width, h = this.height;
    if (!w || !h) return;
    const bg = c.createLinearGradient(0, 0, 0, h);
    bg.addColorStop(0, '#101b17'); bg.addColorStop(1, '#1d3020');
    c.fillStyle = bg; c.fillRect(0, 0, w, h);
    const ground = h * .79, scale = w / (w < 450 ? 12.5 : 18), px = w * .2;
    const p = this.replay;
    const index = p ? Math.floor(this.position) : 0;
    const a = p?.frames[index] || [0, 0, 0, 0], b = p?.frames[Math.min(index + 1, p.frames.length - 1)] || a;
    const fraction = this.position - index, x = a[0] + (b[0] - a[0]) * fraction, y = a[1] + (b[1] - a[1]) * fraction;
    c.strokeStyle = '#78977b10'; c.lineWidth = 1;
    for (let gx = -(x * scale * .3) % 40; gx < w; gx += 40) { c.beginPath(); c.moveTo(gx, 0); c.lineTo(gx, ground); c.stroke(); }
    for (let gy = ground % 40; gy < ground; gy += 40) { c.beginPath(); c.moveTo(0, gy); c.lineTo(w, gy); c.stroke(); }
    // Decorative skyline; the agent and hazards below use recorded simulator coordinates.
    c.fillStyle = '#48604412';
    for (let i = -1; i < 8; i++) {
      const left = i * w / 5 - (x * scale * .1) % (w / 5);
      c.beginPath(); c.moveTo(left, ground); c.lineTo(left + w * .08, ground - h * .27);
      c.lineTo(left + w * .18, ground); c.fill();
    }
    c.fillStyle = '#213624'; c.fillRect(0, ground, w, h - ground);
    c.fillStyle = '#a4d88b'; c.fillRect(0, ground, w, 1.5);
    c.strokeStyle = '#4e70403b';
    for (let gx = -(x * scale) % (scale * 2); gx < w; gx += scale * 2) {
      c.beginPath(); c.moveTo(gx, ground + 1); c.lineTo(gx - 13, h); c.stroke();
    }
    if (!p) return;
    for (const o of p.obstacles) for (let i = 0; i < o.count; i++) {
      const left = px + (o.x + i * .7 - x) * scale;
      if (left < -scale || left > w + scale) continue;
      c.beginPath(); c.moveTo(left, ground); c.lineTo(left + .35 * scale, ground - o.height * scale); c.lineTo(left + .7 * scale, ground); c.closePath();
      c.fillStyle = '#344b30'; c.fill(); c.strokeStyle = '#aacd86'; c.lineWidth = 1.5; c.stroke();
      c.beginPath(); c.moveTo(left + .12 * scale, ground - .08 * scale); c.lineTo(left + .35 * scale, ground - o.height * scale + 8); c.lineTo(left + .58 * scale, ground - .08 * scale); c.strokeStyle = '#708e543a'; c.stroke();
    }
    const finish = px + (p.length - x) * scale;
    if (finish > 0 && finish < w) {
      c.fillStyle = '#b4ee8955'; c.fillRect(finish, ground - scale * 2.5, 2, scale * 2.5);
      c.font = '9px system-ui'; c.fillStyle = '#b4ee89'; c.fillText('MÅL', finish + 7, ground - scale * 2.3);
    }
    for (let tail = 1; tail <= 7; tail++) {
      const previous = p.frames[Math.max(0, index - tail * 2)];
      c.fillStyle = `rgba(168,225,124,${.13 * (1 - tail / 8)})`;
      c.fillRect(px + (previous[0] - x) * scale, ground - (previous[1] + p.playerSize) * scale + 6, p.playerSize * scale - 10, p.playerSize * scale - 12);
    }
    const size = p.playerSize * scale, top = ground - (y + p.playerSize) * scale;
    c.shadowColor = '#b3ed8940'; c.shadowBlur = 15;
    c.fillStyle = p.result.dead && index === p.frames.length - 1 ? '#edab89' : '#b3ed89';
    c.beginPath(); c.roundRect(px, top, size, size, 3); c.fill(); c.shadowBlur = 0;
    c.strokeStyle = '#274426'; c.lineWidth = 2; c.strokeRect(px + size * .16, top + size * .16, size * .68, size * .68);
    c.fillStyle = '#274426'; c.fillRect(px + size * .3, top + size * .33, size * .09, size * .19); c.fillRect(px + size * .62, top + size * .33, size * .09, size * .19);
    if (index === p.frames.length - 1) {
      c.fillStyle = '#101b17c9'; c.fillRect(w * .31, h * .32, w * .46, h * .24);
      c.textAlign = 'center'; c.font = `500 ${w < 450 ? 15 : 23}px "Space Grotesk", sans-serif`;
      c.fillStyle = p.result.success ? '#b3ed89' : '#edb889';
      c.fillText(p.result.success ? 'Banan klarad.' : p.result.dead ? 'Nästa försök.' : 'Tiden är slut.', w * .54, h * .47);
      c.textAlign = 'left';
    }
  }
}
