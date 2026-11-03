const form = document.querySelector('#chat-form');
const input = document.querySelector('#message-input');
const sendButton = document.querySelector('#send-button');
const conversation = document.querySelector('#conversation');
const clearButton = document.querySelector('#clear-button');
const STORAGE_KEY = 'local-ollama-chat-messages';

let messages = loadMessages();

function loadMessages() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(saved) ? saved.filter((message) =>
      message && ['user', 'assistant'].includes(message.role) && typeof message.content === 'string'
    ) : [];
  } catch {
    return [];
  }
}

function saveMessages() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
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
  const sources = Array.isArray(message.sources) ? message.sources.filter((source) =>
    source && typeof source.filename === 'string' && Number.isInteger(source.page) && source.page > 0
  ) : [];
  if (message.role === 'assistant' && sources.length) {
    const sourceSection = document.createElement('section');
    sourceSection.className = 'message-sources';
    const heading = document.createElement('h3');
    heading.textContent = 'Sources used';
    const list = document.createElement('ul');
    for (const source of sources) {
      const item = document.createElement('li');
      item.textContent = `${source.filename} · page ${source.page}`;
      list.append(item);
    }
    sourceSection.append(heading, list);
    content.append(sourceSection);
  }
  conversation.append(row);
}

function renderHistory() {
  conversation.replaceChildren();
  if (messages.length === 0) {
    const welcome = document.createElement('div');
    welcome.id = 'welcome';
    welcome.className = 'welcome';
    welcome.innerHTML = '<div class="welcome-icon" aria-hidden="true">✳</div><h2>What’s on your mind?</h2><p>Your conversation stays in this browser and runs on your machine.</p>';
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

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The request failed.');
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
    sendButton.disabled = false;
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
