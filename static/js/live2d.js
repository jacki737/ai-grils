// ===== Live2D 立绘(shizuku) + 说话口型 =====
// 调优参数: 改这里的数字即可微调
const L2D_CFG = {
  fitScale: 0.95,     // 立绘适配容器后的整体缩放(小于1更小)
  posY: 4,            // 立绘底部距容器底部的像素偏移
  mouthInterval: 110, // 口型刷新间隔 ms
  mouthStep: 2.0,     // 每个刷新周期的相位增量, 越大口型越快(默认约 0.35s 开合一次)
  walkSpeed: 2.4,
  walkAmp: 7.0,
  walkArm: 25.0,
  walkLift: 10.0,
  walkShift: 30.0,
  mouthAmp: 0.8       // 口型张开幅度 0~1
};
let l2dModel = null;
let l2dReady = false;
let mouthTimer = null;
let walkTimer = null;
let walkBaseX = 0, walkBaseY = 0;

function initLive2D() {
  const canvas = document.getElementById('l2dCanvas');
  if (!canvas || !window.PIXI || !PIXI.live2d) return;
  const container = canvas.parentElement;
  const cw = container.clientWidth || 300;
  const ch = container.clientHeight || 400;
  const app = new PIXI.Application({
    width: cw, height: ch,
    backgroundAlpha: 0,
    transparent: true,
    view: canvas,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2)
  });
  PIXI.live2d.Live2DModel.from('/static/live2d/model/Haru/Haru.model3.json')
    .then(model => {
      l2dModel = model;
      model.anchor.set(0.5, 1);
      model.scale.set(1);
      let mw = 600, mh = 800;
      try {
        const b = model.getLocalBounds();
        if (b.width > 0 && b.height > 0) { mw = b.width; mh = b.height; }
      } catch (e) {}
      const s = Math.min(cw / mw, ch / mh) * L2D_CFG.fitScale;
      model.scale.set(s);
      model.x = cw / 2;
      model.y = ch - L2D_CFG.posY;
      app.stage.addChild(model);
      canvas.style.display = 'block';
      l2dReady = true;
      // Live2D 就绪后隐藏静态立绘
      const spriteImg = document.getElementById('spriteImg');
      if (spriteImg) spriteImg.style.display = 'none';
      walkBaseX = model.x;
      walkBaseY = model.y;
      stopIdleMotion();
      startWalk();
    })
    .catch(e => console.warn('Live2D 加载失败, 继续使用静态立绘', e));
}

const MOUTH_PARAM_IDS = ['ParamMouthOpenY', 'PARAM_MOUTH_OPEN_Y'];
let mouthParamId = '';
function setLive2dParam(id, v) {
  if (!l2dModel) return;
  try {
    const cm = l2dModel.internalModel.coreModel;
    const setter = cm.setParameterValueById || cm.setParamFloat;
    if (setter) setter.call(cm, id, v);
  } catch (e) {}
}
function setMouthOpen(v) {
  if (mouthParamId) { setLive2dParam(mouthParamId, v); return; }
  for (const id of MOUTH_PARAM_IDS) {
    try {
      const cm = l2dModel.internalModel.coreModel;
      const setter = cm.setParameterValueById || cm.setParamFloat;
      if (setter) { setter.call(cm, id, v); mouthParamId = id; return; }
    } catch (e) {}
  }
}
function startMouth(audio) {
  if (!l2dModel) return;
  stopMouth();
  // prefer driving mouth by real audio volume, fallback to rhythm
  if (audioCtx && audio && audioCtx.createMediaElementSource) {
    try {
      const src = audioCtx.createMediaElementSource(audio);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      analyser.connect(audioCtx.destination);
      const buf = new Uint8Array(analyser.fftSize);
      let smoothOpen = 0;
      mouthTimer = setInterval(() => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / buf.length);
        const target = Math.min(1, rms * 7) * L2D_CFG.mouthAmp;
        smoothOpen += (target - smoothOpen) * 0.45;
        setMouthOpen(smoothOpen);
      }, 40);
      return;
    } catch (e) { console.warn('volume mouth failed, use rhythm', e); }
  }
  let t = 0;
  mouthTimer = setInterval(() => {
    t += L2D_CFG.mouthStep;
    const v = (Math.sin(t) + 1) / 2;   // 0~1 speaking rhythm
    setMouthOpen(v * L2D_CFG.mouthAmp);
  }, L2D_CFG.mouthInterval);
}

function stopMouth() {
  if (mouthTimer) { clearInterval(mouthTimer); mouthTimer = null; }
  setMouthOpen(0);
}

function stopIdleMotion() {
  try {
    const mm = (l2dModel.internalModel && l2dModel.internalModel.motionManager) || l2dModel.motionManager;
    if (mm && mm.stopAllMotions) mm.stopAllMotions();
  } catch (e) {}
}

function startWalk() {
  if (!l2dModel) return;
  stopWalk();
  const t0 = performance.now();
  walkTimer = setInterval(() => {
    const t = (performance.now() - t0) / 1000;
    const step = Math.sin(t * L2D_CFG.walkSpeed);
    setLive2dParam('ParamBodyAngleZ', step * L2D_CFG.walkAmp);
    setLive2dParam('ParamBodyAngleX', Math.sin(t * L2D_CFG.walkSpeed + 1.1) * L2D_CFG.walkAmp * 0.4);
    setLive2dParam('ParamArmLA', step * L2D_CFG.walkArm);
    setLive2dParam('ParamArmRA', -step * L2D_CFG.walkArm);
    setLive2dParam('ParamBreath', 0.5 + Math.sin(t * 1.2) * 0.25);
    const blinkT = (t % 3.5);
    const blink = blinkT < 0.15 ? Math.max(0, 1 - blinkT / 0.15) : 1;
    setLive2dParam('ParamEyeLOpen', blink);
    setLive2dParam('ParamEyeROpen', blink);
    l2dModel.y = walkBaseY - Math.abs(step) * L2D_CFG.walkLift;
    l2dModel.x = walkBaseX + Math.sin(t * L2D_CFG.walkSpeed * 0.5) * L2D_CFG.walkShift;
  }, 50);
}

function stopWalk() {
  if (walkTimer) { clearInterval(walkTimer); walkTimer = null; }
}