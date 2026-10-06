/* webfx.js: Visual motion effects.
   1. capture web - a glowing particle web spins outward while a file is being indexed.
   2. citation thread - a gold thread draws from a clicked page chip to the source panel. */

import { $, reducedMotion } from "./core.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

class WebFx {
  constructor() {
    this.canvas = $("#webfx");
    this.ctx = this.canvas ? this.canvas.getContext("2d") : null;
    this.layer = $("#threadLayer");
    this.web = null;
    this.raf = 0;
    if (this.canvas) {
      this.#resize();
      window.addEventListener("resize", () => this.#resize());
    }
  }

  #resize() {
    if (!this.canvas) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = window.innerWidth * ratio;
    this.canvas.height = window.innerHeight * ratio;
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  /** Begin a web centred on an element. Call progress() as indexing advances. */
  start(anchor) {
    if (reducedMotion() || !anchor) return null;
    const rect = anchor.getBoundingClientRect();
    const web = {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      p: 0.04,
      phase: "active",
      born: performance.now(),
      done: 0,
      ok: true,
    };
    this.web = web;
    this.#loop();
    return web;
  }

  progress(web, value) {
    if (web && web.phase === "active") web.p = Math.max(web.p, Math.min(value, 1));
  }

  finish(web, ok = true) {
    if (!web) return;
    web.phase = "burst";
    web.ok = ok;
    web.done = performance.now();
  }

  #loop() {
    if (this.raf || !this.ctx) return;
    const tick = (now) => {
      this.raf = 0;
      const { ctx, web } = this;
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      if (!web) return;
      if (web.phase === "burst" && now - web.done > 700) {
        this.web = null;
        return;
      }
      this.#draw(web, now);
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  #draw(web, now) {
    const { ctx } = this;
    const t = Math.max(0, now - web.born) / 1000;
    const burst = web.phase === "burst" ? Math.min((now - web.done) / 700, 1) : 0;
    const color = web.ok ? css("--thread") : css("--rose");
    const accent = css("--violet");
    const spokes = 14;
    const rings = 5;
    const reach = 110 * (1 + burst * 1.5);
    const fade = 1 - burst;
    const grow = Math.min(1, web.p * 1.25 + 0.12);

    ctx.save();
    ctx.translate(web.x, web.y);
    ctx.lineWidth = 1.2;
    ctx.lineCap = "round";

    const point = (spoke, radius) => {
      const angle = (Math.PI * 2 * spoke) / spokes + Math.sin(t * 1.2 + spoke) * 0.03;
      const wobble = Math.sin(t * 2.5 + spoke * 1.8 + radius * 0.06) * 2.0;
      return [Math.cos(angle) * (radius + wobble), Math.sin(angle) * (radius + wobble)];
    };

    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.6 * fade;
    for (let s = 0; s < spokes; s++) {
      const [x, y] = point(s, reach * grow);
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(x, y);
      ctx.stroke();
    }

    ctx.strokeStyle = accent;
    for (let r = 1; r <= rings; r++) {
      const radius = (reach * r) / rings;
      const visible = Math.min(1, Math.max(0, web.p * (rings + 1) - (r - 1)));
      if (visible <= 0 || radius > reach * grow) continue;
      ctx.globalAlpha = 0.55 * visible * fade;
      ctx.beginPath();
      for (let s = 0; s <= spokes; s++) {
        const [x, y] = point(s % spokes, radius);
        if (s === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      ctx.fillStyle = color;
      ctx.globalAlpha = 0.95 * visible * fade;
      for (let s = 0; s < spokes; s++) {
        const [x, y] = point(s, radius);
        ctx.beginPath();
        ctx.arc(x, y, 2.2 + Math.sin(t * 3.5 + s + r) * 0.6, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Concentric pulse wave
    const pulse = Math.max(0, (t * 0.8) % 1);
    ctx.globalAlpha = (1 - pulse) * 0.4 * fade;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(0, 0, reach * grow * pulse, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  /** Draw a gold thread from one element to another, then let it fade. */
  thread(from, to) {
    if (reducedMotion() || !from || !to || !this.layer) return;
    const a = from.getBoundingClientRect();
    const b = to.getBoundingClientRect();
    const x1 = a.left + a.width / 2;
    const y1 = a.top + a.height / 2;
    const x2 = b.left + Math.min(40, b.width / 2);
    const y2 = b.top + b.height / 2;
    const lift = Math.max(70, Math.abs(x2 - x1) * 0.28);

    const NS = "http://www.w3.org/2000/svg";
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", `M ${x1} ${y1} C ${x1 + (x2 - x1) * 0.3} ${y1 - lift}, ${x1 + (x2 - x1) * 0.7} ${y2 - lift}, ${x2} ${y2}`);
    path.setAttribute("stroke", css("--thread"));
    path.setAttribute("stroke-width", "2");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke-linecap", "round");

    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", x2);
    dot.setAttribute("cy", y2);
    dot.setAttribute("r", 5);
    dot.setAttribute("fill", css("--thread"));
    dot.style.opacity = "0";
    dot.style.transformBox = "fill-box";
    dot.style.transformOrigin = "center";
    this.layer.append(path, dot);

    const length = path.getTotalLength();
    path.style.strokeDasharray = String(length);
    const draw = path.animate([{ strokeDashoffset: length }, { strokeDashoffset: 0 }], {
      duration: 540,
      easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      fill: "forwards",
    });

    draw.onfinish = () => {
      dot.animate([{ opacity: 1, transform: "scale(1)" }, { opacity: 0, transform: "scale(3.5)" }], {
        duration: 600,
        easing: "ease-out",
        fill: "forwards",
      }).onfinish = () => dot.remove();
      
      path.animate([{ opacity: 1 }, { opacity: 0 }], {
        duration: 700,
        delay: 120,
        fill: "forwards",
      }).onfinish = () => path.remove();
    };
  }
}

export const webfx = new WebFx();
