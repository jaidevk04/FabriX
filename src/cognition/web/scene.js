import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

const EQUIPMENT = {
  cement: [
    [
      "kiln",
      "Rotary kiln",
      "The thermal surrogate follows kiln temperature. Shell rotation is illustrative; temperature and duty come from the twin.",
    ],
    [
      "burner",
      "Main burner",
      "Thermal duty is the controllable input. Orange glow reflects the current temperature deviation.",
    ],
    [
      "drive",
      "Kiln drive",
      "Motion stops when the twin actuator is stuck. Kiln speed is not an independent control in this model.",
    ],
    [
      "feed",
      "Raw-meal feed",
      "Illustrative feed hopper and chute. Material chemistry and throughput are not modelled.",
    ],
  ],
  steel: [
    [
      "furnace",
      "Reheating furnace",
      "The thermal surrogate follows furnace temperature. Walls can be hidden to inspect the hot zone.",
    ],
    [
      "burner",
      "Burner bank",
      "Thermal duty determines the simulated heating input, subject to gateway limits.",
    ],
    [
      "rollers",
      "Roller conveyor",
      "Rollers turn to carry billets forward at a speed set by the actuator position. Motion stops with an actuator-stuck fault. Illustrative only.",
    ],
    [
      "billets",
      "Steel billets",
      "Visual workpieces that ride the roller surface. Metallurgy, residence time and individual billet temperatures are not modelled.",
    ],
  ],
  chemical: [
    [
      "reactor",
      "Jacketed reactor",
      "The thermal surrogate follows bulk temperature. Cutaway reveals the illustrative vessel interior.",
    ],
    [
      "jacket",
      "Heating jacket",
      "Thermal duty controls heating input. Pressure and reaction kinetics are not modelled.",
    ],
    [
      "agitator",
      "Agitator drive",
      "Illustrative mixing motion stops with an actuator-stuck fault. Mixing is not independently simulated.",
    ],
    [
      "pipes",
      "Process piping",
      "Illustrative inlet and outlet connections. Flow and composition are not modelled.",
    ],
  ],
};
export class TwinScene {
  // `compact` renders a still-friendly hero for plant cards: no grid, labels, selection or pointer control.
  constructor(container, onInspect, options = {}) {
    this.container = container;
    this.onInspect = onInspect;
    this.compact = Boolean(options.compact);
    this.annotationHost = this.compact ? null : document.getElementById("equipment-annotations");
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.compact ? 2 : 1.7));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.3;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    container.append(this.renderer.domElement);
    this.renderer.domElement.setAttribute(
      "aria-label",
      "Interactive 3D industrial equipment. Use the camera buttons for keyboard access.",
    );
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.minDistance = 5;
    this.controls.maxDistance = 22;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.015;
    if (this.compact) {
      Object.assign(this.controls, { enabled: false, autoRotate: false, minDistance: 0.5, maxDistance: 400, enableDamping: false });
      Object.assign(this.renderer.domElement.style, { touchAction: "auto", pointerEvents: "none" });
    }
    this.scene.add(new THREE.HemisphereLight(0xc6e2ff, 0x152222, 2.2));
    const light = new THREE.DirectionalLight(0xffe3ca, 3.3);
    light.position.set(4, 8, 5);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    Object.assign(light.shadow.camera, {
      left: -8,
      right: 8,
      top: 8,
      bottom: -8,
      near: 0.5,
      far: 25,
    });
    light.shadow.bias = -0.001;
    light.shadow.normalBias = 0.035;
    this.scene.add(light);
    const rim = new THREE.DirectionalLight(0x70aaff, 2.1);
    rim.position.set(-5, 4, -4);
    this.scene.add(rim);
    this.floor = new THREE.Mesh(
      new THREE.BoxGeometry(10, 0.18, 7),
      new THREE.MeshStandardMaterial({
        color: 0x8395a4,
        metalness: 0.15,
        roughness: 0.7,
      }),
    );
    this.floor.position.y = -0.15;
    this.floor.receiveShadow = true;
    this.scene.add(this.floor);
    if (!this.compact) {
      const grid = new THREE.GridHelper(24, 48, 0x9cacba, 0xb9c7d2);
      grid.position.y = -0.25;
      this.scene.add(grid);
    } else {
      // Cards show the equipment floating on the backdrop with only its soft shadow underneath.
      this.floor.material.dispose();
      this.floor.material = new THREE.ShadowMaterial({ opacity: 0.22 });
    }
    this.ray = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();
    this.projected = new THREE.Vector3();
    this.labelsEnabled = true;
    this.annotations = [];
    this.pointerDown = null;
    this.renderer.domElement.addEventListener("pointerdown", (e) => {
      this.pointerDown = [e.clientX, e.clientY];
    });
    this.renderer.domElement.addEventListener("pointerup", (e) => {
      if (
        !this.pointerDown ||
        Math.hypot(
          e.clientX - this.pointerDown[0],
          e.clientY - this.pointerDown[1],
        ) > 5
      )
        return;
      const r = this.renderer.domElement.getBoundingClientRect();
      this.mouse.set(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        (-(e.clientY - r.top) / r.height) * 2 + 1,
      );
      this.ray.setFromCamera(this.mouse, this.camera);
      const hit = this.ray
        .intersectObjects(this.model.children, true)
        .find((h) => {
          let obj = h.object;
          while (obj) {
            if (!obj.visible) return false;
            obj = obj.parent;
          }
          return h.object.userData.equipment;
        });
      if (hit) this.select(hit.object.userData.equipment);
    });
    this.resize = new ResizeObserver(() => this.resizeView());
    this.resize.observe(container);
    this.dock = new MutationObserver(() => this.resizeView());
    this.dock.observe(container, { attributes: true, attributeFilter: ["data-narrator"] });
    this.motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.heatmap = true;
    this.cutaway = false;
    this.lastTime = 0;
    this.setCamera("iso");
    this.resizeView();
    this.renderer.setAnimationLoop((t) => this.frame(t));
    this.contextLost = (e) => {
      e.preventDefault();
      const note = document.getElementById("scene-error");
      if (note) note.textContent =
        "3D graphics context lost. Reload to restore the view; process controls remain available.";
    };
    this.renderer.domElement.addEventListener(
      "webglcontextlost",
      this.contextLost,
    );
  }
  resizeView() {
    // A docked overlay (live activity) reserves the right edge so the model stays fully visible.
    const reserved = parseFloat(getComputedStyle(this.container).getPropertyValue("--tn-w")) || 0;
    const w = this.container.clientWidth - reserved,
      h = this.container.clientHeight;
    if (w <= 0 || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    if (this.compact && this.model) {
      this.frameModel();
      if (!this.active) this.renderOnce();
    }
  }
  // Frames the whole model along the isometric direction so it fills the stage at any aspect ratio.
  frameModel() {
    const box = new THREE.Box3().setFromObject(this.model);
    const center = box.getCenter(new THREE.Vector3());
    const corners = [];
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
    const direction = new THREE.Vector3(9, 7, 10).normalize();
    const fits = (distance) => {
      this.camera.position.copy(center).addScaledVector(direction, distance);
      this.camera.lookAt(center);
      this.camera.updateMatrixWorld(true);
      return corners.every((c) => {
        const p = c.clone().project(this.camera);
        return Math.abs(p.x) < 0.9 && Math.abs(p.y) < 0.86;
      });
    };
    let low = 1;
    let high = 80;
    for (let i = 0; i < 18; i++) {
      const mid = (low + high) / 2;
      if (fits(mid)) high = mid;
      else low = mid;
    }
    fits(high);
    this.controls.target.copy(center);
    this.baseOffset = this.camera.position.clone().sub(center);
    this.controls.update();
  }
  // A slow sway of the camera keeps the framing valid at every angle (a full turn would not).
  sway() {
    if (!this.baseOffset) return;
    const angle = this.motion ? Math.sin((this.clock ?? 0) * 0.45) * 0.2 : 0;
    this.camera.position.copy(this.controls.target).add(this.baseOffset.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), angle));
    this.camera.lookAt(this.controls.target);
  }
  // Still frame for idle cards; the animation loop only runs while a plant is live or hovered.
  renderOnce() {
    this.sway();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
  setActive(active) {
    if (this.active === active) return;
    this.active = active;
    this.motion = active && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (active) this.renderer.setAnimationLoop((t) => this.frame(t));
    else {
      this.renderer.setAnimationLoop(null);
      this.renderOnce();
    }
  }
  material(color, extra = {}) {
    return new THREE.MeshStandardMaterial({
      color,
      metalness: 0.55,
      roughness: 0.4,
      ...extra,
    });
  }
  mesh(geometry, material, position = [0, 0, 0], parent = this.model) {
    const obj = new THREE.Mesh(geometry, material);
    obj.position.set(...position);
    obj.castShadow = true;
    obj.receiveShadow = true;
    parent.add(obj);
    return obj;
  }
  box(size, position, material, parent) {
    return this.mesh(
      new THREE.BoxGeometry(...size),
      material,
      position,
      parent,
    );
  }
  cylinder(radius, length, position, material, parent) {
    return this.mesh(
      new THREE.CylinderGeometry(radius, radius, length, 40),
      material,
      position,
      parent,
    );
  }
  // Four-blade fan or impeller; spins about its own vertical axis through the rotor list.
  fan(position, radius, material, parent, rate) {
    const hub = new THREE.Group();
    hub.position.set(...position);
    parent.add(hub);
    for (let i = 0; i < 4; i++) {
      const blade = this.box(
        [radius, 0.025, radius * 0.28],
        [0, 0, 0],
        material,
        hub,
      );
      blade.position.set(
        Math.cos((i * Math.PI) / 2) * radius * 0.5,
        0,
        Math.sin((i * Math.PI) / 2) * radius * 0.5,
      );
      blade.rotation.y = -(i * Math.PI) / 2;
      blade.rotation.z = 0.25;
    }
    this.cylinder(radius * 0.14, 0.06, [0, 0, 0], material, hub);
    this.rotors.push([hub, "y", rate]);
    return hub;
  }
  // Flame length follows the actuator position and flickers with scene time.
  flicker(cone, phase = 0) {
    this.animated.push((t) => {
      const load = THREE.MathUtils.clamp((this.state?.actuator ?? 50) / 50, 0.2, 2);
      cone.scale.y = load * (1 + 0.1 * Math.sin(t * 13 + phase) + 0.05 * Math.sin(t * 29 + phase));
      cone.scale.x = cone.scale.z = 0.85 + 0.15 * load;
    });
  }
  group(id) {
    const g = new THREE.Group();
    g.userData.equipment = id;
    this.model.add(g);
    return g;
  }
  tagGroups() {
    this.model.children.forEach((g) => {
      if (g.userData.equipment)
        g.traverse((o) => {
          o.userData.equipment = g.userData.equipment;
        });
    });
  }
  disposeModel() {
    if (!this.model) return;
    const materials = new Set();
    this.model.traverse((o) => {
      o.geometry?.dispose();
      if (o.material) materials.add(o.material);
    });
    materials.forEach((m) => m.dispose());
    this.scene.remove(this.model);
    this.annotationHost?.replaceChildren();
    this.annotations = [];
  }
  pipe(points, radius, material, parent = this.model) {
    const curve = new THREE.CatmullRomCurve3(
      points.map((p) => new THREE.Vector3(...p)),
      false,
      "centripetal",
    );
    return this.mesh(
      new THREE.TubeGeometry(curve, 32, radius, 8, false),
      material,
      [0, 0, 0],
      parent,
    );
  }
  rail(x, z, length, material, parent = this.model) {
    for (let dx = -length / 2; dx <= length / 2 + 0.01; dx += length / 4)
      this.cylinder(0.025, 0.85, [x + dx, 1.2, z], material, parent);
    for (const y of [1.25, 1.6])
      this.pipe(
        [
          [x - length / 2, y, z],
          [x + length / 2, y, z],
        ],
        0.025,
        material,
        parent,
      );
  }
  details(industry, metal, dark, light) {
    const safety = this.material(0xd6a84a, { metalness: 0.15, roughness: 0.6 });
    const blue = this.material(0x326887, { roughness: 0.55 });
    const base = this.group("infrastructure");
    // Service walkway, safety rails, steps and control cabinet are illustrative.
    this.box([8.2, 0.12, 0.8], [0, 0.74, 2.05], dark, base);
    this.rail(0, 2.45, 8.1, safety, base);
    for (const x of [-3.8, -1.8, 0.2, 2.2, 3.8])
      this.box([0.09, 0.75, 0.09], [x, 0.3, 2.05], metal, base);
    for (let i = 0; i < 5; i++)
      this.box(
        [0.65, 0.15, 0.28],
        [4.2, 0.08 + i * 0.15, 1.2 + i * 0.23],
        light,
        base,
      );
    this.box([0.75, 1.1, 0.45], [3.75, 0.6, -2.3], blue, base);
    this.box([0.4, 0.3, 0.025], [3.75, 0.85, -2.06], dark, base);
    for (const x of [3.58, 3.75, 3.92])
      this.mesh(
        new THREE.SphereGeometry(0.04, 8, 8),
        safety,
        [x, 0.54, -2.05],
        base,
      );
    this.pipe(
      [
        [-4, 0.2, -2.2],
        [-4, 1.0, -2.2],
        [-2.8, 1.05, -2.2],
        [2.5, 1.05, -2.2],
        [2.7, 0.3, -2.2],
      ],
      0.075,
      blue,
      base,
    );
    for (const x of [-2, 0, 2]) {
      const flange = this.cylinder(0.13, 0.07, [x, 1.05, -2.2], light, base);
      flange.rotation.z = Math.PI / 2;
      this.box([0.12, 1, 0.12], [x, 0.4, -2.2], dark, base);
    }
    if (industry === "cement") {
      const kiln = this.model.children.find(
        (g) => g.userData.equipment === "kiln",
      );
      for (let x = -2.5; x < 2.7; x += 0.5) {
        const ring = this.mesh(
          new THREE.TorusGeometry(0.76, 0.018, 6, 48),
          dark,
          [x, 0, 0],
          kiln,
        );
        ring.rotation.y = Math.PI / 2;
      }
      for (const x of [-1.7, 1.7])
        for (let i = 0; i < 12; i++) {
          const a = (i * Math.PI) / 6;
          this.mesh(
            new THREE.SphereGeometry(0.035, 6, 6),
            dark,
            [x, Math.cos(a) * 0.8, Math.sin(a) * 0.8],
            kiln,
          );
        }
      this.pipe(
        [
          [3.6, 0.3, -1.1],
          [3.6, 1.5, -1.1],
          [3.2, 1.5, 0],
        ],
        0.075,
        blue,
        this.model.children.find((g) => g.userData.equipment === "burner"),
      );
    } else if (industry === "steel") {
      const furnace = this.model.children.find(
        (g) => g.userData.equipment === "furnace",
      );
      for (const x of [-2.1, -1.05, 0, 1.05, 2.1])
        for (const z of [-1.4, 1.4])
          this.box([0.08, 1.7, 0.1], [x, 1.6, z], dark, furnace);
      const burners = this.model.children.find(
        (g) => g.userData.equipment === "burner",
      );
      this.pipe(
        [
          [-2.4, 0.2, -1.9],
          [-2.4, 1.6, -1.9],
          [2.4, 1.6, -1.9],
        ],
        0.1,
        blue,
        burners,
      );
      for (const x of [-1.5, 0, 1.5]) {
        const valve = this.mesh(
          new THREE.TorusGeometry(0.14, 0.025, 8, 16),
          safety,
          [x, 1.8, -1.9],
          burners,
        );
        valve.rotation.x = Math.PI / 2;
      }
    } else {
      const reactor = this.model.children.find(
        (g) => g.userData.equipment === "reactor",
      );
      for (const y of [0.58, 2.78]) {
        this.mesh(
          new THREE.TorusGeometry(1.07, 0.05, 8, 48),
          light,
          [0, y, 0],
          reactor,
        ).rotation.x = Math.PI / 2;
        for (let i = 0; i < 16; i++) {
          const a = (i * Math.PI) / 8;
          this.cylinder(
            0.035,
            0.12,
            [Math.cos(a) * 1.07, y, Math.sin(a) * 1.07],
            dark,
            reactor,
          );
        }
      }
      const pipes = this.model.children.find(
        (g) => g.userData.equipment === "pipes",
      );
      this.pipe(
        [
          [0, 2.9, 0],
          [0.2, 3.3, -0.5],
          [1.8, 3.3, -0.5],
          [1.8, 2.4, 0],
        ],
        0.075,
        blue,
        pipes,
      );
      for (const x of [-1.8, 1.8]) {
        this.mesh(
          new THREE.TorusGeometry(0.15, 0.025, 8, 20),
          safety,
          [x, 2, 0],
          pipes,
        );
        this.cylinder(0.16, 0.09, [x, 2.35, 0], light, pipes).rotation.x =
          Math.PI / 2;
      }
      const ladder = this.group("access");
      for (const z of [0.65, 1.15])
        this.cylinder(0.035, 3.1, [-1.25, 1.55, z], metal, ladder);
      for (let y = 0.2; y < 3.1; y += 0.25)
        this.pipe(
          [
            [-1.25, y, 0.65],
            [-1.25, y, 1.15],
          ],
          0.025,
          metal,
          ladder,
        );
    }
  }
  buildAnnotations() {
    const host = this.annotationHost;
    if (!host) return;
    this.model.updateMatrixWorld(true);
    this.annotations = EQUIPMENT[this.industry].map(([id, label]) => {
      const g = this.model.children.find((o) => o.userData.equipment === id);
      const bounds = new THREE.Box3().setFromObject(g),
        point = new THREE.Vector3();
      bounds.getCenter(point);
      point.y = bounds.max.y + 0.2;
      const e = document.createElement("span");
      e.className = "equipment-annotation";
      e.textContent = label;
      host.append(e);
      return { id, point, e };
    });
  }
  setLabels(value) {
    this.labelsEnabled = value;
    if (!value) this.annotations.forEach((a) => (a.e.hidden = true));
  }
  fitSelection() {
    const g =
      this.model.children.find((o) => o.userData.equipment === this.selected) ||
      this.model;
    const bounds = new THREE.Box3().setFromObject(g),
      center = bounds.getCenter(new THREE.Vector3()),
      size = bounds.getSize(new THREE.Vector3());
    const distance = Math.max(5, Math.max(size.x, size.y, size.z) * 1.8);
    const direction = this.camera.position
      .clone()
      .sub(this.controls.target)
      .normalize();
    this.controls.target.copy(center);
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.controls.update();
  }
  build(industry) {
    this.disposeModel();
    this.model = new THREE.Group();
    this.scene.add(this.model);
    this.industry = industry;
    this.rotors = [];
    this.animated = [];
    this.shells = [];
    this.hotMaterials = [];
    const metal = this.material(0x677f91),
      dark = this.material(0x273d4d),
      light = this.material(0xb2c5ce),
      green = this.material(0x426f8c);
    const hot = this.material(0xed8754, {
      emissive: 0xf87625,
      emissiveIntensity: 0.5,
    });
    this.hotMaterials.push(hot);
    if (industry === "cement") {
      const kiln = this.group("kiln");
      kiln.position.set(0, 1.55, 0);
      kiln.rotation.z = 0.04;
      const shell = this.cylinder(0.75, 5.6, [0, 0, 0], metal, kiln);
      shell.rotation.z = Math.PI / 2;
      this.shells.push(shell);
      this.rotors.push([shell, "x", 0.16]);
      for (const x of [-1.7, 1.7]) {
        const band = this.mesh(
          new THREE.TorusGeometry(0.77, 0.09, 12, 48),
          light,
          [x, 0, 0],
          kiln,
        );
        band.rotation.y = Math.PI / 2;
        for (const z of [-0.55, 0.55]) {
          const support = this.cylinder(0.22, 0.5, [x, -0.82, z], dark, kiln);
          support.rotation.z = Math.PI / 2;
          this.box([0.7, 0.62, 0.45], [x, 0.3, z], dark, this.model);
        }
      }
      const inner = this.cylinder(0.66, 5.55, [0, 0, 0], hot, kiln);
      inner.rotation.z = Math.PI / 2;
      // Ribs orbit the kiln axis on a pivot that turns with the shell.
      const ribs = new THREE.Group();
      kiln.add(ribs);
      this.rotors.push([ribs, "x", 0.16]);
      for (let i = 0; i < 8; i++) {
        const rib = this.box([5.4, 0.035, 0.04], [0, 0.755, 0], dark, ribs);
        rib.rotation.x = (i * Math.PI) / 4;
        rib.position.set(
          0,
          Math.cos((i * Math.PI) / 4) * 0.755,
          Math.sin((i * Math.PI) / 4) * 0.755,
        );
      }
      const burner = this.group("burner");
      const nozzle = this.cylinder(0.22, 1.1, [3, 1.45, 0], green, burner);
      nozzle.rotation.z = Math.PI / 2;
      const flame = this.mesh(
        new THREE.ConeGeometry(0.33, 0.9, 24),
        hot,
        [2.5, 1.5, 0],
        burner,
      );
      flame.rotation.z = Math.PI / 2;
      this.flicker(flame);
      this.box([1.2, 0.17, 1.1], [3.3, 0.55, 0], dark, burner);
      const drive = this.group("drive");
      this.box([0.9, 0.55, 0.65], [-1.8, 0.65, 1.15], green, drive);
      const wheel = this.mesh(
        new THREE.TorusGeometry(0.35, 0.1, 12, 32),
        light,
        [-1.8, 1, 1.05],
        drive,
      );
      this.rotors.push([wheel, "z", 0.6]);
      const feed = this.group("feed");
      this.mesh(
        new THREE.CylinderGeometry(0.6, 0.18, 1, 4),
        light,
        [-3.3, 2.6, 0],
        feed,
      );
      this.box([0.45, 1.3, 0.45], [-3.3, 1.5, 0], dark, feed);
      for (const z of [-0.6, 0.6])
        this.box([0.12, 2.8, 0.12], [-3.5, 1.4, z], metal, feed);
      const chimney = this.cylinder(0.28, 2.9, [-3, 1.45, -1.8], metal, feed);
      this.mesh(
        new THREE.TorusGeometry(0.31, 0.05, 8, 32),
        light,
        [-3, 2.95, -1.8],
        feed,
      ).rotation.x = Math.PI / 2;
      chimney.userData.illustrative = true;
      this.fan([-3, 2.98, -1.8], 0.5, light, feed, 6);
    } else if (industry === "steel") {
      const furnace = this.group("furnace");
      this.box([4.7, 0.3, 2.8], [0, 0.7, 0], dark, furnace);
      for (const z of [-1.3, 1.3])
        this.shells.push(
          this.box([4.7, 1.55, 0.16], [0, 1.6, z], metal, furnace),
        );
      this.shells.push(this.box([4.8, 0.22, 2.9], [0, 2.4, 0], light, furnace));
      this.box([4.5, 0.07, 2.35], [0, 0.9, 0], hot, furnace);
      for (const x of [-1.7, 1.7])
        for (const z of [-0.9, 0.9])
          this.box([0.18, 0.6, 0.18], [x, 0.3, z], dark, furnace);
      const rollers = this.group("rollers");
      const ROLLER_RADIUS = 0.12,
        ROLLER_SPEED = 3; // rad/s at nominal actuator (50 %)
      for (let i = 0; i < 17; i++) {
        // Geometry is laid along Z, so the mesh itself spins about its own axis.
        const geometry = new THREE.CylinderGeometry(ROLLER_RADIUS, ROLLER_RADIUS, 2.1, 32);
        geometry.rotateX(Math.PI / 2);
        const r = this.mesh(geometry, light, [-3.84 + i * 0.48, 1.1, 0], rollers);
        // A dark key stripe makes the rotation visible.
        this.box([0.035, 0.035, 1.9], [ROLLER_RADIUS, 0, 0], dark, r);
        // Negative spin about +Z moves the roller's top surface toward +X, the feed direction.
        this.rotors.push([r, "z", -ROLLER_SPEED]);
      }
      for (const z of [-1.15, 1.15])
        this.box([8, 0.08, 0.12], [0, 0.94, z], green, rollers);
      const billets = this.group("billets");
      const BILLET_PITCH = 3.2,
        BILLET_SPAN = BILLET_PITCH * 3;
      const pieces = [-BILLET_PITCH, 0, BILLET_PITCH].map((x) =>
        this.box([1.7, 0.18, 0.55], [x, 1.31, 0], hot, billets),
      );
      // Billets ride on the roller surface: no slip, so speed = radius * angular speed.
      this.animated.push((t, dt, rate) => {
        const step = ROLLER_RADIUS * ROLLER_SPEED * rate * dt;
        pieces.forEach((p) => {
          const x = p.position.x + step + BILLET_SPAN / 2;
          p.position.x = ((x % BILLET_SPAN) + BILLET_SPAN) % BILLET_SPAN - BILLET_SPAN / 2;
        });
      });
      const burners = this.group("burner");
      for (const x of [-1.5, 0, 1.5]) {
        const n = this.cylinder(0.16, 0.6, [x, 1.55, -1.6], green, burners);
        n.rotation.x = Math.PI / 2;
        const flame = this.mesh(
          new THREE.ConeGeometry(0.17, 0.65, 16),
          hot,
          [x, 1.5, -0.92],
          burners,
        );
        flame.rotation.x = Math.PI / 2;
        this.flicker(flame, x);
      }
      for (const x of [-1.4, 1.4]) {
        this.cylinder(0.2, 1.2, [x, 3, -0.65], metal, burners);
        this.fan([x, 3.64, -0.65], 0.36, light, burners, 7);
      }
    } else {
      const reactor = this.group("reactor");
      const shell = this.cylinder(1.05, 2.2, [0, 1.65, 0], metal, reactor);
      this.shells.push(shell);
      const cap = this.mesh(
        new THREE.SphereGeometry(1.05, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2),
        light,
        [0, 2.75, 0],
        reactor,
      );
      cap.scale.y = 0.45;
      this.shells.push(cap);
      this.cylinder(
        0.88,
        1.5,
        [0, 1.4, 0],
        this.material(0x35a4ba, { transparent: true, opacity: 0.72 }),
        reactor,
      );
      for (const x of [-0.7, 0.7])
        for (const z of [-0.7, 0.7])
          this.box([0.14, 0.65, 0.14], [x, 0.3, z], dark, reactor);
      const jacket = this.group("jacket");
      for (const y of [0.68, 2.63])
        this.mesh(
          new THREE.TorusGeometry(1.09, 0.1, 12, 48),
          green,
          [0, y, 0],
          jacket,
        ).rotation.x = Math.PI / 2;
      for (let y = 0.85; y < 2.5; y += 0.22)
        this.mesh(
          new THREE.TorusGeometry(1.09, 0.045, 8, 48),
          hot,
          [0, y, 0],
          jacket,
        ).rotation.x = Math.PI / 2;
      const agitator = this.group("agitator");
      this.box([0.6, 0.45, 0.6], [0, 3.4, 0], green, agitator);
      const shaft = this.cylinder(0.07, 2.8, [0, 2, 0], light, agitator);
      this.rotors.push([shaft, "y", 0.8]);
      for (const y of [1.1, 1.8]) {
        const blade = this.box([1.55, 0.08, 0.22], [0, y, 0], light, agitator);
        this.rotors.push([blade, "y", 0.8]);
      }
      const pipes = this.group("pipes");
      for (const x of [-1.8, 1.8]) {
        this.cylinder(0.09, 2.9, [x, 1.45, 0], green, pipes);
        const p = this.cylinder(0.09, 0.8, [x * 0.77, 2.8, 0], green, pipes);
        p.rotation.z = Math.PI / 2;
      }
      this.box([0.8, 0.8, 0.7], [2.6, 0.4, 0], dark, pipes);
      this.cylinder(0.22, 0.45, [2.6, 0.85, 0], light, pipes);
      this.fan([2.6, 1.12, 0], 0.4, light, pipes, 6);
      // Flow markers travel along the vertical process lines at a rate set by the actuator.
      const flowMaterial = this.material(0x8fd3e6, { emissive: 0x2a7f95 });
      const markers = [-1.8, 1.8].flatMap((x, side) =>
        [0, 1, 2].map((n) => {
          const m = this.mesh(new THREE.SphereGeometry(0.07, 12, 8), flowMaterial, [x, 0.2, 0], pipes);
          m.userData.phase = n / 3;
          m.userData.side = side ? -1 : 1;
          return m;
        }),
      );
      this.flow = 0;
      this.animated.push((t, dt, rate) => {
        this.flow = (this.flow + dt * 0.25 * rate) % 1;
        markers.forEach((m) => {
          const u = (this.flow + m.userData.phase) % 1;
          m.position.y = 0.2 + (m.userData.side > 0 ? u : 1 - u) * 2.5;
        });
      });
      this.mesh(
        new THREE.TorusGeometry(0.19, 0.035, 8, 32),
        hot,
        [1.8, 1.2, 0],
        pipes,
      );
    }
    // Platform pad stripes are decorative and deliberately have no process metadata.
    for (const z of [-3.1, 3.1])
      this.box([9, 0.015, 0.045], [0, -0.05, z], green);
    this.details(industry, metal, dark, light);
    this.tagGroups();
    this.buildAnnotations();
    this.setCutaway(this.cutaway);
    this.selected = null;
    if (!this.compact) this.select(EQUIPMENT[industry][0][0]);
    else if (this.container.clientWidth) this.frameModel();
  }
  setState(state) {
    this.state = state;
    if (this.industry !== state.spec.industry) this.build(state.spec.industry);
    this.setTemperature(state.temperature);
    const tracking = THREE.MathUtils.clamp(state.actuator/50,0,2);
    this.processRate = state.stuck ? 0 : tracking;
    this.showClock(state);
  }
  // Simulated process time. "Running" means the sampler advanced it within the last few seconds.
  showClock(state) {
    const el = document.getElementById("scene-clock");
    if (!el) return;
    const sim = state.sim_seconds ?? 0;
    if (sim !== this.lastSim || this.lastPlant !== state.spec.id) {
      this.lastSim = sim;
      this.lastPlant = state.spec.id;
      this.lastAdvance = performance.now();
    }
    const running = performance.now() - this.lastAdvance < 6000 && sim > 0;
    const t = Math.floor(sim);
    const pad = (n) => String(n).padStart(2, "0");
    const clock = `${pad(Math.floor(t / 3600))}:${pad(Math.floor((t % 3600) / 60))}:${pad(t % 60)}`;
    el.textContent = `Sim time ${clock} · tick ${state.tick} · ${running ? "running" : "held"}`;
    el.dataset.running = String(running);
    clearTimeout(this.clockTimer);
    if (running) this.clockTimer = setTimeout(() => this.showClock(this.state), 6100);
  }
  setTemperature(value) {
    this.displayTemperature = value;
    if (!this.state) return;
    const scale = { cement: 100, steel: 100, chemical: 15 }[this.industry];
    const fraction = THREE.MathUtils.clamp(
      (value - this.state.target) / scale,
      -1,
      1,
    );
    const color = new THREE.Color().setHSL(
      0.095 - fraction * 0.045,
      0.85,
      0.55,
    );
    this.hotMaterials.forEach((m) => {
      m.color.copy(this.heatmap ? color : new THREE.Color(0xd49160));
      m.emissive.copy(color);
      m.emissiveIntensity = this.heatmap
        ? 0.2 + Math.max(0, fraction) * 0.55 + (this.state.actuator/100)*0.5
        : 0.1;
    });
  }
  setHeatmap(value) {
    this.heatmap = value;
    this.setTemperature(this.displayTemperature);
  }
  setCutaway(value) {
    this.cutaway = value;
    this.shells?.forEach((s) => {
      s.visible = !value;
    });
  }
  select(id) {
    const entry = EQUIPMENT[this.industry].find((e) => e[0] === id);
    if (!entry) return;
    this.selected = id;
    this.annotations.forEach((a) =>
      a.e.classList.toggle("selected", a.id === id),
    );
    this.onInspect(entry, EQUIPMENT[this.industry]);
    // A box helper highlights the selected equipment without changing shared materials.
    if (this.selection) {
      this.scene.remove(this.selection);
      this.selection.geometry.dispose();
      this.selection.material.dispose();
    }
    const g = this.model.children.find((o) => o.userData.equipment === id);
    if (g) {
      this.selection = new THREE.BoxHelper(g, 0x4485af);
      this.selection.material.transparent = true;
      this.selection.material.opacity = 0.45;
      this.scene.add(this.selection);
    }
  }
  setCamera(view) {
    const poses = { iso: [9, 7, 10], top: [0.01, 14, 0.01], front: [0, 3, 13] };
    this.camera.position.set(...poses[view]);
    this.controls.target.set(0, 1.3, 0);
    this.controls.update();
  }
  frame(time) {
    const dt = Math.min((time - this.lastTime) / 1000, 0.05);
    this.lastTime = time;
    if (document.hidden || !this.container.clientWidth) return;
    if (this.motion) {
      const rate = this.processRate ?? 1;
      this.clock = (this.clock ?? 0) + dt;
      this.rotors?.forEach(([o, axis, speed]) => {
        o.rotation[axis] += dt * speed * rate;
      });
      this.animated?.forEach((fn) => fn(this.clock, dt, rate));
    }
    this.selection?.update();
    if (this.compact) this.sway();
    this.controls.update();
    this.annotations.forEach((a) => {
      this.projected.copy(a.point).project(this.camera);
      const visible =
        this.labelsEnabled &&
        (this.container.clientWidth > 480 || a.id === this.selected) &&
        this.projected.z < 1 &&
        Math.abs(this.projected.x) < 0.95 &&
        Math.abs(this.projected.y) < 0.88;
      a.e.hidden = !visible;
      if (visible) {
        a.e.style.left = `${(this.projected.x * 0.5 + 0.5) * 100}%`;
        a.e.style.top = `${(-this.projected.y * 0.5 + 0.5) * 100}%`;
      }
    });
    this.renderer.render(this.scene, this.camera);
  }
  destroy() {
    this.renderer.setAnimationLoop(null);
    this.resize.disconnect();
    this.dock.disconnect();
    this.controls.dispose();
    this.disposeModel();
    this.scene.traverse((o) => {
      o.geometry?.dispose();
      o.material?.dispose();
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
