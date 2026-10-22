
const form = document.getElementById('chatForm');
const input = document.getElementById('prompt');
const messagesEl = document.getElementById('messages');
const welcome = document.getElementById('welcome');
const sendBtn = document.getElementById('sendBtn');
const toast = document.getElementById('toast');
const installBtn = document.getElementById('installBtn');

let conversation = [];
let activeChatId = localStorage.getItem('nova-active-chat') || null;
let deferredInstall = null;
let toastTimer;
let isLoadingChat = false;

function getGuestId() {
  let id = localStorage.getItem('nova-guest-id');

  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem('nova-guest-id', id);
  }

  return id;
}

const guestId = getGuestId();

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[c]));
}

function renderText(text) {
  let safe = escapeHtml(text);
  const blocks = [];

  safe = safe.replace(/```([\s\S]*?)```/g, (_, code) => {
    blocks.push('<pre><code>' + code.trim() + '</code></pre>');
    return `@@CODE${blocks.length - 1}@@`;
  });

  safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');
  safe = safe.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  safe = safe.split(/\n{2,}/).map(p =>
    p.startsWith('@@CODE')
      ? p
      : '<p>' + p.replace(/\n/g, '<br>') + '</p>'
  ).join('');

  return safe.replace(/@@CODE(\d+)@@/g, (_, i) => blocks[Number(i)]);
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

  bubble.innerHTML = role === 'user'
    ? escapeHtml(content).replace(/\n/g, '<br>')
    : renderText(content);

  row.append(avatar, bubble);

  if (addActions) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';

    const copy = document.createElement('button');
    copy.textContent = 'Copy response';

    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(content);
        showToast('Response copied');
      } catch {
        showToast('Could not access clipboard');
      }
    });

    actions.append(copy);
    bubble.append(actions);
  }

  messagesEl.append(row);

  document.getElementById('conversation').scrollTo({
    top: document.getElementById('conversation').scrollHeight,
    behavior: 'smooth'
  });

  return { row, bubble };
}

function showTyping() {
  welcome.hidden = true;

  const row = document.createElement('article');
  row.className = 'message assistant';
  row.innerHTML =
    '<div class="avatar">✳</div>' +
    '<div class="bubble"><div class="typing">' +
    '<span></span><span></span><span></span></div></div>';

  messagesEl.append(row);

  document.getElementById('conversation').scrollTo({
    top: document.getElementById('conversation').scrollHeight,
    behavior: 'smooth'
  });

  return row;
}

async function apiPost(payload) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ guestId, ...payload })
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }

  return data;
}

async function createChat() {
  const data = await apiPost({ action: 'create' });

  activeChatId = data.chatId;
  localStorage.setItem('nova-active-chat', activeChatId);

  conversation = [];
  renderConversation();
  await refreshChatList();

  return activeChatId;
}

function renderConversation() {
  messagesEl.innerHTML = '';
  welcome.hidden = conversation.length > 0;

  conversation.forEach(message => {
    addMessage(
      message.role,
      message.content,
      message.role === 'assistant'
    );
  });
}

async function sendMessage(text) {
  const trimmed = text.trim();

  if (!trimmed || sendBtn.disabled || isLoadingChat) return;

  sendBtn.disabled = true;
  input.value = '';
  input.style.height = 'auto';

  let typing;

  try {
    // Create a database chat only when the user first sends a message.
    if (!activeChatId) {
      await createChat();
    }

    conversation.push({ role: 'user', content: trimmed });
    addMessage('user', trimmed);

    typing = showTyping();

    const data = await apiPost({
      action: 'chat',
      chatId: activeChatId,
      messages: conversation
    });

    const reply = data.reply ||
      'I could not generate a response. Please try again.';

    conversation.push({ role: 'assistant', content: reply });

    typing.remove();
    typing = null;

    addMessage('assistant', reply, true);

    // MongoDB is the persistent history; this is only a local fallback.
    try {
      sessionStorage.setItem('nova-history', JSON.stringify(conversation));
    } catch {}

    await refreshChatList();

  } catch (err) {
    if (typing) typing.remove();

    // If a request fails, preserve the unsent conversation locally.
    try {
      sessionStorage.setItem('nova-history', JSON.stringify(conversation));
    } catch {}

    addMessage(
      'assistant',
      `I couldn't complete the request. ${err.message || 'Please try again.'}`,
      true
    );

    showToast('Request failed');
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

async function loadChat(chatId) {
  if (isLoadingChat || sendBtn.disabled) return;

  isLoadingChat = true;

  try {
    const data = await apiPost({
      action: 'load',
      chatId
    });

    activeChatId = data.chatId;
    localStorage.setItem('nova-active-chat', activeChatId);

    conversation = Array.isArray(data.messages) ? data.messages : [];

    try {
      sessionStorage.setItem('nova-history', JSON.stringify(conversation));
    } catch {}

    renderConversation();
    await refreshChatList();

    document.getElementById('sidebar').classList.remove('open');
  } catch (err) {
    showToast(err.message || 'Could not load chat');
  } finally {
    isLoadingChat = false;
  }
}

async function deleteChat(chatId) {
  if (!confirm('Delete this conversation permanently?')) return;

  try {
    await apiPost({
      action: 'delete',
      chatId
    });

    if (activeChatId === chatId) {
      activeChatId = null;
      localStorage.removeItem('nova-active-chat');
      conversation = [];
      renderConversation();

      try {
        sessionStorage.removeItem('nova-history');
      } catch {}
    }

    await refreshChatList();
    showToast('Conversation deleted');
  } catch (err) {
    showToast(err.message || 'Could not delete chat');
  }
}

function createHistorySection() {
  const sidebar = document.getElementById('sidebar');
  let section = document.getElementById('novaChatHistory');

  if (!section) {
    section = document.createElement('section');
    section.id = 'novaChatHistory';
    section.innerHTML = `
      <h3 class="nova-history-heading">Recent chats</h3>
      <div id="novaChatList"></div>
    `;

    sidebar.appendChild(section);
  }

  return section;
}

async function refreshChatList() {
  const section = createHistorySection();
  const list = section.querySelector('#novaChatList');

  try {
    const data = await apiPost({ action: 'list' });
    list.innerHTML = '';

    if (!data.chats || data.chats.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'nova-history-empty';
      empty.textContent = 'Your saved chats will appear here.';
      list.appendChild(empty);
      return;
    }

    data.chats.forEach(chat => {
      const item = document.createElement('div');
      item.className = 'nova-history-item';

      if (chat.chatId === activeChatId) {
        item.classList.add('active');
      }

      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'nova-history-open';
      open.textContent = chat.title || 'New chat';
      open.title = chat.title || 'New chat';
      open.addEventListener('click', () => loadChat(chat.chatId));

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'nova-history-delete';
      remove.textContent = '×';
      remove.title = 'Delete conversation';
      remove.setAttribute('aria-label', 'Delete conversation');
      remove.addEventListener('click', () => deleteChat(chat.chatId));

      item.append(open, remove);
      list.appendChild(item);
    });
  } catch {
    list.innerHTML = '';
    const error = document.createElement('p');
    error.className = 'nova-history-empty';
    error.textContent = 'Chat history unavailable. Check MongoDB setup.';
    list.appendChild(error);
  }
}

async function resetChat() {
  conversation = [];
  activeChatId = null;

  localStorage.removeItem('nova-active-chat');

  try {
    sessionStorage.removeItem('nova-history');
  } catch {}

  renderConversation();
  await refreshChatList();

  showToast('New conversation started');
}

form.addEventListener('submit', e => {
  e.preventDefault();
  sendMessage(input.value);
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 180) + 'px';
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll('[data-prompt]').forEach(btn => {
  btn.addEventListener('click', () => sendMessage(btn.dataset.prompt));
});

document.getElementById('newChat').addEventListener('click', async () => {
  await resetChat();
  document.getElementById('sidebar').classList.remove('open');
});

document.getElementById('clearChat').addEventListener('click', resetChat);

document.getElementById('mobileMenu').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('open');
});

window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredInstall = e;
  installBtn.hidden = false;
});

installBtn.addEventListener('click', async () => {
  if (!deferredInstall) {
    showToast('Use your browser menu and choose Add to Home screen');
    return;
  }

  deferredInstall.prompt();
  await deferredInstall.userChoice;
  deferredInstall = null;
  installBtn.hidden = true;
});

window.addEventListener('appinstalled', () => showToast('NOVA AI installed'));

if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// Load the saved active conversation on startup.
async function initializeChatHistory() {
  createHistorySection();

  if (activeChatId) {
    try {
      const data = await apiPost({
        action: 'load',
        chatId: activeChatId
      });

      conversation = Array.isArray(data.messages) ? data.messages : [];
      renderConversation();
    } catch {
      // The old chat may have been deleted or guest storage reset.
      activeChatId = null;
      localStorage.removeItem('nova-active-chat');

      try {
        const saved = JSON.parse(
          sessionStorage.getItem('nova-history') || '[]'
        );

        if (Array.isArray(saved)) {
          conversation = saved;
          renderConversation();
        }
      } catch {}
    }
  } else {
    // Restore a local fallback only when no database chat is selected.
    try {
      const saved = JSON.parse(
        sessionStorage.getItem('nova-history') || '[]'
      );

      if (Array.isArray(saved) && saved.length) {
        conversation = saved;
        renderConversation();
      }
    } catch {}
  }

  await refreshChatList();
}

initializeChatHistory();
