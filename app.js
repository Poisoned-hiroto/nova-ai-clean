
const form = document.getElementById('chatForm');
const input = document.getElementById('prompt');
const messagesEl = document.getElementById('messages');
const welcome = document.getElementById('welcome');
const sendBtn = document.getElementById('sendBtn');
const toast = document.getElementById('toast');
const installBtn = document.getElementById('installBtn');
const fileInput = document.getElementById('fileInput');
const attachBtn = document.getElementById('attachBtn');
const attachmentPreview = document.getElementById('attachmentPreview');

let selectedFile = null;
let conversation = [];
let activeChatId = localStorage.getItem('nova-active-chat') || null;
let deferredInstall = null;
let toastTimer;
let isLoadingChat = false;

const MAX_FILE_SIZE = 4 * 1024 * 1024;

const ALLOWED_MIME_TYPES = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif',
  'application/pdf'
];

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

  toastTimer = setTimeout(() => {
    toast.classList.remove('show');
  }, 2600);
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
    blocks.push(
      '<pre><code>' + code.trim() + '</code></pre>'
    );

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
    copy.type = 'button';
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

  const conversationEl = document.getElementById('conversation');

  conversationEl.scrollTo({
    top: conversationEl.scrollHeight,
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

  const conversationEl = document.getElementById('conversation');

  conversationEl.scrollTo({
    top: conversationEl.scrollHeight,
    behavior: 'smooth'
  });

  return row;
}

async function apiPost(payload) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      guestId,
      ...payload
    })
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      data.error || `Request failed (${response.status})`
    );
  }

  return data;
}

async function createChat() {
  const data = await apiPost({
    action: 'create'
  });

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

  if (!trimmed || sendBtn.disabled || isLoadingChat) {
    return;
  }

  sendBtn.disabled = true;

  input.value = '';
  input.style.height = 'auto';

  let typing;

  try {
    if (!activeChatId) {
      await createChat();
    }

    conversation.push({
      role: 'user',
      content: trimmed
    });

    addMessage('user', trimmed);

    typing = showTyping();

    const data = await apiPost({
      action: 'chat',
      chatId: activeChatId,
      messages: conversation
    });

    const reply = data.reply ||
      'I could not generate a response. Please try again.';

    conversation.push({
      role: 'assistant',
      content: reply
    });

    typing.remove();
    typing = null;

    addMessage('assistant', reply, true);

    saveLocalConversation();

    await refreshChatList();

  } catch (err) {
    if (typing) {
      typing.remove();
    }

    saveLocalConversation();

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
  if (isLoadingChat || sendBtn.disabled) {
    return;
  }

  isLoadingChat = true;

  try {
    const data = await apiPost({
      action: 'load',
      chatId
    });

    activeChatId = data.chatId;

    localStorage.setItem('nova-active-chat', activeChatId);

    conversation = Array.isArray(data.messages)
      ? data.messages
      : [];

    saveLocalConversation();
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
  if (!confirm('Delete this conversation permanently?')) {
    return;
  }

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
    const data = await apiPost({
      action: 'list'
    });

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

      open.addEventListener('click', () => {
        loadChat(chat.chatId);
      });

      const remove = document.createElement('button');

      remove.type = 'button';
      remove.className = 'nova-history-delete';
      remove.textContent = '×';
      remove.title = 'Delete conversation';
      remove.setAttribute('aria-label', 'Delete conversation');

      remove.addEventListener('click', () => {
        deleteChat(chat.chatId);
      });

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

  clearSelectedFile();
  renderConversation();

  await refreshChatList();

  showToast('New conversation started');
}

function saveLocalConversation() {
  try {
    sessionStorage.setItem(
      'nova-history',
      JSON.stringify(conversation)
    );
  } catch {}
}

// ------------------------------
// FILE ATTACHMENT
// ------------------------------

function clearSelectedFile() {
  selectedFile = null;

  fileInput.value = '';
  attachmentPreview.innerHTML = '';
  attachmentPreview.hidden = true;
}

function showSelectedFile(file) {
  attachmentPreview.innerHTML = '';

  const item = document.createElement('div');
  item.className = 'attachment-item';

  const details = document.createElement('div');
  details.className = 'attachment-details';

  const name = document.createElement('strong');
  name.textContent = file.name;

  const size = document.createElement('small');

  size.textContent =
    `${(file.size / 1024 / 1024).toFixed(2)} MB`;

  details.append(name, size);

  const remove = document.createElement('button');

  remove.type = 'button';
  remove.className = 'attachment-remove';
  remove.textContent = '×';
  remove.setAttribute('aria-label', 'Remove attachment');

  remove.addEventListener('click', clearSelectedFile);

  item.append(details, remove);

  attachmentPreview.append(item);
  attachmentPreview.hidden = false;
}

attachBtn.addEventListener('click', () => {
  fileInput.click();
});

fileInput.addEventListener('change', () => {
  const file = fileInput.files && fileInput.files[0];

  if (!file) {
    return;
  }

  if (!ALLOWED_MIME_TYPES.includes(file.type)) {
    clearSelectedFile();
    showToast('Choose a supported image or PDF file.');
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    clearSelectedFile();
    showToast('File must be smaller than 4 MB.');
    return;
  }

  selectedFile = file;
  showSelectedFile(file);
});

async function analyzeSelectedFile(file, question) {
  const base64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');

      if (comma < 0) {
        reject(new Error('Could not read this file.'));
        return;
      }

      resolve(result.slice(comma + 1));
    };

    reader.onerror = () => {
      reject(new Error('Could not read this file.'));
    };

    reader.readAsDataURL(file);
  });

  const payload = JSON.stringify({
    fileName: file.name,
    mimeType: file.type,
    fileData: base64,
    question
  });

  // Try both route forms in case the deployment exposes
  // the Python function using the explicit .py path.
  const endpoints = [
    '/api/analyze',
    '/api/analyze.py'
  ];

  let lastError = 'Analysis endpoint not found. Check the Vercel deployment.';

  for (const endpoint of endpoints) {
    let response;

    try {
      response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: payload,
        cache: 'no-store'
      });

    } catch {
      lastError = 'Could not reach the analysis service. Check your connection.';
      continue;
    }

    const data = await response.json().catch(() => ({}));

    if (response.status === 404) {
      lastError = 'Analysis endpoint not found. Check the Vercel deployment.';
      continue;
    }

    if (!response.ok) {
      throw new Error(
        data.error || `File analysis failed (${response.status}).`
      );
    }

    if (
      typeof data.analysis !== 'string' ||
      !data.analysis.trim()
    ) {
      throw new Error(
        'The analysis service returned an empty response.'
      );
    }

    return data.analysis;
  }

  throw new Error(lastError);
}

async function handleFileAnalysis() {
  if (!selectedFile || sendBtn.disabled || isLoadingChat) {
    return;
  }

  const file = selectedFile;
  const question = input.value.trim();

  const userText = question
    ? `${question}\n\nAttached file: ${file.name}`
    : `Please analyse this file: ${file.name}`;

  sendBtn.disabled = true;
  attachBtn.disabled = true;

  input.value = '';
  input.style.height = 'auto';

  addMessage('user', userText);

  const typing = showTyping();

  try {
    const analysis = await analyzeSelectedFile(file, question);

    typing.remove();

    addMessage(
      'assistant',
      `## File analysis: ${file.name}\n\n${analysis}`,
      true
    );

    // Keep the result in the current browser session.
    // MongoDB persistence for file-analysis results requires
    // a corresponding backend API change.
    conversation.push({
      role: 'user',
      content: userText
    });

    conversation.push({
      role: 'assistant',
      content: analysis
    });

    saveLocalConversation();

    clearSelectedFile();

    showToast('File analysis complete.');

  } catch (error) {
    typing.remove();

    addMessage(
      'assistant',
      `I couldn't analyse this file. ${error.message || 'Please try again.'}`,
      true
    );

    showToast('File analysis failed');

  } finally {
    sendBtn.disabled = false;
    attachBtn.disabled = false;
    input.focus();
  }
}

// One submit handler: file analysis OR normal chat, never both.
form.addEventListener('submit', event => {
  event.preventDefault();

  if (selectedFile) {
    handleFileAnalysis();
  } else {
    sendMessage(input.value);
  }
});

// ------------------------------
// INPUT AND NAVIGATION
// ------------------------------

input.addEventListener('input', () => {
  input.style.height = 'auto';

  input.style.height =
    Math.min(input.scrollHeight, 180) + 'px';
});

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll('[data-prompt]').forEach(button => {
  button.addEventListener('click', () => {
    sendMessage(button.dataset.prompt);
  });
});

document.getElementById('newChat').addEventListener('click', async () => {
  await resetChat();

  document.getElementById('sidebar').classList.remove('open');
});

document.getElementById('clearChat').addEventListener('click', resetChat);

document.getElementById('mobileMenu').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('open');
});

// ------------------------------
// PWA INSTALL
// ------------------------------

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();

  deferredInstall = event;
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

window.addEventListener('appinstalled', () => {
  showToast('NOVA AI installed');
});

if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

// ------------------------------
// RESTORE CHAT HISTORY
// ------------------------------

async function initializeChatHistory() {
  createHistorySection();

  if (activeChatId) {
    try {
      const data = await apiPost({
        action: 'load',
        chatId: activeChatId
      });

      conversation = Array.isArray(data.messages)
        ? data.messages
        : [];

      renderConversation();

    } catch {
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
