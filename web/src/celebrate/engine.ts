/** One fixed canvas for streamers, sparks and the sunrise (sorting redesign, Performance 2). It is made at the first
 *  burst and removed as soon as nothing is left to draw. It runs on requestAnimationFrame alone and stops at once when
 *  the tab is hidden. Particles are capped: 40, or 20 on a device with 4 cores or fewer, a coarse pointer or a screen
 *  under 600 px. */
export type Shape = 'ribbon' | 'leaf' | 'flake' | 'spark';
export type Particle = {
  x: number; y: number; vx: number; vy: number;   // px and px/s
  g: number;                                       // gravity, px/s²
  drag: number;                                    // the share of velocity kept per second
  rot: number; vr: number;                         // rad and rad/s
  size: number; color: string; shape: Shape;
  age: number;                                     // s; below 0 until it starts (a burst scheduled for later)
  life: number;                                    // s
};
export type Drawer = { age: number; life: number; draw: (ctx: CanvasRenderingContext2D, t: number) => void };

export function particleCap(env: { cores?: number; coarse: boolean; narrow: boolean }): 20 | 40 {
  return (env.cores !== undefined && env.cores <= 4) || env.coarse || env.narrow ? 20 : 40;
}

function deviceCap(): number {
  const mq = (q: string) => typeof window.matchMedia === 'function' && window.matchMedia(q).matches;
  return particleCap({ cores: navigator.hardwareConcurrency, coarse: mq('(pointer: coarse)'), narrow: window.innerWidth < 600 });
}

/** Moves a particle on by dt seconds; false once its life is over. */
export function step(p: Particle, dt: number): boolean {
  p.age += dt;
  if (p.age < 0) return true;
  if (p.age >= p.life) return false;
  const keep = Math.pow(p.drag, dt);
  p.vx *= keep;
  p.vy = p.vy * keep + p.g * dt;
  p.x += p.vx * dt;
  p.y += p.vy * dt;
  p.rot += p.vr * dt;
  return true;
}

function paint(ctx: CanvasRenderingContext2D, p: Particle): void {
  if (p.age < 0) return;
  ctx.globalAlpha = 1 - Math.max(0, (p.age / p.life - 0.6) / 0.4);      // the last 40% of its life fades out
  ctx.fillStyle = p.color;
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.rotate(p.rot);
  if (p.shape === 'ribbon') {
    ctx.scale(1, Math.cos(p.rot * 2));                                   // a strip that flutters as it turns
    ctx.fillRect(-p.size / 2, -p.size, p.size, p.size * 2);
  } else {
    ctx.beginPath();
    if (p.shape === 'leaf') ctx.ellipse(0, 0, p.size, p.size / 2, 0, 0, Math.PI * 2);
    else ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
  ctx.globalAlpha = 1;
}

export class Engine {
  canvas: HTMLCanvasElement | null = null;
  particles: Particle[] = [];
  drawers: Drawer[] = [];
  private raf = 0;
  private last = 0;
  readonly capacity: () => number;

  constructor(capacity: () => number = deviceCap) {
    this.capacity = capacity;
  }

  add(ps: Particle[]): void {
    if (document.hidden) return;
    this.particles.push(...ps);
    const over = this.particles.length - this.capacity();
    if (over > 0) this.particles.splice(0, over);   // the oldest go first
    this.start();
  }

  addDrawer(d: Drawer): void {
    if (document.hidden) return;
    this.drawers.push(d);
    this.start();
  }

  private start(): void {
    if (!this.canvas) {
      const c = document.createElement('canvas');
      c.className = 'cel-canvas';
      c.setAttribute('aria-hidden', 'true');
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      c.width = Math.round(window.innerWidth * dpr);
      c.height = Math.round(window.innerHeight * dpr);
      document.body.appendChild(c);
      c.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.canvas = c;
    }
    if (!this.raf) {
      this.last = 0;
      this.raf = requestAnimationFrame(this.frame);
    }
  }

  private readonly frame = (now: number): void => {
    this.raf = 0;
    if (document.hidden) { this.stop(); return; }
    const dt = this.last ? Math.min((now - this.last) / 1000, 0.05) : 1 / 60;
    this.last = now;
    const ctx = this.canvas?.getContext('2d') ?? null;
    ctx?.clearRect(0, 0, window.innerWidth, window.innerHeight);
    this.drawers = this.drawers.filter((d) => {
      d.age += dt;
      if (d.age >= d.life) return false;
      if (ctx) d.draw(ctx, d.age / d.life);
      return true;
    });
    this.particles = this.particles.filter((p) => {
      if (!step(p, dt)) return false;
      if (ctx) paint(ctx, p);
      return true;
    });
    if (this.particles.length === 0 && this.drawers.length === 0) { this.stop(); return; }
    this.raf = requestAnimationFrame(this.frame);
  };

  stop(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.particles = [];
    this.drawers = [];
    this.canvas?.remove();
    this.canvas = null;
  }
}

export const engine = new Engine();
