// ===== 角色切换 / 收藏 =====
let currentRole = 'jarvis';  // 默认贾维斯
const topTitle = document.getElementById('topTitle');
const topDesc = document.getElementById('topDesc');
const favList = document.getElementById('favList');
const favModal = document.getElementById('favModal');

// 收藏(简单版: localStorage 记录)
let favRoles = JSON.parse(localStorage.getItem('favRoles') || '[]');
const favBtn = document.getElementById('favBtn');

function isFav(role) { return favRoles.includes(role); }
function toggleFav(role) {
  const i = favRoles.indexOf(role);
  if (i >= 0) favRoles.splice(i, 1); else favRoles.push(role);
  localStorage.setItem('favRoles', JSON.stringify(favRoles));
  renderFavList();
  updateFavBtn();
}
function updateFavBtn() {
  favBtn.textContent = isFav(currentRole) ? '★' : '☆';
  favBtn.style.color = isFav(currentRole) ? 'rgba(255,200,80,.9)' : '';
}
favBtn.addEventListener('click', () => { renderFavList(); favModal.classList.add('show'); });
favModal.addEventListener('click', e => { if (e.target === favModal) favModal.classList.remove('show'); });

async function loadPersonas() {
  try {
    const res = await fetch('/api/personas');
    const personas = await res.json();
    window._personas = personas;
    renderFavList();
    // 初始化当前角色: 标题/副标题 + 开场白
    await switchPersona(currentRole);
  } catch (e) { console.log('加载角色失败', e); }
}

function renderFavList() {
  const personas = window._personas || [];
  favList.innerHTML = personas.map(p => `
    <div class="fav-item ${p.id === currentRole ? 'active' : ''}" onclick="switchPersona('${p.id}')">
      <div class="fav-avatar">${(p.name || '?').slice(0, 1)}</div>
      <div class="fav-info"><b>${p.name}</b><span>${p.desc || ''}</span></div>
      <span class="fav-star" onclick="event.stopPropagation();toggleFav('${p.id}')">${isFav(p.id) ? '★' : '☆'}</span>
    </div>`).join('');
}

async function switchPersona(role) {
  currentRole = role;
  renderFavList();
  updateFavBtn();
  favModal.classList.remove('show');  // 选完自动关闭
  // 保留历史: 切回该角色时恢复并展示之前的对话(记忆持久化)
  chatArea.querySelectorAll('.msg').forEach(m => m.remove());
  try {
    const hr = await fetch('/api/history?role=' + encodeURIComponent(role));
    const hd = await hr.json();
    if (hd && hd.messages) {
      for (const m of hd.messages) {
        const who = (m.role === 'user') ? 'user' : 'ai';
        addMessage(m.content, who);
      }
    }
  } catch (e) { console.log('历史加载失败', e); }
  try {
    const res = await fetch('/api/persona?role=' + encodeURIComponent(role));
    const data = await res.json();
    topTitle.textContent = data.name;
    topDesc.textContent = data.desc;
    document.title = data.name + ' - AI 女友';
    addMessage(data.greeting, 'ai');
  } catch (e) { console.log('切换角色失败', e); }
}

function randomPersona() {
  const personas = window._personas || [];
  if (!personas.length) return;
  const pool = personas.filter(p => p.id !== currentRole);
  const pick = pool.length ? pool : personas;
  switchPersona(pick[Math.floor(Math.random() * pick.length)].id);
}

document.getElementById('randomBtn').addEventListener('click', randomPersona);
loadPersonas();