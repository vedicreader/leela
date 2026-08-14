/* leela IDE client.
 *
 * Sources live in `leela/static/js/` and concatenate via `tools/build_ide_js.py`.
 * One bundle, one script tag: the modules share a scope, so `$`, `esc` and `lee`
 * are defined here once and used by every later module.
 *
 * The keymap is fetched from /keys.json (leela.core.keys). Dispatch is scope-aware:
 * `lee.scope` must match or be 'global', else the browser/CodeMirror keep the chord.
 */
"use strict";

const lee = {
  keys: [], help: {}, scope: 'editor', execScope: 'live',
  editors: new Map(),        // cell id (or 'exec'/'file') -> CodeMirror view
  cells: [], sel: 0, cellSelection: new Set(), cellAnchor: 0, kind: null, path: '',
  hist: [], histIdx: 0,
  varOpen: new Set(), varPrev: {}, varStates: new Map(), varFingerprints: new Map(), varRuntime: '',
  term: null, terms: new Map(), activeTerm: '', termSeq: 0,
  cellObserver: null, lastDoc: null, buffers: new Map(), dirtyBuffers: new Set(), bufferTimers: new Map(),
  autoSaveTimer: null, saving: false, editVersion: 0, collapsedCells: new Set(), fileGit: null,
  diskVersion: '', seenDiskVersion: '', watchingDisk: false,
  breakpoints: new Map(), debugThread: null, debugCell: null, debugState: null, directDebug: false, debugWatches: [],
  shownProblems: new Set(),   // agent failures already written into the pane, so they show once
  agentAttachments: new Map(), agentSuggest: [], agentSuggestAt: 0, agentVocabulary: null, stateSuggestions: [],
  cellClipboard: null,       // detached cell payload; survives tab switches for cross-notebook moves
  recentTabs: [], locations: new Map(), recentCycle: [], recentCycleAt: 0, researchDocs: [], researchSelected: new Set(),
  draftBases: new Map(), draftTimers: new Map(), heldSaveConflicts: new Set(),
  editorPrefs: null, settingsMeta: null, filePrefs: {}, workbenchPrefs: {}, debugPrefs: {},
  theme: null,               // {family, mode, density}; mode may be 'system', resolved at paint time
  gitDiffTabs: new Map(), activeGitTab: '', gitMergeView: null,
};
const CODE_FONTS = [
  ['JetBrains Mono', 'Bundled · full italic support'],
  ['Fira Code', 'Bundled · strong coding ligatures'],
  ['System monospace', 'Uses the platform editor font'],
];
const FONT_STACKS = {
  'JetBrains Mono': '"JetBrains Mono", ui-monospace, monospace',
  'Fira Code': '"Fira Code", ui-monospace, monospace',
  'System monospace': 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
};
const EDITOR_DEFAULTS = {fontFamily: 'JetBrains Mono', fontSize: 13, lineHeight: 1.5,
  lineLength: 100, guideColumns: '88', visualGuides: true, ligatures: true, tabSize: 4,
  useTabs: false, detectIndentation: true, wordWrap: 'off', wrapIndent: 'same',
  bracketMatching: true, bracketColors: false, closeBrackets: true, activeLine: true,
  overviewMode: 'long', overviewThreshold: 120, stickyNavigation: true,
  lineNumbers: 'absolute', renderWhitespace: 'selection', indentGuides: true,
  highlightSelection: true, methodSeparators: false, cursorStyle: 'line',
  cursorBlinking: 'blink', scrollPastEnd: false, smoothScrolling: true, scrollMargin: 3,
  folding: true, quickSuggestions: true, parameterHints: true, inlayHints: true};
function readEditorPrefs() {
  try {
    const old = JSON.parse(localStorage.getItem('lee-editor-settings') || '{}');
    if (old.fontFamily && !FONT_STACKS[old.fontFamily]) {
      const match = Object.keys(FONT_STACKS).find(name => String(old.fontFamily).includes(name));
      old.fontFamily = match || 'System monospace';
    }
    if (typeof old.wordWrap === 'boolean') old.wordWrap = old.wordWrap ? 'viewport' : 'off';
    // Two renames of the same setting: the boolean it started as, and the name it had
    // while it drew a picture of the text rather than marking up the scrollbar.
    if ('minimap' in old && !old.minimapMode) old.minimapMode = old.minimap ? 'always' : 'off';
    if (old.minimapMode && !old.overviewMode) old.overviewMode = old.minimapMode;
    if (old.minimapThreshold && !old.overviewThreshold) old.overviewThreshold = old.minimapThreshold;
    return {...EDITOR_DEFAULTS, ...old};
  } catch (_) { return {...EDITOR_DEFAULTS}; }
}
lee.editorPrefs = readEditorPrefs();
function applyEditorPrefs(prefs = lee.editorPrefs, persist = false) {
  const p = {...EDITOR_DEFAULTS, ...prefs};
  p.fontSize = Math.max(9, Math.min(28, Number(p.fontSize) || 13));
  p.lineHeight = Math.max(1, Math.min(2.4, Number(p.lineHeight) || 1.5));
  p.tabSize = Math.max(1, Math.min(8, Number(p.tabSize) || 4));
  p.lineLength = Math.max(40, Math.min(240, Number(p.lineLength) || 100));
  p.guideColumns = p.guideColumns == null ? '' : String(p.guideColumns);
  lee.editorPrefs = p;
  const root = document.documentElement;
  root.style.setProperty('--lee-mono', FONT_STACKS[p.fontFamily] || FONT_STACKS['System monospace']);
  root.style.setProperty('--lee-code-size', p.fontSize + 'px');
  root.style.setProperty('--lee-code-line-height', String(p.lineHeight));
  root.dataset.editorLigatures = p.ligatures ? 'on' : 'off';
  for (const [key,view] of lee.editors) LeeCM.configure?.(view, ['file','secondary'].includes(key)?p:{...p,overviewMode:'off'});
  if (persist) localStorage.setItem('lee-editor-settings', JSON.stringify(p));
  return p;
}
async function loadSettings(language = '') {
  try {
    const d = await api('/settings?language=' + encodeURIComponent(language));
    lee.settingsMeta = d; lee.filePrefs = d.effective.files || {};
    lee.workbenchPrefs = d.effective.workbench || {}; lee.debugPrefs = d.effective.debug || {};
    applyEditorPrefs(d.effective.editor || EDITOR_DEFAULTS);
  } catch (_) { applyEditorPrefs(lee.editorPrefs); }
}
applyEditorPrefs(lee.editorPrefs);
function createEditor(el, opts = {}) { return LeeCM.create(el, {...opts, settings: {...lee.editorPrefs, ...(opts.settings||{})}}); }
try { lee.recentTabs = JSON.parse(sessionStorage.getItem('lee-recent-tabs') || '[]'); }
catch (_) { lee.recentTabs = []; }
try { lee.locations = new Map(JSON.parse(sessionStorage.getItem('lee-tab-locations') || '[]')); }
catch (_) { lee.locations = new Map(); }
try { lee.breakpoints = new Map(JSON.parse(localStorage.getItem('lee-breakpoints') || '[]')); }
catch (_) { lee.breakpoints = new Map(); }
try { lee.debugWatches=JSON.parse(localStorage.getItem('lee-debug-watches')||'[]'); } catch(_){lee.debugWatches=[];}
function rememberBreakpoints(key, rows){lee.breakpoints.set(key,rows);localStorage.setItem('lee-breakpoints',JSON.stringify([...lee.breakpoints]));}
function detailedBreakpoints(path){const details=JSON.parse(localStorage.getItem('lee-breakpoint-details')||'{}');return (lee.breakpoints.get(path)||[]).map(line=>({line,...(details[`${path}:${line}`]||{})}));}
document.addEventListener('contextmenu',e=>{const gutter=e.target.closest?.('.cm-lee-breakpoints');if(!gutter)return;e.preventDefault();
  const entry=[...lee.editors.entries()].find(([,view])=>view.dom.contains(gutter));if(!entry)return;const [key,view]=entry,path=key==='file'?lee.path:key;
  const pos=view.posAtCoords({x:e.clientX,y:e.clientY});if(pos==null)return;const line=view.state.doc.lineAt(pos).number;editBreakpoint(path,line,view);});
async function editBreakpoint(path,line,view){const all=JSON.parse(localStorage.getItem('lee-breakpoint-details')||'{}'),current=all[`${path}:${line}`]||{};
  const m=modal(`<div class="lee-mhead">breakpoint<span class="sub">line ${line}</span></div><div class="lee-run-fields"><label>Condition<input class="lee-input" data-condition value="${esc(current.condition||'')}"></label><label>Hit count<input class="lee-input" data-hit value="${esc(current.hitCondition||'')}" placeholder="> 3"></label><label>Log message<input class="lee-input" data-log value="${esc(current.logMessage||'')}" placeholder="value={value}"></label></div><div class="lee-mfoot"><button class="lee-btn warn" data-remove>remove</button><span class="lee-spacer"></span><button class="lee-btn go" data-save>save breakpoint</button></div>`);
  $('[data-remove]',m).onclick=()=>{const rows=(lee.breakpoints.get(path)||[]).filter(x=>x!==line);rememberBreakpoints(path,rows);delete all[`${path}:${line}`];localStorage.setItem('lee-breakpoint-details',JSON.stringify(all));LeeCM.setBreakpoints(view,rows);m.remove();};
  $('[data-save]',m).onclick=()=>{const rows=[...new Set([...(lee.breakpoints.get(path)||[]),line])].sort((a,b)=>a-b);rememberBreakpoints(path,rows);all[`${path}:${line}`]={condition:$('[data-condition]',m).value.trim(),hitCondition:$('[data-hit]',m).value.trim(),logMessage:$('[data-log]',m).value.trim()};localStorage.setItem('lee-breakpoint-details',JSON.stringify(all));LeeCM.setBreakpoints(view,rows);if(lee.directDebug)post('/debug/breakpoints',{path,breakpoints:detailedBreakpoints(path)});m.remove();};}

/* Durable browser drafts. indexed-cache is intentionally not used here: it caches static
 * asset Blobs, while editor recovery needs keyed mutable records and atomic replacement.
 * Native IndexedDB is the smaller and more appropriate primitive. */
const DRAFT_DB = 'leela-editor-drafts', DRAFT_STORE = 'drafts';
let draftDBPromise = null;
function draftDB() {
  if (!('indexedDB' in window)) return Promise.resolve(null);
  if (draftDBPromise) return draftDBPromise;
  draftDBPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DRAFT_DB, 1);
    req.onupgradeneeded = () => {
      const store = req.result.createObjectStore(DRAFT_STORE, {keyPath: 'key'});
      store.createIndex('document', 'document', {unique: false});
    };
    req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
  }).catch(e => { console.warn('Leela draft store unavailable:', e); return null; });
  return draftDBPromise;
}
async function draftPut(record) {
  const db = await draftDB(); if (!db) return;
  await new Promise((resolve, reject) => {
    const tx = db.transaction(DRAFT_STORE, 'readwrite'); tx.objectStore(DRAFT_STORE).put(record);
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
}
async function draftsFor(documentKey) {
  const db = await draftDB(); if (!db || !documentKey) return [];
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DRAFT_STORE, 'readonly');
    const req = tx.objectStore(DRAFT_STORE).index('document').getAll(documentKey);
    req.onsuccess = () => resolve(req.result || []); req.onerror = () => reject(req.error);
  });
}
async function rebaseDrafts(documentKey, diskVersion) {
  for (const key of [...lee.draftBases.keys()]) if (key === documentKey || key.startsWith(documentKey + ':'))
    lee.draftBases.set(key, diskVersion);
  const db = await draftDB(); if (!db) return;
  const rows = await draftsFor(documentKey);
  await Promise.all(rows.map(row => draftPut({...row, baseDiskVersion: diskVersion})));
}
async function clearDrafts(documentKey) {
  if (!documentKey) return;
  for (const [key, timer] of [...lee.draftTimers]) if (key === documentKey || key.startsWith(documentKey + ':')) {
    clearTimeout(timer); lee.draftTimers.delete(key);
  }
  const db = await draftDB(); if (!db) return;
  const rows = await draftsFor(documentKey);
  await new Promise((resolve, reject) => {
    const tx = db.transaction(DRAFT_STORE, 'readwrite'), store = tx.objectStore(DRAFT_STORE);
    rows.forEach(row => store.delete(row.key)); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
  for (const key of [...lee.draftBases.keys()]) if (key === documentKey || key.startsWith(documentKey + ':')) lee.draftBases.delete(key);
}
function draftBaseFor(documentKey) {
  const values = [...lee.draftBases].filter(([key]) => key === documentKey || key.startsWith(documentKey + ':'))
    .map(([, value]) => value).filter(Boolean);
  return values[0] || lee.diskVersion || '';
}
function writeDraftNow(key, payload) {
  const documentKey = payload.path || payload.title || lee.tabKey || key;
  if (!documentKey) return;
  const draftKey = payload.kind === 'notebook' ? `${documentKey}:${payload.id || payload.i}` : documentKey;
  if (!lee.draftBases.has(draftKey)) lee.draftBases.set(draftKey, lee.diskVersion || '');
  draftPut({key: draftKey, document: documentKey, payload, baseDiskVersion: lee.draftBases.get(draftKey),
            updatedAt: Date.now()}).catch(() => {});
}
function persistDraft(key, payload) {
  const documentKey = payload.path || payload.title || lee.tabKey || key;
  if (!documentKey) return;
  const draftKey = payload.kind === 'notebook' ? `${documentKey}:${payload.id || payload.i}` : documentKey;
  if (!lee.draftBases.has(draftKey)) lee.draftBases.set(draftKey, lee.diskVersion || '');
  clearTimeout(lee.draftTimers.get(draftKey));
  lee.draftTimers.set(draftKey, setTimeout(() => {
    lee.draftTimers.delete(draftKey);
    writeDraftNow(key, payload);
  }, 60));
}
function snapshotCurrentDraft() {
  if (!lee.tabKey || !$('.lee-tab.active.dirty')) return;
  if (lee.kind === 'text') {
    const view = lee.editors.get('file'); if (view) writeDraftNow(lee.tabKey, {path: lee.path, title: lee.tabKey, kind: 'text', text: LeeCM.getDoc(view)});
  } else if (lee.kind === 'notebook') {
    lee.cells.forEach((cell, i) => {
      const view = lee.editors.get(cell.id), text = view ? LeeCM.getDoc(view) : cell.source;
      writeDraftNow(`${lee.tabKey}:${cell.id}`, {path: lee.path, title: lee.tabKey, kind: 'notebook', i, id: cell.id, text});
    });
  }
}
window.addEventListener('pagehide', snapshotCurrentDraft);
window.addEventListener('beforeunload', e => {
  snapshotCurrentDraft();
  if ($('.lee-tab.dirty')) { e.preventDefault(); e.returnValue = ''; }
});
async function restoreDrafts(st) {
  const documentKey = st.path || st.title || ''; if (!documentKey) return false;
  let rows = [];
  try { rows = await draftsFor(documentKey); } catch (_) { return false; }
  if (!rows.length) return false;
  // A draft record is not itself evidence of unsaved work. Records can survive a crash
  // after the disk write but before IndexedDB cleanup; treating an identical record as a
  // recovery marked the clean tab dirty, then autosave compared its stale base and opened
  // the keep/overwrite dialog on every mount.
  let recovered = false;
  if (st.kind === 'text') {
    const row = rows.sort((a, b) => b.updatedAt - a.updatedAt)[0];
    if (row?.payload?.text != null && row.payload.text !== st.text) {
      st.text = row.payload.text; recovered = true;
      lee.draftBases.set(row.key, row.baseDiskVersion || '');
    }
  } else if (st.kind === 'notebook') {
    const byId = new Map(rows.map(row => [row.payload?.id, row]));
    for (const cell of (st.cells || [])) {
      const row = byId.get(cell.id); if (!row || row.payload.text === cell.source) continue;
      lee.draftBases.set(row.key, row.baseDiskVersion || '');
      cell.source = row.payload.text; recovered = true;
    }
  }
  if (!recovered) await clearDrafts(documentKey);
  return recovered;
}
window.lee = lee;

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

const fmtArgs = (args) => typeof args === 'string' ? args
  : Object.entries(args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ');

const CODE_LANGS = {py: 'python', python: 'python', js: 'javascript', javascript: 'javascript',
  mjs: 'javascript', cjs: 'javascript', ts: 'typescript', typescript: 'typescript', jsx: 'jsx', tsx: 'tsx',
  json: 'json', jsonc: 'json', json5: 'json', toml: 'toml', html: 'html', css: 'css', sql: 'sql',
  yml: 'yaml', yaml: 'yaml', md: 'markdown', markdown: 'markdown', sh: 'bash', bash: 'bash', shell: 'bash',
  zsh: 'bash', fish: 'bash', rs: 'rust', rust: 'rust', go: 'go', java: 'java', c: 'cpp', cc: 'cpp',
  cpp: 'cpp', cxx: 'cpp', h: 'cpp', hpp: 'cpp', xml: 'xml', svg: 'xml', ini: 'properties',
  properties: 'properties'};
function codeLang(name = '', path = '') {
  const raw = String(name || '').toLowerCase().replace(/^language-/, '');
  const ext = String(path || '').split('.').pop().toLowerCase();
  return CODE_LANGS[raw] || CODE_LANGS[ext] || 'python';
}
async function promoteCodeToNotebook(code, lang = 'python') {
  if (lee.kind !== 'notebook') return status('open a notebook before promoting code', 'err');
  const at = lee.sel + 1;
  await nbEdit({op: 'insert', i: at, source: code, cell_type: lang === 'markdown' ? 'markdown' : 'code'});
  focusCell(at); status(`promoted to cell ${at + 1}`, 'ok');
}
function mountCodeSurface(host, code, lang = 'python', promote = false) {
  const shell = document.createElement('section'); shell.className = 'lee-code-surface';
  const head = document.createElement('header'); head.className = 'lee-code-head';
  head.innerHTML = `<span>${esc(lang)}</span><span class="lee-spacer"></span>` +
    `<button type="button" data-copy>copy</button>` +
    (promote ? `<button type="button" data-promote>promote to cell</button>` : '');
  const editor = document.createElement('div'); editor.className = 'lee-code-editor';
  const lines = Math.max(1, String(code).split('\n').length);
  editor.style.setProperty('--lee-code-lines', Math.min(lines, 18));
  shell.append(head, editor); host.appendChild(shell);
  const view = createEditor(editor, {doc: String(code || ''), lang: codeLang(lang), readOnly: true, lineNums: true});
  head.querySelector('[data-copy]').onclick = () => {
    navigator.clipboard?.writeText(String(code || '')); status('code copied', 'ok');
  };
  head.querySelector('[data-promote]')?.addEventListener('click', () => promoteCodeToNotebook(String(code || ''), codeLang(lang)));
  return view;
}
function portableToolPayload(raw) {
  try {
    const value = JSON.parse(raw);
    if (!value || !('result' in value)) return null;
    if (value.name) return {id: value.id || '', tool: value.name, args: value.args || {}, detail: value.result};
    const fn = value.call?.function;
    if (fn?.name) return {id: value.id || '', tool: fn.name, args: fn.arguments || {}, detail: value.result};
  } catch {}
  return null;
}
function compactPath(path) {
  const bits = String(path || '').split('/').filter(Boolean);
  return bits.slice(-2).join('/') || String(path || '');
}
function portableToolKind(tool) {
  if (['search_code', 'similar_code', 'outline', 'list_files'].includes(tool)) return 'search';
  if (['view_file', 'view_cell', 'notebook_cells', 'read_terminal'].includes(tool)) return 'view';
  if (['edit_file', 'create_file', 'edit_cell', 'add_cell'].includes(tool)) return 'edit';
  if (['web_search', 'read_url', 'research'].includes(tool)) return 'web';
  if (['run_python', 'inspect_python', 'list_vars'].includes(tool)) return 'run';
  if (tool === 'read_skill') return 'skill';
  if (tool.startsWith('delegate_')) return 'delegate';
  return 'tool';
}
function portableToolSummary(tool, args) {
  const a = args || {}, short = value => String(value || '').replace(/\s+/g, ' ').trim();
  if (tool === 'search_code') return `Search code · ${short(a.query).slice(0, 92)}`;
  if (tool === 'view_file') {
    const range = a.start || a.end ? `:${a.start || 1}–${a.end || 'end'}` : '';
    return `Read · ${compactPath(a.path)}${range}`;
  }
  if (tool === 'read_skill') return `Load skill · ${short(a.name)}`;
  if (tool === 'list_files') return `Scan files · ${short(a.pattern) || 'all'}`;
  if (tool === 'run_python') return `Run Python · ${short(a.code).split(';')[0].slice(0, 82)}`;
  if (tool === 'inspect_python') return `Inspect · ${short(a.code).split(';')[0].slice(0, 82)}`;
  if (tool === 'web_search') return `Search web · ${short(a.query).slice(0, 92)}`;
  if (tool === 'read_url') return `Read web · ${short(a.url).slice(0, 92)}`;
  const body = Object.entries(a).slice(0, 2).map(([k, v]) => `${k}: ${short(v).slice(0, 54)}`).join(' · ');
  return `${tool.replaceAll('_', ' ')}${body ? ' · ' + body : ''}`;
}
function polishActivityGroup(el) {
  // Markdown keeps a standards-compliant list for plain Jupyter. In Leela, collapse that
  // scaffolding into one compact timeline so a dozen calls occupy a dozen rows, not a page.
  $$('ul, ol', el).forEach(list => {
    const rows = $$('.lee-agent-step', list);
    if (!rows.length) return;
    const timeline = document.createElement('section'); timeline.className = 'lee-activity-list';
    rows.forEach(row => timeline.appendChild(row)); list.replaceWith(timeline);
  });
  $$('details', el).forEach(group => {
    const summary = group.querySelector(':scope > summary');
    if (!summary || !/what i did/i.test(summary.textContent || '')) return;
    group.classList.add('lee-activity-group');
    const count = $$('.lee-agent-step', group).length;
    summary.innerHTML = `<span class="lee-activity-title">Work log</span>` +
      `<span class="lee-activity-count">${count} ${count === 1 ? 'step' : 'steps'}</span>` +
      `<span class="lee-agent-step-chevron" aria-hidden="true"></span>`;
  });
}
function upgradePortableToolMarkdown(el) {
  // Rishi's formatter emits portable JSON so plain Jupyter can retain tool activity.
  // In the IDE that JSON becomes the same compact disclosure row as native live activity.
  $$('pre > code', el).forEach(code => {
    const payload = portableToolPayload(code.textContent || ''); if (!payload) return;
    const row = document.createElement('details');
    renderAgentStep(row, {...payload, kind: portableToolKind(payload.tool), done: true, ok: true, secs: 0,
                          summary: portableToolSummary(payload.tool, payload.args)});
    const container = code.parentElement.closest('details') || code.parentElement;
    container.replaceWith(row);
  });
  // The pending portable line is redundant once its completed disclosure exists.
  $$('li', el).forEach(li => {
    if (/[⏳⌛]/u.test(li.textContent || '') && li.querySelector('code')) li.remove();
  });
  polishActivityGroup(el);
}
function enhanceCodeBlocks(el) {
  for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  el._leeCodeViews = [];
  $$('pre > code', el).forEach(code => {
    const pre = code.parentElement, text = code.textContent || '';
    const declared = [...code.classList].find(x => x.startsWith('language-')) || '';
    const lang = codeLang(declared);
    // Every explicitly tagged supported language gets the editor's syntax surface.
    // Promotion stays Python-only: highlighting a TOML or JS answer must not imply that a
    // Python notebook kernel can execute it. Untagged and huge blocks remain lightweight.
    const python = /^(language-)?(py|python)$/.test(declared.toLowerCase());
    const named = declared.replace(/^language-/, '').toLowerCase();
    if (!declared || !CODE_LANGS[named] || text.length > 40000) return;
    const host = document.createElement('div'); pre.replaceWith(host);
    el._leeCodeViews.push(mountCodeSurface(host, text.replace(/\n$/, ''), lang,
                                           python && el.classList.contains('lee-reply')));
  });
}
function addMarkdownCellAction(el) {
  if (!el.dataset.markdown.trim() ||
      (!el.classList.contains('lee-reply') && !el.classList.contains('lee-md-output'))) return;
  const bar = document.createElement('footer'); bar.className = 'lee-reply-actions';
  const button = document.createElement('button'); button.type = 'button';
  button.textContent = el.classList.contains('lee-reply')
    ? 'edit response as markdown cell' : 'edit as markdown cell';
  button.onclick = () => promoteCodeToNotebook(el.dataset.markdown, 'markdown');
  bar.appendChild(button); el.appendChild(bar);
}
// `onRender` runs on the fragment mdhtml just produced, before anything else touches it.
// A caller that has something to say about *which source lines* a block came from -- the
// rendered diff below is the one that does -- has to see the elements the renderer emitted,
// in the order it emitted them, and the code-block upgrade replaces `<pre>` with an editor
// surface. So the annotation goes first, and a throw in it cannot cost the reader the
// rendering it was annotating.
function renderMarkdown(el, text, allowRaw = false, onRender = null) {
  if (!el) return;
  el.dataset.markdown = String(text || '');
  el._leeMarkdownSeq = (el._leeMarkdownSeq || 0) + 1;
  const seq = el._leeMarkdownSeq;
  clearTimeout(el._leeMarkdownTimer);
  el._leeMarkdownAbort?.abort();
  // Streaming can deliver many partial documents per second. Render only the newest one;
  // until mdhtml answers, plain text is the safe fallback rather than client-side raw HTML.
  el._leeMarkdownTimer = setTimeout(async () => {
    const controller = new AbortController(); el._leeMarkdownAbort = controller;
    try {
      const r = await fetch('/markdown/render', {method: 'POST', signal: controller.signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: el.dataset.markdown, allow_raw: allowRaw})});
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      const d = await r.json(); if (seq !== el._leeMarkdownSeq) return;
      el.innerHTML = d.html;
      if (d.warnings?.length) el.dataset.markdownWarnings = d.warnings.join(' · ');
      else delete el.dataset.markdownWarnings;
      if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
      el._leeCodeFrame = requestAnimationFrame(() => {
        el._leeCodeFrame = 0;
        if (onRender) try { onRender(el); } catch (e) { console.warn('Leela markdown annotation:', e); }
        upgradePortableToolMarkdown(el); enhanceCodeBlocks(el); addMarkdownCellAction(el);
      });
    } catch (e) {
      if (e.name === 'AbortError' || seq !== el._leeMarkdownSeq || !el.isConnected) return;
      el.textContent = el.dataset.markdown;
      // A stream repaint or app restart can invalidate an in-flight fragment. Keep the
      // readable source in place and annotate this surface; do not emit dozens of global
      // error toasts while the conversation is still mounting.
      el.dataset.markdownWarnings = `renderer unavailable: ${e.message || e}`;
      if (!el._leeMarkdownReported) {
        el._leeMarkdownReported = true;
        console.warn('Leela markdown fallback:', e);
      }
    }
  }, 32);
}

async function api(url, opts) {
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((body && body.error) || r.statusText);
  return body;
}
const post = (url, data) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                      body: JSON.stringify(data || {})});

async function postEvents(url, data, onEvent) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify(data || {})});
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  const reader = r.body.getReader(), decoder = new TextDecoder();
  let pending = '';
  while (true) {
    const {value, done} = await reader.read();
    pending += decoder.decode(value || new Uint8Array(), {stream: !done});
    let cut;
    while ((cut = pending.indexOf('\n\n')) >= 0) {
      const frame = pending.slice(0, cut); pending = pending.slice(cut + 2);
      let event = 'message', payload = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) payload += line.slice(5).trim();
      }
      if (payload) onEvent(event, JSON.parse(payload));
    }
    if (done) break;
  }
}

let statusTimer = null;
function status(msg, kind) {
  const el = $('#status'); if (!el) return;
  clearTimeout(statusTimer); statusTimer = null;
  msg = String(msg || '').trim();
  if (!msg) { el.textContent = ''; el.className = 'lee-status'; el.hidden = true; return; }
  const busyWords = /(?:running|starting|loading|syncing|searching|fetching|reading|asking|finding|creating|installing|restarting|clustering|working|saving|stopping|connecting)/i;
  const tone = kind || (busyWords.test(msg) || msg.endsWith('…') ? 'busy' : 'info');
  el.textContent = msg; el.hidden = false;
  el.onclick = () => {
    clearTimeout(statusTimer); el.classList.remove('show');
    setTimeout(() => { el.hidden = true; el.textContent = ''; }, 180);
  };
  // Re-adding `show` on a fresh frame restarts the entrance motion even when one status
  // immediately replaces another (running cell 2 after running cell 1).
  el.className = `lee-status ${tone}`;
  requestAnimationFrame(() => el.classList.add('show'));
  const ttl = tone === 'busy' ? 0 : tone === 'err' ? 8000 : tone === 'ok' ? 3200 : 5000;
  if (ttl) statusTimer = setTimeout(() => {
    if (el.textContent !== msg) return;
    el.classList.remove('show');
    setTimeout(() => { if (el.textContent === msg) { el.textContent = ''; el.hidden = true; } }, 220);
  }, ttl);
}

/* ------------------------------------------------------------------ keymap */
const MAC = /Mac|iPhone|iPad|iPod/.test(navigator.userAgentData?.platform || navigator.platform || '');
const displayChord = s => String(s || '').replace(/\bmod\+/g, MAC ? '⌘' : 'ctrl+');
function paintKeyLabels(root = document) {
  $$('kbd', root).forEach(k => { if (k.textContent.includes('mod+')) k.textContent = displayChord(k.textContent); });
}

async function loadKeys() {
  const d = await api('/keys.json');
  lee.keys = d.keys; lee.help = d.help; lee.keyPath = d.path; lee.keyNotes = d.notes || [];
  lee.bars = d.bars || {}; lee.menus = d.menus || {};
  paintKeyLabels();
  const prompt = $('#agentprompt'); if (prompt) prompt.placeholder = displayChord(prompt.placeholder);
  renderContextKeys(lee.scope);
  if (lee.keyNotes.length) status(lee.keyNotes[0] + ' — see the keys panel', 'err');
}

function renderContextKeys(scope = lee.scope) {
  const host = $('#keytoast'), tag = $('#keyscope');
  if (!host || !lee.keys.length) return;
  // This panel is a glanceable contextual cheat sheet, not the full keymap. Commands
  // marked help-only stay in the searchable help/settings surfaces instead of pushing the
  // file tree and editor off screen when the editor scope has dozens of actions.
  const local = lee.keys.filter(k => k.scope === scope && k.label && k.key && ['footer','toast'].includes(k.show)).slice(0, 8);
  const global = lee.keys.filter(k => k.scope === 'global' && k.show === 'toast' && k.label && k.key).slice(0, 4);
  const rows = local.concat(global);
  if (tag) tag.textContent = scope && scope !== 'global' ? `· ${scope}` : '';
  host.innerHTML = rows.length ? rows.map(k =>
    `<div class="lee-krow${k.scope === scope ? ' contextual' : ''}"><kbd>${esc(displayChord(k.key))}</kbd>` +
    `<span>${esc(k.label)}</span></div>`).join('') : '<div class="lee-dim">no keys in this context</div>';
}

/* One application-level keyboard router owns every app command. CodeMirror owns editing
 * commands and xterm owns pty input, but neither gets a duplicate copy of this map. A
 * capturing listener is intentional: an accepted app command is resolved before an editor
 * can consume it; an unaccepted event is untouched and continues normally. */
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'settings', 'toggle_left', 'toggle_right']);
const EDITING_SCOPES = new Set(['editor', 'exec', 'agent', 'term']);

function eventContext(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const inPath = selector => path.some(n => n instanceof Element && n.matches(selector));
  // Overlays own their keyboard while open. Their local handler receives the event after
  // this router leaves it alone; commands behind a dialog must never fire accidentally.
  if (inPath('.lee-modal, .lee-ctxmenu')) return 'overlay';
  if (inPath('#termwrap, .xterm')) return 'term';
  if (inPath('#agentprompt, .lee-agent')) return 'agent';
  if (inPath('#execbox, .lee-exec')) return 'exec';
  if (inPath('#editor, .lee-cell, #filecm')) return 'editor';
  if (inPath('#vars, #varfilter, .lee-varspanel')) return 'vars';
  if (inPath('#filetree, .lee-files')) return 'files';
  return lee.scope || 'editor';
}

function isTextEntry(el) {
  if (!(el instanceof Element)) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
  return el.tagName === 'INPUT' &&
    !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(el.type);
}

function chordMatches(c, e) {
  if (e.isComposing || e.key === 'Process' || e.repeat) return false;
  // macOS reports Caps Lock remapped to Hyper as all four modifiers. Other platforms and
  // some Karabiner/browser combinations expose only Ctrl+Alt+Shift—the Command/Meta bit
  // is not portable there. Hyper explicitly accepts either shape; ordinary `mod` remains
  // strict, so regular shortcuts do not become ambiguous.
  if (c.hyper) {
    // Hyper remappers agree on Ctrl+Alt but Safari/Chrome occasionally omit either the
    // synthetic Shift or Meta bit for named keys. Require the stable pair plus one of the
    // two high modifiers; this accepts both browser shapes without colliding with normal
    // two-modifier shortcuts.
    if (!e.ctrlKey || !e.altKey || !(e.shiftKey || e.metaKey)) return false;
  } else {
    const wantCtrl = !!c.ctrl || (!!c.mod && !MAC);
    const wantMeta = !!c.mod && MAC;
    if (wantCtrl !== e.ctrlKey || wantMeta !== e.metaKey || !!c.alt !== e.altKey || !!c.shift !== e.shiftKey)
      return false;
  }
  // Every modified shortcut is matched by physical code when available. Karabiner/Hyper
  // can transform `event.key` (not just Option-printable characters), while `event.code`
  // remains Enter, KeyR, ArrowDown, and so on.
  if (c.code && (c.mod || c.ctrl || c.alt || c.hyper)) return c.code === e.code;
  return c.key.toLowerCase() === (e.key || '').toLowerCase();
}

const firesInTextEntry = c => c.mod || c.ctrl || c.alt || /^F([1-9]|1[0-2])$/.test(c.key);
function findBinding(e, scope) {
  if (scope === 'overlay') return null;
  const allowed = scope === 'term'
    ? k => k.scope === 'term' || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action)
    : k => k.scope === scope || k.scope === 'global';
  const guard = !EDITING_SCOPES.has(scope) && isTextEntry(e.target);
  for (const k of lee.keys) {
    if (!allowed(k)) continue;
    const chord = k.chords.find(c => chordMatches(c, e));
    if (!chord || (guard && !firesInTextEntry(chord))) continue;
    // Standard Copy/Cut become whole-cell operations only when a notebook cell has no
    // text selection. Selected source keeps the browser/CodeMirror clipboard semantics.
    if (['cell_copy', 'cell_cut'].includes(k.action)) {
      if (lee.kind !== 'notebook') continue;
      const inEditor = e.composedPath?.().some(n => n instanceof Element && n.matches('.cm-editor'));
      const selection = curEditor() ? LeeCM.selection(curEditor()) : null;
      if (inEditor && selection?.from !== selection?.to) continue;
    }
    if (['cell_first', 'cell_last', 'cell_page_up', 'cell_page_down'].includes(k.action) && lee.kind !== 'notebook') continue;
    return {binding: k, chord};
  }
  return null;
}

window.addEventListener('keydown', e => {
  const scope = eventContext(e), match = findBinding(e, scope);
  // Kept on `lee` deliberately: the key editor and DevTools can distinguish "Chrome did
  // not deliver it" from "the router rejected it" using the last real event.
  lee.lastKeyEvent = {key: e.key, code: e.code, ctrl: e.ctrlKey, alt: e.altKey,
                      shift: e.shiftKey, meta: e.metaKey, scope,
                      action: match?.binding.action || '', trusted: e.isTrusted};
  if (!match) return;
  e.preventDefault(); e.stopPropagation();
  leeAct(match.binding.action);
}, true);

/* ------------------------------------------------------------------ actions */
const ACTIONS = {
  focus_files:  () => { leePane('left', true); leeLeft('files'); setScope('files'); $('#filetree')?.focus(); highlightTree(); },
  focus_editor: () => { setScope('editor'); if (lee.cells.length) focusCell(lee.sel); else $('#editor')?.focus(); },
  focus_exec:   () => { leePane('bottom', true); leeDock('exec'); setScope('exec'); lee.editors.get('exec')?.focus(); },
  focus_vars:   () => { leePane('right', true); leeRight('vars'); setScope('vars'); $('#varfilter')?.focus(); },
  focus_agent:  () => { leePane('right', true); leeRight('agent'); setScope('agent'); $('#agentprompt')?.focus(); },
  toggle_left:  () => leePane('left'),
  toggle_right: () => leePane('right'),
  toggle_bottom:() => leePane('bottom'),
  toggle_scope: () => leeScope(lee.execScope === 'live' ? 'agent' : 'live'),
  help:         showHelp,
  settings:     editorSettings,
  quick_open:   quickOpen,
  code_search:  codeSearch,
  find_definition: () => findDefinition(),
  find_usages: () => findUsages(),
  rename_symbol: () => renameSymbol(),
  sync_index: syncCodeIndex,
  run_app:      runApp,
  palette:      palette,
  recent_tabs:  recentTabs,
  save:         saveTab,
  save_all:     saveAllTabs,
  close_tab:    closeTab,
  next_tab:     () => shiftTab(1),
  prev_tab:     () => shiftTab(-1),
  interrupt:    async () => {
    const r = await post('/kernel/interrupt');
    status(r.note || 'cell stopped', (r.forced || !r.ok) ? 'err' : 'ok');
  },
  restart:      async () => { status('restarting kernel…'); await post('/kernel/restart'); markPreviousRuns(); status('kernel restarted · saved outputs are from the previous kernel', 'ok'); leeVars(); },
  switch_env:   pickEnv,
  edit_runs:    editRuns,
  quit:         () => status('close the browser tab to leave'),

  run_cell:     () => lee.kind === 'text' ? runFile() : runCell(lee.sel, false),
  run_advance:  () => lee.kind === 'text' ? runFile() : runCell(lee.sel, true),
  run_insert:   () => lee.kind === 'text' ? runFile() : runCell(lee.sel, 'insert'),
  stop_cell:    () => stopCell(lee.sel),
  run_above:    () => runRange(0, lee.sel, 'cells above'),
  run_below:    () => runRange(lee.sel, lee.cells.length, 'this cell and below'),
  run_all:      runAll,
  restart_run_all: restartRunAll,
  run_file:     runFile,
  run_selection: runSelection,
  pick_kernel:  pickKernel,
  new_notebook: () => htmxPost('/tab/new?kind=notebook'),
  edit_keys:    editKeys,
  cell_select_above: () => focusCell(lee.sel - 1),
  cell_select_below: () => focusCell(lee.sel + 1),
  cell_first: () => focusCell(0),
  cell_last: () => focusCell(lee.cells.length - 1),
  cell_page_up: () => focusCellPage(-1),
  cell_page_down: () => focusCellPage(1),
  cell_move_up: () => moveCellTo(lee.sel, lee.sel - 1),
  cell_move_down: () => moveCellTo(lee.sel, lee.sel + 1),
  cell_above:   async () => { const at = lee.sel; await nbEdit({op: 'insert', i: at}); focusCell(at); status('cell inserted above', 'ok'); },
  cell_below:   async () => { const at = lee.sel + 1; await nbEdit({op: 'insert', i: at}); focusCell(at); status('cell inserted below', 'ok'); },
  cell_delete:  async () => { const at = lee.sel; await nbEdit({op: 'delete', i: at}); focusCell(Math.min(at, lee.cells.length - 1)); status('cell deleted', 'ok'); },
  notebook_undo: async () => {
    const r = await nbEdit({op: 'undo', i: lee.sel});
    focusCell(r.index ?? lee.sel); status('cell operation undone', 'ok');
  },
  notebook_redo: async () => {
    const r = await nbEdit({op: 'redo', i: lee.sel});
    focusCell(r.index ?? lee.sel); status('cell operation redone', 'ok');
  },
  cell_type:    async () => {
    const id = lee.cells[lee.sel]?.id;
    const r = await nbEdit({op: 'type', i: lee.sel, cycle: true});
    const at = Math.max(0, r.cells.findIndex(c => c.id === id));
    focusCell(at); status(`cell ${at + 1} is now ${r.cells[at]?.cell_type || 'code'}`, 'ok');
  },
  capture:      captureScreen,
  cell_split:   async () => {
    const at = lee.sel, v = lee.editors.get(lee.cells[at].id);
    await nbEdit({op: 'split', i: at, offset: v ? LeeCM.cursor(v) : 0});
    focusCell(at + 1); status('cell split', 'ok');
  },
  cell_collapse: () => setCellCollapsed(lee.sel),
  cell_duplicate: async () => {
    const at = lee.sel; await nbEdit({op: 'duplicate', i: at});
    focusCell(at + 1); status('cell duplicated', 'ok');
  },
  cell_copy: () => copyCell(lee.sel),
  cell_cut: () => cutCell(lee.sel),
  cell_paste_above: () => pasteCell(lee.sel),
  cell_paste_below: () => pasteCell(lee.sel + 1),
  cell_merge_above: async () => {
    const at = lee.sel; if (at < 1) return status('there is no cell above', 'err');
    await nbEdit({op: 'merge_above', i: at}); focusCell(at - 1); status('cells merged', 'ok');
  },
  cell_merge_below: async () => {
    const at = lee.sel; if (at + 1 >= lee.cells.length) return status('there is no cell below', 'err');
    await nbEdit({op: 'merge_below', i: at}); focusCell(at); status('cells merged', 'ok');
  },
  clear_cell_output: async () => {
    const at = lee.sel; await nbEdit({op: 'clear_cell', i: at});
    focusCell(at); status('cell output cleared', 'ok');
  },
  clear_all_outputs: async () => {
    await nbEdit({op: 'clear'}); focusCell(lee.sel); status('all outputs cleared', 'ok');
  },
  comment:      toggleComment,
  complete:     kernelComplete,
  ai_complete:  aiComplete,
  show_docs:    showDocs,
  show_diff:    showDiff,
  git_blame:    leeBlame,
  clip_to_vault: leeClipToVault,
  find_similar: findSimilar,
  code_map:     codeMap,

  exec_run:     runExec,
  exec_newline: () => { const v = lee.editors.get('exec'); if (v) LeeCM.insert(v, '\n'); },
  exec_prev:    () => recall(-1),
  exec_next:    () => recall(1),
  exec_clear:   leeExecClear,
  exec_promote: () => { leeScope('live'); runExec(); },

  open:         treeActivate,
  tree_down:    () => moveTreeSelection(1),
  tree_up:      () => moveTreeSelection(-1),
  tree_expand:  treeExpand,
  tree_collapse: treeCollapse,
  new_file:     () => newEntry('file'),
  new_dir:      () => newEntry('dir'),
  rename:       renameEntry,
  delete:       deleteEntry,
  add_root:     addRoot,
  find_repo:    findRepo,
  remove_root:  removeRoot,
  refresh_files: () => refreshFileTree(),
  up_dir:       treeCollapse,
  filter_files: () => status('filter the tree with ctrl+p'),

  expand:       () => $('.lee-vrow.sel')?.click(),
  filter_vars:  () => $('#varfilter')?.focus(),
  edit_value:   editSelectedVar,
  grid:         openGrid,
  copy_value:   () => copyVar('value'),
  copy_path:    () => copyVar('path'),
  promote:      promoteVar,
  sort:         () => { const s = $('#varsort'); s.selectedIndex = (s.selectedIndex + 1) % s.options.length; leeVars(); },
  profile_minimal:  () => setProfile('minimal'),
  profile_standard: () => setProfile('standard'),
  profile_full:     () => setProfile('full'),

  agent_send:   sendAgent,
  agent_stop:   stopAgent,
  agent_tools:  agentTools,

  close_others: () => closeTabs('others'),
  close_right:  () => closeTabs('right'),
  close_saved:  () => closeTabs('saved'),

  terminal:     () => openTerm('shell'),
  git:          () => openTerm('git'),
  panel_git:      () => leeLeft('git'),
  panel_releases: () => leeLeft('releases'),
  panel_deploys:  () => leeLeft('deploys'),
  term_new:     leeNewTerm,
  term_next:    () => cycleTerm(1),
  term_prev:    () => cycleTerm(-1),
  term_close:   closeTerm,

  web_search:   webSearch,
  research:     researchQ,
  read_url:     () => readUrl(),
};
for (let i = 1; i <= 9; i++) ACTIONS['tab_' + i] = () => htmxPost('/tab/select?i=' + (i - 1));

function leeAct(name) {
  const f = ACTIONS[name];
  if (!f) return status('no handler for ' + name);
  try { const r = f(); if (r && r.catch) r.catch(e => status(String(e.message || e), 'err')); }
  catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAct = leeAct;

function setScope(s) {
  lee.scope = s;
  renderContextKeys(s);
}
const activeTabIndex = () => $$('.lee-tab').findIndex(t => t.classList.contains('active'));
async function closeTab(index = null) {
  const i = index == null ? (lee.menuTab == null ? activeTabIndex() : lee.menuTab) : Number(index);
  lee.menuTab = null;
  if (i < 0) return;
  const tab = $$('.lee-tab')[i];
  if (tab?.dataset.gitDiff) return closeGitDiffTab(tab.dataset.gitDiff);
  if (tab?.classList.contains('dirty') &&
      !await confirmDialog('close unsaved tab', `${$('.lee-tab-name', tab)?.textContent || 'This file'} has unsaved changes.`, 'close')) return;
  htmxPost('/tab/close?i=' + i);
}
window.leeCloseTab = closeTab;
async function closeTabs(which) {
  // `others`, `right` and `saved`, the three a browser offers after a morning of opening
  // files. The reference point is the tab the menu was opened on, not the active one -- a
  // right-click on a background tab selects it first, but the menu is still about that tab.
  const at = lee.menuTab == null ? activeTabIndex() : lee.menuTab;
  lee.menuTab = null;
  if (at < 0) return;
  const tabs = $$('.lee-tab');
  const keep = i => which === 'others' ? i === at : which === 'right' ? i <= at
                  : tabs[i].classList.contains('dirty');
  // Git diff tabs live only in the browser and are appended after the real ones, so they
  // are left alone and cannot shift an index. Highest first, for the same reason.
  const doomed = tabs.map((_, i) => i).filter(i => !keep(i) && !tabs[i].dataset.gitDiff).reverse();
  if (!doomed.length) return status('nothing to close');
  const unsaved = doomed.filter(i => tabs[i].classList.contains('dirty')).length;
  if (unsaved && !await confirmDialog('close unsaved tabs',
      `${unsaved} of ${doomed.length} tabs have unsaved changes.`, 'close')) return;
  for (const i of doomed) await htmxPost('/tab/close?i=' + i);
  status(`closed ${doomed.length} tab${doomed.length === 1 ? '' : 's'}`);
}
function moveTab(from, to) {
  if (from === to || from < 0 || to < 0) return;
  htmxPost(`/tab/move?i=${from}&j=${to}`);
}
function rememberRecentTab(st) {
  const key = st.path || st.title || '';
  if (!key) return;
  const current = {key, path: st.path || '', title: st.title || key, kind: st.kind || 'text', at: Date.now()};
  lee.recentTabs = [current, ...lee.recentTabs.filter(x => x?.key !== key)].slice(0, 60);
  try { sessionStorage.setItem('lee-recent-tabs', JSON.stringify(lee.recentTabs)); } catch (_) {}
}
function recentTabs() {
  const open = $$('.lee-tab').map((tab, i) => ({
    i, key: tab.title || $('.lee-tab-name', tab)?.textContent || '',
    path: tab.title || '', title: $('.lee-tab-name', tab)?.textContent || 'untitled',
    dirty: tab.classList.contains('dirty'), running: !!$('.lee-tab-run', tab),
  }));
  if (!open.length) return status('no files are open', 'err');
  const byKey = new Map(open.map(x => [x.key, x]));
  let rows = lee.recentTabs.map(x => ({...x, ...byKey.get(x.key)})).filter(x => x.i != null);
  for (const row of open) if (!rows.some(x => x.i === row.i)) rows.push(row);
  const now = Date.now(), active = activeTabIndex();
  if (now - lee.recentCycleAt > 1400 || !lee.recentCycle.length)
    lee.recentCycle = rows.filter(x => x.i !== active).map(x => x.i);
  lee.recentCycleAt = now;
  if (lee.recentCycle.length) {
    const next = lee.recentCycle.shift(); lee.recentCycle.push(next);
    return htmxPost('/tab/select?i=' + next);
  }
  let filtered = rows, sel = Math.max(0, Math.min(1, rows.length - 1));
  const m = modal(`<div class="lee-mhead">Recent files<span class="sub">most recently used</span></div>` +
    `<input class="lee-input lee-recent-query" placeholder="filter open files…" autofocus>` +
    `<div class="lee-modallist lee-recent-list"></div><div class="lee-mfoot lee-dim">enter switch · delete close</div>`, e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, filtered.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
      else if (e.key === 'Delete' && filtered[sel]) { e.preventDefault(); const row = filtered[sel]; m.remove(); closeTab(row.i); }
    });
  const list = $('.lee-recent-list', m), input = $('.lee-recent-query', m);
  const paint = () => {
    list.innerHTML = filtered.length ? filtered.map((r, i) => `<button class="lee-recent-row${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span class="lee-recent-kind">${r.kind === 'notebook' ? 'NB' : 'FILE'}</span>` +
      `<span class="lee-recent-copy"><strong>${esc(r.title)}</strong><small>${esc(compactPath(r.path))}</small></span>` +
      `<span class="lee-recent-state">${r.running ? 'running' : r.dirty ? 'unsaved' : ''}</span></button>`).join('') :
      '<div class="lee-dim">No matching open files.</div>';
    $('.lee-recent-row.sel', list)?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const row = filtered[sel]; if (!row) return; m.remove(); htmxPost('/tab/select?i=' + row.i); };
  input.oninput = () => { const q = input.value.trim().toLowerCase(); filtered = rows.filter(r => `${r.title} ${r.path}`.toLowerCase().includes(q)); sel = 0; paint(); };
  list.onclick = e => { const row = e.target.closest('[data-i]'); if (!row) return; sel = +row.dataset.i; go(); };
  paint();
}
function shiftTab(d) {
  const n = $$('.lee-tab').length; if (!n) return;
  htmxPost('/tab/select?i=' + ((activeTabIndex() + d + n) % n));
}
function layoutTabs() {
  const bar = $('#tabbar'), more = $('#taboverflow'); if (!bar || !more) return;
  const tabs = $$('.lee-tab', bar), active = Math.max(0, activeTabIndex());
  // Keep a calm, finite strip. The active file and its neighbours remain spatially
  // meaningful; every other open document is one click away in the overflow menu.
  const breakpointCap = innerWidth >= 1700 ? 7 : innerWidth >= 1300 ? 5 : innerWidth >= 960 ? 4 : 2;
  const cap = Math.max(1, Math.min(breakpointCap, Math.floor(bar.clientWidth / 138) || 1));
  const keep = new Set();
  if (tabs.length <= cap) tabs.forEach((_, i) => keep.add(i));
  else {
    keep.add(active);
    for (let distance = 1; keep.size < cap && distance < tabs.length; distance++) {
      if (active - distance >= 0) keep.add(active - distance);
      if (keep.size < cap && active + distance < tabs.length) keep.add(active + distance);
    }
    for (let i = 0; keep.size < cap && i < tabs.length; i++) keep.add(i);
  }
  tabs.forEach((tab, i) => tab.classList.toggle('overflowed', !keep.has(i)));
  const hidden = tabs.length - keep.size;
  more.hidden = hidden <= 0; more.textContent = hidden > 0 ? `+${hidden}` : '⋯';
  more.title = hidden > 0 ? `${hidden} more open files` : 'all open files';
}
function leeTabOverflow(anchor) {
  const rows = $$('.lee-tab').map((tab, i) => ({tab, i})).filter(x => x.tab.classList.contains('overflowed')).map(({tab, i}) => ({
    label: $('.lee-tab-name', tab)?.textContent || `tab ${i + 1}`,
    detail: `${tab.classList.contains('dirty') ? 'unsaved · ' : ''}${tab.title || ''}`,
    run: () => htmxPost('/tab/select?i=' + i),
  }));
  openChromeMenu(anchor, rows);
}
window.leeTabOverflow = leeTabOverflow;
// Returns htmx's promise: closing several tabs has to await each swap, because the server
// addresses tabs by index and the next index is only true once the strip has been rebuilt.
function htmxPost(url) { return htmx.ajax('POST', url, {target: '#tabbar', swap: 'outerHTML'}); }
let openFileVersion=0;
function gitDiffTabKey(data) { return encodeURIComponent(`${data.kind || 'review'}\0${data.base || ''}\0${data.head || ''}\0${data.path}`); }
function syncGitDiffTabs() {
  const bar = $('#tabbar'); if (!bar) return;
  for (const [key, data] of lee.gitDiffTabs) {
    if ($(`.lee-tab[data-git-diff="${CSS.escape(key)}"]`, bar)) continue;
    const tab = document.createElement('div');
    tab.className = 'lee-tab lee-git-diff-tab' + (lee.activeGitTab === key ? ' active' : '');
    tab.dataset.gitDiff = key; tab.dataset.kind = 'git-diff'; tab.title = `${data.base} → ${data.head} · ${data.path}`;
    tab.setAttribute('role', 'tab'); tab.innerHTML = `<span class="lee-git-diff-dot">±</span><span class="lee-tab-name">${esc(data.path.split('/').pop())}</span><span class="lee-git-diff-ref">${esc(data.headLabel || data.head.slice(0, 8))}</span><button class="lee-tab-x" title="close diff" aria-label="close diff">×</button>`;
    tab.onclick = e => { if (e.target.closest('.lee-tab-x')) closeGitDiffTab(key); else activateGitDiffTab(key); };
    bar.appendChild(tab);
  }
  requestAnimationFrame(layoutTabs);
}
function closeGitDiffTab(key) {
  const wasActive = lee.activeGitTab === key, returnTab = lee.gitDiffTabs.get(key)?.returnTab || 0;
  lee.gitDiffTabs.delete(key); $(`.lee-tab[data-git-diff="${CSS.escape(key)}"]`)?.remove();
  if (wasActive) { lee.activeGitTab = ''; lee.gitMergeView && LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; htmxPost('/tab/select?i=' + Math.max(0, Number(returnTab) || 0)); }
  else layoutTabs();
}
async function openGitDiffTab(data) {
  const key = gitDiffTabKey(data), existing = lee.gitDiffTabs.get(key), returnTab = $('.lee-tab.active:not([data-git-diff])')?.dataset.i || existing?.returnTab || 0;
  lee.gitDiffTabs.set(key, {...existing, ...data, key, returnTab, view: existing?.view || data.view || 'unified'});
  syncGitDiffTabs(); await activateGitDiffTab(key);
}
async function activateGitDiffTab(key) {
  const data = lee.gitDiffTabs.get(key); if (!data) return;
  lee.activeGitTab = key; $$('.lee-tab').forEach(t => t.classList.toggle('active', t.dataset.gitDiff === key));
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  if (lee.gitMergeView) { LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; }
  lee.kind = 'git-diff'; lee.path = ''; lee.tabKey = `git-diff:${key}`; updateToolbarForKind('git-diff');
  const host = $('#editor'); if (!host) return;
  host.innerHTML = `<section class="lee-diff-document"><header><div><strong>${esc(data.path)}</strong><span>${esc(data.baseLabel || data.base)} → ${esc(data.headLabel || data.head)}</span></div><nav aria-label="Diff layout"><button data-diff-view="unified">unified</button><button data-diff-view="split">side by side</button>${isMarkdownPath(data.path) ? '<button data-diff-view="rendered">rendered</button>' : ''}</nav><span class="lee-spacer"></span><span class="lee-diff-edit-state" hidden>preview changed</span>${data.allowWrite ? '<button data-apply-merge-result hidden>apply result to working tree</button>' : ''}${data.reviewKey ? '<button data-review-note>note…</button><button data-review-mark>mark reviewed</button>' : ''}${data.can_apply ? '<button data-review-apply>apply hunks…</button>' : ''}${data.group ? '<button data-diff-hunks>select hunks</button>' : ''}<button data-open-source>open working file</button></header><div class="lee-diff-document-body"></div></section>`;
  host.querySelectorAll('[data-diff-view]').forEach(b => { b.classList.toggle('active', b.dataset.diffView === data.view); b.onclick = () => { data.view = b.dataset.diffView; activateGitDiffTab(key); }; });
  host.querySelector('[data-open-source]').onclick = () => data.absolutePath ? leeOpenFile(data.absolutePath) : status('this historical file has no working-tree path', 'err');
  host.querySelector('[data-diff-hunks]')?.addEventListener('click', () => showGitFileDiff(data.absolutePath || data.path, data.patch, 0, data.rawPatch || data.patch, !!data.notebook, {group: data.group, label: `${data.baseLabel} → ${data.headLabel}`}));
  const mark = host.querySelector('[data-review-mark]'); if (mark) { mark.classList.toggle('active', !!gitUI.reviewed[data.reviewKey]); mark.textContent = gitUI.reviewed[data.reviewKey] ? 'reviewed ✓' : 'mark reviewed'; mark.onclick = () => { gitUI.reviewed[data.reviewKey] = !gitUI.reviewed[data.reviewKey]; saveGitWorkflowState(); activateGitDiffTab(key); }; }
  host.querySelector('[data-review-note]')?.addEventListener('click', async () => { const note = await inputDialog('review note', `Note for ${data.path}`, gitUI.reviewNotes[data.reviewKey] || '', 'Question, risk, or follow-up'); if (note !== null) { if (note.trim()) gitUI.reviewNotes[data.reviewKey] = note.trim(); else delete gitUI.reviewNotes[data.reviewKey]; saveGitWorkflowState(); } });
  host.querySelector('[data-review-apply]')?.addEventListener('click', () => { gitUI.reviewFile = data.path; gitUI.reviewPatch = data.patch; showReviewHunkApply(gitUI.snapshot); });
  host.querySelector('[data-apply-merge-result]')?.addEventListener('click', async () => {
    if (data.mergeResult == null) return;
    const message = `Replace the working-tree version of ${data.path} with this reviewed result? The file will remain uncommitted.`;
    if (!await confirmDialog('apply split diff result', message, 'apply result')) return;
    try { const next = await gitDo('write_worktree', {path: data.path, content: data.mergeResult}), fresh = await api(gitUrl('/git/diff', {path: data.path, staged: false})); data.base = 'index'; data.head = 'worktree'; data.baseLabel = 'index'; data.headLabel = 'working tree'; data.left = fresh.left || ''; data.right = fresh.right || ''; data.patch = fresh.content || fresh.text || ''; data.rawPatch = fresh.text || ''; data.group = 'unstaged'; data.mergeResult = null; gitUI.review = null; paintGitPill(next); await activateGitDiffTab(key); status(`${data.path} updated in the working tree`, 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  const body = host.querySelector('.lee-diff-document-body');
  if (data.file?.binary) body.innerHTML = '<div class="lee-git-empty-state"><strong>Binary file changed</strong><span>Text comparison is not available for this file.</span></div>';
  else if (data.view === 'rendered' && isMarkdownPath(data.path)) await mountMarkdownDiff(body, data);
  else if (data.view === 'split') {
    body.className += ' split';
    const changed = result => { data.mergeResult = result; const state = host.querySelector('.lee-diff-edit-state'), apply = host.querySelector('[data-apply-merge-result]'); if (state) state.hidden = false; if (apply) apply.hidden = false; };
    lee.gitMergeView = LeeCM.createMerge(body, {left: data.left || '', right: data.mergeResult ?? data.right ?? '', lang: codeLang('', data.path), settings: lee.editorPrefs, readOnlyRight: !data.allowWrite, revertControls: data.allowWrite ? 'a-to-b' : false, onChange: data.allowWrite ? changed : null});
  } else {
    body.innerHTML = gitDiffNotebookHtml(data.patch, data);
    body.querySelectorAll('[data-fold-diff]').forEach(b => b.onclick = () => { const cell = b.closest('.lee-diff-cell'), folded = cell.classList.toggle('collapsed'); b.textContent = folded ? '+' : '−'; });
  }
  setScope('editor'); layoutTabs();
}
function gitDiffNotebookHtml(patch, data) {
  const parts = gitPatchParts(patch);
  if (!parts.hunks.length) return `<div class="lee-git-empty-state"><strong>No textual patch</strong><span>${data.path} has no line-level changes in this comparison.</span></div>`;
  return `<div class="lee-diff-notebook">${parts.hunks.map((h, i) => { const title = h.split('\n')[0] || `hunk ${i + 1}`; return `<article class="lee-diff-cell"><header><button data-fold-diff aria-label="collapse hunk">−</button><strong>change ${i + 1}</strong><code>${esc(title)}</code><span class="lee-spacer"></span><small>${h.split('\n').filter(x => x.startsWith('+') && !x.startsWith('+++')).length} added · ${h.split('\n').filter(x => x.startsWith('-') && !x.startsWith('---')).length} removed</small></header><div class="lee-git-patch">${gitPatchHtml(h)}</div></article>`; }).join('')}</div>`;
}
window.openGitDiffTab = openGitDiffTab;

/* ----------------------------------------------------- a Markdown diff, read as Markdown
 * A third way of reading the same diff, beside unified and side by side, and the only one in
 * which a README reads like a README: the new document rendered, with a bar in the margin
 * beside every block that changed and the line-level change shown *inside* a fenced block.
 *
 * The rendering is `/markdown/render`, unchanged and still `allow_raw: false` -- Markdown out
 * of a repository is untrusted input and this surface widens nothing. What makes the marks
 * placeable is `/markdown/diff`, which pairs the two versions block against block and reports
 * each block's source lines and the tag it should render as. Lines could not do this on their
 * own: a rendered paragraph has no line numbers, and an edit at the top of a file moves every
 * line below it while moving no blocks at all.
 */
const MARKDOWN_PATH = /\.(?:md|markdown|mdown|mkdn?)$/i;
const isMarkdownPath = path => MARKDOWN_PATH.test(String(path || ''));

// mdhtml's own top-level nodes, in document order. The footnotes section is generated from the
// definitions rather than from a block of its own, so it never carries a mark; a comment is a
// node a raw-HTML block legitimately produces, so it counts as a carrier even though there is
// nothing to draw beside it -- dropping it would silently shift every block after it.
function markdownCarriers(el) {
  return [...el.childNodes].filter(n => n.nodeType === 8 ||
    (n.nodeType === 1 && !(n.tagName === 'SECTION' && n.classList.contains('footnotes'))));
}
const markdownTagOf = n => n.nodeType === 1 ? n.tagName.toLowerCase() : '#comment';

/* Which element each block became. This is the crux of the whole view, and the part that has
 * to be allowed to fail: the server names the blocks in source order with the tag each is
 * expected to render as, and this walks the rendered nodes in that same order checking every
 * expectation it can. One mismatch, or one node no block claimed, and the answer is `null` --
 * a raw HTML block that produced two elements shifts everything after it, and a change bar
 * beside the wrong paragraph is a false statement about the diff. Nothing is drawn then, and
 * the surface says why rather than quietly looking correct.
 *
 * The answer is *positions*, not nodes, because the code-block upgrade later swaps each `<pre>`
 * for an editor surface in the same place. A caller that has to wait for a request before it can
 * draw reads the tags now and the nodes again afterwards, and the positions still hold.
 */
function alignMarkdownBlocks(tags, rows) {
  const pairs = [];
  let at = 0;
  for (const row of rows) {
    if (row.status === 'removed') { pairs.push({row, at: -1}); continue; }
    if (!row.renders) continue;                       // a link or footnote definition renders nothing
    if (at >= tags.length) return null;
    const tag = tags[at++], want = row.tags || [];
    if (want.length && !want.includes(tag)) return null;
    pairs.push({row, at: at - 1});
  }
  return at === tags.length ? pairs : null;
}

/* The line-level change inside one fenced block: the lines as they read now, additions on
 * green and removals struck through on pink, with `tokenDiffHtml` marking the words that
 * actually moved in a line that was edited. An LCS over lines is the same shape as the token
 * diff one level down and is affordable at a code fence's length; a pathologically long fence
 * falls back to "all of the old, then all of the new" rather than allocating a large matrix.
 */
function markdownCodeDiffHtml(before, after) {
  const a = String(before ?? '').replace(/\n$/, '').split('\n');
  const b = String(after ?? '').replace(/\n$/, '').split('\n');
  const line = (kind, html) => `<div class="lee-md-code-line ${kind}">${html || ' '}</div>`;
  if (a.length > 600 || b.length > 600)
    return a.map(x => line('del', esc(x))).join('') + b.map(x => line('add', esc(x))).join('');
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { rows.push({kind: 'ctx', now: b[j]}); i++; j++; }
    else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) rows.push({kind: 'add', now: b[j++]});
    else rows.push({kind: 'del', old: a[i++]});
  }
  // A removal immediately followed by an addition is one line somebody edited, and the words
  // that changed in it are the thing worth pointing at on both halves.
  return rows.map((r, k) => {
    if (r.kind === 'ctx') return line('ctx', esc(r.now));
    if (r.kind === 'del') {
      const twin = rows[k + 1]?.kind === 'add' ? rows[k + 1] : null;
      return line('del', twin ? tokenDiffHtml(r.old, twin.now) : esc(r.old));
    }
    const prior = rows[k - 1]?.kind === 'del' ? rows[k - 1] : null;
    return line('add', prior ? tokenDiffHtml(r.now, prior.old) : esc(r.now));
  }).join('');
}

// Pink for text that changed, green for text that is new, amber for a code fence -- the three
// the reader has to tell apart at a glance, and the same three the gutter already uses.
const markdownChangeKind = row => row.status === 'added' ? 'added'
  : row.status !== 'modified' ? '' : row.type === 'code_block' ? 'code' : 'modified';

function paintMarkdownDiff(doc, rows) {
  const nodes = markdownCarriers(doc), pairs = alignMarkdownBlocks(nodes.map(markdownTagOf), rows);
  const note = doc.parentElement?.querySelector('[data-md-diff-note]');
  if (!pairs) { if (note) note.hidden = false; return false; }
  // A removed block has nothing left to render, so it is reported on the block that now stands
  // where it stood: a second, thinner mark and the old text in the tooltip. Removals with
  // nothing after them belong to the last block in the document.
  let removed = [], last = null;
  for (const {row, at} of pairs) {
    if (row.status === 'removed') { removed.push(row); continue; }
    const node = nodes[at];
    let host = node;
    // A fenced block is the one place a rendering can carry a line diff itself, and it is also
    // the one place the mark cannot simply be put on the element: `enhanceCodeBlocks` replaces
    // every `pre > code` with an editor surface a moment after this runs. An edited fence
    // becomes the interleaved diff, which has no `<code>` for the upgrade to find; a fence that
    // is new keeps its highlighted rendering and gets a wrapper to hold the mark instead.
    if (row.type === 'code_block' && node?.nodeType === 1 && node.tagName === 'PRE'
        && (row.status !== 'equal' || removed.length)) {
      host = document.createElement('div');
      if (row.status === 'modified') {
        host.className = 'lee-md-code-diff';
        host.innerHTML = `<pre>${markdownCodeDiffHtml(row.old_code || '', row.code || '')}</pre>`;
        node.replaceWith(host);
      } else { node.replaceWith(host); host.className = 'lee-md-code-host'; host.appendChild(node); }
    }
    if (host?.nodeType !== 1) continue;               // a comment carries no mark
    last = host;
    const kind = markdownChangeKind(row), notes = [];
    if (kind === 'added') notes.push('added in this change');
    else if (kind) notes.push(`was:\n${row.old || ''}`);
    if (removed.length) {
      const gone = removed.reduce((n, r) => n + r.to - r.from + 1, 0);
      host.dataset.removedAbove = String(gone);
      notes.push(`${gone} line${gone === 1 ? '' : 's'} removed here:\n${removed.map(r => r.source).join('\n\n')}`);
      removed = [];
    }
    if (!kind && !host.dataset.removedAbove) continue;
    host.classList.add('lee-md-change');
    if (kind) host.dataset.change = kind;
    host.title = notes.join('\n\n');
  }
  if (removed.length && last) {
    const gone = removed.reduce((n, r) => n + r.to - r.from + 1, 0);
    last.classList.add('lee-md-change'); last.dataset.removedBelow = String(gone);
    last.title = `${last.title ? last.title + '\n\n' : ''}${gone} line${gone === 1 ? '' : 's'} removed after this:\n${removed.map(r => r.source).join('\n\n')}`;
  }
  return true;
}

async function mountMarkdownDiff(body, data) {
  body.classList.add('lee-md-diff');
  body.innerHTML = `<div class="lee-md-diff-stat"></div>` +
    `<div class="lee-md-diff-note" data-md-diff-note hidden>The blocks of this document cannot be matched to the elements they rendered as, so no change bars are drawn. Read it as unified or side by side to see where the change is.</div>` +
    `<article class="lee-md-preview lee-md-diff-doc" data-markdown=""></article>`;
  let d;
  try { d = await post('/markdown/diff', {left: data.left || '', right: data.right || ''}); }
  catch (e) {
    body.innerHTML = `<div class="lee-git-empty-state"><strong>Rendered diff unavailable</strong><span>${esc(e.message || e)}</span></div>`;
    return;
  }
  const rows = d.blocks || [], changed = rows.filter(r => r.status !== 'equal').length;
  body.querySelector('.lee-md-diff-stat').innerHTML =
    `<span class="add">+${d.added || 0}</span><span class="del">−${d.removed || 0}</span>` +
    `<span class="lee-dim">${changed || 'no'} changed block${changed === 1 ? '' : 's'}</span>` +
    `<span class="lee-spacer"></span><span class="lee-md-diff-legend">` +
    `<i data-change="added"></i>added<i data-change="modified"></i>changed<i data-change="code"></i>code<i data-change="removed"></i>removed</span>`;
  const doc = body.querySelector('.lee-md-diff-doc');
  if (!String(data.right || '').trim()) {
    doc.innerHTML = `<div class="lee-git-empty-state"><strong>Nothing left to render</strong>` +
      `<span>This comparison removes the whole file; its ${d.removed || 0} removed lines are in the unified view.</span></div>`;
    return;
  }
  // The document is rendered by the same route as every other Markdown surface in the app, and
  // annotated on the fragment it produced -- there is no second renderer here.
  renderMarkdown(doc, data.right || '', false, () => paintMarkdownDiff(doc, rows));
}

/* The same marks on the file's own rendered pane, from the ranges the gutter beside it is
 * already drawing. This is the line-range route rather than the block-pairing one: `/git/file`
 * reports changed lines in the working tree's own numbering, and a block owns a range when the
 * two overlap -- Git points a pure deletion at the line that closed over it, so a removal lands
 * on the block that now stands there.
 *
 * Only the first render asks. While the file is being typed the ranges describe the version on
 * disk, and the honest number of marks for a paragraph that has moved under them is none. The
 * tags are read before the request goes out, because by the time it answers the code-block
 * upgrade has already replaced every `<pre>` with an editor surface.
 */
async function paintMarkdownFileChanges(el, ranges) {
  if (!ranges?.length) return;
  const text = el.dataset.markdown, tags = markdownCarriers(el).map(markdownTagOf);
  let d;
  try { d = await post('/markdown/blocks', {text, ranges}); } catch (_) { return; }
  if (!el.isConnected || el.dataset.markdown !== text) return;
  const blocks = (d.blocks || []).map((b, i) => ({...b, kind: (d.kinds || [])[i]}));
  const pairs = alignMarkdownBlocks(tags, blocks);
  if (!pairs) return;
  const nodes = markdownCarriers(el);
  for (const {row, at} of pairs) {
    const node = nodes[at];
    if (!row.kind || node?.nodeType !== 1) continue;
    node.classList.add('lee-md-change'); node.dataset.change = row.kind;
    node.title = row.kind === 'added' ? 'added since HEAD'
      : row.kind === 'removed' ? 'text was removed here' : 'changed since HEAD';
  }
}

async function leeOpenFile(path) {
  // The absolute path is the identity. Use one versioned request rather than HTMX's
  // implicit swap: an older response must never remount a same-named file from another root.
  path=String(path||'');const version=++openFileVersion;lee.pendingFocusPath=path;
  // File rows stopPropagation on their own onclick, so the document listener never paints
  // `.sel`. Keyboard navigation already calls selectTreeNode; keep mouse opens in sync.
  const treeNode = $$('.lee-node').find(n => n.dataset.path === path);
  if (treeNode) selectTreeNode(treeNode);
  const response=await fetch('/tab/open?path='+encodeURIComponent(path),{method:'POST',headers:{'HX-Request':'true'}});
  if(!response.ok)throw new Error(await response.text());const html=await response.text();
  if(version!==openFileVersion)return;
  const doc=new DOMParser().parseFromString(html,'text/html'),fresh=doc.querySelector('#tabbar'),old=$('#tabbar');
  if(!fresh||!old)throw new Error('tab open returned no tab bar');old.replaceWith(fresh);htmx.process(fresh);
  await mountTab(path);await leeVars();refreshProjectPills();requestAnimationFrame(layoutTabs);
  const after = $$('.lee-node').find(n => n.dataset.path === path);
  if (after) selectTreeNode(after);
}
window.leeOpenFile = leeOpenFile;

/* ------------------------------------------------------------------ editor */
function updateToolbarForKind(kind) {
  const notebook = kind === 'notebook', text = kind === 'text';
  const visibility = {run_cell: notebook, run_advance: notebook, run_file: text, run_selection: text};
  for (const [action, shown] of Object.entries(visibility)) {
    const button = $(`#toolbar [data-action="${action}"]`); if (button) button.hidden = !shown;
  }
}

let mountTabVersion=0;
function saveTabLocation() {
  const view = curEditor(), key = lee.path || lee.tabKey;
  if (!view || !key) return;
  // A Map keeps a re-set key at its *first* insertion point, so without the delete the tail
  // slice below persisted the eighty oldest files ever opened and dropped the recent ones.
  lee.locations.delete(key);
  lee.locations.set(key, {pos: LeeCM.cursor(view), scroll: view.scrollDOM.scrollTop,
    cell: lee.kind === 'notebook' ? lee.sel : -1});
  // Nothing else prunes this: a closed, renamed or deleted file leaves its entry behind, so
  // the cap is what keeps a long session (and sessionStorage) bounded.
  for (const stale of [...lee.locations.keys()].slice(0, lee.locations.size - 80)) lee.locations.delete(stale);
  try { sessionStorage.setItem('lee-tab-locations', JSON.stringify([...lee.locations])); } catch (_) {}
}
function restoreTabLocation(st, skip = false) {
  const key = st.path || st.title, loc = lee.locations.get(key);
  if (!loc || skip || lee.pendingLocation) return;
  requestAnimationFrame(() => {
    let view = lee.editors.get('file');
    if (st.kind === 'notebook' && loc.cell >= 0 && loc.cell < lee.cells.length) {
      selectCell(loc.cell); view = ensureCellMounted(loc.cell);
    }
    if (!view) return;
    LeeCM.setCursor(view, loc.pos); view.scrollDOM.scrollTop = loc.scroll || 0;
  });
}
async function mountTab(expectedPath = '') {
  saveTabLocation();
  const hadPendingLocation = Boolean(lee.pendingLocation);
  const mountVersion=++mountTabVersion;
  lee.activeGitTab = '';
  if (lee.gitMergeView) { LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; }
  syncGitDiffTabs();
  clearTimeout(lee.autoSaveTimer);
  lee.editVersion += 1; // invalidates an autosave response belonging to the previous tab
  const st=await api('/tab/state'+(expectedPath?'?path='+encodeURIComponent(expectedPath):''));
  if(mountVersion!==mountTabVersion)return;
  const recoveredDraft = await restoreDrafts(st);
  // Only the tab's own editors are torn down. The exec strip belongs to the app, not
  // to the tab, and destroying it here would silently leave the box unmounted.
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  const host = $('#editor'); if (!host) return;
  lee.kind = st.kind; lee.path = st.path || ''; lee.tabKey = st.path || st.title || ''; lee.cells = st.cells || [];
  await loadSettings(st.lang || (st.kind === 'notebook' ? 'python' : ''));
  updateToolbarForKind(st.kind);
  rememberRecentTab(st);
  lee.diskVersion = st.disk_version || ''; lee.seenDiskVersion = lee.diskVersion;
  // Tab navigation always returns Run and Variables to that tab's private kernel.
  paintEnv('');
  // The empty state is authored once, in Python's `_empty_editor`, and shipped as a template.
  if (!st.kind) { host.replaceChildren($('#leeempty')?.content.cloneNode(true) ?? ''); return; }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (st.kind === 'vault') await mountVault(host, st);
  else if (st.kind === 'pdf') mountPdf(host, st);
  else if (st.kind === 'notebook') mountNotebook(host, st);
  else await mountFile(host, st);
  if (recoveredDraft) {
    const tab = $('.lee-tab.active'); tab?.classList.add('dirty'); setTabSaveState(tab, 'pending');
    status('restored an unsaved browser draft · autosave will persist it', 'ok');
    scheduleAutoSave();
  }
  if (lee.pendingLocation && (!lee.pendingLocation.path || lee.pendingLocation.path === st.path)) {
    const loc = lee.pendingLocation; lee.pendingLocation = null;
    requestAnimationFrame(() => {
      // A notebook is a column of editors, each with its own line 1, so a location in one has
      // to name the cell. `cellIndex` is the fallback for a notebook whose cells carry no ids
      // of their own (anything written before nbformat 4.5), and the debug decorations are only
      // for the debugger: a search result is somewhere to go, not the line being executed.
      if ((loc.cellId || loc.cellIndex >= 0) && lee.kind === 'notebook') {
        let i = loc.cellId ? lee.cells.findIndex(c => c.id === loc.cellId) : -1;
        if (i < 0 && loc.cellIndex >= 0 && loc.cellIndex < lee.cells.length) i = loc.cellIndex;
        if (i >= 0) {
          selectCell(i); const view = ensureCellMounted(i);
          if (loc.debug) {
            LeeCM.setDebugLine(view, loc.line);
            paintDebugInlineValues(view, loc.line, lee.debugState?.variables);
          }
          jumpToLine(loc.line);
        }
      } else {
        jumpToLine(loc.line);
        if (loc.debug && lee.editors.get('file')) {
          LeeCM.setDebugLine(lee.editors.get('file'), loc.line);
          paintDebugInlineValues(lee.editors.get('file'), loc.line, lee.debugState?.variables);
        }
      }
    });
  }
  restoreTabLocation(st, hadPendingLocation);
  refreshKernelPill();
  if ($('#left')?.classList.contains('left-symbols')) leeSymbols();
  paintAgentAttachments();
  try { const split=JSON.parse(localStorage.getItem('lee-editor-split')||'null'); if(split?.path&&split.path!==st.path) await mountSecondary(split.path,split.direction); }
  catch (_) { localStorage.removeItem('lee-editor-split'); }
  if (lee.pendingFocusPath === st.path) {
    lee.pendingFocusPath = '';
    requestAnimationFrame(() => {
      const view = st.kind === 'text' ? lee.editors.get('file') : lee.editors.get(lee.cells[lee.sel]?.id);
      if (view) { LeeCM.focus(view); setScope('editor'); }
    });
  }
}

function rememberBuffer(key, payload) {
  lee.buffers.set(key, payload.text); lee.dirtyBuffers.add(key); persistDraft(key, payload);
  clearTimeout(lee.bufferTimers.get(key));
  lee.bufferTimers.set(key, setTimeout(() => {
    lee.bufferTimers.delete(key);
    const documentKey = payload.path || payload.title || lee.tabKey || key;
    post('/tab/buffer', {...payload, base_disk_version: draftBaseFor(documentKey)})
      .catch(e => status(String(e.message || e), 'err'));
  }, 120));
}

// A PDF, in the viewer the browser already ships. Reimplementing one on a canvas would be a
// worse viewer and a large amount of code, and we are in a browser after all -- so the whole
// feature is an `<iframe>` pointed at the bytes, plus the two things an iframe cannot do for
// itself: open the file outside Leela, and say something useful if the viewer is disabled.
function mountPdf(host, st) {
  // The filename goes in the *path* as well as the query, because the browser's own viewer titles
  // itself from the last path segment -- so `/file/raw?path=…` opened every document called
  // "raw". The segment is decoration: the server still resolves the file from `path` alone, and
  // must, or a name in a URL would become a way to ask for a different file.
  const name = (st.path || '').split('/').pop() || 'document.pdf';
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  host.innerHTML =
    `<div class="lee-doc">` +
    `<div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span><span class="lee-spacer"></span>` +
    `<a class="lee-btn" href="${esc(raw)}" target="_blank" rel="noopener noreferrer">open externally</a>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body"><iframe class="lee-pdf" title="${esc(st.title || 'PDF')}" src="${esc(raw)}"></iframe>` +
    `<noscript class="lee-dim">This view needs the browser's PDF viewer.</noscript></div></div>`;
}

async function mountFile(host, st) {
  const isProject = st.path?.endsWith('/pyproject.toml') || st.title === 'pyproject.toml';
  const crumbMode=lee.workbenchPrefs.breadcrumbs||'pathAndSymbols',crumb=crumbMode==='off'?'':`<nav class="lee-breadcrumbs" id="editorcrumbs" aria-label="File and symbol path"><span>${esc(compactPath(st.path||st.title||''))}</span></nav>`;
  // Markdown gets a rendered pane beside the editor. The editor stays mounted in every view and
  // is merely hidden by CSS when only the rendering is showing -- everything that reaches for
  // `lee.editors.get('file')` (saving, autosave, blame, the change gutter, jump-to-line) keeps
  // working, and "rendered" is a way of *looking* at the file rather than a different kind of tab.
  const isMd = (st.lang || '') === 'markdown';
  const view = isMd ? (localStorage.getItem('lee-md-view') || 'split') : '';
  host.innerHTML = crumb + (isProject ? '<div class="lee-package-summary" id="packagebar" hidden></div>' : '') +
    (isMd ? `<div class="lee-doc-head lee-md-bar"><div class="lee-segbar" id="mdview" aria-label="markdown view">` +
            ['edit', 'split', 'rendered'].map(v =>
              `<button class="lee-seg${v === view ? ' active' : ''}" data-md-view="${v}">${v}</button>`).join('') +
            `</div><span class="lee-spacer"></span>` +
            `<span class="lee-dim">the change gutter and blame stay on the source</span></div>` : '') +
    (isMd ? `<div class="lee-md-stage" data-view="${view}"><div class="lee-cm" id="filecm"></div>` +
            `<div class="lee-md-preview" id="mdpreview" data-markdown=""></div></div>`
          : '<div class="lee-cm" id="filecm"></div>');
  let git = {ranges: []}, packages = null;
  if (st.path) {
    const requests = [api('/git/file?path=' + encodeURIComponent(st.path)).catch(() => git)];
    if (isProject && lee.workbenchPrefs.dependencyHints !== false) requests.push(api('/editor/packages?path=' + encodeURIComponent(st.path)).catch(() => null));
    [git, packages] = await Promise.all(requests);
  }
  lee.fileGit = git;
  const key = st.path || st.title;
  const v = createEditor($('#filecm'), {
    // A cached value is authoritative only after an actual user edit. This guard prevents
    // stale/programmatic empty entries from blanking a freshly loaded file or run result.
    doc: lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : (st.text || ''),
    lang: st.lang || 'python', lineNums: true, lintPath: st.path || '',
    completeUrl: '/complete', changedLines: git.ranges || [], breakpoints: lee.breakpoints.get(st.path)||[],
    onBreakpoint: st.lang==='python' ? lines=>{rememberBreakpoints(st.path,lines);if(lee.directDebug)post('/debug/breakpoints',{path:st.path,breakpoints:lines}).catch(e=>status(e.message||String(e),'err'));} : null,
    onChangeClick: line => showChangePopup(st.path, line),
    onDefinition: name => findDefinition(name), onSelection: () => {
      clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120);
    },
    onChange: txt => {
      rememberBuffer(key, {path: key, kind: 'text', text: txt}); markDirty();
      // The preview follows the buffer, not the file: `renderMarkdown` is already debounced and
      // drops superseded renders, so this is safe to call on every keystroke.
      if (isMd) renderMarkdown($('#mdpreview'), txt);
    },
  });
  lee.editors.set('file', v);
  if (isMd) {
    // The rendered pane carries the same change marks as the gutter beside it, placed by block
    // rather than by line. Only this first render is annotated; see `paintMarkdownFileChanges`.
    renderMarkdown($('#mdpreview'), LeeCM.getDoc(v), false,
                   el => paintMarkdownFileChanges(el, git.ranges || []));
    $('#mdview').onclick = e => {
      const b = e.target.closest('[data-md-view]'); if (!b) return;
      const next = b.dataset.mdView;
      localStorage.setItem('lee-md-view', next);
      $('.lee-md-stage').dataset.view = next;
      $$('#mdview .lee-seg').forEach(x => x.classList.toggle('active', x === b));
      // The editor was display:none a moment ago, so CodeMirror has stale measurements and will
      // draw the cursor in the wrong place until it re-measures.
      if (next !== 'rendered') requestAnimationFrame(() => LeeCM.focus(v));
    };
  }
  if(st.lang==='python'&&st.path&&lee.editorPrefs.inlayHints)api('/lsp/inlay-hints',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:st.path,text:LeeCM.getDoc(v)})}).then(d=>LeeCM.setInlayHints?.(v,d.hints||[])).catch(()=>{});
  if(st.lang==='python'&&st.path&&['symbols','pathAndSymbols'].includes(crumbMode))api('/lsp/symbols',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:st.path,text:LeeCM.getDoc(v)})}).then(d=>{const el=$('#editorcrumbs');if(el){const names=(d.symbols||[]).slice(0,40).map(s=>`<button data-line="${(s.range?.start?.line||0)+1}">${esc(s.name)}</button>`).join('');el.insertAdjacentHTML('beforeend',`<i>›</i><span class="lee-breadcrumb-symbols">${names}</span>`);el.onclick=e=>{const b=e.target.closest('[data-line]');if(b)jumpToLine(b.dataset.line);};}}).catch(()=>{});
  if (packages) paintPackageVersions(v, packages);
  closeChangePopup(); armChangeGutter($('#filecm'));
  $('#filecm').addEventListener('focusin', () => { lee.activeEditor='primary'; setScope('editor'); });
}

async function mountSecondary(path, direction = 'vertical') {
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return;
  const st=await api('/tab/state?path='+encodeURIComponent(path));
  if (st.kind!=='text') return status('split view currently opens text files; notebooks stay in the primary editor','err');
  if (lee.editors.get('secondary')) { LeeCM.destroy(lee.editors.get('secondary')); lee.editors.delete('secondary'); }
  stage.classList.add('split',`split-${direction}`); stage.classList.remove(`split-${direction==='vertical'?'horizontal':'vertical'}`);
  host.hidden=false; host.innerHTML=`<div class="lee-split-head"><span>${esc(compactPath(st.path))}</span><button class="lee-btn" onclick="leeCloseSplit()">close</button></div><div class="lee-cm" id="filecm2"></div>`;
  const key=st.path,view=createEditor($('#filecm2'),{doc:lee.dirtyBuffers.has(key)?lee.buffers.get(key):(st.text||''),lang:st.lang||'python',lineNums:true,lintPath:st.path||'',completeUrl:'/complete',
    onDefinition:name=>findDefinition(name),onChange:txt=>{rememberBuffer(key,{path:key,kind:'text',text:txt});lee.editVersion+=1;const tab=$$('.lee-tab').find(x=>x.title===key);tab?.classList.add('dirty');setTabSaveState(tab,'pending');scheduleAutoSave();}});
  lee.editors.set('secondary',view);lee.secondaryPath=path;$('#filecm2').addEventListener('focusin',()=>{lee.activeEditor='secondary';setScope('editor');});localStorage.setItem('lee-editor-split',JSON.stringify({path,direction}));LeeCM.focus(view);
}
function leeCloseSplit(){const stage=$('#editorstage'),host=$('#editor2'),v=lee.editors.get('secondary');if(v)LeeCM.destroy(v);lee.editors.delete('secondary');lee.secondaryPath='';lee.activeEditor='primary';stage?.classList.remove('split','split-vertical','split-horizontal');if(host){host.hidden=true;host.innerHTML='';}localStorage.removeItem('lee-editor-split');}
window.leeCloseSplit=leeCloseSplit;
function leeSplit(direction='vertical') {
  const rows=$$('.lee-tab').filter(t=>t.dataset.kind==='text'&&t.title!==lee.path).map(t=>({path:t.title,label:$('.lee-tab-name',t)?.textContent||t.title}));
  if (!rows.length) return status('open another text file before splitting','err');
  const m=modal(`<div class="lee-mhead">Split editor<span class="sub">${direction==='vertical'?'side by side':'top and bottom'}</span></div><div class="lee-modallist">${rows.map((r,i)=>`<button class="lee-mrow" data-i="${i}"><strong>${esc(r.label)}</strong><span class="sub">${esc(compactPath(r.path))}</span></button>`).join('')}</div>`);
  $$('.lee-mrow',m).forEach(b=>b.onclick=()=>{const r=rows[+b.dataset.i];m.remove();mountSecondary(r.path,direction);});
}
window.leeSplit=leeSplit;

function paintPackageVersions(view, data) {
  LeeCM.setPackageVersions(view, data.packages || []);
  const bar = $('#packagebar'), s = data.summary || {};
  if (!bar) return;
  const env = String(s.python || '').replace(/\\/g, '/').split('/').slice(-2).join('/');
  bar.innerHTML = `<strong>environment</strong><span>${esc(env || 'python')}</span>` +
    `<span>${s.installed || 0}/${s.total || 0} installed</span>` +
    (s.mismatch ? `<span class="warn">${s.mismatch} version mismatch${s.mismatch === 1 ? '' : 'es'}</span>` : '') +
    (s.missing ? `<span class="err">${s.missing} missing</span>` : '<span class="ok">requirements satisfied</span>');
  bar.hidden = false;
}

async function refreshPackageVersions() {
  if (!lee.path?.endsWith('/pyproject.toml') || !lee.editors.get('file')) return;
  try { paintPackageVersions(lee.editors.get('file'), await api('/editor/packages?path=' + encodeURIComponent(lee.path))); }
  catch (_) {}
}

window.addEventListener('lee-package-open', e => {
  $('.lee-package-popover')?.remove();
  const item = e.detail?.item || {}, anchor = e.detail?.anchor;
  const p = document.createElement('aside'); p.className = 'lee-package-popover';
  const state = item.installed == null ? 'missing from this environment'
    : item.compatible === false ? 'installed version does not satisfy the declaration'
    : 'installed in this environment';
  p.innerHTML = `<div class="lee-inline-head"><strong>${esc(item.name || 'package')}</strong>` +
    `<button class="lee-icon" aria-label="close">×</button></div>` +
    `<dl><dt>declared</dt><dd>${esc(item.required || 'any version')}</dd>` +
    `<dt>installed</dt><dd>${esc(item.installed || 'not installed')}</dd>` +
    (item.marker ? `<dt>marker</dt><dd>${esc(item.marker)}</dd>` : '') +
    `<dt>runtime</dt><dd title="${esc(item.python || '')}">${esc(String(item.python || '').split('/').slice(-2).join('/'))}</dd></dl>` +
    `<p class="${item.installed == null || item.compatible === false ? 'warn' : 'ok'}">${esc(state)}</p>`;
  document.body.appendChild(p);
  const a = anchor?.getBoundingClientRect() || {left: innerWidth / 2, bottom: innerHeight / 2};
  const r = p.getBoundingClientRect(); p.style.left = Math.max(8, Math.min(a.left, innerWidth-r.width-8)) + 'px';
  p.style.top = Math.min(innerHeight-r.height-8, a.bottom+6) + 'px';
  p.querySelector('[aria-label="close"]').onclick = () => p.remove();
});
document.addEventListener('pointerdown', e => {
  if ($('.lee-package-popover') && !e.target.closest('.lee-package-popover, .cm-lee-package'))
    $('.lee-package-popover')?.remove();
}, true);

function notebookHeadings(cells) {
  return cells.flatMap((c, i) => c.cell_type === 'markdown' ? String(c.source || '').split('\n').flatMap(line => {
    const m = /^(#{1,6})\s+(.+?)\s*$/.exec(line); return m ? [{i, level: m[1].length, text: m[2].replace(/[*_`]/g, '')}] : [];
  }) : []);
}
function notebookToc(cells) {
  const headings = notebookHeadings(cells);
  const toc = document.createElement('details'); toc.className = 'lee-nb-toc';
  toc.innerHTML = `<summary>contents <span>${headings.length || 'no'} sections</span></summary><nav></nav>`;
  const nav = toc.querySelector('nav');
  if (!headings.length) nav.innerHTML = '<div class="lee-dim">Add Markdown headings to build the outline.</div>';
  else headings.forEach((h, at) => {
    const next = headings.slice(at + 1).find(x => x.level <= h.level);
    const row = document.createElement('div'); row.className = 'lee-toc-row'; row.style.setProperty('--level', h.level);
    row.innerHTML = `<button class="lee-toc-jump">${esc(h.text)}</button>` +
      `<button class="lee-toc-fold" title="collapse or expand this section">${lee.collapsedCells.has(cells[h.i].id) ? '+' : '−'}</button>`;
    row.querySelector('.lee-toc-jump').onclick = () => { toc.open = false; focusCell(h.i); };
    row.querySelector('.lee-toc-fold').onclick = () => {
      const end = next ? next.i : cells.length;
      for (let i = h.i; i < end; i++) setCellCollapsed(i, !lee.collapsedCells.has(cells[h.i].id));
      row.querySelector('.lee-toc-fold').textContent = lee.collapsedCells.has(cells[h.i].id) ? '+' : '−';
    };
    nav.appendChild(row);
  });
  return toc;
}
function observeNotebookCells(host, cells) {
  // Cell shells preserve the notebook's geometry; CodeMirror is only created near the
  // viewport. A 150-cell notebook therefore paints immediately instead of constructing
  // 150 editors in one uninterruptible task.
  lee.cellObserver?.disconnect();
  lee.cellObserver = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) {
      const i = +e.target.dataset.i; ensureCellMounted(i); lee.cellObserver?.unobserve(e.target);
    }
  }, {root: host, rootMargin: '700px 0px'});
  $$('.lee-cell', host).forEach((el, i) => {
    if (i === lee.sel || cells[i]?.running) ensureCellMounted(i);
    else lee.cellObserver.observe(el);
  });
}

function mountNotebook(host, st) {
  lee.cellObserver?.disconnect();
  for (const [key, view] of [...lee.editors.entries()]) {
    if (key === 'exec' || key === 'file') continue;
    LeeCM.destroy(view); lee.editors.delete(key);
  }
  host.innerHTML = '';
  host.appendChild(notebookToc(st.cells));
  st.cells.forEach((c, i) => host.appendChild(cellEl(c, i)));
  selectCell(Math.min(lee.sel, st.cells.length - 1));
  observeNotebookCells(host, st.cells);
  lee.notebookGit = {};       // marks belong to the notebook that was open, not the next one
  paintNotebookGitMarks();
  queueNotebookOverview();    // a notebook outside a repository still gets its viewport thumb
}

function patchNotebook(host, before, cells, op = '') {
  // Keep unchanged cell DOM and CodeMirror views alive. Moving those nodes is effectively
  // free and, unlike rebuilding the notebook, cannot flash blank or reset the viewport.
  lee.cellObserver?.disconnect();
  const oldCells = new Map(before.map(c => [c.id, c]));
  const oldEls = new Map($$('.lee-cell', host).map(el => [el.dataset.id, el]));
  const ids = new Set(cells.map(c => c.id));
  for (const [id, el] of oldEls) if (!ids.has(id)) {
    const view = lee.editors.get(id); if (view) LeeCM.destroy(view);
    lee.editors.delete(id); el.remove();
  }
  const toc = notebookToc(cells), oldToc = $('.lee-nb-toc', host);
  if (oldToc) oldToc.replaceWith(toc); else host.prepend(toc);
  cells.forEach((c, i) => {
    const old = oldCells.get(c.id);
    let el = oldEls.get(c.id);
    const changed = !old || old.source !== c.source || old.cell_type !== c.cell_type;
    if (!el || changed) {
      const view = lee.editors.get(c.id); if (view) LeeCM.destroy(view);
      lee.editors.delete(c.id);
      const key = `${lee.path || 'scratch'}:${c.id}`;
      lee.buffers.set(key, c.source); lee.dirtyBuffers.add(key);
      const fresh = cellEl(c, i);
      if (el) el.replaceWith(fresh);
      el = fresh;
    } else {
      el.dataset.i = i;
      el.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '');
      const buttons = $('.lee-cellbtns', el); if (buttons) buttons.innerHTML = cellButtons(i);
      const summary = $('.lee-cell-summary', el);
      if (summary) summary.textContent = String(c.source || '').trim().split('\n')[0] || 'empty cell';
      const gutter = $('#g-' + c.id); if (gutter) gutter.textContent = gutterFor(c);
      const context = $('.lee-cell-context', el); if (context) paintCellContext(context, c);
      setCellState(c, cellState(c)); setCellTime(c, c.execution_ms, c.running);
      if (op === 'clear' || op === 'clear_cell') renderOutputs(c);
    }
    host.appendChild(el); // appending an existing node reorders it without remounting
  });
  paintSel();
  observeNotebookCells(host, cells);
  // `className` is rewritten above for every reused cell, so the marks are reapplied from
  // what was last read rather than refetched -- the disk has not moved, only the DOM.
  repaintNotebookGitMarks();
  queueNotebookOverview();
}

function ensureCellMounted(i) {
  const c = lee.cells[i];
  if (!c || lee.editors.has(c.id)) return lee.editors.get(c?.id);
  mountCell(c, i);
  return lee.editors.get(c.id);
}

// A prompt cell's gutter is its own mark, so the three kinds are told apart at a glance
// without reading any of them.
const gutterFor = (c) => c.cell_type === 'code' ? '[' + (c.execution_count ?? ' ') + ']'
                       : c.cell_type === 'prompt' ? '✦' : 'md';
const cellState = (c) => c.running ? 'running' : c.cell_type === 'code' && c.execution_count != null
  ? (!c.fresh ? 'previous' : (c.outputs || []).some(o => o.output_type === 'error') ? 'error' : 'done') : 'idle';
const stateSvg = (state) => state === 'done'
  ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.2 2.8 2.8 6.2-6.2"/></svg>'
  : state === 'error'
    ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.5 4.5 7 7m0-7-7 7"/></svg>'
    : state === 'previous'
      ? '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5"/><path d="M8 5v3l2 1.5"/></svg>'
      : state === 'running' ? '<span class="lee-cell-spinner" aria-hidden="true"></span>' : '';
function setCellState(c, state, label = '') {
  const badge = $('#state-' + c.id); if (!badge) return;
  badge.className = 'lee-cell-state ' + state;
  badge.innerHTML = stateSvg(state);
  badge.title = label || ({done: 'ran successfully in the current kernel', error: 'run failed in the current kernel',
    previous: 'saved output from a previous kernel; run this cell to restore its variables', running: 'running'}[state] || 'not run');
  badge.setAttribute('aria-label', badge.title);
  queueNotebookOverview();      // a failure is one of the two things the stripe reports
}
function markPreviousRuns() {
  for (const c of lee.cells) {
    if (c.cell_type !== 'code' || c.execution_count == null) continue;
    c.fresh = false; setCellState(c, 'previous'); setCellTime(c, c.execution_ms, false);
  }
}
function formatCellTime(ms) {
  if (ms == null || !Number.isFinite(Number(ms))) return '';
  ms = Number(ms);
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function setCellTime(c, ms, running = false) {
  const el = $('#time-' + c.id); if (!el) return;
  el.textContent = formatCellTime(ms);
  el.hidden = !el.textContent;
  el.classList.toggle('running', running);
  const previous = !running && c.cell_type === 'code' && c.execution_count != null && !c.fresh;
  el.classList.toggle('previous', previous);
  el.title = running ? 'current execution time' : previous ? 'duration of the saved run; its variables are not in this kernel' : 'last execution time';
}

/* The per-cell controls, from the same table the toolbar comes from. They act on the cell
 * they are drawn in rather than on the selected one -- clicking ▶ on the third cell has
 * to run the third cell, whatever the cursor was doing. */
const contextLabel = mode => ({keep: 'keep context', discard: 'discard first', auto: 'context auto'}[mode] || 'context auto');
function paintCellContext(button, c) {
  const mode = c.context_mode || 'auto';
  button.dataset.mode = mode; button.textContent = contextLabel(mode);
  button.title = mode === 'keep' ? 'keep this cell if notebook context is compacted'
    : mode === 'discard' ? 'discard this cell first if notebook context is compacted'
    : 'automatically choose if notebook context is compacted';
}
async function cycleCellContext(i) {
  const c = lee.cells[i]; if (!c) return;
  const modes = ['auto', 'keep', 'discard'], mode = modes[(modes.indexOf(c.context_mode || 'auto') + 1) % modes.length];
  const r = await nbEdit({op: 'context', i, mode});
  Object.assign(c, r.cells[i]);
  const button = $(`.lee-cell[data-i="${i}"] .lee-cell-context`); if (button) paintCellContext(button, c);
  status(`cell ${i + 1}: ${contextLabel(mode)}`, 'ok');
}
window.leeCellContext = cycleCellContext;

function cellButtons(i) {
  const normal = (lee.bars.cell || []).map(b =>
    `<button class="lee-cbtn ${esc(b.kind)}" title="${esc(b.title)}" ` +
    `onclick="leeCellAct(${i}, '${esc(b.action)}')">${esc(b.label)}</button>`).join('');
  const debug = lee.cells[i]?.cell_type === 'code'
    ? `<button class="lee-cbtn" title="debug this cell (ipykernel)" onclick="leeDebugCell(${i})">◆</button>` : '';
  const more = `<button class="lee-cbtn" title="more cell actions" aria-label="more cell actions" ` +
    `onclick="leeCellMenu(${i}, this, event)">⋯</button>`;
  return debug + normal + more;
}
function leeCellAct(i, action) { selectCell(i); setScope('editor'); leeAct(action); }
function leeCellMenu(i, button, event) {
  event?.preventDefault(); event?.stopPropagation(); selectCell(i); setScope('editor');
  const r = button.getBoundingClientRect(); openMenu('cell', r.right - 4, r.bottom + 3);
}
window.leeCellAct = leeCellAct; window.leeCellMenu = leeCellMenu;

function cellEl(c, i) {
  const d = document.createElement('div');
  d.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '');
  d.dataset.i = i; d.dataset.id = c.id;
  d.style.setProperty('--lee-cell-lines', Math.min(20, Math.max(2, String(c.source || '').split('\n').length)));
  const state = cellState(c);
  d.innerHTML =
    `<div class="lee-gutter" draggable="true" title="drag to move cell">` +
    `<button class="lee-cell-fold" title="collapse cell" aria-label="collapse cell">${lee.collapsedCells.has(c.id) ? '+' : '−'}</button>` +
    `<div class="lee-execution-count" id="g-${c.id}">${gutterFor(c)}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cell-chrome">` +
    `<span class="lee-cell-summary">${esc(String(c.source || '').trim().split('\n')[0] || 'empty cell')}</span>` +
    `<span class="lee-cell-state ${state}" id="state-${c.id}" ` +
    `title="${state === 'done' ? 'ran successfully in the current kernel' : state === 'error' ? 'run failed in the current kernel' : state === 'previous' ? 'saved output from a previous kernel; run to restore variables' : 'not run'}">${stateSvg(state)}</span>` +
    `<time class="lee-cell-time" id="time-${c.id}" title="last execution time" ` +
    `${c.execution_ms == null ? 'hidden' : ''}>${esc(formatCellTime(c.execution_ms))}</time>` +
    `<button class="lee-cell-context" data-mode="${esc(c.context_mode || 'auto')}" ` +
    `onclick="event.stopPropagation();leeCellContext(${i})">${esc(contextLabel(c.context_mode || 'auto'))}</button>` +
    `<div class="lee-model-running" id="model-${c.id}" role="status" aria-live="polite" hidden>` +
    `<span class="lee-running-dot" aria-hidden="true">●</span>` +
    `<span class="lee-running-copy">Model is running</span>` +
    `<span class="lee-running-time"> · starting</span></div>` +
    `<div class="lee-cellbtns">${cellButtons(i)}</div></div>` +
    `<div class="lee-cm" id="cm-${c.id}"></div><div id="out-${c.id}"></div></div>`;
  d.addEventListener('mousedown', e => { selectCell(+d.dataset.i, e.shiftKey); setScope('editor'); });
  d.querySelector('.lee-cell-fold').onclick = e => { e.stopPropagation(); setCellCollapsed(+d.dataset.i); };
  const gutter = d.querySelector('.lee-gutter');
  gutter.addEventListener('dragstart', e => {
    if (!lee.cellSelection.has(+d.dataset.i)) selectCell(+d.dataset.i);
    e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/lee-cell', d.dataset.i);
    e.dataTransfer.setData('text/lee-cells', JSON.stringify([...lee.cellSelection].sort((a,b) => a-b)));
    d.classList.add('dragging');
  });
  gutter.addEventListener('dragend', () => {
    d.classList.remove('dragging'); $$('.lee-cell.drag-target').forEach(x => x.classList.remove('drag-target'));
  });
  d.addEventListener('dragover', e => {
    if (!e.dataTransfer.types.includes('text/lee-cell')) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move'; d.classList.add('drag-target');
  });
  d.addEventListener('dragleave', () => d.classList.remove('drag-target'));
  d.addEventListener('drop', e => {
    const from = Number(e.dataTransfer.getData('text/lee-cell'));
    if (!Number.isInteger(from)) return;
    let indices = [from]; try { indices = JSON.parse(e.dataTransfer.getData('text/lee-cells') || `[${from}]`); } catch (_) {}
    e.preventDefault(); d.classList.remove('drag-target');
    if (indices.length > 1) moveCellsTo(indices, +d.dataset.i); else moveCellTo(from, +d.dataset.i);
  });
  return d;
}

function setCellCollapsed(i, value = null) {
  const c = lee.cells[i]; if (!c) return;
  const collapsed = value === null ? !lee.collapsedCells.has(c.id) : value;
  if (collapsed) lee.collapsedCells.add(c.id); else lee.collapsedCells.delete(c.id);
  const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.toggle('collapsed', collapsed);
  const button = el?.querySelector('.lee-cell-fold'); if (button) button.textContent = collapsed ? '+' : '−';
}

function cellClipboardPayload(i) {
  const cell = lee.cells[i]; if (!cell || lee.kind !== 'notebook') return null;
  const view = lee.editors.get(cell.id);
  const payload = JSON.parse(JSON.stringify(cell));
  if (view) payload.source = LeeCM.getDoc(view);
  payload.running = false; payload.fresh = false;
  return payload;
}
function selectedCellIndices(fallback = lee.sel) {
  return [...(lee.cellSelection.size ? lee.cellSelection : new Set([fallback]))].filter(i => i >= 0 && i < lee.cells.length).sort((a,b) => a-b);
}
function copyCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to copy', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} copied — open another notebook and paste`, 'ok');
}
async function cutCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to cut', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  await nbEdit({op: 'delete_many', i: indices[0], indices});
  focusCell(Math.min(indices[0], lee.cells.length - 1));
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} cut`, 'ok');
}
async function pasteCell(i) {
  if (lee.kind !== 'notebook') return status('cells can only be pasted into a notebook', 'err');
  const cells = lee.cellClipboard?.cells || (lee.cellClipboard?.cell ? [lee.cellClipboard.cell] : []);
  if (!cells.length) return status('copy or cut cells first', 'err');
  const at = Math.max(0, Math.min(i, lee.cells.length));
  await nbEdit({op: 'paste_many', i: at, cells});
  focusCell(at); lee.cellSelection = new Set(cells.map((_, n) => at + n)); paintSel();
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} pasted from ${compactPath(lee.cellClipboard.from)}`, 'ok');
}

async function moveCellsTo(indices, to) {
  indices = [...new Set(indices)].sort((a,b) => a-b);
  const r = await nbEdit({op: 'move_many', i: indices[0], indices, target: to});
  const at = r.index ?? to; focusCell(at); lee.cellSelection = new Set(indices.map((_, n) => at + n));
  paintSel(); status(`${indices.length} cells moved`, 'ok');
}

async function moveCellTo(from, to) {
  const last = lee.cells.length - 1;
  to = Math.max(0, Math.min(to, last));
  if (from === to || from < 0 || from > last) return focusCell(from);
  await nbEdit({op: 'move', i: from, d: to - from});
  focusCell(to); status(`cell moved to ${to + 1}`, 'ok');
}

function mountCell(c, i) {
  if (lee.editors.has(c.id)) return;
  const key = `${lee.path || 'scratch'}:${c.id}`;
  // Only a docChanged transaction marks a buffer authoritative. A stale empty cache must
  // never replace the non-empty source returned by /tab/state after running a cell.
  const source = lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source;
  c.source = source;
  const v = createEditor($('#cm-' + c.id), {
    doc: source, lang: c.cell_type === 'code' ? 'python' : c.cell_type === 'markdown' ? 'markdown' : '',
    placeholder: c.cell_type === 'prompt' ? `ask the inline model — ${displayChord('mod+enter')} answers in place` : '',
    completeUrl: c.cell_type === 'code' ? '/complete' : null,
    onDefinition: c.cell_type === 'code' ? name => findDefinition(name) : null,
    breakpoints: lee.breakpoints.get(c.id) || [],
    // Line numbers relative to this cell, which is the only place they are drawn. A cell
    // mounted after the marks arrived would otherwise stay unmarked until the next save.
    changedLines: (lee.notebookGit?.lines || {})[c.id] || [],
    onBreakpoint: c.cell_type === 'code' ? lines => rememberBreakpoints(c.id, lines) : null,
    settings: {overviewMode:'off'},
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
    onChange: (txt) => {
      const at = lee.cells.findIndex(cell => cell.id === c.id); if (at < 0) return;
      lee.cells[at].source = txt;
      rememberBuffer(key, {path: lee.path, kind: 'notebook', i: at, id: c.id, text: txt});
      if (cellState(lee.cells[at]) !== 'idle') setCellState(lee.cells[at], 'stale', 'code changed since the last run');
      markDirty();
    },
  });
  lee.editors.set(c.id, v);
  $('#cm-' + c.id).addEventListener('focusin', () => {
    const at = lee.cells.findIndex(cell => cell.id === c.id);
    if (at >= 0) { lee.activeEditor='primary'; lee.sel = at; setScope('editor'); paintSel(); }
  });
  renderOutputs(c);
  if (c.running) {
    const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.add('running');
    setCellState(c, 'running', 'still running in the background');
    setCellTime(c, 0, true);
    if (c.cell_type === 'prompt') {
      const notice = $('#model-' + c.id);
      if (notice) { notice.hidden = false; notice.querySelector('.lee-running-time').textContent = ' · in background'; }
    }
  }
}

function renderOutputs(c) {
  const box = $('#out-' + c.id); if (!box) return;
  $$('[data-markdown]', box).forEach(el => {
    if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  });
  box.innerHTML = '';
  // A prompt cell's "output" is the answer, and it is stored in the cell rather than in
  // an nbformat output -- so it renders from its own fields.
  if (c.cell_type === 'prompt') {
    if ((c.calls || []).length) {
      const steps = document.createElement('div'); steps.className = 'lee-agent-steps lee-cell-agent-steps';
      for (const activity of c.calls) {
        const row = document.createElement('details'); renderAgentStep(row, activity); steps.appendChild(row);
      }
      box.appendChild(steps);
    }
    if (c.reply) {
      const reply = document.createElement('div');
      reply.className = 'lee-reply'; box.appendChild(reply);
      renderMarkdown(reply, c.reply);
      const usage = usageMeta(c.usage, '', c.usage?.model); if (usage) box.appendChild(usage);
    }
    return;
  }
  for (const o of (c.outputs || [])) box.appendChild(outputEl(o));
}

const stripAnsi = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, '');
const MAX_OUTPUT_CHARS = 60000;
function outputText(el, value) {
  const text = String(value || '');
  if (text.length <= MAX_OUTPUT_CHARS) { el.textContent = text; return; }
  el.textContent = text.slice(0, MAX_OUTPUT_CHARS);
  const folded = document.createElement('button');
  folded.className = 'lee-output-fold';
  folded.textContent = `show ${(text.length - MAX_OUTPUT_CHARS).toLocaleString()} more characters`;
  folded.title = 'Large outputs are folded to keep the notebook responsive';
  folded.onclick = () => { el.textContent = text; };
  el.appendChild(folded);
}

function closeInlinePopover() { $('.lee-inline-popover')?.remove(); }
function valueLensMeta(item) {
  return [item.type && item.type !== 'result' ? item.type : '', item.shape ? `shape ${item.shape}` : '',
          item.dtype ? `dtype ${item.dtype}` : ''].filter(Boolean).join(' · ') || 'runtime value';
}
function openValueLens(item, anchor, label = '') {
  if (!item) return;
  closeInlinePopover();
  const p = document.createElement('aside');
  p.className = 'lee-inline-popover lee-value-lens'; p.setAttribute('role', 'dialog');
  p.setAttribute('aria-label', `${label || item.name || 'result'} runtime value`);
  p.innerHTML = `<div class="lee-inline-head"><strong>${esc(label || item.path || item.name || 'result')}</strong>` +
    `<span>${esc(valueLensMeta(item))}</span><button class="lee-icon" aria-label="close">×</button></div>` +
    `<div class="lee-value-tree"></div><div class="lee-inline-actions">` +
    `<button class="lee-btn" data-copy>copy value</button>` +
    (item.accessor?.length && item.accessor[0] !== '_' ? `<button class="lee-btn" data-variables>variables</button>` : '') + `</div>`;
  const tree = $('.lee-value-tree', p);
  const row = (value, depth = 0) => {
    const shell = document.createElement('div'); shell.className = 'lee-value-node';
    const button = document.createElement('button'); button.className = 'lee-value-row';
    button.style.setProperty('--depth', depth);
    button.innerHTML = `<span class="lee-value-caret">${value.is_container ? '›' : ''}</span>` +
      `<strong>${esc(value.name || 'result')}</strong><small>${esc(value.type || '')}</small>` +
      `<span>${esc(value.value || '')}</span>`;
    shell.appendChild(button);
    if (value.is_container && value.accessor?.length) {
      const kids = document.createElement('div'); kids.className = 'lee-value-kids'; kids.hidden = true; shell.appendChild(kids);
      let open = false, loaded = false;
      button.onclick = async () => {
        open = !open; button.classList.toggle('open', open); kids.hidden = !open;
        if (!open || loaded) return;
        kids.innerHTML = '<div class="lee-value-loading">reading children…</div>';
        try {
          const acc = encodeURIComponent(JSON.stringify(value.accessor));
          const values = await api(`/vars/expand?accessor=${acc}&scope=${lee.execScope}`);
          kids.innerHTML = ''; values.forEach(child => kids.appendChild(row(child, depth + 1)));
          if (!values.length) kids.innerHTML = '<div class="lee-value-loading">no children</div>';
          loaded = true;
        } catch (e) { kids.innerHTML = `<div class="lee-value-error">${esc(e.message || e)}</div>`; }
      };
    }
    return shell;
  };
  tree.appendChild(row(item)); document.body.appendChild(p);
  const a = anchor?.getBoundingClientRect() || {left: innerWidth / 2, right: innerWidth / 2, top: innerHeight / 2, bottom: innerHeight / 2};
  const r = p.getBoundingClientRect(), below = a.bottom + 6;
  p.style.left = Math.max(8, Math.min(a.right - r.width, innerWidth - r.width - 8)) + 'px';
  p.style.top = (below + r.height < innerHeight - 8 ? below : Math.max(8, a.top - r.height - 6)) + 'px';
  $('[aria-label="close"]', p).onclick = closeInlinePopover;
  $('[data-copy]', p).onclick = () => { navigator.clipboard?.writeText(item.value || ''); status('value copied', 'ok'); };
  const show = $('[data-variables]', p);
  if (show) show.onclick = async () => {
    closeInlinePopover(); leePane('right', true); leeRight('vars'); await leeVars(); setScope('vars');
    const found = $$('#vars .lee-vrow').find(r => r.dataset.name === item.name);
    if (found) { selectVar(found); found.scrollIntoView({block: 'nearest'}); }
  };
}
window.openValueLens = openValueLens;
window.addEventListener('lee-inline-open', e => openValueLens(e.detail?.item, e.detail?.anchor));
document.addEventListener('pointerdown', e => {
  if ($('.lee-inline-popover') && !e.target.closest('.lee-inline-popover, .cm-lee-inline-value')) closeInlinePopover();
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeInlinePopover(); }, true);

function outputTone(o) {
  if (o.output_type === 'error') return 'error';
  if (o.output_type === 'stream' && o.name === 'stderr')
    return /\b(?:warning|warns?|deprecated|deprecation)\b/i.test(String(o.text || '')) ? 'warning' : 'log';
  if (o.output_type === 'execute_result' || o.output_type === 'display_data') return 'result';
  return 'output';
}
function outputEl(o) {
  const d = document.createElement('div');
  const tone = outputTone(o);
  d.className = `lee-out ${tone}`;
  if (o.output_type === 'stream') { outputText(d, o.text); return d; }
  if (o.output_type === 'error') {
    outputText(d, stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`);
    return d;
  }
  const data = o.data || {};
  if (data['image/png']) {
    const i = document.createElement('img');
    i.src = 'data:image/png;base64,' + data['image/png'];
    d.appendChild(i); return d;
  }
  if (data['text/markdown']) {
    d.classList.add('lee-md-output'); renderMarkdown(d, data['text/markdown']); return d;
  }
  if (data['text/html'] || data['image/svg+xml']) {
    // Rich reprs get their own shadow root. pandas ships a <style> block with every
    // DataFrame and `scoped` has been dead for years, so without this an output could
    // restyle the IDE around it. Very large HTML stays unparsed until requested: parsing
    // a multi-megabyte table on the main thread is enough to trigger Chrome's hang dialog.
    const rich = data['text/html'] || data['image/svg+xml'];
    const show = () => { d.textContent = ''; d.attachShadow({mode: 'open'}).innerHTML = rich; };
    if (rich.length > MAX_OUTPUT_CHARS) {
      const folded = document.createElement('button'); folded.className = 'lee-output-fold';
      folded.textContent = `render large rich output (${Math.round(rich.length / 1024).toLocaleString()}kb)`;
      folded.onclick = show; d.appendChild(folded);
    } else show();
    return d;
  }
  outputText(d, data['text/plain'] || '');
  return d;
}

function paintSel() {
  $$('.lee-cell').forEach(el => {
    const i = +el.dataset.i, selected = lee.cellSelection.has(i) || (!lee.cellSelection.size && i === lee.sel);
    el.classList.toggle('sel', selected); el.setAttribute('aria-selected', String(selected));
  });
}
function selectCell(i, extend = false) {
  if (!lee.cells.length) return;
  lee.sel = Math.max(0, Math.min(i, lee.cells.length - 1));
  if (extend) {
    const lo = Math.min(lee.cellAnchor, lee.sel), hi = Math.max(lee.cellAnchor, lee.sel);
    lee.cellSelection = new Set(Array.from({length: hi - lo + 1}, (_, n) => lo + n));
  } else { lee.cellAnchor = lee.sel; lee.cellSelection = new Set([lee.sel]); }
  paintSel();
}
function focusCell(i) {
  selectCell(i);
  const c = lee.cells[lee.sel]; if (!c) return;
  const cell = $(`.lee-cell[data-i="${lee.sel}"]`);
  // CodeMirror focuses its own scroller but cannot reveal itself inside the notebook's
  // outer scroller. Run-and-advance therefore used to move the caret below the viewport.
  cell?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  const v = ensureCellMounted(lee.sel);
  if (v) requestAnimationFrame(() => LeeCM.focus(v));
}
function focusCellPage(direction) {
  if (!lee.cells.length) return;
  const host = $('#editor'), current = $(`.lee-cell[data-i="${lee.sel}"]`);
  if (!host || !current) return focusCell(lee.sel + direction);
  const target = current.getBoundingClientRect().top + direction * Math.max(180, host.clientHeight * .78);
  const cells = $$('.lee-cell', host);
  const candidates = cells.filter(el => direction < 0 ? +el.dataset.i < lee.sel : +el.dataset.i > lee.sel);
  if (!candidates.length) return focusCell(direction < 0 ? 0 : lee.cells.length - 1);
  const next = candidates.reduce((best, el) =>
    Math.abs(el.getBoundingClientRect().top - target) < Math.abs(best.getBoundingClientRect().top - target) ? el : best);
  focusCell(+next.dataset.i);
}
function autoSaveEnabled() { return (lee.filePrefs.autoSave || 'afterDelay') !== 'off'; }
function normalizeSavedText(text) {
  const prefs=lee.filePrefs||{}; let out=String(text??'');
  if(prefs.trimTrailingWhitespace)out=out.split('\n').map(line=>line.replace(/[ \t]+$/,'')).join('\n');
  if(prefs.trimFinalNewlines)out=out.replace(/\n+$/,'');
  if(prefs.insertFinalNewline && out && !out.endsWith('\n'))out+='\n';
  return out;
}
function setTabSaveState(tab, state, detail = '') {
  if (!tab) return;
  const dot = $('.lee-save-state', tab); if (!dot) return;
  const labels = {
    pending: lee.path ? 'Changes queued for autosave' : 'Unsaved — choose a filename to save',
    saving: 'Saving changes…', saved: 'Saved on disk', error: 'Autosave failed',
  };
  dot.className = `lee-save-state ${state}`;
  dot.title = detail || labels[state] || state;
  dot.setAttribute('aria-label', dot.title);
  tab.dataset.saveState = state;
}
function scheduleAutoSave() {
  clearTimeout(lee.autoSaveTimer);
  if ((lee.filePrefs.autoSave || 'afterDelay') !== 'afterDelay' || !lee.path || lee.heldSaveConflicts.has(lee.path)) return;
  const version = lee.editVersion;
  lee.autoSaveTimer = setTimeout(async () => {
    if (lee.saving || version !== lee.editVersion) return scheduleAutoSave();
    lee.saving = true;
    setTabSaveState($('.lee-tab.active'), 'saving');
    try { await saveTab(true, version); }
    finally { lee.saving = false; if (version !== lee.editVersion) scheduleAutoSave(); }
  }, Math.max(100, Number(lee.filePrefs.autoSaveDelay) || 900));
}
document.addEventListener('focusout',e=>{if(lee.filePrefs.autoSave==='onFocusChange'&&!lee.heldSaveConflicts.has(lee.path)&&e.target.closest?.('.cm-editor')&&$('.lee-tab.active.dirty'))saveTab(true);});
window.addEventListener('blur',()=>{if(lee.filePrefs.autoSave==='onWindowChange'&&!lee.heldSaveConflicts.has(lee.path)&&$('.lee-tab.active.dirty'))saveTab(true);});
function markDirty() {
  lee.editVersion += 1;
  const t = $('.lee-tab.active');
  if (t) { t.classList.add('dirty'); setTabSaveState(t, 'pending'); }
  scheduleAutoSave();
}
function jumpToLine(line) {
  const v = lee.kind === 'notebook' ? lee.editors.get(lee.cells[lee.sel]?.id) : lee.editors.get('file');
  if (!v) return;
  const n = Math.max(1, Math.min(Number(line) || 1, v.state.doc.lines));
  const pos = v.state.doc.line(n).from;
  v.dispatch({selection: {anchor: pos}, scrollIntoView: true}); v.focus();
}
function openLocation(hit) {
  // A hit in a notebook reports two coordinates: `line` in the .ipynb JSON, which is what
  // ripgrep and blame speak, and the cell plus the line inside it, which is the only pair an
  // editor can open. Prefer the second when the server placed the hit; a notebook hit it could
  // not place keeps the file line, and lands nowhere, rather than opening a cell chosen at random.
  const name = hit.path.split('/').pop();
  const inCell = Number(hit.cell_line) > 0;
  if (!inCell && /\.ipynb$/i.test(hit.path)) {
    // Nowhere to scroll to: the JSON line is not a line of any cell's editor, and jumping to
    // it inside whichever cell happens to be selected would look like an answer.
    leeOpenFile(hit.path);
    return status(`${name} — line ${hit.line} of the notebook file is in no cell`, 'info');
  }
  const line = inCell ? Number(hit.cell_line) : hit.line;
  lee.pendingLocation = {path: hit.path, line,
                         cellId: hit.cell || '',
                         cellIndex: Number.isFinite(hit.cell_index) ? Number(hit.cell_index) : -1};
  leeOpenFile(hit.path);
  status(`${name}${inCell ? ` · cell ${Number(hit.cell_index) + 1}` : ''}:${line}`);
}

async function stopCell(i) {
  const c = lee.cells[i];
  if (!c?.running) return status(`cell ${i + 1} is not running`, 'err');
  status(`stopping cell ${i + 1}…`);
  const r = await post('/nb/interrupt', {path: lee.tabKey || '', id: c.id});
  status(r.forced ? 'cell stopped · kernel restarted because interrupt was ignored' : 'cell stopped',
         r.forced ? 'err' : 'ok');
}

async function runCell(i, advance) {
  const c = lee.cells[i]; if (!c) return;
  if (c.running) return status(`cell ${i + 1} is already running`, 'err');
  const runPath = lee.path, cellId = c.id;
  const v = ensureCellMounted(i);
  const src = v ? LeeCM.getDoc(v) : c.source;
  const el = $(`.lee-cell[data-i="${i}"]`);
  if (c.cell_type === 'markdown') {
    // Rendering must not make the source editor disappear permanently. Keep both visible:
    // the preview is evidence of Run, and the source remains one click away to edit.
    const out = $('#out-' + c.id);
    if (out) {
      out.innerHTML = '<div class="lee-md"></div>';
      renderMarkdown(out.querySelector('.lee-md'), src, true);
    }
  } else if (c.cell_type === 'prompt') {
    c.running = true;
    try { await askCell(i, src, el); }
    finally { c.running = false; }
  } else {
    // PyCharm/Jupyter users expect code run from a file-backed notebook to be visible to
    // code that reads that notebook during the cell (indexers, nbdev, papermill). Flush
    // the complete browser document before execution; otherwise a newly created .ipynb
    // can still be zero-byte on disk while its in-memory cell is already running.
    if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) {
      return status('save the notebook before running this cell', 'err');
    }
    const began = performance.now();
    c.running = true;
    el?.classList.add('running');
    setCellState(c, 'running');
    setCellTime(c, 0, true);
    const cellClock = setInterval(() => setCellTime(c, performance.now() - began, true), 100);
    $('#g-' + c.id).textContent = '[*]';
    status(`running cell ${i + 1}…`);
    try {
      let r = null;
      await postEvents('/nb/run/stream', {i, id: cellId, path: runPath || lee.tabKey || '', source: src}, (event, data) => {
        const stillHere = lee.path === runPath && lee.cells[i]?.id === cellId;
        if (!stillHere) return;
        if (event === 'output') {
          lee.cells[i].outputs = data.outputs || [];
          renderOutputs(lee.cells[i]);
        } else if (event === 'error') throw new Error(data.text || 'cell execution failed');
        else if (event === 'done') r = data;
      });
      if (!r) throw new Error('cell execution ended without a result');
      const stillHere = lee.path === runPath && lee.cells[i]?.id === cellId;
      if (!stillHere) { leeVars(); return; }
      // Preserve the mounted cell object and its source/editor relationship. Replacing it
      // wholesale made stale buffer state able to win on a later remount and show blanks.
      Object.assign(c, r.cell);
      renderOutputs(r.cell);
      LeeCM.setInlineValues(v, r.inline || []);
      if (r.result) requestAnimationFrame(() => openValueLens(r.result, $('#out-' + c.id) || el, 'expression result'));
      $('#g-' + c.id).textContent = '[' + (r.cell.execution_count ?? ' ') + ']';
      const elapsed = Number(c.execution_ms ?? (performance.now() - began));
      const duration = formatCellTime(elapsed);
      setCellTime(c, elapsed, false);
      setCellState(c, r.ok ? 'done' : 'error', r.ok ? `ran successfully in ${duration}` : `failed after ${duration}`);
      status(r.ok ? `cell ${i + 1} ran in ${duration}` : `cell ${i + 1} failed after ${duration}`,
             r.ok ? 'ok' : 'err');
    } catch (e) {
      const elapsed = performance.now() - began;
      c.execution_ms = elapsed; setCellTime(c, elapsed, false);
      setCellState(c, 'error', `run failed after ${formatCellTime(elapsed)}`);
      status(String(e.message || e), 'err');
    } finally { clearInterval(cellClock); }
    c.running = false;
    el?.classList.remove('running');
    leeVars();
  }
  if (advance === 'insert') { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); }
  else if (advance) { if (i + 1 < lee.cells.length) focusCell(i + 1); else { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); } }
}

function paintDebugInlineValues(view, lineNo, variables) {
  if (!view || !lineNo || lee.debugPrefs.showInlineValues === false) return;
  const line = view.state.doc.line(Math.min(lineNo, view.state.doc.lines));
  const names = new Set((line.text.match(/[_A-Za-z]\w*/g) || []));
  const values = (variables || []).filter(v => names.has(v.name)).map(v => ({
    line: line.number, name: v.name, value: v.value || '', type: v.type || '',
    shape: null, dtype: null, is_grid: false, accessor: ['debug', Number(v.variablesReference) || 0],
  }));
  LeeCM.setInlineValues(view, values);
}

async function revealDebugFrame(state) {
  const frame = (state.frames || []).find(f => f.id === state.frame_id) || state.frames?.[0];
  if (!frame) return;
  // Exactly one source line is current. Clear the old marker before moving, including
  // when step-in changes files.
  for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
  if (frame.open_path) {
    $('#debugsource')?.remove();
    if (lee.path !== frame.open_path) {
      lee.pendingLocation = {path: frame.open_path, line: frame.line, debug: true,
                             cellId: frame.cell_id || ''};
      leeOpenFile(frame.open_path);
      return;
    }
    if (frame.cell_id && lee.kind === 'notebook') {
      const i = lee.cells.findIndex(c => c.id === frame.cell_id);
      if (i >= 0) {
        selectCell(i); const view = ensureCellMounted(i);
        LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line);
      }
    } else {
      const view = lee.editors.get('file');
      if (view) { LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line); }
    }
    return;
  }
  // Library frames are outside the workspace sandbox. Ask by frame id (never by an
  // arbitrary browser path) and show a read-only source view so step-in remains useful.
  if(lee.directDebug)return;
  const src = await api(`/nb/debug/source?frame_id=${frame.id}`);
  let pane = $('#debugsource');
  if (!pane) {
    pane = document.createElement('aside'); pane.id = 'debugsource'; pane.className = 'lee-debug-source-pane';
    pane.innerHTML = `<div class="lee-mhead">debug source <span class="sub"></span>` +
                     `<button class="lee-icon" aria-label="close">×</button></div>` +
                     `<div class="lee-debug-source-editor"></div>`;
    pane.querySelector('[aria-label="close"]').onclick = () => pane.remove();
    document.body.appendChild(pane);
  }
  pane.querySelector('.lee-mhead .sub').textContent = src.path || src.name || 'external frame';
  const host = pane.querySelector('.lee-debug-source-editor'); host.innerHTML = '';
  if (host._leeView) LeeCM.destroy(host._leeView);
  host._leeView = createEditor(host, {doc: src.content || '', lang: 'python', readOnly: true, lineNums: true});
  LeeCM.setDebugLine(host._leeView, src.line); const pos = host._leeView.state.doc.line(Math.min(src.line, host._leeView.state.doc.lines)).from;
  host._leeView.dispatch({selection: {anchor: pos}, scrollIntoView: true});
}

async function debugEvaluate(expression){return post(lee.directDebug?'/debug/evaluate':'/nb/debug/evaluate',lee.directDebug?{expression,frame_id:lee.debugState?.frame_id}:{code:expression,frame_id:lee.debugState?.frame_id});}
async function paintDebugWatches(panel=$('#debugger')){const host=$('.lee-debug-watches',panel);if(!host)return;host.innerHTML=lee.debugWatches.map((expression,i)=>`<div class="lee-debug-watch" data-i="${i}"><strong>${esc(expression)}</strong><span>evaluating…</span><button aria-label="remove">×</button></div>`).join('')||'<div class="lee-dim">no watch expressions</div>';
  $$('.lee-debug-watch',host).forEach(async row=>{row.querySelector('button').onclick=()=>{lee.debugWatches.splice(+row.dataset.i,1);localStorage.setItem('lee-debug-watches',JSON.stringify(lee.debugWatches));paintDebugWatches(panel);};try{const r=await debugEvaluate($('strong',row).textContent);$('span',row).textContent=r.result??r.value??'';}catch(e){$('span',row).textContent=e.message||String(e);}});}

function paintDebugger(state) {
  lee.debugState = state;
  let panel = $('#debugger');
  if (!panel) {
    panel = document.createElement('aside'); panel.id = 'debugger'; panel.className = 'lee-debugger';
    document.body.appendChild(panel);
  }
  const frames = state.frames || [], vars = state.variables || [];
  panel.innerHTML = `<div class="lee-debug-head"><strong>Paused at line ${esc(frames[0]?.line || '?')}</strong>` +
    `<span>${esc(frames[0]?.name || '')}</span><div class="lee-debug-controls">` +
    `<button title="continue" onclick="leeDebugControl('continue')">▶</button>` +
    `<button title="step over" onclick="leeDebugControl('next')">↷</button>` +
    `<button title="step into" onclick="leeDebugControl('stepIn')">↓</button>` +
    `<button title="step out" onclick="leeDebugControl('stepOut')">↑</button>` +
    `<button title="stop" onclick="leeDebugStop()">■</button></div></div>` +
    `<div class="lee-debug-body"><section><h4>call stack</h4>${frames.map(f =>
      `<button class="lee-debug-frame ${f.id === state.frame_id ? 'active' : ''}" onclick="leeDebugFrame(${f.id})">` +
      `${esc(f.name)} <span>line ${esc(f.line)}</span></button>`).join('')}</section>` +
    `<section><h4>locals <span class="lee-dim">expand in Variables</span></h4>${vars.map(v => `<div class="lee-debug-var"><strong>${esc(v.name)}</strong>` +
      `<span>${esc(v.value)}</span><small>${esc(v.type || '')}</small></div>`).join('') || '<div class="lee-dim">no locals</div>'}` +
    `<h4>watch</h4><form class="lee-debug-watch-form"><input class="lee-input" placeholder="expression"><button class="lee-btn">add</button></form><div class="lee-debug-watches"></div>` +
    `<h4>debug console</h4><form class="lee-debug-console-form"><input class="lee-input" placeholder="evaluate in selected frame"><button class="lee-btn">run</button></form><div class="lee-debug-console-out"></div></section></div>`;
  $('.lee-debug-watch-form',panel).onsubmit=e=>{e.preventDefault();const input=$('input',e.currentTarget),expression=input.value.trim();if(expression&&!lee.debugWatches.includes(expression)){lee.debugWatches.push(expression);localStorage.setItem('lee-debug-watches',JSON.stringify(lee.debugWatches));input.value='';paintDebugWatches(panel);}};
  $('.lee-debug-console-form',panel).onsubmit=async e=>{e.preventDefault();const input=$('input',e.currentTarget),expression=input.value.trim();if(!expression)return;try{const r=await debugEvaluate(expression);$('.lee-debug-console-out',panel).textContent=`${expression} → ${r.result??r.value??''}`;}catch(error){$('.lee-debug-console-out',panel).textContent=error.message||String(error);}};
  paintDebugWatches(panel);
  revealDebugFrame(state).catch(e => status(String(e.message || e), 'err'));
  leeScope('live'); leeRight('vars'); leeVars();
}

async function leeDebugFrame(frameId) {
  try {
    const state = await api(`${lee.directDebug?'/debug/state':'/nb/debug/state'}?frame_id=${frameId}`);
    paintDebugger(state);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeDebugFrame = leeDebugFrame;

async function leeDebugControl(command) {
  try {
    await post(lee.directDebug?'/debug/control':'/nb/debug/control', {command, thread_id: lee.debugThread});
    $('#debugger')?.classList.add('running'); status(`debugger: ${command}`);
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeDebugControl = leeDebugControl;

async function leeDebugStop() {
  try { await post(lee.directDebug?'/debug/stop':'/nb/debug/stop', {}); } catch (_) {}
  lee.debugThread = null; lee.debugCell = null; lee.debugState = null; lee.directDebug=false;
  $('#debugger')?.remove(); $('#debugsource')?.remove();
  for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
  leeScope('live'); leeVars(); status('debugger stopped', 'ok');
}
window.leeDebugStop = leeDebugStop;

async function debugCell(i) {
  const c = lee.cells[i]; if (!c || c.cell_type !== 'code') return;
  if (lee.debugCell != null) return status('a debugger session is already active', 'err');
  const view = ensureCellMounted(i), source = LeeCM.getDoc(view);
  let breakpoints = lee.breakpoints.get(c.id) || [];
  if (!breakpoints.length) {
    breakpoints = [LeeCM.lineOf(view)]; rememberBreakpoints(c.id, breakpoints);
    LeeCM.setBreakpoints(view, breakpoints);
  }
  lee.debugCell = i; c.running = true; setCellState(c, 'running');
  status(`starting ipykernel debugger for cell ${i + 1}…`);
  let done = null;
  try {
    await postEvents('/nb/debug/stream', {i, id: c.id, path: lee.path || lee.tabKey || '', source, breakpoints}, (event, data) => {
      if (event === 'ready') {
        rememberBreakpoints(c.id, data.breakpoints || breakpoints);
        LeeCM.setBreakpoints(view, data.breakpoints || breakpoints);
      } else if (event === 'stopped') {
        lee.debugThread = data.thread_id; $('#debugger')?.classList.remove('running');
        paintDebugger(data); status(`paused at line ${data.frames?.[0]?.line || '?'}`, 'ok');
      } else if (event === 'continued') {
        lee.debugThread = null; lee.debugState = null; $('#debugger')?.classList.add('running');
        for (const [key, editor] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(editor, 0); LeeCM.setInlineValues(editor, []); }
        leeVars();
      } else if (event === 'done') done = data;
      else if (event === 'error') throw new Error(data.text || 'debugger failed');
    });
    if (done?.cell) {
      Object.assign(c, done.cell); renderOutputs(c);
      $('#g-' + c.id).textContent = '[' + (c.execution_count ?? ' ') + ']';
      setCellState(c, done.ok ? 'done' : 'error');
    }
    status(done?.ok ? 'debug session finished' : (done?.error || 'debug session failed'), done?.ok ? 'ok' : 'err');
  } catch (e) { setCellState(c, 'error'); status(String(e.message || e), 'err'); }
  finally {
    c.running = false; lee.debugThread = null; lee.debugCell = null; lee.debugState = null;
    $('#debugger')?.remove(); $('#debugsource')?.remove();
    for (const [key, view] of lee.editors) if (key !== 'exec') { LeeCM.setDebugLine(view, 0); LeeCM.setInlineValues(view, []); }
    leeScope('live'); leeVars();
  }
}
window.leeDebugCell = debugCell;

/* Running a prompt cell. The answer lands in the cell rather than in the pane below,
 * which is the point of the cell type: it saves with the notebook and reads in order.
 *
 * The tab is deliberately *not* re-mounted afterwards even though the assistant's tools
 * may have edited files -- /tab/state reloads the notebook from disk, which would throw
 * away the answer that has not been saved yet. Files it changed are reported instead. */
async function askCell(i, src, el) {
  const c = lee.cells[i], runPath = lee.path, cellId = c.id;
  const notice = $('#model-' + c.id);
  const began = performance.now();
  let clock = null;
  el?.classList.add('running');
  $('#g-' + c.id).textContent = '…';
  if (notice) {
    notice.hidden = false;
    const tick = () => {
      const elapsed = performance.now() - began;
      const seconds = Math.floor(elapsed / 1000);
      setCellTime(c, elapsed, true);
      const time = notice.querySelector('.lee-running-time');
      if (time) time.textContent = seconds < 2 ? ' · starting' : ` · ${seconds}s elapsed`;
    };
    tick();
    clock = setInterval(tick, 1000);
  }
  status('model running…');
  try {
    let r = null, raw = '';
    const out = $('#out-' + c.id), seen = new Map();
    if (out) out.innerHTML = '<div class="lee-agent-steps lee-cell-agent-steps"></div><div class="lee-reply"></div>';
    await postEvents('/nb/ask/stream', {i, source: src}, (event, data) => {
      if (event === 'chunk') {
        raw += data.text || '';
        const reply = $('#out-' + c.id + ' .lee-reply');
        renderMarkdown(reply, raw);
      } else if (event === 'activity') {
        const steps = $('#out-' + c.id + ' .lee-agent-steps');
        let row = seen.get(data.id);
        if (!row && steps) { row = document.createElement('details'); steps.appendChild(row); seen.set(data.id, row); }
        if (row) renderAgentStep(row, data);
      } else if (event === 'approval') showApproval(data);
      else if (event === 'error') throw new Error(data.text || 'model failed');
      else if (event === 'done') r = data;
    });
    if (!r) throw new Error('the model stream ended without a result');
    if (lee.path !== runPath || lee.cells[i]?.id !== cellId) { leeVars(); return; }
    Object.assign(c, r.cell);
    renderOutputs(c);
    for (const e of (r.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const here = (r.edits || []).some(e => e.path === lee.path);
    showProblems(r.problems);
    status((r.problems || []).length ? r.problems[r.problems.length - 1]
           : here ? 'this notebook also changed on disk — your buffer wins until you save'
                  : (r.note || 'answered'),
           r.ok && !here && !(r.problems || []).length ? 'ok' : 'err');
    markDirty();
    leeVars();
  } catch (e) { status(String(e.message || e), 'err'); }
  finally {
    if (clock) clearInterval(clock);
    if (c.execution_ms == null) c.execution_ms = performance.now() - began;
    setCellTime(c, c.execution_ms, false);
    if (notice) notice.hidden = true;
  }
  $('#g-' + c.id).textContent = '✦';
  el?.classList.remove('running');
}

/* ---------------------------------------------------------- running files */
/* The exec log is where anything run outside a notebook cell lands -- the exec box, a
 * selection, a whole file. One place to look for "what have I asked this kernel to do". */
function execLine(code, text, ok) {
  const log = $('#execlog'); if (!log) return;
  const line = document.createElement('div');
  line.className = 'lee-runline' + (ok ? '' : ' err');
  line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                   `<span class="res">${esc((text || 'ok').trim())}</span>`;
  log.appendChild(line); log.scrollTop = log.scrollHeight;
}

/* Run the open .py as a script, in the tab's own kernel: `__main__`, an argv, and a
 * traceback that points at the file -- but with everything it defines left in the
 * namespace the variable panel is watching, which a subprocess could not do. */
async function runFile() {
  if (lee.kind !== 'text') return status('this is a notebook — run its cells, or “▶ all”', 'err');
  if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true))
    return status('save the file before running it', 'err');
  const v = lee.editors.get('file');
  const name = (lee.path || '').split('/').pop();
  status('running ' + name + '…');
  const r = await post('/run/file', {text: v ? LeeCM.getDoc(v) : null});
  execLine('▶ ' + r.label, r.text, r.ok);
  status(r.ok ? r.label + ' finished' : r.label + ' raised — see the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Just the selected code. Read straight off the CodeMirror state rather than through
 * `LeeCM`: the bundle in static/ is committed and rebuilding it needs node, so the client
 * does not grow a dependency on a wrapper function that is not in the shipped build. */
async function runSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const s = v.state.selection.main;
  const code = s.empty ? '' : v.state.doc.sliceString(s.from, s.to);
  if (!code.trim()) return status('select some code first', 'err');
  const r = await post('/run/code', {code});
  const head = code.trim().split('\n')[0].slice(0, 60);
  execLine(head + (code.trim().includes('\n') ? ' …' : ''), r.text, r.ok);
  status(r.ok ? 'ran the selection' : 'the selection raised — see the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Execute a bounded notebook range in order. Range commands deliberately run code cells
 * only: “run above” must not unexpectedly send every prompt cell above it to a model. */
async function runRange(start, end, label) {
  if (lee.kind !== 'notebook') return runFile();
  start = Math.max(0, start); end = Math.min(end, lee.cells.length);
  for (let i = start; i < end; i++) {
    const c = lee.cells[i];
    if (c.cell_type !== 'code' || !(c.source || '').trim()) continue;
    status(`running cell ${i + 1}…`);
    await runCell(i, false);
    if ((lee.cells[i].outputs || []).some(o => o.output_type === 'error'))
      return status(`cell ${i + 1} raised — stopped there`, 'err');
  }
  status(`ran ${label}`, 'ok');
}

async function runAll() {
  return runRange(0, lee.cells.length, 'every cell');
}

async function restartRunAll() {
  if (lee.kind !== 'notebook') return runFile();
  status('restarting kernel…');
  await post('/kernel/restart');
  markPreviousRuns();
  await runAll();
}

/* ---------------------------------------------------------- kernel picker */
/* Two questions, two lists: which interpreter's packages this tab can import, and which
 * launcher runs it. Both restart the kernel, so what that costs is on the screen while
 * the choice is being made rather than in a toast afterwards. */
async function pickKernel() {
  const o = await api('/kernel/options');
  const row = (cur, main, sub, attrs) =>
    `<div class="lee-mrow${cur ? ' sel' : ''}" ${attrs}>${cur ? '● ' : '○ '}${esc(main)}` +
    `<span class="sub">${esc(sub)}</span></div>`;
  const kinds = o.kinds.map(k => row(
    k.current, k.id,
    k.note || (k.id === 'ipymini' ? 'execs and completions run beside a busy cell'
                                  : 'the standard jupyter kernel'),
    `data-kind="${esc(k.id)}"${k.available ? '' : ' data-off="1"'}`)).join('');
  const pys = o.pythons.map(p => row(p.current, p.label, p.path, `data-py="${esc(p.path)}"`)).join('');
  const m = modal(
    `<div class="lee-mhead">kernel<span class="sub">${esc(o.key)} · ` +
    `${o.alive ? '⏺ running, pid ' + o.pid : '○ not started'} · ` +
    `${o.private ? 'private to this tab' : 'shared across this folder'}</span></div>` +
    (o.boot_error ? `<div class="lee-err">${esc(o.boot_error)}</div>` : '') +
    (o.api_error ? `<div class="lee-err">Inspector connection failed: ${esc(o.api_error)} <button class="lee-btn" data-kernel-reconnect>Restart kernel</button></div>` : '') +
    `<div class="lee-dim">choosing either of these restarts the kernel — its variables are lost</div>` +
    `<h4>launcher</h4><div class="lee-modallist">${kinds}</div>` +
    `<h4>interpreter</h4><div class="lee-modallist">${pys}</div>` +
    `<div class="lee-runtime-cwd"><span>working directory</span><code>${esc(o.cwd || '')}</code>` +
    `<button class="lee-btn" id="kernelcwd">change</button></div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="kernelattach">` +
    `${o.private ? 'attach to folder kernel' : 'give this tab its own kernel'}</button>` +
    `<span class="lee-dim">notebooks default to their own kernel; files share by folder</span></div>`);
  const reconnect = $('[data-kernel-reconnect]', m);
  if (reconnect) reconnect.onclick = async () => { await post('/kernel/restart'); m.remove(); status('kernel restarted', 'ok'); };
  m.querySelector('#kernelcwd').onclick = async () => {
    const cwd = await inputDialog('kernel working directory', 'folder inside an open project',
                                  o.cwd || '', '/path/to/project');
    if (!cwd || cwd === o.cwd) return;
    m.remove(); status('restarting kernel in ' + cwd + '…');
    const d = await post('/kernel/cwd', {cwd});
    markPreviousRuns(); paintEnv(''); status('kernel cwd: ' + d.cwd, 'ok'); refreshKernelPill(); leeVars();
  };
  m.querySelector('#kernelattach').onclick = async () => {
    const privateKernel = !o.private; m.remove(); status('changing kernel attachment…');
    const d = await post('/kernel/select', {private: privateKernel});
    markPreviousRuns(); paintEnv('');
    status(privateKernel ? 'this tab now has its own kernel' : 'attached to the folder kernel', 'ok');
    refreshKernelPill(); leeVars();
  };
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    if (r.dataset.off) {
      if (!o.python) return status('choose a project interpreter before installing kernel support', 'err');
      m.remove(); status('installing ipykernel and ipymini with uv…');
      const support = await post('/runtime/support', {python: o.python});
      status(support.ok ? 'kernel support installed · ipykernel + ipymini' : support.error,
             support.ok ? 'ok' : 'err');
      return pickKernel();
    }
    m.remove();
    status('starting the new kernel…');
    const d = await post('/kernel/select',
                         r.dataset.kind ? {kind: r.dataset.kind} : {python: r.dataset.py});
    markPreviousRuns();
    // Picking a runtime also makes its namespace the live variable source. Do not leave
    // the panel visually (or server-side) pinned to the process watched before the switch.
    paintEnv('');
    status(`kernel: ${d.running_kind} · ${(d.python || 'leela’s own python').split('/').pop()} · variables connected`, 'ok');
    refreshKernelPill(); leeVars();
  });
}

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

/* ---- whichever editor has the cursor: a cell, a whole file, or the exec box ---- */
function curEditor() {
  if (lee.scope === 'exec') return lee.editors.get('exec');
  if (lee.activeEditor === 'secondary') return lee.editors.get('secondary');
  if (lee.kind === 'notebook') { const c = lee.cells[lee.sel]; return c && lee.editors.get(c.id); }
  return lee.editors.get('file');
}
function curLang() {
  if (lee.scope === 'exec') return 'python';
  if (lee.kind === 'notebook') return lee.cells[lee.sel]?.cell_type === 'markdown' ? 'markdown' : 'python';
  return $('#editor')?.dataset.lang || 'python';
}

function kernelComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  LeeCM.startCompletion(v);
}

/* Two completions, two different questions. alt+/ asks the kernel what names
 * exist -- instant, and right by construction because it is the real namespace.
 * This asks the model what should come next, which costs a forward pass, so it is
 * never fired by typing and the suggestion stays ghost text until tab accepts it. */
function closeSelectionHelp() { $('.lee-selection-tools')?.remove(); }
function selectionEditor() {
  if (!['editor', 'exec'].includes(lee.scope)) return null;
  return curEditor();
}
function positionFloating(el, rect) {
  document.body.appendChild(el);
  const own = el.getBoundingClientRect(), left = Math.max(8, Math.min(rect.left, innerWidth - own.width - 8));
  const below = rect.bottom + 7, top = below + own.height < innerHeight - 8 ? below : Math.max(8, rect.top - own.height - 7);
  el.style.left = left + 'px'; el.style.top = top + 'px';
}
function showSelectionHelp() {
  if ($('.lee-selection-reply') || document.activeElement?.closest?.('.lee-selection-tools')) return;
  const view = selectionEditor(); if (!view) return closeSelectionHelp();
  const selected = LeeCM.selection(view); if (!selected?.text.trim()) return closeSelectionHelp();
  const rect = LeeCM.selectionCoords(view); if (!rect) return closeSelectionHelp();
  closeSelectionHelp();
  const tools = document.createElement('aside'); tools.className = 'lee-selection-tools';
  tools.innerHTML = `<button type="button" data-summary>summarise</button>` +
    `<button type="button" data-ask>ask AI</button>`;
  positionFloating(tools, rect);
  $('[data-summary]', tools).onclick = () => runSelectionHelp(view, selected, rect, 'summary');
  $('[data-ask]', tools).onclick = () => {
    tools.classList.add('asking');
    tools.innerHTML = `<input class="lee-input" placeholder="e.g. make this clearer, fix it, explain briefly…">` +
      `<button type="button" data-send>send</button>`;
    const input = $('input', tools); input.focus();
    const send = () => { const instruction = input.value.trim(); if (instruction) runSelectionHelp(view, selected, rect, 'instruction', instruction); };
    $('[data-send]', tools).onclick = send;
    input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); send(); } else if (e.key === 'Escape') closeSelectionHelp(); };
  };
}
async function runSelectionHelp(view, selected, rect, mode, instruction = '') {
  closeSelectionHelp();
  status(mode === 'summary' ? 'summarising selection with the local model…' : 'asking the inline model to rewrite the selection…');
  const panel = document.createElement('aside'); panel.className = 'lee-selection-reply loading';
  panel.innerHTML = `<header><strong>${mode === 'summary' ? 'Summarising selection' : 'Inline AI help'}</strong>` +
    `<span>working locally when available</span></header><div class="lee-selection-skeleton"><i></i><i></i><i></i></div>`;
  positionFloating(panel, rect);
  try {
    const result = await post('/complete/selection', {text: selected.text, mode, instruction, lang: curLang()});
    panel.classList.remove('loading'); panel.innerHTML = `<header><strong>${mode === 'summary' ? 'Summary' : 'Suggested replacement'}</strong>` +
      `<span>${esc(result.model || '')}</span></header><pre></pre><footer>` +
      `<button class="lee-btn" data-discard>discard</button><button class="lee-btn go" data-replace>replace selection</button></footer>`;
    $('pre', panel).textContent = result.text;
    $('[data-discard]', panel).onclick = () => panel.remove();
    $('[data-replace]', panel).onclick = () => {
      if (LeeCM.slice(view, selected.from, selected.to) !== selected.text)
        return status('selection changed while the model was answering; suggestion left open', 'err');
      LeeCM.replaceRange(view, selected.from, selected.to, result.text); panel.remove(); status('selection replaced', 'ok');
    };
    panel.onkeydown = e => {
      if (e.key === 'Escape') panel.remove();
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('[data-replace]', panel).click();
    };
    $('[data-replace]', panel).focus();
    status(`${mode === 'summary' ? 'summary' : 'replacement'} ready from ${result.model || 'the inline model'} · review before replacing`, 'ok');
  } catch (e) {
    panel.classList.remove('loading'); panel.innerHTML = `<div class="lee-selection-error">${esc(e.message || e)}</div>` +
      `<footer><button class="lee-btn" data-discard>close</button></footer>`;
    $('[data-discard]', panel).onclick = () => panel.remove();
  }
}
let selectionHelpTimer = null;
document.addEventListener('selectionchange', () => {
  clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 180);
});
document.addEventListener('pointerdown', e => {
  if ($('.lee-selection-tools') && !e.target.closest('.lee-selection-tools, .cm-editor')) closeSelectionHelp();
}, true);

async function aiComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  if (LeeCM.ghost(v)) { LeeCM.acceptGhost(v); return status('accepted', 'ok'); }
  const pos = LeeCM.cursor(v);
  status('checking Kosha graph, then asking the completion model…');
  const d = await post('/complete/ai', {code: LeeCM.getDoc(v), pos, lang: curLang(), cell: lee.sel});
  if (!d.text) return status(d.note || 'no suggestion', 'err');
  if (LeeCM.cursor(v) !== pos) return status('cursor moved while the model was thinking', 'err');
  LeeCM.focus(v);
  LeeCM.setGhost(v, d.text);
  const graph = d.graph_methods ? ` · ${d.graph_methods} Kosha graph method(s)` : '';
  status(`suggestion ready from ${d.model || 'the completion model'}${graph} · tab accepts · esc dismisses`, 'ok');
}

async function showDocs() {
  const v = curEditor();
  if (!v) return status('put the cursor on a name first', 'err');
  status('asking the kernel…');
  const d = await post('/inspect', {code: LeeCM.getDoc(v), pos: LeeCM.cursor(v)});
  if (!d.text) return status(d.note, 'err');
  status('');
  modal(`<div class="lee-mhead">docs<span class="sub">from the object the kernel actually has</span></div>
         <pre class="lee-docs">${esc(d.text)}</pre>`);
}

/* ------------------------------------------------------------------ diffs */
const diffHtml = (rows) => rows.map(r =>
  `<div class="lee-drow ${r.kind}"><span class="lee-dnum">${r.line || ''}</span>` +
  `<span class="lee-dtext">${esc(r.text)}</span></div>`).join('');

function diffModal(title, label, rows) {
  return modal(`<div class="lee-mhead">${esc(title)}<span class="sub">${esc(label)}</span></div>
                <div class="lee-diff">${diffHtml(rows)}</div>`);
}

// The dirty dot says *that* a tab changed. This says what changed -- the question
// actually worth answering before a save, or after something moved the file underneath.
function bufferBody() {
  return lee.kind === 'notebook'
    ? {cells: lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}))}
    : {text: lee.editors.has('file') ? LeeCM.getDoc(lee.editors.get('file')) : ''};
}

async function showDiff() {
  if (!lee.kind) return status('nothing open', 'err');
  const d = await post('/diff', bufferBody());
  if (!d.rows.length) return status('no unsaved changes', 'ok');
  status(`${d.label} unsaved`, 'ok');
  diffModal('unsaved changes — ' + d.title, d.label, d.rows);
}

async function openMergeConflict(conflictBox) {
  if (!lee.path) return status('save the document before merging it', 'err');
  const disk = await api('/tab/disk?path=' + encodeURIComponent(lee.path));
  if (lee.kind === 'notebook') {
    conflictBox?.remove(); const merges = [];
    const count = Math.max(lee.cells.length, (disk.cells || []).length);
    const m = modal(`<div class="lee-mhead">Resolve notebook conflict<span class="sub">cell-aware disk / draft merge</span></div>` +
      `<div class="lee-notebook-merge">${Array.from({length: count}, (_, i) => `<section><header>Cell ${i + 1} · ${esc(lee.cells[i]?.cell_type || disk.cells?.[i]?.cell_type || 'code')}</header><div data-cell-merge="${i}"></div></section>`).join('')}</div>` +
      `<div class="lee-mfoot"><span class="lee-dim">Disk is left; the result saved to the notebook is right.</span><span class="lee-spacer"></span><button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save-merge>save merged notebook</button></div>`,
      null, () => merges.forEach(LeeCM.destroyMerge), {className:'lee-merge-modal', storageKey:'notebook-merge'});
    for (let i = 0; i < count; i++) {
      const view = lee.cells[i] && lee.editors.get(lee.cells[i].id);
      const draft = view ? LeeCM.getDoc(view) : (lee.cells[i]?.source || '');
      merges[i] = LeeCM.createMerge($(`[data-cell-merge="${i}"]`, m), {left: disk.cells?.[i]?.source || '', right: draft,
        lang: lee.cells[i]?.cell_type === 'markdown' ? 'markdown' : 'python', settings: lee.editorPrefs});
    }
    $('[data-cancel]', m).onclick = () => m.remove();
    $('[data-save-merge]', m).onclick = async () => {
      for (let i = 0; i < Math.min(lee.cells.length, merges.length); i++) {
        const source = LeeCM.mergeResult(merges[i]); lee.cells[i].source = source;
        const view = lee.editors.get(lee.cells[i].id); if (view) LeeCM.setDoc(view, source);
      }
      const added = merges.slice(lee.cells.length).map((merge, n) => ({
        source: LeeCM.mergeResult(merge), cell_type: disk.cells?.[lee.cells.length + n]?.cell_type || 'code',
        metadata: {}, outputs: [], execution_count: null})).filter(cell => cell.source);
      if (added.length) await nbEdit({op:'paste_many', i:lee.cells.length, cells:added});
      m.remove(); await saveTab(false, disk.disk_version, true); status('merged notebook saved', 'ok');
    };
    return;
  }
  const draft = LeeCM.getDoc(lee.editors.get('file'));
  conflictBox?.remove();
  let mergeView = null;
  const m = modal(`<div class="lee-mhead">Resolve file conflict<span class="sub">disk on the left · editable result on the right</span></div>` +
    `<div class="lee-merge-host"></div><div class="lee-mfoot"><span class="lee-dim">Use the arrows to accept disk changes into your result.</span>` +
    `<span class="lee-spacer"></span><button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save-merge>save merged result</button></div>`,
    null, () => { if (mergeView) LeeCM.destroyMerge(mergeView); }, {className: 'lee-merge-modal', storageKey: 'merge'});
  mergeView = LeeCM.createMerge($('.lee-merge-host', m), {left: disk.text || '', right: draft,
    lang: curLang(), settings: lee.editorPrefs});
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save-merge]', m).onclick = async () => {
    const result = LeeCM.mergeResult(mergeView), view = lee.editors.get('file');
    LeeCM.setDoc(view, result); rememberBuffer(lee.path, {path: lee.path, kind: 'text', text: result});
    m.remove(); await saveTab(false, disk.disk_version, true); status('merged file saved', 'ok');
  };
}
function showSaveConflict(message) {
  if ($('.lee-save-conflict')) return;
  const box = modal(`<div class="lee-mhead">File changed on disk</div>` +
    `<div class="lee-dialogcopy">${esc(message)} Your browser draft is safe and has not been replaced.</div>` +
    `<div class="lee-mfoot"><button class="lee-btn go" data-keep>keep draft</button>` +
    `<button class="lee-btn" data-merge>merge changes</button>` +
    `<button class="lee-btn warn" data-overwrite>overwrite disk</button>` +
    `<button class="lee-btn" data-disk>load disk version</button></div>`);
  box.classList.add('lee-save-conflict');
  $('[data-keep]', box).onclick = () => {
    lee.heldSaveConflicts.add(lee.path); box.remove();
    setTabSaveState($('.lee-tab.active'), 'pending', 'Draft kept; press Save to review the disk conflict again');
    status('kept browser draft · automatic retries paused until you save or resolve it', 'ok');
  };
  $('[data-merge]', box).onclick = () => openMergeConflict(box);
  $('[data-overwrite]', box).onclick = async () => { lee.heldSaveConflicts.delete(lee.path); box.remove(); await saveTab(false, null, true); };
  $('[data-disk]', box).onclick = async () => { lee.heldSaveConflicts.delete(lee.path); box.remove(); await takeDiskVersion(lee.path); status('loaded disk version; browser draft discarded', 'ok'); };
}
async function saveTab(quiet = false, expectedVersion = null, force = false) {
  // A document the browser renders has no editor behind it, so there is nothing to write and
  // `getDoc` would be called on nothing. Reporting success is honest here: the file on disk is
  // exactly what is being shown.
  if (lee.kind === 'pdf') { if (!quiet) status('a PDF is read-only here'); return true; }
  let saveTabEl = $('.lee-tab.active');
  setTabSaveState(saveTabEl, 'saving');
  try {
    if (lee.activeEditor==='secondary' && lee.editors.get('secondary') && lee.secondaryPath) {
      const path=lee.secondaryPath,base_disk_version=draftBaseFor(path);
      const d=await post('/nb/save',{path,text:normalizeSavedText(LeeCM.getDoc(lee.editors.get('secondary'))),base_disk_version,force});
      lee.buffers.delete(path);lee.dirtyBuffers.delete(path);await clearDrafts(path);
      saveTabEl = $$('.lee-tab').find(x=>x.title===path); saveTabEl?.classList.remove('dirty');
      setTabSaveState(saveTabEl, 'saved');
      if(!quiet)status(`saved ${path.split('/').pop()}`,'ok');return true;
    }
    const bufferKeys = lee.kind === 'notebook'
      ? [...lee.bufferTimers.keys()].filter(k => k.startsWith((lee.path || 'scratch') + ':'))
      : [lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || ''];
    for (const k of bufferKeys) { clearTimeout(lee.bufferTimers.get(k)); lee.bufferTimers.delete(k); }
    let d;
    const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
    const base_disk_version = draftBaseFor(documentKey);
    if (lee.kind === 'notebook') {
      const cells = lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}));
      d = await post('/nb/save', {cells, base_disk_version, force});
    } else {
      let text=normalizeSavedText(LeeCM.getDoc(lee.editors.get('file')));
      if(lee.filePrefs.formatOnSave){try{const formatted=await post('/editor/format',{path:lee.path,lang:curLang(),text});text=formatted.text;if(text!==LeeCM.getDoc(lee.editors.get('file')))LeeCM.setDoc(lee.editors.get('file'),text);}catch(e){status(`format skipped: ${e.message||e}`,'err');}}
      d = await post('/nb/save', {text, base_disk_version, force});
    }
    // An autosave request may finish after another keystroke. The disk has its snapshot,
    // but the newer browser buffer must remain authoritative and schedule the next save.
    if (expectedVersion !== null && expectedVersion !== lee.editVersion) {
      // This request wrote an older snapshot, but newer typing is still in the editor and
      // IndexedDB. Rebase that draft on our own disk write so the follow-up autosave is not
      // mistaken for an external conflict.
      lee.diskVersion = d.disk_version || lee.diskVersion; lee.seenDiskVersion = lee.diskVersion;
      await rebaseDrafts(documentKey, lee.diskVersion);
      setTabSaveState(saveTabEl, 'pending', 'Newer changes are queued for autosave');
      return false;
    }
    lee.diskVersion = d.disk_version || lee.diskVersion; lee.seenDiskVersion = lee.diskVersion;
    const key = documentKey;
    if (lee.kind === 'notebook') {
      for (const k of [...lee.buffers.keys()]) if (k.startsWith((lee.path || 'scratch') + ':')) {
        lee.buffers.delete(k); lee.dirtyBuffers.delete(k);
      }
    } else { lee.buffers.delete(key); lee.dirtyBuffers.delete(key); }
    await clearDrafts(documentKey);
    lee.heldSaveConflicts.delete(documentKey);
    saveTabEl?.classList.remove('dirty');
    setTabSaveState(saveTabEl, 'saved');
    if (!quiet) status('saved', 'ok');
    refreshProjectPills();
    refreshOpenGitMarks();      // a notebook's marks are per cell, a file's per line
    if (lee.path?.endsWith('/pyproject.toml')) refreshPackageVersions();
    return true;
  } catch (e) {
    const message = String(e.message || e);
    setTabSaveState(saveTabEl, 'error', `Autosave failed: ${message}`);
    if (message.includes('changed on disk after this browser draft began')) {
      const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
      if (!quiet || !lee.heldSaveConflicts.has(documentKey)) showSaveConflict(message);
    }
    else status(message, 'err');
    return false;
  }
}

async function saveAllTabs() {
  // The active editor is saved through the same version-checked path as ordinary autosave.
  // Inactive editors are mirrored to the server within 120ms; let pending mirrors land
  // rather than cancelling their timers and accidentally saving the previous snapshot.
  if (!lee.kind) return status('nothing to save', 'err');
  if (!lee.path) return status('save the unnamed tab individually first', 'err');
  const activeDirty = !!$('.lee-tab.active.dirty');
  if (activeDirty && !await saveTab(true)) return;
  await new Promise(resolve => setTimeout(resolve, 140));
  try {
    const d = await post('/tabs/save-all'), saved = d.saved + (activeDirty ? 1 : 0);
    for (const tab of $$('.lee-tab')) {
      if (tab.classList.contains('dirty')) await clearDrafts(tab.title || $('.lee-tab-name', tab)?.textContent || '');
      tab.classList.remove('dirty'); setTabSaveState(tab, 'saved');
    }
    status(`saved ${saved} tab${saved === 1 ? '' : 's'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}

/* ------------------------------------------------------------------ exec */
function mountExec() {
  const host = $('#execbox'); if (!host || lee.editors.has('exec')) return;
  const v = createEditor(host, {
    doc: '', lang: 'python', placeholder: `python — ${displayChord('mod+enter')} runs · ctrl+shift+↑/↓ history`,
    completeUrl: '/complete', onDefinition: name => findDefinition(name),
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
  });
  lee.editors.set('exec', v);
  host.addEventListener('focusin', () => setScope('exec'));
  leeScope(lee.execScope);
  api('/exec/history').then(d => { lee.hist = d.cells || []; lee.histIdx = lee.hist.length; }).catch(() => {});
}

function leeScope(s) {
  lee.execScope = s;
  const scopeButton = $('.lee-bar-exec .lee-btn:nth-child(2)');
  if (scopeButton) { scopeButton.textContent = 'live/agent'; scopeButton.title = 'switch owner and protected agent namespaces'; }
  $('#sc-live')?.classList.toggle('active', s === 'live');
  $('#sc-agent')?.classList.toggle('active', s === 'agent');
  const tag = $('#execscope');
  if (tag) tag.textContent = s === 'live'
    ? (lee.debugState?.paused ? '· evaluates in the paused debug frame' : '· runs in your kernel')
    : '· protected agent session';
  leeVars();
}
window.leeScope = leeScope;

async function runExec() {
  const v = lee.editors.get('exec'); if (!v) return;
  const code = LeeCM.getDoc(v).trim(); if (!code) return;
  if (lee.execBusy) return status('exec is already running', 'err');
  lee.execBusy = true; status('running exec…');
  const log = $('#execlog');
  try {
    const r = await post('/exec', {code, scope: lee.execScope, frame_id: lee.debugState?.frame_id});
    const line = document.createElement('div');
    line.className = 'lee-runline' + (r.ok ? '' : ' err');
    line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                     `<span class="res">${esc((r.text || 'ok').trim())}</span>`;
    log.appendChild(line); log.scrollTop = log.scrollHeight;
    if (r.result) requestAnimationFrame(() => openValueLens(r.result, line, code));
    lee.hist.push(code); lee.histIdx = lee.hist.length;
    LeeCM.setDoc(v, '');
    if (r.debug && lee.debugState) {
      try { lee.debugState = await api(`/nb/debug/state?frame_id=${lee.debugState.frame_id}`); }
      catch (_) {}
    }
    leeVars();
  } catch (e) { status(String(e.message || e), 'err'); }
  finally { lee.execBusy = false; }
}

function recall(d) {
  const v = lee.editors.get('exec'); if (!v || !lee.hist.length) return;
  lee.histIdx = Math.max(0, Math.min(lee.hist.length, lee.histIdx + d));
  LeeCM.setDoc(v, lee.histIdx >= lee.hist.length ? '' : lee.hist[lee.histIdx]);
  LeeCM.focus(v, true);
}
function leeExecClear() { const l = $('#execlog'); if (l) l.innerHTML = ''; }
window.leeExecClear = leeExecClear;

/* ------------------------------------------------------------------ variables */
async function leeVars() {
  const box = $('#vars'); if (!box || document.hidden) return;
  // Polling is a refresh, not a queue. A slow inspector used to let the 2.5s interval
  // stack an unbounded number of fetches and full-tree DOM rebuilds until Chrome declared
  // the page unresponsive. Coalesce every request that arrives while one is in flight.
  if (lee.varsBusy) { lee.varsPending = true; return; }
  lee.varsBusy = true;
  try { await refreshVars(box); }
  finally {
    lee.varsBusy = false;
    if (lee.varsPending) { lee.varsPending = false; queueMicrotask(leeVars); }
  }
}
window.leeVars = leeVars;

async function refreshVars(box) {
  const profile = $('#varprofile')?.value || 'minimal';
  const sort = $('#varsort')?.value || 'recent';
  let d;
  if (lee.debugState?.paused) {
    const frame = (lee.debugState.frames || []).find(f => f.id === lee.debugState.frame_id);
    d = {runtime: `debug:${lee.debugState.thread_id}:${lee.debugState.frame_id}`,
         groups: [{label: `paused locals · ${frame?.name || 'frame'} · line ${frame?.line || '?'}`,
                   nodes: (lee.debugState.variables || []).map(debugVar)}]};
  } else {
    try { d = await api(`/vars?profile=${profile}&sort=${sort}&scope=${lee.execScope}`); }
    catch (e) { box.innerHTML = `<div class="lee-err">${esc(e.message)}</div>`; return; }
    if (d.error) {
      box.innerHTML = `<div class="lee-err"><strong>Dhrishti inspector unavailable</strong><span>${esc(d.error)}</span>` +
        `<button class="lee-btn" data-repair-inspector>Restart kernel and repair</button></div>`;
      $('[data-repair-inspector]', box).onclick = async () => {
        if (!await confirmDialog('Restart kernel', 'Repairing the inspector restarts this kernel and clears its live variables.', 'restart and repair')) return;
        await post('/kernel/restart'); markPreviousRuns(); await leeVars(); refreshKernelPill();
      };
      return;
    }
    if (d.python) paintEnv(String(d.python).split('/').slice(-3).join('/'));
    const envTag = $('#envtag');
    if (envTag && d.inspector) envTag.title = `${d.inspector} inspector · ${d.python || d.runtime}${d.cwd ? ' · cwd ' + d.cwd : ''}`;
  }

  // Every runtime gets its own little view memory. Switching notebooks should feel like
  // switching debugger sessions, not like one global tree whose open rows and filter leak.
  const runtime = d.runtime || 'default';
  if (lee.varRuntime !== runtime) {
    if (lee.varRuntime) lee.varStates.set(lee.varRuntime, {
      open: new Set(lee.varOpen), prev: lee.varPrev, seen: lee.varSeen,
      scroll: box.scrollTop, filter: $('#varfilter')?.value || '', selected: selVar()?.dataset.name || '',
    });
    const saved = lee.varStates.get(runtime) || {};
    lee.varRuntime = runtime; lee.varOpen = new Set(saved.open || []);
    lee.varPrev = saved.prev || {}; lee.varSeen = !!saved.seen;
    if ($('#varfilter')) $('#varfilter').value = saved.filter || '';
    lee.varRestore = {scroll: saved.scroll || 0, selected: saved.selected || ''};
  }

  // Most polls are identical. Avoid rebuilding the entire variable DOM every 2.5 seconds;
  // that work competes directly with CodeMirror selection and streamed Markdown painting.
  const fingerprint = JSON.stringify(d.groups || []);
  if (!lee.varRestore && lee.varFingerprints.get(runtime) === fingerprint) return;
  lee.varFingerprints.set(runtime, fingerprint);

  // A changed poll must not cost the user their place: remember what is open, selected,
  // and where the panel is scrolled, re-render, then put all three back.
  const scroll = lee.varRestore ? lee.varRestore.scroll : box.scrollTop;
  const selName = lee.varRestore ? lee.varRestore.selected : selVar()?.dataset.name;
  lee.varRestore = null;
  const cur = {};
  const html = (d.groups || []).map(g => {
    const rows = (g.nodes || []).map(n => { cur[n.name] = n.value; return varRow(n); }).join('');
    return g.label ? `<div class="lee-vgroup">${esc(g.label)}</div>${rows}` : rows;
  }).join('');
  box.innerHTML = html || '<div class="lee-dim">(no variables yet)</div>';
  lee.varPrev = cur; lee.varSeen = true;
  await Promise.all([...lee.varOpen].map(acc => fillKids(acc)));
  if (selName) $$(`#vars .lee-vrow`).find(r => r.dataset.name === selName)?.classList.add('sel');
  box.scrollTop = scroll;
  leeFilterVars();
}

function debugVar(v) {
  const ref = Number(v.variablesReference) || 0;
  return {name: v.name || '?', type: v.type || '', value: v.value || '', shape: null,
          accessor: ['debug', ref], is_container: ref > 0, is_grid: false, debug_reference: ref};
}

function varRow(n, depth = 0) {
  // new/edited is a statement about the namespace, so it only makes sense for top-level
  // names -- tagging a DataFrame's own `shape` as "(new)" is noise, not news. Nor does
  // the very first render, where by definition everything is new.
  const tag = (depth || !lee.varSeen) ? ''
            : (!(n.name in lee.varPrev)) ? '<span class="lee-vnew"> (new)</span>'
            : (lee.varPrev[n.name] !== n.value ? '<span class="lee-vedit"> (edited)</span>' : '');
  const typ = n.shape ? `${n.type}: ${n.shape}` : n.type;
  const acc = encodeURIComponent(JSON.stringify(n.accessor));
  return `<div class="lee-vrow" data-name="${esc(n.name)}" data-acc="${acc}" data-container="${n.is_container ? 1 : 0}"
            data-grid="${n.is_grid ? 1 : 0}" onclick="leeVarClick(this)">` +
    `<span class="lee-vname">${esc(n.name)}</span> <span class="lee-vtype">{${esc(typ)}}</span> ` +
    `<span class="lee-vval">${esc(n.value)}</span>${n.is_grid ?
      ' <button class="lee-vgrid" title="open grid" onclick="event.stopPropagation(); selectVar(this.closest(\'.lee-vrow\')); openGrid()">▦</button>' : ''}${tag}</div>` +
    `<div class="lee-vkids" id="k-${acc}"></div>`;
}

async function fillKids(acc) {
  const box = document.getElementById('k-' + acc);
  if (!box) { lee.varOpen.delete(acc); return; }   // the variable is gone; stop tracking it
  try {
    const accessor = JSON.parse(decodeURIComponent(acc));
    const kids = accessor[0] === 'debug'
      ? (await api(`/nb/debug/variables?reference=${Number(accessor[1])}`)).variables.map(debugVar)
      : await api(`/vars/expand?accessor=${acc}&scope=${lee.execScope}`);
    box.innerHTML = kids.map(k => varRow(k, 1)).join('');
  } catch (e) { lee.varOpen.delete(acc); box.innerHTML = `<div class="lee-err">${esc(e.message)}</div>`; }
}

function selectVar(el) {
  $$('.lee-vrow').forEach(r => r.classList.remove('sel'));
  el?.classList.add('sel');
}
window.selectVar = selectVar;

async function leeVarClick(el) {
  selectVar(el);
  if (el.dataset.container !== '1') return;
  const acc = el.dataset.acc;
  const box = document.getElementById('k-' + acc);
  if (!box) return;
  if (lee.varOpen.has(acc)) { lee.varOpen.delete(acc); box.innerHTML = ''; return; }
  lee.varOpen.add(acc);
  await fillKids(acc);
}
window.leeVarClick = leeVarClick;

function leeFilterVars() {
  const raw = $('#varfilter')?.value || '', q = raw.toLowerCase();
  const expression = raw.trimStart().startsWith('=');
  $$('#vars .lee-vrow').forEach(r => {
    r.style.display = (expression || !q || (r.dataset.name || '').toLowerCase().includes(q)) ? '' : 'none';
  });
  $('#varfilter')?.classList.toggle('expression', expression);
}
async function leeEvalVarFilter(event) {
  if (event.key !== 'Enter') return;
  const input = event.currentTarget, raw = input.value.trim();
  if (!raw.startsWith('=')) return;
  event.preventDefault(); event.stopPropagation();
  const code = raw.slice(1).trim(); if (!code) return status('enter Python after =', 'err');
  input.disabled = true; status('evaluating variable expression…');
  try {
    const r = await post('/vars/eval', {code, scope: lee.execScope});
    if (!r.ok) return status(r.error || 'expression failed', 'err');
    if (r.stdout) status(r.stdout.trim(), 'info');
    if (!r.result) return status('expression returned no value', 'info');
    openValueLens(r.result, input, code); status('expression ready', 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
  finally { input.disabled = false; input.focus(); }
}
window.leeFilterVars = leeFilterVars; window.leeEvalVarFilter = leeEvalVarFilter;

function setProfile(p) { const s = $('#varprofile'); if (s) { s.value = p; leeVars(); } }
const selVar = () => $('.lee-vrow.sel');

async function editSelectedVar() {
  const r = selVar(); if (!r) return status('select a variable first');
  const expr = await inputDialog('set variable', `${r.dataset.name} =`, '', 'Python expression');
  if (expr == null) return;
  const res = await post('/vars/set', {accessor: decodeURIComponent(r.dataset.acc), expr});
  res.ok ? (status('set ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}

async function openGrid() {
  const row = selVar();
  if (!row) return status('select a variable first', 'err');
  if (row.dataset.grid !== '1') return status(row.dataset.name + ' is not a table or array', 'err');
  let roff = 0, coff = 0, page = null;
  const m = modal(`<div class="lee-mhead">${esc(row.dataset.name)}<span class="sub">grid view</span></div>
    <div class="lee-gridwrap" id="gridbody"></div>
    <div class="lee-mfoot"><button class="lee-btn" id="gprevrow">↑ rows</button>
    <button class="lee-btn" id="gnextrow">↓ rows</button><button class="lee-btn" id="gprevcol">← columns</button>
    <button class="lee-btn" id="gnextcol">→ columns</button><span class="lee-dim" id="gridpos"></span></div>`);
  const draw = async () => {
    page = await api(`/vars/grid?accessor=${row.dataset.acc}&roff=${roff}&coff=${coff}&scope=${lee.execScope}`);
    if (!page) { m.remove(); return status('that value cannot be shown as a grid', 'err'); }
    const heads = page.headers.map(h => `<th>${esc(h)}</th>`).join('');
    const rows = page.cells.map((cells, i) => `<tr><th>${esc(page.index[i])}</th>` +
      cells.map(c => `<td>${esc(c)}</td>`).join('') + '</tr>').join('');
    m.querySelector('#gridbody').innerHTML = `<table class="lee-grid"><thead><tr><th></th>${heads}</tr></thead><tbody>${rows}</tbody></table>`;
    m.querySelector('#gridpos').textContent = `rows ${page.roff + 1}–${Math.min(page.roff + page.rows, page.nrows)} of ${page.nrows} · columns ${page.coff + 1}–${Math.min(page.coff + page.cols, page.ncols)} of ${page.ncols}`;
  };
  m.querySelector('#gprevrow').onclick = () => { roff = Math.max(0, roff - (page?.rows || 50)); draw(); };
  m.querySelector('#gnextrow').onclick = () => { roff = Math.min(Math.max(0, (page?.nrows || 1) - 1), roff + (page?.rows || 50)); draw(); };
  m.querySelector('#gprevcol').onclick = () => { coff = Math.max(0, coff - (page?.cols || 50)); draw(); };
  m.querySelector('#gnextcol').onclick = () => { coff = Math.min(Math.max(0, (page?.ncols || 1) - 1), coff + (page?.cols || 50)); draw(); };
  try { await draw(); } catch (e) { m.remove(); status(String(e.message || e), 'err'); }
}
async function promoteVar() {
  const r = selVar(); if (!r) return status('select a variable first');
  const res = await api('/vars/promote?accessor=' + r.dataset.acc);
  res.ok ? (status('promoted ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}
function copyVar(what) {
  const r = selVar(); if (!r) return status('select a variable first');
  const txt = what === 'path' ? decodeURIComponent(r.dataset.acc) : r.querySelector('.lee-vval').textContent;
  navigator.clipboard?.writeText(txt);
  status('copied ' + what, 'ok');
}

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
  host.innerHTML = active + [...lee.agentAttachments.entries()].map(([path, name]) =>
    `<span class="lee-agent-attachment" title="${esc(path)}"><span>${esc(name)}</span>` +
    `<button type="button" data-path="${esc(path)}" aria-label="remove ${esc(name)}">remove</button></span>`).join('') + states;
  $$('.lee-agent-state-suggestion', host).forEach(b => b.onclick = async () => {
    await post('/agent/state/load', {id: b.dataset.stateId, layer: 'task'});
    lee.stateSuggestions = []; paintAgentAttachments(); status('relevant state attached to this workspace', 'ok');
  });
  $$('button', host).forEach(b => b.onclick = () => { lee.agentAttachments.delete(b.dataset.path); paintAgentAttachments(); });
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
    lee.agentAttachments.set(item.path, item.name);
    const at = input.selectionStart, left = input.value.slice(0, at).replace(/(^|\s)@[^\s@]*$/, '$1');
    input.value = left + input.value.slice(at); input.selectionStart = input.selectionEnd = left.length;
    paintAgentAttachments();
  }
  closeAgentSuggest(); input.focus();
}
let agentSuggestSeq = 0, stateSuggestTimer = null;
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
    const d = await api('/fs/find?scope=project&q=' + encodeURIComponent(mention[1]) + '&limit=12');
    if (seq !== agentSuggestSeq) return;
    lee.agentSuggest = (d.hits || []).slice(0, 12).map(f => ({kind: 'file', path: f.path, name: f.name,
      label: '@' + f.name, detail: compactPath(f.path)}));
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
    grow(); updateAgentSuggest().catch(e => status(String(e.message || e), 'err'));
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
  const attachments = [...lee.agentAttachments.keys()]; lee.agentAttachments.clear(); paintAgentAttachments();
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

/* ------------------------------------------------------------------ terminal */
let termBundle = null;
function loadTermBundle() {
  if (window.LeeTerm) return Promise.resolve();
  if (termBundle) return termBundle;
  termBundle = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = $('#termwrap')?.dataset.termSrc || '/leestatic/lee-term.js';
    script.onload = resolve; script.onerror = () => reject(new Error('terminal bundle failed to load'));
    document.head.appendChild(script);
  });
  return termBundle;
}
// Multiple xterm instances keep their websocket/pty alive while hidden. The 285kb bundle
// still loads only on the first terminal action, never during ordinary notebook startup.
// `taken` is the set of ids the *server* is holding. A pty deliberately outlives its websocket
// so that reloading the page can reattach to it -- but this counter restarts at zero on reload,
// so it handed out `term-1` again, `terms.open` found a live pty under that key and returned it,
// and a brand new terminal came up showing an old session's scrollback with its process still
// running in it. Both halves of that are the same bug.
function nextTermId(kind, taken = []) {
  if (kind === 'git') return 'git';
  const used = new Set([...lee.terms.keys(), ...taken]);
  do { lee.termSeq += 1; } while (used.has('term-' + lee.termSeq));
  return 'term-' + lee.termSeq;
}
function termLabel(kind, id) { return kind === 'git' ? 'lazygit' : kind === 'release' ? 'release pipeline' : kind === 'deploy' ? 'deploy' : kind === 'drive' ? 'drive' : kind === 'gh-auth' ? 'gh auth' : `terminal ${id.split('-').pop()}`; }
function paintTermTabs() {
  const bar = $('#termtabs'); if (!bar) return;
  /* The close control belongs to the tab, not to the header. One × over there always shut
     the *active* terminal, so closing a background one meant selecting it first, and which
     tab it would close was never visible from the tab itself. */
  bar.innerHTML = [...lee.terms.entries()].map(([id, t]) =>
    `<span role="tab" aria-selected="${id === lee.activeTerm}" class="lee-termtab${id === lee.activeTerm ? ' active' : ''}" ` +
    `data-term="${esc(id)}" title="${esc(t.cwd || '')}"><button class="lee-termtab-name" data-term-pick="${esc(id)}">${esc(t.label)}</button>` +
    `<button class="lee-termtab-x" data-term-close="${esc(id)}" title="Close ${esc(t.label)}" aria-label="Close ${esc(t.label)}">×</button></span>`).join('');
  bar.querySelectorAll('[data-term-pick]').forEach(b => b.onclick = () => switchTerm(b.dataset.termPick));
  bar.querySelectorAll('[data-term-close]').forEach(b => b.onclick = e => {
    e.stopPropagation();            // closing a tab must not also select it
    closeTerm(b.dataset.termClose);
  });
  $('#termempty')?.toggleAttribute('hidden', lee.terms.size > 0);
}
function leeLeft(which = 'files') {
  const left = $('#left'); if (!left) return;
  leePane('left', true);
  left.classList.toggle('left-files', which === 'files');
  left.classList.toggle('left-symbols', which === 'symbols');
  left.classList.toggle('left-git', which === 'git');
  left.classList.toggle('left-workflows', which === 'workflows');
  left.classList.toggle('left-releases', which === 'releases');
  left.classList.toggle('left-deploys', which === 'deploys');
  left.classList.toggle('left-drive', which === 'drive');
  $$('.lee-activity-btn', left).forEach(b => {
    const active = b.dataset.left === which; b.classList.toggle('active', active);
    b.setAttribute('aria-pressed', String(active));
  });
  localStorage.setItem('lee-left-view', which);
  if (which === 'git') { setScope('files'); renderGitPanel(); }
  else if (which === 'workflows') { setScope('files'); leeWorkflows(); }
  else if (which === 'releases') { setScope('files'); leeReleases(); }
  else if (which === 'deploys') { setScope('files'); leeDeploys(); }
  else if (which === 'drive') { setScope('files'); leeDrive(); }
  else if (which === 'symbols') { setScope('files'); leeSymbols(); }
  else { setScope('files'); requestAnimationFrame(() => $('#filetree')?.focus()); }
}
window.leeLeft = leeLeft;
function leePane(which, show = null) {
  const shell = $('#shell'); if (!shell) return;
  const cls = which === 'left' ? 'no-left' : which === 'right' ? 'no-right' : 'no-bottom';
  const hidden = show === null ? !shell.classList.contains(cls) : !show;
  shell.classList.toggle(cls, hidden);
  if (matchMedia('(max-width: 1100px)').matches && which !== 'bottom') {
    shell.classList.toggle('mobile-' + which, !hidden);
    if (!hidden) {
      const other = which === 'left' ? 'right' : 'left';
      shell.classList.remove('mobile-' + other);
      shell.classList.add(other === 'left' ? 'no-left' : 'no-right');
    }
  }
  localStorage.setItem('lee-pane-' + which, hidden ? 'hidden' : 'shown');
  if (!hidden && which === 'bottom') requestAnimationFrame(() => lee.term?.refit());
}
window.leePane = leePane;
/* ------------------------------------------------------------------ logs

   The detail a status line cannot hold. Git's refusals are the motivating case: the useful
   part of "cannot switch branch" is the list of files it would overwrite, and a toast shows
   one clipped sentence of it. Runs are the other: `/dev/log` has always kept what a dev
   server prints, and nothing in the browser read it.

   Kept in memory for this session on purpose. This answers "what just happened", and a store
   that outlives the question would need retention rules to go with it. */
const LOG_MAX = 500;
lee.logs = [];

function leeLog(source, title, detail = '', kind = '') {
  lee.logs.push({at: new Date(), source, title: String(title || ''), detail: String(detail || ''), kind});
  if (lee.logs.length > LOG_MAX) lee.logs.splice(0, lee.logs.length - LOG_MAX);
  const dock = $('#bottomdock');
  if (dock?.classList.contains('dock-logs')) renderLogs();
  else if (kind === 'err') $$('.lee-docktab').forEach(b => {
    if (b.dataset.dock === 'logs') b.classList.add('has-error');   // a failure you have not read
  });
}
window.leeLog = leeLog;

function renderLogs() {
  const el = $('#loglist'); if (!el) return;
  const want = lee.logFilter || '';
  const rows = lee.logs.filter(r => !want || r.source === want);
  el.innerHTML = rows.length ? rows.map(r =>
    `<article class="lee-logrow${r.kind ? ' ' + r.kind : ''}">` +
    `<div class="lee-loghead"><time>${r.at.toTimeString().slice(0, 8)}</time>` +
    `<span class="lee-logsource">${esc(r.source)}</span><strong>${esc(r.title)}</strong></div>` +
    (r.detail ? `<pre class="lee-logdetail">${esc(r.detail)}</pre>` : '') + `</article>`).join('')
    : `<div class="lee-dim lee-logempty">nothing logged${want ? ' for ' + esc(want) : ''} yet</div>`;
  el.scrollTop = el.scrollHeight;
}

/* "See logs" has to end with you seeing the log.

   The reason a failure writes a detail line at all is that the toast cannot hold it -- so
   sending the reader off to find it, through a dock that is showing something else and a
   filter they set an hour ago for something unrelated, loses the very thing that was worth
   keeping. A failure now opens the log it just wrote, on a filter that can show it. */
function showLog(source = '') {
  if (lee.logFilter && lee.logFilter !== source) leeLogFilter('');
  leeDock('logs');
}
// The first line of git's refusal is usually the whole story ("would be overwritten by
// checkout"), and the files it names are the part that needs the pane.
function firstLine(text, max = 96) {
  const line = String(text || '').replace(/^\w*Error:\s*/, '').split('\n').find(x => x.trim()) || '';
  return line.length > max ? line.slice(0, max - 1) + '…' : line;
}

function leeLogFilter(which) {
  lee.logFilter = which || '';
  $$('.lee-logfilter').forEach(b => b.classList.toggle('active', (b.dataset.logFilter || '') === lee.logFilter));
  renderLogs();
}
function leeLogClear() { lee.logs = []; renderLogs(); }
async function leeLogCopy() {
  const want = lee.logFilter || '';
  const text = lee.logs.filter(r => !want || r.source === want)
    .map(r => `${r.at.toTimeString().slice(0, 8)} ${r.source} ${r.title}` + (r.detail ? '\n' + r.detail : '')).join('\n');
  try { await navigator.clipboard.writeText(text); status('log copied', 'ok'); }
  catch (e) { status('could not copy the log', 'err'); }
}
window.leeLogFilter = leeLogFilter; window.leeLogClear = leeLogClear; window.leeLogCopy = leeLogCopy;

/* Dev servers already keep what they print; `/dev/log` has served it all along with nothing
   reading it. Tailed only while the pane is open -- an app's output is worth watching when you
   are looking at it, and not worth a request every five seconds when you are not. */
lee.runSeen = new Map();
async function pollRunLogs() {
  const dock = $('#bottomdock');
  if (!dock?.classList.contains('dock-logs')) return;
  if (lee.logFilter && lee.logFilter !== 'runs') return;
  let servers = [];
  try { servers = (await api('/dev/list')).servers || []; } catch (_) { return; }
  for (const srv of servers) {
    const path = srv.path || srv.script || '';
    if (!path) continue;
    let lines = [];
    try { lines = (await api('/dev/log?n=200&path=' + encodeURIComponent(path))).log || []; }
    catch (_) { continue; }
    const seen = lee.runSeen.get(path) || 0;
    if (lines.length <= seen) { if (lines.length < seen) lee.runSeen.set(path, lines.length); continue; }
    const fresh = lines.slice(seen);
    lee.runSeen.set(path, lines.length);
    leeLog('runs', srv.name || path.split('/').pop(), fresh.join('\n'), srv.alive === false ? 'err' : '');
  }
}

function leeDock(which) {
  const dock = $('#bottomdock'); if (!dock) return;
  leePane('bottom', true);
  const centre = $('.lee-centre');
  dock.classList.toggle('dock-exec', which === 'exec');
  dock.classList.toggle('dock-term', which === 'term');
  dock.classList.toggle('dock-logs', which === 'logs');
  if (which === 'logs') {
    $$('.lee-docktab').forEach(b => { if (b.dataset.dock === 'logs') b.classList.remove('has-error'); });
    renderLogs();
  }
  $$('.lee-docktab', dock).forEach(b => {
    const active = b.dataset.dock === which; b.classList.toggle('active', active);
    b.setAttribute('aria-selected', String(active));
  });
  if (which === 'term') requestAnimationFrame(() => lee.term?.refit());
}
window.leeDock = leeDock;
function switchTerm(id) {
  const t = lee.terms.get(id); if (!t) return;
  leeDock('term'); lee.activeTerm = id; lee.term = t.view;
  $$('.lee-term-session').forEach(x => x.hidden = x.dataset.term !== id);
  paintTermTabs(); $('#shell').classList.add('show-term'); setScope('term');
  requestAnimationFrame(() => { t.view.refit(); t.view.focus(); });
}
function cycleTerm(d) {
  const ids = [...lee.terms.keys()]; if (!ids.length) return;
  const at = Math.max(0, ids.indexOf(lee.activeTerm));
  switchTerm(ids[(at + d + ids.length) % ids.length]);
}
async function openTerm(kind = 'shell', forceNew = false) {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  if (kind === 'git' && !d.lazygit) return status(d.lazygit_why, 'err');
  const external = $('#termexternal');
  if (external) external.hidden = !(d.external || []).length;
  const live = (d.open || []).filter(t => t.alive).map(t => t.id).filter(Boolean);
  if (!forceNew) {
    const existing = [...lee.terms.entries()].find(([, t]) => t.kind === kind);
    if (existing) return switchTerm(existing[0]);
    // A session this page has never seen, still running from before a reload. Reattaching is
    // the point of letting a pty outlive its socket -- and it has to be *visible* to be
    // closable, or its process is orphaned where nobody can see it to stop it.
    const orphan = live.find(id => !lee.terms.has(id) && (kind === 'git' ? id === 'git'
                                                                        : id.startsWith('term-')));
    if (orphan) return adoptTerm(orphan, kind, d);
  }
  const id = nextTermId(kind, live);
  if (lee.terms.has(id)) return switchTerm(id);
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id), cwd: d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
// The pipeline's pty is opened by the pipeline, not by whoever attaches, so this
// terminal talks to `/release/ws` instead of `/term/ws`. Everything else -- the theme, the
// keyboard, the dock tab -- is the same component the shell uses. `cwd` carries the project
// root, which is the only thing that socket needs to know which pipeline is being watched.
async function openReleaseTerm(root = '', kind = 'release') {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  const id = kind, prior = lee.terms.get(id);
  if (prior && !prior.exited) return switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id), cwd: root || d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: root || d.cwd, kind, id,
    url: kind === 'drive' ? '/drive/ws' : '/pipeline/ws',
    onStatus: m => status(`${termLabel(kind, id)}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
// Reconnect to a pty that is already running, rather than starting one. Same component and the
// same id, so the server hands back the session it still has -- which is what makes the process
// inside it visible in a tab, and therefore closable.
function adoptTerm(id, kind, d) {
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id), cwd: d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
  status(`${record.label} was still running — reattached`);
}

// xterm.js cannot be attached to a terminal application that is already running: that program is
// itself an emulator with its own pty, and a browser pane has no way to adopt its window. What it
// can do is hand the project over, which is what this is -- and the button stays hidden unless
// the server found a terminal to hand it to, so it is never one that fails when pressed.
async function leeExternalTerm() {
  try {
    const d = await post('/term/external');
    status(`opened ${(d.argv || []).includes('-a') ? d.argv[d.argv.indexOf('-a') + 1] : (d.argv || [])[0] || 'terminal'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeExternalTerm = leeExternalTerm;

function leeNewTerm() { return openTerm('shell', true); }
window.leeNewTerm = leeNewTerm;

// The IDE follows the system's light/dark setting through a media query; the terminal
// reads its colours from CSS once, when it is created, so it has to be told.
try {
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    for (const t of lee.terms.values()) t.view.retheme();
  });
} catch (e) {}

function leeTermExpand() {
  const centre = $('.lee-centre'); if (!centre) return;
  leeDock('term');
  centre.classList.toggle('term-expanded');
  const expanded = centre.classList.contains('term-expanded');
  $('#termexpand').textContent = expanded ? 'restore' : 'expand';
  requestAnimationFrame(() => { lee.term?.refit(); lee.term?.focus(); });
}
window.leeTermExpand = leeTermExpand;

function closeTerm(id = lee.activeTerm) {
  const t = lee.terms.get(id); if (!t) return;
  t.view.dispose(); t.host.remove(); lee.terms.delete(id); post('/term/close?id=' + encodeURIComponent(id));
  const next = [...lee.terms.keys()].at(-1);
  lee.term = null; lee.activeTerm = '';
  if (next) switchTerm(next);
  else {
    paintTermTabs(); $('#shell').classList.remove('show-term'); leeDock('exec');
    $('.lee-centre')?.classList.remove('term-expanded'); setScope('editor');
  }
  // A shell or lazygit may have changed the working tree under us.
  refreshFileTree(undefined, false).catch(e => status(String(e.message || e), 'err'));
}

/* ---------------------------------------------------------- web preferences */
/* Themes are families with a dark and a light variant: `data-theme` is the family,
   `data-mode` the resolved variant. Each entry's swatch colours are [bg, bg1, accent],
   read from the same palette its CSS block declares, so the picker cannot drift from it. */
const THEMES = {
  leela: {blurb: 'the house palette', dark: ['#0d1117', '#161b22', '#58a6ff'], light: ['#ffffff', '#f6f8fa', '#0969da']},
  cursor: {blurb: 'thin quiet chrome', dark: ['#141414', '#1a1a1a', '#6a9fff'], light: ['#fbfbfb', '#f4f4f4', '#171717']},
  vscode: {blurb: 'Dark+ / Light+', dark: ['#1e1e1e', '#252526', '#3794ff'], light: ['#ffffff', '#f3f3f3', '#005fb8']},
  jetbrains: {blurb: 'Darcula / IntelliJ', dark: ['#2b2b2b', '#313335', '#589df6'], light: ['#ffffff', '#f7f8fa', '#2470b3']},
  solarized: {blurb: 'Ethan Schoonover', dark: ['#002b36', '#073642', '#268bd2'], light: ['#fdf6e3', '#f5eeda', '#268bd2']},
  gruvbox: {blurb: 'warm retro groove', dark: ['#282828', '#32302f', '#83a598'], light: ['#fbf1c7', '#f2e5bc', '#076678']},
  nord: {blurb: 'arctic bluish', dark: ['#2e3440', '#333b48', '#88c0d0'], light: ['#eceff4', '#e5e9f0', '#5e81ac']},
  dracula: {blurb: 'the famous fangs', dark: ['#282a36', '#21222c', '#bd93f9'], light: ['#faf9f2', '#f2f1e8', '#7b48c8']},
};
const THEME_MODES = ['system', 'dark', 'light'];
// Density is its own axis: the tight chrome started as cursor's look, but wanting it with
// another family's colours is reasonable, so it is stored and chosen separately.
const THEME_DENSITIES = ['tight', 'relaxed'];
const THEME_DEFAULT = 'cursor:light:tight';
// What `lee-theme` held before families existed. Dropping these would silently reset everyone.
const THEME_LEGACY = {system: 'leela:system:relaxed', dark: 'leela:dark:relaxed',
                      light: 'leela:light:relaxed', cursor: 'cursor:light:tight'};
const darkQuery = () => matchMedia('(prefers-color-scheme: dark)');

function parseTheme(theme) {
  "A stored value, a `family:mode:density` string or a {family, mode, density} object, validated."
  if (theme && typeof theme === 'object') theme = `${theme.family}:${theme.mode}:${theme.density}`;
  const [family, mode, density] = String(theme || '').includes(':') ? String(theme).split(':')
    : (THEME_LEGACY[theme] || THEME_DEFAULT).split(':');
  return {family: family in THEMES ? family : 'cursor',
          mode: THEME_MODES.includes(mode) ? mode : 'light',
          // A two-field value predates the split, when density was whatever the family implied.
          density: THEME_DENSITIES.includes(density) ? density : family === 'cursor' ? 'tight' : 'relaxed'};
}
const readTheme = () => parseTheme(localStorage.getItem('lee-theme'));
const themeMode = mode => mode === 'system' ? (darkQuery().matches ? 'dark' : 'light') : mode;

function paintTheme() {
  "Write the family, the resolved mode and the density onto <html>, and retheme what CSS cannot reach."
  const {family, mode, density} = lee.theme, resolved = themeMode(mode), root = document.documentElement;
  root.dataset.theme = family; root.dataset.mode = resolved; root.dataset.density = density;
  // color-scheme only accepts dark/light; a family name here is ignored and native controls stay wrong.
  root.style.colorScheme = resolved;
  const pill = $('#themepill'); if (pill) pill.textContent = mode === 'system' ? `${family} · auto` : `${family} · ${mode}`;
  for (const t of lee.terms.values()) t.view.retheme();
}
function applyTheme(theme) {
  lee.theme = parseTheme(theme);
  const {family, mode, density} = lee.theme;
  localStorage.setItem('lee-theme', `${family}:${mode}:${density}`);
  paintTheme();
}
// Following the system means following it now, not at the next reload.
darkQuery().addEventListener('change', () => { if (lee.theme?.mode === 'system') paintTheme(); });
async function editorSettings(languageScope = null) {
  if(typeof languageScope!=='string'){
    // Default to All languages, never to the focused tab's language. Deriving it from
    // curLang() silently scoped every save into `languages.<lang>`, and since saving also
    // remembers the choice, one visit with a .py file focused sent all later edits there
    // too. The values were written correctly and then read back through a scope the editor
    // only uses for matching tabs, so global preferences looked like they reverted on
    // every restart. A language scope is now only ever chosen explicitly.
    const remembered=localStorage.getItem('lee-settings-language-scope');
    languageScope=remembered!==null?remembered:'';
  }
  const rememberedScope=localStorage.getItem('lee-settings-save-scope')||'user';
  await loadSettings(languageScope);
  const original = {...lee.editorPrefs}, originalFiles = {...lee.filePrefs},
        originalWorkbench = {...lee.workbenchPrefs}, originalDebug = {...lee.debugPrefs},
        originalTheme = readTheme();
  let saved = false, previewView = null;
  const selected = (value, current) => value === current ? ' selected' : '';
  const checked = (section, key) => (section === 'editor' ? lee.editorPrefs : section === 'files' ? lee.filePrefs :
    section === 'workbench' ? lee.workbenchPrefs : lee.debugPrefs)[key] ? ' checked' : '';
  const fontSelect = CODE_FONTS.map(([name, detail]) =>
    `<option value="${esc(name)}"${selected(name, lee.editorPrefs.fontFamily)}>${esc(name)} — ${esc(detail)}</option>`).join('');
  const field = (section, key, label, input, help='') => `<label>${label}${input.replace('data-setting', `data-pref-section="${section}" data-pref="${key}"`)}${help ? `<small>${help}</small>` : ''}</label>`;
  const check = (section, key, label, help='') => `<label class="lee-settings-toggle"><input type="checkbox" data-pref-section="${section}" data-pref="${key}"${checked(section,key)}><span>${label}${help ? `<small>${help}</small>` : ''}</span></label>`;
  const select = (section, key, label, values, help='') => field(section,key,label,
    `<select class="lee-select" data-setting>${values.map(([value,text]) => `<option value="${value}"${selected(value,(section==='editor'?lee.editorPrefs:section==='files'?lee.filePrefs:section==='workbench'?lee.workbenchPrefs:lee.debugPrefs)[key])}>${text}</option>`).join('')}</select>`,help);
  const swatch = (family, mode) => {
    const [bg, bg1, accent] = THEMES[family][themeMode(mode)];
    return `background: linear-gradient(135deg, ${bg} 0 42%, ${bg1} 42% 62%, ${accent} 62%)`;
  };
  const themeButtons = mode => Object.entries(THEMES).map(([family, {blurb}]) =>
    `<button class="lee-theme-choice${family === originalTheme.family ? ' active' : ''}" data-theme="${family}" aria-pressed="${family === originalTheme.family}">` +
    `<span class="lee-theme-swatch" style="${swatch(family, mode)}"></span><strong>${family}</strong><span>${esc(blurb)}</span></button>`).join('');
  const modeButtons = mode => THEME_MODES.map(m =>
    `<button class="lee-theme-mode${m === mode ? ' active' : ''}" data-theme-mode="${m}" aria-pressed="${m === mode}">${m === 'system' ? 'follow system' : m}</button>`).join('');
  const densityButtons = density => THEME_DENSITIES.map(d =>
    `<button class="lee-theme-mode${d === density ? ' active' : ''}" data-theme-density="${d}" aria-pressed="${d === density}">${d}</button>`).join('');
  const m = modal(`<div class="lee-mhead">settings<span class="sub">user · workspace · language-aware</span></div>` +
    `<div class="lee-settings-scope"><label>Save to <select class="lee-select" data-settings-scope><option value="user"${selected('user',rememberedScope)}>User</option><option value="workspace"${selected('workspace',rememberedScope)}>Workspace</option></select></label>` +
    `<label>Apply to <select class="lee-select" data-settings-language><option value=""${selected('',languageScope)}>All languages</option><option value="python"${selected('python',languageScope)}>Python</option><option value="markdown"${selected('markdown',languageScope)}>Markdown</option></select></label>` +
    `<span data-settings-target></span><span data-settings-path>${esc(lee.settingsMeta?.paths?.user || '')}</span></div>` +
    `<div class="lee-settings-layout"><nav class="lee-settings-nav" aria-label="Settings sections">` +
    `<button class="active" data-settings-page="editor">Text editor</button><button data-settings-page="appearance">Appearance</button>` +
    `<button data-settings-page="files">Files & save</button><button data-settings-page="debug">Run & debug</button>` +
    `<button data-settings-page="keys">Keybindings</button></nav><div class="lee-settings-content">` +
    `<section data-settings-section="editor"><div class="lee-settings-title"><span>Text editor</span><kbd>${esc(displayChord(lee.keys.find(k=>k.action==='settings')?.key||'mod+,'))}</kbd></div>` +
    `<p>Editing behavior updates live. Portable values are saved as JSON, not trapped in this browser.</p>` +
    `<div class="lee-settings-group"><h4>Typography</h4><div class="lee-settings-grid">` +
    `<label class="wide">Code font<select class="lee-select" data-pref-section="editor" data-pref="fontFamily">${fontSelect}</select><small>JetBrains Mono and Fira Code are bundled for reliable offline rendering.</small></label>` +
    field('editor','fontSize','Size',`<input class="lee-input" data-setting type="number" min="9" max="28" value="${lee.editorPrefs.fontSize}">`) +
    field('editor','lineHeight','Line height',`<input class="lee-input" data-setting type="number" min="1" max="2.4" step="0.1" value="${lee.editorPrefs.lineHeight}">`) +
    field('editor','tabSize','Tab size',`<input class="lee-input" data-setting type="number" min="1" max="8" value="${lee.editorPrefs.tabSize}">`) + `</div>` +
    `<div class="lee-ligature-proof"><span>Ligature proof</span><code>!=  ->  =>  <=  >=  ===  ::</code></div></div>` +
    `<div class="lee-settings-group"><h4>Wrapping and line length</h4><div class="lee-settings-grid lee-settings-line-grid">` +
    select('editor','wordWrap','Word wrap',[['off','Off'],['viewport','At viewport'],['column','At preferred column']]) +
    field('editor','lineLength','Preferred column',`<input class="lee-input" data-setting type="number" min="40" max="240" value="${lee.editorPrefs.lineLength}">`) +
    `<label class="wide">Additional guides<input class="lee-input" data-pref-section="editor" data-pref="guideColumns" value="${esc(lee.editorPrefs.guideColumns)}" placeholder="88, 120"><small>Comma-separated; preferred column remains the primary guide.</small></label></div></div>` +
    `<div class="lee-settings-checks">${check('editor','visualGuides','Visual column guides')}${check('editor','ligatures','Programming ligatures','Visible with the proof row above.')}` +
    `${check('editor','useTabs','Indent with tabs')}${check('editor','detectIndentation','Detect existing indentation')}${check('editor','activeLine','Highlight active line')}` +
    `${check('editor','bracketMatching','Match brackets')}${check('editor','closeBrackets','Auto-close brackets and quotes')}${check('editor','folding','Code folding')}` +
    `${check('editor','stickyNavigation','Sticky Python symbol')}${check('editor','scrollPastEnd','Scroll past end')}${check('editor','smoothScrolling','Smooth scrolling')}</div>` +
    `<div class="lee-settings-preview" id="settingspreview"></div><div class="lee-setting-row"><span><strong>Python language service</strong><small>Pyright diagnostics and code intelligence</small></span><span class="lee-setting-state" data-lsp-state>checking…</span></div></section>` +
    `<section data-settings-section="appearance" hidden><h3>Appearance</h3><p>Reduce navigation friction without crowding the editor.</p>` +
    `<div class="lee-theme-modes" role="group" aria-label="Theme variant">Variant ${modeButtons(originalTheme.mode)}` +
    `<span class="lee-spacer"></span>Layout ${densityButtons(originalTheme.density)}<small>tight thins the chrome; it is independent of the palette</small></div>` +
    `<div class="lee-theme-options" role="group" aria-label="Theme family">${themeButtons(originalTheme.mode)}</div>` +
    `<div class="lee-settings-group"><h4>Editor chrome</h4><div class="lee-settings-grid">` +
    select('editor','lineNumbers','Line numbers',[['off','Off'],['absolute','Absolute'],['relative','Relative'],['hybrid','Hybrid']]) +
    select('editor','renderWhitespace','Whitespace',[['none','None'],['selection','Selection'],['trailing','Trailing'],['all','All']]) +
    select('editor','cursorStyle','Caret',[['line','Line'],['block','Block'],['underline','Underline']]) +
    select('editor','cursorBlinking','Blinking',[['off','Off'],['blink','Blink'],['smooth','Smooth']]) +
    select('editor','overviewMode','Overview stripe',[['off','Off'],['long','Long files only'],['always','Always']], 'The scrollbar, marked up: a tick for each problem and a bar for each uncommitted line. Long-file mode keeps it out of notebook cells.') +
    field('editor','overviewThreshold','Long file threshold',`<input class="lee-input" data-setting type="number" min="20" max="5000" value="${lee.editorPrefs.overviewThreshold}">`) + `</div>` +
    `<div class="lee-settings-checks">${check('editor','indentGuides','Indent guides')}${check('editor','methodSeparators','Function separators')}${check('editor','bracketColors','Bracket-pair colors')}${check('editor','highlightSelection','Highlight selected occurrences')}</div></div>` +
    `<div class="lee-settings-group"><h4>Navigation</h4><div class="lee-settings-grid">` +
    select('workbench','breadcrumbs','Breadcrumbs',[['off','Off'],['path','File path'],['symbols','Symbols'],['pathAndSymbols','Path and symbols']]) +
    `</div><div class="lee-settings-checks">${check('editor','inlayHints','Inferred type and parameter hints from Pyright')}${check('workbench','dependencyHints','Dependency version hints')}</div></div></section>` +
    `<section data-settings-section="files" hidden><h3>Files & save</h3><p>Recovery is always enabled; choose when durable disk writes happen.</p><div class="lee-settings-group"><div class="lee-settings-grid">` +
    select('files','autoSave','Auto save',[['off','Off'],['afterDelay','After delay'],['onFocusChange','On editor focus change'],['onWindowChange','On window focus change']]) +
    field('files','autoSaveDelay','Delay (ms)',`<input class="lee-input" data-setting type="number" min="100" max="60000" value="${lee.filePrefs.autoSaveDelay||900}">`) + `</div>` +
    `<div class="lee-settings-checks">${check('files','trimTrailingWhitespace','Trim trailing whitespace')}${check('files','trimFinalNewlines','Remove final blank lines')}${check('files','insertFinalNewline','Ensure final newline')}${check('files','formatOnSave','Format on save')}${check('files','confirmDelete','Confirm destructive deletes')}</div></div>` +
    `<div class="lee-setting-row"><span><strong>Crash recovery</strong><small>Unsaved drafts stay in IndexedDB and external writes require review.</small></span><span class="lee-setting-state">always on</span></div></section>` +
    `<section data-settings-section="debug" hidden><h3>Run & debug</h3><p>Defaults for notebook DAP and direct debugpy sessions.</p><div class="lee-settings-checks">` +
    `${check('debug','justMyCode','Just my code')}${check('debug','stopOnEntry','Stop on entry')}${check('debug','subProcess','Debug subprocesses')}${check('debug','showInlineValues','Inline paused values')}${check('debug','breakOnRaised','Break on raised exceptions')}${check('debug','breakOnUncaught','Break on uncaught exceptions')}</div>` +
    `<div class="lee-setting-row"><span><strong>debugpy</strong><small>Python files, modules, tests, applications, and attach sessions use the selected project interpreter.</small></span><button class="lee-btn" data-open-runs>Run configurations…</button></div></section>` +
    `<section data-settings-section="keys" hidden><h3>Keybindings</h3><p>Every command can be rebound from the same single-source keymap.</p><button class="lee-btn" data-open-keys>Edit keybindings…</button></section>` +
    `</div></div><div class="lee-mfoot"><button class="lee-btn" data-reset>Reset this section</button><span class="lee-spacer"></span><button class="lee-btn" data-cancel>Cancel</button><button class="lee-btn go" data-save>Save settings</button></div>`,
    null,()=>{if(previewView)LeeCM.destroy(previewView);if(!saved){applyEditorPrefs(original);lee.filePrefs=originalFiles;lee.workbenchPrefs=originalWorkbench;lee.debugPrefs=originalDebug;applyTheme(originalTheme);}},
    {className:'lee-settings-modal',storageKey:'settings'});
  api('/lsp/status').then(d=>{const el=$('[data-lsp-state]',m);if(el){el.textContent=d.available?(d.alive?'connected':'available'):'optional';el.title=d.note||'';}}).catch(()=>{});
  await document.fonts.ready;
  previewView=createEditor($('#settingspreview',m),{doc:'# Programming ligatures and line guides\nfrom pathlib import Path\n\ndef compare(left: int, right: int) -> bool:\n    return left != right and left <= 100  # => result\n',lang:'python',lineNums:true});
  const sections={editor:lee.editorPrefs,files:lee.filePrefs,workbench:lee.workbenchPrefs,debug:lee.debugPrefs};
  const initialSections=Object.fromEntries(Object.entries(sections).map(([name,values])=>[name,{...values}]));
  const update=()=>{$$('[data-pref]',m).forEach(input=>{const target=sections[input.dataset.prefSection];target[input.dataset.pref]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;});applyEditorPrefs(sections.editor);LeeCM.configure(previewView,sections.editor);};
  $$('[data-pref]',m).forEach(input=>input.addEventListener('input',update));
  let page='editor';
  $$('[data-settings-page]',m).forEach(button=>button.onclick=()=>{page=button.dataset.settingsPage;$$('[data-settings-page]',m).forEach(x=>x.classList.toggle('active',x===button));$$('[data-settings-section]',m).forEach(x=>x.hidden=x.dataset.settingsSection!==page);});
  const scope=$('[data-settings-scope]',m),language=$('[data-settings-language]',m),path=$('[data-settings-path]',m),target=$('[data-settings-target]',m);
  const paintPath=()=>{path.textContent=lee.settingsMeta?.paths?.[scope.value]||'';target.textContent=`${scope.value} · ${language.value||'all languages'}`;};
  scope.onchange=()=>{localStorage.setItem('lee-settings-save-scope',scope.value);paintPath();};paintPath();
  language.onchange=()=>{localStorage.setItem('lee-settings-language-scope',language.value);saved=true;m.remove();editorSettings(language.value);};
  // Every click previews live; the modal's close handler puts the original back unless saved.
  const paintPicker=()=>{const {family,mode}=lee.theme;
    $$('[data-theme]',m).forEach(b=>{const on=b.dataset.theme===family;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);
      $('.lee-theme-swatch',b).style.cssText=swatch(b.dataset.theme,mode);});
    $$('[data-theme-mode]',m).forEach(b=>{const on=b.dataset.themeMode===mode;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});
    $$('[data-theme-density]',m).forEach(b=>{const on=b.dataset.themeDensity===lee.theme.density;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});};
  $$('[data-theme]',m).forEach(b=>b.onclick=()=>{applyTheme({...lee.theme,family:b.dataset.theme});paintPicker();});
  $$('[data-theme-mode]',m).forEach(b=>b.onclick=()=>{applyTheme({...lee.theme,mode:b.dataset.themeMode});paintPicker();});
  $$('[data-theme-density]',m).forEach(b=>b.onclick=()=>{applyTheme({...lee.theme,density:b.dataset.themeDensity});paintPicker();});
  $('[data-reset]',m).onclick=async()=>{const section=page==='appearance'?'editor':page; if(!sections[section])return;await post('/settings/reset',{scope:scope.value,section,language:language.value});saved=true;m.remove();applyEditorPrefs(EDITOR_DEFAULTS);setTimeout(editorSettings,0);};
  $('[data-cancel]',m).onclick=()=>m.remove();
  $('[data-save]',m).onclick=async()=>{update();let count=0;for(const [section,values] of Object.entries(sections)){const changed=Object.fromEntries(Object.entries(values).filter(([key,value])=>value!==initialSections[section][key]));if(Object.keys(changed).length){await post('/settings/save',{scope:scope.value,language:language.value,section,values:changed});count+=Object.keys(changed).length;}}localStorage.setItem('lee-settings-save-scope',scope.value);localStorage.setItem('lee-settings-language-scope',language.value);localStorage.removeItem('lee-editor-settings');await loadSettings(language.value);saved=true;m.remove();status(`${count||'no'} setting${count===1?'':'s'} saved to ${scope.value} · ${language.value||'all languages'} (${lee.settingsMeta?.paths?.[scope.value]||''})`,'ok');};
  $('[data-open-keys]',m).onclick=()=>{saved=true;m.remove();editKeys();};
  $('[data-open-runs]',m).onclick=()=>{saved=true;m.remove();editRuns();};
}
function leeTheme() { editorSettings(); }
window.leeTheme = leeTheme; window.leeEditorSettings = editorSettings;

/* ---------------------------------------------------------- cwd and source control */
function paintGitTree(d) {
  $$('.lee-file').forEach(row => {
    row.classList.remove('git-modified', 'git-staged', 'git-untracked', 'git-conflict');
    row.querySelectorAll('.lee-tree-git').forEach(badge => badge.remove());
  });
  for (const c of (d.changes || [])) {
    const path = d.root + '/' + c.path;
    const row = $$('.lee-file').find(x => x.dataset.path === path); if (!row) continue;
    const state = c.conflicted ? 'conflict' : c.untracked ? 'untracked' : c.staged && !c.unstaged ? 'staged' : 'modified';
    row.classList.add('git-' + state);
    const badge = document.createElement('span'); badge.className = 'lee-tree-git'; badge.textContent = state[0].toUpperCase();
    row.appendChild(badge);
  }
}
async function refreshOpenGitMarks() {
  if (lee.kind === 'notebook') return paintNotebookGitMarks();
  if (lee.kind !== 'text' || !lee.path) return;
  try {
    lee.fileGit = await api('/git/file?path=' + encodeURIComponent(lee.path));
    const view = lee.editors.get('file'); if (view) LeeCM.setChangedLines(view, lee.fileGit.ranges || []);
  } catch (_) {}
}
// The same mark a file gets, at the unit a notebook has. Line numbers cannot say anything
// useful about an .ipynb -- it is JSON, and editing one cell moves every line below it -- so
// the server answers per cell id and the whole cell carries the bar.
async function paintNotebookGitMarks() {
  if (lee.kind !== 'notebook' || !lee.path) return;
  try { lee.notebookGit = await api('/git/notebook?path=' + encodeURIComponent(lee.path)); }
  catch (_) { return; }
  repaintNotebookGitMarks();
}
function repaintNotebookGitMarks() {
  const cells = lee.notebookGit?.cells || {}, lines = lee.notebookGit?.lines || {};
  $$('.lee-cell').forEach(el => {
    const kind = cells[el.dataset.id] || '';
    el.classList.toggle('changed', !!kind);
    el.classList.toggle('changed-added', kind === 'added');
    // The bar on the cell says *that* it differs; the lines inside say where. A mounted
    // editor is told directly -- `mountCell` only reads these once, when it is created.
    const view = lee.editors.get(el.dataset.id);
    if (view) LeeCM.setChangedLines(view, lines[el.dataset.id] || []);
  });
  paintNotebookOverview();
}

/* The notebook's overview stripe.

   A file gets one from CodeMirror, because a file *is* the editor and the editor owns the
   scrollbar. A notebook scrolls as a page of cells, so its scrollbar belongs to `#editor`
   and nothing inside any one cell can mark it -- which left the per-cell change marks
   invisible until you had already scrolled to them, and knowing where the changes are
   without scrolling is the entire point of an overview.

   Same rules as the editor's: it stands where the scrollbar was, it maps the whole document
   onto its height, and it is never a second thing to scroll. */
const NB_OVERVIEW_W = 14;
function nbOverview() {
  const stage = $('#editorstage'); if (!stage) return null;
  let c = $('#nboverview');
  if (!c) {
    c = document.createElement('canvas'); c.id = 'nboverview'; c.className = 'lee-nb-overview';
    c.setAttribute('aria-label', 'notebook overview: uncommitted cells and failures');
    const seek = e => {
      const host = $('#editor'); if (!host) return;
      const box = c.getBoundingClientRect();
      const at = Math.max(0, Math.min(1, (e.clientY - box.top) / (box.height || 1)));
      host.scrollTop = Math.max(0, at * host.scrollHeight - host.clientHeight / 2);
    };
    c.addEventListener('pointerdown', e => { c.setPointerCapture(e.pointerId); e.preventDefault(); seek(e); });
    c.addEventListener('pointermove', e => { if (e.buttons & 1) { e.preventDefault(); seek(e); } });
    stage.appendChild(c);
  }
  return c;
}
function paintNotebookOverview() {
  const host = $('#editor'), stage = $('#editorstage'), c = nbOverview();
  if (!c || !host || !stage) return;
  // Nothing to overview when the whole notebook already fits: the stripe would be a bar
  // saying "you can see all of this", and it would take the scrollbar away to say it.
  const on = lee.kind === 'notebook' && host.scrollHeight > host.clientHeight + 4;
  c.hidden = !on; host.classList.toggle('has-overview', on);
  if (!on) return;
  const stageBox = stage.getBoundingClientRect(), box = host.getBoundingClientRect();
  // Measured rather than pinned to the stage, so a split editor puts it on the notebook's
  // own right edge instead of the pane beside it.
  c.style.left = (box.right - stageBox.left - NB_OVERVIEW_W) + 'px';
  c.style.top = (box.top - stageBox.top) + 'px';
  const dpr = devicePixelRatio || 1, w = NB_OVERVIEW_W, h = Math.max(40, host.clientHeight);
  c.width = w * dpr; c.height = h * dpr; c.style.width = w + 'px'; c.style.height = h + 'px';
  const ctx = c.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const colour = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const total = host.scrollHeight || 1, changed = lee.notebookGit?.cells || {};
  const y = px => px / total * h;
  for (const el of $$('.lee-cell', host)) {
    const top = y(el.getBoundingClientRect().top - box.top + host.scrollTop);
    const tall = Math.max(2, y(el.offsetHeight));
    const kind = changed[el.dataset.id];
    if (kind) {
      ctx.fillStyle = kind === 'added' ? colour('--lee-green', '#3fb950') : colour('--lee-orange', '#d29922');
      ctx.fillRect(0, top, 2, tall);
    }
    // A failed run is the other thing worth seeing from the top of a long notebook.
    if ($('.lee-cell-state.error', el)) {
      ctx.fillStyle = colour('--lee-red', '#f85149');
      ctx.fillRect(3, Math.min(h - 2, top), w - 5, 2);
    }
  }
  ctx.fillStyle = colour('--lee-fg4', '#6e7681'); ctx.globalAlpha = .28;
  ctx.fillRect(0, y(host.scrollTop), w, Math.max(6, y(host.clientHeight)));
  ctx.globalAlpha = 1;
}
let nbOverviewFrame = 0;
function queueNotebookOverview() {
  cancelAnimationFrame(nbOverviewFrame);
  nbOverviewFrame = requestAnimationFrame(paintNotebookOverview);
}
document.addEventListener('scroll', e => {
  if (e.target?.id === 'editor') queueNotebookOverview();
}, true);
addEventListener('resize', queueNotebookOverview);
/* Everything downstream of a branch, without a page refresh.

   The pill and the tree badges were repainted by this poll; nothing else was. So a checkout
   -- from the panel, from lazygit in the terminal, or from the agent -- left the editor's
   change marks describing the branch you came from, the History and Branches lists showing
   what they showed before, and the release panel counting against the old tag.

   `head` is in the signature because a commit is the case the others miss: branch, counts
   and file list all read the same afterwards, and the only thing that moved is the sha. */
function gitSignature(d) {
  /* Each changed file's own state, not merely how many there are. The count is the same before
     and after almost every edit a person actually makes -- typing in a file that was already
     modified moves no count, so the signature did not move and the panel went on showing the
     stats it drew when the file first changed. That is the "source control does not refresh until
     I refresh it" report: the poll was running the whole time and finding nothing to say.

     The staged/worktree status codes and the line counts are what actually differ, so they are
     what goes in. Cheap: `/git/info` already returns all of it on every poll, so this reads a
     payload that was being fetched and thrown away. */
  const changes = (d.changes || []).map(c =>
    [c.path, c.index, c.worktree,
     (c.staged_stat || {}).additions, (c.staged_stat || {}).deletions,
     (c.unstaged_stat || {}).additions, (c.unstaged_stat || {}).deletions].join(':')).join(',');
  return [d.root, d.branch, d.head, d.upstream, d.ahead, d.behind, changes,
          (d.stashes || []).length, (d.operation || {}).active || ''].join('|');
}
function noticeGitState(d) {
  const sig = gitSignature(d), had = lee.gitSignature;
  lee.gitSignature = sig;
  if (had && had !== sig) gitChanged();     // `had` empty on the first poll: nothing has moved yet
}
function gitChanged() {
  refreshOpenGitMarks();                    // the file's lines, or the notebook's cells
  const left = $('#left');
  if (left?.classList.contains('left-git')) {
    // The snapshot and the loaded history are both about the commit we were on.
    gitUI.snapshot = null; gitUI.history = [];
    renderGitPanel();
  }
  // A release is measured from the last tag on this branch, and a deploy from what is
  // committed, so both are answers about the branch rather than about the panel.
  if (left?.classList.contains('left-releases')) leeReleases();
  if (left?.classList.contains('left-deploys')) leeDeploys();
}
window.leeGitChanged = gitChanged;

// Choosing another folder is a bigger change than a commit, and needs its own refresh.
// `gitChanged` reloads what depends on the *branch*; this reloads what depends on which
// project it is at all -- so drive and workflows are here and not there, because a commit does
// not change where a project deploys to or which workflows it has, and a different project
// certainly does. Without this, the open panel kept describing the folder left behind, which
// looked exactly like the backend still being pinned to the first repository.
function projectChanged() {
  // Every cached answer describes the folder we just left, whether or not its panel is on
  // screen. They all go: otherwise opening one of these panels a minute later shows the old
  // project's state, which is the same bug arriving later and harder to explain.
  gitUI.snapshot = null; gitUI.history = [];
  relUI.data = drvUI.data = null;
  Object.assign(wfUI, {data: null, runs: null, env: null, catalogue: null, docker: null});
  Object.assign(depUI, {data: null, infra: null, stack: null, records: null});
  gitChanged();
  const left = $('#left');
  if (left?.classList.contains('left-drive')) leeDrive();
  if (left?.classList.contains('left-workflows')) leeWorkflows();
}

// Which repository a panel request is about lives in `gitUI.repo`, and `gitUrl` puts it on the
// query. These two only ask whether Source Control is on screen, and repaint it if it is.
function scmPanelOpen() { return !!$('#left')?.classList.contains('left-git'); }
function refreshScmIfOpen(snapshot = null) {
  if (!scmPanelOpen()) return;
  if (snapshot) renderGitPanel(snapshot);
  else leeGitRefresh();
}

async function refreshProjectPills() {
  try {
    const d = await api('/workspace/info');
    const active = (d.roots || []).find(r => r.path === (gitUI.repo || d.active)) || (d.roots || [])[0];
    const name = $('#workspacename'); if (name) name.textContent = active?.name || 'open workspace';
    const workspace = $('#workspacepill'); if (workspace) workspace.title = active?.path || 'open workspace';
  } catch (_) {}
  try {
    const d = await api('/cwd');
    const cwd = $('#cwdpill');
    if (cwd) { cwd.textContent = (d.explicit ? 'cwd ' : 'cwd auto ') + (d.cwd.split('/').pop() || d.cwd);
               cwd.title = d.cwd || 'choose a working directory'; }
  } catch (_) {}
  try {
    // Bare, not `gitUrl`: the pill and the tree badges describe the repository the active tab
    // is in, so a panel pinned elsewhere must not repaint them.
    const d = await api('/git/info');
    const git = $('#gitpill'); if (!git) return;
    const n = (d.changes || []).length;
    git.textContent = `${d.branch}${n ? ' · ' + n : ''}`;
    git.className = 'lee-branch-switcher ' + (n ? 'lee-pill-warn' : 'lee-pill-on');
    git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ''}${d.ahead ? ' · ahead ' + d.ahead : ''}${d.behind ? ' · behind ' + d.behind : ''}`;
    paintGitTree(d);
    noticeGitState(d);
  } catch (_) {
    const git = $('#gitpill'); if (git) { git.textContent = 'no git'; git.className = 'lee-branch-switcher'; }
  }
}

async function leeCwd() {
  const d = await api('/cwd');
  const value = await inputDialog('script working directory', 'Directory inside an open folder', d.cwd,
                                  'Leave empty to use the Git repository root');
  if (value === null) return;
  const r = await post('/cwd/set', {path: value});
  status(`${r.explicit ? 'working directory' : 'automatic repository root'}: ${r.cwd}`, 'ok');
  refreshProjectPills();
  // A new working directory can imply a different repository, so an open panel is stale.
  refreshScmIfOpen();
}
window.leeCwd = leeCwd;

function gitPatchHtml(text) {
  if (!text) return '<div class="lee-git-empty-state"><strong>No patch yet</strong><span>Stage an untracked file to create its first patch.</span></div>';
  return String(text).split('\n').map(line => {
    const kind = line.startsWith('@@') ? 'hunk' : line.startsWith('+') && !line.startsWith('+++') ? 'add' :
                 line.startsWith('-') && !line.startsWith('---') ? 'del' : line.startsWith('diff ') || line.startsWith('index ') ? 'meta' : '';
    return `<div class="lee-patch-line ${kind}">${esc(line) || ' '}</div>`;
  }).join('');
}
function gitPatchParts(text) {
  const lines = String(text || '').split('\n'), first = lines.findIndex(x => x.startsWith('@@'));
  if (first < 0) return {header: text, hunks: []};
  const header = lines.slice(0, first).join('\n') + '\n', hunks = [];
  let current = [];
  for (const line of lines.slice(first)) {
    if (line.startsWith('@@') && current.length) { hunks.push(current.join('\n') + '\n'); current = []; }
    current.push(line);
  }
  if (current.length) hunks.push(current.join('\n') + '\n');
  return {header, hunks};
}
function showGitFileDiff(path, patch = '', line = 0, rawPatch = '', notebook = false, options = {}) {
  const name = String(path || '').split('/').pop(), parts = gitPatchParts(rawPatch || patch);
  const canPartial = !notebook && parts.hunks.length > 0 && options.group;
  const controls = canPartial ? `<button class="lee-btn" id="githunks">select hunks</button>` : '';
  const m = modal(`<div class="lee-mhead">${esc(name)}<span class="sub">${options.label || 'working tree against HEAD'}${line ? ' · line ' + line : ''}</span>` +
    `<span class="lee-spacer"></span>${notebook ? '<button class="lee-btn active" id="gitcontent">cell content</button><button class="lee-btn" id="gitraw">raw notebook</button>' : ''}` +
    `${controls}<button class="lee-btn" id="gitexpand">expand</button></div>` +
    `<div class="lee-git-patch">${gitPatchHtml(patch)}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gitopenfile">open file</button><span class="lee-dim">Unified patch · additions and removals retain Git semantics.</span></div>`);
  m.querySelector('#gitopenfile').onclick = () => { m.remove(); leeOpenFile(path); };
  const repaint = (text, active) => {
    m.querySelector('.lee-git-patch').innerHTML = gitPatchHtml(text);
    for (const id of ['gitcontent', 'gitraw']) m.querySelector('#' + id)?.classList.toggle('active', id === active);
  };
  m.querySelector('#gitcontent')?.addEventListener('click', () => repaint(patch, 'gitcontent'));
  m.querySelector('#gitraw')?.addEventListener('click', () => repaint(rawPatch, 'gitraw'));
  m.querySelector('#githunks')?.addEventListener('click', () => {
    const body = m.querySelector('.lee-git-patch');
    body.innerHTML = parts.hunks.map((h, i) => `<label class="lee-git-hunk"><input type="checkbox" data-hunk="${i}" checked><span>hunk ${i + 1}</span>${gitPatchHtml(h)}</label>`).join('');
    const foot = m.querySelector('.lee-mfoot');
    foot.innerHTML = `<button class="lee-btn go" id="gitapplyhunks">${options.group === 'staged' ? 'unstage' : 'stage'} selected hunks</button><span class="lee-dim">Only checked hunks will move between the index and working tree.</span>`;
    foot.querySelector('#gitapplyhunks').onclick = async () => {
      const selected = [...body.querySelectorAll('[data-hunk]:checked')].map(x => parts.hunks[+x.dataset.hunk]);
      if (!selected.length) return status('select at least one hunk', 'err');
      try {
        const d = await gitDo('apply_patch', {patch: parts.header + selected.join(''), staged: true, reverse: options.group === 'staged'});
        m.remove(); renderGitPanel(d);
      } catch (e) { status(e.message || String(e), 'err'); }
    };
  });
  m.querySelector('#gitexpand').onclick = e => {
    const expanded = m.classList.toggle('lee-git-diff-expanded');
    e.target.textContent = expanded ? 'restore' : 'expand';
  };
}

/* ---------------------------------------------------------------- change gutter popup
 * PyCharm's gutter, which is the one people mean: the mark thickens under the pointer, and
 * clicking it shows what the line used to say next to the four things you want at that moment --
 * step to the next change, put this one back, copy the old text, or commit only this.
 *
 * The hunks come from /git/file, where they are cut out of a three-context diff so that each one
 * is a patch Git can place by its own context. The browser never assembles a patch of its own:
 * a hand-built hunk with the wrong line numbers is applied silently in the wrong place, and this
 * surface's whole job is to change one change and nothing else.
 */
const fileHunks = () => lee.fileGit?.hunks || [];

function hunkAtLine(line) {
  const hunks = fileHunks();
  const inside = hunks.findIndex(h => line >= h.from && line <= h.to);
  if (inside >= 0) return inside;
  // Three context lines can merge two changes into one hunk, so a mark drawn from the exact
  // zero-context ranges can sit just outside the span of the hunk that carries it. The nearest
  // change is then the right answer, and is certainly better than the click doing nothing.
  let best = -1, gap = Infinity;
  hunks.forEach((h, i) => {
    const d = Math.min(Math.abs(line - h.from), Math.abs(line - h.to));
    if (d < gap) { gap = d; best = i; }
  });
  return best;
}

/* Which words of the old line the new one no longer has. PyCharm boxes them, and it is the
 * difference between reading "the line changed" and seeing what changed in it. A plain LCS over
 * words is enough at one line's length, and costs nothing at it. */
function tokenDiffHtml(before, after) {
  const a = String(before ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  const b = String(after ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  if (!a.length) return '';
  if (!b.length) return `<mark>${esc(before)}</mark>`;
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let out = '', run = '', i = 0, j = 0;
  const flush = () => { if (run) out += `<mark>${esc(run)}</mark>`; run = ''; };
  while (i < n) {
    if (j < m && a[i] === b[j]) { flush(); out += esc(a[i]); i++; j++; }
    else if (j < m && dp[i + 1][j] < dp[i][j + 1]) j++;
    else run += a[i++];
  }
  flush();
  return out;
}

function closeChangePopup() {
  const pop = $('.lee-change-pop');
  if (!pop) return;
  pop._leeOff?.(); pop.remove();
}

/* The mark widens only while the pointer is actually on it. 12px is the editor bundle's own
 * click target for a change mark; if this number and that one disagreed, the gutter would
 * advertise an affordance it does not answer. */
function armChangeGutter(host) {
  if (!host || host._leeGutterArmed) return;
  host._leeGutterArmed = true;
  let hot = null;
  const cool = () => { hot?.classList.remove('lee-change-hot'); hot = null; };
  host.addEventListener('mousemove', e => {
    const line = e.target.closest?.('.cm-lee-change');
    if (!line || e.clientX > line.getBoundingClientRect().left + 12) return cool();
    if (line === hot) return;
    cool(); hot = line; line.classList.add('lee-change-hot');
  });
  host.addEventListener('mouseleave', cool);
}

function changePopupBody(h) {
  if (!h.old) return '<div class="lee-change-new">These lines are new — there is no committed version of them.</div>';
  const old = h.old.replace(/\n$/, '').split('\n'), now = (h.new || '').replace(/\n$/, '').split('\n');
  return `<pre class="lee-change-old">${old.map((l, k) => tokenDiffHtml(l, now[k])).join('\n')}</pre>`;
}

function showChangePopup(path, line) {
  closeChangePopup();
  const hunks = fileHunks(), at = hunkAtLine(line);
  // An untracked file has no committed version of anything, so there is nothing for this popup
  // to show; the whole-file diff is the honest answer there.
  if (at < 0) return showGitFileDiff(path, lee.fileGit?.diff || '', line);
  const h = hunks[at], name = String(path || '').split('/').pop();
  const pop = document.createElement('div');
  pop.className = 'lee-change-pop'; pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', `change ${at + 1} of ${hunks.length} in ${name}, line ${h.from}`);
  pop.innerHTML =
    `<div class="lee-change-tools">` +
    `<button class="lee-change-icon" data-act="prev" title="previous change" aria-label="previous change">↑</button>` +
    `<button class="lee-change-icon" data-act="next" title="next change" aria-label="next change">↓</button>` +
    `<button class="lee-change-icon" data-act="revert" title="revert this change" aria-label="revert this change">⟲</button>` +
    `<button class="lee-change-icon" data-act="diff" title="show this file's whole diff" aria-label="show diff">◫</button>` +
    `<button class="lee-change-icon" data-act="copy" title="copy the previous version" aria-label="copy the previous version">⧉</button>` +
    `<span class="lee-change-count">${at + 1} / ${hunks.length}</span>` +
    `<input class="lee-input lee-change-msg" placeholder="Commit this change" aria-label="commit message for this change">` +
    `<button class="lee-btn go" data-act="commit">commit</button></div>` + changePopupBody(h);
  document.body.appendChild(pop);
  const anchor = $(`#filecm .cm-lee-change[data-change-line="${h.from}"]`) ||
                 $(`#filecm .cm-lee-change[data-change-line="${line}"]`) || $('#filecm');
  const rect = anchor.getBoundingClientRect(), size = pop.getBoundingClientRect();
  pop.style.left = Math.max(4, Math.min(rect.left, innerWidth - size.width - 4)) + 'px';
  pop.style.top = Math.max(4, Math.min(rect.bottom + 4, innerHeight - size.height - 4)) + 'px';

  const away = e => { if (!pop.contains(e.target)) closeChangePopup(); };
  const key = e => { if (e.key === 'Escape') { e.stopPropagation(); closeChangePopup(); } };
  // Deferred by a tick: the click that opened this popup is still on its way up.
  setTimeout(() => document.addEventListener('mousedown', away), 0);
  document.addEventListener('keydown', key, true);
  pop._leeOff = () => {
    document.removeEventListener('mousedown', away);
    document.removeEventListener('keydown', key, true);
  };

  pop.addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    if (act === 'prev' || act === 'next') {
      const next = hunks[(at + (act === 'next' ? 1 : hunks.length - 1)) % hunks.length];
      jumpToLine(next.from);
      // The line has to be laid out before it can be measured, and the editor only renders the
      // lines it has scrolled to.
      return requestAnimationFrame(() => showChangePopup(path, next.from));
    }
    if (act === 'diff') { closeChangePopup(); return showGitFileDiff(path, lee.fileGit?.diff || '', h.from); }
    if (act === 'copy') return copyChangeHunk(h);
    if (act === 'revert') return revertChangeHunk(path, h);
    if (act === 'commit') return commitChangeHunk(path, h, pop.querySelector('.lee-change-msg').value);
  });
  return pop;
}

async function copyChangeHunk(h) {
  try { await navigator.clipboard.writeText(h.old || h.new || ''); status('previous version copied', 'ok'); }
  catch (_) { status('clipboard access failed', 'err'); }
}

/* Git reads and writes the file on disk, and this editor may be holding a newer version of it.
 * Both directions of that are silent data loss -- the revert overwrites the unsaved edit, or the
 * next autosave writes the reverted lines back -- so the file is saved first and the buffer is
 * reloaded after, rather than either being guessed at. */
async function refreshFileChanges(path, fromDisk = false) {
  const v = lee.editors.get('file');
  if (!v) return;
  if (fromDisk) {
    const st = await api('/tab/state?path=' + encodeURIComponent(path)).catch(() => null);
    if (typeof st?.text === 'string') {
      lee.dirtyBuffers.delete(path); lee.buffers.delete(path);
      if (st.text !== LeeCM.getDoc(v)) LeeCM.setDoc(v, st.text);
      $$('.lee-tab').find(x => x.title === path)?.classList.remove('dirty');
    }
  }
  const git = await api('/git/file?path=' + encodeURIComponent(path)).catch(() => null);
  if (!git) return;
  lee.fileGit = git; LeeCM.setChangedLines(v, git.ranges || []);
}

async function revertChangeHunk(path, h) {
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  const ok = await confirmDialog('Revert this change?',
    `Lines ${h.from}–${h.to} of ${String(path).split('/').pop()} go back to their committed ` +
    `version. Every other change in the file is left alone.`, 'revert');
  if (!ok) return;
  closeChangePopup();
  // reverse against the working tree, not the index: this is an edit to the file, and the
  // index is not involved in it at all.
  try { await gitDo('apply_patch', {patch: h.patch, staged: false, reverse: true}); }
  catch (_) { return; }
  await refreshFileChanges(path, true);
}

async function commitChangeHunk(path, h, message) {
  const text = String(message || '').trim();
  if (!text) return status('write a message to commit this change', 'err');
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  /* PyCharm commits the one change and nothing else. Git can only commit what is in the index, so
   * this stages the hunk and commits -- which means anything already staged rides along. Rather
   * than quietly widening a one-hunk commit, or quietly unstaging work someone deliberately
   * staged, the choice is put to whoever is looking at it. */
  const snapshot = gitUI.snapshot || await api('/git/info').catch(() => null);
  const staged = (snapshot?.changes || []).filter(c => c.staged && c.path !== path).map(c => c.path);
  if (staged.length) {
    const shown = staged.slice(0, 3).join(', ') + (staged.length > 3 ? `, and ${staged.length - 3} more` : '');
    const ok = await confirmDialog('Something else is already staged',
      `${shown} ${staged.length === 1 ? 'is' : 'are'} staged and would be committed together with ` +
      `this change. Unstage first to commit this change on its own.`, 'commit anyway');
    if (!ok) return;
  }
  closeChangePopup();
  try {
    await gitDo('apply_patch', {patch: h.patch, staged: true, reverse: false});
    await gitDo('commit', {message: text});
  } catch (_) { return; }
  await refreshFileChanges(path);
}

function gitChangeRow(c, group) {
  const state = c.conflicted ? 'conflict' : c.untracked ? 'new file' : group === 'staged' ? 'will commit' : 'not staged';
  const selected = gitUI.selectedChanges.has(`${group}:${c.path}`);
  const list = gitUI.changeLists[c.path], stat = group === 'staged' ? c.staged_stat : c.unstaged_stat;
  return `<article class="lee-git-change ${group}${selected ? ' selected' : ''}" data-path="${esc(c.path)}" data-group="${group}">` +
    `<input type="checkbox" data-select-change aria-label="Select ${esc(c.path)}" ${selected ? 'checked' : ''}>` +
    `<button class="lee-git-file" title="review diff"><span class="lee-git-status">${esc(group === 'staged' ? c.index : c.worktree)}</span><span>${esc(c.path)}</span></button>` +
    `${list ? `<i class="lee-git-changelist">${esc(list)}</i>` : ''}${stat ? `<small class="lee-git-line-stat">${stat.binary ? 'binary' : `+${stat.additions} −${stat.deletions}`}</small>` : ''}` +
    `<span class="sub">${state}</span><span class="lee-spacer"></span>${c.conflicted ? '<button class="lee-btn warn" data-resolve>resolve</button>' : '<button class="lee-btn" data-blame title="file history and blame">blame</button>'}` +
    `<button class="lee-btn" data-open title="open file">open</button>` +
    `${group === 'unstaged' ? '<button class="lee-btn" data-git="stage">stage</button>' : '<button class="lee-btn" data-git="unstage">unstage</button>'}` +
    `${group === 'unstaged' && !c.untracked ? '<button class="lee-btn warn" data-git="discard">discard</button>' : ''}</article>`;
}
function gitRelative(stamp) {
  if (!stamp) return 'date unavailable';
  const seconds = Math.max(0, Date.now() / 1000 - stamp), units = [[31536000, 'y'], [2592000, 'mo'], [604800, 'w'], [86400, 'd'], [3600, 'h'], [60, 'm']];
  for (const [size, label] of units) if (seconds >= size) return `${Math.floor(seconds / size)}${label} ago`;
  return 'just now';
}
function gitFreshness(stamp) { return stamp ? `fetched ${gitRelative(stamp)}` : 'remote refs have not been fetched'; }
let savedGitLists = {}, savedGitReviews = {}, savedGitNotes = {};
try { savedGitLists = JSON.parse(localStorage.getItem('lee-git-changelists') || '{}'); } catch (_) {}
try { savedGitReviews = JSON.parse(localStorage.getItem('lee-git-reviews') || '{}'); } catch (_) {}
try { savedGitNotes = JSON.parse(localStorage.getItem('lee-git-review-notes') || '{}'); } catch (_) {}
const gitUI = {tab: 'changes', snapshot: null, repo: '', repos: null, reposResults: [], expect: '', history: [], historyQuery: '', branchQuery: '', branchScope: 'all', compareFrom: '', compareTo: '', reviewBase: '', reviewHead: '', reviewMode: 'review', review: null, reviewFile: '', reviewPatch: '', selectedCommit: null, selectedChanges: new Set(), changeLists: savedGitLists, reviewed: savedGitReviews, reviewNotes: savedGitNotes, busy: ''};
// Which repository a panel request is about. Empty means the one the active tab lives in,
// which is what the branch pill, the file tree and the editor's change marks always mean.
function gitUrl(path, params = {}) {
  const q = new URLSearchParams(params);
  if (gitUI.repo) q.set('repo', gitUI.repo);
  const query = q.toString();
  return query ? `${path}?${query}` : path;
}
function gitRepoName(root) { return String(root || '').split('/').filter(Boolean).pop() || root; }
function saveGitWorkflowState() { localStorage.setItem('lee-git-changelists', JSON.stringify(gitUI.changeLists)); localStorage.setItem('lee-git-reviews', JSON.stringify(gitUI.reviewed)); localStorage.setItem('lee-git-review-notes', JSON.stringify(gitUI.reviewNotes)); }
function gitReviewKey(d, path) { return `${d.root || gitUI.snapshot?.root || ''}\0${d.base}\0${d.head}\0${d.mode}\0${path}`; }
function paintGitPill(d) {
  // The pill and the tree badges belong to the repository the active tab is in. A panel
  // pinned to another repository in the workspace must not repaint them from a snapshot
  // that is not theirs -- a clean pill over a dirty file tree is worse than no pill.
  if (gitUI.repo) return;
  const git = $('#gitpill'); if (!git || !d) return;
  const n = (d.changes || []).length;
  git.textContent = `${d.branch}${n ? ' · ' + n : ''}${d.ahead ? ' · ↑' + d.ahead : ''}${d.behind ? ' · ↓' + d.behind : ''}`;
  git.className = 'lee-branch-switcher ' + (n ? 'lee-pill-warn' : 'lee-pill-on');
  git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ' · no upstream'} · ${gitFreshness(d.fetched_at)}`;
  paintGitTree(d);
}
async function gitDo(op, extra = {}) {
  const started = performance.now(), name = op.replaceAll('_', ' ');
  gitUI.busy = op; status(`git ${name}…`);
  try {
    const d = await post('/git/action', {op, repo: gitUI.repo, ...extra});
    gitUI.snapshot = d; paintGitPill(d);
    // Immediately, rather than up to one poll later -- and the signature is cleared so the
    // poll that follows does not treat our own mutation as news and do it all again.
    lee.gitSignature = ''; gitChanged();
    // What the operation *left behind* beats how long it took. A squash that staged twelve
    // files and a merge that stopped at a conflict both "complete", and saying only that is
    // how an index full of someone else's changes came to look like a bug in Leela.
    // One call, not two: a second `status` replaces the first, and the note is the half that
    // must not be the one dropped.
    const said = d.outcome?.summary || `complete · ${Math.round(performance.now() - started)} ms`;
    status(`git ${name} · ${said}${d.outcome?.note ? ' — ' + d.outcome.note : ''}`,
           d.outcome?.note ? 'err' : 'ok');
    leeLog('git', `${name} · ${gitRepoName(gitUI.repo || d.root || '')}`,
           [extra.branch, extra.ref, extra.message].filter(Boolean).join(' ') || '', 'ok');
    return d;
  } catch (e) {
    /* Without this the status line kept saying "git checkout…" for ever. Git refusing a
       switch because local changes would be overwritten is a normal, fast answer, and it
       looked identical to a hang -- the one thing a progress message must never do.
       The message itself goes to the log: git's refusals are multi-line, and the list of
       files it would overwrite is the part worth reading. */
    const detail = e.message || String(e);
    leeLog('git', `${name} failed`, detail, 'err');
    showLog('git');
    status(`git ${name} failed — ${firstLine(detail)}`, 'err');
    throw e;
  } finally { gitUI.busy = ''; }
}
function gitOperationBanner(d) {
  const op = d.operation || {};
  if (!op.active) return '';
  return `<section class="lee-git-operation"><div><strong>${esc(op.active)} in progress</strong><span>Resolve the listed conflicts, then continue or abort.</span></div>` +
    `<span class="lee-spacer"></span><button data-conflict-center>resolve conflicts</button>${op.can_continue ? '<button data-operation="continue">continue</button>' : ''}${op.can_skip ? '<button data-operation="skip">skip</button>' : ''}` +
    `${op.can_abort ? '<button data-operation="abort" class="warn">abort</button>' : ''}</section>`;
}
// Why a file will not stay staged, said once, where the file list is. Git treats a filter it
// cannot run as nothing having gone wrong, so this is the only place the reason can come from.
function gitFilterBanner(d) {
  const f = d.filters || {};
  if (f.ok !== false || !f.explain) return '';
  return `<section class="lee-git-operation lee-git-filters"><div>` +
    `<strong>files here may not stay staged</strong><span>${esc(f.explain)}</span></div></section>`;
}

// The way back from the last thing that moved this branch. Offered whenever there is one,
// rather than only after a failure: "that merge was not what I wanted" arrives a minute later.
function gitUndoBanner(d) {
  const point = (d.safepoints || [])[0];
  if (!point) return '';
  return `<section class="lee-git-undo"><span>last: ${esc(point.describe)}</span>` +
    `<span class="lee-spacer"></span><button data-git-undo="${esc(point.token)}">undo</button></section>`;
}

function gitNav() {
  return `<nav class="lee-git-nav" aria-label="Source control views">${[['changes','Changes'],['review','Review'],['branches','Branches'],['history','History'],['resources','Repository'],['repos','All repos']].map(([id, label]) =>
    `<button data-git-tab="${id}" class="${gitUI.tab === id ? 'active' : ''}">${label}</button>`).join('')}</nav>`;
}
function gitSummary(d) {
  return `<header class="lee-sc-branch"><div><strong>${esc(d.branch)}</strong><span>${esc(d.upstream || 'unpublished branch')}</span></div>` +
    `<span class="lee-spacer"></span>${d.behind ? `<b>↓${d.behind}</b>` : ''}${d.ahead ? `<b>↑${d.ahead}</b>` : ''}` +
    `<small title="Remote-derived branch data may be stale">${esc(gitFreshness(d.fetched_at))}</small></header>`;
}
function gitChangesView(d) {
  const staged = (d.changes || []).filter(c => c.staged), unstaged = (d.changes || []).filter(c => c.unstaged);
  const allStats = [...staged.map(c => c.staged_stat), ...unstaged.map(c => c.unstaged_stat)].filter(Boolean);
  const additions = allStats.reduce((n, x) => n + (x.additions || 0), 0), deletions = allStats.reduce((n, x) => n + (x.deletions || 0), 0);
  const rows = (items, group) => items.length ? items.map(c => gitChangeRow(c, group)).join('') :
    `<div class="lee-git-empty-state"><strong>${group === 'staged' ? 'Nothing staged' : 'Working tree clean'}</strong><span>${group === 'staged' ? 'Stage files or individual hunks to prepare a commit.' : 'There are no local file changes.'}</span></div>`;
  return gitOperationBanner(d) + gitFilterBanner(d) + gitUndoBanner(d) + `<div class="lee-git-change-summary"><strong>${d.changes.length} changed file${d.changes.length === 1 ? '' : 's'}</strong><span>+${additions}</span><span>−${deletions}</span><small>${staged.length} staged · ${unstaged.length} unstaged</small></div>` + `<div class="lee-sc-actions"><button data-top="fetch">fetch</button><button data-top="pull">pull</button><button data-top="push">push</button>` +
    `${!d.upstream ? '<button data-top="publish">publish branch</button>' : ''}<button id="scstash">stash</button></div>` +
    `<div class="lee-git-selection" ${gitUI.selectedChanges.size ? '' : 'hidden'}><strong>${gitUI.selectedChanges.size} selected</strong><button data-selected-action="stage">stage</button><button data-selected-action="unstage">unstage</button><button data-selected-action="changelist">move to changelist</button><button data-selected-action="clear">clear</button></div>` +
    `<form id="sccommit" class="lee-sc-commit"><label>Commit message<textarea rows="3" placeholder="Describe this change" aria-label="Commit message"></textarea></label>` +
    `<label class="lee-git-check"><input type="checkbox" name="amend"> amend previous commit</label><button type="button" id="screviewstaged" ${staged.length ? '' : 'disabled'}>review staged</button><button ${staged.length ? '' : 'disabled'}>commit ${staged.length || ''}</button></form>` +
    `<details class="lee-sc-group" open><summary><span>Staged changes</span><b>${staged.length}</b>${staged.length ? '<button type="button" id="scunstageall">unstage all</button>' : ''}</summary><div>${rows(staged, 'staged')}</div></details>` +
    `<details class="lee-sc-group" open><summary><span>Changes</span><b>${unstaged.length}</b>${unstaged.length ? '<button type="button" id="scstageall">stage all</button>' : ''}</summary><div>${rows(unstaged, 'unstaged')}</div></details>` +
    `<details class="lee-sc-group"><summary><span>Stashes</span><b>${(d.stashes || []).length}</b></summary><div class="lee-sc-refs">` +
    `${(d.stashes || []).map(s => `<div class="lee-sc-ref" data-stash="${esc(s.ref)}"><span>${esc(s.ref)}</span><small>${esc(s.subject)} · ${gitRelative(s.timestamp)}</small><button data-apply>apply</button><button data-pop>pop</button><button data-drop>drop</button></div>`).join('') || '<div class="lee-dim lee-git-empty">No stashes</div>'}</div></details>`;
}
function gitBranchesView(d) {
  let branches = [...(d.branches || [])];
  const q = gitUI.branchQuery.toLowerCase();
  if (q) branches = branches.filter(b => `${b.name} ${b.subject} ${b.author}`.toLowerCase().includes(q));
  if (gitUI.branchScope === 'local') branches = branches.filter(b => !b.remote);
  if (gitUI.branchScope === 'remote') branches = branches.filter(b => b.remote);
  if (gitUI.branchScope === 'unmerged') branches = branches.filter(b => !b.merged);
  branches.sort((a, b) => b.timestamp - a.timestamp);
  return `<div class="lee-git-filter"><input id="gitbranchfilter" class="lee-input" value="${esc(gitUI.branchQuery)}" placeholder="Filter branches, commits, authors…">` +
    `<select id="gitbranchscope"><option value="all">all refs</option><option value="local">local</option><option value="remote">remote</option><option value="unmerged">unmerged</option></select><button id="scbranch">new branch</button></div>` +
    `<div class="lee-git-branch-list">${branches.map((b, index) => `<article class="lee-git-branch-row${b.current ? ' current' : ''}${b.latest ? ' latest' : ''}" data-branch="${esc(b.name)}">` +
      `<button data-switch ${b.current ? 'disabled' : ''} title="${b.remote ? 'create local tracking branch' : 'switch branch'}">${b.current ? '●' : '○'}</button><div class="lee-git-branch-copy"><strong>${esc(b.name)}</strong>` +
      `<span>${esc(b.subject || 'No commit subject')}</span><small>${esc(b.author)} · ${gitRelative(b.timestamp)} · ${esc(b.oid)}</small></div>` +
      `<div class="lee-git-badges">${index === 0 ? '<i>latest commit</i>' : ''}${b.default ? '<i>default</i>' : ''}${b.remote ? '<i>remote</i>' : ''}${b.merged ? '<i>merged</i>' : '<i>unmerged</i>'}${b.track ? `<i>${esc(b.track)}</i>` : ''}</div>` +
      `${b.current ? '<span></span>' : '<button data-compare title="Review changes proposed by this branch">review</button>'}${b.remote ? '<span></span>' : '<button data-more title="branch actions">•••</button>'}</article>`).join('') || '<div class="lee-git-empty-state"><strong>No matching branches</strong><span>Change the filter or fetch remote refs.</span></div>'}</div>` +
    `<details class="lee-sc-group"><summary><span>Tags</span><b>${(d.tags || []).length}</b><button id="sctag">new tag</button></summary><div class="lee-sc-meta">` +
    `${(d.tag_details || []).map(t => `<span class="lee-sc-tag" data-tag="${esc(t.name)}">${esc(t.name)} <small>${gitRelative(t.timestamp)}</small><button data-delete-tag>×</button></span>`).join('') || '<span>no tags</span>'}</div></details>`;
}
function gitReviewView(d) {
  if (!gitUI.reviewBase) gitUI.reviewBase = d.branch;
  if (!gitUI.reviewHead) gitUI.reviewHead = (d.branches || []).find(b => !b.current && !b.merged)?.name || (d.branches || []).find(b => !b.current)?.name || d.upstream || d.branch;
  const refs = [...new Set([d.branch, ...(d.branches || []).map(b => b.name), ...(d.tags || [])])];
  const options = refs.map(ref => `<option value="${esc(ref)}"></option>`).join('');
  const r = gitUI.review;
  const reviewedCount = r ? r.files.filter(f => gitUI.reviewed[gitReviewKey({...r, root: d.root}, f.path)]).length : 0;
  const summary = r ? `<div class="lee-git-review-summary"><strong>${r.summary.files} files</strong><span class="add">+${r.summary.additions}</span><span class="del">−${r.summary.deletions}</span><span>${reviewedCount}/${r.summary.files} reviewed</span><button id="gitreviewcopynotes">copy notes</button></div>` : '';
  const commits = r?.commits.length ? `<details class="lee-git-review-commits"><summary>${r.commits.length} incoming commit${r.commits.length === 1 ? '' : 's'}</summary>${r.commits.map(c => `<button data-commit="${esc(c.oid)}"><code>${esc(c.short)}</code><span>${esc(c.subject)}</span><small>${esc(c.author)} · ${gitRelative(c.timestamp)}</small></button>`).join('')}</details>` : '';
  const alternative = r?.snapshot_alternative?.files ? `<div class="lee-git-review-direction"><strong>No changes are proposed by ${esc(r.head)}</strong><span>${esc(r.head)} is already contained in ${esc(r.base)}. The refs still have ${r.snapshot_alternative.files} file difference${r.snapshot_alternative.files === 1 ? '' : 's'} because ${esc(r.base)} is ${r.base_only} commit${r.base_only === 1 ? '' : 's'} ahead.</span><button id="gitreviewsnapshot">show ${r.snapshot_alternative.files} snapshot differences</button><button id="gitreviewswap">review the opposite direction</button></div>` : '';
  const files = r?.files.length ? r.files.map((f, i) => {
    const reviewed = !!gitUI.reviewed[gitReviewKey({...r, root: d.root}, f.path)];
    const note = gitUI.reviewNotes[gitReviewKey({...r, root: d.root}, f.path)];
    return `<button class="lee-git-review-file${f.path === gitUI.reviewFile ? ' active' : ''}${reviewed ? ' reviewed' : ''}" data-review-path="${esc(f.path)}" data-review-index="${i}"><b>${reviewed ? '✓' : f.status}</b><span>${f.old_path ? `${esc(f.old_path)} → ` : ''}${esc(f.path)}${note ? ' · note' : ''}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`;
  }).join('') : r ? '<div class="lee-git-empty-state"><strong>No files in this review direction</strong><span>Swap base and branch, or use complete snapshots to see content that differs.</span></div>' : '<div class="lee-git-empty-state"><strong>Choose a branch to review</strong><span>Review proposed branch changes or compare complete snapshots.</span></div>';
  return `<section class="lee-git-review-controls"><label>Base<input id="gitreviewbase" list="gitreviewrefs" value="${esc(gitUI.reviewBase)}"></label><label>Branch<input id="gitreviewhead" list="gitreviewrefs" value="${esc(gitUI.reviewHead)}"></label>` +
    `<datalist id="gitreviewrefs">${options}</datalist><button id="gitreviewcontrolswap" title="Swap base and branch">swap direction</button><select id="gitreviewmode"><option value="review">proposed changes</option><option value="snapshot">complete snapshots</option></select><button id="gitreviewload">review</button></section>` + summary + alternative + commits +
    `<div class="lee-git-review-workspace"><header><strong>Changed files</strong><span>Click a file to open its diff in an editor tab.</span></header><aside class="lee-git-review-files">${files}</aside></div>`;
}
function gitCommitInspector() {
  const c = gitUI.selectedCommit; if (!c) return '';
  const files = c.files.map(f => `<button class="lee-git-commit-file" data-commit-file="${esc(f.path)}"><b>${esc(f.status)}</b><span>${f.old_path ? `${esc(f.old_path)} → ` : ''}${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
  return `<article class="lee-git-commit-inspector"><header><div><strong>${esc(c.message.split('\n')[0])}</strong><span>${esc(c.author)} · ${gitRelative(c.timestamp)} · ${esc(c.short)}</span></div><button data-cherry>cherry-pick</button><button data-revert>revert</button><button data-reset>reset…</button><button data-close-commit aria-label="Close commit details">×</button></header><section class="lee-git-commit-stats"><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span><code>${esc(c.oid)}</code></section>${c.message.includes('\n') ? `<div class="lee-git-commit-message">${esc(c.message)}</div>` : ''}<details open><summary>changed files</summary><div>${files}</div></details></article>`;
}
function gitHistoryView(d) {
  const refs = [...new Set([...(d.branches || []).map(b => b.name), ...(d.tags || [])])];
  if (!gitUI.compareTo) gitUI.compareTo = d.branch;
  if (!gitUI.compareFrom) gitUI.compareFrom = (d.branches || []).find(b => b.default && b.name !== d.branch)?.name || (d.branches || []).find(b => !b.current)?.name || d.upstream || d.branch;
  const suggestions = refs.map(ref => `<option value="${esc(ref)}"></option>`).join('');
  return `<div class="lee-git-filter"><input id="githistoryfilter" class="lee-input" value="${esc(gitUI.historyQuery)}" placeholder="Search commit messages…"><button id="githistorygo">search</button>` +
    `<select id="githistoryref"><option value="--all">all refs</option>${(d.branches || []).map(b => `<option value="${esc(b.name)}">${esc(b.name)}</option>`).join('')}</select><button id="gitreflog">reflog</button></div>` +
    `<section class="lee-git-compare"><header><strong>Compare snapshots</strong><span>All file changes, including branches behind current</span></header>` +
    `<div class="lee-git-compare-fields"><label>From (base)<input id="gitcompareleft" list="gitcomparerefs" value="${esc(gitUI.compareFrom)}" autocomplete="off"></label>` +
    `<button id="gitcompareswap" title="Swap comparison direction" aria-label="Swap comparison direction">⇄</button><label>To (target)<input id="gitcompareright" list="gitcomparerefs" value="${esc(gitUI.compareTo)}" autocomplete="off"></label>` +
    `<datalist id="gitcomparerefs">${suggestions}</datalist><button id="gitcomparego">compare files</button></div><small>Shows the exact change needed to turn the base snapshot into the target.</small></section>` +
    gitCommitInspector() + `<div id="githistoryrows" class="lee-git-history">${gitUI.history.length ? gitUI.history.map(c => `<button class="lee-git-commit-row${gitUI.selectedCommit?.oid === c.oid ? ' active' : ''}" data-history-commit="${c.oid}"><span class="lee-git-graph">${c.parents.length > 1 ? '◆' : '●'}</span><span><strong>${esc(c.subject)}</strong><small>${esc(c.author)} · ${gitRelative(c.timestamp)} · ${esc(c.short)}${c.decoration ? ' · ' + esc(c.decoration) : ''}</small></span></button>`).join('') : '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading commit graph</small></div>'}</div>`;
}
function gitResourcesView(d) {
  const hosted = (d.remotes || []).find(r => r.web_url);
  const pr = hosted ? `${hosted.web_url}/${hosted.web_url.includes('gitlab') ? '-/merge_requests/new?merge_request[source_branch]=' : 'compare/' + encodeURIComponent(d.branch) + '?expand=1'}${hosted.web_url.includes('gitlab') ? encodeURIComponent(d.branch) : ''}` : '';
  return `<section class="lee-git-resource"><header><strong>Remotes</strong>${pr ? `<button data-hosted-pr data-url="${esc(pr)}">open pull request</button>` : ''}<button id="gitaddremote">add remote</button></header><div class="lee-sc-meta">` +
    `${(d.remotes || []).map(r => `<article data-remote="${esc(r.name)}"><strong>${esc(r.name)}</strong><code>${esc(r.fetch)}</code><code>${esc(r.push)}</code><span>${r.web_url ? `<button data-open-remote data-url="${esc(r.web_url)}">open host</button>` : ''}<button data-fetch-remote>fetch</button><button data-edit-remote>edit</button><button data-remove-remote class="warn">remove</button></span></article>`).join('') || '<div class="lee-git-empty-state"><strong>No remotes</strong><span>Add a remote to fetch, publish, and collaborate.</span></div>'}</div></section>` +
    `<section class="lee-git-resource"><header><strong>Worktrees</strong><button id="gitaddworktree">add worktree</button></header><div id="gitworktrees"><div class="lee-git-loading"><small>reading worktrees</small></div></div></section>` +
    `<section class="lee-git-resource"><header><strong>Submodules</strong></header><div id="gitsubmodules"><div class="lee-git-loading"><small>reading submodules</small></div></div></section>`;
}
function gitScope() {
  if (!gitUI.repo) return '';
  return `<div class="lee-git-scope" title="The branch pill, tree badges and editor change marks still follow the file you have open."><b>${esc(gitRepoName(gitUI.repo))}</b>` +
    `<span>pinned</span><span class="lee-spacer"></span><button id="gitscopeclear">follow active tab</button></div>`;
}
function gitRepoBadges(r) {
  if (r.error) return `<i class="warn">${esc(r.error)}</i>`;
  return [r.changed ? `<i class="warn">${r.changed} changed</i>` : '<i>clean</i>',
    r.behind ? `<i class="warn">↓${r.behind}</i>` : '', r.ahead ? `<i>↑${r.ahead}</i>` : '',
    r.upstream ? '' : '<i>unpublished</i>', r.off_branch ? '<i class="warn">off branch</i>' : '',
    r.unreleased ? `<i>${r.unreleased} since ${esc(r.tag)}</i>` : '',
    r.operation ? `<i class="warn">${esc(r.operation)} in progress</i>` : ''].filter(Boolean).join('');
}
function gitReposView() {
  const d = gitUI.repos;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repositories</small></div>';
  const s = d.summary || {}, rows = d.repos || [];
  const results = gitUI.reposResults.length ? `<details class="lee-sc-group" open><summary><span>Last run</span><b>${gitUI.reposResults.length}</b></summary>` +
    `<div class="lee-git-repo-results">${gitUI.reposResults.map(r => `<article class="${r.ok === false ? 'failed' : r.skipped ? 'skipped' : 'done'}">` +
      `<strong>${esc(r.name || r.spec || '')}</strong><span>${esc(r.error || r.skipped || r.output || 'done')}</span></article>`).join('')}</div></details>` : '';
  const list = rows.length ? rows.map(r => `<article class="lee-git-repo-row${r.root === gitUI.repo ? ' active' : ''}${r.off_branch ? ' off-branch' : ''}${gitUI.reposBusy?.has(r.root) ? ' working' : ''}" data-repo="${esc(r.root)}" title="${esc(r.root)}">` +
    `<button data-repo-open title="Point source control at this repository">${gitUI.reposBusy?.has(r.root) ? '<span class="lee-spin"></span>' : (r.root === gitUI.repo ? '●' : '○')}</button>` +
    `<div class="lee-git-repo-copy"><strong>${esc(r.name)}</strong><span>${esc(r.branch || 'no branch')}${r.upstream ? ' · ' + esc(r.upstream) : ''}</span>` +
    `<small>${esc(r.last_commit?.subject || 'no commits yet')}${r.last_commit?.timestamp ? ' · ' + gitRelative(r.last_commit.timestamp) : ''}</small>` +
    `<div class="lee-git-badges">${gitRepoBadges(r)}<button data-repo-fetch title="Fetch this repository">fetch</button></div></div>` +
    `<button data-repo-remove title="Stop listing this repository here" aria-label="Stop listing this repository">×</button></article>`).join('') :
    `<div class="lee-git-empty-state"><strong>No repositories in this workspace</strong><span>Open a folder that is a checkout or holds them, clone one, or add a checkout from elsewhere.</span></div>`;
  return `<section class="lee-git-repos-summary"><strong>${s.repos || 0} repositor${s.repos === 1 ? 'y' : 'ies'}</strong>` +
    `${s.dirty ? `<span class="warn">${s.dirty} dirty</span>` : '<span>all clean</span>'}` +
    `${s.behind ? `<span class="warn">${s.behind} behind</span>` : ''}${s.ahead ? `<span>${s.ahead} ahead</span>` : ''}` +
    `${s.off_branch ? `<span class="warn">${s.off_branch} off branch</span>` : ''}` +
    `${s.unreleased ? `<span>${s.unreleased} unreleased</span>` : ''}${s.errors ? `<span class="warn">${s.errors} unreadable</span>` : ''}</section>` +
    `<div class="lee-sc-actions"><button data-repos-op="status">refresh</button><button data-repos-op="fetch">fetch all</button>` +
    `<button data-repos-op="pull">pull all</button><button data-repos-op="push">push all</button>` +
    `<button id="gitrepoclone">clone…</button><button id="gitrepoadd">add repository…</button></div>` +
    `<div class="lee-git-filter"><input id="gitrepoexpect" class="lee-input" value="${esc(gitUI.expect)}" placeholder="Expected branch — default: ${esc(d.expected_branch || 'the one most share')}" aria-label="Expected branch"></div>` +
    `<div class="lee-git-repo-list">${list}</div>` + results;
}
async function loadGitRepos() {
  try { gitUI.repos = await api('/git/repos' + (gitUI.expect ? '?expect=' + encodeURIComponent(gitUI.expect) : '')); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
}
async function gitReposDo(op, extra = {}) {
  const started = performance.now();
  const targets = (extra.paths && extra.paths.length ? extra.paths
                   : ((gitUI.repos && gitUI.repos.repos) || []).map(r => r.root));
  /* The fan-out answers all at once, so there is no per-repository progress to stream. What
     there is: which repositories are in flight. Naming them beats "workspace fetch…" when one
     of them is slow, because the question you have is always *which one*. */
  gitUI.reposBusy = new Set(targets);
  gitUI.reposResults = [];
  if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
  status(`workspace ${op} · ${targets.length} ${targets.length === 1 ? 'repository' : 'repositories'}…`);
  try {
    const d = await post('/git/repos/action', {op, expect: gitUI.expect, ...extra});
    gitUI.repos = d; gitUI.reposResults = d.results || [];
    const failed = gitUI.reposResults.filter(r => r.ok === false).length;
    const skipped = gitUI.reposResults.filter(r => r.ok !== false && r.skipped).length;
    const done = gitUI.reposResults.length - failed - skipped;
    status(`workspace ${op}: ${done} done · ${skipped} skipped · ${failed} failed · ${Math.round(performance.now() - started)} ms`,
           failed ? 'err' : 'ok');
    for (const r of gitUI.reposResults) {
      leeLog('git', `${op} · ${r.name}${r.skipped ? ' — ' + r.skipped : ''}`,
             r.ok === false ? (r.error || 'failed') : (r.output || ''), r.ok === false ? 'err' : '');
    }
    if (failed) showLog('git');       // one repository refusing is the reason to read the log
    if (gitUI.repo && !(d.repos || []).some(r => r.root === gitUI.repo)) gitUI.repo = '';
    gitUI.snapshot = null;
    await renderGitPanel();
    refreshProjectPills();
    return d;
  } catch (e) {
    const detail = e.message || String(e);
    leeLog('git', `workspace ${op} failed`, detail, 'err');
    showLog('git');
    status(`workspace ${op} failed — ${firstLine(detail)}`, 'err');
  }
  finally {
    gitUI.reposBusy = null;
    if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
  }
}
// Pinning is a scope change, not a filter: every ref, commit and review already loaded
// belongs to the repository being left, so all of it goes rather than being shown against
// the wrong one.
async function gitPinRepo(root, tab = 'changes') {
  gitUI.repo = String(root || '');
  gitUI.snapshot = null; gitUI.history = []; gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = '';
  gitUI.reviewBase = ''; gitUI.reviewHead = ''; gitUI.compareFrom = ''; gitUI.compareTo = '';
  gitUI.selectedCommit = null; gitUI.selectedChanges.clear();
  gitUI.tab = tab;
  await renderGitPanel();
  if (!gitUI.repo) refreshProjectPills();
}

/* ------------------------------------------------- workflows and the release pipeline */
// Both panels are about a project rather than a file, so they ask the same question the
// source-control panel does -- which repository -- and answer it the same way: empty means
// the one the active tab is in.
const wfUI = {data: null, runs: null, env: null, catalogue: null, docker: null, open: '', view: 'graph', preview: '', busy: ''};
const relUI = {data: null, busy: '', poll: 0};
function projectRepo() { return gitUI.repo || ''; }
function projectQuery(params = {}) {
  const q = new URLSearchParams(params);
  if (projectRepo()) q.set('repo', projectRepo());
  const query = q.toString();
  return query ? `?${query}` : '';
}
function wfStatusNote(st) {
  if (!st) return '';
  if (!st.gheasy) return `<div class="lee-wf-note"><strong>Local only</strong><span>${esc(st.why)}</span><code>pip install "leela[github]"</code></div>`;
  if (!st.repo) return '<div class="lee-wf-note"><strong>No GitHub remote</strong><span>Runs and secrets need one; the files below still read.</span></div>';
  if (!st.token) return `<div class="lee-wf-note"><strong>No GITHUB_TOKEN</strong><span>Set it in Environment below and the run history appears.</span></div>`;
  return '';
}
function wfJobBox(job, run) {
  const jr = (run?.jobs || []).find(j => j.name === job.name || j.name === job.id);
  const state = jr ? (jr.conclusion || jr.status || '') : '';
  return `<article class="lee-wf-job ${state ? 'state-' + esc(state) : ''}" data-job="${esc(job.id)}">` +
    `<header><strong>${esc(job.name)}</strong>${state ? `<i>${esc(state)}</i>` : ''}</header>` +
    `<small>${esc(job.runs_on || job.uses || '')}${job.environment ? ' · ' + esc(job.environment) : ''}</small>` +
    `${job.if ? `<code class="lee-wf-if">if ${esc(job.if)}</code>` : ''}` +
    `<ol class="lee-wf-steps">${job.steps.map(st => `<li title="${esc(st.uses || st.run)}">${esc(st.name)}</li>`).join('')}</ol></article>`;
}
function wfGraph(wf, run) {
  if (wf.error) return `<div class="lee-git-empty-state"><strong>${esc(wf.file)}</strong><span>${esc(wf.error)}</span></div>`;
  if (!wf.jobs.length) return `<div class="lee-git-empty-state"><strong>No jobs</strong><span>${esc(wf.file)} declares no jobs.</span></div>`;
  const byId = Object.fromEntries(wf.jobs.map(j => [j.id, j]));
  return `<div class="lee-wf-graph">${wf.levels.map((row, i) => `<div class="lee-wf-level">` +
    `${i ? '<span class="lee-wf-edge" aria-hidden="true"></span>' : ''}` +
    `<div class="lee-wf-row">${row.map(id => wfJobBox(byId[id], run)).join('')}</div></div>`).join('')}</div>`;
}
function wfRunRow(r) {
  const state = r.conclusion || r.status || '';
  return `<button class="lee-wf-run state-${esc(state)}" data-run="${r.id}" data-url="${esc(r.url)}">` +
    `<b>${state === 'success' ? '✓' : state === 'failure' ? '✗' : state === 'in_progress' ? '•' : '·'}</b>` +
    `<span><strong>${esc(r.title || r.name || r.file)}</strong><small>${esc(r.file)} · ${esc(r.branch)} · ${esc(r.event)}${r.actor ? ' · ' + esc(r.actor) : ''}</small></span>` +
    `<small>#${r.number || ''}</small></button>`;
}
function wfPickRows(cat) {
  if (!cat) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the project</small></div>';
  const d = cat.detect || {};
  const tags = Object.entries(d).filter(([k, v]) => v === true).map(([k]) => `<i>${esc(k)}</i>`).join('');
  const rows = (cat.workflows || []).map(w => `<article class="lee-wf-pick${w.recommended ? ' recommended' : ''}${w.present ? ' present' : ''}" data-pick="${esc(w.id)}">` +
    `<div><strong>${esc(w.name)}</strong><small>${esc(w.doc)}</small>` +
    `${w.recommended ? `<i class="lee-wf-because">recommended · ${esc(w.why)}</i>` : ''}</div>` +
    `<span class="lee-wf-pickfile">${esc(w.file)}</span>` +
    `<button data-pick-preview>preview</button>` +
    `${w.present ? '<span class="lee-wf-has">already here</span>' : '<button data-pick-add>add</button>'}</article>`).join('');
  return `<div class="lee-wf-detect"><strong>detected</strong>${tags || '<i>nothing conclusive</i>'}` +
    `${d.build ? `<code>${esc(d.build)}</code>` : d.build_why ? `<small>${esc(d.build_why)}</small>` : ''}</div>` +
    `<div class="lee-wf-picks">${rows}</div>`;
}
// `refresh` fetches what GitHub has; without this the answer was thrown away. Values of secrets
// are not readable by GitHub's design, so remote presence is all there is to show for one.
function wfRemoteMark(remote, key) {
  if (!remote) return '';
  const hit = (remote.secrets || []).find(s => s.name === key) || (remote.variables || []).find(v => v.name === key);
  if (!hit) return '<span class="lee-wf-remote missing" title="not on GitHub">·</span>';
  const when = String(hit.updated_at || '').slice(0, 10);
  return `<span class="lee-wf-remote" title="on GitHub${when ? ', updated ' + when : ''}">gh</span>`;
}
function wfRemoteExtra(remote, entries) {
  if (!remote) return '';
  const declared = new Set((entries || []).map(e => e.key));
  const extra = [...(remote.secrets || []), ...(remote.variables || [])].map(x => x.name).filter(n => !declared.has(n));
  return extra.length ? `<div class="lee-wf-remote-extra">on GitHub but not declared here: ${extra.map(esc).join(', ')}</div>` : '';
}
function wfEnvRows(entries, remote) {
  if (!entries?.length) return '<div class="lee-git-empty-state"><strong>Nothing declared</strong><span>Add <code>env_schema</code> to .gheasy/config.json, or a release step that needs a key.</span></div>';
  return entries.map(e => `<article class="lee-wf-env${e.set ? ' is-set' : ''}" data-env="${esc(e.key)}">` +
    `<div><strong>${esc(e.key)}</strong><small>${e.target}${e.declared ? '' : ' · from a release step'}</small></div>` +
    `<span class="lee-wf-envval">${e.secret ? (e.set ? '••••••••' : 'not set') : esc(e.value || 'not set')}</span>` +
    wfRemoteMark(remote, e.key) +
    `<button data-env-set>${e.set ? 'change' : 'set'}</button>${e.set ? '<button data-env-unset aria-label="remove">×</button>' : ''}</article>`).join('')
    + wfRemoteExtra(remote, entries);
}
function renderWorkflowsPanel() {
  const host = $('#workflowspanel'); if (!host) return;
  const d = wfUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading workflows</small></div>'; return; }
  const st = d.status || {};
  const wf = d.workflows.find(w => w.file === wfUI.open) || d.workflows[0];
  if (wf) wfUI.open = wf.file;
  const tabs = d.workflows.map(w => `<button data-wf="${esc(w.file)}" class="${w.file === wfUI.open ? 'active' : ''}">${esc(w.name)}</button>`).join('');
  const runsFor = (wfUI.runs || []).filter(r => !wf || !r.file || r.file === wf.file);
  const body = wfUI.view === 'runs'
    ? `<div class="lee-wf-runs">${runsFor.length ? runsFor.map(wfRunRow).join('')
        : `<div class="lee-git-empty-state"><strong>No runs</strong><span>${st.token ? 'This workflow has not run yet.' : 'Connect a token to see run history.'}</span></div>`}</div>`
    : wfUI.view === 'add'
    ? wfPickRows(wfUI.catalogue)
    : wfUI.view === 'build'
    ? renderBuilder()
    : wfUI.view === 'yaml'
    ? `<pre class="lee-wf-yaml">${esc(wfUI.preview || 'Generate to preview the workflow gheasy would write from .gheasy/config.json.')}</pre>`
    : wf ? wfGraph(wf, wfUI.runJobs) : '<div class="lee-git-empty-state"><strong>No workflows</strong><span>This project has no .github/workflows yet.</span></div>';
  host.innerHTML = wfStatusNote(st) +
    `<header class="lee-sc-branch"><div><strong>${esc(st.repo || d.root.split('/').pop())}</strong><span>${d.workflows.length} workflow${d.workflows.length === 1 ? '' : 's'}${d.config ? ' · gheasy config' : ''}</span></div></header>` +
    `<nav class="lee-git-nav" aria-label="Workflow views">${[['graph', 'Jobs'], ['add', 'Add'], ['build', 'Build'], ['runs', 'Runs'], ['env', 'Environment']].map(([id, label]) =>
      `<button data-wf-view="${id}" class="${wfUI.view === id ? 'active' : ''}">${label}</button>`).join('')}</nav>` +
    (wfUI.view === 'add' || wfUI.view === 'build'
      ? `<main class="lee-wf-body">${body}</main>`
      : wfUI.view === 'env'
      ? `<div class="lee-sc-actions"><button data-wf-env="refresh">refresh</button>` +
        `${st.gh_cli && !st.gh_auth ? '<button data-wf-env="auth">gh auth login…</button>' : ''}` +
        `<button data-wf-env="push" ${st.gh_auth ? '' : 'title="pushing uses the GitHub CLI"'}>push declared to GitHub</button>` +
        `<button data-wf-env="add">add key…</button></div>` +
        `<div class="lee-wf-envs">${wfEnvRows(wfUI.env?.entries, wfUI.env?.remote)}</div>`
      : `<div class="lee-wf-tabs">${tabs}</div>` +
        `<div class="lee-sc-actions">${wf?.dispatchable ? '<button data-wf-op="dispatch">run workflow</button>' : ''}` +
        `<button data-wf-op="open">open file</button><button data-wf-op="edit">edit in builder</button>` +
        `<button data-wf-op="generate">from gheasy config</button>` +
        `${d.config ? '<button data-wf-op="write">write gheasy.yml</button>' : ''}` +
        `<button data-wf-op="docker">Dockerfile…</button></div>` +
        `<main class="lee-wf-body">${body}</main>`);
  wireWorkflowsPanel(host, d, wf);
  if (wfUI.view === 'build') wireBuilder(host);
}
function wireWorkflowsPanel(host, d, wf) {
  host.querySelectorAll('[data-wf-view]').forEach(b => b.onclick = () => {
    wfUI.view = b.dataset.wfView; renderWorkflowsPanel();
    if (wfUI.view === 'runs' && !wfUI.runs) loadWorkflowRuns();
    if (wfUI.view === 'add' && !wfUI.catalogue) loadWorkflowCatalogue();
    if (wfUI.view === 'build' && !bldUI.vocab) loadBuilder(wfUI.open);
    if (wfUI.view === 'env' && !wfUI.env) loadWorkflowEnv();
  });
  host.querySelectorAll('[data-wf]').forEach(b => b.onclick = () => { wfUI.open = b.dataset.wf; wfUI.runJobs = null; renderWorkflowsPanel(); });
  host.querySelectorAll('[data-wf-op]').forEach(b => b.onclick = () => workflowOp(b.dataset.wfOp, wf));
  host.querySelector('[data-wf-op="edit"]')?.addEventListener('click', () => { wfUI.view = 'build'; loadBuilder(wf?.file); });
  host.querySelectorAll('.lee-wf-pick').forEach(row => {
    const id = row.dataset.pick;
    row.querySelector('[data-pick-preview]').onclick = () => pickWorkflow('preview', id);
    row.querySelector('[data-pick-add]')?.addEventListener('click', () => pickWorkflow('add', id));
  });
  host.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
    try { wfUI.runJobs = {jobs: (await api('/workflows/jobs' + projectQuery({id: b.dataset.run}))).jobs};
          wfUI.view = 'graph'; renderWorkflowsPanel();
          status('run ' + b.dataset.run + ': job results are on the graph', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  host.querySelectorAll('[data-env]').forEach(row => {
    const key = row.dataset.env;
    row.querySelector('[data-env-set]').onclick = async () => {
      const entry = (wfUI.env?.entries || []).find(e => e.key === key) || {};
      const value = await inputDialog(`set ${key}`, entry.secret ? 'Value (stored in your keychain, never shown again)' : 'Value',
                                      entry.secret ? '' : (entry.value || ''), entry.secret ? 'paste the token' : 'value');
      if (value) envOp('set', {key, value, secret: !!entry.secret});
    };
    row.querySelector('[data-env-unset]')?.addEventListener('click', async () => {
      if (await confirmDialog('remove value', `Remove ${key} from the keychain and the env file?`, 'remove')) envOp('unset', {key});
    });
  });
  host.querySelectorAll('[data-wf-env]').forEach(b => b.onclick = async () => {
    const op = b.dataset.wfEnv;
    if (op === 'refresh') return loadWorkflowEnv(true);
    // Authenticating is a conversation with a browser and a one-time code in it, so the
    // button opens the real `gh auth login` rather than a form pretending to be one.
    if (op === 'auth') { await openTerm('gh-auth'); return status('finish the login in the terminal, then refresh', 'ok'); }
    if (op === 'push') {
      if (await confirmDialog('push to GitHub', 'Send every declared value to this repository as a secret or a variable?', 'push')) envOp('push', {});
      return;
    }
    const key = await inputDialog('add key', 'Environment key', '', 'GITHUB_TOKEN');
    if (!key) return;
    const value = await inputDialog(`set ${key}`, 'Value (stored in your keychain)', '', 'paste the value');
    if (value) envOp('set', {key, value, secret: true});
  });
}
async function leeWorkflows() {
  try { wfUI.data = await api('/workflows' + projectQuery()); }
  catch (e) { const host = $('#workflowspanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderWorkflowsPanel();
  if (wfUI.view === 'runs' && !wfUI.runs) loadWorkflowRuns();
  if (wfUI.view === 'add' && !wfUI.catalogue) loadWorkflowCatalogue();
  if (wfUI.view === 'env' && !wfUI.env) loadWorkflowEnv();
}
window.leeWorkflows = leeWorkflows;
async function loadWorkflowCatalogue() {
  try { wfUI.catalogue = await api('/workflows/catalogue' + projectQuery()); }
  catch (e) { status(e.message || String(e), 'err'); return; }
  renderWorkflowsPanel();
}
async function pickWorkflow(op, id) {
  try {
    const d = await post('/workflows/action', {op: op === 'add' ? 'add' : 'preview', repo: projectRepo(), workflow: id});
    if (d.yaml) { wfUI.preview = d.yaml; wfUI.view = 'yaml'; }
    if (d.path) { status(`wrote ${d.path}`, 'ok'); wfUI.catalogue = null; loadWorkflowCatalogue(); }
    if (d.workflows) wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadWorkflowRuns() {
  if (!wfUI.data?.status?.token) { wfUI.runs = []; return renderWorkflowsPanel(); }
  try { wfUI.runs = (await api('/workflows/runs' + projectQuery({limit: 20}))).runs; }
  catch (e) { wfUI.runs = []; status(e.message || String(e), 'err'); }
  renderWorkflowsPanel();
}
async function loadWorkflowEnv(remote = false) {
  try { wfUI.env = await api('/workflows/env' + projectQuery(remote ? {remote: true} : {})); }
  catch (e) { status(e.message || String(e), 'err'); return; }
  renderWorkflowsPanel();
}
async function envOp(op, extra) {
  try {
    const d = await post('/workflows/env/action', {op, repo: projectRepo(), ...extra});
    wfUI.env = {...(wfUI.env || {}), entries: d.entries};
    // A push changes what GitHub has, so a listing already on screen is now wrong.
    if (op === 'push' && wfUI.env.remote) return loadWorkflowEnv(true);
    if (d.results) {
      const failed = d.results.filter(r => r.ok === false).length;
      status(`pushed ${d.results.filter(r => r.ok && !r.skipped).length} · skipped ${d.results.filter(r => r.skipped).length} · failed ${failed}`, failed ? 'err' : 'ok');
    } else status(`${extra.key} ${op === 'unset' ? 'removed' : 'saved'}`, 'ok');
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function workflowOp(op, wf) {
  try {
    if (op === 'open') { if (wf) leeOpenFile(wf.path); return; }
    if (op === 'edit') return;                       // wired separately: it changes view, not state
    if (op === 'docker') {
      const d = await api('/workflows/docker' + projectQuery());
      if (d.why) return status(d.why, 'err');
      if (d.dockerfile) return status('this project already has a Dockerfile', 'ok');
      if (!await confirmDialog('write Dockerfile', `dockeasy detected:\n\n${d.base}\n\nWrite this Dockerfile?`, 'write')) return;
      op = 'dockerfile';
    }
    if (op === 'dispatch') {
      const ref = await inputDialog('run workflow', 'Branch or tag to run on', '', 'leave empty for the current branch');
      if (ref === null) return;
      const d = await post('/workflows/action', {op, repo: projectRepo(), workflow: wf.file, ref});
      wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
      status(`dispatched ${wf.file} on ${d.ref}`, 'ok');
      wfUI.view = 'runs'; setTimeout(loadWorkflowRuns, 1500);
      return renderWorkflowsPanel();
    }
    const d = await post('/workflows/action', {op, repo: projectRepo()});
    wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
    if (d.yaml) { wfUI.preview = d.yaml; wfUI.view = 'yaml'; }
    if (d.path) status(`wrote ${d.path}`, 'ok');
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}

// -- the workflow builder ---------------------------------------------------------------
// A form over gheasy's DSL. The vocabulary comes from the server as data, so a preset added
// in leela/wfbuild.py appears here without a line of frontend -- and the form is the list of
// decisions a workflow actually has, which is the part that is hard to learn from YAML.
const bldUI = {vocab: null, spec: null, yaml: '', file: '', stale: false, timer: 0};
function blankSpec() {
  return {name: 'ci', file: 'ci.yml', on: {push: 'main', pull_request: 'main', workflow_dispatch: true},
          jobs: [{preset: 'uv_test', needs: []}]};
}
function bldTrigger(t, on) {
  const v = on[t.id];
  const checked = t.kind === 'flag' ? !!v : (v !== undefined && v !== false && v !== '');
  const field = t.kind === 'flag' ? '' :
    `<input class="lee-input" data-trigger-value="${t.id}" value="${esc(checked ? String(v ?? t.default) : t.default)}" ` +
    `placeholder="${esc(t.kind === 'cron' ? 'minute hour day month weekday' : 'main, release')}" ${checked ? '' : 'disabled'}>`;
  return `<article class="lee-bld-trigger"><label><input type="checkbox" data-trigger="${t.id}" ${checked ? 'checked' : ''}>` +
    `<strong>${esc(t.label)}</strong></label><small>${esc(t.doc)}</small>${field}</article>`;
}
function bldOption(o, job, i) {
  const value = (job.options || {})[o.key] ?? o.default;
  const field = o.type === 'flag'
    ? `<input type="checkbox" data-opt="${o.key}" data-job="${i}" ${value ? 'checked' : ''}>`
    : o.type === 'lines'
    ? `<textarea class="lee-keyedit" rows="3" data-opt="${o.key}" data-job="${i}">${esc(value)}</textarea>`
    : `<input class="lee-input" data-opt="${o.key}" data-job="${i}" value="${esc(value)}">`;
  return `<label class="lee-bld-opt"><span>${esc(o.label)}</span>${field}${o.doc ? `<small>${esc(o.doc)}</small>` : ''}</label>`;
}
function bldJob(job, i, presets, spec) {
  const preset = presets.find(p => p.id === job.preset) || presets[0];
  const others = spec.jobs.map((j, n) => n === i ? null : (j.id || (presets.find(p => p.id === j.preset) || {}).job))
                         .filter(Boolean);
  const needs = (job.needs || []).join(', ');
  return `<article class="lee-bld-job" data-job="${i}">` +
    `<header><select data-preset="${i}">${presets.map(p => `<option value="${p.id}" ${p.id === job.preset ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>` +
    `<button data-job-up="${i}" title="move earlier" ${i ? '' : 'disabled'}>↑</button>` +
    `<button data-job-del="${i}" title="remove" aria-label="remove job">×</button></header>` +
    `<small>${esc(preset.doc)}</small>` +
    (others.length ? `<label class="lee-bld-opt"><span>waits for</span>` +
      `<input class="lee-input" data-needs="${i}" value="${esc(needs)}" placeholder="${esc(others.join(', '))}"></label>` : '') +
    preset.options.map(o => bldOption(o, job, i)).join('') + `</article>`;
}
function renderBuilder() {
  const v = bldUI.vocab;
  if (!v) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the presets</small></div>';
  const spec = bldUI.spec || (bldUI.spec = blankSpec());
  return `<div class="lee-bld">` +
    `<div class="lee-bld-head"><label class="lee-bld-opt"><span>file</span><input class="lee-input" id="bldfile" value="${esc(spec.file || 'ci.yml')}"></label>` +
    `<label class="lee-bld-opt"><span>name</span><input class="lee-input" id="bldname" value="${esc(spec.name || 'ci')}"></label></div>` +
    `${bldUI.stale ? '<div class="lee-wf-note"><strong>The file has been edited</strong><span>Writing replaces those edits with what this form says.</span></div>' : ''}` +
    `<section class="lee-bld-section"><header>when it runs</header>${v.triggers.map(t => bldTrigger(t, spec.on || {})).join('')}</section>` +
    `<section class="lee-bld-section"><header>what it does<button id="bldaddjob">add job</button></header>` +
    `${spec.jobs.map((j, i) => bldJob(j, i, v.presets, spec)).join('')}</section>` +
    `<div class="lee-sc-actions"><button id="bldwrite">write ${esc(spec.file || 'ci.yml')}</button><button id="bldyaml">show YAML</button></div>` +
    `${bldUI.yaml ? `<pre class="lee-wf-yaml">${esc(bldUI.yaml)}</pre>` : ''}</div>`;
}
function wireBuilder(host) {
  const spec = bldUI.spec;
  const touch = () => { renderWorkflowsPanel(); scheduleBuild(); };
  host.querySelector('#bldfile')?.addEventListener('change', e => { spec.file = e.target.value.trim(); touch(); });
  host.querySelector('#bldname')?.addEventListener('change', e => { spec.name = e.target.value.trim(); touch(); });
  host.querySelectorAll('[data-trigger]').forEach(b => b.onchange = () => {
    const id = b.dataset.trigger, t = bldUI.vocab.triggers.find(x => x.id === id);
    spec.on = spec.on || {};
    if (!b.checked) delete spec.on[id];
    else spec.on[id] = t.kind === 'flag' ? true : t.default;
    touch();
  });
  host.querySelectorAll('[data-trigger-value]').forEach(i => i.onchange = () => {
    spec.on[i.dataset.triggerValue] = i.value.trim(); touch();
  });
  host.querySelector('#bldaddjob')?.addEventListener('click', () => { spec.jobs.push({preset: 'run', needs: []}); touch(); });
  host.querySelectorAll('[data-preset]').forEach(sel => sel.onchange = () => {
    const i = Number(sel.dataset.preset);
    spec.jobs[i] = {preset: sel.value, needs: spec.jobs[i].needs || []};
    touch();
  });
  host.querySelectorAll('[data-job-del]').forEach(b => b.onclick = () => { spec.jobs.splice(Number(b.dataset.jobDel), 1); touch(); });
  host.querySelectorAll('[data-job-up]').forEach(b => b.onclick = () => {
    const i = Number(b.dataset.jobUp); if (!i) return;
    [spec.jobs[i - 1], spec.jobs[i]] = [spec.jobs[i], spec.jobs[i - 1]]; touch();
  });
  host.querySelectorAll('[data-needs]').forEach(i => i.onchange = () => {
    spec.jobs[Number(i.dataset.needs)].needs = i.value.split(',').map(x => x.trim()).filter(Boolean);
    touch();
  });
  host.querySelectorAll('[data-opt]').forEach(el => el.onchange = () => {
    const job = spec.jobs[Number(el.dataset.job)];
    job.options = job.options || {};
    job.options[el.dataset.opt] = el.type === 'checkbox' ? el.checked : el.value;
    scheduleBuild();
  });
  host.querySelector('#bldyaml')?.addEventListener('click', () => buildYaml(true));
  host.querySelector('#bldwrite')?.addEventListener('click', async () => {
    try {
      const d = await post('/workflows/action', {op: 'write_spec', repo: projectRepo(), spec: bldUI.spec, file: bldUI.spec.file});
      status(`wrote ${d.path}`, 'ok');
      wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
      wfUI.catalogue = null; bldUI.stale = false; wfUI.view = 'graph';
      wfUI.open = bldUI.spec.file;
      renderWorkflowsPanel();
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}
function scheduleBuild() { clearTimeout(bldUI.timer); bldUI.timer = setTimeout(() => buildYaml(false), 350); }
async function buildYaml(show) {
  try {
    const d = await post('/workflows/action', {op: 'build', repo: projectRepo(), spec: bldUI.spec});
    if (show || bldUI.yaml) { bldUI.yaml = d.yaml; renderWorkflowsPanel(); }
    else bldUI.yaml = '';
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadBuilder(file = '') {
  if (!bldUI.vocab) { try { bldUI.vocab = await api('/workflows/presets'); } catch (e) { return status(e.message || String(e), 'err'); } }
  if (file) {
    try {
      const d = await api('/workflows/spec' + projectQuery({file}));
      if (d.spec) { bldUI.spec = d.spec; bldUI.stale = !!d.stale; }
    } catch (e) {}
  }
  if (!bldUI.spec) bldUI.spec = blankSpec();
  renderWorkflowsPanel();
}

// -- the release pipeline ------------------------------------------------------------
const REL_MARK = {passed: '✓', failed: '✗', running: '•', skipped: '⤼', pending: '·'};
// A failed step's traceback belongs to *someone*, and in a stack you own that is the whole
// question. The server rewrote the path to the checkout in this workspace, so "open" lands
// in the repository rather than in a copy under .venv that the next sync overwrites.
function blameRow(b) {
  if (!b || !b.package) return '';
  const where = b.file ? `${b.package}/${b.file.split('/').slice(-1)[0]}:${b.line}` : b.package;
  return `<div class="lee-blame"><strong>${esc(b.package)}</strong>` +
    `<span>${esc(b.error || 'raised here')}</span>` +
    `<code>${esc(where)}${b.fn ? ' in ' + esc(b.fn) : ''}</code>` +
    `${b.checkout ? '<i>your checkout</i>' : '<i class="warn">installed copy</i>'}` +
    `${b.open ? `<button data-blame-open="${esc(b.open)}" data-blame-line="${b.line}">open</button>` : ''}</div>`;
}
function wireBlame(host) {
  host.querySelectorAll('[data-blame-open]').forEach(b => b.onclick = async () => {
    try { await leeOpenFile(b.dataset.blameOpen); } catch (e) { return status(e.message || String(e), 'err'); }
    // The line the traceback named, once the editor has actually mounted the file.
    const line = Number(b.dataset.blameLine) || 0;
    if (!line) return;
    setTimeout(() => {
      const view = lee.editors.get('file'); if (!view) return;
      const doc = view.state.doc, at = doc.line(Math.max(1, Math.min(line, doc.lines)));
      // `setCursor` deliberately does not scroll, so the move is dispatched with the
      // scroll asked for -- landing on a line you cannot see is not landing on it.
      view.dispatch({selection: {anchor: at.from}, scrollIntoView: true});
      LeeCM.focus?.(view);
    }, 350);
  });
}
function openProjectEnv() {
  leeLeft('workflows'); wfUI.view = 'env'; wfUI.env = null; return leeWorkflows();
}
// A finished pipeline refuses to start again server-side, because its end publishes or ships.
async function confirmRerun(d, what) {
  return !d.done || confirmDialog(`run ${what} again`,
    `Every step already ran. Forget that and run the whole ${what} again from the top?`, 'run again');
}
function relStepRow(s, d) {
  const busy = d.running && s.status !== 'running';
  return `<article class="lee-rel-step state-${s.status}" data-step="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong>${esc(s.label)}</strong><code>${esc(s.cmd)}</code>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${s.missing.length ? `<i class="warn">needs ${s.missing.map(esc).join(', ')}</i>` : ''}</div>` +
    `<span class="lee-rel-actions">` +
    `${s.status === 'running' ? '<button data-rel="stop">stop</button>' :
      `<button data-rel="step" ${busy ? 'disabled' : ''} title="run only this step">run</button>` +
      `${s.status === 'failed' ? `<button data-rel="start" ${busy ? 'disabled' : ''} title="retry, then continue">retry</button><button data-rel="skip" title="mark done without running">skip</button>` : ''}`}` +
    `</span></article>`;
}
function renderReleasesPanel() {
  const host = $('#releasespanel'); if (!host) return;
  const d = relUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the pipeline</small></div>'; return; }
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(d.root.split('/').pop())}</strong>` +
    `<span>${d.nbdev ? 'nbdev project' : 'plain project'} · ${done}/${d.steps.length} done${d.configured ? ' · .leela/release.json' : ' · default pipeline'}</span></div></header>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-rel-top="stop" class="warn">stop</button>' : `<button data-rel-top="start">${d.failed ? 'continue' : 'run release'}</button>`}` +
    `<button data-rel-top="terminal">terminal</button><button data-rel-top="env">environment</button><button data-rel-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-rel-top="edit">edit steps</button>${d.configured ? '<button data-rel-top="defaults">defaults</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the release terminal. Fix and retry, or skip it deliberately.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>` +
    `${d.needs.length ? `<div class="lee-rel-needs"><strong>needs</strong>${d.needs.map(k => `<i>${esc(k)}</i>`).join('')}<button data-rel-top="env">environment…</button></div>` : ''}`;
  wireReleasesPanel(host, d);
  wireBlame(host);
  relPoll(d);
}
function wireReleasesPanel(host, d) {
  host.querySelectorAll('[data-rel-top]').forEach(b => b.onclick = () => releaseTop(b.dataset.relTop, d));
  host.querySelectorAll('.lee-rel-step').forEach(row => {
    const step = row.dataset.step;
    row.querySelectorAll('[data-rel]').forEach(b => b.onclick = () => releaseOp(b.dataset.rel, {step}));
  });
}
function relPoll(d) {
  clearTimeout(relUI.poll);
  // Steps finish on their own and start the next one, so the panel has to keep asking.
  // Only while something is running: an idle pipeline costs nothing.
  if (d.running) relUI.poll = setTimeout(() => leeReleases(), 1200);
}
async function leeReleases() {
  try { relUI.data = await api('/releases' + projectQuery()); }
  catch (e) { const host = $('#releasespanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderReleasesPanel();
}
window.leeReleases = leeReleases;
async function releaseOp(op, extra = {}) {
  try {
    relUI.data = await post('/releases/action', {op, repo: projectRepo(), ...extra});
    if (op === 'start' || op === 'step') await openReleaseTerm(relUI.data.root, 'release');
    renderReleasesPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function releaseTop(op, d) {
  if (op === 'terminal') return openReleaseTerm(d.root, 'release');
  if (op === 'env') return openProjectEnv();
  if (op === 'defaults') return releaseOp('reset_plan');
  if (op === 'start') {
    const missing = d.steps.flatMap(s => s.missing);
    if (missing.length && !await confirmDialog('run release',
        `These steps are missing ${[...new Set(missing)].join(', ')}. Run anyway?`, 'run')) return;
    if (!await confirmRerun(d, 'release')) return;
    if (d.done) await releaseOp('reset');
    return releaseOp('start');
  }
  if (op === 'stop') { if (await confirmDialog('stop release', 'Stop the running step?', 'stop')) releaseOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The commands are unchanged.', 'reset')) releaseOp('reset'); return; }
  if (op === 'edit') {
    const text = await textDialog('release steps', 'One step per line: id | label | command',
                                  d.steps.map(s => `${s.id} | ${s.label} | ${s.cmd}`).join('\n'));
    if (text === null) return;
    const steps = text.split('\n').map(line => line.split('|').map(x => x.trim())).filter(p => p.length >= 3 && p[2])
      .map(([id, label, cmd]) => ({id, label, cmd}));
    releaseOp('save', {steps});
  }
}

// -- deploy ---------------------------------------------------------------------------
// The same pipeline as a release, with a target above it: a deploy that cannot say where it
// is going is the one nobody presses.
const depUI = {data: null, poll: 0, view: 'stages', infra: null, stack: null, zone: '', records: null};
function depTargetCard(t) {
  const files = [['deploy.py', t.script], ['setup.py', t.setup], ['Dockerfile', t.dockerfile],
                 ['docker-compose.yml', t.compose], ['Caddyfile', t.caddyfile]];
  return `<header class="lee-sc-branch"><div><strong>${esc(t.domain || t.app)}</strong>` +
    `<span>${esc(t.server || 'no server named')} · ${esc(t.user)}@:${esc(t.port)}</span></div></header>` +
    `<div class="lee-dep-files">${files.map(([n, has]) => `<i class="${has ? 'has' : ''}">${esc(n)}</i>`).join('')}</div>` +
    (t.missing.length ? `<div class="lee-wf-note"><strong>${t.missing.length} value${t.missing.length === 1 ? '' : 's'} not set</strong>` +
      `<span>${t.missing.map(esc).join(', ')}</span><code>set them in Workflows → Environment</code><button data-dep-env>environment</button></div>` : '');
}

function depInfraRows() {
  const d = depUI.infra;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>asking Hetzner and Cloudflare</small></div>';
  const st = d.status || {};
  const half = (title, part, render) => `<section class="lee-inf-group"><header>${title}</header>` +
    (part.error ? `<div class="lee-wf-note"><span>${esc(part.error)}</span></div>`
                : (part.rows.length ? part.rows.map(render).join('')
                                    : '<div class="lee-dim lee-git-empty">none</div>')) + '</section>';
  return `<div class="lee-inf-status">${['vpseasy', 'cfeasy'].map(k => `<i class="${st[k] ? 'has' : ''}">${k}</i>`).join('')}` +
    `<i class="${st.hcloud_token ? 'has' : ''}">HCLOUD_TOKEN</i><i class="${st.cf_token ? 'has' : ''}">CLOUDFLARE_API_TOKEN</i></div>` +
    half('servers', d.servers || {rows: [], error: ''}, s =>
      `<article class="lee-inf-row" data-server="${esc(s.name)}"><div><strong>${esc(s.name)}</strong><small>${esc(s.ip || '')} · ${esc(s.status || '')}</small></div>` +
      `<button data-server-del title="delete this server">delete</button></article>`) +
    half('tunnels', d.tunnels || {rows: [], error: ''}, t =>
      `<article class="lee-inf-row" data-tunnel="${esc(t.id)}"><div><strong>${esc(t.name)}</strong><small>${esc(t.status || '')} · ${t.connections} connection${t.connections === 1 ? '' : 's'}</small></div>` +
      `<button data-tunnel-del title="delete this tunnel">delete</button></article>`) +
    half('zones', d.zones || {rows: [], error: ''}, z =>
      `<article class="lee-inf-row" data-zone="${esc(z.name)}"><div><strong>${esc(z.name)}</strong><small>${esc(z.status || '')}</small></div>` +
      `<button data-zone-dns>records</button></article>`) +
    (depUI.records ? `<section class="lee-inf-group"><header>${esc(depUI.zone)}</header>` +
      depUI.records.map(r => `<article class="lee-inf-row"><div><strong>${esc(r.name)}</strong>` +
        `<small>${esc(r.type)} · ${esc(r.content)}${r.proxied ? ' · proxied' : ''}</small></div>` +
        `${r.tunnel ? '<i class="lee-inf-tag">tunnel</i>' : ''}</article>`).join('') + '</section>' : '');
}
function depStackRows() {
  const d = depUI.stack;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the stack</small></div>';
  return `<div class="lee-inf-status"><i>${d.checkouts.length} checkouts open</i></div>` +
    `<div class="lee-pkgs">${d.packages.map(p => `<article class="lee-pkg${p.shadowed ? ' shadowed' : ''}">` +
      `<div><strong>${esc(p.name)}</strong><small>${p.installed ? esc(p.version || 'no version') + ' · ' + esc(p.source) : 'not installed'}</small>` +
      `${p.shadowed ? '<i class="warn">edits in your checkout are not what runs — reinstall it editable</i>' : ''}</div>` +
      `${p.checkout ? `<button data-pkg-open="${esc(p.checkout)}">open</button>` : ''}</article>`).join('')}</div>`;
}
async function loadInfra(force = false) {
  if (depUI.infra && !force) return renderDeployPanel();
  try { depUI.infra = await api('/infra'); } catch (e) { status(e.message || String(e), 'err'); return; }
  renderDeployPanel();
}
async function loadStack() {
  try { depUI.stack = await api('/stack' + projectQuery()); } catch (e) { status(e.message || String(e), 'err'); return; }
  renderDeployPanel();
}
async function infraOp(op, extra = {}) {
  try {
    depUI.infra = await post('/infra/action', {op, ...extra});
    status(`${op.replace('_', ' ')} done`, 'ok');
    renderDeployPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
function wireInfra(host) {
  host.querySelectorAll('[data-server-del]').forEach(b => b.onclick = async () => {
    const name = b.closest('[data-server]').dataset.server;
    if (await confirmDialog('delete server', `Delete ${name}? The machine and everything on it goes.`, 'delete'))
      infraOp('delete_server', {name});
  });
  host.querySelectorAll('[data-tunnel-del]').forEach(b => b.onclick = async () => {
    const row = b.closest('[data-tunnel]');
    if (await confirmDialog('delete tunnel', `Delete this tunnel? Anything routed through it stops answering.`, 'delete'))
      infraOp('delete_tunnel', {id: row.dataset.tunnel});
  });
  host.querySelectorAll('[data-zone-dns]').forEach(b => b.onclick = async () => {
    const zone = b.closest('[data-zone]').dataset.zone;
    try { depUI.zone = zone; depUI.records = (await api('/infra/records?zone=' + encodeURIComponent(zone))).records; }
    catch (e) { return status(e.message || String(e), 'err'); }
    renderDeployPanel();
  });
  host.querySelectorAll('[data-pkg-open]').forEach(b => b.onclick = () => leeOpenFile(b.dataset.pkgOpen));
}
function renderDeployPanel() {
  const host = $('#deploypanel'); if (!host) return;
  const d = depUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the deploy plan</small></div>'; return; }
  const t = d.target;
  const nav = `<nav class="lee-git-nav" aria-label="Deploy views">${[['stages', 'Stages'], ['infra', 'Servers'], ['stack', 'Stack']].map(([id, label]) =>
    `<button data-dep-view="${id}" class="${depUI.view === id ? 'active' : ''}">${label}</button>`).join('')}</nav>`;
  if (depUI.view !== 'stages') {
    host.innerHTML = depTargetCard(t) + nav +
      `<main class="lee-wf-body">${depUI.view === 'infra' ? depInfraRows() : depStackRows()}</main>`;
    host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
    wireInfra(host);
    if (depUI.view === 'infra' && !depUI.infra) loadInfra();
    if (depUI.view === 'stack' && !depUI.stack) loadStack();
    return;
  }
  host.innerHTML = depTargetCard(t) + nav +
    `<div class="lee-sc-actions">` +
    `${t.script ? (d.running ? '<button data-dep-top="stop" class="warn">stop</button>'
                             : `<button data-dep-top="start">${d.failed ? 'continue' : 'deploy'}</button>`)
                : '<button data-dep-top="scaffold">write deploy.py…</button>'}` +
    `<button data-dep-top="terminal">terminal</button><button data-dep-top="env">environment</button>` +
    `<button data-dep-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-dep-top="edit">edit steps</button>` +
    `${t.script ? '<button data-dep-top="open">open deploy.py</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the deploy terminal. The stages are idempotent — fix and continue.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
  host.querySelectorAll('[data-dep-top]').forEach(b => b.onclick = () => deployTop(b.dataset.depTop, d));
  host.querySelector('[data-dep-env]')?.addEventListener('click', openProjectEnv);
  wireBlame(host);
  host.querySelectorAll('.lee-rel-step').forEach(row => {
    const step = row.dataset.step;
    row.querySelectorAll('[data-rel]').forEach(b => b.onclick = () => deployOp(b.dataset.rel, {step}));
  });
  clearTimeout(depUI.poll);
  if (d.running) depUI.poll = setTimeout(() => leeDeploys(), 1200);
}
async function leeDeploys() {
  try { depUI.data = await api('/deploys' + projectQuery()); }
  catch (e) { const host = $('#deploypanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderDeployPanel();
}
window.leeDeploys = leeDeploys;
async function deployOp(op, extra = {}) {
  try {
    depUI.data = await post('/deploys/action', {op, repo: projectRepo(), ...extra});
    if (op === 'start' || op === 'step') await openReleaseTerm(depUI.data.root, 'deploy');
    renderDeployPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function deployTop(op, d) {
  const t = d.target;
  if (op === 'terminal') return openReleaseTerm(d.root, 'deploy');
  if (op === 'env') return openProjectEnv();
  if (op === 'open') return leeOpenFile(d.root + '/deploy.py');
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The stages are unchanged.', 'reset')) deployOp('reset'); return; }
  if (op === 'stop') { if (await confirmDialog('stop deploy', 'Stop the running stage?', 'stop')) deployOp('stop'); return; }
  if (op === 'scaffold') {
    const domain = await inputDialog('write deploy.py', 'Domain this app answers on', t.domain || '', 'example.com');
    if (!domain) return;
    const sub = await inputDialog('write deploy.py', 'Subdomain, or empty for the apex', '', 'app');
    if (sub === null) return;
    const second = await inputDialog('write deploy.py', 'A second hostname on the same container, or empty',
                                     '', 'the apex, as lego serves it');
    if (second === null) return;
    const r = await post('/deploys/action', {op: 'scaffold', repo: projectRepo(), domain,
                                             subdomain: sub, second_host: second})
                    .catch(e => { status(e.message || String(e), 'err'); });
    if (!r) return;
    depUI.data = r.state;
    status(`wrote ${(r.written || []).map(p => p.split('/').pop()).join(', ')}`, 'ok');
    return renderDeployPanel();
  }
  if (op === 'start') {
    if (t.missing.length && !await confirmDialog('deploy',
        `These are not set: ${t.missing.join(', ')}. Deploy anyway?`, 'deploy')) return;
    if (!await confirmRerun(d, 'deploy')) return;
    if (d.done) await deployOp('reset');
    return deployOp('start');
  }
  if (op === 'edit') {
    const text = await textDialog('deploy stages', 'One stage per line: id | label | command',
                                  d.steps.map(s => `${s.id} | ${s.label} | ${s.cmd}`).join('\n'));
    if (text === null) return;
    const steps = text.split('\n').map(l => l.split('|').map(x => x.trim())).filter(p => p.length >= 3 && p[2])
      .map(([id, label, cmd]) => ({id, label, cmd}));
    deployOp('save', {steps});
  }
}

// -- driving the packages one call at a time --------------------------------------------
// The alternative to the deploy script, kept as its own panel so the two can be compared:
// same runner, same terminal, same blame on a failure -- six library calls instead of three
// subcommands. The snippet is on screen because a button you cannot read is not a diagnostic.
const drvUI = {data: null, open: '', poll: 0};
function drvPart(s, d) {
  const m = s.meta || {}, busy = d.running && s.status !== 'running';
  const flow = [...(m.produces || []).map(f => `<i>writes ${esc(f)}</i>`),
                ...(m.writes || []).map(k => `<i class="writes">sets ${esc(k)}</i>`),
                ...(s.missing || []).map(k => `<i class="warn">needs ${esc(k)}</i>`)].join('');
  const open = drvUI.open === s.id;
  return `<article class="lee-drv-part state-${s.status}" data-part="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong><span class="lee-drv-pkg">${esc(m.package || '')}</span>${esc(m.title || s.label)}</strong>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${flow ? `<div class="lee-drv-flow">${flow}</div>` : ''}` +
    `<details ${open ? 'open' : ''}><summary>${open ? 'hide' : 'show'} the call</summary>` +
    `<pre class="lee-drv-code">${esc(m.code || '')}</pre></details></div>` +
    `<span class="lee-drv-actions">` +
    `${s.status === 'running' ? '<button data-drv="stop">stop</button>'
                              : `<button data-drv="step" ${busy ? 'disabled' : ''}>run</button>`}` +
    `</span></article>`;
}
function renderDrivePanel() {
  const host = $('#drivepanel'); if (!host) return;
  const d = drvUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the parts</small></div>'; return; }
  const c = d.context || {};
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(c.host || c.app || '')}</strong>` +
    `<span>${esc(d.packages.join(' · '))} · ${done}/${d.steps.length} run</span></div></header>` +
    `<div class="lee-drv-ctx"><b>values</b><i>app ${esc(c.app || '')}</i>` +
    `${c.domain ? `<i>domain ${esc(c.domain)}</i>` : '<i class="warn">DOMAIN not set</i>'}` +
    `${c.subdomain ? `<i>sub ${esc(c.subdomain)}</i>` : ''}<i>tunnel ${esc(c.tunnel || '')}</i></div>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-drv-top="stop" class="warn">stop</button>'
                 : '<button data-drv-top="start">run all</button>'}` +
    `<button data-drv-top="terminal">terminal</button>` +
    `<button data-drv-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-drv-top="values">environment</button></div>` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => drvPart(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-drv-top]').forEach(b => b.onclick = () => driveTop(b.dataset.drvTop, d));
  host.querySelectorAll('.lee-drv-part').forEach(row => {
    const step = row.dataset.part;
    row.querySelectorAll('[data-drv]').forEach(b => b.onclick = () => driveOp(b.dataset.drv, {step}));
    row.querySelector('details')?.addEventListener('toggle', e => { drvUI.open = e.target.open ? step : ''; });
  });
  wireBlame(host);
  clearTimeout(drvUI.poll);
  if (d.running) drvUI.poll = setTimeout(() => leeDrive(), 1200);
}
async function leeDrive() {
  try { drvUI.data = await api('/drive' + projectQuery()); }
  catch (e) { const host = $('#drivepanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderDrivePanel();
}
window.leeDrive = leeDrive;
async function driveOp(op, extra = {}) {
  try {
    drvUI.data = await post('/drive/action', {op, repo: projectRepo(), ...extra});
    if (op === 'step' || op === 'start') await openReleaseTerm(drvUI.data.root, 'drive');
    renderDrivePanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function driveTop(op, d) {
  if (op === 'terminal') return openReleaseTerm(d.root, 'drive');
  if (op === 'values') return openProjectEnv();
  if (op === 'stop') { if (await confirmDialog('stop', 'Stop the running call?', 'stop')) driveOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The calls are unchanged.', 'reset')) driveOp('reset'); return; }
  if (op === 'start') {
    const missing = [...new Set(d.steps.flatMap(s => s.missing))];
    if (missing.length && !await confirmDialog('run every call',
        `These are not set: ${missing.join(', ')}. Run anyway?`, 'run')) return;
    if (!await confirmRerun(d, 'run')) return;
    if (d.done) await driveOp('reset');
    return driveOp('start');
  }
}

async function renderGitPanel(snapshot = null) {
  const host = $('#gitpanel'); if (!host) return;
  host.dataset.features = 'Staged changes · Changes · Branches · Stashes · Remotes & tags · All repos · staged changes · working tree · fetch · pull · push · stash · tag · stage all · unstage all · fetch all · pull all · push all · clone';
  if (gitUI.tab === 'repos') {
    host.innerHTML = gitScope() + gitNav() + `<main class="lee-git-view">${gitReposView()}</main>`;
    wireGitPanel(host, gitUI.snapshot);
    if (!gitUI.repos) loadGitRepos();
    return;
  }
  if (!snapshot && !gitUI.snapshot) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repository</small></div>';
  let d = snapshot || gitUI.snapshot;
  try { if (!d) d = await api(gitUrl('/git/info')); }
  catch (e) {
    // Still draw the nav: a workspace whose active folder is not a checkout can have five
    // other repositories in it, and Repos is how you reach them.
    host.innerHTML = gitScope() + gitNav() +
      `<main class="lee-git-view"><div class="lee-git-empty-state"><strong>No Git repository</strong><span>${esc(e.message || e)}</span></div></main>`;
    // `null`, not `{}`: switching to another view from here must re-read the repository
    // rather than render a snapshot-shaped object with no fields in it.
    wireGitPanel(host, null);
    return;
  }
  gitUI.snapshot = d; paintGitPill(d);
  const view = gitUI.tab === 'changes' ? gitChangesView(d) : gitUI.tab === 'review' ? gitReviewView(d) : gitUI.tab === 'branches' ? gitBranchesView(d) : gitUI.tab === 'history' ? gitHistoryView(d) : gitResourcesView(d);
  host.innerHTML = gitScope() + gitSummary(d) + gitNav() + `<main class="lee-git-view">${view}</main>`;
  wireGitPanel(host, d);
  if (gitUI.tab === 'history' && !gitUI.history.length) loadGitHistory();
  if (gitUI.tab === 'review' && !gitUI.review) loadGitReview();
  if (gitUI.tab === 'resources') loadGitResources();
}
async function loadGitReview() {
  if (!gitUI.reviewBase || !gitUI.reviewHead) return;
  const host = $('.lee-git-review-workspace');
  if (host) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>building review</small></div>';
  try {
    gitUI.review = await api(gitUrl('/git/review', {base: gitUI.reviewBase, head: gitUI.reviewHead, mode: gitUI.reviewMode}));
    gitUI.reviewFile = gitUI.review.files[0]?.path || ''; gitUI.reviewPatch = '';
    renderGitPanel(gitUI.snapshot);
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadGitReviewFile(path, asTab = false) {
  if (!gitUI.review) return;
  gitUI.reviewFile = path;
  try {
    const d = await api(gitUrl('/git/review/file', {base: gitUI.review.base, head: gitUI.review.head, mode: gitUI.review.mode, path}));
    gitUI.reviewPatch = d.patch || '';
    if (asTab) return openGitDiffTab({...d, path, kind: 'review', baseLabel: gitUI.review.base, headLabel: gitUI.review.head, absolutePath: gitUI.snapshot.root + '/' + path, reviewKey: gitReviewKey({...gitUI.review, root: gitUI.snapshot.root}, path), allowWrite: !!d.can_apply && !path.toLowerCase().endsWith('.ipynb')});
    renderGitPanel(gitUI.snapshot);
  } catch (e) { status(e.message || String(e), 'err'); }
}
function moveGitReviewFile(delta) {
  const files = gitUI.review?.files || [], at = files.findIndex(f => f.path === gitUI.reviewFile);
  if (!files.length) return;
  loadGitReviewFile(files[(Math.max(0, at) + delta + files.length) % files.length].path);
}
async function loadGitHistory() {
  const rows = $('#githistoryrows');
  try {
    const ref = $('#githistoryref')?.value || '--all';
    const result = await api(gitUrl('/git/history', {limit: 150, query: gitUI.historyQuery, ref}));
    gitUI.history = result.commits || []; renderGitPanel(gitUI.snapshot);
  } catch (e) { if (rows) rows.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function loadGitResources() {
  try {
    const r = await api(gitUrl('/git/resources'));
    const worktrees = $('#gitworktrees');
    if (worktrees) worktrees.innerHTML = (r.worktrees || []).map(w => `<article class="lee-git-resource-row" data-worktree="${esc(w.path)}"><div><strong>${esc(w.branch || 'detached')}</strong><code>${esc(w.path)}</code></div>${w.path === gitUI.snapshot.root ? '<i>current</i>' : '<button data-remove-worktree class="warn">remove</button>'}</article>`).join('') || '<span class="lee-dim">No worktrees</span>';
    const submodules = $('#gitsubmodules');
    if (submodules) submodules.innerHTML = (r.submodules || []).map(s => `<article class="lee-git-resource-row"><div><strong>${esc(s.path)}</strong><code>${esc(s.oid)}</code></div><i>${s.state === ' ' ? 'clean' : s.state === '-' ? 'not initialized' : s.state === '+' ? 'different commit' : 'conflict'}</i></article>`).join('') || '<span class="lee-dim">No submodules</span>';
    worktrees?.querySelectorAll('[data-remove-worktree]').forEach(b => b.onclick = async () => {
      const path = b.closest('[data-worktree]').dataset.worktree;
      if (await confirmDialog('remove worktree', `Remove ${path}? Uncommitted work prevents removal.`, 'remove')) renderGitPanel(await gitDo('remove_worktree', {path}));
    });
  } catch (e) { status(e.message || String(e), 'err'); }
}
function wireGitPanel(host, d) {
  host.querySelectorAll('[data-git-tab]').forEach(b => b.onclick = () => { gitUI.tab = b.dataset.gitTab; if (gitUI.tab !== 'history') gitUI.history = []; renderGitPanel(d); });
  host.querySelector('#gitscopeclear')?.addEventListener('click', () => gitPinRepo(''));
  host.querySelectorAll('[data-repos-op]').forEach(b => b.onclick = () => gitReposDo(b.dataset.reposOp));
  host.querySelectorAll('.lee-git-repo-row').forEach(row => {
    const root = row.dataset.repo;
    row.querySelector('[data-repo-open]').onclick = () => gitPinRepo(root === gitUI.repo ? '' : root);
    row.querySelector('[data-repo-fetch]').onclick = () => gitReposDo('fetch', {paths: [root]});
    row.querySelector('[data-repo-remove]').onclick = async () => {
      if (!await confirmDialog('remove repository', `Stop listing ${gitRepoName(root)} here? The checkout is left alone.`, 'remove')) return;
      if (gitUI.repo === root) gitUI.repo = '';
      gitReposDo('remove', {path: root});
    };
  });
  const expect = host.querySelector('#gitrepoexpect');
  if (expect) expect.onchange = () => { gitUI.expect = expect.value.trim(); loadGitRepos(); };
  host.querySelector('#gitrepoadd')?.addEventListener('click', async () => {
    const path = await inputDialog('add repository', 'Path to a Git checkout', '', '/home/you/code/project');
    if (path) gitReposDo('add', {path});
  });
  host.querySelector('#gitrepoclone')?.addEventListener('click', async () => {
    const spec = await inputDialog('clone repositories', 'URLs or owner/name, one per line', '', 'AnswerDotAI/fastws');
    if (spec) gitReposDo('clone', {urls: spec.split(/[\s,]+/).filter(Boolean)});
  });
  const act = async (op, extra = {}) => renderGitPanel(await gitDo(op, extra));
  host.querySelectorAll('[data-operation]').forEach(b => b.onclick = async () => {
    if (b.dataset.operation === 'abort' && !await confirmDialog('abort Git operation', `Abort the active ${d.operation.active}?`, 'abort')) return;
    act('operation_' + b.dataset.operation);
  });
  host.querySelectorAll('[data-git-undo]').forEach(b => b.onclick = async () => {
    const point = (d.safepoints || [])[0];
    if (!await confirmDialog('undo Git operation',
        `Put this repository back where it was before ${point?.describe || 'the last operation'}?` +
        `\n\nHEAD returns to ${point?.head || 'the recorded commit'}` +
        `${point?.dirty ? ` and ${point.dirty} uncommitted file(s) are restored` : ''}.`, 'undo')) return;
    act('undo', {token: b.dataset.gitUndo});
  });
  host.querySelectorAll('[data-top]').forEach(b => b.onclick = () => b.dataset.top === 'publish' ? act('push', {publish: true}) : act(b.dataset.top));
  host.querySelector('#scstageall')?.addEventListener('click', e => { e.preventDefault(); act('stage', {paths: d.changes.filter(x => x.unstaged).map(x => x.path)}); });
  host.querySelector('#scunstageall')?.addEventListener('click', e => { e.preventDefault(); act('unstage', {paths: d.changes.filter(x => x.staged).map(x => x.path)}); });
  host.querySelector('#scstash')?.addEventListener('click', async () => { const message = await inputDialog('stash changes', 'Optional message', '', 'work in progress'); if (message !== null) act('stash', {message}); });
  host.querySelector('#sccommit')?.addEventListener('submit', e => { e.preventDefault(); const message = e.target.querySelector('textarea').value.trim(); if (message) act('commit', {message, amend: e.target.elements.amend.checked}); });
  host.querySelector('#screviewstaged')?.addEventListener('click', () => showStagedReview(d));
  host.querySelector('[data-conflict-center]')?.addEventListener('click', () => showConflictCenter());
  host.querySelectorAll('[data-selected-action]').forEach(b => b.onclick = async () => {
    const action = b.dataset.selectedAction;
    if (action === 'clear') { gitUI.selectedChanges.clear(); return renderGitPanel(d); }
    const selected = [...gitUI.selectedChanges].map(key => { const [group, ...parts] = key.split(':'); return {group, path: parts.join(':')}; });
    if (action === 'changelist') {
      const name = await inputDialog('move to changelist', 'Local changelist name', '', 'Focused change');
      if (name !== null) { for (const x of selected) { if (name) gitUI.changeLists[x.path] = name; else delete gitUI.changeLists[x.path]; } saveGitWorkflowState(); renderGitPanel(d); }
      return;
    }
    const paths = selected.filter(x => action === 'stage' ? x.group === 'unstaged' : x.group === 'staged').map(x => x.path);
    if (!paths.length) return status(`select ${action === 'stage' ? 'unstaged' : 'staged'} files`, 'err');
    gitUI.selectedChanges.clear(); act(action, {paths});
  });
  host.querySelectorAll('.lee-git-change').forEach(row => {
    const path = row.dataset.path, staged = row.dataset.group === 'staged';
    row.querySelector('[data-select-change]').onchange = e => { const key = `${row.dataset.group}:${path}`; if (e.target.checked) gitUI.selectedChanges.add(key); else gitUI.selectedChanges.delete(key); renderGitPanel(d); };
    row.querySelector('.lee-git-file').onclick = async () => { const patch = await api(gitUrl('/git/diff', {path, staged})); openGitDiffTab({kind: 'changes-' + row.dataset.group, path, absolutePath: d.root + '/' + path, base: staged ? 'HEAD' : 'index', head: staged ? 'index' : 'worktree', baseLabel: staged ? 'HEAD' : 'index', headLabel: staged ? 'staged' : 'working tree', left: patch.left || '', right: patch.right || '', patch: patch.content || patch.text || '', rawPatch: patch.text || '', notebook: !!patch.notebook, group: row.dataset.group, allowWrite: row.dataset.group === 'unstaged' && !patch.notebook}); };
    row.querySelector('[data-open]').onclick = () => leeOpenFile(d.root + '/' + path);
    row.querySelector('[data-blame]')?.addEventListener('click', () => showGitBlame(d.root, path, null));
    row.querySelector('[data-resolve]')?.addEventListener('click', () => showGitConflict(path));
    row.querySelectorAll('[data-git]').forEach(b => b.onclick = async () => { const op = b.dataset.git; if (op === 'discard' && !await confirmDialog('discard changes', `Restore ${path} from the index? This cannot be undone.`, 'discard')) return; act(op, {paths: [path]}); });
  });
  host.querySelectorAll('[data-stash]').forEach(row => { const ref = row.dataset.stash; row.querySelector('[data-apply]').onclick = () => act('stash_apply', {ref}); row.querySelector('[data-pop]').onclick = () => act('stash_pop', {ref}); row.querySelector('[data-drop]').onclick = async () => { if (await confirmDialog('drop stash', `Delete ${ref}?`, 'drop')) act('stash_drop', {ref}); }; });
  const branchFilter = host.querySelector('#gitbranchfilter'); if (branchFilter) branchFilter.oninput = () => { gitUI.branchQuery = branchFilter.value; renderGitPanel(d); requestAnimationFrame(() => { const x = $('#gitbranchfilter'); x?.focus(); x?.setSelectionRange(x.value.length, x.value.length); }); };
  const branchScope = host.querySelector('#gitbranchscope'); if (branchScope) { branchScope.value = gitUI.branchScope; branchScope.onchange = () => { gitUI.branchScope = branchScope.value; renderGitPanel(d); }; }
  host.querySelector('#scbranch')?.addEventListener('click', async () => { const branch = await inputDialog('new branch', 'Branch name', '', 'feature/name'); if (branch) act('create', {branch}); });
  host.querySelectorAll('[data-branch]').forEach(row => { const branch = row.dataset.branch; row.querySelector('[data-switch]').onclick = () => act('checkout', {branch}); row.querySelector('[data-compare]')?.addEventListener('click', () => { gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); }); const more = row.querySelector('[data-more]'); more?.addEventListener('click', () => gitBranchMenu(more, branch, d, act)); });
  host.querySelector('#sctag')?.addEventListener('click', async () => { const name = await inputDialog('create tag', 'Tag name', '', 'v1.0.0'); if (!name) return; const message = await inputDialog('annotated tag', 'Optional annotation', '', ''); if (message !== null) act('tag', {name, message}); });
  host.querySelectorAll('[data-delete-tag]').forEach(b => b.onclick = async () => { const name = b.closest('[data-tag]').dataset.tag; if (await confirmDialog('delete tag', `Delete local tag ${name}?`, 'delete')) act('delete_tag', {name}); });
  host.querySelector('#gitreviewmode') && (host.querySelector('#gitreviewmode').value = gitUI.reviewMode);
  const swapReviewDirection = () => { const base = $('#gitreviewbase')?.value.trim() || gitUI.reviewBase; gitUI.reviewBase = $('#gitreviewhead')?.value.trim() || gitUI.reviewHead; gitUI.reviewHead = base; gitUI.review = null; loadGitReview(); };
  host.querySelector('#gitreviewcontrolswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewsnapshot')?.addEventListener('click', () => { gitUI.reviewMode = 'snapshot'; gitUI.review = null; loadGitReview(); });
  host.querySelector('#gitreviewload')?.addEventListener('click', () => { gitUI.reviewBase = $('#gitreviewbase').value.trim(); gitUI.reviewHead = $('#gitreviewhead').value.trim(); gitUI.reviewMode = $('#gitreviewmode').value; gitUI.review = null; loadGitReview(); });
  host.querySelectorAll('[data-review-path]').forEach(b => b.onclick = () => loadGitReviewFile(b.dataset.reviewPath, true));
  host.querySelector('#gitreviewprev')?.addEventListener('click', () => moveGitReviewFile(-1));
  host.querySelector('#gitreviewnext')?.addEventListener('click', () => moveGitReviewFile(1));
  host.querySelector('#gitreviewmark')?.addEventListener('click', () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile); gitUI.reviewed[key] = !gitUI.reviewed[key]; saveGitWorkflowState(); renderGitPanel(d); });
  host.querySelector('#gitreviewnote')?.addEventListener('click', async () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile), note = await inputDialog('review note', `Note for ${gitUI.reviewFile}`, gitUI.reviewNotes[key] || '', 'Question, risk, or follow-up'); if (note !== null) { if (note.trim()) gitUI.reviewNotes[key] = note.trim(); else delete gitUI.reviewNotes[key]; saveGitWorkflowState(); renderGitPanel(d); } });
  host.querySelector('#gitreviewcopynotes')?.addEventListener('click', async () => { const prefix = `${d.root}\0${gitUI.review.base}\0${gitUI.review.head}\0${gitUI.review.mode}\0`, rows = Object.entries(gitUI.reviewNotes).filter(([key]) => key.startsWith(prefix)).map(([key, note]) => `- **${key.slice(prefix.length)}** — ${note}`); if (!rows.length) return status('this review has no notes', 'err'); const text = `# Review: ${gitUI.review.head} → ${gitUI.review.base}\n\n${rows.join('\n')}\n`; try { await navigator.clipboard.writeText(text); status(`copied ${rows.length} review note${rows.length === 1 ? '' : 's'}`, 'ok'); } catch (_) { status('clipboard access failed', 'err'); } });
  host.querySelector('#gitreviewapply')?.addEventListener('click', () => showReviewHunkApply(d));
  host.querySelector('#githistorygo')?.addEventListener('click', () => { gitUI.historyQuery = $('#githistoryfilter').value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#githistoryfilter')?.addEventListener('keydown', e => { if (e.key === 'Enter') { gitUI.historyQuery = e.target.value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); } });
  host.querySelector('#githistoryref')?.addEventListener('change', () => { gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#gitreflog')?.addEventListener('click', showGitReflog);
  host.querySelectorAll('[data-history-commit]').forEach(b => b.onclick = () => loadGitCommitInspector(b.dataset.historyCommit));
  host.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
  host.querySelectorAll('[data-commit-file]').forEach(b => b.onclick = () => openGitCommitFile(gitUI.selectedCommit.oid, b.dataset.commitFile));
  host.querySelector('[data-close-commit]')?.addEventListener('click', () => { gitUI.selectedCommit = null; renderGitPanel(d); });
  host.querySelector('.lee-git-commit-inspector [data-cherry]')?.addEventListener('click', () => act('cherry_pick', {ref: gitUI.selectedCommit.oid}));
  host.querySelector('.lee-git-commit-inspector [data-revert]')?.addEventListener('click', async () => { if (await confirmDialog('revert commit', `Create a commit that reverses ${gitUI.selectedCommit.short}?`, 'revert')) act('revert', {ref: gitUI.selectedCommit.oid}); });
  host.querySelector('.lee-git-commit-inspector [data-reset]')?.addEventListener('click', async () => { const c = gitUI.selectedCommit, mode = await inputDialog('reset branch', 'Mode: soft keeps index; mixed keeps files; hard discards changes', 'mixed', 'soft, mixed, or hard'); if (!['soft','mixed','hard'].includes(mode)) return status('reset mode must be soft, mixed, or hard', 'err'); if (mode === 'hard' && !await confirmDialog('hard reset', `Discard tracked changes and reset to ${c.short}? This cannot be undone.`, 'reset')) return; act('reset', {ref: c.oid, mode}); });
  const rememberCompare = () => { gitUI.compareFrom = $('#gitcompareleft')?.value.trim() || ''; gitUI.compareTo = $('#gitcompareright')?.value.trim() || ''; };
  host.querySelector('#gitcompareleft')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareright')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareswap')?.addEventListener('click', () => { const left = $('#gitcompareleft'), right = $('#gitcompareright'), value = left.value; left.value = right.value; right.value = value; rememberCompare(); });
  host.querySelector('#gitcomparego')?.addEventListener('click', () => { rememberCompare(); showGitCompare(gitUI.compareFrom, gitUI.compareTo); });
  host.querySelector('[data-hosted-pr]')?.addEventListener('click', e => window.open(e.currentTarget.dataset.url, '_blank', 'noopener,noreferrer'));
  host.querySelector('#gitaddremote')?.addEventListener('click', async () => { const name = await inputDialog('add remote', 'Remote name', '', 'origin'); if (!name) return; const url = await inputDialog('add remote', 'Fetch URL', '', 'https://github.com/owner/repository.git'); if (url) act('add_remote', {name, url}); });
  host.querySelectorAll('[data-remote]').forEach(row => { const remote = row.dataset.remote; row.querySelector('[data-open-remote]')?.addEventListener('click', b => window.open(b.currentTarget.dataset.url, '_blank', 'noopener,noreferrer')); row.querySelector('[data-fetch-remote]').onclick = () => act('fetch', {remote}); row.querySelector('[data-edit-remote]').onclick = async () => { const url = await inputDialog('edit remote', `${remote} fetch URL`, row.querySelector('code').textContent, 'https://github.com/owner/repository.git'); if (url) act('set_remote', {name: remote, url}); }; row.querySelector('[data-remove-remote]').onclick = async () => { if (await confirmDialog('remove remote', `Remove ${remote}? Local commits and branches remain.`, 'remove')) act('remove_remote', {name: remote}); }; });
  host.querySelector('#gitaddworktree')?.addEventListener('click', async () => { const path = await inputDialog('add worktree', 'Directory path', '', '../project-feature'); if (!path) return; const branch = await inputDialog('add worktree', 'Existing branch, or a new branch name', '', 'feature/name'); if (branch) act('add_worktree', {path, branch, create: !(d.branches || []).some(b => !b.remote && b.name === branch)}); });
}
async function showStagedReview(d) {
  const files = (d.changes || []).filter(c => c.staged);
  if (!files.length) return status('stage changes before reviewing them', 'err');
  const m = modal(`<div class="lee-mhead">Review staged changes<span class="sub">${files.length} file${files.length === 1 ? '' : 's'} will be committed</span><span class="lee-spacer"></span><button class="lee-btn" data-prev>previous</button><button class="lee-btn" data-next>next</button></div><div class="lee-git-full-review"><aside></aside><main class="lee-git-patch"></main></div><div class="lee-mfoot"><span class="lee-dim">Only the index is shown. Unstaged edits are not part of the commit.</span></div>`);
  m.classList.add('lee-git-review-expanded');
  let at = 0;
  const paint = async next => {
    at = (next + files.length) % files.length;
    const active = files[at];
    m.querySelector('aside').innerHTML = files.map((f, i) => `<button data-index="${i}" class="${i === at ? 'active' : ''}"><b>${esc(f.index)}</b><span>${esc(f.path)}</span></button>`).join('');
    m.querySelectorAll('[data-index]').forEach(b => b.onclick = () => paint(+b.dataset.index));
    const detail = await api(gitUrl('/git/diff', {path: active.path, staged: true}));
    m.querySelector('main').innerHTML = gitPatchHtml(detail.content || detail.text || '');
  };
  m.querySelector('[data-prev]').onclick = () => paint(at - 1);
  m.querySelector('[data-next]').onclick = () => paint(at + 1);
  paint(0);
}
function showReviewHunkApply(d) {
  if (!gitUI.reviewPatch || !gitUI.review?.can_apply) return status('partial apply requires a clean current branch that is the review base', 'err');
  const parts = gitPatchParts(gitUI.reviewPatch);
  if (!parts.hunks.length) return status('this file has no text hunks to apply', 'err');
  const m = modal(`<div class="lee-mhead">Apply parts of ${esc(gitUI.reviewFile)}<span class="sub">from ${esc(gitUI.review.head)} into the current working tree</span></div><div class="lee-git-patch">${parts.hunks.map((h, i) => `<label class="lee-git-hunk"><input type="checkbox" data-hunk="${i}" checked><span>hunk ${i + 1}</span>${gitPatchHtml(h)}</label>`).join('')}</div><div class="lee-mfoot"><button class="lee-btn go" data-apply>apply selected hunks</button><span class="lee-dim">Changes remain uncommitted and can be reviewed before staging.</span></div>`);
  m.querySelector('[data-apply]').onclick = async () => {
    const selected = [...m.querySelectorAll('[data-hunk]:checked')].map(x => parts.hunks[+x.dataset.hunk]);
    if (!selected.length) return status('select at least one hunk', 'err');
    if (!await confirmDialog('apply branch hunks', `Apply ${selected.length} selected hunk${selected.length === 1 ? '' : 's'} from ${gitUI.review.head} to the working tree?`, 'apply')) return;
    try { const next = await gitDo('apply_patch', {patch: parts.header + selected.join(''), staged: false}); m.remove(); gitUI.review = null; gitUI.tab = 'changes'; renderGitPanel(next); }
    catch (e) { status(e.message || String(e), 'err'); }
  };
}
async function showMergePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/merge-preview', {incoming: branch}));
    const r = p.review, relation = {'fast-forward': 'Fast-forward available', 'already-merged': 'Already contained in current', 'identical': 'Branches are identical', 'diverged': 'Branches have diverged'}[p.relation] || p.relation;
    const conflict = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts expected</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in merge rehearsal</strong><span>The working tree can still change before merge.</span></div>';
    // Untracked files are not dirt: git merges beside them and refuses only when the merge
    // would overwrite one, at which point it says so itself. Only tracked work blocks.
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const blocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                  : p.relation === 'already-merged' ? `${p.current} already contains ${branch}`
                  : p.relation === 'identical' ? 'the two branches are identical' : '';
    const m = modal(`<div class="lee-mhead">Merge ${esc(branch)}<span class="sub">into ${esc(p.current)}</span></div><div class="lee-git-merge-preview"><header><strong>${esc(relation)}</strong><span>${r.head_only} commits · ${r.summary.files} files · +${r.summary.additions} −${r.summary.deletions}</span></header>${dirty}${conflict}<label>Strategy<select data-strategy><option value="merge">merge commit when needed</option><option value="squash">squash into working tree</option><option value="ff-only" ${p.relation === 'fast-forward' ? '' : 'disabled'}>fast-forward only</option></select></label><button class="lee-btn" data-review>review incoming files</button></div><div class="lee-mfoot"><button class="lee-btn go" data-merge>merge ${esc(branch)}</button><span class="lee-dim">${blocked ? esc(blocked) : 'Merge starts only after this preview.'}</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    // Never a disabled button: one that cannot be pressed cannot say why, and "I clicked
    // merge and nothing happened" is the report that came back from exactly that.
    m.querySelector('[data-merge]').onclick = async () => {
      if (blocked) return status(`cannot merge — ${blocked}`, 'err');
      const strategy = m.querySelector('[data-strategy]').value;
      if (!await confirmDialog('merge branch', `Merge ${branch} into ${p.current} using ${strategy}?`, 'merge')) return;
      m.remove(); act('merge', {branch, strategy});
    };
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function showRebasePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/rebase-preview', {onto: branch})), r = p.review;
    const warning = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts may occur while replaying commits</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in the tree rehearsal</strong><span>Rebase replays commits individually, so this remains a forecast.</span></div>';
    const rbDirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const rbBlocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                    : p.already_based ? `${p.current} already contains ${branch}`
                    : !p.commits.length ? 'there is nothing to replay' : '';
    const m = modal(`<div class="lee-mhead">Rebase ${esc(p.current)}<span class="sub">onto ${esc(branch)}</span></div><div class="lee-git-merge-preview"><header><strong>${p.already_based ? 'Branch already contains the target history' : `${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} will be replayed`}</strong><span>${r.summary.files} proposed files · +${r.summary.additions} −${r.summary.deletions}</span></header>${rbDirty}${warning}<div class="lee-git-rebase-commits">${p.commits.slice(0, 12).map(c => `<span><code>${esc(c.short)}</code>${esc(c.subject)}</span>`).join('')}</div><button class="lee-btn" data-review>review branch changes</button></div><div class="lee-mfoot"><button class="lee-btn go" data-rebase>start rebase</button><span class="lee-dim">The operation banner will offer continue, skip, and abort if Git pauses.</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = branch; gitUI.reviewHead = d.branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    m.querySelector('[data-rebase]').onclick = async () => {
      if (rbBlocked) return status(`cannot rebase — ${rbBlocked}`, 'err');
      if (!await confirmDialog('rebase branch', `Replay ${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} from ${p.current} onto ${branch}?`, 'rebase')) return;
      m.remove(); act('rebase', {branch});
    };
  } catch (e) { status(e.message || String(e), 'err'); }
}
/* The branch row's `•••`, as a menu anchored to the button rather than a modal: picking a
   branch to compare against is a glance, not a dialogue. Named for this panel because the
   branch pill in `28_branchbar.js` has its own, differently-shaped menu, and the modules are
   concatenated into one scope -- two `function branchActions` and the later file silently won. */
function gitBranchMenu(anchor, branch, d, act) {
  const current = branch === d.branch;
  const review = mode => {
    Object.assign(gitUI, {reviewBase: d.branch, reviewHead: branch, reviewMode: mode, review: null, tab: 'review'});
    renderGitPanel(d);
  };
  const rows = [
    {label: `Checkout ${branch}`, disabled: current, run: () => act('checkout', {branch})},
    {label: 'New branch from…', detail: branch, run: async () => {
      const name = await inputDialog('new branch', `Branch name, starting at ${branch}`, '', 'feature/name');
      if (name) act('create', {branch: name, start: branch});
    }},
    {separator: true},
    {label: `Review ${branch} into ${d.branch}`, detail: 'proposed changes', disabled: current,
     run: () => review('review')},
    {label: `Diff ${d.branch} … ${branch}`, detail: 'complete snapshots', disabled: current,
     run: () => review('snapshot')},
    {separator: true},
    {label: `Rebase ${d.branch} onto ${branch}`, disabled: current, run: () => showRebasePreview(branch, d, act)},
    {label: `Merge ${branch} into ${d.branch}`, disabled: current, run: () => showMergePreview(branch, d, act)},
    {separator: true},
    {label: 'Rename…', run: async () => {
      const name = await inputDialog('rename branch', 'New name', branch, 'feature/name');
      if (name) act('rename_branch', {branch, name});
    }},
    {label: 'Set upstream…', run: async () => {
      const upstream = await inputDialog('set upstream', 'Remote tracking branch', '', 'origin/' + branch);
      if (upstream) act('set_upstream', {branch, upstream});
    }},
  ];
  if (!current) rows.push({separator: true}, {label: `Delete ${branch}`, warn: true, run: async () => {
    if (await confirmDialog('delete branch', `Delete local branch ${branch}?`, 'delete')) act('delete', {branch});
  }});
  openChromeMenu(anchor, rows);
}
async function loadGitCommitInspector(ref) {
  try { gitUI.selectedCommit = await api(gitUrl('/git/commit/review', {ref})); renderGitPanel(gitUI.snapshot); }
  catch (e) { status(e.message || String(e), 'err'); }
}
async function openGitCommitFile(ref, path) {
  try {
    const d = await api(gitUrl('/git/commit/file', {ref, path}));
    const c = gitUI.selectedCommit;
    return openGitDiffTab({...d, path, kind: 'commit', baseLabel: c?.parents?.[0]?.slice(0, 8) || 'empty tree', headLabel: c?.short || ref.slice(0, 8), absolutePath: gitUI.snapshot.root + '/' + path});
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function showGitCommit(ref) {
  try {
    const c = await api(gitUrl('/git/commit/review', {ref}));
    const files = c.files.map(f => `<button class="lee-git-commit-file" data-path="${esc(f.path)}"><b>${esc(f.status)}</b><span>${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
    const m = modal(`<div class="lee-mhead">${esc(c.short)}<span class="sub">${esc(c.author)} · ${new Date(c.timestamp * 1000).toLocaleString()}</span></div><article class="lee-git-commit-sheet"><h3>${esc(c.message)}</h3><section><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span></section><div>${files}</div></article>`);
    m.querySelectorAll('[data-path]').forEach(b => b.onclick = () => { m.remove(); gitUI.selectedCommit = c; openGitCommitFile(c.oid, b.dataset.path); });
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function showGitCompare(left, right) {
  if (!left || !right) return status('choose a base and target ref', 'err');
  gitUI.reviewBase = left; gitUI.reviewHead = right; gitUI.reviewMode = 'snapshot';
  gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = ''; gitUI.tab = 'review';
  await renderGitPanel(gitUI.snapshot);
}
async function showGitReflog() {
  try {
    const d = await api(gitUrl('/git/reflog', {limit: 150}));
    const m = modal(`<div class="lee-mhead">reflog<span class="sub">local recovery history · newest first</span></div><div class="lee-git-history">${(d.entries || []).map(x => `<button class="lee-git-commit-row" data-commit="${x.oid}"><span class="lee-git-graph">◆</span><span><strong>${esc(x.subject)}</strong><small>${esc(x.selector)} · ${esc(x.author)} · ${gitRelative(x.timestamp)} · ${esc(x.short)}</small></span></button>`).join('') || '<div class="lee-git-empty-state"><strong>No reflog entries</strong><span>This repository has no local movement history.</span></div>'}</div>`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
  } catch (e) { status(e.message || String(e), 'err'); }
}
// Three-pane conflict resolution: ours, an editable result, and theirs.
//
// The conflicts are read from the markers Git already wrote into the working-tree file, not
// diffed back out of the three versions. Git's own account of what it could not decide is
// better than anything reconstructed from the sides afterwards -- it knows which lines it
// tried to merge and gave up on, and a re-diff only guesses at it.
//
// The result pane is that file, markers and all, and it is re-scanned after every change.
// That is what lets the buttons and hand-editing coexist without either being a mode:
// "which conflicts are left" is answered by looking at the text rather than by remembering
// what was clicked, so an edit that removes a marker block counts as resolving it.

const CONFLICT_OPEN = /^<{7}(?:\s|$)/, CONFLICT_MID = /^={7}(?:\s|$)/,
      CONFLICT_BASE = /^\|{7}(?:\s|$)/, CONFLICT_CLOSE = /^>{7}(?:\s|$)/;

function scanConflicts(text) {
  const lines = String(text ?? '').split('\n'), blocks = [];
  for (let i = 0; i < lines.length; i++) {
    if (!CONFLICT_OPEN.test(lines[i])) continue;
    const block = {start: i, end: -1, ours: [], theirs: [], base: []};
    let side = block.ours, j = i + 1;
    for (; j < lines.length; j++) {
      if (CONFLICT_BASE.test(lines[j])) { side = block.base; continue; }
      if (CONFLICT_MID.test(lines[j])) { side = block.theirs; continue; }
      if (CONFLICT_CLOSE.test(lines[j])) { block.end = j; break; }
      side.push(lines[j]);
    }
    // An opening marker with no close is a line of text that happens to look like one --
    // in a file *about* merge conflicts, say. Not a conflict, and not ours to rewrite.
    if (block.end < 0) continue;
    blocks.push(block); i = block.end;
  }
  return {lines, blocks};
}

// One whole side of a conflicted file, as it would read if every contested block went that
// way. `ranges` are the 1-based line spans of the contested parts, for marking them.
function conflictSide(scan, pick) {
  const out = [], ranges = [];
  let at = 0;
  for (const block of scan.blocks) {
    out.push(...scan.lines.slice(at, block.start));
    const from = out.length + 1;
    out.push(...(block[pick] || []));
    // A side that deleted these lines contributes none, so the marker goes on the seam.
    ranges.push(out.length >= from ? {from, to: out.length}
                                   : {from: Math.max(1, from - 1), to: Math.max(1, from - 1)});
    at = block.end + 1;
  }
  out.push(...scan.lines.slice(at));
  return {text: out.join('\n'), ranges};
}

function replaceConflict(scan, index, lines) {
  const block = scan.blocks[index];
  if (!block) return null;
  return [...scan.lines.slice(0, block.start), ...lines,
          ...scan.lines.slice(block.end + 1)].join('\n');
}

async function showGitConflict(path) {
  try {
    const d = await api(gitUrl('/git/conflict', {path}));
    const original = scanConflicts(d.worktree || '');
    if (!original.blocks.length && (d.ours || d.theirs)) {
      // Add/add or delete/modify: there are no marked lines to work through, so the choice
      // is which whole side to keep, and pretending otherwise would be a worse dialog.
      return showWholeSideConflict(path, d);
    }
    const lang = codeLang('', path);
    const pane = (key, label, note) =>
      `<section data-pane="${key}"${key === 'base' ? ' hidden' : ''}>` +
      `<header><strong>${label}</strong>${note ? `<small>${note}</small>` : ''}</header>` +
      `<div class="lee-merge3-editor" data-editor></div></section>`;
    const m = modal(
      `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">ours · result · theirs</span></div>` +
      `<div class="lee-git-merge3">` +
      `<div class="lee-merge3-bar">` +
      `<span class="lee-merge3-count" data-count></span>` +
      `<button class="lee-btn" data-nav="prev" title="previous conflict">‹</button>` +
      `<button class="lee-btn" data-nav="next" title="next conflict">›</button>` +
      `<span class="lee-merge3-take">` +
      `<button class="lee-btn" data-take="ours">take ours</button>` +
      `<button class="lee-btn" data-take="theirs">take theirs</button>` +
      `<button class="lee-btn" data-take="both">both</button></span>` +
      `<button class="lee-btn" data-base-toggle>show base</button></div>` +
      `<div class="lee-merge3-panes">${pane('base', 'base', 'common ancestor')}` +
      `${pane('ours', 'ours', 'this branch')}` +
      `${pane('result', 'result', 'editable')}` +
      `${pane('theirs', 'theirs', 'incoming')}</div>` +
      `<div class="lee-merge3-foot"><span class="lee-dim" data-state></span>` +
      `<button class="lee-btn go" data-resolve>resolve &amp; stage</button></div></div>`,
      null, () => teardown(), {className: 'lee-modal-merge3', storageKey: 'git-conflict'});

    const views = {};
    const editorFor = key => m.querySelector(`[data-pane="${key}"] [data-editor]`);
    const teardown = () => Object.values(views).forEach(v => { try { LeeCM.destroy(v); } catch {} });
    let live = original, active = 0;

    const marks = (ranges, current) => ranges.map((r, i) =>
      ({...r, kind: i === current ? 'conflict-active' : 'conflict'}));

    for (const key of ['base', 'ours', 'theirs']) {
      const {text, ranges} = conflictSide(original, key);
      views[key] = LeeCM.create(editorFor(key), {
        doc: text, lang, readOnly: true, lineNums: true, settings: lee.editorPrefs});
      views[key]._ranges = ranges;
      LeeCM.setChangedLines(views[key], marks(ranges, 0));
    }
    // `onChange` runs inside CodeMirror's own update, where dispatching again is not allowed,
    // and `refresh` dispatches marks -- hence the deferral. `programmatic` is why a button's own
    // `setDoc` does not come back round here and refresh a second time from stale text.
    let programmatic = false;
    views.result = LeeCM.create(editorFor('result'), {
      doc: d.worktree || '', lang, lineNums: true, settings: lee.editorPrefs,
      onChange: text => { if (!programmatic) setTimeout(() => refresh(text, false), 0); }});

    // Which of the original blocks a remaining one is, matched on its contested text. Indices
    // cannot be used: resolving the second of three leaves two, and the sides still show three.
    // Two identical conflicts in one file align to the first of them, which is harmless.
    const originalIndex = block => original.blocks.findIndex(b =>
      b.ours.join('\n') === block.ours.join('\n') && b.theirs.join('\n') === block.theirs.join('\n'));

    // The side panes are read-only and CodeMirror only builds the lines it is showing, so
    // there is no element to scroll to for a conflict that is off screen. Proportional
    // scrolling gets there regardless, and lands close enough to read.
    const align = () => {
      const block = live.blocks[active];
      const index = block ? originalIndex(block) : -1;
      for (const key of ['base', 'ours', 'theirs']) {
        const view = views[key], range = index >= 0 ? view._ranges[index] : null;
        LeeCM.setChangedLines(view, marks(view._ranges, index));
        const scroller = view.dom.querySelector('.cm-scroller');
        if (!range || !scroller) continue;
        const total = Math.max(1, LeeCM.lineCount(view));
        scroller.scrollTop = Math.max(0, (range.from - 1) / total * scroller.scrollHeight
                                         - scroller.clientHeight / 3);
      }
    };

    const refresh = (text, move = true) => {
      live = scanConflicts(text ?? LeeCM.getDoc(views.result));
      const total = live.blocks.length;
      active = Math.max(0, Math.min(active, total - 1));
      const done = original.blocks.length - total;
      m.querySelector('[data-count]').textContent = total
        ? `conflict ${active + 1} of ${total}` : 'no conflicts left';
      m.querySelector('[data-state]').textContent = total
        ? `${done} of ${original.blocks.length} resolved`
        : `all ${original.blocks.length} resolved — staging marks this file merged`;
      m.querySelectorAll('[data-take],[data-nav]').forEach(b => b.disabled = !total);
      m.querySelector('[data-resolve]').classList.toggle('go', !total);
      LeeCM.setChangedLines(views.result, marks(
        live.blocks.map(b => ({from: b.start + 1, to: b.end + 1})), active));
      if (move) align();
    };

    const jumpTo = index => {
      const total = live.blocks.length;
      if (!total) return;
      active = (index + total) % total;
      const block = live.blocks[active];
      const at = live.lines.slice(0, block.start).reduce((n, l) => n + l.length + 1, 0);
      refresh(null, true);
      LeeCM.setSelection(views.result, at, at);
    };

    const take = which => {
      const block = live.blocks[active];
      if (!block) return;
      const lines = which === 'both' ? [...block.ours, ...block.theirs] : block[which];
      const next = replaceConflict(live, active, lines);
      if (next == null) return;
      programmatic = true;
      try { LeeCM.setDoc(views.result, next); } finally { programmatic = false; }
      refresh(next, true);
      if (live.blocks.length) jumpTo(Math.min(active, live.blocks.length - 1));
    };

    m.querySelectorAll('[data-take]').forEach(b => b.onclick = () => take(b.dataset.take));
    m.querySelector('[data-nav="prev"]').onclick = () => jumpTo(active - 1);
    m.querySelector('[data-nav="next"]').onclick = () => jumpTo(active + 1);
    m.querySelector('[data-base-toggle]').onclick = e => {
      const section = m.querySelector('[data-pane="base"]');
      section.hidden = !section.hidden;
      e.currentTarget.textContent = section.hidden ? 'show base' : 'hide base';
      if (!section.hidden) align();
    };
    m.querySelector('[data-resolve]').onclick = async () => {
      const content = LeeCM.getDoc(views.result);
      const left = scanConflicts(content).blocks.length;
      if (left && !await confirmDialog('stage an unresolved file',
          `${left} conflict marker block${left === 1 ? '' : 's'} are still in ${path}. Stage it ` +
          `anyway, markers and all?`, 'stage anyway')) return;
      const next = await gitDo('resolve_conflict', {path, choice: 'resolved', content});
      m.remove();
      renderGitPanel(next);
      status(next.outcome?.summary || `${path} staged as resolved`, 'ok');
    };
    refresh(d.worktree || '', true);
    jumpTo(0);
  } catch (e) { status(e.message || String(e), 'err'); }
}

// Add/add and delete/modify conflicts have no contested lines to work through -- one side has
// no file at all -- so the only question is which side to keep.
async function showWholeSideConflict(path, d) {
  const side = (label, text, choice) =>
    `<section><header><strong>${label}</strong>` +
    `<button class="lee-btn" data-choice="${choice}">use ${label}</button></header>` +
    `<pre>${esc(text || 'This side does not have this file.')}</pre></section>`;
  const m = modal(
    `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">one side has no file to merge</span></div>` +
    `<div class="lee-git-conflict">${side('ours', d.ours, 'ours')}${side('theirs', d.theirs, 'theirs')}` +
    `<details><summary>common base</summary><pre>${esc(d.base || 'No common base content.')}</pre></details></div>`,
    null, null, {storageKey: 'git-conflict-side'});
  m.querySelectorAll('[data-choice]').forEach(b => b.onclick = async () => {
    const choice = b.dataset.choice;
    if (!await confirmDialog('resolve conflict', `Use ${choice} for ${path} and stage it as resolved?`, 'resolve')) return;
    m.remove();
    const next = await gitDo('resolve_conflict', {path, choice});
    renderGitPanel(next);
    status(next.outcome?.summary || `${path} staged as resolved`, 'ok');
  });
}

// Blame, reachable from wherever you are rather than only from a changed-file row. A text
// file blames the lines you have selected -- "who wrote these six" is the question, and the
// whole-file answer is one button away. A notebook blames its cells, because blaming its
// JSON tells you about `"source": [` and nothing about your code.
function blameRelative(root, path) {
  const p = String(path || '');
  if (!root) return p;
  return p.startsWith(root + '/') ? p.slice(root.length + 1) : p;
}
function blameSelectionRange() {
  const view = curEditor(); if (!view || lee.kind === 'notebook') return null;
  const sel = view.state.selection.main;
  if (sel.empty) return null;
  const doc = view.state.doc;
  return {start: doc.lineAt(sel.from).number, end: doc.lineAt(sel.to).number};
}
async function leeBlame() {
  if (!lee.path) return status('open a file to blame it', 'err');
  let root = gitUI.snapshot?.root;
  if (!root) { try { root = (await api(gitUrl('/git/info'))).root; } catch (e) { return status(e.message || String(e), 'err'); } }
  showGitBlame(root, blameRelative(root, lee.path), blameSelectionRange());
}
window.leeBlame = leeBlame;
function blameHue(oid, commits) {
  // Colour by commit so a cell made of three commits reads as three bands. Position in the
  // recency-sorted legend, not a hash: the newest change is the one being looked for.
  const i = commits.findIndex(c => c.oid === oid);
  return i < 0 ? 'var(--lee-fg4)' : `hsl(${(i * 47) % 360} 55% 55%)`;
}
function blameLineRows(lines, commits, showN) {
  return lines.map(l => `<button class="lee-blame-line${l.uncommitted ? ' uncommitted' : ''}" data-commit="${esc(l.oid)}" ` +
    `title="${esc(l.author)} · ${esc(l.summary || '')}">` +
    `<i style="background:${blameHue(l.oid, commits)}"></i>` +
    `<code>${l.uncommitted ? 'working' : esc(l.oid.slice(0, 8))}</code>` +
    `<span class="lee-blame-who">${esc(l.author || '')}</span>` +
    `<small>${l.timestamp ? gitRelative(l.timestamp) : ''}</small>` +
    `<em>${showN ? l.n : l.line}</em><pre>${esc(l.text)}</pre></button>`).join('');
}
function blameCells(d) {
  const commits = d.commits || [];
  const legend = commits.length ? `<div class="lee-blame-legend">${commits.map(c =>
    `<i style="border-color:${blameHue(c.oid, commits)}">${c.uncommitted ? 'working tree' : esc(c.oid.slice(0, 8))} · ${esc(c.author || '')}</i>`).join('')}</div>` : '';
  const cells = d.cells.map(c => {
    const t = c.touched || {};
    const made = c.commits.length;
    return `<details class="lee-blame-cell" data-cell="${c.index}">` +
      `<summary><b>${c.index}</b><span class="lee-blame-kind">${esc(c.kind)}</span>` +
      `<strong>${esc(t.author || 'never committed')}</strong>` +
      `<small>${t.timestamp ? gitRelative(t.timestamp) : ''}${made > 1 ? ` · ${made} commits` : ''}` +
      `${c.mapped ? '' : ' · lines not located'}</small>` +
      `<span class="lee-blame-bar">${c.commits.map(x =>
        `<i style="background:${blameHue(x.oid, commits)};flex:${x.lines}"></i>`).join('')}</span></summary>` +
      `<div class="lee-git-blame">${blameLineRows(c.lines, commits, true)}</div></details>`;
  }).join('');
  return legend + `<div class="lee-blame-cells">${cells}</div>`;
}
async function showGitBlame(root, path, range = null) {
  try {
    const params = range ? {path, start: range.start, end: range.end} : {path};
    const d = await api(gitUrl('/git/blame', params));
    const scope = d.notebook ? `${d.cells.length} cells`
                             : range ? `lines ${range.start}–${range.end}` : 'whole file';
    const commits = d.commits || [];
    const body = d.notebook ? blameCells(d)
      : `<div class="lee-git-blame">${blameLineRows((d.lines || []).map(x => ({...x, uncommitted: /^0+$/.test(x.oid)})), commits, false)}</div>`;
    const m = modal(`<div class="lee-mhead">${esc(path)}<span class="sub">who wrote this · ${esc(scope)}</span></div>` +
      `${d.error ? `<div class="lee-dialogcopy">${esc(d.error)}</div>` : ''}${body}` +
      `${range ? '<div class="lee-mfoot"><button class="lee-btn" id="blameall">blame the whole file</button></div>' : ''}`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
    m.querySelector('#blameall')?.addEventListener('click', () => { m.remove(); showGitBlame(root, path, null); });
  } catch (e) { status(e.message || String(e), 'err'); }
}
function leeGit() { leeLeft('git'); }
function leeGitRefresh() { gitUI.snapshot = null; gitUI.history = []; renderGitPanel(); refreshProjectPills(); }
window.leeGit = leeGit; window.leeGitRefresh = leeGitRefresh;

async function leeNbdevPrepare() {
  status('nbdev prepare…', 'busy');
  try {
    const r = await post('/project/nbdev_prepare', {});
    status(`nbdev prepare · ${PathName(r.root)}${r.nbs_path ? ' · ' + r.nbs_path : ''}`, 'ok');
    refreshFileTree(undefined, false).catch(() => {});
  } catch (e) { status(String(e.message || e), 'err'); }
}
function PathName(path) { return String(path || '').split('/').pop() || path || ''; }
window.leeNbdevPrepare = leeNbdevPrepare;

/* ------------------------------------------------------------------ research */
function researchDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch (_) { return 'source'; }
}
function openWebpage(url) {
  if (!url) return status('choose a source first', 'err');
  window.open(url, '_blank', 'noopener,noreferrer');
}
async function saveDoc(doc, kind) {
  doc = doc || lee.lastDoc; if (!doc) return status('nothing fetched yet', 'err');
  if (kind === 'notebook' && !doc.url) return status('a research digest can be saved as markdown; source pages can become notebooks', 'err');
  if (!doc.text && doc.url && kind !== 'notebook') {
    status('reading source before saving…');
    const fetched = await api('/research/read?url=' + encodeURIComponent(doc.url));
    if (!fetched.doc) return status(fetched.note, 'err');
    doc = fetched.doc;
  }
  const r = await post('/research/save', {kind: kind === 'notebook' ? 'notebook' : 'md',
                                          url: doc.url, title: doc.title, text: doc.text});
  status('saved ' + r.entry.path, 'ok');
  leeOpenFile(r.entry.path);
}
function researchWorkspace(mode = 'search', value = '') {
  let activeMode = mode, docs = [], activeDoc = null, digest = '', query = value;
  const m = modal(`<div class="lee-mhead lee-research-head"><span>Research</span>` +
    `<span class="sub">search, read, and keep sources with the project</span></div>` +
    `<form class="lee-research-command"><div class="lee-segbar" aria-label="research mode">` +
    `<button type="button" class="lee-seg" data-mode="search">Search</button>` +
    `<button type="button" class="lee-seg" data-mode="read">Read URL</button>` +
    `<button type="button" class="lee-seg" data-mode="research">Research</button></div>` +
    `<input class="lee-input" id="researchquery" autocomplete="off">` +
    `<label class="lee-research-remember" title="Store fetched sources in durable memory"><input type="checkbox" id="researchremember" checked> remember</label>` +
    `<button class="lee-btn go" type="submit">Go</button></form>` +
    `<div class="lee-research-body"><aside class="lee-research-sources">` +
    `<div class="lee-research-section-label">Sources</div><div id="researchsources" class="lee-research-source-list">` +
    `<div class="lee-research-empty">Search the web or enter a URL to begin.</div></div></aside>` +
    `<main class="lee-research-reader"><div class="lee-research-reader-head"><div>` +
    `<strong id="researchtitle">Research workspace</strong><span id="researchmeta">Current sources stay visible while you read.</span></div>` +
    `<div class="lee-research-actions"><button class="lee-btn" data-new-thought>New note</button>` +
    `<button class="lee-btn" data-open disabled>Open webpage</button>` +
    `<button class="lee-btn" data-save disabled>Save Markdown</button><button class="lee-btn" data-notebook disabled>Make notebook</button>` +
    `<button class="lee-btn" data-memory-note disabled>Add to agent memory</button>` +
    `<button class="lee-btn" data-forget disabled>Forget</button><button class="lee-btn" data-ask disabled>Ask with sources</button></div></div>` +
    `<article id="researchreader" class="lee-research-content"><div class="lee-research-hero">` +
    `<span class="lee-research-mark">R</span><strong>Keep evidence close to the work.</strong>` +
    `<p>Read a source cleanly, save it into the project, or carry cited results into the assistant.</p></div></article></main></div>`);
  m.classList.add('lee-research-modal');
  const input = $('#researchquery', m), list = $('#researchsources', m), reader = $('#researchreader', m);
  const title = $('#researchtitle', m), meta = $('#researchmeta', m);
  const setMode = next => {
    activeMode = next;
    $$('[data-mode]', m).forEach(b => b.classList.toggle('active', b.dataset.mode === next));
    input.placeholder = next === 'read' ? 'https://example.com/article' :
      next === 'research' ? 'Research a question across several sources…' : 'Search the web…';
    input.focus();
  };
  const setBusy = text => {
    reader.innerHTML = `<div class="lee-research-loading"><span></span><span></span><span></span><p>${esc(text)}</p></div>`;
  };
  const setActions = doc => {
    $('[data-open]', m).disabled = !doc?.url;
    $('[data-save]', m).disabled = !doc;
    $('[data-notebook]', m).disabled = !doc?.url;
    $('[data-memory-note]', m).disabled = !doc?.text;
    $('[data-forget]', m).disabled = !doc?.memory_id;
    $('[data-ask]', m).disabled = !(docs.length || doc);
  };
  const showDoc = async doc => {
    activeDoc = doc; lee.lastDoc = doc;
    title.textContent = doc.title || doc.url || 'Source'; meta.textContent = doc.url || 'research digest';
    setActions(doc);
    if (!doc.text && doc.url) {
      setBusy('Reading and cleaning the source…');
      try {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/read?url=' + encodeURIComponent(doc.url) + '&remember=' + remember);
        if (!result.doc) throw new Error(result.note || 'No readable content');
        Object.assign(doc, result.doc); activeDoc = doc; lee.lastDoc = doc; setActions(doc);
      } catch (e) { reader.innerHTML = `<div class="lee-research-error"><strong>Could not read this source</strong><p>${esc(e.message || e)}</p>` +
        `<button class="lee-btn" data-open-fallback>Open the original webpage</button></div>`;
        $('[data-open-fallback]', reader).onclick = () => openWebpage(doc.url); return; }
    }
    reader.innerHTML = '';
    if ((doc.sections || []).length > 1) {
      const collection = document.createElement('div'); collection.className = 'lee-research-collection';
      doc.sections.forEach((section, i) => {
        const article = document.createElement('article'); article.className = 'lee-research-article';
        article.innerHTML = `<header><span>${String(i + 1).padStart(2, '0')}</span>` +
          `<strong>${esc(section.title || `Article ${i + 1}`)}</strong></header>`;
        const body = document.createElement('div'); body.className = 'lee-research-markdown';
        article.appendChild(body); collection.appendChild(article); renderMarkdown(body, section.text || '');
      });
      reader.appendChild(collection);
      meta.textContent = `${researchDomain(doc.url)} · ${doc.sections.length} articles · ` +
        `${doc.sections.reduce((n, x) => n + (x.text || '').length, 0).toLocaleString()} characters`;
    } else {
      const md = document.createElement('div'); md.className = 'lee-research-markdown'; reader.appendChild(md);
      renderMarkdown(md, doc.text || 'No readable content was returned.');
      meta.textContent = `${researchDomain(doc.url)} · ${(doc.text || '').length.toLocaleString()} characters`;
    }
  };
  const paintSources = () => {
    list.innerHTML = docs.length ? docs.map((doc, i) => `<button class="lee-research-source${doc === activeDoc ? ' active' : ''}" data-source="${i}">` +
      `<span class="lee-research-source-index">${String(i + 1).padStart(2, '0')}</span><span><strong>${esc(doc.title || doc.url)}</strong>` +
      `<small>${esc(researchDomain(doc.url))}</small></span></button>`).join('') :
      '<div class="lee-research-empty">No sources yet.</div>';
  };
  const run = async () => {
    query = input.value.trim(); if (!query) return;
    setBusy(activeMode === 'research' ? 'Reading and comparing the strongest sources…' : activeMode === 'read' ? 'Fetching the page…' : 'Searching the web…');
    try {
      if (activeMode === 'read') {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/read?url=' + encodeURIComponent(query) + '&remember=' + remember);
        if (!result.doc) throw new Error(result.note || 'No readable content');
        docs = [result.doc]; paintSources(); await showDoc(result.doc); paintSources();
      } else if (activeMode === 'research') {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/dig?q=' + encodeURIComponent(query) + '&remember=' + remember);
        docs = result.docs || []; digest = result.digest || '';
        const brief = {title: query, url: '', text: digest, kind: 'research'};
        paintSources(); await showDoc(brief); status(result.note, docs.length ? 'ok' : 'err');
      } else {
        const result = await api('/research/search?q=' + encodeURIComponent(query));
        docs = result.docs || []; activeDoc = null; paintSources();
        title.textContent = `${docs.length} results`; meta.textContent = result.note || query; setActions(null);
        reader.innerHTML = docs.length ? '<div class="lee-research-empty">Choose a source to open it in the reader.</div>' :
          '<div class="lee-research-error"><strong>No sources found</strong><p>Try a more specific query or switch to Research.</p></div>';
        status(result.note, docs.length ? 'ok' : 'err');
      }
    } catch (e) { reader.innerHTML = `<div class="lee-research-error"><strong>Research stopped</strong><p>${esc(e.message || e)}</p></div>`; status(e.message || String(e), 'err'); }
  };
  m.querySelector('.lee-research-command').onsubmit = e => { e.preventDefault(); run(); };
  m.querySelector('.lee-segbar').onclick = e => { const b = e.target.closest('[data-mode]'); if (b) setMode(b.dataset.mode); };
  list.onclick = e => { const b = e.target.closest('[data-source]'); if (!b) return; const doc = docs[+b.dataset.source]; showDoc(doc).then(paintSources); };
  $('[data-new-thought]', m).onclick = () => {
    activeDoc = {title: 'Research notes', url: '', text: '', kind: 'note'}; lee.lastDoc = activeDoc;
    title.textContent = 'New research note'; meta.textContent = 'Your Markdown scratchpad · save to the project or agent memory';
    reader.innerHTML = `<section class="lee-research-note-editor"><label>Title<input class="lee-input" data-thought-title value="Research notes"></label>` +
      `<div class="lee-research-note-cm"></div></section>`;
    const noteEditor = createEditor($('.lee-research-note-cm', reader), {doc: '# Notes\n\n', lang: 'markdown', lineNums: true,
      placeholder: 'Write observations, decisions, open questions, and links…', onChange: text => {
        activeDoc.text = text; setActions(activeDoc);
      }});
    activeDoc.text = LeeCM.getDoc(noteEditor); setActions(activeDoc);
    $('[data-thought-title]', reader).oninput = e => { activeDoc.title = e.target.value || 'Research notes'; };
    $('[data-thought-title]', reader).focus();
  };
  $('[data-open]', m).onclick = () => openWebpage(activeDoc?.url);
  $('[data-save]', m).onclick = () => activeDoc && saveDoc(activeDoc, 'markdown');
  $('[data-notebook]', m).onclick = () => activeDoc && saveDoc(activeDoc, 'notebook');
  $('[data-memory-note]', m).onclick = () => {
    if (!activeDoc?.text) return;
    const source = activeDoc.url ? `\n\nSource: ${activeDoc.url}` : '';
    const text = String(activeDoc.text || '').slice(0, 30_000) + source;
    m.remove(); leeNewMemoryNote({title: activeDoc.title || query || 'Research note', text});
    status('research added to a new memory note; edit and choose model routing before saving', 'ok');
  };
  $('[data-forget]', m).onclick = async () => {
    if (!activeDoc?.memory_id) return;
    if (!await confirmDialog('forget research source', `Remove ${activeDoc.title || activeDoc.url} from durable memory?`, 'forget')) return;
    await post('/memory/forget', {id: activeDoc.memory_id}); activeDoc.memory_id = '';
    setActions(activeDoc); lee.memoryLoaded = false; status('source removed from memory', 'ok');
  };
  $('[data-ask]', m).onclick = () => {
    const sources = docs.filter(d => d.url).map((d, i) => `[${i + 1}] ${d.title}: ${d.url}`).join('\n');
    const prompt = $('#agentprompt'); if (!prompt) return;
    prompt.value = `Research this question using these sources and cite them in the answer:\n\n${query || activeDoc?.title || ''}\n\n${sources}`;
    m.remove(); leePane('right', true); leeRight('agent'); prompt.focus(); status(`${docs.length} research sources added to the prompt`, 'ok');
  };
  setMode(mode); input.value = value;
  if (value) queueMicrotask(run);
  return m;
}
function webSearch() { return researchWorkspace('search'); }
function readUrl(url = '') { return researchWorkspace('read', url); }
function researchQ() { return researchWorkspace('research'); }


/* ---- clip: a file, a folder or the open tab into the workspace vault shelf ---- */
function clipTarget() {
  // Which menu opened decides the target. A tab names its path in `title`, so an inactive tab
  // read straight after right-clicking it does not have to wait for the select to land.
  const s = lee.menuSurface;
  if (s === 'file' || s === 'folder') return treeSel()?.dataset.path || '';
  if (s === 'tab') return $(`.lee-tab[data-i="${lee.menuTab}"]`)?.title || '';
  return treeSel()?.dataset.path || lee.path || '';
}
async function leeClipToVault() {
  const target = clipTarget();
  if (!target) return status('select a file, a folder or a tab to clip', 'err');
  leePane('right', true); leeRight('memory'); setMemoryView('vault');
  // The panel first, because the job card swaps into it. Both are ordinary htmx requests.
  await htmx.ajax('GET', '/vault/panel', {target: '#memorybody', swap: 'innerHTML'});
  await htmx.ajax('POST', '/clip?' + new URLSearchParams({target, kind: 'clip', origin: 'menu'}),
    {target: '#vaultjobs', swap: 'afterbegin'});
  status(`clipping ${target.split('/').pop() || target} into the vault…`);
}
window.leeClipToVault = leeClipToVault;
/* ------------------------------------------------------------------ overlays */
function modal(inner, onKey, onClose, options = {}) {
  const previousFocus = document.activeElement;
  const m = document.createElement('div');
  m.className = `lee-modal${options.className ? ' ' + options.className : ''}`;
  m.innerHTML = `<div class="lee-modalbox lee-modal-resizable" role="dialog" aria-modal="true" tabindex="-1">` +
                `<div class="lee-modal-grip" aria-hidden="true"></div>${inner}` +
                `<button class="lee-modal-expand" type="button" aria-label="expand dialog" title="expand dialog">↗</button>` +
                `<button class="lee-modal-close" type="button" aria-label="close dialog">×</button></div>`;
  const box = m.querySelector('.lee-modalbox');
  const heading = box.querySelector('.lee-mhead');
  if (heading) box.setAttribute('aria-label', heading.textContent.trim());
  const storageKey = options.storageKey ? `lee-modal-size:${options.storageKey}` : '';
  if (storageKey) {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (saved?.width) box.style.width = Math.min(saved.width, innerWidth - 16) + 'px';
      if (saved?.height) box.style.height = Math.min(saved.height, innerHeight - 16) + 'px';
      if (Number.isFinite(saved?.left) && Number.isFinite(saved?.top)) {
        m.classList.add('lee-modal-moved');
        box.style.left = Math.max(0, Math.min(saved.left, innerWidth - 80)) + 'px';
        box.style.top = Math.max(0, Math.min(saved.top, innerHeight - 48)) + 'px';
      }
    } catch (_) {}
  }
  // Result rows are true keyboard targets, not divs that only a mouse can activate.
  const prepareRows = root => $$('.lee-mrow', root).forEach(row => {
    row.tabIndex = row.dataset.off ? -1 : 0; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(row.classList.contains('sel')));
    const list = row.closest('.lee-modallist'); if (list && !list.hasAttribute('role')) list.setAttribute('role', 'listbox');
  });
  prepareRows(m);
  const observer = new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(n => {
    if (n instanceof Element) { if (n.matches('.lee-mrow')) prepareRows(n.parentElement); else prepareRows(n); }
  })));
  observer.observe(box, {childList: true, subtree: true});
  let closed = false;
  const nativeRemove = m.remove.bind(m);
  const focusables = () => $$('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', box)
    .filter(el => !el.hidden && el.getClientRects().length);
  const key = (e) => {
    // Nested dialogs (for example “change cwd” from the kernel picker) form a stack.
    // Only the top one owns keys; otherwise one Escape closes every layer at once.
    if ($$('.lee-modal').at(-1) !== m) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); m.remove(); return; }
    if (e.key === 'Tab') {
      const items = focusables(); if (!items.length) { e.preventDefault(); box.focus(); return; }
      const at = items.indexOf(document.activeElement);
      if (e.shiftKey && at <= 0) { e.preventDefault(); items.at(-1).focus(); }
      else if (!e.shiftKey && (at < 0 || at === items.length - 1)) { e.preventDefault(); items[0].focus(); }
      return;
    }
    if (onKey) onKey(e, m);
    if (e.defaultPrevented) return;
    const rows = $$('.lee-mrow:not([data-off])', m), at = rows.indexOf(document.activeElement);
    if (rows.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault(); e.stopPropagation();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      const next = rows[(Math.max(0, at) + step + rows.length) % rows.length];
      rows.forEach(r => { const selected = r === next; r.classList.toggle('sel', selected); r.setAttribute('aria-selected', String(selected)); });
      next.focus(); next.scrollIntoView({block: 'nearest'});
    } else if (at >= 0 && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault(); e.stopPropagation(); rows[at].click();
    }
  };
  m.remove = () => {
    if (closed) return;
    closed = true; observer.disconnect(); document.removeEventListener('keydown', key, true); nativeRemove();
    if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
    if (onClose) onClose();
  };
  const dragHandle = heading || m.querySelector('.lee-modal-grip');
  let drag = null;
  dragHandle.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button, input, textarea, select, a') || m.classList.contains('lee-modal-expanded')) return;
    const r = box.getBoundingClientRect();
    m.classList.add('lee-modal-moved', 'lee-modal-dragging');
    box.style.left = r.left + 'px'; box.style.top = r.top + 'px';
    drag = {x: e.clientX, y: e.clientY, left: r.left, top: r.top, dx: 0, dy: 0};
    dragHandle.setPointerCapture(e.pointerId); e.preventDefault();
  });
  dragHandle.addEventListener('pointermove', e => {
    if (!drag) return;
    const r = box.getBoundingClientRect(), width = r.width, height = r.height;
    const maxX = Math.max(0, innerWidth - width) - drag.left;
    const maxY = Math.max(0, innerHeight - height) - drag.top;
    drag.dx = Math.max(-drag.left, Math.min(e.clientX - drag.x, maxX));
    drag.dy = Math.max(-drag.top, Math.min(e.clientY - drag.y, maxY));
    box.style.transform = `translate3d(${drag.dx}px, ${drag.dy}px, 0)`;
    e.preventDefault();
  });
  const endDrag = e => {
    if (!drag) return;
    box.style.left = Math.max(0, drag.left + drag.dx) + 'px'; box.style.top = Math.max(0, drag.top + drag.dy) + 'px';
    box.style.transform = ''; drag = null; m.classList.remove('lee-modal-dragging');
    try { dragHandle.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  dragHandle.addEventListener('pointerup', endDrag); dragHandle.addEventListener('pointercancel', endDrag);
  const toggleExpanded = () => {
    const expanding = !m.classList.contains('lee-modal-expanded');
    if (expanding) {
      box._leeRestorePosition = m.classList.contains('lee-modal-moved')
        ? {left: box.style.left, top: box.style.top} : null;
      m.classList.remove('lee-modal-moved'); box.style.left = box.style.top = box.style.transform = '';
      m.classList.add('lee-modal-expanded');
    } else {
      m.classList.remove('lee-modal-expanded');
      if (box._leeRestorePosition) {
        m.classList.add('lee-modal-moved'); box.style.left = box._leeRestorePosition.left; box.style.top = box._leeRestorePosition.top;
      }
    }
    const expanded = m.classList.contains('lee-modal-expanded');
    m.querySelector('.lee-modal-expand').textContent = expanded ? '↙' : '↗';
    m.querySelector('.lee-modal-expand').setAttribute('aria-label', expanded ? 'restore dialog' : 'expand dialog');
  };
  m.querySelector('.lee-modal-expand').onclick = toggleExpanded;
  heading?.addEventListener('dblclick', e => { if (!e.target.closest('button, input, select')) toggleExpanded(); });
  if (storageKey && 'ResizeObserver' in window) {
    const sizeObserver = new ResizeObserver(() => {
      if (m.classList.contains('lee-modal-expanded')) return;
      const r = box.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) localStorage.setItem(storageKey, JSON.stringify({width: Math.round(r.width), height: Math.round(r.height), left: Math.round(r.left), top: Math.round(r.top)}));
    });
    sizeObserver.observe(box);
    const oldRemove = m.remove;
    m.remove = () => { sizeObserver.disconnect(); oldRemove(); };
  }
  m.querySelector('.lee-modal-close').onclick = () => m.remove();
  m.addEventListener('mousedown', e => { if (e.target === m) m.remove(); });
  document.addEventListener('keydown', key, true);
  document.body.appendChild(m);
  requestAnimationFrame(() => {
    const target = box.querySelector('[autofocus]') || box.querySelector('.lee-mrow.sel:not([data-off])') ||
                   box.querySelector('.lee-mrow:not([data-off])') || box.querySelector('input, textarea, select') ||
                   box.querySelector('button:not(.lee-modal-close):not([disabled])') || box;
    target.focus({preventScroll: true});
    if (target.classList.contains('lee-mrow')) target.scrollIntoView({block: 'nearest'});
  });
  return m;
}

function inputDialog(title, label, value = '', placeholder = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(
      `<form class="lee-dialogform"><div class="lee-mhead">${esc(title)}</div>` +
      `<label class="lee-fieldlabel">${esc(label)}<input class="lee-input" id="dialoginput" ` +
      `placeholder="${esc(placeholder)}" autocomplete="off"></label>` +
      `<div class="lee-mfoot"><button class="lee-btn go" type="submit">confirm</button>` +
      `<button class="lee-btn" type="button" id="dialogcancel">cancel</button></div></form>`,
      null, () => { if (!settled) { settled = true; resolve(null); } });
    const input = m.querySelector('#dialoginput'); input.value = value;
    m.querySelector('form').onsubmit = e => { e.preventDefault(); done(input.value.trim()); };
    m.querySelector('#dialogcancel').onclick = () => done(null);
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

function textDialog(title, label, value = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(
      `<form class="lee-dialogform"><div class="lee-mhead">${esc(title)}</div>` +
      `<label class="lee-fieldlabel">${esc(label)}<textarea class="lee-keyedit" id="dialogtext" rows="12" spellcheck="false"></textarea></label>` +
      `<div class="lee-mfoot"><button class="lee-btn go" type="submit">retry</button>` +
      `<button class="lee-btn" type="button" id="dialogcancel">cancel</button></div></form>`,
      null, () => { if (!settled) { settled = true; resolve(null); } });
    const input = m.querySelector('#dialogtext'); input.value = value;
    m.querySelector('form').onsubmit = e => { e.preventDefault(); done(input.value.trim()); };
    m.querySelector('#dialogcancel').onclick = () => done(null);
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

function confirmDialog(title, detail, action = 'confirm') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(`<div class="lee-mhead">${esc(title)}</div><div class="lee-dialogcopy">${esc(detail)}</div>` +
      `<div class="lee-mfoot"><button class="lee-btn warn" id="dialogyes">${esc(action)}</button>` +
      `<button class="lee-btn" id="dialogno" autofocus>cancel</button></div>`, null,
      () => { if (!settled) { settled = true; resolve(false); } });
    m.querySelector('#dialogyes').onclick = () => done(true);
    m.querySelector('#dialogno').onclick = () => done(false);
  });
}

/* One menu renderer for every contextual surface. Labels and effective chords came from
 * leela.blocks.keys.menus + leela.core.keys; the browser only positions rows and dispatches their action. */
function closeMenu() { $('.lee-ctxmenu')?.remove(); }
function openMenu(surface, x, y) {
  closeMenu();
  lee.menuSurface = surface;   // an action can act on what was right-clicked, not on the focus
  const rows = lee.menus?.[surface] || [];
  if (!rows.length) return;
  const menu = document.createElement('div');
  menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu'); menu.tabIndex = -1;
  menu.innerHTML = rows.map(r => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem ${esc(r.kind)}" role="menuitem" data-action="${esc(r.action)}">` +
    `<span>${esc(r.label)}</span>${r.chord && r.chord !== '—' ? `<kbd>${esc(displayChord(r.chord))}</kbd>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(x, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(y, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => { const item = e.target.closest('.lee-menuitem'); if (!item) return; closeMenu(); leeAct(item.dataset.action); };
  menu.onkeydown = e => {
    const items = $$('.lee-menuitem', menu), at = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); items.at(-1)?.focus(); }
  };
  menu.focus();
}
function leeMenuAt(surface, anchor) {
  const r = anchor.getBoundingClientRect(); openMenu(surface, r.right - 4, r.bottom + 3);
}
window.leeMenuAt = leeMenuAt;

function openChromeMenu(anchor, rows) {
  closeMenu();
  const menu = document.createElement('div'); menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu');
  menu.innerHTML = rows.map((r, i) => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem${r.warn ? ' warn' : ''}" role="menuitem" data-i="${i}" ${r.disabled ? 'disabled' : ''}>` +
    `<span>${esc(r.label)}</span>${r.detail ? `<small>${esc(r.detail)}</small>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const a = anchor.getBoundingClientRect(), rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(a.left, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(a.bottom + 3, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => { const b = e.target.closest('[data-i]'); if (!b || b.disabled) return; closeMenu(); rows[+b.dataset.i].run?.(); };
  menu.tabIndex = -1; menu.focus();
}

// Choosing a folder is choosing a project: source control, releases, deploys and the branch
// pill all follow it. Selecting the folder in the tree without saying so left every one of
// them describing whichever folder had been opened first.
async function activateRoot(path) {
  try { await post('/workspace/activate', {path}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  leeLeft('files');
  const node = $$('.lee-root').find(n => n.dataset.path === path);
  if (node) { selectTreeNode(node); await loadTreeDir(node); node.scrollIntoView({block: 'nearest'}); }
  gitUI.repo = '';                  // the panels follow the workspace again, not a pinned repo
  refreshProjectPills();
  projectChanged();
  status(`project · ${path.split('/').pop() || path}`);
}
window.leeActivateRoot = activateRoot;

async function leeWorkspaceMenu(anchor) {
  const d = await api('/workspace/info');
  const sites = d.workspaces || [];
  const rows = sites.map(site => ({label: site.name, detail: site.root, run: () => {
    if (site.url && site.url !== location.href) location.href = site.url;
  }}));
  if (sites.length && (d.roots || []).length) rows.push({separator: true});
  rows.push(...(d.roots || []).map(root => ({label: sites.length ? `Folder: ${root.name}` : root.name,
    detail: root.path, run: () => activateRoot(root.path)})));
  if (rows.length) rows.push({separator: true});
  rows.push({label: 'Add folder…', detail: 'to this workspace', run: addRoot});
  openChromeMenu(anchor, rows);
}
window.leeWorkspaceMenu = leeWorkspaceMenu;

/* The branch pill's own popup is `28_branchbar.js`: it is a searchable list of branches and
   actions rather than a menu, so it does not fit `openChromeMenu`. */

async function operationHistory() {
  const d = await api('/history/operations');
  const m = modal(`<div class="lee-mhead">workspace history<span class="sub">saved file checkpoints · newest first</span></div>` +
    // An empty `data-history` still matches `[data-history]`, so the attribute is omitted
    // rather than blanked: a spent operation must not be clickable at all.
    `<div class="lee-modallist">${(d.operations || []).map(op => `<button class="lee-mrow" data-op="${esc(op.id)}"${op.reversible ? ' data-history="undo"' : op.redoable ? ' data-history="redo"' : ' data-off="1"'}>` +
      `<strong>${esc(op.label)}</strong><span class="sub">${op.redoable ? 'undone · redo available · ' : ''}${new Date(op.at * 1000).toLocaleString()} · ${esc((op.paths || []).join(', '))}</span></button>`).join('') || '<div class="lee-dim">No saved operations yet.</div>'}</div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Undo and redo refuse files changed after the checkpoint.</span></div>`);
  $$('[data-history]', m).forEach(row => row.onclick = async () => {
    const redo = row.dataset.history === 'redo', verb = redo ? 'Redo' : 'Undo';
    if (!await confirmDialog(`${verb} workspace operation`, `${verb} ${row.textContent.trim()}?`, verb.toLowerCase())) return;
    try { const r = await post('/history/' + (redo ? 'redo' : 'undo'), {id: row.dataset.op}); m.remove();
      if ((r.operation.resources || []).some(x => x.path === lee.path)) await takeDiskVersion(lee.path);
      status(`workspace operation ${redo ? 'redone' : 'undone'}`, 'ok'); refreshFileTree(undefined, false);
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}

function leeToolsMenu(anchor) {
  openChromeMenu(anchor, [
    {label: 'Command palette', detail: displayChord('mod+shift+p'), run: () => leeAct('palette')},
    {label: 'Recent files', detail: displayChord('mod+e'), run: () => leeAct('recent_tabs')},
    {separator: true},
    {label: 'Research workspace…', run: () => leeAct('research')},
    {label: 'Read webpage…', run: () => leeAct('read_url')},
    {label: 'Kernel and interpreter…', run: () => leeAct('pick_kernel')},
    {label: 'Working directory…', run: leeCwd},
    {label: 'nbdev prepare…', detail: 'uv + settings.ini', run: leeNbdevPrepare},
    {separator: true},
    {label: 'Settings…', detail: displayChord(lee.keys.find(k => k.action === 'settings')?.key || 'mod+,'), run: editorSettings},
    {label: 'Workspace history…', detail: 'conflict-safe undo', run: operationHistory},
    {label: 'Keybindings…', run: () => leeAct('edit_keys')},
    {label: 'Terminal', run: () => leeAct('terminal')},
  ]);
}
window.leeToolsMenu = leeToolsMenu;

function leeEditorMenu(anchor) {
  const rows = [
    {label: 'Run selection', detail: displayChord(lee.keys.find(k => k.action === 'run_selection')?.key || ''), run: () => leeAct('run_selection')},
    {label: 'Run all cells', detail: displayChord(lee.keys.find(k => k.action === 'run_all')?.key || ''), run: () => leeAct('run_all')},
    {label: 'Restart and run all', run: () => leeAct('restart_run_all')},
    {separator: true},
    {label: 'Save', detail: displayChord(lee.keys.find(k => k.action === 'save')?.key || ''), run: () => leeAct('save')},
    {label: 'Show unsaved changes', run: () => leeAct('show_diff')},
    {label: 'Rename symbol…', run: () => leeAct('rename_symbol')},
    {label: 'Replace in workspace…', run: () => leeAct('replace_workspace')},
    {separator: true},
    {label: 'Insert cell below', run: () => leeAct('cell_below')},
    {label: 'Change cell type', run: () => leeAct('cell_type')},
    {label: 'Clear all outputs', run: () => leeAct('clear_all_outputs')},
    {separator: true},
    {label: 'All commands…', detail: displayChord(lee.keys.find(k => k.action === 'palette')?.key || ''), run: () => leeAct('palette')},
  ];
  openChromeMenu(anchor, rows);
}
window.leeEditorMenu = leeEditorMenu;

function leeDebugMenu(anchor) {
  openChromeMenu(anchor, [
    {label:'Debug current Python file',detail:'debugpy',disabled:lee.kind!=='text'||curLang()!=='python',run:()=>startDirectDebug({name:lee.path?.split('/').pop()||'Python',program:lee.path,debug:true})},
    {label:'Run or debug configuration…',run:()=>leeAct('run_app')},
    {label:'Edit configurations…',run:editRuns},
    {separator:true},
    {label:'Continue',disabled:!lee.debugState,run:()=>leeDebugControl('continue')},
    {label:'Step over',disabled:!lee.debugState,run:()=>leeDebugControl('next')},
    {label:'Step into',disabled:!lee.debugState,run:()=>leeDebugControl('stepIn')},
    {label:'Step out',disabled:!lee.debugState,run:()=>leeDebugControl('stepOut')},
    {label:'Stop debugger',warn:true,disabled:!lee.debugCell&&!lee.directDebug,run:leeDebugStop},
    {separator:true},
    {label:'Interrupt kernel',warn:true,run:()=>leeAct('interrupt')},
    {label:'Restart kernel',warn:true,run:()=>leeAct('restart')},
  ]);
}
window.leeDebugMenu = leeDebugMenu;

document.addEventListener('pointerdown', e => { if (!e.target.closest('.lee-ctxmenu, .lee-more')) closeMenu(); }, true);
window.addEventListener('blur', closeMenu);
window.addEventListener('resize', () => { closeMenu(); layoutTabs(); });
window.addEventListener('scroll', closeMenu, true);

function showHelp() {
  const scopes = Object.entries(lee.help).sort(([a], [b]) =>
    a === lee.scope ? -1 : b === lee.scope ? 1 : a === 'global' ? -1 : b === 'global' ? 1 : 0);
  const body = scopes.map(([scope, rows]) =>
    `<section class="lee-help-scope${scope === lee.scope ? ' active' : ''}"><h4>${esc(scope)}` +
    `${scope === lee.scope ? '<span>current</span>' : ''}</h4>` + rows.map(([k, l]) =>
      `<div class="lee-krow"><kbd>${esc(displayChord(k))}</kbd><span>${esc(l)}</span></div>`).join('') + '</section>').join('');
  const m = modal(
    `<div class="lee-mhead">keys<span class="sub">${esc(lee.keyPath || '')}</span></div>` +
    (lee.keyNotes || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('') +
    `<div class="lee-dim">every one of these can be rebound, and every one of them also has a ` +
    `button — nothing here is reachable only by a chord.</div>` +
    `<div class="lee-help">${body}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gokeys">edit keybindings</button></div>`);
  m.querySelector('#gokeys').onclick = () => { m.remove(); editKeys(); };
}

async function quickOpen(searchMode) {
  const d = await api('/fs/find');
  let hits = d.hits, sel = 0;
  const m = modal(
    `<input class="lee-input" id="qo" placeholder="${searchMode ? 'search files…' : 'open file…'}" autofocus>
     <div class="lee-modallist" id="qolist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#qolist'), input = m.querySelector('#qo');
  const paint = () => {
    list.innerHTML = hits.slice(0, 300).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.path)}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); leeOpenFile(h.path); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  input.addEventListener('input', async () => {
    const q = input.value.trim();
    hits = (await api('/fs/find?q=' + encodeURIComponent(q))).hits; sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

// The modes, in the order Tab walks them. `all` leads and is the default: it ranks every backend
// together, so it is the one that answers without you having to know which store the thing you
// half-remember is in. A rail rather than a row because each one carries a count, and a count is
// the thing that tells you where to look next when the mode you picked came back empty.
const SEARCH_MODES = [
  ['all', 'all', 'rank ripgrep, symbols, FTS and semantic results together'],
  ['rg', 'rg', 'ripgrep: literal search over current files, fastest'],
  ['context', 'context', 'Kosha composed retrieval across repository code and installed packages'],
  ['repo', 'repo', 'Kosha repository code store'],
  ['env', 'packages', 'Kosha installed-package environment store'],
  ['symbols', 'symbols', 'Kosha symbols: repository and indexed packages'],
  ['ann', 'ANN', 'Kosha embedding ANN'],
];

async function codeSearch() {
  let hits = [], sel = 0, backend = '', previewView = null, searchSeq = 0;
  let mode = localStorage.getItem('lee-search-mode') || 'all';
  if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all';
  const counts = {};
  const m = modal(
    `<div class="lee-searchbar"><input class="lee-input" id="cs" placeholder="search code, symbols and meaning…" autofocus>
     <button class="lee-btn" id="kosharefresh" type="button">sync</button></div>` +
    // Where and what, beside which backend. A workspace holds several checkouts, so "this
    // project" is the useful default and "everything open" is the deliberate widening.
    `<div class="lee-searchfilters">
       <label>in<select id="csscope">
         <option value="project">this project</option>
         <option value="workspace">every open folder</option></select></label>
       <label>files<input class="lee-input" id="csexts" placeholder="py, ts — blank for all"
              aria-label="restrict to file extensions"></label>
       <span class="lee-dim" id="csscopenote"></span></div>` +
    `<div class="lee-kosha-status" id="koshastatus"><span>Opening Kosha…</span></div>
     <div class="lee-code-search-body">
       <nav class="lee-searchrail" id="csrail" aria-label="search mode">${SEARCH_MODES.map(([id, label, tip]) =>
         `<button class="lee-searchrail-mode" data-mode="${id}" title="${esc(tip)}">` +
         `<span>${esc(label)}</span><b data-count-for="${id}"></b></button>`).join('')}
         <span class="lee-dim lee-searchrail-hint">tab / shift+tab</span></nav>
       <div class="lee-modallist" id="cslist"><div class="lee-dim">type to search repository + environment context</div></div>
       <aside class="lee-search-preview"><header><div><strong id="cspreviewtitle">Code preview</strong>` +
       `<span id="cspreviewmeta">Select a result</span></div><button class="lee-btn go" id="csopen" disabled>Open file</button></header>` +
       `<div id="cspreview"><div class="lee-search-preview-empty">Matches open here with syntax highlighting.</div></div>` +
       `<div class="lee-search-relations" id="csrelations"></div></aside></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
      // Tab walks the modes rather than the focus. The dialog traps Tab anyway, so the only
      // thing given up is a focus order over four controls, and what is bought is trying the
      // same query against another backend without leaving the keyboard.
      else if (e.key === 'Tab') { e.preventDefault(); cycleMode(e.shiftKey ? -1 : 1); }
    }, () => {
      if (previewView) LeeCM.destroy(previewView);
      // Closing the dialog must stop the search too, or four backends go on working for a
      // question whose answer has nowhere left to be drawn.
      if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    });
  m.classList.add('lee-code-search-modal');
  const list = $('#cslist', m), input = $('#cs', m), preview = $('#cspreview', m), open = $('#csopen', m);
  const scopeEl = $('#csscope', m), extsEl = $('#csexts', m);
  // Remembered, because a person who works in Python does not want to retype `py` every time
  // they open this box -- and the scope they chose is a statement about how they work.
  scopeEl.value = localStorage.getItem('lee-search-scope') || 'project';
  extsEl.value = localStorage.getItem('lee-search-exts') || '';
  const paintRail = () => {
    $$('.lee-searchrail-mode', m).forEach(b =>
      b.classList.toggle('active', b.dataset.mode === mode));
    // A count only means something once that mode has actually run. Blank is "not asked yet",
    // which is a different thing from nought and must not look like it.
    SEARCH_MODES.forEach(([id]) => {
      const el = $(`[data-count-for="${id}"]`, m); if (!el) return;
      el.textContent = counts[id] == null ? '' : counts[id];
      el.classList.toggle('zero', counts[id] === 0);
    });
  };
  const setMode = next => {
    if (!next || next === mode) return;
    mode = next; localStorage.setItem('lee-search-mode', mode);
    paintRail();
    if (input.value.trim()) search(); else paint();
    input.focus();
  };
  const cycleMode = step => {
    const at = SEARCH_MODES.findIndex(([id]) => id === mode);
    const next = SEARCH_MODES[(at + step + SEARCH_MODES.length) % SEARCH_MODES.length];
    setMode(next[0]);
  };
  const showPreview = () => {
    if (previewView) { LeeCM.destroy(previewView); previewView = null; }
    const h = hits[sel];
    if (!h) {
      preview.innerHTML = '<div class="lee-search-preview-empty">No result selected.</div>';
      open.disabled = true; return;
    }
    const filename = h.path.split('/').pop() || h.package || 'indexed source';
    $('#cspreviewtitle', m).textContent = h.symbol || filename;
    $('#cspreviewmeta', m).textContent = `${h.package ? h.package + ' · ' : ''}${filename}:${h.line} · ${(h.sources || [h.kind]).join(' + ')}`;
    const environment = h.kind.startsWith('env-');
    open.disabled = environment && !h.package;
    open.textContent = environment ? (h.package ? 'Package API' : 'Indexed package') : 'Open file';
    preview.innerHTML = '<div class="lee-search-preview-editor"></div>';
    previewView = mountCodeSurface($('.lee-search-preview-editor', preview), h.text || '(no indexed preview)',
                                   codeLang('', h.path), false);
    const relations = $('#csrelations', m), callers = h.callers || [];
    relations.innerHTML = callers.length ? `<span>called by</span>` + callers.map(name =>
      `<button data-symbol="${esc(name)}">${esc(name.split('.').pop())}</button>`).join('') : '';
    // Following a caller is a graph question, so it switches to the mode that answers one.
    $$('[data-symbol]', relations).forEach(button => button.onclick = () => {
      input.value = button.dataset.symbol;
      if (mode === 'context') search(); else setMode('context');
    });
  };
  const paint = () => {
    if (!hits.length) {
      list.innerHTML = `<div class="lee-dim">${backend ? 'no matches · ' + esc(backend) : 'type to search'}</div>`;
      showPreview(); return;
    }
    list.innerHTML = hits.map((h, i) => {
      const f = h.path.split('/').pop() || h.package || 'environment';
      const foundBy = (h.sources || [h.kind]).join(' + ');
      return `<button class="lee-search-result${i === sel ? ' sel' : ''}" data-i="${i}">` +
        `<span class="lee-search-result-kind">${esc(h.kind.startsWith('env-') ? 'PKG' : h.symbol ? 'SYM' : 'TXT')}</span>` +
        `<span><strong>${esc(h.symbol || h.text.split('\n')[0].slice(0, 90))}</strong>` +
        `<small>${esc(h.package ? h.package + ' · ' : '')}${esc(f)}:${h.line}</small></span>` +
        `<em>${esc(foundBy)}</em></button>`;
    }).join('');
    $('.lee-search-result.sel', list)?.scrollIntoView({block: 'nearest'}); showPreview();
  };
  const go = async () => {
    const h = hits[sel]; if (!h) return;
    if (h.kind.startsWith('env-')) {
      if (!h.package) return status('package source is indexed read-only', 'info');
      const d = await api('/code/package-api?package=' + encodeURIComponent(h.package));
      const box = modal(`<div class="lee-mhead">${esc(h.package)}<span class="sub">public API from Kosha</span></div>` +
        `<div class="lee-package-api"></div>`);
      const body = $('.lee-package-api', box), symbols = d.symbols || [];
      body.innerHTML = symbols.length ? symbols.map(row => `<button data-name="${esc(row.mod_name || '')}">` +
        `<strong>${esc(row.mod_name || '')}</strong><span>${esc(row.docstring || '')}</span></button>`).join('') :
        '<div class="lee-dim">No exported API metadata found.</div>';
      $$('[data-name]', body).forEach(row => row.onclick = () => { box.remove(); input.value = row.dataset.name; search(); });
      return;
    }
    m.remove(); openLocation(h);
  };
  // One click opens at the line, because that is what the box is *for*. It used to select on the
  // first click and need a second one on the same row to go anywhere, so the obvious gesture
  // landed in a preview pane and looked like the result was not clickable. The preview is still
  // reachable without committing: arrow keys move the selection and paint it.
  list.onclick = e => {
    const row = e.target.closest('[data-i]'); if (!row) return;
    sel = +row.dataset.i; paint(); go();
  };
  open.onclick = go;
  // `all` streamed: one section per backend, in the server's best-first leg order, each filling
  // in as that backend reports. Slots are stable on purpose -- rg answers in tens of milliseconds
  // and the embedding leg in seconds, and a list that re-ranked on every arrival would reshuffle
  // under the cursor precisely while someone was reading it. A hit a later leg finds again is not
  // shown twice; it adds its name to the row the first leg already produced, which is the same
  // merge the batch answer does.
  const streamAll = (q, seq) => new Promise(resolve => {
    const slots = new Map(), seen = new Map();
    let notes = [];
    const es = new EventSource('/search/stream?q=' + encodeURIComponent(q) +
                               '&scope=' + encodeURIComponent(scopeEl.value) +
                               '&exts=' + encodeURIComponent(extsEl.value.trim()));
    // Held so the next keystroke can close it. A stream left open keeps four backends working on
    // a question nobody is asking any more, and the server only notices when it next tries to
    // write -- which for the slow legs is seconds away.
    liveStream = es;
    const stop = () => { try { es.close(); } catch {} if (liveStream === es) liveStream = null; resolve(); };
    const recount = () => {
      hits = [];
      for (const leg of slots.keys()) hits.push(...slots.get(leg));
      counts.all = hits.length; paintRail();
    };
    es.addEventListener('start', e => {
      const d = JSON.parse(e.data);
      for (const leg of d.legs || []) slots.set(leg, []);      // fixes the order once
      const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
      $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
    });
    es.addEventListener('leg', e => {
      if (seq !== searchSeq) return stop();
      const d = JSON.parse(e.data);
      if (d.note) notes.push(d.note);
      const kept = [];
      for (const h of d.hits || []) {
        const key = `${h.path}:${h.line}:${h.package || ''}`;
        const already = seen.get(key);
        if (already) { already.sources = [...new Set([...(already.sources || []), d.leg])]; continue; }
        seen.set(key, h); kept.push(h);
      }
      slots.set(d.leg, kept);
      recount();
      backend = `all · ${[...slots.keys()].filter(k => slots.get(k).length).join(' + ') || 'searching'}`;
      // The selection is an index into a list that just grew at the end, so it still points at
      // the row it pointed at. Only an empty list needs resetting.
      if (sel >= hits.length) sel = Math.max(0, hits.length - 1);
      paint();
    });
    es.addEventListener('done', e => {
      if (notes.length) backend += ' · ' + notes.slice(0, 2).join('; ');
      paint(); stop();
    });
    es.onerror = () => { backend = backend || 'search stream failed'; paint(); stop(); };
  });

  let timer, liveStream = null;
  const search = () => {
    clearTimeout(timer); const seq = ++searchSeq;
    if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { hits = []; backend = ''; paint(); return; }
      if (mode === 'all') {
        hits = []; sel = 0; backend = 'all · searching';
        list.innerHTML = `<div class="lee-search-progress"><span></span>every backend, fastest first…</div>`;
        return streamAll(q, seq);
      }
      list.innerHTML = `<div class="lee-search-progress"><span></span>searching ${esc(mode === 'context' ? 'Kosha repo + environment context' : mode === 'all' ? 'rg, symbols, FTS and ANN' : mode)}…</div>`;
      try {
        const d = await api('/search?q=' + encodeURIComponent(q) + '&mode=' + mode +
                            '&scope=' + encodeURIComponent(scopeEl.value) +
                            '&exts=' + encodeURIComponent(extsEl.value.trim()));
        if (seq !== searchSeq) return;
        hits = d.hits || []; backend = d.backend + (d.note ? ' · ' + d.note : ''); sel = 0;
        // Which folders were actually walked, because "no matches" and "no matches *here*" are
        // different answers and only one of them means the thing is not in your code.
        const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
        $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
        counts[mode] = hits.length; paintRail();
        paint(); status(`search: ${d.backend}${d.note ? ' — ' + d.note : ''}`);
      } catch (e) {
        if (seq !== searchSeq) return;
        hits = []; backend = e.message || String(e); paint(); status(backend, 'err');
      }
    }, mode === 'rg' ? 120 : mode === 'all' || mode === 'context' ? 360 : 280);
  };
  input.addEventListener('input', search);
  scopeEl.addEventListener('change', () => {
    localStorage.setItem('lee-search-scope', scopeEl.value);
    if (input.value.trim()) search();
  });
  extsEl.addEventListener('input', () => {
    localStorage.setItem('lee-search-exts', extsEl.value.trim());
    if (input.value.trim()) search();
  });
  api('/code/status').then(d => {
    const el = $('#koshastatus', m); if (!el) return;
    el.innerHTML = d.ok ? `<span class="ok">Kosha connected</span><span>${Number(d.files || 0).toLocaleString()} files</span>` +
      `<span>${Number(d.packages || 0).toLocaleString()} packages</span><span>${Number(d.graph_nodes || 0).toLocaleString()} graph nodes</span>` +
      `${d.stale_files ? `<span class="warn">${d.stale_files} stale files</span>` : ''}` : `<span class="warn">${esc(d.note || 'Kosha unavailable')}</span>`;
  }).catch(() => {});
  $('#kosharefresh', m).onclick = async () => {
    const button = $('#kosharefresh', m); button.disabled = true; button.textContent = 'syncing…';
    try { await post('/code/sync'); button.textContent = 'synced'; status('Kosha code, notebooks and graph synced', 'ok'); if (input.value.trim()) search(); }
    catch (e) { button.textContent = 'retry sync'; status(e.message || String(e), 'err'); }
    finally { button.disabled = false; }
  };
  $('#csrail', m).onclick = e => {
    const b = e.target.closest('[data-mode]'); if (!b) return;
    e.preventDefault(); setMode(b.dataset.mode);
  };
  paintRail();
  setTimeout(() => input.focus(), 0);
}

function cursorWord() {
  const v = curEditor(); return v ? LeeCM.wordAtCursor(v) : '';
}
async function findDefinition(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  const d = await api('/code/definition?name=' + encodeURIComponent(name) + '&path=' + encodeURIComponent(lee.path || ''));
  if (!(d.hits || []).length) return status(`no definition found for ${name}`, 'err');
  if (d.hits.length === 1) return openLocation(d.hits[0]);
  hitList(d.hits, `${d.backend} — ${d.note}`, `definitions of ${name}`, openLocation);
}
async function findUsages(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  const d = await api('/code/usages?name=' + encodeURIComponent(name));
  hitList(d.hits || [], `${d.backend} — ${d.note}`, `usages of ${name}`, openLocation);
}
async function renameSymbol() {
  const name=cursorWord(),view=curEditor();
  if(!name||!view||!lee.path||curLang()!=='python')return status('put the cursor on a Python symbol first','err');
  const next=await inputDialog('rename symbol','New name',name,'valid Python identifier');
  if(!next||next===name)return;
  const pos=LeeCM.cursor(view),line=view.state.doc.lineAt(pos),character=pos-line.from;
  try{
    const preview=await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next});
    if(!preview.files?.length)return status('Pyright found no rename edits','err');
    const summary=preview.files.map(f=>`${f.path.split('/').pop()} · ${f.edits} edit${f.edits===1?'':'s'}`).join('\n');
    if(!await confirmDialog('Rename across workspace',`${name} → ${next}\n\n${summary}`,'rename'))return;
    await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next,apply:true});
    await post('/tab/reload',{path:lee.path});await mountTab();refreshFileTree(undefined,false);status(`renamed ${name} to ${next}`,'ok');
  }catch(e){status(e.message||String(e),'err');}
}

async function syncCodeIndex() {
  status('syncing Kosha index, notebooks and call graph…');
  const d = await post('/code/sync'); status(d.note || 'Kosha index synced', d.ok ? 'ok' : 'err');
}

async function leeSymbols() {
  const host = $('#symbols'), label = $('#symbolfile'); if (!host) return;
  const name = compactPath(lee.path || ''); if (label) label.textContent = name ? '· ' + name : '';
  // Notebooks are included: their defs and classes are real structure, and the server reads
  // them out of the cells rather than out of the JSON. The outline is of the file on disk, so
  // a def typed and not yet saved appears once autosave has run.
  if (!lee.path || (lee.kind !== 'text' && lee.kind !== 'notebook')) {
    host.innerHTML = '<div class="lee-dim">Open a source file or notebook to see its symbols.</div>'; return;
  }
  host.innerHTML = '<div class="lee-symbol-loading">Reading structure…</div>';
  try {
    const d = await api('/outline?path=' + encodeURIComponent(lee.path));
    const rows = d.symbols || [];
    host.innerHTML = rows.length ? rows.map((s, i) => {
      const depth = Math.max(0, Math.floor(Number(s.score || 0) / 4));
      const kind = /^class\s/.test(s.text || '') ? 'class' : 'function';
      // A notebook symbol is addressed by cell, and the JSON line it also carries would be a
      // meaningless number to show: the row says which cell and where in it instead.
      const cellLine = Number(s.cell_line || 0), cellIndex = Number(s.cell_index ?? -1);
      const where = cellLine > 0 ? `${cellIndex + 1}:${cellLine}` : String(Number(s.line || 1));
      return `<button class="lee-symbol-row" role="treeitem" style="--depth:${depth}" ` +
        `data-line="${Number(s.line || 1)}" data-cell="${esc(s.cell || '')}" ` +
        `data-cell-index="${cellIndex}" data-cell-line="${cellLine}">` +
        `<span class="lee-symbol-kind">${kind === 'class' ? 'C' : 'ƒ'}</span>` +
        `<span>${esc(s.symbol)}</span><small>${esc(where)}</small></button>`;
    }).join('') : '<div class="lee-dim">No functions or classes in this file.</div>';
    $$('.lee-symbol-row', host).forEach(row => row.onclick = () => {
      openLocation({path: lee.path, line: +row.dataset.line, cell: row.dataset.cell,
                    cell_index: +row.dataset.cellIndex, cell_line: +row.dataset.cellLine});
      if (matchMedia('(max-width: 1100px)').matches) leePane('left', false);
    });
  } catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.leeSymbols = leeSymbols;

/* ---- similarity: what else in this codebase looks like the thing under the cursor ---- */
function cursorLine() {
  if (lee.kind === 'notebook') {
    const c = lee.cells[lee.sel], v = c && lee.editors.get(c.id);
    return v ? LeeCM.lineOf(v) : 1;
  }
  const v = lee.editors.get('file');
  return v ? LeeCM.lineOf(v) : 1;
}

function hitList(hits, note, title, onPick) {
  let sel = 0;
  const m = modal(
    `<div class="lee-mhead">${esc(title)}<span class="sub">${esc(note || '')}</span></div>
     <div class="lee-modallist" id="hl"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#hl');
  const paint = () => {
    list.innerHTML = hits.length ? hits.map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span>${esc(h.symbol || h.text.slice(0, 60))}</span>` +
      `<span class="sub">${esc(h.path.split('/').pop())}:${h.line}` +
      `${h.score ? ' · d=' + h.score.toFixed(3) : ''}</span></div>`).join('')
      : '<div class="lee-dim">nothing found</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); onPick(h); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  paint();
  return m;
}

const openHit = openLocation;

async function findSimilar() {
  if (!lee.path) return status('open a file first', 'err');
  status('finding similar code…');
  const d = await api(`/similar?path=${encodeURIComponent(lee.path)}&line=${cursorLine()}&mode=cluster`);
  status(`${d.hits.length} similar · ${d.backend} · ${d.note}`, d.hits.length ? 'ok' : null);
  hitList(d.hits, `${d.backend} — ${d.note}`, 'code like this', openHit);
}

async function codeMap() {
  status('clustering the codebase…');
  const d = await api('/clusters');
  if (!d.clusters.length) return status(d.note || 'no clusters', 'err');
  status(`${d.clusters.length} clusters · ${d.note}`, 'ok');
  // one row per cluster; picking one drills into its members
  const rows = d.clusters.map(c => ({
    symbol: `${c.label}  (${c.size})`, text: '', path: c.files[0] || '', line: 1,
    score: 0, _cluster: c,
  }));
  hitList(rows, d.note, 'code map — clusters by shape', (r) => {
    const c = r._cluster;
    hitList(c.members, `${c.size} members across ${c.files.length} files`, `cluster: ${c.label}`, openHit);
  });
}

/* Start a run configuration -- a command line, kept in the project -- in a process leela
 * puts an inspector into. That is the difference between this and the same command in a
 * terminal: the inspector is *inside* it, so the variable panel can watch the app's own
 * module while it serves. A process started anywhere else has to opt in with
 * `dhrishti.serving.serve()`; the picker says so, because everyone asks. */
async function runApp() {
  const d = await api('/runs');
  const opts = (d.runs || []).concat(d.here ? [d.here] : []);
  if (!opts.length) {
    editRuns();
    return status('no run configurations yet — here is the file', 'err');
  }
  const start = async (r) => {
    if(r.debug)return startDirectDebug(r);
    status(`starting ${r.name}…`);
    const s = await api('/dev/start?name=' + encodeURIComponent(r.name) +
                        '&path=' + encodeURIComponent(r.cmd));
    if (!s.ok) return status(s.error || 'failed to start', 'err');
    agentLog(`<div class="lee-runline"><span class="sub">▶ ${esc(s.label)} — ${esc(s.cmd)}</span></div>` +
             `<div class="lee-runline"><span class="res">${esc((s.log || []).join('\n'))}</span></div>`);
    if (s.base) {
      // Running from the picker is an explicit choice of runtime. Connect the variable
      // panel immediately instead of making the user repeat that choice in “env…”.
      await post('/envs/watch', {base: s.base});
      paintEnv(s.label);
    }
    status(`${s.label} running · app ${s.app_url || '?'} · ` +
           (s.base ? 'variables connected' : 'inspector pending'), 'ok');
    leeVars();
  };
  if (opts.length === 1) return start(opts[0]);
  const m = modal(
    `<div class="lee-mhead">run<span class="sub">${esc(d.path || 'no project folder')}</span></div>` +
    `<div class="lee-modallist">${opts.map((r, i) =>
      `<div class="lee-mrow" data-i="${i}">${esc(r.name)}<span class="sub">${esc(r.cmd)}</span></div>`).join('')}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="editruns">edit configurations</button></div>`);
  m.addEventListener('click', (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    m.remove(); start(opts[+r.dataset.i]);
  });
  m.querySelector('#editruns').onclick = () => { m.remove(); editRuns(); };
}

async function startDirectDebug(run={}) {
  let capabilities=await api('/debug/capabilities');
  if(!capabilities.debugpy){
    const ok=await confirmDialog('Install debugpy',`Install debugpy into ${capabilities.python}?`,'install');
    if(!ok)return;
    status('installing debugpy…');await post('/debug/install',{python:capabilities.python});
  }
  const path=run.program||lee.path||'', lines=path?detailedBreakpoints(path):[];
  status(`starting debugger: ${run.name||path.split('/').pop()||'Python'}…`);
  const config={...lee.debugPrefs,...run,program:run.program||path,breakpoints:path?{[path]:lines}:{}};
  await post('/debug/start',config);lee.directDebug=true;
  status('debugger running','ok');
  postEvents('/debug/events',{},(event,data)=>{
    if(event==='stopped'){lee.debugThread=data.thread_id;paintDebugger(data);status(`paused at line ${data.frames?.[0]?.line||'?'}`,'ok');}
    else if(event==='continued'){$('#debugger')?.classList.add('running');}
    else if(event==='output'){const text=data.output||'';if(text)agentLog(`<div class="lee-runline"><span class="res">${esc(text)}</span></div>`);}
    else if(event==='error')status(data.message||'debugger failed','err');
    else if(event==='terminated'||event==='exited'){leeDebugStop();status('debug session finished','ok');}
  }).catch(e=>status(e.message||String(e),'err'));
}
window.leeStartDebug=startDirectDebug;

/* Which live namespace the variable panel shows. Every process that registered an
 * inspector is here -- a notebook kernel, an app leela started, or something you launched
 * yourself that called `dhrishti.serving.serve()`. Nothing else can be, because nothing else
 * has anything to read. */
function paintEnv(name) {
  lee.env = name || '';
  const t = $('#envtag'); if (!t) return;
  t.textContent = name ? '▶ ' + name : '';
  t.style.display = name ? '' : 'none';
  t.title = name ? 'Run and the variable panel are connected to this runtime' : '';
}

async function pickEnv() {
  const d = await api('/envs');
  const rows = [{name: 'the tab’s own kernel', base: null, kind: 'kernel', current: !d.watching}]
    .concat(d.envs || []);
  const m = modal(
    `<div class="lee-mhead">runtime<span class="sub">Run + variables · ${(d.envs || []).length} live env(s)</span></div>` +
    `<div class="lee-modallist">${rows.map((e, i) =>
      `<div class="lee-mrow${e.current ? ' sel' : ''}" data-i="${i}">${e.current ? '● ' : '○ '}` +
      `${esc(e.name)}<span class="sub">${esc(e.kind)}${e.pid ? ' · pid ' + e.pid : ''}</span></div>`).join('')}</div>` +
    `<div class="lee-dim">a process only appears here if it has an inspector in it — ` +
    `<code>${esc(d.hint)}</code> puts one in yours.</div>`);
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    const pick = rows[+r.dataset.i];
    m.remove();
    await post('/envs/watch', {base: pick.base});
    paintEnv(pick.base ? pick.name : '');
    status(pick.base ? 'watching ' + pick.name : 'back on the tab’s kernel', 'ok');
    leeVars();
  });
}

/* The configurations themselves, editable in place for the same reason the keymap is:
 * telling someone to go and find a JSON file is not a feature. */
async function editRuns() {
  const d = await api('/runs/file');
  let data;
  try { data = JSON.parse(d.text); } catch (_) { data = {runs: []}; }
  let runs = Array.isArray(data) ? data : (data.runs || []);
  const m = modal(`<div class="lee-mhead">run configurations<span class="sub">${esc(d.path || 'open a folder first')}</span></div>` +
    `<div class="lee-runtime-workbench"><header><div><strong>Project runtime</strong><span>Commands, working directories, and environment sources</span></div>` +
    `<button class="lee-btn" data-add-run>Add configuration</button></header><div data-run-list></div>` +
    `<details class="lee-run-json"><summary>Advanced JSON</summary><textarea class="lee-keyedit" spellcheck="false"></textarea></details></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Secret values belong in an ignored .env.local file, not runs.json.</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save>save configurations</button></div>`,
    null, null, {className: 'lee-runtime-modal', storageKey: 'runs'});
  const list = $('[data-run-list]', m), json = $('.lee-run-json textarea', m);
  const normal = r => ({name:r.name||'run',cmd:r.cmd||'',cwd:r.cwd||'',watch:r.watch||'',inspect:r.inspect!==false,
    env_file:r.env_file||'',env:{...(r.env||{})},debug:!!r.debug,request:r.request||'launch',program:r.program||'',module:r.module||'',
    args:Array.isArray(r.args)?r.args:[],justMyCode:r.justMyCode!==false,stopOnEntry:!!r.stopOnEntry,subProcess:r.subProcess!==false,
    host:r.host||'127.0.0.1',port:Number(r.port)||5678,django:!!r.django,jinja:!!r.jinja,gevent:!!r.gevent,pathMappings:r.pathMappings||[]});
  runs = runs.map(normal);
  const collect = () => $$('.lee-run-card', list).map(card => {
    const env = {}; $$('.lee-env-row', card).forEach(row => { const key = $('[data-env-key]', row).value.trim(); if (key) env[key] = $('[data-env-value]', row).value; });
    return {name:$('[data-run-name]',card).value.trim()||'run',cmd:$('[data-run-cmd]',card).value.trim(),cwd:$('[data-run-cwd]',card).value.trim(),
      watch:$('[data-run-watch]',card).value.trim(),env_file:$('[data-run-env-file]',card).value.trim(),inspect:$('[data-run-inspect]',card).checked,env,
      debug:$('[data-run-debug]',card).checked,request:$('[data-debug-request]',card).value,program:$('[data-debug-program]',card).value.trim(),
      module:$('[data-debug-module]',card).value.trim(),args:$('[data-debug-args]',card).value.trim().split(/\s+/).filter(Boolean),
      justMyCode:$('[data-debug-mycode]',card).checked,stopOnEntry:$('[data-debug-entry]',card).checked,subProcess:$('[data-debug-subprocess]',card).checked,
      host:$('[data-debug-host]',card).value.trim()||'127.0.0.1',port:Number($('[data-debug-port]',card).value)||5678,
      django:$('[data-debug-django]',card).checked,jinja:$('[data-debug-jinja]',card).checked,gevent:$('[data-debug-gevent]',card).checked,
      pathMappings:(()=>{try{return JSON.parse($('[data-debug-paths]',card).value||'[]');}catch(_){return [];}})()};
  });
  const envRow = (key = '', value = '') => `<div class="lee-env-row"><input class="lee-input" data-env-key placeholder="NAME" value="${esc(key)}">` +
    `<input class="lee-input" data-env-value placeholder="value" value="${esc(value)}"><button class="lee-icon" data-remove-env aria-label="remove variable">×</button></div>`;
  const paint = () => {
    list.innerHTML = runs.map((r, i) => `<section class="lee-run-card" data-i="${i}"><header><strong>${esc(r.name)}</strong>` +
      `<button class="lee-btn warn" data-remove-run>remove</button></header><div class="lee-run-fields">` +
      `<label>Name<input class="lee-input" data-run-name value="${esc(r.name)}"></label><label>Command<input class="lee-input" data-run-cmd value="${esc(r.cmd)}" placeholder="uv run python app.py"></label>` +
      `<label>Working directory<input class="lee-input" data-run-cwd value="${esc(r.cwd)}" placeholder="project root"></label><label>Watch module<input class="lee-input" data-run-watch value="${esc(r.watch)}" placeholder="infer from command"></label>` +
      `<label>Environment file<input class="lee-input" data-run-env-file value="${esc(r.env_file)}" placeholder=".env.local"></label><label class="lee-run-check"><input type="checkbox" data-run-inspect${r.inspect?' checked':''}> Attach live inspector</label></div>` +
      `<details class="lee-debug-config"${r.debug?' open':''}><summary><label class="lee-run-check"><input type="checkbox" data-run-debug${r.debug?' checked':''}> Debug with debugpy</label></summary><div class="lee-run-fields">` +
      `<label>Request<select class="lee-select" data-debug-request><option value="launch"${r.request==='launch'?' selected':''}>Launch</option><option value="attach"${r.request==='attach'?' selected':''}>Attach</option></select></label>` +
      `<label>Program<input class="lee-input" data-debug-program value="${esc(r.program)}" placeholder="active Python file"></label><label>Module<input class="lee-input" data-debug-module value="${esc(r.module)}" placeholder="pytest"></label>` +
      `<label>Arguments<input class="lee-input" data-debug-args value="${esc(r.args.join(' '))}" placeholder="-x tests"></label><label>Attach host<input class="lee-input" data-debug-host value="${esc(r.host)}"></label><label>Attach port<input class="lee-input" data-debug-port type="number" value="${r.port}"></label>` +
      `<label>Path mappings<input class="lee-input" data-debug-paths value="${esc(JSON.stringify(r.pathMappings||[]))}" placeholder='[{"localRoot":".","remoteRoot":"/app"}]'></label>` +
      `<label class="lee-run-check"><input type="checkbox" data-debug-mycode${r.justMyCode?' checked':''}> Just my code</label><label class="lee-run-check"><input type="checkbox" data-debug-entry${r.stopOnEntry?' checked':''}> Stop on entry</label><label class="lee-run-check"><input type="checkbox" data-debug-subprocess${r.subProcess?' checked':''}> Subprocesses</label>` +
      `<label class="lee-run-check"><input type="checkbox" data-debug-django${r.django?' checked':''}> Django</label><label class="lee-run-check"><input type="checkbox" data-debug-jinja${r.jinja?' checked':''}> Jinja templates</label><label class="lee-run-check"><input type="checkbox" data-debug-gevent${r.gevent?' checked':''}> gevent</label></div></details>` +
      `<div class="lee-env-head"><strong>Environment variables</strong><button class="lee-btn" data-add-env>Add variable</button></div><div data-env-list>${Object.entries(r.env).map(([k,v])=>envRow(k,v)).join('')}</div></section>`).join('') ||
      `<div class="lee-empty"><strong>No run configurations</strong><p>Add how this project starts, then attach its live namespace to Variables.</p></div>`;
    $$('.lee-run-card', list).forEach(card => {
      $('[data-remove-run]', card).onclick = () => { runs = collect(); runs.splice(+card.dataset.i, 1); paint(); };
      $('[data-add-env]', card).onclick = () => { $('[data-env-list]', card).insertAdjacentHTML('beforeend', envRow()); $('.lee-env-row:last-child [data-env-key]', card).focus(); };
      card.onclick = e => { const b = e.target.closest('[data-remove-env]'); if (b) b.closest('.lee-env-row').remove(); };
    });
  };
  paint();
  $('[data-add-run]', m).onclick = () => { runs = collect(); runs.push(normal({name: `run ${runs.length + 1}`})); paint(); $$('.lee-run-card', list).at(-1)?.scrollIntoView({block:'center'}); };
  $('.lee-run-json', m).ontoggle = e => { if (e.target.open) json.value = JSON.stringify({runs: collect()}, null, 2); };
  json.addEventListener('change', () => { try { runs = (JSON.parse(json.value).runs || []).map(normal); paint(); } catch (e) { status('invalid run configuration JSON: ' + e.message, 'err'); } });
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save]', m).onclick = async () => {
    try {
      runs = collect();
      const r = await post('/runs/save', {text: JSON.stringify({runs}, null, 2) + '\n'});
      status(r.note || `saved ${r.runs.length} configuration(s)`, r.note ? 'err' : 'ok'); m.remove();
    } catch (e) { status(String(e.message || e), 'err'); }
  };
}

function palette() {
  const agentCommands = [
    {name: 'Agent: autopilot mode', scope: 'agent', run: () => leeAgentControl('autopilot')},
    {name: 'Agent: guided mode', scope: 'agent', run: () => leeAgentControl('guided')},
    {name: 'Agent: directed mode', scope: 'agent', run: () => leeAgentControl('directed')},
    {name: 'Agent: pause after current call', scope: 'agent', run: pauseAgentAfterCurrent},
    {name: 'Agent: run until next write', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'until_write'})},
    {name: 'Agent: run read-only calls', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'reads'})},
    {name: 'Agent: edit starting state', scope: 'agent', run: leeAgentState},
    {name: 'Agent: steer after current call', scope: 'agent', run: () => $('#agentsteer')?.focus()},
  ];
  const cmds = lee.keys.filter(k => k.label).map(k => ({name: k.label, scope: k.scope, action: k.action, key: k.key})).concat(agentCommands);
  let hits = cmds, sel = 0;
  const m = modal(`<input class="lee-input" id="cp" placeholder="command…" autofocus>
                   <div class="lee-modallist" id="cplist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#cplist'), input = m.querySelector('#cp');
  const paint = () => {
    list.innerHTML = hits.slice(0, 200).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.scope)} · ${esc(displayChord(h.key))}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); h.run ? h.run() : leeAct(h.action); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    hits = cmds.filter(c => c.name.toLowerCase().includes(q) || (c.action || '').includes(q)); sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

/* ------------------------------------------------------------------ file ops */
const treeSel = () => $('.lee-node.sel');
const visibleTreeNodes = () => $$('.lee-node').filter(n => n.getClientRects().length);
function selectTreeNode(n) {
  if (!n) return;
  $$('.lee-node').forEach(x => { x.classList.remove('sel'); x.setAttribute('aria-selected', 'false'); });
  n.classList.add('sel'); n.setAttribute('aria-selected', 'true');
  n.scrollIntoView({block: 'nearest'});
}
window.selectTreeNode = selectTreeNode;
function highlightTree() { if (!treeSel()) selectTreeNode(visibleTreeNodes()[0]); }
function moveTreeSelection(d) {
  const nodes = visibleTreeNodes(); if (!nodes.length) return;
  const at = Math.max(0, nodes.indexOf(treeSel()));
  selectTreeNode(nodes[Math.max(0, Math.min(nodes.length - 1, at + d))]);
}
async function loadTreeDir(n) {
  if (!n?.classList.contains('lee-dir')) return;
  const kids = n.querySelector(':scope > .lee-kids');
  n.open = true; n.setAttribute('aria-expanded', 'true');
  if (kids && !kids.children.length) {
    kids.innerHTML = await fetch('/tree?path=' + encodeURIComponent(n.dataset.path),
                                 {headers: {'HX-Request': 'true'}}).then(r => r.text());
    htmx.process(kids);
  }
}
async function treeActivate() {
  const n = treeSel(); if (!n) return highlightTree();
  if (n.classList.contains('lee-dir')) {
    if (n.open) { n.open = false; n.setAttribute('aria-expanded', 'false'); }
    else await loadTreeDir(n);
    return;
  }
  leeOpenFile(n.dataset.path);
}
async function treeExpand() {
  const n = treeSel(); if (!n) return highlightTree();
  if (!n.classList.contains('lee-dir')) return treeActivate();
  if (!n.open) await loadTreeDir(n);
  else selectTreeNode(visibleTreeNodes()[visibleTreeNodes().indexOf(n) + 1] || n);
}
function treeCollapse() {
  const n = treeSel(); if (!n) return highlightTree();
  if (n.classList.contains('lee-dir') && n.open) {
    n.open = false; return;
  }
  selectTreeNode(n.parentElement?.closest('.lee-node.lee-dir') || n);
}
async function refreshFileTree(selectPath = treeSel()?.dataset.path, focus = true) {
  const old = $('.lee-files'); if (!old) return;
  const open = $$('.lee-dir[open]', old).map(n => n.dataset.path).sort((a, b) => a.split('/').length - b.split('/').length);
  const scrollTop = $('#filetree')?.scrollTop || 0;
  const html = await fetch('/files/panel').then(r => { if (!r.ok) throw new Error(r.statusText); return r.text(); });
  const doc = new DOMParser().parseFromString(html, 'text/html'), fresh = doc.querySelector('.lee-files');
  if (!fresh) throw new Error('file tree refresh returned no panel');
  old.replaceWith(fresh); htmx.process(fresh);
  for (const path of open) {
    const dir = $$('.lee-dir').find(n => n.dataset.path === path); if (!dir) continue;
    dir.open = true;
    const kids = dir.querySelector(':scope > .lee-kids');
    const childHtml = await fetch('/tree?path=' + encodeURIComponent(path),
                                  {headers: {'HX-Request': 'true'}}).then(r => r.text());
    kids.innerHTML = childHtml; htmx.process(kids);
  }
  const wanted = $$('.lee-node').find(n => n.dataset.path === selectPath) || visibleTreeNodes()[0];
  selectTreeNode(wanted); if ($('#filetree')) $('#filetree').scrollTop = scrollTop;
  if (focus) setScope('files');
  status('files refreshed', 'ok');
}

async function newEntry(kind) {
  const sel = treeSel();
  const parent = sel ? (sel.classList.contains('lee-dir') ? sel.dataset.path
                                                        : sel.dataset.path.replace(/\/[^/]+$/, '')) : '';
  if (!parent) return status('open a folder first', 'err');
  const name = await inputDialog(kind === 'dir' ? 'new folder' : 'new file', 'name', '',
                                 kind === 'dir' ? 'folder name' : 'filename.py');
  if (!name) return;
  const r = await post('/fs/new', {parent, name, kind});
  status('created ' + name, 'ok');
  await refreshFileTree(r.entry.path);
  if (kind === 'file') leeOpenFile(r.entry.path);
}
async function renameEntry() {
  const sel = treeSel(); if (!sel) return status('select a file or folder first');
  const old = sel.dataset.path.split('/').pop();
  const name = await inputDialog('rename', 'name', old);
  if (!name || name === old) return;
  const r = await post('/fs/rename', {path: sel.dataset.path, name});
  await refreshFileTree(r.entry.path);
}
async function deleteEntry() {
  const sel = treeSel(); if (!sel) return status('select a file or folder first');
  const name = sel.dataset.path.split('/').pop(), folder = sel.classList.contains('lee-dir');
  const warning = folder
    ? 'This permanently deletes the folder and everything inside it from disk.'
    : 'This permanently deletes the file from disk.';
  if (lee.filePrefs.confirmDelete !== false && !await confirmDialog('delete ' + name + ' from disk', warning, 'delete')) return;
  const parent = sel.parentElement?.closest('.lee-node.lee-dir')?.dataset.path;
  await post('/fs/delete', {path: sel.dataset.path});
  await refreshFileTree(parent);
}
async function removeRoot() {
  const sel = treeSel();
  if (!sel?.classList.contains('lee-root')) return status('select an open project root first', 'err');
  const name = sel.dataset.path.split('/').pop();
  if (!await confirmDialog('remove ' + name + ' from workspace', 'Files stay on disk. Open tabs inside it will close.', 'remove')) return;
  await post('/fs/remove-root', {path: sel.dataset.path});
  await refreshFileTree();
  status(name + ' removed from the workspace; files were not deleted', 'ok');
}
/* `find` opens the same dialog with the repository filter focused. Browsing and searching are
   the two ways people actually find a checkout, and they want the same confirm button. */
async function findRepo() { return addRoot(true); }

/* One box, the way a shell has one.

   The picker used to be a path bar, a separate filter box, a list and an up button -- four
   controls for "which folder", and the path bar was the only one that took a path. Typing
   into it now completes folders under what is already typed, Tab takes the completion,
   and Enter opens. Repositories deeper down still answer to a bare name, because a
   directory of checkouts is more than one level deep and that was the other thing the
   second box was for. */
async function addRoot(find = false) {
  const m = modal(`<div class="lee-mhead">open folder<span class="sub">type a path · Tab completes · Enter opens</span></div>
    <input class="lee-input lee-pathinput" id="folderpath" autocomplete="off" spellcheck="false"
      aria-label="folder path" aria-autocomplete="list" aria-controls="folderlist"
      placeholder="~/code/  ·  or the name of a repository below it">
    <div class="lee-modallist lee-folderlist" id="folderlist" role="listbox"></div>
    <div class="lee-mfoot"><button class="lee-btn go" id="folderopen">open this folder</button>
    <span class="lee-dim" id="folderhint"></span></div>`);
  const input = m.querySelector('#folderpath'), list = m.querySelector('#folderlist');
  const hint = m.querySelector('#folderhint'), openBtn = m.querySelector('#folderopen');
  let base = '', dirs = [], rows = [], sel = 0, lastDir = null, seq = 0, timer = null;

  const dirOf = v => { const i = v.lastIndexOf('/'); return i < 0 ? '' : v.slice(0, i + 1); };
  const fragOf = v => { const i = v.lastIndexOf('/'); return i < 0 ? v : v.slice(i + 1); };
  const row = (r, i) =>
    `<button class="lee-folderrow${i === sel ? ' sel' : ''}" role="option" aria-selected="${i === sel}" ` +
    `data-path="${esc(r.path)}"><span class="lee-folderglyph">▸</span>${esc(r.name)}` +
    (r.where ? `<span class="lee-dim lee-folderwhere">${esc(r.where)}</span>` : '') + `</button>`;
  const paint = (extra = '') => {
    list.innerHTML = rows.map(row).join('') + extra ||
      '<div class="lee-dim">no folders match — Enter still opens what you typed, if it exists</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
    hint.textContent = base ? `in ${base}` : '';
  };
  // Prefix matches first: completing `pe` should offer `personal` before `home/spec`.
  const rank = frag => {
    const f = frag.toLowerCase();
    const starts = dirs.filter(x => x.name.toLowerCase().startsWith(f));
    return starts.concat(dirs.filter(x => !starts.includes(x) && x.name.toLowerCase().includes(f)));
  };
  const repos = async frag => {
    const mine = ++seq;
    try {
      const r = await api(`/git/find?base=${encodeURIComponent(base)}&q=${encodeURIComponent(frag)}`);
      if (mine !== seq) return;                        // a later keystroke already answered
      const found = (r.repos || []).filter(x => !rows.some(n => n.path === x.path));
      if (!found.length) return paint();
      rows = rows.concat(found.map(x => ({name: x.name, path: x.path, where: x.parent})));
      paint();
    } catch (_) { paint(); }
  };
  const draw = async () => {
    const v = input.value, dir = dirOf(v), frag = fragOf(v);
    if (dir !== lastDir) {
      lastDir = dir;
      try {
        const d = await api('/fs/browse?path=' + encodeURIComponent(dir || v));
        base = d.path; dirs = d.dirs || [];
      } catch (_) { dirs = []; base = ''; }
    }
    rows = rank(frag); sel = 0;
    clearTimeout(timer);
    if (frag.length < 2) return paint();
    // The search below walks a tree, so it is debounced: a five-letter name is one search,
    // not five queued behind one worker.
    paint(`<div class="lee-searching"><span class="lee-spin"></span>searching ${esc(base)} for repositories…</div>`);
    timer = setTimeout(() => repos(frag), 200);
  };
  const complete = () => {
    const r = rows[sel]; if (!r) return false;
    input.value = r.path + '/'; draw(); return true;
  };
  const open = async path => {
    const target = path || input.value.trim(); if (!target) return;
    m.remove();
    try {
      await post('/fs/add-root', {path: target});
      // The tree is redrawn *before* the folder is activated: activating selects the new
      // root's node, and a tree that has not been rebuilt does not have one yet -- which
      // left a folder that was open on the server and absent from the panel until reload.
      await refreshFileTree(target);
      await activateRoot(target);           // the folder you just opened is the one you mean
    } catch (e) { status(String(e.message || e), 'err'); }
  };
  input.oninput = draw;
  input.onkeydown = e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); if (!rows.length) return;
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length; paint();
    } else if (e.key === 'Tab') { e.preventDefault(); complete(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const v = input.value.trim(), frag = fragOf(v);
      // A path that names a folder is a folder to open. Anything else is half-typed, so the
      // first Enter completes it and the second opens it -- Tab, for people who press Enter.
      if (v && (!frag || dirs.some(x => x.path === v.replace(/\/$/, '')))) return open(v);
      if (!complete()) if (v) open(v);
    } else if (e.key === 'Escape') { e.preventDefault(); m.remove(); }
  };
  list.onclick = e => {
    const r = e.target.closest('.lee-folderrow'); if (!r) return;
    input.value = r.dataset.path + '/'; input.focus(); draw();
  };
  openBtn.onclick = () => open();
  input.value = find ? '' : (await api('/fs/browse?path=').catch(() => ({path: ''}))).path + '/';
  input.focus(); input.setSelectionRange(input.value.length, input.value.length);
  await draw();
}

document.addEventListener('keydown', e => {
  const tab = e.target.closest?.('.lee-tab'); if (!tab) return;
  const tabs = $$('.lee-tab'), at = tabs.indexOf(tab);
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    e.preventDefault(); const step = e.key === 'ArrowRight' ? 1 : -1;
    const next = tabs[(at + step + tabs.length) % tabs.length]; next?.focus(); next?.click();
  } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tab.click(); }
  else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); tab.querySelector('.lee-tab-x')?.click(); }
});

document.addEventListener('click', (e) => {
  const n = e.target.closest('.lee-node');
  if (n) { selectTreeNode(n); setScope('files'); }
  if (e.target.closest('.lee-vars')) setScope('vars');
});
document.addEventListener('toggle', e => {
  if (e.target.matches?.('.lee-dir')) e.target.setAttribute('aria-expanded', e.target.open ? 'true' : 'false');
}, true);

// Middle-click closes a tab, as it does in every browser. Delegated because both strips are
// re-rendered whole -- the document strip by htmx, the terminal strip by `paintTermTabs`.
document.addEventListener('auxclick', e => {
  if (e.button !== 1) return;
  const term = e.target.closest?.('.lee-termtab');
  if (term) { e.preventDefault(); return closeTerm(term.dataset.term); }
  const tab = e.target.closest?.('.lee-tab');
  if (!tab) return;
  e.preventDefault();                     // some platforms paste or autoscroll on button 1
  if (tab.dataset.gitDiff) return closeGitDiffTab(tab.dataset.gitDiff);
  closeTab(+tab.dataset.i);
});

// Drag to reorder. The order is the user's arrangement of their own work, so the drop is
// posted rather than kept in the browser: it has to survive a reload like the tabs do.
document.addEventListener('dragstart', e => {
  const tab = e.target.closest?.('.lee-tab');
  if (!tab || tab.dataset.gitDiff) return;
  lee.dragTab = +tab.dataset.i;
  e.dataTransfer.effectAllowed = 'move';
  try { e.dataTransfer.setData('text/plain', tab.dataset.i); } catch (_) {}
});
document.addEventListener('dragover', e => {
  if (lee.dragTab == null) return;
  const tab = e.target.closest?.('.lee-tab');
  if (!tab || tab.dataset.gitDiff) return;
  e.preventDefault(); e.dataTransfer.dropEffect = 'move';
  $$('.lee-tab').forEach(t => t.classList.toggle('drop', t === tab));
});
document.addEventListener('drop', e => {
  if (lee.dragTab == null) return;
  const tab = e.target.closest?.('.lee-tab');
  $$('.lee-tab').forEach(t => t.classList.remove('drop'));
  if (tab && !tab.dataset.gitDiff) { e.preventDefault(); moveTab(lee.dragTab, +tab.dataset.i); }
  lee.dragTab = null;
});
document.addEventListener('dragend', () => {
  lee.dragTab = null; $$('.lee-tab').forEach(t => t.classList.remove('drop'));
});

document.addEventListener('contextmenu', e => {
  // Shift+right-click remains the browser's native copy/paste/spellcheck menu.
  if (e.shiftKey) return;
  const node = e.target.closest('.lee-node');
  if (node) {
    e.preventDefault(); $$('.lee-node').forEach(x => x.classList.remove('sel')); node.classList.add('sel');
    const surface = node.classList.contains('lee-root') ? 'root' : node.classList.contains('lee-dir') ? 'folder' : 'file';
    setScope('files'); openMenu(surface, e.clientX, e.clientY); return;
  }
  if (e.target.closest('#filetree')) {
    e.preventDefault(); setScope('files'); openMenu('files', e.clientX, e.clientY); return;
  }
  const variable = e.target.closest('.lee-vrow');
  if (variable) {
    e.preventDefault(); selectVar(variable); setScope('vars'); openMenu('variable', e.clientX, e.clientY); return;
  }
  const cell = e.target.closest('.lee-cell');
  if (cell) {
    e.preventDefault(); selectCell(+cell.dataset.i); setScope('editor'); openMenu('cell', e.clientX, e.clientY); return;
  }
  const tab = e.target.closest('.lee-tab');
  if (tab) {
    e.preventDefault(); lee.menuTab = +tab.dataset.i;
    if (!tab.classList.contains('active')) htmxPost('/tab/select?i=' + tab.dataset.i);
    openMenu('tab', e.clientX, e.clientY); return;
  }
  if (e.target.closest('#kpill')) { e.preventDefault(); openMenu('kernel', e.clientX, e.clientY); return; }
  if (e.target.closest('.lee-exec')) { e.preventDefault(); setScope('exec'); openMenu('exec', e.clientX, e.clientY); return; }
  if (e.target.closest('#editor')) { e.preventDefault(); setScope('editor'); openMenu('editor', e.clientX, e.clientY); }
});

/* ------------------------------------------------------------------ splitters */
function initSplits() {
  const savedLeft = localStorage.getItem('lee-left-view');
  // Every panel is saved on switch, so every panel is restorable. Restoring only two of them
  // meant a reload silently moved you back to the file tree from the one you were working in.
  leeLeft(['git', 'symbols', 'workflows', 'releases', 'deploys', 'drive'].includes(savedLeft) ? savedLeft : 'files');
  for (const pane of ['left', 'right', 'bottom'])
    if (localStorage.getItem('lee-pane-' + pane) === 'hidden') leePane(pane, false);
  if (matchMedia('(max-width: 1100px)').matches) {
    leePane('left', false); leePane('right', false);
  }
  $$('.lee-split').forEach(sp => {
    sp.onpointerdown = (e) => {
      e.preventDefault(); sp.classList.add('drag'); sp.setPointerCapture(e.pointerId);
      const side = sp.dataset.split;
      const move = (ev) => {
        const w = side === 'left' ? ev.clientX : window.innerWidth - ev.clientX;
        const v = Math.max(140, Math.min(window.innerWidth - 300, w));
        document.documentElement.style.setProperty(`--lee-${side}-w`, v + 'px');
        localStorage.setItem(`lee-${side}-w`, v + 'px');
      };
      const up = () => { sp.classList.remove('drag'); sp.onpointermove = null; sp.onpointerup = null; };
      sp.onpointermove = move; sp.onpointerup = up;
    };
  });
  const centreHeight = () => $('.lee-centre')?.clientHeight || window.innerHeight;
  // The dock may occupy most of the workspace; 360px made Agent and Terminal feel like
  // preview strips on large displays. The editor keeps its own 140px safety floor.
  const limit = () => Math.min(900, Math.max(110, centreHeight() - 240));
  const dockSplit = $('.lee-dock-split');
  if (dockSplit) dockSplit.onpointerdown = (e) => {
    e.preventDefault(); dockSplit.classList.add('drag'); dockSplit.setPointerCapture(e.pointerId);
    const bottom = $('#bottomdock')?.getBoundingClientRect().bottom || window.innerHeight;
    const move = (ev) => {
      const v = Math.max(110, Math.min(limit(), bottom - ev.clientY));
      document.documentElement.style.setProperty('--lee-dock-h', v + 'px');
      localStorage.setItem('lee-dock-h', v + 'px');
      localStorage.setItem('lee-agent-h', v + 'px'); // migrate the previous bottom-dock preference
      requestAnimationFrame(() => lee.term?.refit());
    };
    dockSplit.onpointermove = move;
    dockSplit.onpointerup = () => { dockSplit.classList.remove('drag'); dockSplit.onpointermove = null; };
  };
  ['left-w', 'right-w'].forEach(k => {
    const v = localStorage.getItem('lee-' + k);
    if (v) document.documentElement.style.setProperty('--lee-' + k, v);
  });
  // Legacy names remain readable so an upgrade preserves the user's lower-panel height.
  const legacyPanelFloors = [['exec-h', 80], ['agent-h', 110]];
  void legacyPanelFloors;
  for (const [k, floor] of [['dock-h', 110]]) {
    const raw = parseFloat(localStorage.getItem('lee-' + k) || localStorage.getItem('lee-agent-h'));
    if (!Number.isFinite(raw)) continue;
    const value = Math.max(floor, Math.min(limit(), raw));
    document.documentElement.style.setProperty('--lee-' + k, value + 'px');
    localStorage.setItem('lee-' + k, value + 'px');
  }
  if (localStorage.getItem('lee-agent-expanded') === '1') {
    $('#shell')?.classList.add('agent-focus');
    if ($('#agentexpand')) $('#agentexpand').textContent = 'restore';
  }
}

async function refreshKernelPill() {
  try {
    const d = await api('/kernel/info');
    const pill = $('#kpill'); if (!pill) return;
    pill.className = 'lee-pill ' + (d.api_error || d.boot_error ? 'lee-pill-warn' : d.alive ? 'lee-pill-on' : 'lee-pill-err');
    pill.textContent = (d.api_error ? '⚠ ' : d.alive ? '⏺ ' : '○ ') + (d.key || '').split('/').pop();
    pill.title = (d.base || 'no inspector') + (d.cwd ? ' · cwd ' + d.cwd : '') +
                 (d.boot_error ? ' · ' + d.boot_error : '') + (d.api_error ? ' · inspector: ' + d.api_error : '');
    (d.tabs || []).forEach((state, i) => {
      const tab = $(`.lee-tab[data-i="${i}"]`); if (!tab) return;
      let run = tab.querySelector('.lee-tab-run');
      if (state.running && !run) { run = document.createElement('span'); run.className = 'lee-tab-run'; tab.prepend(run); }
      if (run) { run.hidden = !state.running; run.title = `${state.running} cell(s) running`; }
      const wasDirty = tab.classList.contains('dirty');
      tab.classList.toggle('dirty', !!state.dirty);
      if (state.dirty && !wasDirty) setTabSaveState(tab, 'pending');
      else if (!state.dirty && wasDirty && tab.dataset.saveState !== 'error') setTabSaveState(tab, 'saved');
    });
  } catch (e) {}
}

async function checkProjectRuntime() {
  let d;
  try { d = await api('/runtime/info'); } catch (_) { return; }
  if ((!d.needs_create && !d.needs_support) || sessionStorage.getItem('lee-runtime-asked:' + d.root)) return;
  sessionStorage.setItem('lee-runtime-asked:' + d.root, '1');
  /* A folder with no environment at all gets one, without being asked. Opening a project and
     landing on whatever `python3` happens to be on PATH is never what anyone wanted, and with uv
     the fix is one command that a deleted directory undoes. Only for a *missing* environment:
     installing packages into an environment you built yourself is your decision, so needs_support
     below still asks. Without uv it also still asks, because a half-built venv is worse than
     none. */
  if (d.needs_create && d.uv) {
    status('no project environment — creating .venv with uv…');
    try {
      const r = await post('/runtime/create');
      status(`project runtime ready: ${r.python}`, 'ok'); refreshKernelPill();
      return;
    } catch (e) { status(`could not create .venv — ${String(e.message || e)}`, 'err'); }
    /* fall through to the dialog, which offers choosing an interpreter instead */
  }
  if (d.needs_support) {
    const m = modal(`<div class="lee-mhead">enable project runtime<span class="sub">${esc(d.python)}</span></div>` +
      `<div class="lee-dialogcopy">Leela found this folder’s environment, but it needs ` +
      `<code>ipykernel</code> and <code>ipymini</code> to run notebook code. ` +
      `Leela installs them into this project environment with uv; the IDE remains separate.</div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" id="runtimeenable">install kernel support</button>` +
      `<button class="lee-btn" id="runtimelater">not now</button></div>`);
    m.querySelector('#runtimeenable').onclick = async () => {
      m.querySelector('#runtimeenable').disabled = true; status('installing project kernel support…');
      try {
        const r = await post('/runtime/support', {python: d.python}); m.remove();
        status(`project runtime ready · ipykernel + ipymini`, 'ok');
        refreshKernelPill();
      }
      catch (e) { status(String(e.message || e), 'err'); m.querySelector('#runtimeenable').disabled = false; }
    };
    m.querySelector('#runtimelater').onclick = () => m.remove();
    return;
  }
  const m = modal(`<div class="lee-mhead">project runtime<span class="sub">${esc(d.root)}</span></div>` +
    `<div class="lee-dialogcopy">This folder has no <code>.venv</code>, <code>venv</code>, ` +
    `<code>env</code>, or <code>.env</code>. Leela stays in its own environment; your code ` +
    `runs in a project environment.</div><div class="lee-mfoot">` +
    `<button class="lee-btn go" id="runtimecreate">create .venv</button>` +
    `<button class="lee-btn" id="runtimepick">choose interpreter</button>` +
    `<button class="lee-btn" id="runtimelater">not now</button></div>`);
  m.querySelector('#runtimecreate').onclick = async () => {
    m.querySelector('#runtimecreate').disabled = true; status('creating .venv and installing ipykernel…');
    try {
      const r = await post('/runtime/create'); m.remove();
      status(`project runtime ready: ${r.python}`, 'ok'); refreshKernelPill();
    } catch (e) { status(String(e.message || e), 'err'); m.querySelector('#runtimecreate').disabled = false; }
  };
  m.querySelector('#runtimepick').onclick = () => { m.remove(); pickKernel(); };
  m.querySelector('#runtimelater').onclick = () => m.remove();
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  await Promise.all([loadKeys(), loadSettings()]);
  // Model discovery can probe CLIs and registries; it must not hold the editor's first paint.
  loadAgentModels().catch(e => status(String(e.message || e), 'err'));
  initSplits();
  mountExec();
  initAgentComposer();
  await mountTab();
  layoutTabs();
  new ResizeObserver(layoutTabs).observe($('#header'));
  checkProjectRuntime();
  leeVars();
  setInterval(leeVars, 2500);          // the kernel's own inspector is the source of truth; poll it
  setInterval(watchOpenFile, 1000);    // agent, terminal and git writes appear without a page refresh
  pollApproval();
  setInterval(pollApproval, 750);       // catches Rishi approvals raised outside an agent SSE stream
  applyTheme(readTheme());   // also rewrites a pre-family value into `family:mode`
  refreshProjectPills();
  setInterval(refreshKernelPill, 5000);
  setInterval(refreshProjectPills, 5000);
  setInterval(pollRunLogs, 2000);      // only does anything while the logs pane is open
  status('ready', 'ok');
}

document.addEventListener('DOMContentLoaded', boot);

document.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target.id || '';
  // A tab change swaps only the tab bar; re-mount the editor for whatever is now active.
  if (id === 'tabbar') { mountTab().then(leeVars); refreshProjectPills(); requestAnimationFrame(layoutTabs); }
  // Adding a folder rebuilds the whole shell, so everything the client owns is remounted.
  else if (id === 'shell') { lee.editors.clear(); loadAgentModels(); initSplits(); mountExec(); initAgentComposer(); mountTab().then(leeVars); requestAnimationFrame(layoutTabs); }
});
/* -------------------------------------------------------------- refactor */
function refactorRows(files, selected) {
  return files.map((file, i) => `<label class="lee-mrow"><input type="checkbox" data-refactor-path="${esc(file.path)}"${selected.has(file.path) ? ' checked' : ''}>` +
    `<strong>${esc(compactPath(file.path))}</strong><span class="sub">${file.edits} replacement${file.edits === 1 ? '' : 's'}</span></label>`).join('');
}

async function replaceWorkspace() {
  const m = modal(`<div class="lee-mhead">Replace in workspace<span class="sub">preview before changing files</span></div>` +
    `<label>Find<input class="lee-input" data-refactor-find autofocus></label>` +
    `<label>Replace<input class="lee-input" data-refactor-replace></label>` +
    `<label><input type="checkbox" data-refactor-regex> regular expression</label>` +
    `<label><input type="checkbox" data-refactor-case> match case</label>` +
    `<label><input type="checkbox" data-refactor-word> whole word</label>` +
    `<div class="lee-mfoot"><button class="lee-btn go" data-refactor-preview>Preview</button><button class="lee-btn" data-refactor-cancel>Cancel</button></div>`);
  const find = $('[data-refactor-find]', m), replace = $('[data-refactor-replace]', m);
  $('[data-refactor-cancel]', m).onclick = () => m.remove();
  $('[data-refactor-preview]', m).onclick = async () => {
    const button = $('[data-refactor-preview]', m); button.disabled = true;
    try {
      const data = await post('/replace/preview', {find: find.value, replace: replace.value,
        regex: $('[data-refactor-regex]', m).checked, case: $('[data-refactor-case]', m).checked,
        word: $('[data-refactor-word]', m).checked});
      if (!data.summary.files) return status('no matches in editable workspace files', 'err');
      const selected = new Set(data.files.map(x => x.path));
      m.querySelector('.lee-modalbox').innerHTML = `<div class="lee-mhead">Replace preview<span class="sub">${data.summary.edits} replacements in ${data.summary.files} files</span></div>` +
        `<div class="lee-modallist" data-refactor-files>${refactorRows(data.files, selected)}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-refactor-apply>Apply</button><button class="lee-btn" data-refactor-cancel>Cancel</button></div>`;
      $('[data-refactor-cancel]', m).onclick = () => m.remove();
      $('[data-refactor-apply]', m).onclick = async () => {
        const paths = $$('[data-refactor-path]:checked', m).map(x => x.dataset.refactorPath);
        if (!paths.length) return status('select at least one file', 'err');
        if (!await confirmDialog('Replace in workspace', `Change ${paths.length} file${paths.length === 1 ? '' : 's'}?`, 'apply')) return;
        try {
          const result = await post('/replace/apply', {token: data.token, paths}); m.remove();
          if (paths.includes(lee.path)) await takeDiskVersion(lee.path);
          refreshFileTree(undefined, false); status(`replaced text in ${result.paths.length} file${result.paths.length === 1 ? '' : 's'}`, 'ok');
        } catch (e) { status(e.message || String(e), 'err'); }
      };
    } catch (e) { status(e.message || String(e), 'err'); }
    finally { button.disabled = false; }
  };
}

async function workspaceHistoryRedo() {
  try {
    const result = await post('/history/redo', {}), paths = (result.operation.resources || []).map(x => x.path);
    if (paths.includes(lee.path)) await takeDiskVersion(lee.path);
    refreshFileTree(undefined, false); status('workspace operation redone', 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}

/* Extraction and inlining run against the file *on disk*: the endpoints read it themselves and
   address it by character offset, so an unsaved buffer would be rewritten from text the server
   never saw. Both refuse rather than save on the user's behalf. */
function refactorTarget() {
  if (lee.kind !== 'text' || !(lee.path || '').endsWith('.py')) {
    status('open a Python file to refactor', 'err'); return null;
  }
  if (lee.dirtyBuffers.has(lee.path)) { status('save the file before refactoring', 'err'); return null; }
  return curEditor();
}

async function runRefactor(url, body, note) {
  const data = await post(url, {path: lee.path, ...body}), edits = data.summary.edits;
  if (!await confirmDialog('Refactor', `Change ${edits} place${edits === 1 ? '' : 's'} in this file?`, 'apply')) return;
  await post('/refactor/apply', {token: data.token});
  await takeDiskVersion(lee.path); refreshFileTree(undefined, false); status(note, 'ok');
}

/* Whether the block the selection sits in is a class body, which is what decides between a
   method taking `self` and a plain function. The nearest header at a smaller indent wins. */
function inClassBody(view, pos) {
  const doc = view.state.doc, indent = t => t.match(/^[ \t]*/)[0].length;
  const want = indent(doc.lineAt(pos).text);
  for (let n = doc.lineAt(pos).number - 1; n >= 1; n--) {
    const t = doc.line(n).text;
    if (t.trim() && indent(t) < want) return /^\s*class\s/.test(t);
  }
  return false;
}

async function extractRefactor(kind) {
  const view = refactorTarget(); if (!view) return;
  const sel = LeeCM.selection(view);
  if (!sel || sel.from === sel.to) return status('select the code to extract first', 'err');
  if (kind === 'method' && !inClassBody(view, sel.from)) kind = 'function';
  const name = await inputDialog(`extract ${kind}`, 'Name', '', 'valid Python identifier');
  if (!name) return;
  try {
    await runRefactor('/refactor/preview', {start: sel.from, end: sel.to, kind, name}, `extracted ${kind} ${name}`);
  } catch (e) { status(e.message || String(e), 'err'); }
}

async function inlineVariable() {
  const view = refactorTarget(); if (!view) return;
  try {
    await runRefactor('/refactor/inline', {pos: LeeCM.cursor(view)}, 'variable inlined');
  } catch (e) { status(e.message || String(e), 'err'); }
}

/* Whole lines within one buffer, where `cell_move_up`/`cell_move_down` move whole cells.
   Written against the CodeMirror state directly rather than through a new `LeeCM` export: the
   vendored bundle is committed and rebuilding it needs node, so the page must not grow a
   dependency on a wrapper that is not in the shipped build. */
function moveLines(dir) {
  const view = curEditor(); if (!view) return;
  const doc = view.state.doc, sel = view.state.selection.main;
  const first = doc.lineAt(sel.from), last = doc.lineAt(sel.to);
  const n = dir < 0 ? first.number - 1 : last.number + 1;
  if (n < 1 || n > doc.lines) return;
  const swap = doc.line(n), block = doc.sliceString(first.from, last.to);
  const shift = dir * (swap.text.length + 1);
  view.dispatch({
    changes: {from: Math.min(first.from, swap.from), to: Math.max(last.to, swap.to),
              insert: dir < 0 ? block + '\n' + swap.text : swap.text + '\n' + block},
    selection: {anchor: sel.anchor + shift, head: sel.head + shift}, scrollIntoView: true});
  view.focus();
}

ACTIONS.replace_workspace = replaceWorkspace;
ACTIONS.workspace_undo = () => operationHistory();
ACTIONS.workspace_redo = workspaceHistoryRedo;
ACTIONS.extract_variable = () => extractRefactor('variable');
ACTIONS.extract_constant = () => extractRefactor('constant');
ACTIONS.extract_method = () => extractRefactor('method');
ACTIONS.inline_variable = inlineVariable;
ACTIONS.move_line_up = () => moveLines(-1);
ACTIONS.move_line_down = () => moveLines(1);
/* --------------------------------------------------------- git conflicts */
async function showConflictCenter() {
  try {
    const d = await api(gitUrl('/git/conflicts')), files = d.files || [], s = d.summary || {};
    if (!files.length) return status('no unresolved Git conflicts', 'ok');
    const rows = files.map(f => `<button class="lee-mrow" data-conflict-path="${esc(f.path)}"><strong>${esc(f.path)}</strong>` +
      `<span class="sub">${f.kind} · ${f.blocks || 0} conflict${f.blocks === 1 ? '' : 's'} · ${f.safe ? `${f.safe} safe` : f.reason}</span></button>`).join('');
    const m = modal(`<div class="lee-mhead">Resolve conflicts<span class="sub">${esc(d.operation.active || 'Git operation')} paused · ${s.files} files · ${s.blocks} blocks</span></div>` +
      `<div class="lee-git-merge-preview"><header><strong>${s.safe || 0} safe resolution${s.safe === 1 ? '' : 's'} available</strong><span>Automatic changes are limited to identical sides.</span></header></div>` +
      `<div class="lee-modallist">${rows}</div><div class="lee-mfoot"><button class="lee-btn go" data-safe${s.safe ? '' : ' disabled'}>Resolve safe changes</button><button class="lee-btn" data-close>Close</button></div>`);
    $('[data-close]', m).onclick = () => m.remove();
    $$('[data-conflict-path]', m).forEach(b => b.onclick = () => { m.remove(); showGitConflict(b.dataset.conflictPath); });
    $('[data-safe]', m).onclick = async () => {
      if (!await confirmDialog('Resolve safe conflicts', `Stage ${s.safe} deterministic resolution${s.safe === 1 ? '' : 's'}?`, 'resolve')) return;
      const next = await gitDo('resolve_safe_conflicts', {paths: files.filter(f => f.safe).map(f => f.path)});
      m.remove(); renderGitPanel(next); status('safe conflicts resolved; review remaining files', 'ok');
      if ((next.changes || []).some(x => x.conflicted)) showConflictCenter();
    };
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.showConflictCenter = showConflictCenter;
/* ---- vault reader: a document from the vault, as an editor tab ---- */

function vaultSectionRows(sections, active) {
  if (!sections.length) return '<div class="lee-dim">No section structure was extracted.</div>';
  return sections.map(s => `<button class="lee-vault-section${s.node_id === active ? ' active' : ''}" ` +
    `data-node="${esc(s.node_id)}" style="padding-left:${6 + s.depth * 10}px">` +
    `<strong>${esc(s.title)}</strong>${s.page ? `<small>p. ${s.page}</small>` : ''}</button>`).join('');
}

function vaultPrivacy(d) {
  const p = d.privacy || {};
  if (!p.has_pii && !p.detected) return `<div class="lee-pii clear" title="${esc(d.covers || '')}">no pattern found</div>`;
  const kinds = Object.entries(p.kinds || {}).map(([k, n]) => `${k}×${n}`).join(', ');
  const cleared = p.override === 'clear';
  // `detected` stays true under an override, so an overridden document says so rather than
  // claiming the scan found nothing.
  return `<div class="lee-vault-privacy${cleared ? '' : ' sensitive'}">` +
    `<strong>${cleared ? 'Marked not personal' : 'Personal information found'}</strong>` +
    `<span class="lee-pii ${cleared ? 'clear' : 'found'}" title="${esc(d.covers || '')}">${esc(kinds || 'no kinds')}</span>` +
    (d.evidence?.length ? `<div class="lee-vault-evidence">${d.evidence.slice(0, 40).map(e =>
      `<span title="${esc(e.kind)}, page ${e.page}"><mark>${esc(e.value)}</mark><small>p. ${e.page}</small></span>`).join('')}</div>` : '') +
    `<button data-vault-notpii="${cleared ? '0' : '1'}">${cleared ? 'restore detection' : 'mark not personal'}</button></div>`;
}

async function mountVault(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the vault</small></div>';
  const q = new URLSearchParams({doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''});
  let d;
  try { d = await api('/vault/doc?' + q); }
  catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }

  const doc = d.doc || {}, sections = d.sections || [];
  host.innerHTML = `<div class="lee-vault-reader">` +
    `<aside class="lee-vault-toc"><div class="lee-phead"><span class="lee-ptitle">${esc(doc.title || st.title)}</span>` +
    `<span class="lee-keyscope">${esc(doc.kind || 'document')} · ${esc(st.shelf || 'store')}</span></div>` +
    `<div class="lee-vault-sections">${vaultSectionRows(sections, '')}</div></aside>` +
    `<div class="lee-vault-body">${vaultPrivacy(d)}<article class="lee-vault-text" data-markdown=""></article></div></div>`;

  const body = $('.lee-vault-text', host);
  const show = async node => {
    $$('.lee-vault-section', host).forEach(b => b.classList.toggle('active', b.dataset.node === node));
    try {
      const s = await api('/vault/section?' + new URLSearchParams({node, shelf: st.shelf || '', vault: st.vault || ''}));
      renderMarkdown(body, s.section?.text || '');
    } catch (e) { body.textContent = e.message || String(e); }
  };
  $$('.lee-vault-section', host).forEach(b => b.onclick = () => show(b.dataset.node));
  if (sections.length) show(sections[0].node_id);
  // A document with nothing found has no override button, so this is optional -- assuming it was
  // there threw on null and took the rest of the mount, including the first section, with it.
  const notpii = $('[data-vault-notpii]', host);
  if (notpii) notpii.onclick = async e => {
    try {
      await post('/vault/not-pii', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '',
                                    clear: e.target.dataset.vaultNotpii === '1'});
      mountVault(host, st);
    } catch (err) { status(err.message || String(err), 'err'); }
  };
}
window.mountVault = mountVault;

async function leeOpenVaultDoc(doc, shelf = '', vault = '', title = '') {
  await htmx.ajax('POST', '/vault/open?' + new URLSearchParams({doc, shelf, vault, title}),
    {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeOpenVaultDoc = leeOpenVaultDoc;
/* The branch pill as a real Git control, and the three remote gestures beside it.
 *
 * One popup over branches *and* actions, in the order JetBrains settled on: what to do with
 * the branch you are on, then how to get a different one, then the branches themselves. Names
 * containing a `/` fold into a folder by their first segment -- a checkout with forty
 * `cursor/…` branches is otherwise a wall of near-identical rows.
 *
 * Everything here posts to `/git/action`, which already knows checkout, fetch, pull, push,
 * create, merge, rebase and delete. The one new route is `/git/clone`, because a clone is
 * minutes of network and cannot be a request.
 */

const GIT_RECENT_KEY = 'lee-git-recent-branches';
const gitBranchFolders = new Set();      // which prefix folders are expanded, this session

function recentBranches(root) {
  try { return JSON.parse(localStorage.getItem(GIT_RECENT_KEY) || '{}')[root] || []; }
  catch (_) { return []; }
}
function rememberBranch(root, name) {
  let all = {};
  try { all = JSON.parse(localStorage.getItem(GIT_RECENT_KEY) || '{}'); } catch (_) {}
  all[root] = [name, ...(all[root] || []).filter(x => x !== name)].slice(0, 8);
  try { localStorage.setItem(GIT_RECENT_KEY, JSON.stringify(all)); } catch (_) {}
}

// A remote branch's first segment is its remote, not a folder: `origin/cursor/x` belongs in
// `cursor` beside the local branch of the same name.
function branchLeaf(b) { return b.remote ? b.name.split('/').slice(1).join('/') : b.name; }
function branchFolder(b) { const cut = branchLeaf(b).indexOf('/'); return cut < 0 ? '' : branchLeaf(b).slice(0, cut); }
function branchDrift(b) {
  return `${b.behind ? `<i class="behind">↙${b.behind}</i>` : ''}${b.ahead ? `<i class="ahead">↗${b.ahead}</i>` : ''}`;
}

function branchRow(b, label) {
  const upstream = b.gone ? 'upstream gone' : b.upstream || (b.remote ? 'remote' : 'no upstream');
  return `<button class="lee-mrow lee-branch-row${b.current ? ' current' : ''}" data-branch="${esc(b.name)}">` +
    `<span class="lee-branch-mark">${b.current ? '✓' : b.remote ? '☁' : '›'}</span>` +
    `<strong>${esc(label ?? branchLeaf(b))}</strong><span class="sub">${esc(upstream)}</span>` +
    `<span class="lee-spacer"></span>${branchDrift(b)}` +
    `<span class="lee-branch-more" data-more="${esc(b.name)}" role="button" title="branch actions">•••</span></button>`;
}

function branchGroup(title, rows, fold = false) {
  if (!rows.length) return '';
  let body = rows.map(b => branchRow(b)).join('');
  if (fold) {
    const folders = new Map(), loose = [];
    for (const b of rows) {
      const name = branchFolder(b);
      if (!name) { loose.push(b); continue; }
      if (!folders.has(name)) folders.set(name, []);
      folders.get(name).push(b);
    }
    // A collapsed folder's branches are absent from the DOM rather than hidden, so the modal's
    // arrow-key walk over `.lee-mrow` never lands on a row nobody can see.
    body = loose.map(b => branchRow(b)).join('') + [...folders].map(([name, kids]) => {
      const open = gitBranchFolders.has(name) || kids.some(k => k.current);
      return `<button class="lee-mrow lee-branch-folder" data-folder="${esc(name)}">` +
        `<span class="lee-branch-mark">${open ? '▾' : '▸'}</span><strong>${esc(name)}/</strong>` +
        `<span class="sub">${kids.length}</span></button>` +
        (open ? kids.map(b => branchRow(b, branchLeaf(b).slice(name.length + 1))).join('') : '');
    }).join('');
  }
  return `<div class="lee-branch-group"><header>${esc(title)}</header>${body}</div>`;
}

async function switchBranch(d, name) {
  const b = (d.branches || []).find(x => x.name === name);
  if (!b || b.current) return leeLeft('git');
  rememberBranch(d.root, name);
  // A remote-only branch is checked out by its leaf name; Git creates the tracking branch.
  const out = (await gitDo('checkout', {branch: b.remote ? branchLeaf(b) : name})).outcome || {};
  // A switch moves HEAD, so `summary` always says so -- and that buries the one sentence that
  // matters, which is what became of work the switch had to set aside. Say it instead.
  if (out.message) { leeLog('git', 'checkout', out.message, 'ok'); status(`git checkout · ${firstLine(out.message)}`, 'ok'); }
  return out;
}

function compareBranch(d, name) {
  Object.assign(gitUI, {tab: 'review', review: null, reviewBase: d.branch, reviewHead: name});
  leeLeft('git'); leeGitRefresh();
}

function branchActions(anchor, d, b) {
  if (!b) return;
  const leaf = branchLeaf(b);
  const rows = [
    {label: `Checkout ${leaf}`, disabled: b.current, run: () => switchBranch(d, b.name)},
    {label: 'New Branch from…', detail: b.name, run: async () => {
      const branch = await inputDialog('new branch', `Branch name, starting at ${b.name}`, '', 'feature/name');
      if (branch) gitDo('create', {branch, start: b.name});
    }},
    {separator: true},
    {label: 'Compare with current', detail: `${d.branch} … ${leaf}`, disabled: b.current, run: () => compareBranch(d, b.name)},
    {label: `Rebase ${d.branch} onto ${leaf}`, disabled: b.current, run: () => gitDo('rebase', {branch: b.name})},
    {label: `Merge ${leaf} into ${d.branch}`, disabled: b.current, run: () => gitDo('merge', {branch: b.name})},
  ];
  if (!b.remote && !b.current) rows.push({separator: true}, {label: `Delete ${leaf}`, warn: true, run: async () => {
    if (await confirmDialog('delete branch', `Delete ${b.name}? Commits only on it are lost.`, 'delete'))
      gitDo('delete', {branch: b.name, force: !b.merged});
  }});
  openChromeMenu(anchor, rows);
}

function branchTopActions(d) {
  const changed = (d.changes || []).length;
  return [
    {id: 'update', label: 'Update Project', detail: d.behind ? `${d.behind} behind ${d.upstream}` : 'pull, autostashing local work'},
    {id: 'commit', label: 'Commit…', detail: changed ? `${changed} changed file${changed === 1 ? '' : 's'}` : 'working tree clean'},
    {id: 'push', label: 'Push', detail: !d.upstream ? 'publish this branch' : d.ahead ? `${d.ahead} ahead` : 'nothing to push'},
    {id: 'new', label: 'New Branch…', detail: `from ${d.branch}`},
    {id: 'revision', label: 'Checkout Tag or Revision…', detail: 'any tag, commit or branch'},
    {id: 'clone', label: 'Clone Repository…', detail: 'into a folder, then open it'},
  ];
}

function runBranchAction(id, d) {
  if (id === 'update') return gitDo('pull');
  if (id === 'push') return leeGitQuick('push');
  if (id === 'commit') { gitUI.tab = 'changes'; leeLeft('git'); return leeGitRefresh(); }
  if (id === 'clone') return leeCloneRepo();
  if (id === 'new') return inputDialog('new branch', `Branch name, starting at ${d.branch}`, '', 'feature/name')
    .then(branch => branch && gitDo('create', {branch, start: d.branch}));
  return inputDialog('checkout tag or revision', 'Tag, commit or branch', '', 'v1.2.0  ·  a1b2c3d')
    .then(ref => ref && gitDo('checkout', {branch: ref}));
}

async function leeBranchMenu(anchor) {
  let d;
  try { d = await api(gitUrl('/git/info')); }
  catch (e) { return status(e.message || String(e), 'err'); }
  const recent = recentBranches(d.root);
  let search = null;
  const m = modal(
    `<div class="lee-mhead">Git Branches<span class="sub">${esc(gitRepoName(d.root))} · on ${esc(d.branch)}</span></div>` +
    `<input class="lee-input" id="branchsearch" autocomplete="off" spellcheck="false"` +
    ` placeholder="Search branches and actions…" aria-label="search branches and actions">` +
    `<div class="lee-modallist lee-branchlist" id="branchlist"></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Enter checks out · ••• compares, rebases and merges</span></div>`,
    // The arrow keys walk the rows, which takes the caret out of the box; a printable key puts
    // it back, so searching never needs the mouse to come back first.
    e => { if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && document.activeElement !== search) search.focus(); },
    null, {className: 'lee-branchmodal', storageKey: 'branches'});
  search = m.querySelector('#branchsearch');
  const list = m.querySelector('#branchlist');

  const paint = () => {
    const q = search.value.trim().toLowerCase();
    const hit = text => !q || String(text).toLowerCase().includes(q);
    const acts = branchTopActions(d).filter(a => hit(a.label));
    const all = (d.branches || []).filter(b => hit(`${b.name} ${b.subject} ${b.author}`));
    const near = recent.map(n => all.find(b => b.name === n && !b.current)).filter(Boolean);
    const rest = all.filter(b => !near.includes(b));
    list.innerHTML =
      (acts.length ? `<div class="lee-branch-group">${acts.map(a =>
        `<button class="lee-mrow lee-branch-action" data-act="${a.id}"><strong>${esc(a.label)}</strong>` +
        `<span class="lee-spacer"></span><span class="sub">${esc(a.detail)}</span></button>`).join('')}</div>` : '') +
      branchGroup('Recent', near) +
      branchGroup('Local', rest.filter(b => !b.remote), true) +
      branchGroup('Remote', rest.filter(b => b.remote), true) ||
      '<div class="lee-dim">nothing matches</div>';
  };

  list.onclick = e => {
    const more = e.target.closest('[data-more]');
    if (more) return branchActions(more, d, (d.branches || []).find(b => b.name === more.dataset.more));
    const folder = e.target.closest('[data-folder]');
    if (folder) {
      const name = folder.dataset.folder;
      gitBranchFolders.has(name) ? gitBranchFolders.delete(name) : gitBranchFolders.add(name);
      return paint();
    }
    const row = e.target.closest('[data-branch]');
    if (row) { m.remove(); return switchBranch(d, row.dataset.branch); }
    const act = e.target.closest('[data-act]');
    if (act) { m.remove(); return runBranchAction(act.dataset.act, d); }
  };
  search.oninput = paint;
  paint();
  setTimeout(() => search.focus(), 0);
}
window.leeBranchMenu = leeBranchMenu;

/* ------------------------------------------------------------ fetch/pull/push */
async function leeGitQuick(op) {
  const button = $(`#git${op}`);
  if (button) button.disabled = true;
  try {
    // Push is the one that needs to know where it stands: an unpublished branch has nowhere
    // to push to, and saying "nothing to push" would be the wrong half of the truth.
    const publish = op === 'push' && !(gitUI.snapshot || await api(gitUrl('/git/info'))).upstream;
    await gitDo(op, op === 'push' ? {publish} : {});
    refreshScmIfOpen();
  } catch (_) { /* gitDo already logged it, showed the log, and said so in the status line */ }
  finally { if (button) button.disabled = false; }
}
window.leeGitQuick = leeGitQuick;

/* ------------------------------------------------------------------- cloning */
// Poll a clone job until it stops. The cap is there so a wedged job ends as a sentence rather
// than a spinner nothing will ever stop.
async function cloneProgress(id, say) {
  for (let i = 0; i < 900; i++) {
    await new Promise(r => setTimeout(r, 900));
    const job = await api(`/git/clone/status?job=${encodeURIComponent(id)}`);
    if (job.error) throw new Error(job.error);
    if (!job.active) return job.result || {};
    if (job.current) say.textContent = job.current;
  }
  throw new Error('the clone is still running; the jobs panel has it');
}

async function leeCloneRepo() {
  const info = await api('/workspace/info').catch(() => ({}));
  // Beside the folders that are already open, not inside one: a clone that lands *under* an
  // open folder is covered by it and can never become a chosen project of its own.
  const beside = ((info.roots || [])[0]?.path || '').split('/').slice(0, -1).join('/');
  const m = modal(
    `<div class="lee-mhead">clone repository<span class="sub">the clone becomes an open folder</span></div>` +
    `<label class="lee-fieldlabel">Repository<input class="lee-input" id="cloneurl" autocomplete="off"` +
    ` spellcheck="false" placeholder="owner/name  ·  https://…  ·  git@…"></label>` +
    `<label class="lee-fieldlabel">Into<input class="lee-input" id="cloneinto" autocomplete="off"` +
    ` spellcheck="false" value="${esc(beside)}" placeholder="a folder that already exists"></label>` +
    `<div class="lee-mfoot"><button class="lee-btn go" id="clonego">clone</button>` +
    `<span class="lee-dim" id="clonesay"></span></div>`);
  const say = m.querySelector('#clonesay'), go = m.querySelector('#clonego');
  const start = async () => {
    const url = m.querySelector('#cloneurl').value.trim();
    if (!url) return m.querySelector('#cloneurl').focus();
    go.disabled = true; say.textContent = 'starting…';
    try {
      const r = await post('/git/clone', {url, parent: m.querySelector('#cloneinto').value.trim()});
      say.textContent = `cloning into ${r.root}…`;
      const done = await cloneProgress(r.job.id, say);
      m.remove();
      // The same three steps the folder picker takes, so a clone lands where an opened folder
      // lands: added, drawn in the tree, and chosen as the project.
      await post('/fs/add-root', {path: done.root});
      await refreshFileTree(done.root);
      await activateRoot(done.root);
      status(`cloned ${done.name}`, 'ok');
    } catch (e) {
      go.disabled = false; say.textContent = '';
      status(e.message || String(e), 'err');
    }
  };
  go.onclick = start;
  m.querySelector('#cloneurl').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); start(); } };
  setTimeout(() => m.querySelector('#cloneurl').focus(), 0);
}
window.leeCloneRepo = leeCloneRepo;
