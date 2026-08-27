// ===== 设置面板(API Key / 角色管理) =====
const settingsModal = document.getElementById('settingsModal');
document.getElementById('settingsBtn').addEventListener('click', () => {
  settingsModal.classList.add('show');
  loadSettings();
  renderPersonaAdmin();
});
settingsModal.addEventListener('click', e => { if (e.target === settingsModal) settingsModal.classList.remove('show'); });

// 左侧导航切换
document.querySelectorAll('.settings-nav').forEach(nav => {
  nav.addEventListener('click', () => {
    document.querySelectorAll('.settings-nav').forEach(n => n.classList.remove('active'));
    nav.classList.add('active');
    document.querySelectorAll('.settings-tab').forEach(t => t.style.display = 'none');
    const tab = document.getElementById('tab-' + nav.dataset.tab);
    if (tab) tab.style.display = '';
  });
});

// 返回按钮(已从布局移除, 保留逻辑): 清空聊天区回到初始
const backBtn = document.getElementById('backBtn');
if (backBtn) backBtn.addEventListener('click', () => {
  chatArea.querySelectorAll('.msg').forEach(m => m.remove());
  switchPersona(currentRole);
});

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const d = await res.json();
    // 只显示是否已配置(不回显明文)
    const parts = [];
    parts.push(d.mimo_key ? 'MiMo ✓' : 'MiMo ✗');
    parts.push(d.dashscope_key ? 'DashScope ✓' : 'DashScope ✗');
    parts.push(d.tool_key ? 'Tool ✓' : 'Tool ✗');
    parts.push(d.vision_key ? 'Vision ✓' : 'Vision ✗');
    document.getElementById('tokenStatus').textContent = parts.join('  ');
  } catch (e) {}
}

async function saveTokens() {
  const body = {};
  const dk = document.getElementById('setDeepseekKey')?.value?.trim();
  const ak = document.getElementById('setDashscopeKey')?.value?.trim();
  const asr = document.getElementById('setDashscopeAsrKey')?.value?.trim();
  const tk = document.getElementById('setToolKey')?.value?.trim();
  const vk = document.getElementById('setVisionKey')?.value?.trim();
  if (dk) body.mimo_key = dk;
  if (ak) body.dashscope_key = ak;
  if (asr) body.dashscope_asr_key = asr;
  if (tk) body.tool_key = tk;
  if (vk) body.vision_key = vk;
  if (!Object.keys(body).length) { document.getElementById('tokenStatus').textContent = '没有输入'; return; }
  try {
    const res = await fetch('/api/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const d = await res.json();
    document.getElementById('tokenStatus').textContent = d.ok ? '✅ 已保存' : '保存失败';
    // 清空输入框
    ['setDeepseekKey','setDashscopeKey','setDashscopeAsrKey','setToolKey','setVisionKey'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    // 刷新状态
    loadSettings();
  } catch (e) { document.getElementById('tokenStatus').textContent = '保存失败'; }
}

async function renderPersonaAdmin() {
  try {
    const res = await fetch('/api/personas');
    const personas = await res.json();
    const box = document.getElementById('personaAdminList');
    box.innerHTML = personas.map(p => `
      <div class="persona-card">
        <div class="fav-avatar">${(p.name || '?').slice(0, 1)}</div>
        <div class="fav-info">
          <b>${p.name}</b>
          <span>${p.id}${p.likes ? ' · ❤️' + p.likes.slice(0, 10) : ''}</span>
        </div>
        <div class="ops">
          <button onclick="editPersona('${p.id}')" title="编辑">✏️</button>
          <button onclick="deletePersona('${p.id}')" title="删除">🗑</button>
        </div>
      </div>`).join('');
  } catch (e) {}
}

async function editPersona(role) {
  try {
    const res = await fetch('/api/persona/' + encodeURIComponent(role));
    const d = await res.json();
    document.getElementById('pfRole').value = role;
    document.getElementById('pfName').value = d.name;
    document.getElementById('pfDesc').value = d.desc;
    document.getElementById('pfGreeting').value = d.greeting || '';
    document.getElementById('pfSystem').value = d.system || '';
    document.getElementById('pfLikes').value = d.likes || '';
    const vSel = document.getElementById('pfVoice');
    const vCus = document.getElementById('pfVoiceCustom');
    if (Array.from(vSel.options).some(o => o.value === d.voice)) {
      vSel.value = d.voice;
    } else if (d.voice) {
      vSel.value = 'custom';
      vCus.value = d.voice;
    } else {
      vSel.value = '';
      vCus.value = '';
    }
    document.getElementById('personaStatus').textContent = '已载入 ' + role;
  } catch (e) {}
}

function clearPersonaForm() {
  ['pfRole','pfName','pfDesc','pfGreeting','pfSystem','pfLikes','pfVoiceCustom'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('pfVoice').value = '';
  document.getElementById('personaStatus').textContent = '';
}

async function savePersonaForm() {
  const g = id => document.getElementById(id).value.trim();
  const role = g('pfRole'), name = g('pfName');
  if (!role || !name) { document.getElementById('personaStatus').textContent = '角色 ID 和名称必填'; return; }
  let voice = document.getElementById('pfVoice').value;
  if (voice === 'custom') voice = g('pfVoiceCustom');
  const body = {
    id: role, name,
    desc: g('pfDesc'), greeting: g('pfGreeting'),
    system: g('pfSystem'), likes: g('pfLikes'), voice,
  };
  try {
    const res = await fetch('/api/persona/save', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const d = await res.json();
    document.getElementById('personaStatus').textContent = d.ok ? `✅ 已保存: ${d.name}` : '保存失败';
    await renderPersonaAdmin();
    await loadPersonas();   // 刷新右侧下拉框
  } catch (e) { document.getElementById('personaStatus').textContent = '保存失败'; }
}

async function deletePersona(role) {
  if (!confirm(`确定删除角色 ${role} 吗？`)) return;
  try {
    const res = await fetch('/api/persona/' + encodeURIComponent(role), { method: 'DELETE' });
    const d = await res.json();
    document.getElementById('personaStatus').textContent = d.ok ? `🗑 已删除 ${role}` : (d.error || '删除失败');
    await renderPersonaAdmin();
    await loadPersonas();
  } catch (e) {}
}
