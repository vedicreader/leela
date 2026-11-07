/* A chord as this app writes them: `[mod+][ctrl+][alt+][shift+]base`, in that order, with `mod`
   standing for the platform's own command key. Built from a real keystroke, so nobody has to know
   the grammar to bind a key. */
const CHORD_BASE = {' ': 'space', 'Escape': 'esc', 'ArrowUp': 'up', 'ArrowDown': 'down',
                    'ArrowLeft': 'left', 'ArrowRight': 'right', 'Backspace': 'backspace',
                    'Enter': 'enter', 'Tab': 'tab', 'Delete': 'delete'};
const CHORD_SKIP = new Set(['Shift', 'Control', 'Alt', 'Meta', 'CapsLock']);
const CHORD_CODE = {...Object.fromEntries([...'abcdefghijklmnopqrstuvwxyz'].map(c => [`Key${c.toUpperCase()}`, c])),
  ...Object.fromEntries([...'0123456789'].map(c => [`Digit${c}`, c])), Space: 'space', Escape: 'escape',
  BracketLeft: '[', BracketRight: ']', Slash: '/', Backslash: '\\', Backquote: '`', Minus: '-', Equal: '=',
  Period: '.', Comma: ',', Semicolon: ';', Quote: "'"};
function chordFromEvent(e) {
  if (CHORD_SKIP.has(e.key)) return '';
  const mac = navigator.platform.toLowerCase().includes('mac');
  const parts = [];
  if (mac ? e.metaKey : e.ctrlKey) parts.push('mod');
  if (mac && e.ctrlKey) parts.push('ctrl');
  if (e.altKey) parts.push('alt');
  if (e.shiftKey) parts.push('shift');
  // The physical key: Option+W types ∑ and Shift+/ types ?, but the chord is alt+w and shift+/.
  const base = CHORD_CODE[e.code] || CHORD_BASE[e.key] || e.key.toLowerCase();
  parts.push(base);
  return parts.join('+');
}

/* Editable here, because the alternative is telling someone whose terminal eats ctrl+enter to go
 * and find a JSON file. A row per action, a field that takes the keystroke itself, and the
 * server's conflict check on every change. Saving reloads the table this client dispatches on, so
 * a new chord works on the next keystroke. */
async function editKeys() {
  const d = await api('/keys/file');
  const rows = () => (lee.keys || []).filter(k => k.label || k.scope !== 'global');
  const m = modal(
    `<div class="lee-mhead">keybindings<span class="sub">${esc(d.path)}</span></div>` +
    `<div class="lee-keyfilter"><input class="lee-input" id="keysearch" placeholder="filter by action, description or chord…" autofocus>` +
    `<span class="lee-dim" id="keycount"></span></div>` +
    `<div id="keynotes"></div>` +
    `<div class="lee-keytable" id="keyrows"></div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="keyjson">edit as JSON…</button><span class="lee-spacer"></span>` +
    `<button class="lee-btn" id="keyreset">restore defaults</button>` +
    `<button class="lee-btn go" id="keysave">save</button></div>`,
    null, null, {className: 'lee-keys-modal', storageKey: 'keybindings'});
  const notes = ns => {
    const host = m.querySelector('#keynotes');
    host.innerHTML = (ns || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('');
    host.hidden = !(ns || []).length;
  };
  const edited = new Map();                       // action -> chord, only what a person changed
  const chordOf = k => edited.has(k.action) ? edited.get(k.action) : (k.key || '');
  /* The file records what differs from leela's own chords and nothing else. A map of all of them
     freezes every action at today's default, and the next default that moves collides with it. */
  const merged = () => {
    const out = {...(d.overrides || {}), ...Object.fromEntries(edited)};
    for (const a of Object.keys(out)) if (out[a] === (d.defaults || {})[a]) delete out[a];
    return out;
  };
  const paint = () => {
    const q = (m.querySelector('#keysearch').value || '').toLowerCase();
    const shown = rows().filter(k => !q ||
      [k.action, k.label, k.scope, chordOf(k)].join(' ').toLowerCase().includes(q));
    m.querySelector('#keycount').textContent = `${shown.length} of ${rows().length}`;
    m.querySelector('#keyrows').innerHTML = shown.map(k =>
      `<div class="lee-keyrow${edited.has(k.action) ? ' changed' : ''}" data-action="${esc(k.action)}">` +
      `<span class="lee-keyrow-name"><strong>${esc(k.label || k.action)}</strong>` +
      `<small>${esc(k.action)} · ${esc(k.scope)}</small></span>` +
      `<input class="lee-input lee-keyrow-chord" data-chord value="${esc(chordOf(k))}" ` +
      `placeholder="unbound" spellcheck="false" aria-label="chord for ${esc(k.action)}">` +
      `<button type="button" data-record title="press the keys you want">record</button>` +
      `<button type="button" data-clear title="unbind">clear</button></div>`).join('') ||
      `<div class="lee-dim">nothing matches</div>`;
  };
  /* The server decides what conflicts, using the same check the save runs, so a warning here
     cannot promise something the save then refuses. */
  let checking = null;
  const check = async () => {
    if (!edited.size) return notes(d.notes);
    clearTimeout(checking);
    checking = setTimeout(async () => {
      try {
        const r = await post('/keys/check', {keys: merged()});
        notes(r.notes);
        if (r.notes.length) status(r.notes[0], 'err');
      } catch (e) { notes([String(e.message || e)]); }
    }, 180);
  };
  const setChord = (action, chord) => {
    const original = (lee.keys.find(k => k.action === action)?.key) || '';
    if (chord === original) edited.delete(action); else edited.set(action, chord);
    paint(); check();
  };
  m.querySelector('#keyrows').addEventListener('click', e => {
    const row = e.target.closest('[data-action]'); if (!row) return;
    const action = row.dataset.action, field = $('[data-chord]', row);
    if (e.target.closest('[data-clear]')) return setChord(action, '');
    if (!e.target.closest('[data-record]')) return;
    field.value = ''; field.placeholder = 'press the keys…'; field.classList.add('recording'); field.focus();
  });
  m.querySelector('#keyrows').addEventListener('keydown', e => {
    const field = e.target.closest('[data-chord]'); if (!field) return;
    if (!field.classList.contains('recording')) return;   // typed, not recorded: let it through
    e.preventDefault(); e.stopPropagation();
    if (e.key === 'Escape') { field.classList.remove('recording'); field.placeholder = 'unbound'; return paint(); }
    const chord = chordFromEvent(e); if (!chord) return;
    field.classList.remove('recording'); field.placeholder = 'unbound';
    setChord(field.closest('[data-action]').dataset.action, chord);
  }, true);
  m.querySelector('#keyrows').addEventListener('change', e => {
    const field = e.target.closest('[data-chord]'); if (!field) return;
    setChord(field.closest('[data-action]').dataset.action, field.value.trim());
  });
  m.querySelector('#keysearch').addEventListener('input', paint);
  const applied = r => {
    lee.keys = r.keys; lee.help = r.help; lee.keyNotes = r.notes || [];
    if (r.glyphs) lee.glyphs = r.glyphs;
    if (r.legacy) lee.legacy = r.legacy;
    // Both are what the next save builds on, so a reset the modal outlives must not be undone by it.
    if (r.overrides) d.overrides = r.overrides;
    if (r.text) d.text = r.text;
    edited.clear(); notes(r.notes); paint();
    status(r.notes.length ? 'saved, but some entries were skipped' : 'keys saved and live', 'ok');
    remountEditors();
  };
  m.querySelector('#keysave').onclick = async () => {
    try { applied(await post('/keys/save', {text: JSON.stringify({keys: merged()}, null, 2)})); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  m.querySelector('#keyreset').onclick = async () => {
    if (!await confirmDialog('Restore default keybindings', 'Every chord you have changed goes back to leela\u2019s own.', 'restore defaults')) return;
    applied(await post('/keys/reset'));
  };
  m.querySelector('#keyjson').onclick = async () => {
    const text = await textDialog('Keybindings as JSON', d.path, d.text);
    if (text == null) return;
    try { applied(await post('/keys/save', {text})); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  notes(d.notes); paint();
}

/* CodeMirror captures its own keymap at creation, so a rebound chord only reaches the editors
 * after they are rebuilt. */
function remountEditors() {
  const v = lee.editors.get('exec');
  if (v) { LeeCM.destroy(v); lee.editors.delete('exec'); }
  mountExec();
  mountTab(lee.tabKey);
}

/* Screen capture. The grab happens here because `getDisplayMedia` needs a user gesture and a real
 * display, and a server process has neither. The track is kept across captures, so only the first
 * press asks permission. */
async function captureScreen() {
  try {
    // WKWebView offers no `navigator.mediaDevices` at all, so the window Leela ships could never
    // take a picture this way. It is also the one case where the server is on the same machine as
    // the display, so it can take it instead.
    if (!navigator.mediaDevices?.getDisplayMedia) {
      const r = await post('/screen/native', {});
      return status(`screen captured (${Math.round(r.bytes / 1024)}kb) — it rides along with your next question`, 'ok');
    }
    if (!lee.vtrack || lee.vtrack.readyState === 'ended') {
      const s = await navigator.mediaDevices.getDisplayMedia({video: true});
      lee.vtrack = s.getVideoTracks()[0];
    }
    const bmp = await new ImageCapture(lee.vtrack).grabFrame();
    const scale = Math.min(1280 / bmp.width, 1024 / bmp.height, 1);
    const cv = document.createElement('canvas');
    cv.width = Math.floor(bmp.width * scale); cv.height = Math.floor(bmp.height * scale);
    cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
    bmp.close();
    const r = await post('/screen', {data_url: cv.toDataURL('image/png')});
    status(`screen captured (${Math.round(r.bytes / 1024)}kb) — it rides along with your next question`, 'ok');
  } catch (e) { status('capture failed: ' + (e.message || e), 'err'); }
}

/* Edits go one at a time, each to the notebook it was made in, naming cells by id. A response is applied
   only while that notebook is still the one mounted and only when it is no older than what is shown, and
   text typed while it was in flight stays. One arriving while its tab is away waits in `lee.nbLate`.
   Resolves to the response it applied, or null, so a caller leaves focus and selection alone. */
async function nbEdit(d) {
  // A file is one document, not a column of cells, and a structural edit would split the buffer.
  if (lee.kind !== 'notebook') { status('cells belong to notebooks — this tab is a file', 'err'); return null; }
  const key = lee.tabKey, cells = lee.cells, named = {path: key};
  if (!['undo', 'redo', 'clear'].includes(d.op) && cells[d.i]) named.id = cells[d.i].id;
  if (d.indices) named.ids = d.indices.map(i => cells[i]?.id).filter(Boolean);
  if (d.op === 'move_many') named.target_id = cells[d.target]?.id || '';   // '' is the end
  const run = lee.nbQueue.then(() => sendEdit({...d, ...named}, key));
  lee.nbQueue = run.catch(() => {});
  return run;
}
//: Keeps a response for a notebook not on screen for its next mount, when it is the newest one seen. Nothing was applied: null.
function lateEdit(key, r) {
  if (r?.cells && r.version > (lee.nbLate.get(key)?.version ?? 0)) lee.nbLate.set(key, r);
  return null;
}
async function sendEdit(d, key) {
  await headingSynced(key);   // a fold posted just before is written first
  const mounted = lee.mountedAt, here = () => lee.tabKey === key && lee.mountedAt === mounted && mounted === mountTabVersion;
  if (!here()) return lateEdit(key, await post('/nb/edit', d));
  const host = $('#editor'), scrollTop = host?.scrollTop || 0;
  const before = lee.cells.slice();
  const visible = $$('.lee-cell', host).find(el => el.getBoundingClientRect().bottom > host.getBoundingClientRect().top);
  const anchor = visible ? {id: visible.dataset.id, top: visible.getBoundingClientRect().top} : null;
  const selectedId = lee.cells[lee.sel]?.id, selectedView = selectedId && lee.editors.get(selectedId);
  const cursor = selectedView ? LeeCM.cursor(selectedView) : 0;
  const seq = nextSeq(), sent = new Map(lee.cells.map(c => [c.id, lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source]));
  for (const c of lee.cells) c.source = sent.get(c.id);
  // Only the cells whose text the server has not confirmed go, each with the source this page last saw.
  const sources = changedRows(key, lee.cells, seq);
  const r = await post('/nb/edit', d.op === 'source' ? {...d, seq, ...seenRow(key, d.id)} : {...d, sources});
  const clash = new Set(r.clash || []);
  noteSeen(key, r.cells.filter(c => !clash.has(c.id)));
  if (!here() || r.version < (lee.nbVersions.get(key) ?? 0)) return lateEdit(key, r);
  lee.nbVersions.set(key, r.version);
  // A cell this edit left as it was sent keeps what was typed into it since; one that clashed keeps what was typed, for the save to offer.
  for (const c of r.cells) { const v = lee.editors.get(c.id); if (v && (c.source === sent.get(c.id) || clash.has(c.id))) c.source = LeeCM.getDoc(v); }
  if (clash.size) status('another window changed a cell you edited · save to choose what to keep', 'err');
  lee.cells = foldsSince(key, r.cells, r.version);
  const same = r.cells.findIndex(c => c.id === selectedId);
  if (d.op === 'undo' || d.op === 'redo') lee.sel = Math.max(0, Math.min(r.index ?? lee.sel, r.cells.length - 1));
  else if (same >= 0) lee.sel = same;
  patchNotebook(host, before, r.cells, d.op);
  if (host) {
    host.scrollTop = scrollTop;
    const anchored = anchor && $(`.lee-cell[data-id="${CSS.escape(anchor.id)}"]`, host);
    if (anchored) host.scrollTop += anchored.getBoundingClientRect().top - anchor.top;
  }
  const restored = same >= 0 && lee.editors.get(selectedId);
  if (restored) LeeCM.setCursor?.(restored, Math.min(cursor, restored.state.doc.length));
  // An undo that scrolls nothing leaves you looking for what moved. The cell the operation
  // reached is already `lee.sel`, so put it in the middle.
  if (d.op === 'undo' || d.op === 'redo') {
    const cell = $(`.lee-cell[data-i="${lee.sel}"]`);
    cell?.scrollIntoView({block: 'center', inline: 'nearest'});
    cell?.classList.add('lee-cell-changed');
    setTimeout(() => cell?.classList.remove('lee-cell-changed'), 1200);
  }
  markDirty();
  return r;
}

async function toggleComment() {
  const c = lee.cells[lee.sel]; const v = c && lee.editors.get(c.id);
  if (!v) return;
  const txt = LeeCM.getDoc(v);
  const lines = txt.split('\n');
  const allC = lines.every(l => !l.trim() || l.trimStart().startsWith('#'));
  LeeCM.setDoc(v, lines.map(l => allC ? l.replace(/^(\s*)#\s?/, '$1') : (l.trim() ? l.replace(/^(\s*)/, '$1# ') : l)).join('\n'));
}

