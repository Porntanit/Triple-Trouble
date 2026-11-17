// Photos are analyzed first. Only an explicit confirmation adds a meal/photo to history.
for (const scanner of document.querySelectorAll('.image-scanner')) {
  const form = scanner.querySelector('.image-scan-form');
  const status = scanner.querySelector('.scan-status');
  const preview = scanner.querySelector('.scan-preview');
  let draft = null;
  function notice(text, error = false) { status.hidden = false; status.className = 'scan-status ' + (error ? 'error' : ''); status.textContent = text; }
  function field(labelText, type, value) {
    const label = document.createElement('label'); label.textContent = labelText;
    const input = document.createElement('input'); input.type = type; input.value = value ?? ''; label.append(input); return {label,input};
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); const button = form.querySelector('button'); if (button.disabled) return;
    button.disabled = true; preview.hidden = true;
    notice('Analyzing locally… The first photo can take a few minutes.');
    try {
      const data = new FormData(form);
      const response = await fetch('/api/images/analyze', {method:'POST', headers:{'X-CSRF-Token':csrfToken}, body:data});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Image analysis failed.');
      draft = result.analysis; renderPreview(draft); notice('Preview only — nothing has been added to your tracker or collection.');
    } catch (error) { notice(error.message || 'Unable to analyze this photo.', true); }
    finally { button.disabled = false; }
  });
  function renderPreview(result) {
    preview.replaceChildren(); preview.hidden = false;
    const image = document.createElement('img'); image.className = 'scan-result-image'; image.src = '/api/images/draft/' + encodeURIComponent(result.id); image.alt = 'Photo being reviewed';
    const body = document.createElement('div'); const heading = document.createElement('h3'); heading.textContent = result.food_name || 'Photo analysis';
    const source = document.createElement('p'); source.className = 'eyebrow'; source.textContent = result.calorie_source;
    const notes = document.createElement('p'); notes.textContent = result.nutrition_notes;
    const uncertain = document.createElement('p'); uncertain.className = 'subtle-notice'; uncertain.textContent = [result.portion_description, result.uncertainty, result.safety_note].filter(Boolean).join(' ');
    const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = result.kind === 'label' ? 'Check text read from the label' : 'Check what the image model saw';
    const raw = document.createElement('p'); raw.className = 'ocr-text'; raw.textContent = result.ocr_text || result.observation; details.append(summary,raw);
    const confirmation = document.createElement('form'); confirmation.className = 'photo-confirm-form';
    const name = field('Food name (editable)', 'text', result.food_name); name.input.maxLength = 120;
    const value = field('Calories per unit (review estimate)', 'number', result.calories_per_unit); value.input.min = '0'; value.input.max = '20000'; value.input.step = '0.1'; value.input.required = true;
    const basisLabel = document.createElement('label'); basisLabel.textContent = 'What does the calorie value cover?'; const basis = document.createElement('select'); basis.required = true;
    for (const [key,text] of [['','Choose a basis'],['visible_meal','One assumed serving of pictured food'],['per_serving','One labeled serving'],['per_100g','100 g of this food']]) { const option = document.createElement('option'); option.value = key; option.textContent = text; basis.append(option); }
    basis.value = result.basis === 'unknown' ? '' : result.basis; basisLabel.append(basis);
    const amount = field('Portions eaten', 'number', '1'); amount.input.min = '0.1'; amount.input.max = '20'; amount.input.step = '0.1'; amount.input.required = true;
    function updateAmount() { const grams = basis.value === 'per_100g'; amount.label.childNodes[0].textContent = grams ? 'Grams eaten' : 'Portions / servings eaten'; amount.input.max = grams ? '2000' : '20'; amount.input.value = grams ? '100' : '1'; }
    basis.addEventListener('change', updateAmount); updateAmount();
    const date = field('Date eaten', 'date', document.querySelector('.calorie-page')?.dataset.trackingDate || new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()));
    date.input.required = true; date.input.max = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const total = document.createElement('p'); total.className = 'scan-total';
    function updateTotal() { const calories = Number(value.input.value) * Number(amount.input.value) / (basis.value === 'per_100g' ? 100 : 1); total.textContent = value.input.value === '' ? 'No energy reading — review the label before adding.' : `Amount to log: ${Math.round(calories * 10) / 10} kcal (estimate)`; }
    value.input.addEventListener('input',updateTotal); amount.input.addEventListener('input',updateTotal); basis.addEventListener('change',updateTotal); updateTotal();
    const grid = document.createElement('div'); grid.className = 'scan-input-grid'; grid.append(name.label,value.label,basisLabel,amount.label,date.label);
    const add = document.createElement('button'); add.type = 'submit'; add.className = 'primary-button'; add.textContent = 'I ate this — add to tracker ✓'; add.disabled = !result.is_food;
    const discard = document.createElement('button'); discard.type = 'button'; discard.className = 'outline-button'; discard.textContent = 'Just looking — discard';
    const actions = document.createElement('div'); actions.className = 'actions'; actions.append(add,discard);
    confirmation.append(grid,total,actions);
    confirmation.addEventListener('submit', async event => {
      event.preventDefault(); if (add.disabled) return;
      add.disabled = true; discard.disabled = true; notice('Adding your confirmed meal…');
      try {
        const data = await apiRequest('/api/images/confirm/' + encodeURIComponent(result.id), {date:date.input.value, food:name.input.value, calories_per_unit:Number(value.input.value), quantity:Number(amount.input.value)/(basis.value === 'per_100g' ? 100 : 1), basis:basis.value});
        document.dispatchEvent(new CustomEvent('calorie-log-changed',{detail:data}));
        image.src = '/food-photos/' + data.confirmed_entry_id;
        confirmation.replaceChildren(); const link = document.createElement('a'); link.href = '/evaluation?date=' + encodeURIComponent(data.selected.day); link.textContent = 'View my calorie tracker ↗'; link.className = 'outline-button inline-button'; confirmation.append(link);
        notice('Meal added. Its photo is now saved in Document collection.'); draft = null;
      } catch (error) { notice(error.message,true); add.disabled = false; discard.disabled = false; }
    });
    discard.addEventListener('click', async () => {
      discard.disabled = true;
      try { await apiRequest('/api/images/draft/' + encodeURIComponent(result.id), {}, 'DELETE'); preview.replaceChildren(); preview.hidden = true; draft = null; notice('Preview discarded. No meal or photo was added.'); }
      catch (error) { notice(error.message,true); discard.disabled = false; }
    });
    body.append(source,heading,notes,uncertain,details,confirmation); preview.append(image,body);
  }
}
