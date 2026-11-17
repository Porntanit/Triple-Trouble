const form = document.querySelector('#chat-form');
const input = document.querySelector('#message-input');
const sendButton = document.querySelector('#send-button');
const conversation = document.querySelector('#conversation');
const clearButton = document.querySelector('#clear-button');
const modeSelect = document.querySelector('#chat-mode');
let STORAGE_KEY = 'triple-trouble-' + modeSelect.value;

let messages = loadMessages();

function loadMessages() {
  try {
    let raw = localStorage.getItem(STORAGE_KEY);
    // Keep the original app's browser history when first opening General mode.
    if (raw === null && STORAGE_KEY === 'triple-trouble-general') {
      raw = localStorage.getItem('local-ollama-chat-messages');
      if (raw !== null) localStorage.setItem(STORAGE_KEY, raw);
    }
    const saved = JSON.parse(raw || '[]');
    return Array.isArray(saved) ? saved.filter((message) =>
      message && ['user', 'assistant'].includes(message.role) && typeof message.content === 'string'
    ) : [];
  } catch {
    return [];
  }
}

function saveMessages() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(messages)); }
  catch { /* Chat remains usable when browser storage is unavailable. */ }
}

function appendAssistantContent(container, text) {
  const urlPattern = /https?:\/\/[^\s<>"']+/gi;
  let position = 0;

  for (const match of text.matchAll(urlPattern)) {
    const start = match.index;
    let urlText = match[0];
    let trailing = '';

    // Keep sentence punctuation outside the link, and only consume closing
    // parentheses that have a matching opening parenthesis in the URL.
    while (/[.,!?;:]$/.test(urlText)) {
      trailing = urlText.slice(-1) + trailing;
      urlText = urlText.slice(0, -1);
    }
    while (urlText.endsWith(')') && (urlText.match(/\(/g) || []).length < (urlText.match(/\)/g) || []).length) {
      trailing = ')' + trailing;
      urlText = urlText.slice(0, -1);
    }

    let parsedUrl;
    try {
      parsedUrl = new URL(urlText);
    } catch {
      continue;
    }
    if (!['http:', 'https:'].includes(parsedUrl.protocol)) continue;

    container.append(document.createTextNode(text.slice(position, start)));
    const link = document.createElement('a');
    link.href = parsedUrl.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = urlText;
    container.append(link, document.createTextNode(trailing));
    position = start + match[0].length;
  }

  container.append(document.createTextNode(text.slice(position)));
}

function renderMessage(message) {
  const row = document.createElement('article');
  row.className = `message ${message.role}`;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.setAttribute('aria-hidden', 'true');
  avatar.textContent = message.role === 'assistant' ? '✳' : 'You';
  const content = document.createElement('div');
  content.className = 'message-content';
  if (message.role === 'assistant') {
    appendAssistantContent(content, message.content);
  } else {
    content.textContent = message.content;
  }
  row.append(avatar, content);
  if (message.role === 'assistant') {
    const mode = document.createElement('div'); mode.className = 'message-mode';
    mode.textContent = (message.mode || modeSelect.value).toUpperCase(); content.prepend(mode);
    addEvidence(content, message);
  }
  conversation.append(row);
}

function renderHistory() {
  conversation.replaceChildren();
  if (messages.length === 0) {
    const welcome = document.createElement('div');
    welcome.id = 'welcome';
    welcome.className = 'welcome';
    welcome.innerHTML = '<div class="welcome-icon" aria-hidden="true">✳</div><h2>Let’s find your next good choice.</h2><p>Ask a question, explore your sources,<br>or start with an idea below.</p>';
    conversation.append(welcome);
  } else {
    messages.forEach(renderMessage);
  }
  conversation.scrollTop = conversation.scrollHeight;
}

renderHistory();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || sendButton.disabled) return;

  messages.push({ role: 'user', content });
  saveMessages();
  renderHistory();
  input.value = '';
  input.style.height = 'auto';
  sendButton.disabled = true;
  modeSelect.disabled = true; clearButton.disabled = true;
  const loading = document.createElement('p'); loading.className = 'loading-note'; loading.textContent = 'Finding passages and thinking locally…'; conversation.append(loading);

  try {
    const data = await apiRequest('/api/chat', {messages: messages.slice(-39), mode: modeSelect.value});
    messages.push(data.message);
    saveMessages();
    renderHistory();
  } catch (error) {
    const notice = document.createElement('div');
    notice.className = 'message assistant';
    const errorText = document.createElement('div');
    errorText.className = 'message-content error';
    errorText.textContent = error.message || 'Unable to contact the chat server.';
    notice.append(errorText);
    conversation.append(notice);
    conversation.scrollTop = conversation.scrollHeight;
  } finally {
    loading.remove();
    sendButton.disabled = false; modeSelect.disabled = false; clearButton.disabled = false;
    input.focus();
  }
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clearButton.addEventListener('click', () => {
  messages = [];
  saveMessages();
  renderHistory();
  input.focus();
});

modeSelect.addEventListener('change', () => {
  STORAGE_KEY = 'triple-trouble-' + modeSelect.value;
  messages = loadMessages(); renderHistory();
});
for (const chip of document.querySelectorAll('[data-prompt]')) chip.addEventListener('click', () => {
  input.value = chip.dataset.prompt; input.focus(); input.dispatchEvent(new Event('input'));
});
