// ===== 全局 DOM 引用 =====
const orbStatus = document.getElementById('orbStatus');
const input = document.getElementById('input');
const l2dBubble = document.getElementById('l2dBubble');
const chatArea = document.getElementById('chatArea');

// ===== 消息气泡 =====
function addMessage(text, who, extraCls) {
  const div = document.createElement('div');
  div.className = 'msg ' + (who === 'user' ? 'msg-user' : who === 'tool' ? 'msg-tool' : 'msg-ai') + (extraCls ? ' ' + extraCls : '');
  div.textContent = text;
  chatArea.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
  return div;
}

// 立绘气泡(显示小暖当前说的句子)
function showL2dBubble(text) {
  if (!l2dBubble) return;
  if (text) {
    l2dBubble.textContent = text;
    l2dBubble.style.display = 'block';
  } else {
    l2dBubble.style.display = 'none';
  }
}

// ===== 对话请求 =====
async function getReply(text) {
  setStatus('思考中...', 'thinking');
  try {
    // 工具类任务(如爬虫)可能执行很久, 超时放宽到 10 分钟; 超时后释放锁, 语音不会永久卡住
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 600000);
    let res;
    try {
      res = await fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message: text, role: currentRole}), signal: ctrl.signal});
    } finally { clearTimeout(timer); }
    const data = await res.json();
    if (data.tool_used) addMessage('🔧 已调用工具处理', 'tool');
    addMessage(data.reply || '嗯嗯', 'ai');
    if (data.async && data.task_id) {
      // 后台任务: 简短播报一句, 然后轮询结果; 期间可以继续对话
      localStorage.setItem('pendingTask', data.task_id);
      if (voiceActive) speak('收到，我已在后台处理，弄好了马上告诉你。');
      pollTask(data.task_id);
      return;
    }
    await speak(data.reply || '嗯嗯');
  } catch (e) {
    setStatus('连接出错', '');
    setTimeout(() => { if (voiceActive) setStatus('我在听...', 'listening'); }, 1500);
  }
}

// 轮询后台任务结果, 完成后显示并语音播报
async function pollTask(taskId) {
  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    let d;
    try {
      const res = await fetch('/api/task_status?task_id=' + encodeURIComponent(taskId));
      d = await res.json();
    } catch (e) { continue; }
    if (d.status === 'unknown') {
      // 服务端重启/任务丢失: 不再等待
      localStorage.removeItem('pendingTask');
      return;
    }
    if (d.status === 'done' || d.status === 'error') {
      const result = d.reply || (d.status === 'done' ? '（任务已完成）' : '（任务执行出错）');
      addMessage(result, 'ai');
      showL2dBubble(result);
      localStorage.removeItem('pendingTask');
      // 等当前对话/播报结束后再播报结果, 避免与用户说话冲突
      const trySpeak = () => {
        if (isBusy || isSpeaking) { setTimeout(trySpeak, 1500); return; }
        if (voiceActive) speak(result);
      };
      trySpeak();
      return;
    }
  }
}

// ===== 文本输入 =====
async function sendText() {
  const text = input.value.trim();
  if (!text) return;
  if (isBusy) { console.log('对话进行中, 请稍候'); return; }
  input.value = '';
  addMessage(text, 'user');
  await getReply(text);
}

// ===== 逐句拆分(不依赖 lookbehind) =====
function splitSentences(text) {
  // 1) 按 句号/感叹号/问号(。！？!?～) 切分, 用捕获组保留标点
  const parts = text.split(/([。！？!?～])/);
  const sents = [];
  for (let i = 0; i < parts.length; i += 2) {
    const sentence = (parts[i] || '') + (parts[i + 1] || '');
    if (sentence.trim()) sents.push(sentence.trim());
  }
  // 2) 超过 20 字符的长句按逗号(，,、)二次切分
  const result = [];
  for (const sentence of sents) {
    if (sentence.length <= 20) { result.push(sentence); continue; }
    const chunks = sentence.split(/([，,、])/);
    let buf = '';
    for (let i = 0; i < chunks.length; i += 2) {
      const piece = (chunks[i] || '') + (chunks[i + 1] || '');
      if (buf && (buf + piece).length > 20) {
        result.push(buf.trim());
        buf = piece;
      } else {
        buf += piece;
      }
    }
    if (buf.trim()) result.push(buf.trim());
  }
  // 3) 过滤空句
  return result.filter(s => s.length > 0);
}

// 归一化文本用于回声比对: 去标点空白
function normalizeSpeech(s) {
  return (s || '').replace(/[\s，。.！!？?、：:；;~～—""''·…]/g, '');
}

// ===== 主动服务轮询(移植自Nolan): 到点的提醒/条件触发 -> 气泡+语音播报 =====
async function pollDue() {
  let d;
  try {
    const res = await fetch('/api/due');
    d = await res.json();
  } catch (e) { return; }
  const msgs = (d && d.messages) || [];
  for (const m of msgs) {
    const text = m.text || '';
    if (!text) continue;
    addMessage(text, 'ai');
    showL2dBubble(text);
    // 等当前对话/播报结束后再播, 避免打断用户正在说的话
    const trySpeak = () => {
      if (isBusy || isSpeaking) { setTimeout(trySpeak, 1500); return; }
      if (voiceActive) speak(text);
      else setTimeout(() => showL2dBubble(''), 6000);
    };
    trySpeak();
  }
}
setInterval(pollDue, 15000);
setTimeout(pollDue, 3000);