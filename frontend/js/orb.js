/* orb.js: A next-gen 3D WebGL Holographic AI Core (Three.js r128).
   Layers:
   1. Fibonacci Outer Shell - High-density particle mesh with dynamic vertex displacement shader.
   2. Inner Geodesic Core - Volumetric pulsing wireframe core that turns fast when thinking.
   3. Cosmic Starfield - Floating ambient data nodes in 3D space.
   4. Thread Web - Additive line segments connecting particle clusters.
   Modes: idle (gentle wave & float), thinking (high velocity churning & pulse), ingesting (suction spin).
   Degrades gracefully to a CSS glowing orb if WebGL is unavailable. */

import { bus, reducedMotion } from "./core.js";

const MODES = { idle: 0.0, thinking: 1.0, ingesting: 0.65 };

const DISPLACE_SHADER = `
  vec3 displace(vec3 p, float t, float e) {
    float n1 = sin(p.x * 3.5 + t * 1.2) * cos(p.y * 2.8 - t * 0.9) * sin(p.z * 3.1 + t * 1.1);
    float n2 = sin(p.y * 6.0 - t * 2.1) * cos(p.z * 5.0 + t * 1.8);
    float wave = (n1 * 0.7 + n2 * 0.3) * (0.06 + 0.22 * e);
    return p + normalize(p) * wave;
  }
`;

const POINT_VERT = `
  uniform float uTime; 
  uniform float uEnergy; 
  uniform float uSize;
  attribute float aSeed;
  attribute float aScale;
  varying float vMix;
  varying float vAlpha;
  ${DISPLACE_SHADER}

  void main() {
    vec3 p = displace(position, uTime, uEnergy);
    float wave = sin(position.y * 5.0 + uTime * (1.0 + uEnergy * 2.0) + aSeed * 6.2831);
    vMix = clamp(0.5 + 0.5 * wave, 0.0, 1.0);
    vAlpha = clamp(0.4 + 0.6 * sin(aSeed * 12.0 + uTime * 1.5), 0.3, 1.0);
    
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    float distScale = 3.6 / -mv.z;
    gl_PointSize = uSize * aScale * (0.8 + aSeed * 0.8) * (1.0 + uEnergy * 0.5) * distScale;
    gl_Position = projectionMatrix * mv;
  }
`;

const POINT_FRAG = `
  uniform vec3 uA; 
  uniform vec3 uB; 
  uniform float uAlpha;
  varying float vMix;
  varying float vAlpha;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float soft = smoothstep(0.5, 0.02, d);
    vec3 col = mix(uA, uB, vMix);
    // Add inner white core glow
    col += vec3(smoothstep(0.2, 0.0, d) * 0.35);
    gl_FragColor = vec4(col, soft * uAlpha * vAlpha);
  }
`;

const INNER_VERT = `
  uniform float uTime;
  uniform float uEnergy;
  varying vec3 vNormal;
  void main() {
    vNormal = normal;
    float pulse = sin(uTime * 2.5) * 0.05 * (1.0 + uEnergy);
    vec3 p = position * (0.58 + pulse);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`;

const INNER_FRAG = `
  uniform vec3 uColor;
  uniform float uAlpha;
  uniform float uEnergy;
  varying vec3 vNormal;
  void main() {
    float intensity = pow(0.7 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.0);
    vec3 col = uColor + vec3(0.2 * uEnergy);
    gl_FragColor = vec4(col, (intensity * 0.65 + 0.15) * uAlpha);
  }
`;

const LINE_VERT = `
  uniform float uTime; 
  uniform float uEnergy;
  ${DISPLACE_SHADER}
  void main() {
    vec4 mv = modelViewMatrix * vec4(displace(position, uTime, uEnergy), 1.0);
    gl_Position = projectionMatrix * mv;
  }
`;

const LINE_FRAG = `
  uniform vec3 uColor; 
  uniform float uAlpha;
  void main() { 
    gl_FragColor = vec4(uColor, uAlpha); 
  }
`;

function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#ffffff";
}

export class Orb {
  /** @param {HTMLElement} host - Container element or canvas */
  constructor(host, { points = 3200, threads = true, mini = false } = {}) {
    this.mini = mini;
    this.mode = "idle";
    this.energy = 0;
    this.running = false;
    this.visible = true;
    this.pointer = { x: 0, y: 0, targetX: 0, targetY: 0 };
    this.time = 0;

    this.canvas = host instanceof HTMLCanvasElement ? host : document.createElement("canvas");
    if (host !== this.canvas) host.append(this.canvas);

    if (!window.THREE || !this.#initGL(points, threads)) {
      this.#fallback(host);
      return;
    }

    this.refreshColors();
    this.#observe();
    bus.on("theme:changed", () => this.refreshColors());
    
    if (reducedMotion()) this.#renderFrame(0);
    else this.start();
  }

  #initGL(pointCount, withThreads) {
    const THREE = window.THREE;
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        alpha: true,
        antialias: !this.mini,
        powerPreference: "high-performance",
      });
    } catch {
      return false;
    }

    this.renderer.setClearColor(0x000000, 0);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 50);
    this.camera.position.z = 3.4;

    // Main 3D group
    this.group = new THREE.Group();
    this.scene.add(this.group);

    // 1. FIBONACCI SPHERE PARTICLES
    const actualPoints = this.mini ? Math.floor(pointCount * 0.4) : pointCount;
    const positions = new Float32Array(actualPoints * 3);
    const seeds = new Float32Array(actualPoints);
    const scales = new Float32Array(actualPoints);

    const goldenRatio = (1 + Math.sqrt(5)) / 2;
    for (let i = 0; i < actualPoints; i++) {
      const theta = 2 * Math.PI * i / goldenRatio;
      const phi = Math.acos(1 - 2 * (i + 0.5) / actualPoints);
      const r = 1.0;

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);

      seeds[i] = Math.random();
      scales[i] = 0.7 + Math.random() * 0.9;
    }

    const pointGeometry = new THREE.BufferGeometry();
    pointGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    pointGeometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
    pointGeometry.setAttribute("aScale", new THREE.BufferAttribute(scales, 1));

    this.pointUniforms = {
      uTime: { value: 0 },
      uEnergy: { value: 0 },
      uSize: { value: 2.8 },
      uA: { value: new THREE.Color("#9b87ff") },
      uB: { value: new THREE.Color("#f2c46d") },
      uAlpha: { value: 0.95 },
    };

    this.pointMaterial = new THREE.ShaderMaterial({
      uniforms: this.pointUniforms,
      vertexShader: POINT_VERT,
      fragmentShader: POINT_FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.pointsMesh = new THREE.Points(pointGeometry, this.pointMaterial);
    this.group.add(this.pointsMesh);

    // 2. INNER GEODESIC CORE
    if (!this.mini) {
      const innerGeo = new THREE.IcosahedronGeometry(0.55, 2);
      this.innerUniforms = {
        uTime: this.pointUniforms.uTime,
        uEnergy: this.pointUniforms.uEnergy,
        uColor: { value: new THREE.Color("#9b87ff") },
        uAlpha: { value: 0.4 },
      };
      this.innerMaterial = new THREE.ShaderMaterial({
        uniforms: this.innerUniforms,
        vertexShader: INNER_VERT,
        fragmentShader: INNER_FRAG,
        wireframe: true,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      this.innerCore = new THREE.Mesh(innerGeo, this.innerMaterial);
      this.group.add(this.innerCore);

      // 3. COSMIC STARFIELD BACKGROUND PARTICLES
      const starCount = 450;
      const starPositions = new Float32Array(starCount * 3);
      for (let i = 0; i < starCount; i++) {
        const u = Math.random();
        const v = Math.random();
        const theta = u * 2.0 * Math.PI;
        const phi = Math.acos(2.0 * v - 1.0);
        const r = 1.6 + Math.random() * 2.2;
        starPositions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        starPositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
        starPositions[i * 3 + 2] = r * Math.cos(phi);
      }
      const starGeo = new THREE.BufferGeometry();
      starGeo.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
      this.starMaterial = new THREE.PointsMaterial({
        size: 1.8,
        color: new THREE.Color("#f2c46d"),
        transparent: true,
        opacity: 0.35,
        blending: THREE.AdditiveBlending,
      });
      this.starMesh = new THREE.Points(starGeo, this.starMaterial);
      this.group.add(this.starMesh);
    }

    // 4. CONNECTIVE THREAD WEB
    if (withThreads) {
      const sample = this.mini ? 70 : 180;
      const step = Math.floor(actualPoints / sample);
      const nodes = [];
      for (let i = 0; i < sample; i++) {
        const idx = i * step * 3;
        nodes.push(positions.slice(idx, idx + 3));
      }

      const segments = [];
      nodes.forEach((a, i) => {
        const nearest = nodes
          .map((b, j) => ({ j, d: i === j ? Infinity : (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2 }))
          .sort((m, n) => m.d - n.d)
          .slice(0, 2);
        nearest.forEach(({ j }) => segments.push(...a, ...nodes[j]));
      });

      const lineGeometry = new THREE.BufferGeometry();
      lineGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(segments), 3));
      
      this.lineUniforms = {
        uTime: this.pointUniforms.uTime,
        uEnergy: this.pointUniforms.uEnergy,
        uColor: { value: new THREE.Color("#f2c46d") },
        uAlpha: { value: 0.18 },
      };

      this.lineMaterial = new THREE.ShaderMaterial({
        uniforms: this.lineUniforms,
        vertexShader: LINE_VERT,
        fragmentShader: LINE_FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      this.linesMesh = new THREE.LineSegments(lineGeometry, this.lineMaterial);
      this.group.add(this.linesMesh);
    }

    // Pointer Interaction
    if (!this.mini) {
      window.addEventListener("pointermove", (e) => {
        this.pointer.targetX = (e.clientX / window.innerWidth - 0.5) * 1.5;
        this.pointer.targetY = (e.clientY / window.innerHeight - 0.5) * 1.5;
      }, { passive: true });
    }

    this.resizeObserver = new ResizeObserver(() => this.#resize());
    this.resizeObserver.observe(this.canvas);
    this.#resize();

    return true;
  }

  #resize() {
    const width = this.canvas.clientWidth || 300;
    const height = this.canvas.clientHeight || 300;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);

    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();

    this.pointUniforms.uSize.value = ratio * (this.mini ? 2.4 : 2.8 * Math.max(0.75, height / 320));
    if (!this.running) this.#renderFrame(0);
  }

  #observe() {
    new IntersectionObserver(([entry]) => {
      this.visible = entry.isIntersecting;
      this.#syncLoop();
    }).observe(this.canvas);
    document.addEventListener("visibilitychange", () => this.#syncLoop());
  }

  #syncLoop() {
    const shouldRun = this.wantsRun && this.visible && !document.hidden;
    if (shouldRun && !this.running) this.#loop();
    this.running = shouldRun;
  }

  #loop() {
    this.running = true;
    let last = performance.now();
    const tick = (now) => {
      if (!this.running) return;
      this.#renderFrame(Math.min((now - last) / 1000, 0.05));
      last = now;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  #renderFrame(dt) {
    this.energy += (MODES[this.mode] - this.energy) * Math.min(1, dt * 4.5 + 0.002);
    this.time += dt;

    this.pointUniforms.uEnergy.value = this.energy;
    this.pointUniforms.uTime.value = this.time;

    // Smooth physics rotation
    const rotSpeed = 0.18 + this.energy * 0.75;
    this.group.rotation.y += dt * rotSpeed;

    if (this.innerCore) {
      this.innerCore.rotation.y -= dt * (rotSpeed * 1.4);
      this.innerCore.rotation.z += dt * (rotSpeed * 0.8);
    }

    if (this.starMesh) {
      this.starMesh.rotation.y += dt * 0.03;
    }

    // Pointer lerp parallax
    this.pointer.x += (this.pointer.targetX - this.pointer.x) * 0.06;
    this.pointer.y += (this.pointer.targetY - this.pointer.y) * 0.06;

    this.group.rotation.x = this.pointer.y * 0.35;
    this.group.rotation.z = -this.pointer.x * 0.15;

    this.renderer.render(this.scene, this.camera);
  }

  refreshColors() {
    if (!this.pointMaterial) return;
    const THREE = window.THREE;
    const light = document.documentElement.dataset.theme === "light";

    const colViolet = new THREE.Color(cssColor("--violet"));
    const colThread = new THREE.Color(cssColor("--thread"));

    this.pointUniforms.uA.value = colViolet;
    this.pointUniforms.uB.value = colThread;
    this.pointMaterial.blending = light ? THREE.NormalBlending : THREE.AdditiveBlending;
    this.pointUniforms.uAlpha.value = light ? 0.9 : 0.95;

    if (this.innerMaterial) {
      this.innerUniforms.uColor.value = colViolet;
      this.innerMaterial.blending = light ? THREE.NormalBlending : THREE.AdditiveBlending;
    }

    if (this.lineMaterial) {
      this.lineUniforms.uColor.value = colThread;
      this.lineMaterial.blending = light ? THREE.NormalBlending : THREE.AdditiveBlending;
      this.lineUniforms.uAlpha.value = light ? 0.28 : 0.18;
    }

    if (this.starMaterial) {
      this.starMaterial.color = colThread;
    }

    this.pointMaterial.needsUpdate = true;
    if (!this.running) this.#renderFrame(0);
  }

  start() {
    this.wantsRun = true;
    this.#syncLoop();
  }

  stop() {
    this.wantsRun = false;
    this.running = false;
  }

  setMode(mode) {
    if (!(mode in MODES) || mode === this.mode) return;
    this.mode = mode;
    if (reducedMotion() && this.renderer) {
      this.energy = MODES[mode] * 0.5;
      this.#renderFrame(0);
    }
  }

  #fallback(host) {
    if (this.mini) {
      const ctx = this.canvas.getContext?.("2d");
      if (ctx) {
        const g = ctx.createRadialGradient(20, 18, 2, 28, 28, 26);
        g.addColorStop(0, cssColor("--thread"));
        g.addColorStop(1, cssColor("--violet"));
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(28, 28, 22, 0, Math.PI * 2);
        ctx.fill();
      }
      return;
    }
    this.canvas.remove();
    const node = document.createElement("div");
    node.className = "orb-fallback";
    host.append(node);
  }
}
