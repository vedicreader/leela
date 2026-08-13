/* ---------------------------------------------------------- the keymap */
/* Editable here, because the alternative is telling someone whose terminal or browser
 * eats ctrl+enter to go and find a JSON file. Saving re-reads it server-side and reloads
 * the table this client dispatches on, so a new chord works on the next keystroke. */
async function editKeys() {
  const d = await api('/keys/file');
  const m = modal(
    `<div class="lee-mhead">keybindings<span class="sub">${esc(d.path)}</span></div>` +
    `<div class="lee-dim">action → chord, or several separated by spaces; "" unbinds it. ` +
    `A chord is [mod+][ctrl+][alt+][shift+]base; mod is ⌘ on this Mac and ctrl elsewhere.</div>` +
    `<div id="keynotes"></div>` +
    `<textarea class="lee-keyedit" id="keytext" spellcheck="false"></textarea>` +
    `<div class="lee-mfoot"><button class="lee-btn go" id="keysave">save</button>` +
    `<button class="lee-btn" id="keyreset">restore defaults</button></div>`);
  const ta = m.querySelector('#keytext');
  ta.value = d.text;
  const notes = (ns) => {
    m.querySelector('#keynotes').innerHTML = (ns || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('');
  };
  notes(d.notes);
  const applied = (r) => {
    lee.keys = r.keys; lee.help = r.help; lee.keyNotes = r.notes || [];
    notes(r.notes);
    status(r.notes.length ? 'saved, but some entries were skipped' : 'keys saved and live', 'ok');
    remountEditors();
  };
  m.querySelector('#keysave').onclick = async () => {
    try { applied(await post('/keys/save', {text: ta.value})); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  m.querySelector('#keyreset').onclick = async () => {
    const r = await post('/keys/reset');
    ta.value = JSON.stringify({keys: Object.fromEntries(r.keys.map(k => [k.action, k.key]))}, null, 2);
    applied(r);
  };
}

/* CodeMirror captures its own keymap at creation, so a rebound chord only reaches the
 * editors after they are rebuilt. Cheap, and it happens once, when the map changes. */
function remountEditors() {
  const v = lee.editors.get('exec');
  if (v) { LeeCM.destroy(v); lee.editors.delete('exec'); }
  mountExec();
  mountTab();
}

/* Screen capture. The grab happens here, not on the server: getDisplayMedia needs a user
 * gesture and a real display, and a server process has neither. The track is kept across
 * captures so only the first press asks permission. */
async function captureScreen() {
  try {
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

async function nbEdit(d) {
  // A file is one document, not a column of cells; a structural edit here would split the
  // buffer the editor is showing.
  if (lee.kind !== 'notebook') { status('cells belong to notebooks — this tab is a file', 'err'); return {}; }
  const host = $('#editor'), scrollTop = host?.scrollTop || 0;
  const before = lee.cells.slice();
  const visible = $$('.lee-cell', host).find(el => el.getBoundingClientRect().bottom > host.getBoundingClientRect().top);
  const anchor = visible ? {id: visible.dataset.id, top: visible.getBoundingClientRect().top} : null;
  const selectedId = lee.cells[lee.sel]?.id, selectedView = selectedId && lee.editors.get(selectedId);
  const cursor = selectedView ? LeeCM.cursor(selectedView) : 0;
  const cur = lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}));
  for (const c of cur) if (lee.cells[c.i]) lee.cells[c.i].source = c.source;
  const r = await post('/nb/edit', d.op === 'source' ? d : {...d, sources: cur});
  lee.cells = r.cells;
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

