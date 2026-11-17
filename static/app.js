const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
async function apiRequest(url, data, method = 'POST') {
  const response = await fetch(url, { method, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken}, body: JSON.stringify(data) });
  const isJson = (response.headers.get('content-type') || '').includes('application/json');
  if (!isJson) throw new Error('The server could not complete the request. Check available disk space and try again.');
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}
function addEvidence(container, message) {
  for (const warning of message.warnings || []) {
    const p = document.createElement('p'); p.className = 'subtle-notice'; p.textContent = warning; container.append(p);
  }
  const sources = (message.sources || []).filter(s => typeof s.filename === 'string' && Number.isInteger(s.page) && s.page > 0);
  const retrieved = message.retrieved_sources || sources;
  if (!retrieved.length) return;
  const section = document.createElement('section'); section.className = 'message-sources';
  const h = document.createElement('h3'); h.textContent = 'Referenced pages · verify the supporting claims'; section.append(h);
  for (const source of sources) {
    const a = document.createElement('a'); a.href = '/documents/file/' + encodeURIComponent(source.filename) + '#page=' + source.page;
    a.target = '_blank'; a.rel = 'noopener'; a.textContent = `${source.filename} · p. ${source.page}`; section.append(a);
  }
  const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = `Inspect ${retrieved.length} retrieved passage(s)`; details.append(summary);
  for (const source of retrieved) {
    const block = document.createElement('blockquote'); const title = document.createElement('strong'); title.textContent = `${source.filename} · page ${source.page}`;
    const p = document.createElement('p'); p.textContent = source.excerpt || ''; block.append(title, p); details.append(block);
  }
  section.append(details); container.append(section);
}
async function refreshModelStatus() {
  const status = document.querySelector('#model-status');
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    const chatReady = Boolean(data.models && data.models['gemma3:1b']);
    status.textContent = data.ready && data.vision_ready ? 'Ollama · chat & photos ready' : data.ready ? 'Chat ready · photo model downloading/missing' : chatReady ? 'Chat ready · PDF search model missing' : data.ollama ? 'Ollama · chat model missing' : 'Ollama offline · open the Ollama app';
    status.classList.toggle('ready', chatReady);
  } catch { status.textContent = 'Model status unavailable'; }
}
refreshModelStatus();
// Reflect Ollama being opened after the page loaded, without a manual reload.
setInterval(refreshModelStatus, 30000);
const profileForm = document.querySelector('#profile-form');
if (profileForm) {
  const profileStatus = document.querySelector('#profile-status');
  const profileButton = profileForm.querySelector('[type="submit"]');
  function showProfileStatus(message, state) {
    profileStatus.textContent = message;
    profileStatus.className = 'profile-feedback ' + state;
    profileStatus.hidden = false;
    profileStatus.setAttribute('role', state === 'error' ? 'alert' : 'status');
  }
  profileForm.addEventListener('invalid', event => {
    const label = event.target.closest('label');
    const name = label ? label.childNodes[0].textContent.trim() : 'required field';
    showProfileStatus('Please check ' + name + ': ' + event.target.validationMessage, 'error');
  }, true);
  profileForm.addEventListener('input', () => {
    profileButton.textContent = 'Save my profile ↗';
    showProfileStatus('You have unsaved changes.', 'pending');
    document.querySelector('#profile-next').hidden = true;
  });
  profileForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (profileButton.disabled) return;
    const data = Object.fromEntries(new FormData(profileForm));
    data.meal_budget = Number(data.meal_budget); data.meals_per_day = Number(data.meals_per_day);
    for (const key of ['age','height_cm','weight_kg']) data[key] = Number(data[key]);
    profileButton.disabled = true; profileButton.textContent = 'Saving…';
    showProfileStatus('Saving your profile…', 'pending');
    try {
      const result = await apiRequest('/api/profile', data, 'PUT');
      try { localStorage.removeItem('triple-trouble-personalized'); } catch {}
      showProfileStatus('Profile saved successfully. Your preferences are ready for personalized chat.', 'success');
      profileButton.textContent = 'Saved ✓';
      document.querySelector('#profile-energy-value').textContent = result.profile.daily_target ? `${result.profile.daily_target} kcal/day` : 'Complete your details';
      document.querySelector('#profile-next').hidden = false;
      const name = document.querySelector('[data-profile-name]');
      const goal = document.querySelector('[data-profile-goal]');
      const avatar = document.querySelector('[data-profile-avatar]');
      if (name) name.textContent = result.profile.name;
      if (goal) goal.textContent = result.profile.dietary_goal;
      if (avatar) avatar.textContent = result.profile.name.charAt(0).toUpperCase();
    } catch (error) {
      showProfileStatus(error.message, 'error');
      profileButton.textContent = 'Try saving again ↗';
    } finally { profileButton.disabled = false; }
  });
  document.querySelector('#delete-profile').addEventListener('click', async () => {
    if (!confirm('Delete your saved profile, calorie history, comparisons and ratings? This cannot be undone.')) return;
    try { await apiRequest('/api/profile', {}, 'DELETE'); try { localStorage.removeItem('triple-trouble-general'); localStorage.removeItem('triple-trouble-personalized'); localStorage.removeItem('local-ollama-chat-messages'); } catch {} window.location.reload(); }
    catch (error) { showProfileStatus(error.message, 'error'); }
  });
}
const trackingPage = document.querySelector('.calorie-page');
if (trackingPage && document.querySelector('#food-log')) {
  const trackingDate = trackingPage.dataset.trackingDate;
  const status = document.querySelector('#tracking-status');
  const fmt = value => Number(value).toLocaleString('en-US', {maximumFractionDigits: 1});
  function renderTracking(data) {
    const day = data.selected;
    document.querySelector('#calories-consumed').textContent = fmt(day.consumed);
    document.querySelector('#calories-remaining').textContent = day.remaining === null ? '—' : fmt(day.remaining);
    document.querySelector('#remaining-note').textContent = day.target === null ? 'Set your own target below' : day.remaining < 0 ? `${fmt(-day.remaining)} kcal above your target` : `Of your ${fmt(day.target)} kcal target`;
    document.querySelector('#entry-count').textContent = `${data.entries.length} food entries logged`;

    document.querySelector('#self-rating-note').textContent = day.rating ? `Your rating: ${day.rating} / 5` : 'Your own reflection, from 1 to 5';
    for (const button of trackingPage.querySelectorAll('[data-self-rating]')) {
      const chosen = Number(button.dataset.selfRating) === day.rating;
      button.classList.toggle('chosen', chosen); button.setAttribute('aria-pressed', String(chosen));
    }
    const log = document.querySelector('#food-log'); log.replaceChildren();
    for (const entry of data.entries) {
      const li = document.createElement('li'); const name = document.createElement('span'); name.textContent = entry.food;
      const amount = document.createElement('strong'); amount.textContent = `${fmt(entry.calories)} kcal`;
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'delete-button'; remove.dataset.deleteEntry = entry.id; remove.textContent = 'Remove'; remove.setAttribute('aria-label', `Remove ${entry.food}`);
      if (entry.has_photo) { const photo = document.createElement('img'); photo.className = 'food-thumb'; photo.src = '/food-photos/' + entry.id; photo.alt = entry.food; li.append(photo); }
      li.append(name, amount, remove); log.append(li);
    }
    if (!data.entries.length) { const li = document.createElement('li'); li.className = 'muted'; li.textContent = 'No food logged for this date yet.'; log.append(li); }
    const history = document.querySelector('#calorie-history'); history.replaceChildren();
    for (const row of data.history) {
      const tr = document.createElement('tr'); const date = document.createElement('th'); const link = document.createElement('a'); link.href = '/evaluation?date=' + encodeURIComponent(row.day); link.textContent = row.day; date.append(link); tr.append(date);
      for (const text of [`${fmt(row.consumed)} kcal`, `${fmt(row.remaining)} kcal${row.remaining < 0 ? ' (above target)' : ''}`, row.rating ? `${row.rating} / 5` : 'Not rated']) { const cell = document.createElement('td'); cell.textContent = text; tr.append(cell); }
      history.append(tr);
    }
  }
  let trackingBusy = false;
  async function saveTracking(url, payload, method, message) {
    if (trackingBusy) return false;
    trackingBusy = true;
    const controls = [...trackingPage.querySelectorAll('button')]; controls.forEach(button => button.disabled = true);
    status.hidden = false; status.className = ''; status.textContent = 'Saving…';
    try { const data = await apiRequest(url, payload, method); renderTracking(data); status.textContent = message; return true; }
    catch (error) { status.className = 'error'; status.textContent = error.message; return false; }
    finally { trackingBusy = false; controls.forEach(button => button.disabled = false); }
  }
  document.addEventListener('calorie-log-changed', event => { if (event.detail.selected.day === trackingDate) renderTracking(event.detail); });
  trackingPage.addEventListener('click', async event => {
    const rating = event.target.closest('[data-self-rating]');
    if (rating) await saveTracking('/api/calories', {date: trackingDate, rating: Number(rating.dataset.selfRating)}, 'PUT', 'Your daily self-rating is saved.');
    const remove = event.target.closest('[data-delete-entry]');
    if (remove && confirm('Remove this food entry from your log?')) await saveTracking('/api/calories/entries/' + remove.dataset.deleteEntry, {}, 'DELETE', 'Food entry removed. Totals updated.');
  });
}
