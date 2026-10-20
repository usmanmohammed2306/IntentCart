/**
 * IntentCart's original, procedural WebGL workstation.
 * All geometry, imagery and motion are local; this visual does not imply live
 * inventory, model inference, simulated compatibility or measured telemetry.
 */
import * as THREE from './vendor/three.module.js';

const COLORS = {cyan: 0x84e4ed, blue: 0x8badcc, amber: 0xe9b57e, ink: 0x060b10, metal: 0x747f87};
const EVIDENCE = {
  concept: {color: 0x8badcc, ink: '#8badcc', label: 'CONCEPT ASSEMBLY'},
  unresolved: {color: 0xe9b57e, ink: '#e9b57e', label: 'EVIDENCE NEEDED'},
  verified: {color: 0x84e4ed, ink: '#84e4ed', label: 'FIXTURE CHECKS PASS'},
  conflict: {color: 0xee897c, ink: '#ee897c', label: 'CONSTRAINT CONFLICT'},
  changed: {color: 0xc5b0f1, ink: '#c5b0f1', label: 'REVIEW CHANGED PLAN'},
};
const TAU = Math.PI * 2;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const damp = (value, target, delta, speed = 7) => THREE.MathUtils.lerp(value, target, 1 - Math.exp(-delta * speed));

export function createSpatialScene(container, {onSelect = () => {}, onReady = () => {}, onError = () => {}} = {}) {
  if (!container) throw new Error('The spatial scene needs a container.');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(37, 1, 0.1, 90);
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'low-power'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x050808, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.04;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  const canvas = renderer.domElement;
  canvas.className = 'spatial-canvas';
  canvas.setAttribute('aria-label', 'Interactive 3D concept workstation. Drag to orbit. Use component buttons to inspect parts.');
  canvas.setAttribute('role', 'img');
  canvas.style.cssText = 'position:absolute;inset:0;display:block;width:100%;height:100%;touch-action:pan-y;cursor:grab;outline:none;';
  container.appendChild(canvas);

  let disposed = false, visible = true, frame = 0, lastTime = 0, elapsed = 0;
  let requestedMotion = true, motion = !reducedMotion.matches, autoRotate = true, exploded = false, dirty = false;
  let selected = '', hasPlan = false, displayCount = 2, reuseMonitor = true;
  let evidenceMode = false, evidenceState = 'concept', shadowSettling = 0;
  let needsRender = true, width = 0, height = 0, drag = null, pointerDown = null, cameraShift = NaN;
  let requestedView = 'hero', focusedPart = '', lastInteraction = -100, pulseTime = -100;
  const resources = new Set(), customDisposers = [];
  const interactables = [], pick = new THREE.Raycaster(), pointer = new THREE.Vector2();
  const parts = {}, animations = [], screenTextures = [];
  const orbit = {theta: .26, phi: 1.18, radius: 10.2, targetTheta: .26, targetPhi: 1.18, targetRadius: 10.2};
  const lookAt = new THREE.Vector3(0, .94, .3);
  const targetLookAt = lookAt.clone();
  const up = new THREE.Vector3(0, 1, 0);

  const own = value => {resources.add(value); return value;};
  const mat = (color, options = {}) => own(new THREE.MeshStandardMaterial({color, metalness: .65, roughness: .34, ...options}));
  const basic = (color, options = {}) => own(new THREE.MeshBasicMaterial({color, ...options}));
  // Anisotropic-looking tooling marks are generated locally. A fixed pattern
  // avoids texture downloads and keeps the same hardware in every session.
  const brushCanvas = document.createElement('canvas'); brushCanvas.width = brushCanvas.height = 256;
  const brushContext = brushCanvas.getContext('2d');
  brushContext.fillStyle = '#a9a9a9'; brushContext.fillRect(0, 0, 256, 256);
  for (let line = 0; line < 256; line++) {
    const value = 142 + ((line * 47 + line * line * 13) % 47);
    brushContext.fillStyle = `rgb(${value},${value},${value})`;
    brushContext.fillRect(0, line, 256, 1);
  }
  const brushTexture = own(new THREE.CanvasTexture(brushCanvas));
  brushTexture.wrapS = brushTexture.wrapT = THREE.RepeatWrapping;
  brushTexture.repeat.set(2, 3);
  const metal = mat(COLORS.metal, {metalness: .91, roughness: .3, roughnessMap: brushTexture, bumpMap: brushTexture, bumpScale: .0015});
  const graphite = mat(0x141c24, {metalness: .76, roughness: .36, roughnessMap: brushTexture});
  const dark = mat(0x050909, {metalness: .2, roughness: .48});
  const edge = mat(0xadbcc8, {metalness: .96, roughness: .2});
  const glass = own(new THREE.MeshPhysicalMaterial({color: 0x96bfcd, metalness: .08, roughness: .08, transparent: true, opacity: .045, clearcoat: 1, clearcoatRoughness: .06, depthWrite: false}));
  const keyMaterial = mat(0x11191a, {metalness: .12, roughness: .64});
  // Unlit luminous cores retain their color while the metal uses filmic tone mapping.
  const cyan = basic(COLORS.cyan, {toneMapped: false});
  const amber = basic(COLORS.amber, {toneMapped: false});
  const blue = basic(COLORS.blue, {toneMapped: false});
  const translucent = basic(COLORS.cyan, {transparent: true, opacity: .1, side: THREE.DoubleSide, depthWrite: false});

  // A generated studio reflection map gives the devices dimensional metal edges.
  const envCanvas = document.createElement('canvas');
  envCanvas.width = 1024; envCanvas.height = 512;
  const envContext = envCanvas.getContext('2d');
  envContext.fillStyle = '#060b10'; envContext.fillRect(0, 0, 1024, 512);
  const envGradient = envContext.createLinearGradient(0, 0, 0, 512);
  envGradient.addColorStop(0, '#162329'); envGradient.addColorStop(.46, '#2a353c');
  envGradient.addColorStop(.5, '#060b10'); envGradient.addColorStop(1, '#020407');
  envContext.fillStyle = envGradient; envContext.fillRect(0, 0, 1024, 512);
  envContext.fillStyle = '#e5eef0'; envContext.fillRect(115, 95, 116, 110);
  envContext.fillStyle = '#7fcad9'; envContext.fillRect(302, 92, 24, 158);
  envContext.fillStyle = '#d8e6eb'; envContext.fillRect(740, 112, 60, 142);
  envContext.fillStyle = '#aa7d52'; envContext.fillRect(884, 164, 16, 72);
  const envTexture = own(new THREE.CanvasTexture(envCanvas));
  envTexture.mapping = THREE.EquirectangularReflectionMapping;
  envTexture.colorSpace = THREE.SRGBColorSpace;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = pmrem.fromEquirectangular(envTexture);
  resources.add(environment); pmrem.dispose();
  scene.environment = environment.texture;
  scene.add(new THREE.AmbientLight(0x8da5bc, .4));
  scene.add(new THREE.HemisphereLight(0xafc8dc, 0x090d14, .85));
  const keyLight = new THREE.DirectionalLight(0xeaf3f5, 4.2); keyLight.position.set(-4, 7, 5); scene.add(keyLight);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  Object.assign(keyLight.shadow.camera, {left: -6, right: 6, top: 6, bottom: -6, near: .5, far: 22});
  keyLight.shadow.bias = -.00035; keyLight.shadow.normalBias = .025;
  customDisposers.push(() => keyLight.shadow.dispose());
  const rimLight = new THREE.DirectionalLight(0x75dceb, 4.8); rimLight.position.set(5, 3, -4); scene.add(rimLight);
  const wash = new THREE.PointLight(0x67d8e9, 12, 14, 2); wash.position.set(-4, 1.4, -.8); scene.add(wash);
  const practical = new THREE.PointLight(0xeaba86, 8, 10, 2); practical.position.set(4.4, .8, 2.4); scene.add(practical);
  const frontFill = new THREE.DirectionalLight(0xc2d7e5, 1.25); frontFill.position.set(1, 2, 7); scene.add(frontFill);

  function roundedGeometry(w, h, d, radius = .08) {
    const r = Math.min(radius, w / 3, h / 3, d / 2);
    const shape = new THREE.Shape();
    const x = -w / 2 + r, y = -h / 2 + r, rw = w - 2 * r, rh = h - 2 * r;
    shape.moveTo(x, y - r); shape.lineTo(x + rw, y - r);
    shape.quadraticCurveTo(x + rw + r, y - r, x + rw + r, y);
    shape.lineTo(x + rw + r, y + rh); shape.quadraticCurveTo(x + rw + r, y + rh + r, x + rw, y + rh + r);
    shape.lineTo(x, y + rh + r); shape.quadraticCurveTo(x - r, y + rh + r, x - r, y + rh);
    shape.lineTo(x - r, y); shape.quadraticCurveTo(x - r, y - r, x, y - r);
    const geometry = new THREE.ExtrudeGeometry(shape, {depth: Math.max(.001, d - r), bevelEnabled: true, bevelSegments: 2, steps: 1, bevelSize: r / 2, bevelThickness: r / 2, curveSegments: 5});
    geometry.translate(0, 0, -d / 2 + r / 2);
    return own(geometry);
  }
  function box(parent, w, h, d, material, x = 0, y = 0, z = 0, radius = .045) {
    const mesh = new THREE.Mesh(radius ? roundedGeometry(w, h, d, radius) : own(new THREE.BoxGeometry(w, h, d)), material);
    mesh.position.set(x, y, z); mesh.castShadow = !material.transparent; mesh.receiveShadow = !material.transparent; parent.add(mesh); return mesh;
  }
  function cylinder(parent, radius, length, material, x = 0, y = 0, z = 0, segments = 64) {
    const mesh = new THREE.Mesh(own(new THREE.CylinderGeometry(radius, radius, length, segments)), material);
    mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh;
  }
  function ring(parent, radius, thickness, material, y = 0, arc = TAU) {
    const mesh = new THREE.Mesh(own(new THREE.TorusGeometry(radius, thickness, 6, 128, arc)), material);
    mesh.rotation.x = Math.PI / 2; mesh.position.y = y; parent.add(mesh); return mesh;
  }
  function wire(parent, points, material, radius = .012, segments = 40) {
    const curve = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)));
    const mesh = new THREE.Mesh(own(new THREE.TubeGeometry(curve, segments, radius, 5, false)), material);
    parent.add(mesh); return {mesh, curve};
  }
  function tagPart(group, kind) {
    group.traverse(object => {if (object.isMesh) {object.userData.part = kind; interactables.push(object);}});
  }
  function createPart(kind, position, spread) {
    const group = new THREE.Group(); group.position.set(...position); scene.add(group);
    parts[kind] = {group, origin: new THREE.Vector3(...position), spread: new THREE.Vector3(...spread)};
    return group;
  }

  // A machined island and dark architectural floor create a tangible studio.
  // This is an illustrative fixture assembly, never a hardware simulation.
  const stage = new THREE.Group(); stage.position.y = -.77; scene.add(stage);
  function islandShape(w, d, radius) {
    const x = -w / 2, y = -d / 2, shape = new THREE.Shape();
    shape.moveTo(x + radius, y); shape.lineTo(x + w - radius, y);
    shape.quadraticCurveTo(x + w, y, x + w, y + radius);
    shape.lineTo(x + w, y + d - radius); shape.quadraticCurveTo(x + w, y + d, x + w - radius, y + d);
    shape.lineTo(x + radius, y + d); shape.quadraticCurveTo(x, y + d, x, y + d - radius);
    shape.lineTo(x, y + radius); shape.quadraticCurveTo(x, y, x + radius, y);
    return shape;
  }
  const slabGeometry = own(new THREE.ExtrudeGeometry(islandShape(8.45, 6.7, .6), {
    depth: .16, bevelEnabled: true, bevelSegments: 3, bevelSize: .055, bevelThickness: .035, steps: 1, curveSegments: 12,
  }));
  slabGeometry.rotateX(-Math.PI / 2); slabGeometry.translate(0, -.15, 0);
  const stageSurface = new THREE.Mesh(slabGeometry, own(new THREE.MeshPhysicalMaterial({color: 0x0b151f, metalness: .5, roughness: .38, roughnessMap: brushTexture, envMapIntensity: .55, clearcoat: .45, clearcoatRoughness: .32})));
  stageSurface.receiveShadow = true; stageSurface.castShadow = true; stage.add(stageSurface);
  const undersideGeometry = own(new THREE.ExtrudeGeometry(islandShape(8.18, 6.44, .56), {
    depth: .1, bevelEnabled: true, bevelSegments: 2, bevelSize: .035, bevelThickness: .025, steps: 1, curveSegments: 12,
  }));
  undersideGeometry.rotateX(-Math.PI / 2); undersideGeometry.translate(0, -.27, 0);
  const undercut = new THREE.Mesh(undersideGeometry, graphite); undercut.castShadow = true; stage.add(undercut);
  const seamPoints = islandShape(8.47, 6.72, .6).getPoints(120).slice(0, -1).map(point => new THREE.Vector3(point.x, -.045, -point.y));
  const seamCurve = new THREE.CatmullRomCurve3(seamPoints, true, 'centripetal');
  stage.add(new THREE.Mesh(own(new THREE.TubeGeometry(seamCurve, 240, .008, 4, true)), basic(COLORS.cyan, {transparent: true, opacity: .6, toneMapped: false})));
  for (const x of [-3.4, 3.4]) {
    for (const z of [-2.5, 2.5]) {
      cylinder(stage, .22, .35, graphite, x, -.42, z, 24);
      cylinder(stage, .29, .055, dark, x, -.61, z, 24);
      // Recessed titanium fasteners are visible in close inspection.
      cylinder(stage, .045, .004, edge, x, .043, z, 12);
      box(stage, .041, .005, .007, dark, x, .046, z, 0);
    }
  }
  // A finite, feathered ground avoids the opaque horizon rectangle a large
  // reflective plane would create over the host's dark transparent canvas.
  const floorMaskCanvas = document.createElement('canvas'); floorMaskCanvas.width = floorMaskCanvas.height = 128;
  const floorMaskContext = floorMaskCanvas.getContext('2d');
  const floorMask = floorMaskContext.createRadialGradient(64,64,10,64,64,63);
  floorMask.addColorStop(0,'#ffffff'); floorMask.addColorStop(.4,'#d0d0d0');floorMask.addColorStop(.8,'#363636');floorMask.addColorStop(1,'#000000');
  floorMaskContext.fillStyle=floorMask;floorMaskContext.fillRect(0,0,128,128);
  const floorAlpha = own(new THREE.CanvasTexture(floorMaskCanvas));
  const floor = new THREE.Mesh(own(new THREE.PlaneGeometry(28,24)), mat(0x030910, {metalness: .06, roughness: .9, envMapIntensity: .12, transparent:true, opacity:.72, alphaMap:floorAlpha, depthWrite:false}));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -1.44; floor.receiveShadow = true; scene.add(floor);
  scene.fog = new THREE.FogExp2(0x0b1420, .025);
  const architecture = new THREE.Group(); scene.add(architecture);
  for (const side of [-1, 1]) {
    const x = side * 5.05;
    box(architecture, .12, 5.4, .18, graphite, x, 1.2, -3.9, .04);
    box(architecture, .025, 3.8, .025, side < 0 ? cyan : blue, x - side * .058, 1.25, -3.796, .008);
    box(architecture, .28, .06, 1.55, graphite, x - side * .075, -1.39, -3.4, .02);
  }
  // Two quiet inlaid rails suggest the assembly station's geometry, not data.
  for (const x of [-4.62, 4.62]) wire(architecture, [[x,-1.425,4],[x,-1.425,-4],[x*.72,-1.425,-6]], basic(0x294653, {transparent:true,opacity:.42}), .008, 12);
  // Only the front face gets an accent; it is a material detail, not a gauge.
  box(stage, .46, .014, .014, amber, 2.8, -.105, 3.42, .003);
  box(stage, .11, .014, .014, dark, 2.39, -.105, 3.42, .003);
  const stageGlowCanvas = document.createElement('canvas'); stageGlowCanvas.width = stageGlowCanvas.height = 128;
  const glowContext = stageGlowCanvas.getContext('2d');
  const glowGradient = glowContext.createRadialGradient(64, 64, 4, 64, 64, 64);
  glowGradient.addColorStop(0, 'rgba(89,194,216,.23)'); glowGradient.addColorStop(.4, 'rgba(64,137,164,.1)'); glowGradient.addColorStop(.72, 'rgba(46,87,119,.035)'); glowGradient.addColorStop(1, 'rgba(0,0,0,0)');
  glowContext.fillStyle = glowGradient; glowContext.fillRect(0, 0, 128, 128);
  const glowTexture = own(new THREE.CanvasTexture(stageGlowCanvas));
  const platformGlow = new THREE.Mesh(own(new THREE.PlaneGeometry(13, 11)), basic(0xffffff, {map: glowTexture, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false}));
  platformGlow.rotation.x = -Math.PI / 2; platformGlow.position.y = -1.43; scene.add(platformGlow);

  // Generated radial glows simulate a restrained bloom locally, without the
  // resolution cost of a full-screen postprocessing chain on smaller devices.
  const haloCanvas=document.createElement('canvas');haloCanvas.width=haloCanvas.height=128;
  const haloContext=haloCanvas.getContext('2d');
  const haloGradient=haloContext.createRadialGradient(64,64,0,64,64,64);
  haloGradient.addColorStop(0,'rgba(255,255,255,.9)');haloGradient.addColorStop(.16,'rgba(255,255,255,.42)');
  haloGradient.addColorStop(.46,'rgba(255,255,255,.11)');haloGradient.addColorStop(1,'rgba(255,255,255,0)');
  haloContext.fillStyle=haloGradient;haloContext.fillRect(0,0,128,128);
  const haloTexture=own(new THREE.CanvasTexture(haloCanvas));
  function halo(parent,color,size,opacity,x,y,z) {
    const sprite=new THREE.Sprite(own(new THREE.SpriteMaterial({map:haloTexture,color,transparent:true,opacity,blending:THREE.AdditiveBlending,depthWrite:false,toneMapped:false})));
    sprite.scale.set(size,size,1);sprite.position.set(x,y,z);parent.add(sprite);return sprite;
  }
  halo(scene, COLORS.cyan, 3.2, .075, -5, 1.1, -3.7);
  halo(scene, COLORS.blue, 3.2, .055, 5, 1.1, -3.7);
  halo(scene, COLORS.amber, 1.2, .12, 2.8, -.875, 3.42);

  // Generated contact shades keep the devices grounded without a shadow-map
  // pass. Their softening during Explode is a visual cue, not physical simulation.
  const contactShadows = [];
  function contactShadow(kind, x, z, width, depth, opacity = .48) {
    const material = basic(0x00030b, {map:haloTexture, transparent:true, opacity, depthWrite:false, toneMapped:false});
    const shadow = new THREE.Mesh(own(new THREE.PlaneGeometry(width, depth)), material);
    shadow.rotation.x = -Math.PI / 2; shadow.position.set(x, -.697, z); scene.add(shadow);
    contactShadows.push({kind, shadow, opacity});
  }
  contactShadow('monitor', 0, -.5, 7, 2.6, .65);
  contactShadow('laptop', -.65, 2.05, 3.9, 2.4, .65);
  contactShadow('dock', .6, .54, 2.1, 1.7, .55);
  contactShadow('power', 2.6, 1.9, 1.7, 1.7);


  function makeScreen(w, h, variant = 0) {
    const screenCanvas = document.createElement('canvas'); screenCanvas.width = 512; screenCanvas.height = 320;
    const context = screenCanvas.getContext('2d');
    const texture = own(new THREE.CanvasTexture(screenCanvas)); texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
    const material = basic(0xffffff, {map: texture, toneMapped: false});
    const mesh = new THREE.Mesh(own(new THREE.PlaneGeometry(w, h)), material);
    function draw(time) {
      const t = time * .12 + variant * .85;
      const status = EVIDENCE[evidenceState];
      const gradient = context.createLinearGradient(0, 0, 512, 320);
      gradient.addColorStop(0, '#06111b'); gradient.addColorStop(.62, '#102b38'); gradient.addColorStop(1, '#030a12');
      context.fillStyle = gradient; context.fillRect(0, 0, 512, 320);
      const spill = context.createRadialGradient(282, 153, 3, 282, 153, 210);
      spill.addColorStop(0, 'rgba(41,157,190,.38)'); spill.addColorStop(1, 'rgba(0,0,0,0)');
      context.fillStyle = spill; context.fillRect(0, 0, 512, 320);
      // A slow contour sculpture gives the concept display depth. It represents
      // no learned embedding, compatibility score, sensor or inference stream.
      if (variant !== 1) {
        const centerX = variant === 2 ? 290 : 275, centerY = 174;
        const layers = 34;
        for (let layer = 0; layer < layers; layer++) {
          const latitude = (layer / (layers - 1) - .5) * Math.PI;
          const radius = Math.cos(latitude) * 112;
          context.beginPath();
          for (let i = 0; i <= 90; i++) {
            const angle = i / 90 * TAU;
            const warp = 1 + .1 * Math.sin(angle * 3 + latitude * 3 + t);
            const x = Math.cos(angle) * radius * warp;
            const z = Math.sin(angle) * radius * warp;
            const y = Math.sin(latitude) * 90;
            const rotatedX = x * Math.cos(t * .35) - z * Math.sin(t * .35);
            const rotatedZ = x * Math.sin(t * .35) + z * Math.cos(t * .35);
            const perspective = 420 / (420 + rotatedZ);
            const px = centerX + (rotatedX * .92 + y * .24) * perspective;
            const py = centerY + (y * .82 - rotatedZ * .25) * perspective;
            if (!i) context.moveTo(px, py); else context.lineTo(px, py);
          }
          const brightness = .3 + .65 * Math.sin(layer / layers * Math.PI);
          context.strokeStyle = `rgba(115,233,250,${brightness})`;
          context.lineWidth = layer % 5 === 0 ? 1.8 : 1;
          context.shadowBlur=layer%5===0?4:0;context.shadowColor='#56cce3';
          context.stroke();
        }
        context.shadowBlur=0;
      } else {
        // The evidence display is a diagram of component relationships. Status
        // comes only from the host's bounded fixture claims, never from animation.
        const nodes = [[87,164,'LAPTOP'],[252,164,'DOCK'],[405,103,'DISPLAY'],[405,228,displayCount === 1 ? 'POWER' : 'DISPLAY']];
        context.strokeStyle = evidenceMode ? status.ink : '#548798';
        context.lineWidth = 1.4;
        for (const points of [[[112,164],[226,164]],[[278,164],[322,164],[322,103],[378,103]],[[278,164],[322,164],[322,228],[378,228]]]) {
          context.beginPath(); points.forEach(([x,y],i)=>i?context.lineTo(x,y):context.moveTo(x,y)); context.stroke();
        }
        nodes.forEach(([x,y,label], index) => {
          context.fillStyle = '#0a1e2b'; context.fillRect(x-25,y-19,50,38);
          context.strokeStyle = index === 1 ? '#9fdfeb' : '#4d7b8f'; context.strokeRect(x-25,y-19,50,38);
          context.strokeStyle = '#8eb6c2'; context.lineWidth = 1;
          context.strokeRect(x-12,y-8,24,13); context.beginPath(); context.moveTo(x-6,y+10);context.lineTo(x+6,y+10);context.stroke();
          context.fillStyle = '#88a6b8'; context.font = '9px ui-monospace, monospace'; context.textAlign = 'center'; context.fillText(label,x,y+35);
        });
        context.textAlign = 'left';
      }
      context.fillStyle = '#d7e9ef'; context.font = '500 11px ui-monospace, monospace';
      context.fillText(variant === 1 ? 'EVIDENCE / CONNECTIONS' : 'I N T E N T C A R T', 26, 29);
      context.fillStyle = '#668797'; context.font = '8px ui-monospace, monospace';
      context.fillText('ILLUSTRATIVE FIXTURE ASSEMBLY', 26, 46);
      context.fillStyle = evidenceMode ? status.ink : '#819eae'; context.fillRect(27,285,4,4);
      context.font = '9px ui-monospace, monospace'; context.fillText(evidenceMode ? status.label : 'DESCRIBE. VERIFY. REVIEW.', 40, 291);
      context.fillStyle = '#284554'; context.fillRect(26,307,460,1);
      texture.needsUpdate = true;
    }
    draw(0); screenTextures.push(draw); return mesh;
  }

  const monitors = createPart('monitor', [0, 0, -.65], [0, 1, -1]);
  function monitor(x, angle, variant) {
    const assembly = new THREE.Group(); assembly.position.set(x, .92, 0); assembly.rotation.y = angle; monitors.add(assembly);
    const caseBody = box(assembly, 2.95, 1.9, .12, graphite, 0, 1.12, 0, .055);
    box(assembly, 2.94, 1.89, .026, edge, 0, 1.12, .043, .05);
    box(assembly, 2.82, 1.78, .008, dark, 0, 1.12, .064, .025);
    const screen = makeScreen(2.73, 1.66, variant); screen.position.set(0, 1.14, .072); assembly.add(screen);
    box(assembly, 2.74, 1.67, .002, glass, 0, 1.14, .078, .009);
    box(assembly, 2.9, .022, .03, edge, 0, .19, .063, .006);
    box(assembly, .04, .008, .012, cyan, 1.29, .225, .074, .002);
    box(assembly, .17, 2.1, .13, metal, 0, -.54, -.08, .025);
    box(assembly, .055, 1.28, .008, dark, 0, -.8, -.151, .008);
    box(assembly, .94, .06, .65, graphite, 0, -1.58, .075, .025);
    box(assembly, .94, .007, .65, edge, 0, -1.546, .075, .006);
    box(assembly, .78, .05, .48, dark, 0, -1.629, .075, .025);
    cylinder(assembly, .12, .17, edge, 0, .35, -.145, 24).rotation.x = Math.PI / 2;
    box(assembly, .58, .66, .036, graphite, 0, 1.06, -.081, .06);
    for (const screwX of [-.23, .23]) for (const screwY of [.81,1.31]) {
      cylinder(assembly, .022, .01, edge, screwX, screwY, -.109, 8).rotation.x = Math.PI / 2;
    }
    // Backplate vent details remain visible when the user orbits.
    for (let k = 0; k < 14; k++) box(assembly, .025, .17, .009, dark, -.58 + k * .09, .49, -.067, 0);
    caseBody.userData.screen = true;
    return assembly;
  }
  const leftDisplay = monitor(-1.48, .17, 0), rightDisplay = monitor(1.48, -.17, 1);
  tagPart(monitors, 'monitor');

  const laptop = createPart('laptop', [-.65, -.64, 2.05], [-.45, .68, 1.1]);
  laptop.rotation.y = -.15;
  box(laptop, 2.4, .105, 1.52, metal, 0, 0, 0, .045);
  box(laptop, 2.35, .045, 1.47, graphite, 0, -.071, 0, .04);
  for (const x of [-.9,.9]) for (const z of [-.5,.5]) cylinder(laptop,.065,.02,dark,x,-.099,z,12);
  box(laptop, 2.25, .012, 1.37, graphite, 0, .059, -.02, .015);
  box(laptop, .63, .009, .42, metal, 0, .072, .43, .02);
  box(laptop, .09, .012, .55, dark, -1.05, .075, -.21, .01);
  box(laptop, .09, .012, .55, dark, 1.05, .075, -.21, .01);
  const keyGeometry = roundedGeometry(.145, .026, .108, .008);
  for (let row = 0; row < 5; row++) for (let column = 0; column < 12; column++) {
    if (row === 4 && column > 3 && column < 8) continue;
    const key = new THREE.Mesh(keyGeometry, keyMaterial); key.position.set((column - 5.5) * .166, .085, -.53 + row * .145); laptop.add(key);
  }
  box(laptop, .74, .027, .108, keyMaterial, -.005, .085, .05, .008);
  // Hinge and tilted panel give a legible laptop silhouette from every angle.
  const lid = new THREE.Group(); lid.position.set(0, .01, -.7); lid.rotation.x = -.2; laptop.add(lid);
  box(lid, 2.4, 1.51, .075, metal, 0, .75, 0, .035);
  box(lid, 2.29, 1.4, .008, dark, 0, .75, .043, .015);
  const laptopScreen = makeScreen(2.2, 1.29, 2); laptopScreen.position.set(0, .77, .048); lid.add(laptopScreen);
  box(lid, 2.21, 1.3, .002, glass, 0, .77, .055, .01);
  cylinder(laptop, .05, 2.22, edge, 0, .025, -.705, 20).rotation.z = Math.PI / 2;
  box(lid, .022, .022, .01, dark, 0, 1.46, .048, .004);
  for (let i = 0; i < 2; i++) box(laptop, .006, .035, .14, dark, -1.219, -.003, -.4 + i * .25, .003);
  for (let i = 0; i < 9; i++) box(laptop, .1, .012, .02, dark, .56 + i * .052, .079, -.37, 0);
  box(lid, .22, .22, .008, mat(0x68879b, {metalness: .9, roughness: .25}), 0, .75, -.04, .025).rotation.z = Math.PI / 4;
  tagPart(laptop, 'laptop');

  const dock = createPart('dock', [.6, -.545, .54], [.65, 1.1, .2]);
  dock.rotation.y = -.13;
  box(dock, 1.55, .29, .79, metal, 0, 0, 0, .075);
  box(dock, 1.43, .027, .68, dark, 0, -.163, 0, .035);
  box(dock, 1.46, .2, .02, dark, 0, 0, .396, .035);
  for (let i = 0; i < 3; i++) {
    box(dock, .23, .085, .024, edge, -.49 + i * .34, .008, .414, .008);
    box(dock, .18, .047, .029, dark, -.49 + i * .34, .008, .429, .004);
    box(dock, .15, .012, .005, blue, -.49 + i * .34, .017, .446, 0);
  }
  box(dock, .075, .035, .03, cyan, .6, 0, .425, .009);
  for (let i = 0; i < 12; i++) box(dock, .66, .01, .011, dark, -.18, .153, -.29 + i * .05, 0);
  box(dock, .07, .01, .24, cyan, .55, .155, -.025, .006);
  tagPart(dock, 'dock');

  const power = createPart('power', [2.6, -.43, 1.9], [1.1, .7, .55]);
  power.rotation.y = -.35;
  box(power, .82, .49, .88, mat(0x515f6c, {metalness: .73, roughness: .35, roughnessMap: brushTexture}), 0, 0, 0, .09);
  box(power, .62, .044, .62, dark, 0, -.272, 0, .035);
  box(power, .63, .31, .012, graphite, 0, 0, .452, .04);
  box(power, .13, .047, .022, dark, -.12, .025, .471, .012);
  box(power, .065, .018, .018, cyan, .18, .025, .471, .004);
  box(power, .017, .24, .075, edge, -.17, -.02, -.47, .005);
  box(power, .017, .24, .075, edge, .17, -.02, -.47, .005);
  tagPart(power, 'power');

  const cableGroup = createPart('cable', [0, 0, 0], [0, .45, 0]);
  const cablePaths = [
    [[-1.86,-.64,1.85],[-2.1,-.65,1.85],[-1.85,-.67,.72],[-.17,-.545,.54]],
    [[.36,-.545,.2],[.05,-.64,-.25],[-1.55,-.67,-.9],[-1.48,.45,-.79]],
    [[.87,-.545,.2],[1.55,-.65,-.23],[1.85,-.65,-.85],[1.48,.45,-.79]],
    [[2.43,-.43,2.33],[2.1,-.63,2.36],[1.6,-.67,1.16],[1.33,-.545,.57]],
    [[.36,-.545,.2],[.03,-.65,-.08],[-.2,-.65,-.75],[0,.45,-.79]],
  ];
  const flows = [], cableBranches = [], evidenceBranches = [], evidenceLinks = [];
  const evidenceMaterial = basic(EVIDENCE.concept.color, {toneMapped:false, transparent:true, opacity:.85});
  const evidenceSoft = basic(EVIDENCE.concept.color, {toneMapped:false, transparent:true, opacity:.11, blending:THREE.AdditiveBlending, depthWrite:false});
  const evidenceRoutes = new THREE.Group(); scene.add(evidenceRoutes); evidenceRoutes.visible = false;
  // A single registered arch frames the inspected assembly. It is a spatial
  // mode cue, not a gauge, scan measurement, confidence score or extra claim.
  const inspectionArch = new THREE.Group(); inspectionArch.position.set(0,-.56,-1.8);evidenceRoutes.add(inspectionArch);
  for(const [thickness,material] of [[.009,evidenceMaterial],[.029,evidenceSoft]]) {
    const arc = new THREE.Mesh(own(new THREE.TorusGeometry(3.65,thickness,5,128,Math.PI*.92)),material);
    arc.rotation.z=Math.PI*.04;inspectionArch.add(arc);
  }
  const evidenceFootprints = [['dock',.55],['power',.39]].map(([kind,radius])=>{
    const footprint=ring(evidenceRoutes,radius,.007,evidenceMaterial,-.7);
    footprint.userData.partKind=kind;return footprint;
  });
  cablePaths.forEach((points, i) => {
    const branch=new THREE.Group();branch.name=['laptop-link','left-display-link','right-display-link','power-link','single-display-link'][i];branch.visible=i!==4;cableGroup.add(branch);cableBranches.push(branch);
    wire(branch, points, mat(0x0b121a, {roughness:.55,metalness:.16}), .035, 40);
    const route = new THREE.Group(); route.visible = i !== 4; evidenceRoutes.add(route); evidenceBranches.push(route);
    const raised = points.map(([x,y,z], index)=>[x,y+(index===0||index===points.length-1?.16:.55),z]);
    const path = wire(route, raised, evidenceMaterial, .011, 40);
    const softPath = wire(route, raised, evidenceSoft, .028, 40);
    const ends = [];
    for (const index of [0, raised.length-1]) {
      const node = new THREE.Mesh(own(new THREE.SphereGeometry(.045,12,8)), evidenceMaterial);
      node.position.set(...raised[index]); route.add(node); ends.push(node);
    }
    for (let j = 0; j < 2; j++) {
      const packet = new THREE.Mesh(own(new THREE.SphereGeometry(.023,8,6)), evidenceMaterial);
      route.add(packet); flows.push({packet,curve:path.curve,offset:j/2+i*.11});
    }
    const sourceTarget = [['laptop','dock'],['dock','monitor'],['dock','monitor'],['power','dock'],['dock','monitor']][i];
    evidenceLinks.push({source:sourceTarget[0],target:sourceTarget[1],curve:path.curve,points:raised.map(point=>new THREE.Vector3(...point)),ends,lastFrom:null,lastTo:null,
      tubes:[path.mesh,softPath.mesh].map(mesh=>({geometry:mesh.geometry,base:mesh.geometry.attributes.position.array.slice()}))});
  });
  tagPart(cableGroup, 'cable');
  animations.push(time => flows.forEach(({packet,curve,offset}) => packet.position.copy(curve.getPointAt((time*.1+offset)%1))));

  // A luminous selection outline sits around the real group, with a soft local halo.
  const selection = new THREE.Group(); scene.add(selection);
  ring(selection, .8, .012, cyan);
  ring(selection,.8,.05,basic(COLORS.cyan,{transparent:true,opacity:.09,blending:THREE.AdditiveBlending,depthWrite:false,toneMapped:false}));
  halo(selection,COLORS.cyan,2.2,.08,0,.1,0);
  const selectionArc = ring(selection, .89, .012, blue, .012, Math.PI * .65);
  const selectionDisc = new THREE.Mesh(own(new THREE.CircleGeometry(.8, 64)), translucent);
  selectionDisc.rotation.x = -Math.PI/2; selection.add(selectionDisc); selection.visible = false;
  const pulseRing = ring(scene, .8, .013, basic(COLORS.cyan, {transparent:true,opacity:0}), -.52);
  const particlesGeometry = new THREE.BufferGeometry(), particlePositions = [];
  // Sparse studio dust stays peripheral; it carries no state or telemetry.
  let seed = 27;
  const random = () => {seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  for(let i=0;i<18;i++) particlePositions.push((random()-.5)*21,random()*8-1,(random()-.5)*14-4);
  particlesGeometry.setAttribute('position', new THREE.Float32BufferAttribute(particlePositions,3));own(particlesGeometry);
  const particles = new THREE.Points(particlesGeometry,own(new THREE.PointsMaterial({color:0x8aafc1,size:.012,transparent:true,opacity:.12,sizeAttenuation:true,depthWrite:false})));
  scene.add(particles);

  function selectPart(kind) {
    selected = parts[kind] ? kind : '';
    selection.visible = Boolean(selected);
    lastInteraction = elapsed;
    pulseTime = elapsed;
    needsRender = true;
    renderOnce();
  }
  function updateFocus() {
    if (!focusedPart || !parts[focusedPart]) return;
    const views = {
      laptop: [.08, 1.06, 5.8, [0, .58, -.12]],
      monitor: [.04, 1.37, displayCount === 1 ? 6.2 : 8.4, [0, 2.04, 0]],
      // Approach from above the dock's right front corner: the laptop lid
      // otherwise blocks its ports when viewed from the left front corner.
      dock: [.98, .64, 3.9, [0, .1, .04]],
      cable: [.3, .5, 8.8, [0, .12, .6]],
      power: [.76, .85, 3.5, [0, .04, .08]],
    };
    const [theta, phi, radius, offset] = views[focusedPart];
    const part = parts[focusedPart];
    orbit.targetTheta = theta; orbit.targetPhi = phi; orbit.targetRadius = radius;
    targetLookAt.copy(part.origin).addScaledVector(part.spread, exploded ? 1 : 0).add(new THREE.Vector3(...offset));
  }
  // A host-driven tour can focus one real component at a time. Unlike selectPart,
  // this deliberately moves the camera; it never changes a mission or emits a
  // selection callback that could recursively re-enter the host's controls.
  function focusPart(kind) {
    if (!parts[kind]) return false;
    focusedPart = kind; requestedView = 'focus';
    selectPart(kind); updateFocus(); needsRender = true; renderOnce();
    return true;
  }
  function setState(state = {}) {
    const previous = hasPlan;
    const previousDisplayCount = displayCount;
    hasPlan = Boolean(state.hasPlan);
    dirty = Boolean(state.dirty);
    displayCount = state.displays === 1 ? 1 : 2;
    reuseMonitor = state.reuseMonitor !== false;
    if (state.selected !== undefined) selected = parts[state.selected] ? state.selected : '';
    // One-display plans visibly assemble one display, never a fictitious pair.
    rightDisplay.visible = displayCount > 1;
    leftDisplay.position.x = displayCount > 1 ? -1.48 : 0;
    leftDisplay.rotation.y = displayCount > 1 ? .17 : 0;
    cableBranches[1].visible=displayCount>1;
    cableBranches[2].visible=displayCount>1;
    cableBranches[4].visible=displayCount===1;
    evidenceBranches[1].visible=displayCount>1;
    evidenceBranches[2].visible=displayCount>1;
    evidenceBranches[4].visible=displayCount===1;
    evidenceState = Object.hasOwn(EVIDENCE,state.evidenceState) ? state.evidenceState : dirty ? 'changed' : hasPlan ? 'unresolved' : 'concept';
    evidenceMaterial.color.setHex(EVIDENCE[evidenceState].color);
    evidenceSoft.color.setHex(EVIDENCE[evidenceState].color);
    canvas.dataset.evidenceState = evidenceState;
    if (!previous && hasPlan) pulseTime = elapsed;
    canvas.dataset.plan = hasPlan ? 'assembled' : 'concept';
    canvas.dataset.reuseMonitor = String(reuseMonitor);
    scene.userData.status = state.status || 'concept';
    selection.visible = Boolean(selected);
    if (displayCount !== previousDisplayCount) updateFocus();
    renderer.shadowMap.needsUpdate = true;
    screenTextures.forEach(draw=>draw(elapsed));
    needsRender = true;
    renderOnce();
  }
  function setEvidenceMode(value) {
    evidenceMode=Boolean(value); evidenceRoutes.visible=evidenceMode;
    canvas.dataset.evidenceMode=String(evidenceMode);
    screenTextures.forEach(draw=>draw(elapsed));
    lastInteraction=elapsed;needsRender=true;renderOnce();
  }
  function setExploded(value) {exploded=Boolean(value);shadowSettling=elapsed+1.8;updateFocus();lastInteraction=elapsed;needsRender=true;renderOnce();}
  function setAutoRotate(value) {autoRotate=Boolean(value);lastInteraction=-100;needsRender=true;renderOnce();}
  function setMotion(value) {
    requestedMotion=Boolean(value);motion=requestedMotion&&!reducedMotion.matches;
    needsRender=true;
    if(motion) start(); else {stop(); renderOnce(true);}
  }
  function setView(name='hero') {
    requestedView=name;focusedPart='';
    const views={hero:[.26,1.18,10.2,[0,.94,.3]],front:[0,1.42,11.4,[0,1.05,.1]],top:[0,.2,12.4,[0,.5,.1]],detail:[.58,1.04,8.1,[.15,.5,1.2]],rear:[Math.PI+.3,1.12,11.8,[0,.8,0]]};
    const view=views[name]||views.hero;
    orbit.targetTheta=view[0];orbit.targetPhi=view[1];orbit.targetRadius=view[2];targetLookAt.set(...view[3]);
    lastInteraction=elapsed;needsRender=true;renderOnce();
  }
  function zoom(delta) {orbit.targetRadius=clamp(orbit.targetRadius+Number(delta||0),4.4,20);lastInteraction=elapsed;needsRender=true;renderOnce();}
  function pulse(kind) {if(kind)selectPart(kind);pulseTime=elapsed;needsRender=true;renderOnce();}

  function frameScene(delta, time, instant = false) {
    const instantOr = (current,target,speed=5)=>instant?target:damp(current,target,delta,speed);
    orbit.theta=instantOr(orbit.theta,orbit.targetTheta);
    orbit.phi=instantOr(orbit.phi,orbit.targetPhi);
    orbit.radius=instantOr(orbit.radius,orbit.targetRadius);
    lookAt.lerp(targetLookAt,instant?1:1-Math.exp(-delta*5));
    if(motion&&autoRotate&&!drag&&time-lastInteraction>5&&requestedView==='hero')orbit.targetTheta=.26+Math.sin(time*.065)*.15;
    const aspect=width/Math.max(height,1);
    // The wide hero leaves room for the upper-left title. Wide component tours
    // frame the selected hardware left of center, clear of the right-side card.
    // Narrow layouts stay centered because their card sits above the scene.
    const shift=requestedView==='focus'&&aspect>1.35?-.12:requestedView==='hero'&&aspect>1.35?Math.min(.075,(aspect-1.35)*.12):0;
    if(shift!==cameraShift){camera.setViewOffset(width,height,-width*shift,0,width,height);cameraShift=shift;}
    const responsiveDistance=aspect<1.1?1+(1.1-aspect)*.7:1;
    const r=orbit.radius*responsiveDistance;
    camera.position.set(lookAt.x+r*Math.sin(orbit.phi)*Math.sin(orbit.theta),lookAt.y+r*Math.cos(orbit.phi),lookAt.z+r*Math.sin(orbit.phi)*Math.cos(orbit.theta));
    camera.up.copy(up);camera.lookAt(lookAt);
    for(const [kind,part] of Object.entries(parts)) {
      const target=part.origin.clone().addScaledVector(part.spread,exploded?1:0);
      part.group.position.lerp(target,instant?1:1-Math.exp(-delta*5));
    }
    // Hardware is grounded in assembly view. Explode is an explicit visual
    // separation, and its soft shadows update only while positions settle.
    if(time<shadowSettling||instant)renderer.shadowMap.needsUpdate=true;
    if(evidenceMode) {
      inspectionArch.scale.set(displayCount===1?.71:1,1,1);
      evidenceFootprints.forEach(footprint=>{
        const part=parts[footprint.userData.partKind];
        footprint.position.set(part.group.position.x,-.702+part.group.position.y-part.origin.y,part.group.position.z);
      });
      // Stretch illustrative routes between the actual component transforms
      // during an exploded view; do not leave apparently attached stale ends.
      for(const link of evidenceLinks) {
        const from=parts[link.source].group.position.clone().sub(parts[link.source].origin);
        const to=parts[link.target].group.position.clone().sub(parts[link.target].origin);
        if(link.lastFrom&&link.lastFrom.distanceToSquared(from)<1e-8&&link.lastTo.distanceToSquared(to)<1e-8)continue;
        link.lastFrom=from.clone();link.lastTo=to.clone();
        link.curve.points.forEach((point,index)=>point.copy(link.points[index]).addScaledVector(from,1-index/(link.points.length-1)).addScaledVector(to,index/(link.points.length-1)));
        link.curve.updateArcLengths();
        link.ends[0].position.copy(link.curve.points[0]);
        link.ends[1].position.copy(link.curve.points[link.curve.points.length-1]);
        for(const tube of link.tubes) {
          const attribute=tube.geometry.attributes.position;
          for(let index=0;index<attribute.count;index++) {
            const u=Math.floor(index/6)/40;
            attribute.setXYZ(index,tube.base[index*3]+from.x*(1-u)+to.x*u,tube.base[index*3+1]+from.y*(1-u)+to.y*u,tube.base[index*3+2]+from.z*(1-u)+to.z*u);
          }
          attribute.needsUpdate=true;
          // Moving endpoints can leave the original bounding sphere.
          tube.geometry.computeBoundingSphere();
        }
      }
    }
    contactShadows.forEach(({kind, shadow, opacity}) => {
      shadow.material.opacity = instantOr(shadow.material.opacity, exploded ? opacity * .35 : opacity);
      if (kind === 'monitor') shadow.scale.x = displayCount === 1 ? .55 : 1;
    });
    if(selected&&parts[selected]) {
      const part=parts[selected];
      selection.position.copy(part.group.position);
      selection.position.y=part.group.position.y-.27;
      if(selected==='monitor'){selection.position.y=-.695+(exploded?1:0);selection.scale.set(displayCount===1?1.6:3.2,1,1.3);}
      else if(selected==='laptop'){selection.position.y=part.group.position.y-.13;selection.scale.set(1.75,1,1.22);}
      else if(selected==='cable'){selection.position.y=-.4+(exploded?.45:0);selection.scale.set(2.1,1,2.1);}
      else selection.scale.setScalar(selected==='dock'?1.15:.76);
      selectionArc.rotation.z=time*.55;
      selectionDisc.material.opacity=dirty?.035:.07;
    }
    if(evidenceMode)animations.forEach(animate=>animate(motion?time:0));
    const pulseAge=time-pulseTime;
    pulseRing.visible=pulseAge>=0&&pulseAge<1.8&&motion;
    if(pulseRing.visible){pulseRing.scale.setScalar(1+pulseAge*3);pulseRing.material.opacity=Math.max(0,.55-pulseAge*.3);}
    if(motion&&Math.floor(time*8)!==Math.floor((time-delta)*8))screenTextures.forEach(draw=>draw(time));
    particles.rotation.y=motion?time*.005:0;
    renderer.render(scene,camera);
    needsRender=false;
  }
  function renderOnce(instant=false) {
    if(disposed||!visible||document.hidden||!width||!height)return;
    if(!motion||instant)frameScene(.05,elapsed,true);
    else start();
  }
  function tick(now) {
    frame=0;if(disposed||!visible||document.hidden||!motion)return;
    const delta=lastTime?Math.min((now-lastTime)/1000,.05):1/60;lastTime=now;elapsed+=delta;
    frameScene(delta,elapsed);
    frame=requestAnimationFrame(tick);
  }
  function start(){if(!frame&&!disposed&&visible&&!document.hidden&&motion){lastTime=0;frame=requestAnimationFrame(tick);}}
  function stop(){if(frame)cancelAnimationFrame(frame);frame=0;lastTime=0;}
  function resize(){
    if(disposed)return;
    const rect=container.getBoundingClientRect();width=Math.max(1,Math.round(rect.width));height=Math.max(1,Math.round(rect.height));
    renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();cameraShift=NaN;needsRender=true;renderOnce();
  }
  function partAt(event) {
    const rect=canvas.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    pick.setFromCamera(pointer,camera);
    const hits=pick.intersectObjects(interactables,false);
    const hit=hits.find(item=>{let p=item.object;while(p){if(!p.visible)return false;p=p.parent;}return true;});
    return hit?.object.userData.part||'';
  }
  function handleDown(event) {
    if(event.button!==0)return;
    pointerDown={x:event.clientX,y:event.clientY,id:event.pointerId};
    drag={x:event.clientX,y:event.clientY,theta:orbit.targetTheta,phi:orbit.targetPhi,moved:false,type:event.pointerType};
    // Touch starts as a normal page gesture. Horizontal intention opts into orbit.
    if(event.pointerType!=='touch'){canvas.setPointerCapture(event.pointerId);canvas.style.cursor='grabbing';}
    lastInteraction=elapsed;
  }
  function handleMove(event) {
    if(!drag){canvas.style.cursor=partAt(event)?'pointer':'grab';return;}
    const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
    if(drag.type==='touch'&&!drag.moved){if(Math.abs(dy)>Math.abs(dx)+7){drag=null;return;}if(Math.abs(dx)<7)return;}
    if(Math.abs(dx)+Math.abs(dy)>6)drag.moved=true;
    if(drag.moved){focusedPart='';orbit.targetTheta=drag.theta-dx*.006;orbit.targetPhi=clamp(drag.phi-dy*.004,.17,1.52);needsRender=true;renderOnce();}
    lastInteraction=elapsed;
  }
  function handleUp(event) {
    if(pointerDown&&pointerDown.id===event.pointerId&&drag&&!drag.moved){const kind=partAt(event);if(kind){selectPart(kind);onSelect(kind);}}
    if(canvas.hasPointerCapture?.(event.pointerId))canvas.releasePointerCapture(event.pointerId);
    drag=null;pointerDown=null;canvas.style.cursor='grab';
  }
  function handleCancel(){drag=null;pointerDown=null;canvas.style.cursor='grab';}
  function handleVisibility(){if(document.hidden)stop();else{renderOnce();start();}}
  function handleMotionPreference(){setMotion(requestedMotion);}
  function handleContextLoss(event){event.preventDefault();stop();onError(new Error('WebGL context interrupted. Reload to restore the 3D scene.'));}
  canvas.addEventListener('pointerdown',handleDown);canvas.addEventListener('pointermove',handleMove);
  canvas.addEventListener('pointerup',handleUp);canvas.addEventListener('pointercancel',handleCancel);canvas.addEventListener('lostpointercapture',handleCancel);
  canvas.addEventListener('webglcontextlost',handleContextLoss);
  document.addEventListener('visibilitychange',handleVisibility);
  reducedMotion.addEventListener?.('change',handleMotionPreference);
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(container);
  const intersectionObserver=new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting!==false;if(visible){renderOnce();start();}else stop();},{rootMargin:'40px'});
  intersectionObserver.observe(container);

  function dispose(){
    if(disposed)return;disposed=true;stop();
    resizeObserver.disconnect();intersectionObserver.disconnect();
    document.removeEventListener('visibilitychange',handleVisibility);reducedMotion.removeEventListener?.('change',handleMotionPreference);
    canvas.removeEventListener('pointerdown',handleDown);canvas.removeEventListener('pointermove',handleMove);
    canvas.removeEventListener('pointerup',handleUp);canvas.removeEventListener('pointercancel',handleCancel);canvas.removeEventListener('lostpointercapture',handleCancel);
    canvas.removeEventListener('webglcontextlost',handleContextLoss);
    customDisposers.forEach(fn=>fn());resources.forEach(resource=>resource.dispose?.());renderer.dispose();canvas.remove();
  }
  resize();frameScene(1/60,0,true);start();
  queueMicrotask(()=>{if(!disposed)onReady({renderer:'WebGL',concept:true});});
  return {setState,selectPart,focusPart,setExploded,setEvidenceMode,setAutoRotate,setMotion,setView,pulse,zoom,resize,dispose};
}
