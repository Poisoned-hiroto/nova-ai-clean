const form = document.getElementById('chatForm');
const input = document.getElementById('prompt');
const messagesEl = document.getElementById('messages');
const welcome = document.getElementById('welcome');
const sendBtn = document.getElementById('sendBtn');
const toast = document.getElementById('toast');
const installBtn = document.getElementById('installBtn');
let conversation = [];
let deferredInstall = null;
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function renderText(text) {
  // Small safe formatter: escape HTML first, then format code and basic Markdown.
  let safe = escapeHtml(text);
  const blocks = [];
  safe = safe.replace(/```([\s\S]*?)```/g, (_, code) => {
    blocks.push('<pre><code>' + code.trim() + '</code></pre>');
    return `@@CODE${blocks.length-1}@@`;
  });
  safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');
  safe = safe.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  safe = safe.split(/\n{2,}/).map(p => p.startsWith('@@CODE') ? p : '<p>' + p.replace(/\n/g, '<br>') + '</p>').join('');
  safe = safe.replace(/@@CODE(\d+)@@/g, (_, i) => blocks[Number(i)]);
  return safe;
}
function addMessage(role, content, addActions = false) {
  welcome.hidden = true;
  const row = document.createElement('article');
  row.className = `message ${role}`;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? '●' : '✳';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = role === 'user' ? escapeHtml(content).replace(/\n/g, '<br>') : renderText(content);
  row.append(avatar, bubble);
  if (addActions) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const copy = document.createElement('button');
    copy.textContent = 'Copy response';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(content); showToast('Response copied'); }
      catch { showToast('Could not access clipboard'); }
    });
    actions.append(copy);
    bubble.append(actions);
  }
  messagesEl.append(row);
  document.getElementById('conversation').scrollTo({top: document.getElementById('conversation').scrollHeight, behavior:'smooth'});
  return {row, bubble};
}
function showTyping() {
  welcome.hidden = true;
  const row = document.createElement('article');
  row.className = 'message assistant';
  row.innerHTML = '<div class="avatar">✳</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>';
  messagesEl.append(row);
  document.getElementById('conversation').scrollTo({top: document.getElementById('conversation').scrollHeight, behavior:'smooth'});
  return row;
}
async function sendMessage(text) {
  const trimmed = text.trim();
  if (!trimmed || sendBtn.disabled) return;
  conversation.push({role:'user', content:trimmed});
  addMessage('user', trimmed);
  input.value = '';
  input.style.height = 'auto';
  sendBtn.disabled = true;
  const typing = showTyping();
  try {
    const response = await fetch('/api/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({messages:conversation})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    const reply = data.reply || 'I could not generate a response. Please try again.';
    conversation.push({role:'assistant', content:reply});
    typing.remove();
    addMessage('assistant', reply, true);
    try { sessionStorage.setItem('nova-history', JSON.stringify(conversation)); } catch {}
  } catch (err) {
    typing.remove();
    const errorText = `I couldn't reach the AI service. ${err.message || 'Check your connection and try again.'}`;
    addMessage('assistant', errorText, true);
    showToast('AI request failed');
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}
form.addEventListener('submit', e => { e.preventDefault(); sendMessage(input.value); });
input.addEventListener('input', () => { input.style.height='auto'; input.style.height=Math.min(input.scrollHeight,180)+'px'; });
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
document.querySelectorAll('[data-prompt]').forEach(btn => btn.addEventListener('click', () => sendMessage(btn.dataset.prompt)));
function resetChat() {
  conversation = [];
  messagesEl.innerHTML = '';
  welcome.hidden = false;
  try { sessionStorage.removeItem('nova-history'); } catch {}
  showToast('New conversation started');
}
document.getElementById('newChat').addEventListener('click', () => { resetChat(); document.getElementById('sidebar').classList.remove('open'); });
document.getElementById('clearChat').addEventListener('click', resetChat);
document.getElementById('mobileMenu').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferredInstall = e; installBtn.hidden = false; });
installBtn.addEventListener('click', async () => {
  if (!deferredInstall) { showToast('Use your browser menu and choose Add to Home screen'); return; }
  deferredInstall.prompt();
  await deferredInstall.userChoice;
  deferredInstall = null;
  installBtn.hidden = true;
});
window.addEventListener('appinstalled', () => showToast('NOVA AI installed'));
if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}
try {
  const saved = JSON.parse(sessionStorage.getItem('nova-history') || '[]');
  if (Array.isArray(saved) && saved.length) {
    conversation = saved;
    welcome.hidden = true;
    saved.forEach(m => addMessage(m.role, m.content, m.role === 'assistant'));
  }
} catch {}
