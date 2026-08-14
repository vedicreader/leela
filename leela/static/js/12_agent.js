/* ------------------------------------------------------------------ agent */
function closeDismissableDisclosures(except = null) {
  $$('details.lee-dismissable[open]').forEach(details => { if (details !== except) details.open = false; });
}
document.addEventListener('pointerdown', e => {
  const inside = e.target.closest?.('details.lee-dismissable');
  closeDismissableDisclosures(inside);
}, true);
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || $$('.lee-modal').length) return;
  const open = $$('details.lee-dismissable[open]').at(-1);
  if (!open) return;
  e.preventDefault(); e.stopPropagation(); open.open = false;
  open.querySelector(':scope > summary')?.focus();
}, true);
window.addEventListener('blur', () => closeDismissableDisclosures());

async function loadAgentModels(legacy = $('#legacymodels')?.checked ?? true) {
  const selects = {agent: $('#agentmodel'), inline: $('#inlinemodel'), completion: $('#completionmodel')};
  if (!selects.agent || !selects.inline || !selects.completion) return;
  const previous = Object.fromEntries(Object.entries(selects).map(([k, s]) => [k, s.value]));
  const d = await api('/agent/models?legacy=' + (legacy ? 'true' : 'false'));
  for (const [target, select] of Object.entries(selects)) {
    select.innerHTML = '';
    for (const m of (d.models || [])) {
      const option = document.createElement('option');
      option.value = m.value; option.textContent = `${m.label} · ${m.provider}`;
      option.title = m.source || ''; select.appendChild(option);
    }
    const wanted = d.selected?.[target] || previous[target];
    if ([...select.options].some(o => o.value === wanted)) select.value = wanted;
  }
  const notes = Object.values(d.auth || {}).map(x => x.note).filter(Boolean);
  if (notes.length) selects.agent.title = notes.join(' · ');
}
window.leeLoadModels = loadAgentModels;

async function leeAddModel() {
  const d = await api('/agent/models');
  const saved = (d.saved || []).map(x => `<div class="lee-krow"><span><strong>${esc(x.name)}</strong> · ${esc(x.runtime)}<br><small>${esc(x.model_id)}</small></span><button class="lee-btn warn" data-remove="${esc(x.name)}">remove</button></div>`).join('');
  const m = modal(`<div class="lee-mhead">Add model<span class="sub">saved in Leela · API keys stay in environment variables</span></div>
    <label>name<input class="lee-input" id="modelalias" placeholder="ornith-test"></label>
    <label>model ID or Hugging Face URL<input class="lee-input" id="modelid" placeholder="https://huggingface.co/litert-community/… or openai/model-id"></label>
    <label>runtime<select class="lee-select" id="modelruntime"></select></label>
    <label>context tokens<input class="lee-input" id="modelctx" type="number" value="128000" min="1024"></label>
    <details><summary>hosted API settings</summary><label>base URL<input class="lee-input" id="modelbase" placeholder="https://api.example.com/v1"></label><label>API key environment variable<input class="lee-input" id="modelkeyenv" placeholder="OPENAI_API_KEY"></label><label>FastLLM vendor<input class="lee-input" id="modelvendor" placeholder="openai"></label><label>FastLLM API transport<input class="lee-input" id="modelapi" placeholder="openai"></label></details>
    <button class="lee-btn go" id="modelsave">save model</button>
    <h4>saved models</h4><div class="lee-modallist">${saved || '<div class="lee-dim">none yet</div>'}</div>`);
  /* The runtimes ramabana will accept, and which of them rishi can load here -- `d.runtimes`
     rather than a list in this file, which drifted out of step once already and left the
     picker offering MLX after it had been dropped. An unavailable one stays visible but
     disabled and says what to install: "MLX needs rishi[mlx]" beats a silently missing row. */
  const RUNTIME_LABELS = {litert: 'LiteRT', mlx: 'MLX', llama: 'llama.cpp', remote: 'hosted API / FastLLM'};
  const rtsel = m.querySelector('#modelruntime');
  rtsel.innerHTML = (d.runtimes || [{value: 'remote', available: true}]).map(r =>
    `<option value="${esc(r.value)}"${r.available ? '' : ' disabled'}>${esc(RUNTIME_LABELS[r.value] || r.value)}` +
    `${r.available ? '' : ' — needs pip install rishi[' + esc(r.value) + ']'}</option>`).join('');
  const firstrt = rtsel.querySelector('option:not([disabled])');
  if (firstrt) rtsel.value = firstrt.value;

  $('#modelsave', m).onclick = async () => {
    status('validating and saving model…');
    const r = await post('/agent/models/add', {name: $('#modelalias',m).value.trim(), model_id: $('#modelid',m).value.trim(), runtime: $('#modelruntime',m).value, ctx: Number($('#modelctx',m).value), base_url: $('#modelbase',m).value.trim(), api_key_env: $('#modelkeyenv',m).value.trim(), vendor_name: $('#modelvendor',m).value.trim(), api_name: $('#modelapi',m).value.trim()});
    if (!r.ok) return status(r.error || 'could not save model','err');
    m.remove(); await loadAgentModels(); status(`saved ${r.model.name} · ${r.model.runtime} · ${r.model.model_id}`,'ok');
  };
  $$('[data-remove]',m).forEach(b => b.onclick = async () => {
    const name=b.dataset.remove; const r=await post('/agent/models/remove',{name});
    if (!r.ok) return status(r.error || 'could not remove model','err');
    m.remove(); await loadAgentModels(); status(`removed ${name}`,'ok');
  });
  $('#modelalias',m)?.focus();
}
window.leeAddModel = leeAddModel;

async function leeAgentModel(target, model) {
  const select = $('#' + (target === 'agent' ? 'agentmodel' : target === 'inline' ? 'inlinemodel' : 'completionmodel'));
  if (select) select.disabled = true;
  try {
    const d = await post('/agent/model', {target, model});
    status(d.ok ? `${target} model saved: ${d.model}` : (d.error || 'model switch failed'), d.ok ? 'ok' : 'err');
    if (d.ok && target === 'completion') api('/complete/warm').catch(() => {});
    if (!d.ok) await loadAgentModels();
  } catch (e) { await loadAgentModels(); status(e.message || String(e), 'err'); }
  finally { if (select) select.disabled = false; }
}
window.leeAgentModel = leeAgentModel;

async function leeAgentCompaction() {
  try {
    const d = await post('/agent/compaction', {auto: !!$('#autocompact')?.checked,
                                               strategy: $('#compactstrategy')?.value || 'surgical'});
    status(d.note, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentCompaction = leeAgentCompaction;

/* How much work one turn may do. `auto` lets ramabana size it from the prompt; a number pins it.
   The fields are written back from the answer, so a refusal leaves the box showing what is
   actually in force rather than the rejected text. */
/* The highlighted range, queued as context for the next turn.

   Sent as text rather than as `path:from-to` for the agent to go and read: the buffer may be
   unsaved, and what you highlighted is what you meant, not what happens to be on disk. */
function leeAgentSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const sel = v.state.selection.main;
  if (sel.empty) return status('select the code you want the agent to see', 'err');
  const doc = v.state.doc, from = doc.lineAt(sel.from).number, to = doc.lineAt(sel.to).number;
  const path = lee.path || 'untitled', name = path.split('/').pop() || 'untitled';
  lee.agentSelections.push({
    label: `${name}:${from}${to > from ? '–' + to : ''}`,
    path,
    ref: {kind: 'selection', path, from, to, text: doc.sliceString(sel.from, sel.to)},
  });
  leePane('right', true); leeRight('agent'); paintAgentAttachments();
  $('#agentprompt')?.focus();
  status(`selection queued for the agent · ${from}${to > from ? '–' + to : ''}`, 'ok');
}
window.leeAgentSelection = leeAgentSelection;

async function leeAgentBudget() {
  const tools = $('#toolbudget'), steps = $('#stepbudget');
  try {
    const d = await post('/agent/budget', {tools: tools?.value.trim(), steps: steps?.value.trim()});
    if (tools) tools.value = String(d.tools);
    if (steps) steps.value = String(d.steps);
    status(d.note, 'ok');
  } catch (e) {
    status(e.message || String(e), 'err');
    try { const d = await api('/agent/budget/state');
      if (tools) tools.value = String(d.tools); if (steps) steps.value = String(d.steps);
    } catch (_) { /* leave the boxes alone rather than blank them on a second failure */ }
  }
}
window.leeAgentBudget = leeAgentBudget;

async function leeLocalMultimodal(enabled) {
  const box = $('#localmultimodal');
  const d = await post('/agent/settings', {local_multimodal: !!enabled});
  if (!d.ok && box) box.checked = !enabled;
  status(d.ok ? d.note : (d.error || 'local multimodal setting failed'), d.ok ? 'ok' : 'err');
}
window.leeLocalMultimodal = leeLocalMultimodal;

function leeAgentExpand() {
  const shell = $('#shell'); if (!shell) return;
  leeRight('agent'); shell.classList.toggle('agent-focus');
  const expanded = shell.classList.contains('agent-focus');
  $('.lee-agent')?.classList.toggle('timeline-workspace', expanded);
  if ($('#agentexpand')) $('#agentexpand').textContent = expanded ? 'restore' : 'expand';
  localStorage.setItem('lee-agent-expanded', expanded ? '1' : '0');
}
window.leeAgentExpand = leeAgentExpand;

function leeRight(which) {
  const right = $('#right'); if (!right) return;
  right.classList.toggle('right-agent', which === 'agent');
  right.classList.toggle('right-vars', which === 'vars');
  right.classList.toggle('right-memory', which === 'memory');
  $$('.lee-righttab', right).forEach(b => {
    const active = b.dataset.right === which;
    b.classList.toggle('active', active); b.setAttribute('aria-selected', String(active));
  });
  if (which === 'agent') requestAnimationFrame(() => { const log = $('#agentlog'); if (log) log.scrollTop = log.scrollHeight; });
  if (which === 'memory' && !lee.memoryLoaded) leeMemoryNotes();
}
window.leeRight = leeRight;

// Every memory view is fetched asynchronously into one `#memorybody`, so a slow answer must not
// paint over the view you switched to while it was in flight. Each switch takes the next token;
// a fetch that finds the token moved drops its result.
let memoryViewSeq = 0;
function setMemoryView(view) {
  memoryViewSeq += 1;
  const panel = $('.lee-memory');
  if (panel) { panel.classList.remove('memory-view-notes', 'memory-view-sources', 'memory-view-topics', 'memory-view-vault'); panel.classList.add('memory-view-' + view); }
  $$('[data-memory-view]').forEach(button => button.classList.toggle('active', button.dataset.memoryView === view));
}
async function leeMemoryNotes() {
  const body = $('#memorybody'); if (!body) return;
  lee.memoryLoaded = 'loading'; leePane('right', true); leeRight('memory'); setMemoryView('notes');
  const seq = memoryViewSeq;
  body.innerHTML = '<div class="lee-memory-empty">Loading agent memory…</div>';
  try {
    const data = await api('/agent/memory'), selected = Object.fromEntries(
      Object.entries(data.selected || {}).map(([target, ids]) => [target, new Set(ids || [])]));
    if (seq !== memoryViewSeq) return;      // the vault (or another view) is on screen now
    lee.agentMemory = data; lee.memoryLoaded = 'notes';
    $('#memorystatus').textContent = `· ${data.notes.length} note${data.notes.length === 1 ? '' : 's'}`;
    if (!data.notes.length) {
      body.innerHTML = `<section class="lee-memory-notes-empty"><strong>Give the models durable context</strong>` +
        `<p>Store project conventions, decisions, preferences, and recurring instructions. You choose which model sees each note.</p>` +
        `<button class="lee-btn go" onclick="leeNewMemoryNote()">Create a memory note</button></section>`; return;
    }
    const labels = {agent: 'Agent', inline: 'Prompt', completion: 'Complete'};
    body.innerHTML = `<div class="lee-memory-notes-intro"><span>Model context</span><strong>Select exactly where each note is used.</strong></div>` +
      data.notes.map(note => `<article class="lee-memory-note-card" data-note-id="${esc(note.id)}"><button class="lee-memory-note-open" data-edit-note>` +
        `<strong>${esc(note.title || 'Untitled note')}</strong><span>${esc(String(note.text || '').replace(/\s+/g, ' ').slice(0, 180))}</span></button>` +
        `<div class="lee-memory-note-routes">${Object.entries(labels).map(([target, label]) => `<label title="Use in ${esc(data.targets[target])}">` +
          `<input type="checkbox" data-quick-target="${target}"${selected[target]?.has(String(note.id)) ? ' checked' : ''}><span>${label}</span></label>`).join('')}</div>` +
        `<button class="lee-memory-note-edit" data-edit-note aria-label="edit ${esc(note.title || 'memory note')}">edit</button></article>`).join('');
    $$('.lee-memory-note-card', body).forEach(card => {
      const note = data.notes.find(item => String(item.id) === card.dataset.noteId);
      $$('[data-edit-note]', card).forEach(button => button.onclick = () => leeAgentMemory(note.id));
      $$('[data-quick-target]', card).forEach(input => input.onchange = async () => {
        const target = input.dataset.quickTarget, id = String(note.id);
        input.checked ? selected[target].add(id) : selected[target].delete(id);
        try {
          const result = await post('/agent/memory/select', {target, ids: [...selected[target]]});
          status(`${data.targets[target]} memory updated · about ${result.tokens.toLocaleString()} tokens`, 'ok');
        } catch (e) { input.checked = !input.checked; status(e.message || String(e), 'err'); }
      });
    });
  } catch (e) { if (seq !== memoryViewSeq) return; lee.memoryLoaded = false; body.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
function leeNewMemoryNote(draft = {}) { leeAgentMemory('__new__', draft); }
window.leeMemoryNotes = leeMemoryNotes; window.leeNewMemoryNote = leeNewMemoryNote;

async function leeAgentMemory(focusId = '', draft = {}) {
  try {
    const data = await api('/agent/memory'), selected = Object.fromEntries(
      Object.entries(data.selected || {}).map(([target, ids]) => [target, new Set(ids || [])]));
    let active = focusId === '__new__' ? {id: '', title: draft.title || '', text: draft.text || ''} :
      (data.notes || []).find(note => String(note.id) === String(focusId)) || data.notes?.[0] || null;
    const box = modal(`<div class="lee-mhead">Agent memory<span class="sub">durable notes with explicit model routing</span></div>` +
      `<div class="lee-memory-workbench"><aside class="lee-memory-note-list"><header><strong>Notes</strong>` +
      `<button class="lee-btn" data-new-note>New note</button></header><input class="lee-input" data-note-filter placeholder="Filter notes…">` +
      `<div data-note-list></div></aside><section class="lee-memory-note-editor"><div class="lee-memory-note-empty" data-note-empty>` +
      `<strong>No memory note selected</strong><span>Create a note for conventions, architectural decisions, preferences, or recurring context.</span>` +
      `<button class="lee-btn go" data-empty-new>Create first note</button></div><div data-note-form hidden>` +
      `<label class="lee-fieldlabel">Title<input class="lee-input" data-note-title placeholder="e.g. API compatibility rules"></label>` +
      `<div class="lee-memory-editor-head"><span>Memory note</span><small>Markdown · editable</small></div>` +
      `<div class="lee-memory-note-cm" data-note-text></div></div></section>` +
      `<aside class="lee-memory-routing"><header><strong>Use this note in</strong><span>${active?.id ? 'Changes apply to live model context immediately.' : 'Choose now; routing starts when you save.'}</span></header>` +
      `<div data-memory-targets></div><section class="lee-memory-routing-help"><strong>How routing works</strong>` +
      `<p><b>Agent</b> guides the long-running conversation and tools.</p><p><b>Prompt cells</b> guides notebook AI cells independently.</p>` +
      `<p><b>Completion</b> adds a bounded excerpt to one-shot code suggestions. Keep these notes short.</p></section>` +
      `<div class="lee-memory-budget" data-memory-budget></div></aside></div>` +
      `<div class="lee-mfoot"><button class="lee-btn warn" data-delete-note disabled>Delete note</button>` +
      `<span class="lee-spacer"></span><span class="lee-dim" data-note-status>Notes are durable; routing is saved with this workspace.</span>` +
      `<button class="lee-btn go" data-save-note disabled>Save note</button></div>`, null, null,
      {className: 'lee-agent-memory-modal', storageKey: 'agent-memory-v2'});
    const list = $('[data-note-list]', box), form = $('[data-note-form]', box), empty = $('[data-note-empty]', box);
    const title = $('[data-note-title]', box), textHost = $('[data-note-text]', box), targets = $('[data-memory-targets]', box);
    const stateView = createEditor(textHost, {doc: '', lang: 'markdown', lineNums: true,
      placeholder: '# Context\n\nWrite only information that should influence a model…'});
    const noteText = {get value() { return LeeCM.getDoc(stateView); }, set value(value) { LeeCM.setDoc(stateView, String(value || '')); }};
    const labels = data.targets || {agent: 'Agent conversation', inline: 'Prompt cells', completion: 'Code completion'};
    const hasUnsavedChanges = () => !!active && (title.value !== (active.title || '') || noteText.value !== (active.text || ''));
    const mayLeaveNote = async () => !hasUnsavedChanges() || await confirmDialog(
      'discard unsaved note changes', 'Switch notes without saving the edits in the current note?', 'discard edits');
    const isSelected = (target, id) => selected[target]?.has(String(id));
    const selectionCount = id => Object.keys(labels).filter(target => isSelected(target, id)).length;
    const routeBadges = id => [['agent','A'],['inline','P'],['completion','C']]
      .map(([target, label]) => `<i class="${isSelected(target, id) ? 'active' : ''}" title="${esc(labels[target])}">${label}</i>`).join('');
    const paintList = (query = '') => {
      const q = query.trim().toLowerCase(), notes = (data.notes || []).filter(note =>
        !q || `${note.title} ${note.text}`.toLowerCase().includes(q));
      list.innerHTML = notes.map(note => `<button class="lee-memory-note-row${String(note.id) === String(active?.id) ? ' active' : ''}" data-note-id="${esc(note.id)}">` +
        `<span><strong>${esc(note.title || 'Untitled note')}</strong><small>${esc(String(note.text || '').replace(/\s+/g, ' ').slice(0, 110))}</small></span>` +
        `<b class="lee-memory-route-badges">${routeBadges(note.id)}</b></button>`).join('') ||
        '<div class="lee-memory-note-none">No matching notes.</div>';
      $$('[data-note-id]', list).forEach(row => row.onclick = async () => {
        const next = data.notes.find(note => String(note.id) === row.dataset.noteId);
        if (next === active || !await mayLeaveNote()) return; active = next; paint();
      });
    };
    const paintTargets = () => {
      targets.innerHTML = Object.entries(labels).map(([target, label]) => `<label class="lee-memory-target${active && isSelected(target, active.id) ? ' active' : ''}">` +
        `<input type="checkbox" data-memory-target="${target}"${active?.id && isSelected(target, active.id) ? ' checked' : ''}>` +
        `<span><strong>${esc(label)}</strong><small>${target === 'agent' ? 'conversation + tools' : target === 'inline' ? 'notebook prompt cells' : 'one-shot suggestions'}</small></span></label>`).join('');
      $$('[data-memory-target]', targets).forEach(input => input.onchange = async () => {
        const target = input.dataset.memoryTarget, id = String(active.id);
        if (!id) { $('[data-note-status]', box).textContent = 'Routing will activate when you save this note.'; paintBudget(); return; }
        input.checked ? selected[target].add(id) : selected[target].delete(id);
        try {
          const result = await post('/agent/memory/select', {target, ids: [...selected[target]]});
          $('[data-note-status]', box).textContent = `${labels[target]} updated · about ${result.tokens.toLocaleString()} context tokens`;
          paintList($('[data-note-filter]', box).value); paintTargets(); paintBudget();
        } catch (e) { input.checked = !input.checked; status(e.message || String(e), 'err'); }
      });
    };
    const paintBudget = () => {
      if (!active) { $('[data-memory-budget]', box).textContent = 'Select a note to route it.'; return; }
      const tokens = Math.max(1, Math.ceil(noteText.value.length / 4));
      $('[data-memory-budget]', box).innerHTML = active.id
        ? `<strong>~${tokens.toLocaleString()} tokens</strong><span>this note · active on ${selectionCount(active.id)} of 3 surfaces</span>`
        : `<strong>Unsaved note</strong><span>Save it before adding it to model context.</span>`;
    };
    const paint = () => {
      empty.hidden = !!active; form.hidden = !active;
      $('[data-save-note]', box).disabled = !active; $('[data-delete-note]', box).disabled = !active;
      if (active) { title.value = active.title || ''; noteText.value = active.text || ''; }
      paintList($('[data-note-filter]', box).value); paintTargets(); paintBudget();
    };
    const newNote = async () => { if (!await mayLeaveNote()) return; active = {id: '', title: '', text: ''}; paint(); title.focus(); };
    $('[data-new-note]', box).onclick = newNote; $('[data-empty-new]', box).onclick = newNote;
    $('[data-note-filter]', box).oninput = e => paintList(e.target.value);
    const markDirty = () => { $('[data-note-status]', box).textContent = 'Unsaved changes'; paintBudget(); };
    title.oninput = markDirty;
    stateView.dom.addEventListener('input', markDirty);
    $('[data-save-note]', box).onclick = async () => {
      const button = $('[data-save-note]', box); button.disabled = true; button.textContent = 'Saving…';
      try {
        const oldId = String(active.id || ''), requestedTargets = $$('[data-memory-target]:checked', targets).map(input => input.dataset.memoryTarget);
        const result = await post('/agent/memory/save', {id: oldId, title: title.value, text: noteText.value, targets: requestedTargets});
        box.remove(); lee.memoryLoaded = false; status(oldId ? 'memory note updated' : 'memory note created', 'ok'); leeMemoryNotes();
      } catch (e) { button.disabled = false; button.textContent = 'Save note'; status(e.message || String(e), 'err'); }
    };
    $('[data-delete-note]', box).onclick = async () => {
      if (!active?.id || !await confirmDialog('delete memory note', `Delete “${active.title || 'Untitled note'}” from memory and every model route?`, 'delete')) return;
      await post('/agent/memory/delete', {id: active.id}); box.remove(); lee.memoryLoaded = false; status('memory note deleted', 'ok'); leeMemoryNotes();
    };
    paint();
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentMemory = leeAgentMemory;

function memoryRows(rows, kind = 'doc') {
  return rows.map((row, i) => {
    const title = row.breadcrumb || row.title || row.label || row.source || 'Untitled';
    const detail = row.source || row.summary || row.note || `${row.size || row.nchunks || 0} items`;
    const excerpt = (row.snippets || [])[0] || row.text || '';
    return `<button class="lee-memory-${kind}" data-i="${i}"><span class="lee-memory-index">${String(i + 1).padStart(2, '0')}</span>` +
      `<span class="lee-memory-copy"><strong>${esc(title)}</strong><small>${esc(detail)}</small>` +
      `${excerpt ? `<p>${esc(String(excerpt).replace(/\s+/g, ' ').slice(0, 220))}</p>` : ''}</span>` +
      `<span class="lee-memory-kind">${esc(row.kind || (kind === 'hit' ? 'section' : kind))}</span></button>`;
  }).join('');
}
async function leeMemoryHome() {
  const body = $('#memorybody'); if (!body) return;
  lee.memoryLoaded = 'loading'; leePane('right', true); leeRight('memory'); setMemoryView('sources');
  body.innerHTML = '<div class="lee-memory-empty">Opening durable memory…</div>';
  try {
    const d = await api('/memory/info'); lee.memoryLoaded = true; lee.memoryDocs = d.items || [];
    $('#memorystatus').textContent = `· ${d.documents} docs · ${d.nodes} sections`;
    body.innerHTML = lee.memoryDocs.length ? memoryRows(lee.memoryDocs) :
      '<div class="lee-memory-empty">Pages you read and research will be indexed here automatically.</div>';
    $$('.lee-memory-doc', body).forEach((row, i) => row.onclick = () => leeMemoryTree(lee.memoryDocs[i].id));
  } catch (e) { lee.memoryLoaded = false; body.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function leeMemoryPurge() {
  let docs = lee.memoryDocs;
  if (!docs) docs = (await api('/memory/info')).items || [];
  if (!docs.length) return status('memory is already empty', 'info');
  const m = modal(`<div class="lee-mhead">Purge memory<span class="sub">remove bad or irrelevant sources</span></div>` +
    `<div class="lee-memory-purge-list">${docs.map((doc, i) => `<label><input type="checkbox" value="${esc(doc.id)}">` +
      `<span><strong>${esc(doc.title)}</strong><small>${esc(doc.source || doc.kind || '')}</small></span></label>`).join('')}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn warn" data-selected>purge selected</button>` +
    `<span class="lee-spacer"></span><button class="lee-btn warn" data-all>purge everything</button></div>`);
  $('[data-selected]', m).onclick = async () => {
    const ids = $$('input:checked', m).map(x => x.value);
    if (!ids.length) return status('select at least one source to purge', 'err');
    if (!await confirmDialog('purge selected memory', `Remove ${ids.length} document${ids.length === 1 ? '' : 's'} and all indexed sections?`, 'purge')) return;
    await post('/memory/purge', {ids}); m.remove(); lee.memoryLoaded = false; lee.memoryDocs = null; leeMemoryHome();
  };
  $('[data-all]', m).onclick = async () => {
    if (!await confirmDialog('purge all research memory', `Remove all ${docs.length} documents, trees, chunks and vectors?`, 'purge')) return;
    await post('/memory/purge', {ids: null}); m.remove(); lee.memoryLoaded = false; lee.memoryDocs = null; leeMemoryHome();
  };
}
async function leeMemorySearch() {
  const input = $('#memoryquery'), body = $('#memorybody'), q = input?.value.trim(); if (!q || !body) return;
  body.innerHTML = '<div class="lee-memory-empty">Searching remembered sections…</div>';
  try {
    const d = await api('/memory/search?q=' + encodeURIComponent(q)); lee.memoryHits = d.results || [];
    $('#memorystatus').textContent = `· ${d.note || ''}`;
    body.innerHTML = lee.memoryHits.length ? memoryRows(lee.memoryHits, 'hit') : '<div class="lee-memory-empty">Nothing remembered matches this query.</div>';
    $$('.lee-memory-hit', body).forEach((row, i) => row.onclick = () => leeMemoryRead(lee.memoryHits[i].node_id));
  } catch (e) { body.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function leeMemoryTree(doc) {
  const body = $('#memorybody'); if (!body) return;
  body.innerHTML = '<div class="lee-memory-empty">Reading document structure…</div>';
  const d = await api('/memory/toc?doc=' + encodeURIComponent(doc || ''));
  const flatten = (node, depth = 0, out = []) => {
    if (node) { out.push({...node, depth}); (node.children || []).forEach(child => flatten(child, depth + 1, out)); }
    return out;
  };
  const document = (d.documents || [])[0], rows = document ? flatten(document.tree) : [];
  body.innerHTML = `<div class="lee-memory-tree-actions"><button class="lee-btn lee-memory-back" onclick="leeMemoryHome()">Back to memory</button>` +
    `${document ? '<button class="lee-btn warn" data-forget>Forget document</button>' : ''}</div>` +
    `<div class="lee-memory-breadcrumb">${esc(document?.title || 'Document tree')}</div>` +
    (rows.length ? rows.map((row, i) => `<button class="lee-memory-hit lee-memory-tree" style="--depth:${row.depth}" data-node="${esc(row.id)}">` +
      `<span class="lee-memory-index">${String(i + 1).padStart(2, '0')}</span><span class="lee-memory-copy"><strong>${esc(row.title)}</strong>` +
      `<small>${esc(row.summary || `${row.nchunks || 0} chunks`)}</small></span><span class="lee-memory-kind">L${row.level}</span></button>`).join('') :
      '<div class="lee-memory-empty">No section tree is available.</div>');
  $$('[data-node]', body).forEach(row => row.onclick = () => leeMemoryRead(row.dataset.node));
  const forget = $('[data-forget]', body);
  if (forget) forget.onclick = async () => {
    if (!await confirmDialog('forget research document', `Remove ${document.title} and all of its remembered sections?`, 'forget')) return;
    await post('/memory/forget', {id: document.doc_id}); lee.memoryLoaded = false; leeMemoryHome();
  };
}
async function leeMemoryRead(node) {
  if (!node) return;
  const body = $('#memorybody'); body.innerHTML = '<div class="lee-memory-empty">Assembling the section…</div>';
  const d = await api('/memory/read?node=' + encodeURIComponent(node)), section = d.section || {};
  body.innerHTML = `<button class="lee-btn lee-memory-back" onclick="leeMemoryHome()">Back to memory</button>` +
    `<div class="lee-memory-breadcrumb">${esc(section.breadcrumb || section.title || node)}</div><article class="lee-memory-reader"></article>`;
  renderMarkdown($('.lee-memory-reader', body), section.text || 'No section text was retained.');
}
async function leeMemoryTopics() {
  const body = $('#memorybody'); if (!body) return;
  lee.memoryLoaded = 'loading'; leePane('right', true); leeRight('memory'); setMemoryView('topics'); body.innerHTML = '<div class="lee-memory-empty">Clustering remembered research…</div>';
  const d = await api('/memory/clusters'); lee.memoryTopics = d.clusters || [];
  $('#memorystatus').textContent = `· ${d.note || 'topics'}`;
  body.innerHTML = lee.memoryTopics.length ? memoryRows(lee.memoryTopics, 'topic') : `<div class="lee-memory-empty">${esc(d.note || 'Not enough remembered material to form topics.')}</div>`;
  $$('.lee-memory-topic', body).forEach((row, i) => row.onclick = () => {
    const topic = lee.memoryTopics[i], members = topic.members || [];
    body.innerHTML = `<button class="lee-btn lee-memory-back" onclick="leeMemoryTopics()">Back to topics</button>` +
      `<div class="lee-memory-breadcrumb">${esc(topic.label || 'Topic')} · ${topic.size || members.length} sections</div>` +
      (members.length ? memoryRows(members, 'hit') : '<div class="lee-memory-empty">No representative sections.</div>');
    $$('.lee-memory-hit', body).forEach((member, at) => member.onclick = () => leeMemoryRead(members[at].node_id));
  });
}
window.leeMemoryHome = leeMemoryHome; window.leeMemorySearch = leeMemorySearch; window.leeMemoryPurge = leeMemoryPurge;
window.leeMemoryTree = leeMemoryTree; window.leeMemoryRead = leeMemoryRead; window.leeMemoryTopics = leeMemoryTopics;

function rememberAgentLive() {
  if (!lee.agentView || lee.agentView === 'live') lee.agentLive = $('#agentlog')?.innerHTML || '';
}
function restoreAgentLive() {
  const log = $('#agentlog'); if (!log) return;
  log.innerHTML = lee.agentLive || ''; lee.agentView = 'live';
  $('#agenthistory')?.classList.remove('active');
  log.scrollTop = log.scrollHeight;
}
function userMessage(text) {
  const raw = String(text || '').trim(), long = raw.length > 900 || raw.split('\n').length > 14;
  const card = document.createElement('section'); card.className = 'lee-user-message';
  const head = document.createElement('header');
  head.innerHTML = '<strong>You</strong><span>request</span>'; card.appendChild(head);
  if (!long) {
    const body = document.createElement('div'); body.className = 'lee-user-message-body';
    body.textContent = raw; card.appendChild(body); return card;
  }
  const lines = raw.split('\n');
  const preview = lines.slice(0, 6).join('\n').slice(0, 620).trimEnd();
  const body = document.createElement('div'); body.className = 'lee-user-message-body preview';
  body.textContent = preview + (preview.length < raw.length ? '\n…' : ''); card.appendChild(body);
  const more = document.createElement('details'); more.className = 'lee-user-message-more';
  more.innerHTML = `<summary>Show full request <span>${raw.length.toLocaleString()} characters · ${lines.length} lines</span>` +
    `<i class="lee-agent-step-chevron" aria-hidden="true"></i></summary><pre></pre>`;
  more.querySelector('pre').textContent = raw; card.appendChild(more);
  return card;
}
function usageMeta(usage, label = '', model = '') {
  if (!usage && !label) return null;
  const u = usage || {}, parts = [];
  if (Number(u.total)) parts.push(`${Number(u.total).toLocaleString()} tokens`);
  if (Number(u.input)) parts.push(`${Number(u.input).toLocaleString()} input`);
  if (Number(u.output)) parts.push(`${Number(u.output).toLocaleString()} output`);
  if (Number(u.cached)) parts.push(`${Number(u.cached).toLocaleString()} cached`);
  if (Number(u.reasoning)) parts.push(`${Number(u.reasoning).toLocaleString()} reasoning`);
  if (Number(u.cost)) parts.push(`$${Number(u.cost).toFixed(4)}`);
  if (!parts.length && label) parts.push(label);
  if (model || u.model) parts.push(String(model || u.model).split('/').pop());
  const el = document.createElement('footer'); el.className = 'lee-turn-usage';
  el.setAttribute('aria-label', 'Token usage and estimated cost for this turn');
  el.innerHTML = `<span class="lee-turn-usage-mark" aria-hidden="true">∑</span>` + parts.map((part, i) => `<span${i === parts.length - 1 ? ' class="model"' : ''}>${esc(part)}</span>`).join('');
  return el;
}

function renderTurns(log, turns, heading) {
  if (heading) log.insertAdjacentHTML('beforeend', `<div class="lee-vgroup">${esc(heading)}</div>`);
  for (const turn of (turns || [])) {
    const item = document.createElement('article'); item.className = 'lee-history-turn';
    item.innerHTML = `<div class="lee-history-meta"><span>${esc(turn.model)}</span>` +
      `<span>${esc(turn.plan?.route || 'direct')}</span></div>`;
    item.appendChild(userMessage(turn.prompt));
    if ((turn.activity || []).length) {
      const steps = document.createElement('div'); steps.className = 'lee-agent-steps';
      for (const activity of turn.activity) {
        const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
      }
      item.appendChild(steps);
    }
    const reply = document.createElement('div'); reply.className = 'lee-reply'; item.appendChild(reply);
    renderMarkdown(reply, turn.reply || '');
    const usage = usageMeta(turn.usage, turn.usage_label, turn.model); if (usage) item.appendChild(usage);
    log.appendChild(item);
  }
}
const sessionTime = s => s.started ? new Date(s.started * 1000).toLocaleString() : s.id.replace(/^agent_/, '');
async function showHistorySession(group, groups) {
  const log = $('#agentlog'); if (!log) return; log.innerHTML = '';
  const index = document.createElement('nav'); index.className = 'lee-history-index';
  const options = (groups || []).map(s => {
    const models = (s.models || []).map(m => m.split('/').pop()).join(' + ') || 'execution';
    const label = `${sessionTime(s)} · ${models} · ${s.turns.length} turn${s.turns.length === 1 ? '' : 's'}`;
    return `<option value="${esc(s.id)}"${s.id === group?.id ? ' selected' : ''}>${esc(label)}</option>`;
  }).join('');
  index.innerHTML = `<div class="lee-history-heading"><strong>History</strong>` +
    `<span>one continuous model context per session</span></div>` +
    `<select class="lee-select lee-history-select" aria-label="agent history session">${options}</select>` +
    `<span class="lee-history-runs">${group?.code || 0} kernel run${group?.code === 1 ? '' : 's'}</span>`;
  index.querySelector('select')?.addEventListener('change', e =>
    showHistorySession(groups.find(s => s.id === e.target.value), groups));
  log.appendChild(index);
  if (!group) { log.insertAdjacentHTML('beforeend', '<div class="lee-dim">(no sessions yet)</div>'); return; }
  log.insertAdjacentHTML('beforeend', `<div class="lee-history-session-head"><strong>${esc(sessionTime(group))}</strong>` +
    `<span>${group.context_continues ? 'context continued across these turns' : 'separate context'}</span></div>`);
  renderTurns(log, group.turns || [], 'conversation');
  if (group.code || group.id.startsWith('agent_')) {
    const transcript = await api('/agent/transcript?session=' + encodeURIComponent(group.id));
    if ((transcript.cells || []).length) {
      log.insertAdjacentHTML('beforeend', '<div class="lee-vgroup">code executed in this session</div>');
      renderSessionCells(log, transcript);
    }
  }
  log.scrollTop = 0;
}
async function leeAgentHistory() {
  if (lee.agentView === 'history') return restoreAgentLive();
  rememberAgentLive(); lee.agentView = 'history'; $('#agenthistory')?.classList.add('active');
  const d = await api('/agent/history');
  await showHistorySession((d.sessions || [])[0], d.sessions || []);
}
window.leeAgentHistory = leeAgentHistory;

async function leeAgentState() {
  try {
    const [draft, saved, template] = await Promise.all([api('/agent/state/draft'), api('/agent/states'), api('/agent/state/template')]);
    const rows = (saved.states || []).map(s => `<button class="lee-agent-state-row" data-id="${esc(s.id)}">` +
      `<strong>${esc(s.title)}</strong><span>${esc(new Date((s.added_at || 0) * 1000).toLocaleString())}</span></button>`).join('');
    const box = modal(`<div class="lee-mhead">Agent state<span class="sub">remembered rules that stay visible and follow the code</span></div>` +
      `<section class="lee-agent-state-onboard${saved.active ? ' configured' : ''}"${saved.active ? ' hidden' : ''}><div><strong>Start with a worked template</strong>` +
      `<span>Describe what you want this agent to do. The configured summary model fills a complete charter using only tools that are actually installed.</span></div>` +
      `<input class="lee-input" id="agentstateintent" placeholder="e.g. Maintain this Python project; inspect before editing and run focused tests">` +
      `<button class="lee-btn go" data-bootstrap>Generate my charter</button><button class="lee-btn" data-template>Use blank template</button></section>` +
      `<div class="lee-agent-state-grid"><section><div class="lee-agent-state-controls"><label>Where this applies<select class="lee-select" id="agentstatelayer">` +
      `${['organization','project','task','preferences','branch','ephemeral'].map(x => `<option value="${x}"${x === 'task' ? ' selected' : ''}>${x}</option>`).join('')}</select></label>` +
      `<button class="lee-btn" data-update>Refresh from code</button><button class="lee-btn" data-diagnose>Check state</button></div>` +
      `<label class="lee-fieldlabel">Title<input class="lee-input" id="agentstatetitle" value="Working state"></label>` +
      `<div class="lee-state-editor-head"><span>Markdown charter</span><button class="lee-btn" data-add-rule>Add rule</button>` +
      `<button class="lee-btn" data-add-check>Add verification</button><button class="lee-btn" data-add-tool>Add tool route</button>` +
      `<button class="lee-btn" data-preview-state>Preview</button></div><div class="lee-agent-state-editor" id="agentstatetext"></div>` +
      `<div class="lee-agent-state-help" data-state-help>Keep goal, constraints, progress, decisions, next steps, and critical context. ` +
      `This is an explicit briefing, not hidden chat history.</div></section>` +
      `<section class="lee-agent-state-reference"><nav class="lee-state-ref-tabs"><button class="active" data-ref="conversation">Conversation</button>` +
      `<button data-ref="tools">Tools</button><button data-ref="preview">Preview</button><button data-ref="saved">Saved</button></nav>` +
      `<div class="lee-state-ref-pane active" data-ref-pane="conversation"><pre class="lee-agent-conversation">${esc(draft.conversation || '(no completed turns)')}</pre></div>` +
      `<div class="lee-state-ref-pane" data-ref-pane="tools"><div class="lee-state-tool-list">${template.tools.map(t => `<button data-tool-name="${esc(t.name)}"><strong>${esc(t.name)}</strong><span>${esc(t.group)} · ${esc(t.description)}</span></button>`).join('')}</div></div>` +
      `<div class="lee-state-ref-pane lee-md" data-ref-pane="preview" id="agentstatepreview"></div>` +
      `<div class="lee-state-ref-pane" data-ref-pane="saved"><div class="lee-agent-state-list">${rows || '<div class="lee-dim">No saved states yet.</div>'}</div></div></section></div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" data-save>Save to memory + activate</button>` +
      `<button class="lee-btn" data-activate>Activate without saving</button>` +
      `<span class="lee-dim">Drag the lower-right edge to resize · double-click the title to expand.</span></div>`,
      null, null, {className: 'lee-agent-state-modal', storageKey: 'agent-state'});
    const text = $('#agentstatetext', box), layer = $('#agentstatelayer', box);
    const stateView = createEditor(text, {doc: '', lang: 'markdown', lineNums: true, lintPath: '<agent-state>',
      placeholder: '# Agent charter\n\nDescribe how this agent should work…'});
    Object.defineProperty(text, 'value', {get: () => LeeCM.getDoc(stateView), set: value => LeeCM.setDoc(stateView, String(value || ''))});
    const insertStateMarkdown = value => {
      const at = LeeCM.cursor(stateView), prefix = at && !text.value.slice(0, at).endsWith('\n') ? '\n' : '';
      LeeCM.replaceRange(stateView, at, at, prefix + value); LeeCM.focus(stateView);
    };
    const showReference = name => {
      $$('.lee-state-ref-tabs button', box).forEach(b => b.classList.toggle('active', b.dataset.ref === name));
      $$('.lee-state-ref-pane', box).forEach(p => p.classList.toggle('active', p.dataset.refPane === name));
      if (name === 'preview') renderMarkdown($('#agentstatepreview', box), text.value, true);
    };
    $$('.lee-state-ref-tabs button', box).forEach(b => b.onclick = () => showReference(b.dataset.ref));
    $('[data-preview-state]', box).onclick = () => showReference('preview');
    $('[data-add-rule]', box).onclick = () => insertStateMarkdown('\n- [Write a clear, testable rule.]');
    $('[data-add-check]', box).onclick = () => insertStateMarkdown('\n- [Describe the evidence required before completion.]');
    $('[data-add-tool]', box).onclick = () => showReference('tools');
    $$('.lee-state-tool-list button', box).forEach(b => b.onclick = () => {
      const tool = template.tools.find(t => t.name === b.dataset.toolName);
      insertStateMarkdown(`\n- ${tool.name} → ${tool.description}`); showReference('preview');
    });
    const loadLayer = () => { text.value = saved.layers?.[layer.value]?.text || (layer.value === 'task' ? draft.state : ''); };
    loadLayer(); layer.onchange = loadLayer;
    $('[data-template]', box).onclick = async () => {
      const d = await api('/agent/state/template'); text.value = d.template + '\n\n' + d.catalog;
      $('[data-state-help]', box).textContent = 'Template loaded. Replace bracketed prompts, then activate or save it.';
    };
    $('[data-bootstrap]', box).onclick = async () => {
      const button = $('[data-bootstrap]', box); button.disabled = true; button.textContent = 'Generating…';
      try {
        const d = await post('/agent/state/bootstrap', {intent: $('#agentstateintent', box).value});
        text.value = d.text; $('#agentstatetitle', box).value = ($('#agentstateintent', box).value || 'Workspace agent charter').slice(0, 80);
        $('[data-state-help]', box).textContent = `Drafted with ${d.model}. Read every rule, then save + activate.`;
      } catch (e) { $('[data-state-help]', box).textContent = e.message || String(e); }
      finally { button.disabled = false; button.textContent = 'Generate my charter'; }
    };
    $('[data-update]', box).onclick = async () => {
      const d = await post('/agent/state/update', {current: text.value, conversation: draft.conversation});
      const review = modal(`<div class="lee-mhead">Review proposed state update<span class="sub">nothing changes until you apply it</span></div>` +
        `<div class="lee-diff lee-state-update-diff">${diffHtml(d.diff.rows || [])}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-accept>Apply to editor</button>` +
        `<button class="lee-btn" data-reject>Keep current state</button></div>`);
      $('[data-accept]', review).onclick = () => { text.value = d.text; review.remove(); $('[data-state-help]', box).textContent = 'Proposed update applied to the editor. Review before saving or activating.'; };
      $('[data-reject]', review).onclick = () => review.remove();
    };
    $('[data-diagnose]', box).onclick = async () => {
      const d = await post('/agent/state/diagnostics', {text: text.value});
      $('[data-state-help]', box).textContent = `${d.tokens} tokens` +
        (d.missing_paths.length ? ` · missing paths: ${d.missing_paths.join(', ')}` : ' · paths current') +
        (d.duplicate_headings.length ? ` · duplicate headings: ${d.duplicate_headings.join(', ')}` : '');
    };
    const markActive = () => {
      const badge = $('#agentnames'); if (badge) badge.textContent = 'state active';
      $('.lee-agent-welcome', $('#agentlog'))?.remove();
    };
    $('[data-save]', box).onclick = async () => {
      const d = await post('/agent/state/save', {title: $('#agentstatetitle', box).value, text: text.value, layer: layer.value, activate: true});
      markActive(); status(d.saved?.skipped ? 'state already in memory and activated' : 'state saved to memory and activated', 'ok'); box.remove();
    };
    $('[data-activate]', box).onclick = async () => {
      await post('/agent/state/activate', {text: text.value, layer: layer.value});
      markActive(); status('starting state activated without saving', 'ok'); box.remove();
    };
    $$('.lee-agent-state-row', box).forEach(row => row.onclick = async () => {
      const compared = await post('/agent/state/compare', {id: row.dataset.id, current: text.value});
      const review = modal(`<div class="lee-mhead">Compare state revision<span class="sub">choose how this revision enters ${esc(layer.value)}</span></div>` +
        `<div class="lee-diff lee-state-update-diff">${diffHtml(compared.diff.rows || [])}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-replace>Replace + activate</button>` +
        `<button class="lee-btn" data-merge>Merge below current</button><button class="lee-btn" data-cancel>Cancel</button></div>`);
      $('[data-replace]', review).onclick = async () => {
        const d = await post('/agent/state/load', {id: row.dataset.id, layer: layer.value}); text.value = d.state;
        review.remove(); $$('.lee-agent-state-row', box).forEach(x => x.classList.toggle('active', x === row)); status('saved revision restored and active', 'ok');
      };
      $('[data-merge]', review).onclick = () => { text.value = text.value.trim() + '\n\n' + compared.state.trim(); review.remove(); status('revision merged into editor; review before activation', 'ok'); };
      $('[data-cancel]', review).onclick = () => review.remove();
    });
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeAgentState = leeAgentState;

function renderSessionCells(log, d) {
  if (d.path) log.insertAdjacentHTML('beforeend', `<div class="lee-session-path">${esc(d.path)}</div>`);
  for (const [i, cell] of (d.cells || []).entries()) {
    if (cell.cell_type === 'markdown') {
      const md = document.createElement('div'); md.className = 'lee-session-markdown';
      renderMarkdown(md, cell.source); log.appendChild(md); continue;
    }
    const details = document.createElement('details'); details.className = 'lee-session-code';
    const first = (cell.source || '').split('\n').find(x => x.trim()) || '(empty code cell)';
    details.innerHTML = `<summary><span>run ${i + 1}</span><code>${esc(first)}</code>` +
      `<span class="lee-agent-step-chevron" aria-hidden="true"></span></summary><div class="lee-session-code-body"></div>`;
    let mounted = false;
    details.ontoggle = () => {
      if (!details.open || mounted) return; mounted = true;
      requestAnimationFrame(() => mountCodeSurface($('.lee-session-code-body', details), cell.source, 'python', true));
    };
    log.appendChild(details);
  }
}

function agentLog(html) {
  const log = $('#agentlog');
  // Never use `innerHTML +=`: it reparses every existing child and silently detaches all
  // checkpoint, fork, rollback, CodeMirror, and disclosure handlers already in the log.
  log.insertAdjacentHTML('beforeend', html);
  log.scrollTop = log.scrollHeight;
}

/* A write pauses Rishi's tool loop until it is answered. Keep the question in the agent
 * pane rather than a modal, so the rest of the IDE remains usable while the model waits.
 * The same event is used by agent-chat and notebook prompt-cell streams. */
const approvalCards = new Map(), resolvedProposalCards = [];
function proposalArgs(card) {
  const schema = card._schema, args = {};
  for (const field of (schema?.fields || [])) {
    const input = card.querySelector(`[data-field="${CSS.escape(field.name)}"]`);
    if (!input) continue;
    if (field.kind === 'boolean') args[field.name] = input.checked;
    else {
      const raw = input._leeView ? LeeCM.getDoc(input._leeView) : input.value;
      if (!field.required && raw === '') continue;
      if (field.kind === 'integer') args[field.name] = Number.parseInt(raw, 10);
      else if (field.kind === 'number') args[field.name] = Number.parseFloat(raw);
      else args[field.name] = raw;
      if (field.required && (args[field.name] === '' || Number.isNaN(args[field.name])))
        throw new Error(`${field.name} is required`);
    }
  }
  return args;
}
function proposalFields(schema, args) {
  return (schema?.fields || []).map(field => {
    const value = args[field.name] ?? field.default ?? '', required = field.required ? ' required' : '';
    if (field.kind === 'boolean')
      return `<label class="lee-proposal-check"><input type="checkbox" data-field="${esc(field.name)}"${value ? ' checked' : ''}>${esc(field.name)}</label>`;
    const type = field.kind === 'integer' || field.kind === 'number' ? 'number' : 'text';
    const control = field.multiline
      ? `<div class="lee-proposal-field-editor" data-field="${esc(field.name)}" data-value="${esc(value)}"${required}></div>`
      : `<input class="lee-input" type="${type}" data-field="${esc(field.name)}" value="${esc(value)}"${required}>`;
    return `<label><span>${esc(field.name)}${field.required ? ' *' : ''}</span>${control}</label>`;
  }).join('');
}
function mountProposalEditors(card) {
  $$('[data-field-editor], .lee-proposal-field-editor', card).forEach(host => {
    if (host._leeView) return;
    const field = host.dataset.field || '', tool = $('[data-tool]', card)?.value || '';
    const lang = field === 'commands' ? 'json' : field === 'text' || field === 'source'
      ? codeLang('', proposalArgsSafe(card).path || '') : tool.includes('python') ? 'python' : 'text';
    host._leeView = createEditor(host, {doc: host.dataset.value || '', lang, lineNums: true});
  });
}
function proposalArgsSafe(card) { try { return proposalArgs(card); } catch (_) { return {}; } }
function groupedToolOptions(schemas, selected) {
  const groups = new Map();
  for (const schema of schemas) {
    if (!groups.has(schema.group)) groups.set(schema.group, []);
    groups.get(schema.group).push(schema);
  }
  return [...groups].map(([group, tools]) => `<optgroup label="${esc(group)}">` + tools.map(tool =>
    `<option value="${esc(tool.name)}"${tool.name === selected ? ' selected' : ''}>${esc(tool.name)} — ${esc(tool.description)}</option>`).join('') + '</optgroup>').join('');
}
function previewContent(preview) {
  if (!preview) return '<div class="lee-proposal-empty">No preview available.</div>';
  if (preview.kind === 'diff') return `<div class="lee-diff">${diffHtml(preview.rows || [])}</div>`;
  return `<pre class="lee-proposal-code">${esc(preview.text || '')}</pre>`;
}
async function refreshProposalPreview(card) {
  const host = $('[data-preview-body]', card), error = $('.lee-proposal-error', card);
  if (!host) return;
  try {
    const args = card._previewArgs || proposalArgs(card), tool = $('[data-tool]', card).value;
    card._previewArgs = null;
    host.innerHTML = '<div class="lee-proposal-loading"><i></i><i></i><i></i><span>Building dry-run preview</span></div>';
    const d = await post('/agent/tool-preview', {tool, args});
    host.innerHTML = previewContent(d.preview); error.textContent = '';
  } catch (e) { host.innerHTML = ''; error.textContent = e.message || String(e); }
}
function checkpointExplanation(tool, args = {}, schema = {}) {
  const target = args.path ? compactPath(args.path) : args.cwd ? compactPath(args.cwd) : '';
  if (tool === 'run_shell') return {
    title: 'Command approval',
    lead: `The agent wants to run a shell command${target ? ` in ${target}` : ''}. Nothing runs until you approve.`,
    detail: 'Commands can read files, use the network, start processes, and change data. Open “Edit call” to review or change the command.'};
  if (tool === 'run_python') return {
    title: 'Python approval', lead: 'The agent wants to execute Python in the live workspace. Nothing runs until you approve.',
    detail: 'This can change variables and process state. Open “Edit call” to review or change the code.'};
  if (schema.changes_state) return {
    title: 'Change approval', lead: `The agent wants to change ${target || 'the workspace'}. Nothing changes until you approve.`,
    detail: 'Review the preview, edit the call if needed, then choose how far the agent may continue.'};
  return {title: 'Tool approval', lead: `The agent wants to use ${tool}. Nothing runs until you approve.`,
    detail: 'This is a read-only call. You can review its inputs now and run it again later with different inputs.'};
}
function checkpointResult(detail, ok, secs) {
  const result = document.createElement('details'); result.className = 'lee-checkpoint-result';
  const summary = document.createElement('summary');
  summary.innerHTML = `<strong>${ok ? 'Completed' : 'Failed'}</strong><span>${Number(secs || 0).toFixed(1)}s · View output</span>`;
  const pre = document.createElement('pre'); pre.textContent = readableDetail(detail);
  result.append(summary, pre); return result;
}
function showApproval(a) {
  if (!a?.id || approvalCards.has(a.id)) return;
  leePane('right', true); leeRight('agent');
  if (lee.agentView && lee.agentView !== 'live') restoreAgentLive();
  const log = $('#agentlog'); if (!log) return;
  const schemas = a.schemas || [], byName = new Map(schemas.map(s => [s.name, s]));
  const card = document.createElement('section');
  card.className = 'lee-approval lee-proposal proposed'; card.dataset.id = a.id; card.dataset.tool = a.tool; card.tabIndex = -1;
  const pendingRow = [...$$('.lee-agent-step.pending', log)].at(-1);
  if (pendingRow) { pendingRow.hidden = true; card._activityRow = pendingRow; }
  card._schema = byName.get(a.tool) || {name: a.tool, fields: Object.keys(a.args || {}).map(name => ({name, kind: 'string'}))};
  const explanation = checkpointExplanation(a.tool, a.args, card._schema);
  card.innerHTML = `<header class="lee-approval-head"><span class="lee-proposal-mark" aria-hidden="true"></span>` +
    `<span class="lee-checkpoint-title"><strong>${esc(explanation.title)}</strong><small><b>${esc(a.control || 'guided')}</b> paused for your decision</small></span>` +
    `<kbd>↵ run&nbsp;&nbsp; ⇧↵ don’t run&nbsp;&nbsp; E edit&nbsp;&nbsp; S steer</kbd></header>` +
    `<div class="lee-checkpoint-intro"><strong>${esc(explanation.lead)}</strong><span>${esc(explanation.detail)}</span></div>` +
    `<div class="lee-approval-summary"><span>Agent’s reason</span>${esc(a.summary || '')}</div>` +
    `<nav class="lee-proposal-tabs"><button class="active" data-tab="preview">What will happen</button>` +
    `<button data-tab="call">Edit call</button><button data-tab="json">Raw JSON</button></nav>` +
    `<section class="lee-proposal-pane active" data-pane="preview"><div data-preview-body>` +
    `<pre class="lee-proposal-code">${esc(a.preview || '')}</pre></div></section>` +
    `<section class="lee-proposal-pane" data-pane="call"><div class="lee-proposal-fields">` +
    `<label><span>Tool</span><select class="lee-select" data-tool>${groupedToolOptions(schemas, a.tool)}</select></label>` +
    `<div data-schema-fields>${proposalFields(card._schema, a.args || {})}</div></div></section>` +
    `<section class="lee-proposal-pane" data-pane="json"><textarea class="lee-input lee-proposal-json" data-args spellcheck="false"></textarea></section>` +
    `<div class="lee-proposal-error" role="alert"></div>` +
    `<div class="lee-proposal-steer"><label><span>If you don’t run it, tell the agent what to do instead</span>` +
    `<input class="lee-input" data-note placeholder="Optional: use another approach, inspect a different file…"></label></div>` +
    `<footer class="lee-approval-actions"><button class="lee-btn warn" data-ok="0">Don’t run</button>` +
    `<span class="lee-spacer"></span><label class="lee-run-policy-label"><span>After this</span>` +
    `<select class="lee-select" data-run-policy title="how far the agent may continue without another pause">` +
    `<option value="once">Pause again</option><option value="count:3">Allow next 3 tools</option>` +
    `<option value="until_write">Allow reads, pause before changes</option><option value="reads">Allow read-only tools</option>` +
    `<option value="until_failure">Continue until a tool fails</option><option value="completion">Continue until finished</option>` +
    `<option value="approve_session">Trust changes for this session</option></select></label>` +
    `<button class="lee-btn go" data-ok="1">Run this tool</button></footer>`;
  const raw = $('[data-args]', card); raw.value = JSON.stringify(a.args || {}, null, 2); mountProposalEditors(card);
  const switchTab = name => {
    $$('.lee-proposal-tabs button', card).forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    $$('.lee-proposal-pane', card).forEach(p => p.classList.toggle('active', p.dataset.pane === name));
    if (name === 'json') { try { raw.value = JSON.stringify(proposalArgs(card), null, 2); } catch (_) {} }
    if (name === 'preview') refreshProposalPreview(card);
  };
  $$('.lee-proposal-tabs button', card).forEach(b => b.onclick = () => {
    if (b.dataset.tab === 'preview') { try { card._previewArgs = argsFromUI(); } catch (_) {} }
    switchTab(b.dataset.tab);
  });
  $('[data-tool]', card).onchange = e => {
    card._schema = byName.get(e.target.value) || {name: e.target.value, fields: []};
    $('[data-schema-fields]', card).innerHTML = proposalFields(card._schema, {});
    mountProposalEditors(card); switchTab('call');
  };
  const argsFromUI = () => {
    if ($('[data-pane="json"]', card).classList.contains('active')) {
      const parsed = JSON.parse(raw.value || '{}');
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('arguments must be a JSON object');
      return parsed;
    }
    return proposalArgs(card);
  };
  const answer = async ok => {
    const buttons = $$('button', card), error = $('.lee-proposal-error', card);
    // These are two different HITL decisions, not one form with a boolean switch.
    // Approval executes the displayed call and therefore must parse and validate edits.
    // Rejection executes no call, so malformed/missing arguments must never trap the user.
    let args = null, tool = null, changed = false;
    if (ok) {
      try {
        args = argsFromUI(); tool = $('[data-tool]', card).value || a.tool;
        changed = tool !== a.tool || JSON.stringify(args) !== JSON.stringify(a.args || {});
        error.textContent = '';
      } catch (e) { switchTab('call'); error.textContent = e.message || String(e); return; }
    }
    buttons.forEach(b => b.disabled = true);
    try {
      const note = $('[data-note]', card).value || '';
      if (ok) {
        const spec = $('[data-run-policy]', card).value, [policy, count] = spec.split(':');
        if (!['once', 'approve_session'].includes(policy))
          await post('/agent/run-policy', {policy, count: Number(count || 1)});
      }
      const session = ok && $('[data-run-policy]', card).value === 'approve_session';
      await post('/agent/approve', {id: a.id, ok, note, session, tool, args});
      card.classList.remove('proposed'); card.classList.add(ok ? 'running' : 'refused'); if (changed) card.classList.add('edited');
      const checkpointState = $('.lee-checkpoint-title small', card);
      if (checkpointState) checkpointState.textContent = ok
        ? (changed ? 'You edited the call · running now' : 'You approved it · running now')
        : 'You chose not to run it';
      const resolvedTool = ok ? tool : a.tool;
      card.dataset.tool = resolvedTool; card.dataset.resolvedTool = resolvedTool;
      card.dataset.retryable = String(!!byName.get(resolvedTool)?.retryable);
      resolvedProposalCards.push(card);
      $('.lee-approval-actions', card).innerHTML = `<span>${ok ? (changed ? 'Edited call is running' : 'Running approved tool') : (note ? 'Not run · your direction was sent to the agent' : 'Not run')}</span>` +
        (ok && card.dataset.retryable === 'true' ? `<button class="lee-btn" data-retry title="Run this read-only tool again without changing the conversation">Run again</button>` : '') +
        (ok && ['edit_file','create_file'].includes(resolvedTool) ? `<button class="lee-btn warn" data-rollback disabled>Undo file change</button>` : '');
      $('[data-retry]', card)?.addEventListener('click', () => retryProposal(card, resolvedTool, args));
      const rollback = $('[data-rollback]', card);
      if (rollback) { setTimeout(() => rollback.disabled = false, 700); rollback.onclick = () => rollbackProposal(card, a.id); }
      status(ok ? `${changed ? 'edited and ran' : 'ran'} ${resolvedTool}` : `rejected ${a.tool}`, ok ? 'ok' : 'err');
    } catch (e) { buttons.forEach(b => b.disabled = false); error.textContent = String(e.message || e); }
  };
  $('[data-ok="1"]', card).onclick = () => answer(true);
  $('[data-ok="0"]', card).onclick = () => answer(false);
  card.onkeydown = e => {
    if (e.target.matches('input, textarea, select') && e.key !== 'Escape' && !(e.key === 'Enter' && (e.metaKey || e.ctrlKey))) return;
    if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); answer(false); }
    else if (e.key === 'Enter') { e.preventDefault(); answer(true); }
    else if (/^[1-6]$/.test(e.key)) { e.preventDefault(); $('[data-run-policy]', card).selectedIndex = Number(e.key) - 1; }
    else if (e.key.toLowerCase() === 'e') { e.preventDefault(); switchTab('call'); card.querySelector('[data-field], [data-tool]')?.focus(); }
    else if (e.key.toLowerCase() === 's') { e.preventDefault(); $('[data-note]', card).focus(); }
    else if (e.key === 'Escape') switchTab('preview');
  };
  log.appendChild(card); approvalCards.set(a.id, card); card.focus(); log.scrollTop = log.scrollHeight;
  refreshProposalPreview(card); updateAgentRunstrip({waiting: a.tool});
  status(`${a.tool} is waiting at a checkpoint`, 'err');
}

function decodeResponseEntities(text) {
  const area = document.createElement('textarea'); let value = String(text || '');
  for (let i = 0; i < 3 && /&(?:#\d+|#x[\da-f]+|amp|lt|gt|quot|apos);/i.test(value); i++) {
    area.innerHTML = value; const decoded = area.value;
    if (decoded === value) break; value = decoded;
  }
  return value;
}
function editableResponse(raw) {
  const tools = '(?:run_shell|run_python|inspect_python|grep|search_code|similar_code|list_files|ls|view_file|create_file|edit_file|replace_text|view_cell|edit_cell|add_cell|web_search|read_url|research|delegate_[\\w-]+)';
  let text = decodeResponseEntities(raw)
    .replace(/\n?\s*<details>\s*<summary>result<\/summary>[\s\S]*?<\/details>\s*/gi, '\n');
  text = text.split('\n').filter(line =>
    !new RegExp(`^\\s*-\\s*[^\\w<]{0,6}\\s*<code>${tools}\\s*\\(`, 'i').test(line) &&
    !/^\s*(?:#{1,4}\s*)?what i did\s*$/i.test(line)).join('\n');
  return text.replace(/\n{3,}/g, '\n\n').trim();
}

function addResponseRevision(out, turnId, raw, capabilities = {}) {
  if (!turnId || !out || !raw.trim()) return;
  const bar = document.createElement('div'); bar.className = 'lee-response-revision';
  const reviseWhy = capabilities.revisable ? 'Correct this answer and continue the next turn from your version'
    : 'Unavailable: this turn failed before an assistant response entered model history';
  const undoWhy = capabilities.undoable ? `Restore ${capabilities.files.length} file${capabilities.files.length === 1 ? '' : 's'} changed by this turn`
    : 'Unavailable: this turn made no reversible file changes';
  bar.innerHTML = `<span>turn ${esc(turnId.split(':').at(-1))}</span>` +
    `<button class="lee-btn" data-revise title="${esc(reviseWhy)}"${capabilities.revisable ? '' : ' disabled'}>Edit what agent remembers</button>` +
    `<button class="lee-btn warn" data-undo title="${esc(undoWhy)}"${capabilities.undoable ? '' : ' disabled'}>Undo turn</button>`;
  const undoButton = $('[data-undo]', bar), reviseButton = $('[data-revise]', bar);
  undoButton.onclick = async () => {
    try {
      const tx = await api('/agent/turn-transaction?turn_id=' + encodeURIComponent(turnId));
      const files = tx.transaction.files || [], warning = (tx.transaction.irreversible || []).length
        ? `\n\nCannot undo external effects: ${tx.transaction.irreversible.join(', ')}` : '';
      if (!await confirmDialog('Undo agent turn', `Restore ${files.length} file${files.length === 1 ? '' : 's'} changed by this turn?${warning}`, 'restore files')) return;
      const d = await post('/agent/rollback-turn', {turn_id: turnId});
      for (const path of d.paths || []) if (path === lee.path && !$('.lee-tab.active')?.classList.contains('dirty')) await takeDiskVersion(path);
      bar.classList.add('rolled-back'); $('[data-undo]', bar).disabled = true; status('turn changes rolled back', 'ok');
    } catch (e) { status(e.message || String(e), 'err'); }
  };
  reviseButton.onclick = () => {
    const original = editableResponse(raw);
    const box = modal(`<div class="lee-mhead">Shape the next turn<span class="sub">edit what the agent remembers, not the files it touched</span></div>` +
      `<section class="lee-revision-explainer"><strong>You are correcting the conversation.</strong>` +
      `<span>Tools will not run again and files will not change. The agent’s next reply will continue as if it gave your edited answer. The original stays in history.</span></section>` +
      `<div class="lee-revision-layout"><label class="lee-revision-editor"><span>Answer the agent should remember <b>Markdown</b></span>` +
      `<textarea class="lee-keyedit" data-revision spellcheck="true" aria-label="answer the agent should remember"></textarea></label>` +
      `<section class="lee-revision-preview"><header><span>How it will read</span><small>live preview</small></header>` +
      `<div class="lee-md" data-revision-preview></div></section></div>` +
      `<div class="lee-mfoot"><button class="lee-btn" data-cancel>Keep original</button><span class="lee-spacer"></span>` +
      `<span class="lee-dim">Creates a new conversation branch</span><button class="lee-btn go" data-apply>Use edited answer</button></div>`,
      null, null, {className: 'lee-response-editor-modal', storageKey: 'response-editor'});
    const editor = $('[data-revision]', box), preview = $('[data-revision-preview]', box);
    editor.value = original;
    let previewTimer = null;
    const paint = () => { clearTimeout(previewTimer); previewTimer = setTimeout(() => renderMarkdown(preview, editor.value), 90); };
    editor.addEventListener('input', paint); paint();
    $('[data-cancel]', box).onclick = () => box.remove();
    $('[data-apply]', box).onclick = async () => {
      const text = editor.value.trim();
      if (!text) return status('the remembered answer cannot be empty', 'err');
      const d = await post('/agent/revise', {turn_id: turnId, text});
      renderMarkdown(out, text); out.dataset.userRevised = '1';
      bar.innerHTML = `<span>Your edited answer now guides the next turn · ${esc(d.branch_id)}</span>`;
      box.remove(); status('edited answer is now the active conversation branch', 'ok');
    };
  };
  out.after(bar);
}

async function retryProposal(card, tool, args) {
  const copy = structuredClone(args), number = card.querySelectorAll('.lee-proposal-branch').length + 1;
  try {
    const d = await post('/agent/retry-tool', {tool, args: copy});
    const row = document.createElement('section'); row.className = 'lee-proposal-branch';
    row.innerHTML = `<header><strong>Rerun ${number}</strong><span>${esc(tool)} completed with the inputs shown below</span>` +
      `<button class="lee-btn" data-edit-retry>Edit inputs and run</button></header>` +
      `<details class="lee-checkpoint-result"><summary><strong>Result</strong><span>View output</span></summary><pre>${esc(d.result)}</pre></details>` +
      `<footer><span>This result is not in the conversation yet.</span><button class="lee-btn" data-use-result>Use in next message</button></footer>`;
    $('[data-edit-retry]', row).onclick = async () => {
      const text = await textDialog('Run tool with different inputs', 'Arguments as JSON', JSON.stringify(copy, null, 2)); if (!text) return;
      try { await retryProposal(card, tool, JSON.parse(text)); }
      catch (e) { status(e.message || String(e), 'err'); }
    };
    $('[data-use-result]', row).onclick = () => {
      const prompt = $('#agentprompt'); if (!prompt) return;
      const result = String(d.result || '').slice(0, 20_000);
      prompt.value = `Use this rerun of ${tool} to reconsider your previous answer. Explain what changed and what I should do next.\n\n<rerun-result tool="${tool}">\n${result}\n</rerun-result>`;
      prompt.dispatchEvent(new Event('input', {bubbles: true})); prompt.focus();
      row.scrollIntoView({block: 'nearest'}); status('rerun result added to your next message; review it before sending', 'ok');
    };
    card.appendChild(row); status(`rerun ${number} completed; previous conversation is unchanged`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function rollbackProposal(card, id) {
  try {
    const d = await post('/agent/rollback-tool', {id});
    card.classList.add('rolled-back'); $('[data-rollback]', card).disabled = true;
    status(`${d.path.split('/').pop()} rolled back`, 'ok');
    if (d.path === lee.path && !$('.lee-tab.active')?.classList.contains('dirty')) await takeDiskVersion(d.path);
  } catch (e) { status(e.message || String(e), 'err'); }
}
function runPolicyLabel(policy) {
  if (!policy) return '';
  const names = {once: 'next call', count: `next ${policy.remaining}`, until_write: 'until next write',
    reads: 'read-only calls', until_failure: 'until failure', completion: 'to completion'};
  return names[policy.kind] || policy.kind;
}
function updateAgentRunstrip(state = {}) {
  const strip = $('#agentrunstrip'); if (!strip) return;
  strip.hidden = !lee.agentBusy && !state.waiting;
  const label = state.waiting ? `Waiting · ${state.waiting}`
    : state.queued_steer ? 'Steering queued · applies after current call'
    : state.run_policy ? `Running automatically · ${runPolicyLabel(state.run_policy)}`
    : `${($('#agentcontrol')?.value || 'guided').toUpperCase()} · agent working`;
  $('.lee-agent-run-state', strip).textContent = label;
  strip.onclick = e => {
    if (state.waiting && !e.target.closest('button')) approvalCards.get([...approvalCards.keys()].at(-1))?.scrollIntoView({block: 'center'});
  };
}
async function pauseAgentAfterCurrent() {
  const d = await post('/agent/run-policy', {policy: 'pause'}); updateAgentRunstrip(d);
  status('agent will pause before the next call', 'ok');
}
async function leeQueueSteer() {
  const input = $('#agentsteer'), text = input?.value.trim(); if (!text) return status('write a steering instruction first', 'err');
  try {
    const d = await post('/agent/steer', {text}); input.value = '';
    const queue = $('#agentsteerqueue');
    queue.innerHTML = `<span>Steering queued</span><strong>${esc(text)}</strong><button type="button">Cancel</button>`;
    $('button', queue).onclick = async () => { await post('/agent/steer', {cancel: true}); queue.innerHTML = ''; updateAgentRunstrip(); };
    updateAgentRunstrip(d); status('steering queued after the current call', 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeQueueSteer = leeQueueSteer;

async function pollApproval() {
  try {
    const r = await api('/agent/approval');
    if (r.pending) showApproval(r.pending);
  } catch (_) {}
}

function readableDetail(value) {
  const text = String(value || '');
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}
function renderAgentStep(row, a) {
  const wasOpen = row.open;
  for (const v of (row._leeViews || [])) try { LeeCM.destroy(v); } catch {}
  row._leeViews = []; row.innerHTML = '';
  const deferredEditors = [];
  row.className = `lee-agent-step kind-${a.kind || 'tool'} ${a.done ? (a.ok ? 'done' : 'failed') : 'pending'}`;
  const summary = document.createElement('summary');
  summary.innerHTML = `<span class="lee-agent-step-state" aria-hidden="true"></span>` +
    `<span class="lee-agent-step-copy">${esc(a.summary || a.tool || 'Working')}</span>` +
    `<span class="lee-agent-step-meta">${a.done && a.secs ? esc(Number(a.secs).toFixed(1) + 's') : esc(a.kind || '')}</span>` +
    `<span class="lee-agent-step-chevron" aria-hidden="true"></span>`;
  row.appendChild(summary);

  const args = a.args && typeof a.args === 'object' ? a.args : {};
  const code = typeof args.code === 'string' ? args.code : '';
  const rest = Object.entries(args).filter(([k, v]) => k !== 'code' && v != null && String(v) !== '');
  if (code || rest.length || a.detail) {
    const panel = document.createElement('div'); panel.className = 'lee-agent-step-detail';
    if (rest.length) {
      const dl = document.createElement('dl');
      for (const [key, value] of rest) {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = key; dd.textContent = typeof value === 'string' ? value : JSON.stringify(value);
        dl.append(dt, dd);
      }
      panel.appendChild(dl);
    }
    if (code) {
      const block = document.createElement('div'); panel.appendChild(block);
      deferredEditors.push(() => row._leeViews.push(mountCodeSurface(block, code, 'python', true)));
    }
    if (a.detail) {
      const result = document.createElement('section'); result.className = 'lee-tool-result';
      const label = document.createElement('header'); label.textContent = 'result'; result.appendChild(label);
      const detail = readableDetail(a.detail);
      if (a.kind === 'view' || a.kind === 'skill') {
        const block = document.createElement('div'); result.appendChild(block);
        const path = args.path || (a.kind === 'skill' ? 'note.md' : '');
        deferredEditors.push(() => row._leeViews.push(mountCodeSurface(
          block, detail, codeLang('', path), /\.py$/i.test(path))));
      } else {
        const pre = document.createElement('pre'); pre.textContent = detail; result.appendChild(pre);
      }
      panel.appendChild(result);
    }
    row.appendChild(panel); row.open = wasOpen;
    let mounted = false;
    const mountDeferred = () => {
      if (mounted || !row.open) return;
      mounted = true; requestAnimationFrame(() => deferredEditors.forEach(fn => fn()));
    };
    row.ontoggle = mountDeferred;
    mountDeferred();
  } else { summary.classList.add('empty'); row.ontoggle = null; }
}

// A turn gets an immediate, persistent status surface. It is deliberately in the agent
// log rather than only in the footer: long local inference must still look alive when the
// footer is out of sight, and the current phase should sit beside the work it describes.
function agentProgress(log) {
  const el = document.createElement('section');
  el.className = 'lee-agent-progress'; el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<div class="lee-agent-motion" aria-hidden="true"><i></i><i></i><i></i></div>` +
    `<div class="lee-agent-progress-copy"><strong>Model is working</strong>` +
    `<span class="lee-agent-phase">Preparing context</span></div>` +
    `<time class="lee-agent-elapsed">0:00</time>` +
    `<button class="lee-agent-stop" type="button">Stop</button>`;
  log.appendChild(el);
  const began = performance.now(), clock = setInterval(() => {
    const secs = Math.floor((performance.now() - began) / 1000);
    $('.lee-agent-elapsed', el).textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  }, 250);
  $('.lee-agent-stop', el).onclick = () => { $('.lee-agent-phase', el).textContent = 'Stopping after this step'; stopAgent(); };
  return {
    phase(text) { $('.lee-agent-phase', el).textContent = text; },
    finish(ok = true) {
      clearInterval(clock); el.classList.add(ok ? 'complete' : 'failed');
      $('.lee-agent-progress-copy strong', el).textContent = ok ? 'Response ready' : 'Model stopped';
      $('.lee-agent-phase', el).textContent = ok ? 'Finished' : 'The stream ended before completion';
      $('.lee-agent-stop', el).remove();
      setTimeout(() => el.remove(), 900);
    },
  };
}

// Slash commands and @ files are resolved inline, without sending a half-written token
// to the model. Selected files remain visible as removable chips until the turn starts.
function paintAgentAttachments() {
  const host = $('#agentattachments'); if (!host) return;
  const active = lee.path ? `<span class="lee-agent-context" title="The assistant can see the active workspace and open files">` +
    `<span>active · ${esc(compactPath(lee.path))}</span></span>` : '';
  const states = lee.stateSuggestions.map(s => `<button type="button" class="lee-agent-state-suggestion" data-state-id="${esc(s.id)}" ` +
    `title="Preview and attach this remembered starting state">state · ${esc(s.title)}</button>`).join('');
  const sels = lee.agentSelections.map((s, i) =>
    `<span class="lee-agent-attachment selection" title="${esc(s.path)}"><span>${esc(s.label)}</span>` +
    `<button type="button" data-sel="${i}" aria-label="remove ${esc(s.label)}">remove</button></span>`).join('');
  host.innerHTML = active + sels + [...lee.agentAttachments.entries()].map(([path, name]) =>
    `<span class="lee-agent-attachment${name.endsWith('/') ? ' folder' : ''}" title="${esc(path)}"><span>${esc(name)}</span>` +
    `<button type="button" data-path="${esc(path)}" aria-label="remove ${esc(name)}">remove</button></span>`).join('') + states;
  $$('.lee-agent-state-suggestion', host).forEach(b => b.onclick = async () => {
    await post('/agent/state/load', {id: b.dataset.stateId, layer: 'task'});
    lee.stateSuggestions = []; paintAgentAttachments(); status('relevant state attached to this workspace', 'ok');
  });
  $$('[data-sel]', host).forEach(b => b.onclick = () => {
    lee.agentSelections.splice(+b.dataset.sel, 1); paintAgentAttachments();
  });
  $$('[data-path]', host).forEach(b => b.onclick = () => {
    const name = lee.agentAttachments.get(b.dataset.path);
    lee.agentAttachments.delete(b.dataset.path);
    // The token goes with the chip, or the prompt keeps naming something no longer attached.
    const input = $('#agentprompt');
    if (input && name) input.value = input.value.replace(new RegExp(`(^|\\s)@${name.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&')}\\s?`), '$1');
    paintAgentAttachments();
  });
}
function closeAgentSuggest() {
  const menu = $('#agentsuggest'); if (!menu) return;
  menu.hidden = true; menu.innerHTML = ''; lee.agentSuggest = []; lee.agentSuggestAt = 0;
}
function paintAgentSuggest() {
  const menu = $('#agentsuggest'); if (!menu) return;
  menu.hidden = !lee.agentSuggest.length;
  menu.innerHTML = lee.agentSuggest.map((x, i) =>
    `<button type="button" role="option" aria-selected="${i === lee.agentSuggestAt}" ` +
    `class="lee-agent-suggest-row${i === lee.agentSuggestAt ? ' active' : ''}" data-i="${i}">` +
    `<strong>${esc(x.label)}</strong><span>${esc(x.detail || '')}</span></button>`).join('');
  $$('button', menu).forEach(b => b.onclick = () => chooseAgentSuggest(+b.dataset.i));
}
function chooseAgentSuggest(i = lee.agentSuggestAt) {
  const item = lee.agentSuggest[i], input = $('#agentprompt'); if (!item || !input) return;
  if (item.kind === 'command') input.value = `/${item.name} `;
  else if (item.kind === 'tool' || item.kind === 'skill') {
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)\/(?:[A-Za-z_][\w-]*)?$/, `$1/${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
  } else {
    // The token *stays*. Removing it left the sentence reading "look at and tell me why",
    // with the thing being talked about visible only as a chip somewhere else. What you typed
    // is the reference; the chip is that reference resolved, not a replacement for it.
    lee.agentAttachments.set(item.path, item.name);
    const at = input.selectionStart, before = input.value.slice(0, at);
    const left = before.replace(/(^|\s)@[^\s@]*$/, `$1@${item.name} `);
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
    paintAgentAttachments();
  }
  closeAgentSuggest(); input.focus();
}
let agentSuggestSeq = 0, stateSuggestTimer = null, agentSuggestTimer = null;
async function suggestAgentState(text) {
  if (text.trim().length < 18 || text.trim().startsWith('/')) { lee.stateSuggestions = []; return paintAgentAttachments(); }
  try {
    const d = await api('/agent/state/suggest?q=' + encodeURIComponent(text.trim()));
    lee.stateSuggestions = (d.states || []).slice(0, 2); paintAgentAttachments();
  } catch (_) {}
}
async function updateAgentSuggest() {
  const input = $('#agentprompt'); if (!input) return;
  const before = input.value.slice(0, input.selectionStart);
  const slash = before.match(/(?:^|\s)\/([A-Za-z_][\w-]*)?$/), commandSlash = before.match(/^\s*\/([\w-]*)$/);
  const mention = before.match(/(?:^|\s)@([^\s@]*)$/); const seq = ++agentSuggestSeq;
  if (slash) {
    lee.agentVocabulary ||= await api('/agent/commands');
    if (seq !== agentSuggestSeq) return;
    const query = (slash[1] || '').toLowerCase(), vocab = lee.agentVocabulary;
    const commands = commandSlash ? (vocab.commands || []).map(c => ({kind: 'command', ...c})) : [];
    const tools = (vocab.tools || []).map(t => ({kind: 'tool', ...t}));
    const skills = (vocab.skills || []).map(s => ({kind: 'skill', ...s}));
    lee.agentSuggest = [...commands, ...tools, ...skills]
      .filter(x => x.name.toLowerCase().startsWith(query)).slice(0, 14)
      .map(x => ({...x, label: '/' + x.name, detail: `${x.kind} · ${x.help || ''}`}));
  } else if (mention) {
    // `@` means "in this project", not "anywhere the workspace can reach": with several
    // checkouts open, the unscoped list is mostly files from a project you are not in.
    // `dirs`: a folder is somewhere to look, and attaching one is how you say "read around here".
    const d = await api('/fs/find?dirs=1&scope=project&q=' + encodeURIComponent(mention[1]) + '&limit=12');
    if (seq !== agentSuggestSeq) return;
    lee.agentSuggest = (d.hits || []).slice(0, 12).map(f => ({kind: f.kind === 'folder' ? 'folder' : 'file',
      path: f.path, name: f.name, label: '@' + f.name,
      detail: (f.kind === 'folder' ? 'folder · ' : '') + compactPath(f.path)}));
  } else return closeAgentSuggest();
  lee.agentSuggestAt = 0; paintAgentSuggest();
}
async function leeAgentControl(control) {
  try {
    const d = await post('/agent/control', {control});
    const select = $('#agentcontrol'); if (select) select.value = d.control;
    status(`agent control: ${d.control}`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAgentControl = leeAgentControl;

function initAgentComposer() {
  const input = $('#agentprompt'); if (!input || input.dataset.composerReady) return;
  input.dataset.composerReady = '1';
  $('[data-agent-pause]')?.addEventListener('click', pauseAgentAfterCurrent);
  $('[data-agent-stop]')?.addEventListener('click', stopAgent);
  const reasoning = $('#agentreasoning');
  if (reasoning) {
    reasoning.value = localStorage.getItem('lee-agent-reasoning') || 'auto';
    reasoning.onchange = () => localStorage.setItem('lee-agent-reasoning', reasoning.value);
  }
  const grow = () => {
    input.style.height = 'auto';
    input.style.height = Math.min(190, Math.max(64, input.scrollHeight)) + 'px';
  };
  input.addEventListener('input', () => {
    grow();
    // Coalesced, because each call walks the project tree. `agentSuggestSeq` already drops a
    // stale answer, but that discards the work after it has been done rather than before.
    clearTimeout(agentSuggestTimer);
    agentSuggestTimer = setTimeout(
      () => updateAgentSuggest().catch(e => status(String(e.message || e), 'err')), 90);
    clearTimeout(stateSuggestTimer); stateSuggestTimer = setTimeout(() => suggestAgentState(input.value), 420);
  });
  grow();
  input.addEventListener('keydown', e => {
    if ($('#agentsuggest')?.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); const d = e.key === 'ArrowDown' ? 1 : -1;
      lee.agentSuggestAt = (lee.agentSuggestAt + d + lee.agentSuggest.length) % lee.agentSuggest.length;
      paintAgentSuggest();
    } else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); chooseAgentSuggest(); }
    else if (e.key === 'Escape') { e.preventDefault(); closeAgentSuggest(); }
  });
}
async function sendAgentCommand(line) {
  const log = $('#agentlog'); log?.appendChild(userMessage(line));
  try {
    const d = await post('/agent/command', {line});
    if (/^\/reload(?:\s|$)/.test(line)) lee.agentVocabulary = null;
    const out = document.createElement('div'); out.className = 'lee-reply lee-agent-reply'; log?.appendChild(out);
    renderMarkdown(out, d.text || ''); if (log) log.scrollTop = log.scrollHeight;
    status('command finished', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}

// The assistant's tools edit files on disk, so a turn can change what is on screen.
// Activity, answer chunks, and final diffs stream independently; each tool row is updated
// in place so pending work never remains on screen after that step has finished.
async function sendAgent() {
  if (lee.agentBusy) return status('the model is already working', 'err');
  if (lee.agentView && lee.agentView !== 'live') restoreAgentLive();
  const el = $('#agentprompt'); if (!el || !el.value.trim()) return;
  const q = el.value.trim(); el.value = ''; el.style.height = '64px'; closeAgentSuggest();
  if (q.startsWith('/')) {
    try { lee.agentVocabulary ||= await api('/agent/commands'); } catch (_) {}
    const head = q.slice(1).split(/\s/, 1)[0];
    if ((lee.agentVocabulary?.commands || []).some(c => c.name === head)) return sendAgentCommand(q);
  }
  const attachments = [...lee.agentAttachments.keys(), ...lee.agentSelections.map(s => s.ref)];
  lee.agentAttachments.clear(); lee.agentSelections = []; paintAgentAttachments();
  lee.agentBusy = true; updateAgentRunstrip();
  const log = $('#agentlog'); $('.lee-agent-welcome', log)?.remove();
  log.appendChild(userMessage(q)); log.scrollTop = log.scrollHeight;
  status('model is working…');

  const progress = agentProgress(log);
  const acts = document.createElement('div');
  acts.className = 'lee-agent-steps';
  const out = document.createElement('div');
  out.className = 'lee-reply lee-agent-reply';
  log.appendChild(acts); log.appendChild(out); log.scrollTop = log.scrollHeight;
  const body = out, seen = new Map(); let raw = '', finished = false;

  const reasoning = $('#agentreasoning')?.value || 'auto';
  const es = new EventSource('/agent/stream?prompt=' + encodeURIComponent(q) +
    '&attachments=' + encodeURIComponent(JSON.stringify(attachments)) +
    '&reasoning=' + encodeURIComponent(reasoning));

  es.addEventListener('activity', ev => {
    const a = JSON.parse(ev.data);
    let row = seen.get(a.id);
    if (!row) {
      row = document.createElement('details'); acts.appendChild(row); seen.set(a.id, row);
      row.animate([{opacity: 0, transform: 'translateY(4px)'}, {opacity: 1, transform: 'translateY(0)'}],
                  {duration: 220, easing: 'cubic-bezier(.16,1,.3,1)'});
    }
    renderAgentStep(row, a);
    const lifecycle = approvalCards.get(a.action_id || a.id);
    if (lifecycle && a.done) {
      lifecycle.classList.remove('running', 'proposed'); lifecycle.classList.add(a.ok ? 'complete' : 'failed');
      const actions = $('.lee-approval-actions', lifecycle);
      if (actions && !lifecycle.querySelector('.lee-checkpoint-result'))
        actions.before(checkpointResult(a.detail, a.ok, a.secs));
      const checkpointState = $('.lee-checkpoint-title small', lifecycle);
      if (checkpointState) checkpointState.textContent = a.ok ? 'Completed' : 'Tool failed';
      const actionState = $('.lee-approval-actions > span', lifecycle);
      if (actionState) actionState.innerHTML = a.ok
        ? (lifecycle.dataset.retryable === 'true'
            ? '<strong>Completed</strong><small>You can rerun this read-only tool without changing the conversation.</small>'
            : '<strong>Completed</strong><small>To run it again, ask the agent so you can review a new checkpoint.</small>')
        : '<strong>Failed</strong><small>The output above explains what the tool returned.</small>';
      updateAgentRunstrip();
    }
    if (a.done && a.ok && a.kind === 'edit' && a.args?.path) scheduleAgentFileReload(a.args.path);
    progress.phase(a.done ? 'Reviewing tool results' : (a.summary || `Running ${a.tool}`));
    log.scrollTop = log.scrollHeight;
  });

  es.addEventListener('chunk', ev => {
    raw += JSON.parse(ev.data).text || '';
    progress.phase('Writing response');
    renderMarkdown(body, raw);
    log.scrollTop = log.scrollHeight;
  });

  es.addEventListener('approval', ev => { progress.phase('Waiting for your approval'); showApproval(JSON.parse(ev.data)); });
  es.addEventListener('execution', ev => updateAgentRunstrip(JSON.parse(ev.data)));
  es.addEventListener('compaction', ev => {
    const d = JSON.parse(ev.data), note = document.createElement('details'); note.className = 'lee-compaction-event';
    note.innerHTML = `<summary>Context compacted automatically · ${esc(d.strategy)} · ${esc(d.note)}</summary><pre>${esc(d.text || '')}</pre>`;
    acts.appendChild(note); progress.phase('Context compacted; continuing from checkpoint');
  });

  es.addEventListener('error', ev => {
    try { raw += JSON.parse(ev.data).error || ''; renderMarkdown(body, raw); } catch (_) {}
  });

  es.addEventListener('done', async ev => {
    finished = true; lee.agentBusy = false; es.close(); progress.finish(true); updateAgentRunstrip();
    const d = JSON.parse(ev.data);
    addResponseRevision(out, d.turn_id, raw, d.capabilities || {});
    const usage = usageMeta(d.usage, d.usage_label, d.model); if (usage) out.after(usage);
    for (const e of (d.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const tail = d.usage_label ? `${d.note || 'done'} · ${d.usage_label}` : (d.note || 'done');
    showProblems(d.problems);
    if ((d.problems || []).length) status(d.problems[d.problems.length - 1], 'err');
    else status(d.ok ? tail : (d.note || 'assistant unavailable'), d.ok ? 'ok' : 'err');
    await reloadAfterEdits(d.edits || []);
  });

  // A dropped connection must clear both the functional busy lock and its visual state.
  es.onerror = () => {
    if (finished) return;
    lee.agentBusy = false; progress.finish(false); updateAgentRunstrip();
    status('the model stream ended before it returned a result', 'err'); es.close();
  };
}

/* Reloading the open tab is what makes an AI edit visible without a refresh -- but only
 * when there is nothing of the user's to lose. Typing while the model thinks is normal,
 * and a buffer with unsaved edits is not something to overwrite silently just because
 * the model happened to reach the same file. So that case is offered, with the diff, and
 * the choice is the user's. */
function scheduleAgentFileReload(path) {
  if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
  clearTimeout(lee.agentReloadTimer);
  lee.agentReloadTimer = setTimeout(async () => {
    if (path !== lee.path || $('.lee-tab.active')?.classList.contains('dirty')) return;
    try { await takeDiskVersion(path); status(`${path.split('/').pop()} updated from the agent edit`, 'ok'); }
    catch (e) { status(String(e.message || e), 'err'); }
  }, 90);
}
async function watchOpenFile() {
  if (!lee.path || lee.watchingDisk || document.hidden) return;
  lee.watchingDisk = true;
  try {
    const d = await api('/tab/watch');
    if (!d || d.path !== lee.path || !lee.diskVersion) return;
    if (d.disk_version === lee.diskVersion) return;
    // Never advance the editor's base token while it is dirty. Doing so makes a missing
    // IndexedDB base fall back to the *new* disk version and silently turns an external
    // write into our own. The old token is exactly what makes the save endpoint detect it.
    // Never destroy typing that has not reached disk. The diff command remains available,
    // while a clean editor follows agent, terminal, git, and other external writes live.
    if ($('.lee-tab.active')?.classList.contains('dirty')) {
      if (d.disk_version !== lee.seenDiskVersion)
        status(`${lee.path.split('/').pop()} changed on disk — keeping your unsaved buffer`, 'err');
      lee.seenDiskVersion = d.disk_version;
      return;
    }
    await takeDiskVersion(lee.path);
    status(`${lee.path.split('/').pop()} updated from disk`, 'ok');
  } catch (_) {
    // Watching is convenience; a transient request failure should not interrupt editing.
  } finally { lee.watchingDisk = false; }
}

async function takeDiskVersion(path) {
  lee.heldSaveConflicts.delete(path);
  // Accepting disk is explicit. Remove any durable browser draft first so mountTab cannot
  // faithfully restore the very buffer the user chose to discard.
  await clearDrafts(path);
  // Clear both client and server document caches. The following mount therefore reads the
  // bytes the tool just wrote rather than replaying the notebook object from before the turn.
  for (const key of [...lee.buffers.keys()])
    if (key === path || key.startsWith(path + ':')) {
      lee.buffers.delete(key); lee.dirtyBuffers.delete(key);
    }
  await post('/tab/reload', {path});
  await mountTab();
}
async function reloadAfterEdits(edits) {
  const e = edits.find(x => x.path && x.path === lee.path);
  if (!e) return;
  if (!$('.lee-tab.active')?.classList.contains('dirty')) {
    await takeDiskVersion(e.path);
    return status(`${e.path.split('/').pop()} updated from the agent edit`, 'ok');
  }
  const m = diffModal(e.path.split('/').pop() + ' changed on disk', e.label, e.rows);
  const bar = document.createElement('div');
  bar.className = 'lee-mfoot';
  bar.innerHTML = '<button class="lee-btn" id="dtake">reload from disk</button>' +
                  '<button class="lee-btn" id="dkeep">keep my buffer</button>' +
                  '<span class="lee-dim">you have unsaved edits in this tab</span>';
  m.querySelector('.lee-modalbox').appendChild(bar);
  bar.querySelector('#dtake').onclick = async () => {
    m.remove(); await takeDiskVersion(e.path); status('loaded the agent edit from disk', 'ok');
  };
  bar.querySelector('#dkeep').onclick = () => { m.remove(); status('kept your buffer — ctrl+s overwrites', 'ok'); };
}

async function stopAgent() {
  const d = await post('/agent/stop');
  status(d.ok ? 'asked the model to stop' : d.error, d.ok ? 'ok' : 'err');
}

/* Failures with nowhere else to go: a compaction the engine refused, a completion that
 * came back empty, anything the native model layer printed instead of raising. They land
 * in the agent pane because that is where the turn they belong to is. */
function showProblems(ps) {
  for (const p of (ps || [])) {
    if (lee.shownProblems.has(p)) continue;
    lee.shownProblems.add(p);
    agentLog(`<div class="lee-runline err"><span class="res">⚠ ${esc(p)}</span></div>`);
  }
}

async function agentTools() {
  const d = await api('/agent/status');
  const rows = (d.calls || []).map(c => `${c.tool}(${c.args})`).join('\n');
  agentLog(`<div class="lee-runline"><span class="sub">${esc(d.note)} · ${d.ntools} tools` +
           `${d.busy ? ' · thinking now' : ''} · context ${Math.round(100 * (d.pct_full || 0))}% full` +
           `${d.compactions ? ' · ' + d.compactions + ' compaction(s)' : ''}</span></div>` +
           (rows ? `<div class="lee-runline"><span class="code">${esc(rows)}</span></div>` : ''));
  showProblems(d.problems);
}

