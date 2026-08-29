// ===== 语音模式: 本地 VAD + /api/stt(whisper) + /api/tts =====
let audioCtx = null, mediaRecorder = null, mediaStream = null;
let analyser = null;
let isRecording = false, isSpeaking = false, silentTimer = null;
let recordStart = 0;        // 本次录音开始时间(用于过滤噪音短闪)
let pushTalk = false;       // 按住说话模式
let pressTimer = null;      // 按住 vs 短按 判定定时器
let isBusy = false;        // 全局对话锁: 防止语音/文字并发导致声音重叠
let currentAudio = null;   // 当前播放的音频(挂断时可立即停止)
let vadInterval = null;
let audioChunks = [];
let spokenInterrupted = false;   // 用户说话打断当前播报
let currentSentenceFinish = null; // 当前句播放完成回调, 供打断时立即结束
let lastSpokenText = '';         // 最近一次播报的原文, 防止回声误触发
let lastText = '';               // 最近一次识别文本(用于过滤电视重复内容)
let lastTextAt = 0;
let recGen = 0;                  // 录音代数: 新录音开始时+1, 排队中的旧录音据此自我丢弃(防重复回复)

function setStatus(text, cls) {
  orbStatus.textContent = text;
  orbStatus.className = 'orb-status ' + (cls || '');
  setOrbState(cls || 'idle');
}

// ===== 提示音(Web Audio合成, 零延迟): 唤醒成功=升调叮咚 / 唤醒过期=降调 =====
function playChime(kind) {
  try {
    const ctx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    const seq = kind === 'fail' ? [523.3, 392] : [880, 1318.5];  // 咚叮 / 叮咚
    seq.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const t0 = ctx.currentTime + i * 0.13;
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(0.22, t0 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.12);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.13);
    });
  } catch (e) { console.log('提示音失败', e); }
}

function startVAD(stream) {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(stream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  clearInterval(vadInterval);
  vadInterval = setInterval(checkVolume, 100);
}

function checkVolume() {
  if (!voiceActive || pushTalk) return;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i];
  const avg = sum / data.length;
  const isLoud = avg > 15;   // 阈值降低, 说话小声也能触发
  if (isLoud && isSpeaking) { interruptSpeaking(); return; }  // 一开口就打断播报(OpenAI 式)
  if (isLoud && !isRecording) startRecording();
  if (!isLoud && isRecording) {
    if (!silentTimer) silentTimer = setTimeout(() => { stopRecording(); silentTimer = null; }, 900);
  } else if (isLoud && silentTimer) {
    clearTimeout(silentTimer); silentTimer = null;
  }
  // 录音超过 8 秒强制结束(电视/连续噪音会导致录音无限拉长, 拖慢识别)
  if (isRecording && Date.now() - recordStart > 8000) {
    clearTimeout(silentTimer); silentTimer = null;
    stopRecording();
  }
}

function startRecording() {
  isRecording = true;
  recGen++;
  recordStart = Date.now();
  audioChunks = [];
  mediaRecorder = new MediaRecorder(mediaStream);
  mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
  mediaRecorder.onstop = handleRecordingStop;
  mediaRecorder.start();
  setStatus('我在听...', 'listening');
}

async function stopRecording() {
  if (!isRecording) return;
  isRecording = false;
  if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
}

// 大数组分块转 base64, 避免 String.fromCharCode(...大数组) 爆调用栈
function bufToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

// ===== 唤醒词: 全句任意位置模糊匹配, 容忍STT转写偏差 =====
// 变体: 贾维斯/佳维斯/加维斯/假维斯/甲维斯/家维斯/javis/jarvis/jiavis 及 whisper 常见误听(加欸石碰/加威斯等)
const WAKE_CORE = '(?:贾维斯|佳维斯|加维斯|假维斯|甲维斯|家维斯|驾维斯|嫁维斯|加威斯|贾威斯|家威斯|加艾斯|贾维思|加维思|加欸石碰|javis|jarvis|jarves|jiavis|ji\\s?a\\s?vis)';
const WAKE_SUFFIX = '(?:\\s?(?:同学|童鞋|同雪))?';
const WAKE_RE = new RegExp(WAKE_CORE + WAKE_SUFFIX, 'i');

let woken = false;           // 是否处于免唤醒期
let wakeTimer = null;        // 免唤醒倒计时
const WAKE_HOLD_MS = 300000; // 唤醒保持 5 分钟（每次说话自动续期, 连续对话）

function resetWake() {
  woken = false;
  if (wakeTimer) { clearTimeout(wakeTimer); wakeTimer = null; }
}

function keepAwake() {
  woken = true;
  if (wakeTimer) clearTimeout(wakeTimer);
  wakeTimer = setTimeout(resetWake, WAKE_HOLD_MS);
}

// 在整句中搜索唤醒词(任意位置), 找到返回其后的指令(''=纯唤醒); 没找到返回 null
function matchWakeWord(text) {
  const t = (text || '').trim();
  if (!t) return null;
  const m = t.match(WAKE_RE);
  if (!m || m.index === undefined) return null;
  let rest = t.slice(m.index + m[0].length);
  rest = rest.replace(/^[，,。.！!？?、~～的嗯啊哦那就帮我请]\s*/, '').trim();
  return rest;
}

async function handleRecordingStop() {
  const myGen = recGen;   // 本段录音的代数
  // 若正忙(上一句还在处理/播报), 等待它结束再处理本次语音, 不再直接丢弃
  if (isBusy) {
    console.log('对话进行中, 等待结束后再处理本次语音...');
    for (let i = 0; i < 120 && isBusy; i++) {
      await new Promise(r => setTimeout(r, 500));
      // 等待期间用户又说了新话 → 本段是旧的, 自我丢弃防重复回复
      if (recGen !== myGen) { console.log('有更新录音排队, 丢弃本段旧录音'); return; }
    }
    if (isBusy) { console.log('等待超时, 本次语音已忽略'); return; }
  }
  // 噪音短闪(如电视声响)不足 0.4s, 直接丢弃不识别
  if (Date.now() - recordStart < 400) {
    recordStart = 0;
    return;
  }
  isBusy = true;
  try {
    const blob = new Blob(audioChunks, {type: 'audio/webm'});
    const buf = await blob.arrayBuffer();
    const b64 = bufToBase64(buf);
    try {
      const sttCtrl = new AbortController();
      const sttTimer = setTimeout(() => sttCtrl.abort(), 90000);
      let res;
      try {
        res = await fetch('/api/stt', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({audio: b64}), signal: sttCtrl.signal});
      } finally { clearTimeout(sttTimer); }
      const data = await res.json();
      const text = (data.text || '').trim();
      if (!text) { setStatus('我在听...', 'listening'); return; }
      console.log('[STT RESULT]', text);  // 调试：看识别结果
      if (lastSpokenText && normalizeSpeech(text) === normalizeSpeech(lastSpokenText)) return;  // 回声误触发, 忽略
      // 电视/环境音重复内容(10秒内同样的话)不再触发, 防止"牛头不对马嘴"
      if (lastText && normalizeSpeech(text) === lastText && Date.now() - lastTextAt < 10000) return;
      lastText = normalizeSpeech(text);
      lastTextAt = Date.now();
      setStatus('听到: ' + text, 'listening');  // 实时显示听到的内容
// 所有角色统一唤醒逻辑
      // 说"再见/拜拜/退下/挂断/睡吧/休息/闭嘴"结束免唤醒
      if (/再见|拜拜|退下|挂断|睡吧|休息|闭嘴/.test(text)) {
        resetWake();
        showL2dBubble('好的，再见。');
        if (voiceActive) await speak('好的，再见。');
        return;
      }
      const rest = matchWakeWord(text);
      if (rest === null) {
        // 非唤醒语句
        if (woken) {
          // 免唤醒期内：直接当指令
          await getReply(text);
          keepAwake();
        } else {
          playChime('fail');
          if (voiceActive) setStatus('未听到唤醒词', 'idle');
          showL2dBubble('喊我名字来唤醒我哦～');
        }
        return;
      }
      // 检测到唤醒词
      keepAwake();
      playChime('wake');
      if (!rest) {
        // 只喊了唤醒词
        const wakeHint = '在，我在听。要我做什么？';
        showL2dBubble(wakeHint);
        if (voiceActive) { await speak(wakeHint); setStatus('我在听...', 'listening'); }
        return;
      }
      await getReply(rest);
      keepAwake();  // 成功指令后刷新免唤醒计时
    } catch (e) {
      console.warn('STT失败', e);
      if (voiceActive) setStatus('我在听...', 'listening');
    }
  } finally {
    isBusy = false;
    if (voiceActive && !isSpeaking) {
      setStatus('我在听...', 'listening');
    }
  }
}

async function speak(text) {
  if (isSpeaking) { console.log('已在播放, 忽略重复请求'); return; }
  isSpeaking = true;
  spokenInterrupted = false;
  lastSpokenText = text || '';
  setStatus('说话中...', 'speaking');
  try {
    // 按句拆分(保留句末标点), 逐句依次显示+播放
    const sentences = splitSentences(text);
    console.log('[TTS] 待播放句子数:', sentences.length, sentences);
    let voiceMode = voiceActive;  // 记录本次回复开始时的模式
    for (const sentence of sentences) {
      if (voiceMode && !voiceActive) break;  // 语音中途挂断则立即停止
      if (voiceMode) {
        // 1) 先合成该句音频(带角色, 让克隆音色生效)
        const ttsCtrl = new AbortController();
        const ttsTimer = setTimeout(() => ttsCtrl.abort(), 60000);
        let res;
        try {
          res = await fetch('/api/tts', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: sentence, role: currentRole}), signal: ttsCtrl.signal});
        } finally { clearTimeout(ttsTimer); }
        if (!res.ok) {
          // TTS 暂不可用(如 502/限流): 本句起降级为只显示不发音, 不打断整段回复
          console.log('TTS 暂不可用, 降级为文字模式', res.status);
          voiceMode = false;
          showL2dBubble(sentence);
          await new Promise(r => setTimeout(r, Math.max(1200, sentence.length * 150)));
          continue;
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        // 2) 播放开始时才把这一句显示到人物旁边, 与说话同步
        await new Promise((resolve, reject) => {
          const audio = new Audio(url);
          currentAudio = audio;   // 记录当前音频, 挂断时可 stop
          let settled = false;
          const finish = (err) => {
            if (settled) return;
            settled = true;
            if (currentAudio === audio) currentAudio = null;
            if (currentSentenceFinish === finish) currentSentenceFinish = null;
            stopMouth();
            if (err) reject(err); else resolve();
          };
          currentSentenceFinish = finish;   // 打断时可立即结束本句
          audio.onended = () => finish();
          audio.onerror = () => finish(new Error('音频播放失败'));
          showL2dBubble(sentence);
          startMouth(audio);
          // play() 可能被浏览器拦截返回 rejected promise, 捕获避免说话状态挂起
          audio.play().catch(e => finish(e));
          // 兜底: 若 onended 因故不触发(自动播放拦截/音频被中断), 按音频时长+3s 自动结束, 防止说话状态永久挂起
          const durMs = (typeof audio.duration === 'number' && isFinite(audio.duration) && audio.duration > 0) ? audio.duration * 1000 : 15000;
          setTimeout(() => { try { audio.pause(); } catch (e) {} finish(); }, durMs + 3000);
        });
        URL.revokeObjectURL(url);
        if (spokenInterrupted) break;   // 用户说话打断: 不再念后续句子
      } else {
        // 未开启语音: 只依次显示在人物旁边, 按句长延时切换
        showL2dBubble(sentence);
        await new Promise(r => setTimeout(r, Math.max(1200, sentence.length * 150)));
      }
    }
  } catch (e) { console.log('播放失败', e); }
  isSpeaking = false;
  currentAudio = null;
  showL2dBubble('');
  stopMouth();
  if (voiceActive) setStatus('我在听...', 'listening');
}

// 语音 = 本地 VAD(检测说话) + 本地 whisper 识别(/api/stt), 完全离线, 不依赖谷歌/外网
async function startVoiceMode() {
  if (voiceActive) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus('浏览器不支持麦克风', '');
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  } catch (e) {
    setStatus('麦克风权限被拒，请允许后点光球重试', '');
    return;
  }
  voiceActive = true;
  startVAD(mediaStream);
  setStatus('我在听...', 'listening');
}

function stopVoiceMode() {
  if (!voiceActive) return;
  voiceActive = false;
  clearInterval(vadInterval); vadInterval = null;
  silentTimer = null;
  if (isRecording && mediaRecorder) { try { mediaRecorder.onstop = null; mediaRecorder.stop(); } catch (e) {} }
  isRecording = false;
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  if (audioCtx) { try { audioCtx.close(); } catch (e) {} audioCtx = null; }
  // 立即停止正在播放的语音, 防止挂断后声音还在响
  if (currentAudio) { try { currentAudio.pause(); } catch (e) {} currentAudio = null; }
  isSpeaking = false; isBusy = false;
  spokenInterrupted = false;
  currentSentenceFinish = null;
  stopMouth();
  showL2dBubble('');
  setStatus('已挂断', 'idle');
}

// 打断: 用户在说话时, 立即停掉当前播报
function interruptSpeaking() {
  if (!isSpeaking && !currentAudio) return;
  spokenInterrupted = true;
  if (currentAudio) { try { currentAudio.pause(); currentAudio.currentTime = 0; } catch (e) {} currentAudio = null; }
  if (currentSentenceFinish) { const f = currentSentenceFinish; currentSentenceFinish = null; try { f(); } catch (e) {} }
  isSpeaking = false;
  stopMouth();
  showL2dBubble('');
  if (voiceActive) setStatus('我在听...', 'listening');
}