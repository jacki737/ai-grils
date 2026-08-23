// ===== 左侧金暖色缠绕光球 + 星点特效 =====
const particleCanvas = document.getElementById('particleCanvas');
const pctx = particleCanvas.getContext('2d');
let orbState = 'idle';
let audioLevel = 0;
let voiceActive = false;

function resizeParticleCanvas() {
  particleCanvas.width = window.innerWidth;
  particleCanvas.height = window.innerHeight;
}
resizeParticleCanvas();

// 光球中心(页面正中)
function orbCX() { return particleCanvas.width * 0.50; }
function orbCY() { return particleCanvas.height * 0.50; }
function orbRadius() { return Math.min(particleCanvas.width, particleCanvas.height) * 0.24; }

// 缠绕线条参数(密集随机曲线)
const LINE_COUNT = 250;
const lines = [];
for (let i = 0; i < LINE_COUNT; i++) {
  const angle = Math.random() * Math.PI * 2;
  const r1 = 0.1 + Math.random() * 0.9;
  const r2 = 0.1 + Math.random() * 0.9;
  const a1 = angle + (Math.random() - 0.5) * 1.5;
  const a2 = angle + (Math.random() - 0.5) * 1.5 + (Math.random() - 0.5) * 1.0;
  const cp = Math.random() * Math.PI * 2;
  lines.push({
    r1, r2, a1, a2, cp,
    width: 0.5 + Math.random() * 2.0,
    alpha: 0.4 + Math.random() * 0.55,
    speed: 0.0003 + Math.random() * 0.001,
    phase: Math.random() * Math.PI * 2,
  });
}

// 光球外围飞舞的星点
const SPARKLE_COUNT = 400;
const sparkles = [];
for (let i = 0; i < SPARKLE_COUNT; i++) {
  const angle = Math.random() * Math.PI * 2;
  const dist = 0.6 + Math.random() * 0.65;
  sparkles.push({
    angle,
    dist,
    speed: 0.0005 + Math.random() * 0.003,
    size: 0.6 + Math.random() * 1.5,
    alpha: 0.4 + Math.random() * 0.55,
    twinkle: Math.random() * Math.PI * 2,
    twinkleSpeed: 1.0 + Math.random() * 3.0,
  });
}

// 全屏微弱散星
const DUST_COUNT = 180;
const dusts = [];
for (let i = 0; i < DUST_COUNT; i++) {
  dusts.push({
    x: Math.random() * particleCanvas.width,
    y: Math.random() * particleCanvas.height,
    size: 0.3 + Math.random() * 0.5,
    alpha: 0.08 + Math.random() * 0.18,
    twinkle: Math.random() * Math.PI * 2,
    twinkleSpeed: 0.3 + Math.random() * 1.0,
  });
}

// 暖金色调
const STATE_COLORS = {
  speaking:  { r: 255, g: 200, b: 140 },
  listening: { r: 220, g: 210, b: 180 },
  thinking:  { r: 255, g: 220, b: 150 },
  idle:      { r: 235, g: 210, b: 170 },
};
let currentColor = { r: 235, g: 210, b: 170 };
let targetColor = { r: 255, g: 200, b: 120 };

function setOrbState(state) {
  orbState = state || 'idle';
  targetColor = STATE_COLORS[orbState] || STATE_COLORS.idle;
}

function drawOrb(cr, cg, cb, breathe, t) {
  const cx = orbCX(), cy = orbCY(), R = orbRadius();
  // 外层柔光晕
  const outerGlow = pctx.createRadialGradient(cx, cy, 0, cx, cy, R * 2.2);
  outerGlow.addColorStop(0, `rgba(${cr}, ${cg}, ${cb}, ${0.25 * breathe})`);
  outerGlow.addColorStop(0.35, `rgba(${cr}, ${cg}, ${cb}, ${0.08 * breathe})`);
  outerGlow.addColorStop(0.7, `rgba(${cr}, ${cg}, ${cb}, ${0.02 * breathe})`);
  outerGlow.addColorStop(1, `rgba(${cr}, ${cg}, ${cb}, 0)`);
  pctx.beginPath();
  pctx.arc(cx, cy, R * 2.2, 0, Math.PI * 2);
  pctx.fillStyle = outerGlow;
  pctx.fill();
  // 内层亮核
  const innerGlow = pctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.6);
  innerGlow.addColorStop(0, `rgba(255, 248, 230, ${0.7 * breathe})`);
  innerGlow.addColorStop(0.3, `rgba(${cr}, ${cg}, ${cb}, ${0.4 * breathe})`);
  innerGlow.addColorStop(0.7, `rgba(${cr}, ${cg}, ${cb}, ${0.1 * breathe})`);
  innerGlow.addColorStop(1, `rgba(${cr}, ${cg}, ${cb}, 0)`);
  pctx.beginPath();
  pctx.arc(cx, cy, R * 0.6, 0, Math.PI * 2);
  pctx.fillStyle = innerGlow;
  pctx.fill();
  // 中心亮点
  const bright = pctx.createRadialGradient(cx, cy, 0, cx, cy, 8);
  bright.addColorStop(0, `rgba(255,255,240,${0.9 * breathe})`);
  bright.addColorStop(1, `rgba(255,255,240,0)`);
  pctx.beginPath();
  pctx.arc(cx, cy, 8, 0, Math.PI * 2);
  pctx.fillStyle = bright;
  pctx.fill();
  // 缠绕线条
  lines.forEach(line => {
    line.phase += line.speed;
    const a1 = line.a1 + Math.sin(line.phase) * 0.3;
    const a2 = line.a2 + Math.cos(line.phase * 0.7) * 0.3;
    const cpA = line.cp + line.phase * 0.5;
    const x1 = cx + Math.cos(a1) * R * line.r1;
    const y1 = cy + Math.sin(a1) * R * line.r1;
    const x2 = cx + Math.cos(a2) * R * line.r2;
    const y2 = cy + Math.sin(a2) * R * line.r2;
    const cpx = cx + Math.cos(cpA) * R * (line.r1 + line.r2) * 0.35;
    const cpy = cy + Math.sin(cpA) * R * (line.r1 + line.r2) * 0.35;
    pctx.beginPath();
    pctx.moveTo(x1, y1);
    pctx.quadraticCurveTo(cpx, cpy, x2, y2);
    pctx.strokeStyle = `rgba(${cr}, ${cg}, ${cb}, ${line.alpha * breathe})`;
    pctx.lineWidth = line.width;
    pctx.stroke();
  });
  // Voice mode: 挂断徽章嵌在光球中心(原代码放错位置从未生效, 此处修复)
  if (voiceActive) {
    const hx = cx, hy = cy, hr = Math.max(14, R * 0.16);
    pctx.beginPath();
    pctx.arc(hx, hy, hr, 0, Math.PI * 2);
    pctx.fillStyle = 'rgba(200,50,50,0.75)';
    pctx.fill();
    pctx.strokeStyle = 'rgba(255,255,255,0.9)';
    pctx.lineWidth = 2;
    pctx.stroke();
    pctx.fillStyle = '#fff';
    pctx.font = (hr * 1.15).toFixed(0) + 'px sans-serif';
    pctx.textAlign = 'center';
    pctx.textBaseline = 'middle';
    pctx.fillText('📞', hx, hy + 1);
  }
}

function drawSparkles(cr, cg, cb, breathe, dt) {
  const cx = orbCX(), cy = orbCY(), R = orbRadius();
  sparkles.forEach(s => {
    s.angle += s.speed;
    s.twinkle += s.twinkleSpeed * dt;
    const d = s.dist * R;
    const x = cx + Math.cos(s.angle) * d;
    const y = cy + Math.sin(s.angle) * d;
    const tw = 0.5 + 0.5 * Math.sin(s.twinkle);
    const a = s.alpha * tw * breathe;
    if (a < 0.02) return;
    pctx.beginPath();
    pctx.arc(x, y, s.size, 0, Math.PI * 2);
    pctx.fillStyle = `rgba(${cr}, ${cg}, ${cb}, ${a})`;
    pctx.fill();
  });
}

function drawDusts(cr, cg, cb, breathe, dt) {
  dusts.forEach(d => {
    d.twinkle += d.twinkleSpeed * dt;
    const tw = 0.3 + 0.7 * Math.sin(d.twinkle);
    const a = d.alpha * tw * breathe;
    if (a < 0.02) return;
    pctx.beginPath();
    pctx.arc(d.x, d.y, d.size, 0, Math.PI * 2);
    pctx.fillStyle = `rgba(${cr}, ${cg}, ${cb}, ${a})`;
    pctx.fill();
  });
}

let lastTime = performance.now();
function animateParticles() {
  const now = performance.now();
  const dt = (now - lastTime) / 1000;
  lastTime = now;
  currentColor.r += (targetColor.r - currentColor.r) * 0.05;
  currentColor.g += (targetColor.g - currentColor.g) * 0.05;
  currentColor.b += (targetColor.b - currentColor.b) * 0.05;
  const cr = Math.round(currentColor.r), cg = Math.round(currentColor.g), cb = Math.round(currentColor.b);
  const breathe = 0.85 + Math.sin(now / 5000) * 0.15;

  pctx.clearRect(0, 0, particleCanvas.width, particleCanvas.height);
  drawOrb(cr, cg, cb, breathe, now / 1000);
  drawSparkles(cr, cg, cb, breathe, dt);
  drawDusts(cr, cg, cb, breathe, dt);
  requestAnimationFrame(animateParticles);
}
animateParticles();

particleCanvas.addEventListener('click', () => {
  if (voiceActive) stopVoiceMode(); else startVoiceMode();
});

window.addEventListener('resize', () => {
  const oldW = particleCanvas.width, oldH = particleCanvas.height;
  resizeParticleCanvas();
  dusts.forEach(d => {
    d.x *= particleCanvas.width / oldW;
    d.y *= particleCanvas.height / oldH;
  });
});