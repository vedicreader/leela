/* leela IDE client.
 *
 * Sources live with the feature they serve: `leela/blocks/<block>/*.js`, and this shared
 * vocabulary in `leela/static/js/`. `tools/build_ide_js.py` concatenates them, in the order its
 * `LAYERS` fixes, into the bundles `core.web.IDE_BUNDLES` names. Three script tags share one
 * lexical scope and run in order, so `lee`, `$` and `esc` are declared here and read by every
 * later module.
 *
 * The keymap is fetched from `/keys.json`. Dispatch is scope-aware: `lee.scope` must match or be
 * 'global', else the browser or CodeMirror keeps the chord.
 */
"use strict";

const lee = {
  keys: [], help: {}, scope: 'editor', execScope: 'live',
  editors: new Map(),        // cell id (or 'exec'/'file') -> CodeMirror view
  cells: [], sel: 0, cellSelection: new Set(), cellAnchor: 0, kind: null, path: '',
  hist: [], histIdx: 0,
  varOpen: new Set(), varPrev: {}, varStates: new Map(), varFingerprints: new Map(), varRuntime: '',
  term: null, terms: new Map(), activeTerm: '', termSeq: 0,
  cellObserver: null, cellMountTimer: 0, cellsOwed: null, lastDoc: null, buffers: new Map(), dirtyBuffers: new Set(), bufferTimers: new Map(),
  autoSaveTimer: null, saving: false, editVersion: 0, collapsedCells: new Set(), fileGit: null,
  diskVersion: '', seenDiskVersion: '', watchingDisk: false,
  breakpoints: new Map(), debugThread: null, debugCell: null, debugState: null, directDebug: false, debugWatches: [],
  shownProblems: new Set(),   // agent failures already written into the pane, so they show once
  agentAttachments: new Map(), agentSuggest: [], agentSuggestAt: 0, agentVocabulary: null, stateSuggestions: [],
  agentStream: null, agentStreamGen: 0, agentTitle: '', agentThread: '',
  agentThreadDrafts: new Map(),
  find: null,                  // the find pane's query, its matches and where it is
  // Highlighted ranges queued for the next turn. Kept apart from `agentAttachments`, a path->name
  // map, because two selections in one file are two contexts rather than one key overwritten.
  agentSelections: [],
  // Vault documents and sections queued for the next turn. A vault ref is not a path, so `ref` ->
  // {vault, shelf, doc, title} is keyed separately.
  vaultRefs: new Map(),
  cellClipboard: null,       // detached cell payload; survives tab switches for cross-notebook moves
  recentTabs: [], locations: new Map(), recentCycle: [], recentCycleAt: 0, researchDocs: [], researchSelected: new Set(),
  draftBases: new Map(), draftTimers: new Map(), heldSaveConflicts: new Set(),
  editorPrefs: null, settingsMeta: null, filePrefs: {}, workbenchPrefs: {}, debugPrefs: {}, backupPrefs: {},
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
  // Snippet surfaces in rendered markdown are not in `lee.editors`, and are no longer rebuilt on
  // the next render, so this is the only thing that reaches them. `overviewMode` stays off: a
  // read-only block a few lines long has nothing to draw a stripe of.
  for (const view of codeSurfaceViews()) LeeCM.configure?.(view, {...p, overviewMode: 'off'});
  if (persist) localStorage.setItem('lee-editor-settings', JSON.stringify(p));
  return p;
}
async function loadSettings(language = '') {
  try {
    const d = await api('/settings?language=' + encodeURIComponent(language));
    lee.settingsMeta = d; lee.filePrefs = d.effective.files || {};
    lee.workbenchPrefs = d.effective.workbench || {}; lee.debugPrefs = d.effective.debug || {};
    lee.backupPrefs = d.effective.backups || {}; lee.agentPrefs = d.effective.agent || {};
    applyEditorPrefs(d.effective.editor || EDITOR_DEFAULTS);
  } catch (_) { applyEditorPrefs(lee.editorPrefs); }
}
applyEditorPrefs(lee.editorPrefs);
/* macOS hands a `contenteditable` to its own text checker, and WKWebView takes it up where a
   browser does not: the packaged app curled quotes, corrected identifiers and, because the rewrite
   lands behind CodeMirror's back, dropped the next character typed at the start of the line. The
   served workspace never did any of it, which is why this only ever looked like a Mac-app bug.
   Set on the view rather than in the CodeMirror build, because `frontend/editor.js` needs esbuild
   and the bundle is committed; CodeMirror only clears attributes it set itself, so these survive.
   `leela/desktop.py:quiet_text_substitution` turns the same thing off one layer down. */
const TYPING_ATTRS = {spellcheck: 'false', autocorrect: 'off', autocapitalize: 'off',
                      'data-gramm': 'false'};
function quietTyping(view) {
  try { for (const [k, v] of Object.entries(TYPING_ATTRS)) view.contentDOM.setAttribute(k, v); }
  catch (_) { /* a view torn down before it was ever drawn */ }
  return view;
}
function createEditor(el, opts = {}) {
  return quietTyping(LeeCM.create(el, {...opts, settings: {...lee.editorPrefs, ...(opts.settings||{})}}));
}
// A merge is two editors, and the writable one is `b`. Both, so a selection copied out of the
// read-only side is the bytes on disk and not the system's idea of them.
function createMerge(el, opts = {}) {
  const merge = LeeCM.createMerge(el, opts);
  quietTyping(merge.a); quietTyping(merge.b);
  return merge;
}
try { lee.recentTabs = JSON.parse(sessionStorage.getItem('lee-recent-tabs') || '[]'); }
catch (_) { lee.recentTabs = []; }
// The caret in each file, across restarts, so `localStorage` rather than `sessionStorage`, which
// dies with the window. Capped where it is written.
try { lee.locations = new Map(JSON.parse(localStorage.getItem('lee-tab-locations')
                                         || sessionStorage.getItem('lee-tab-locations') || '[]')); }
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
  // A draft belongs to the version of the file it was typed over. Cell ids survive a rewrite, so a
  // draft left from an earlier version lands back on the file that replaced it, and recovering it
  // is what suppresses the reload that would have shown the new text.
  const current = rows.filter(r => !(r.baseDiskVersion && st.disk_version && r.baseDiskVersion !== st.disk_version));
  if (!current.length) {
    await clearDrafts(documentKey);
    status(`${documentKey.split('/').pop()}: discarded a draft of an older version of the file`, 'err');
    return false;
  }
  rows = current;

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
//: The languages Leela serves a language server and a runtime for. Mirrors `LANGS` in
//: `leela/core/langs.py`; `tests/test_langs.py` checks the two still agree.
const LSP_LANGS = ['python', 'rust', 'javascript', 'typescript'];
const nbLang = () => lee.nbLang || 'python';
const servedLang = (l) => LSP_LANGS.includes(String(l || ''));

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
  shell.append(head, editor); host.appendChild(shell);
  /* No overview stripe on a snippet. It is a read-only block a few lines long, a minimap of it says
     nothing, and the stripe is what hides and unhides the block's own scroll bar as it decides
     whether it is needed. A page of rendered markdown holds dozens of these. */
  const view = createEditor(editor, {doc: String(code || ''), lang: codeLang(lang), readOnly: true,
                                     lineNums: true, settings: {overviewMode: 'off'}});
  head.querySelector('[data-copy]').onclick = () => {
    navigator.clipboard?.writeText(String(code || '')); status('code copied', 'ok');
  };
  head.querySelector('[data-promote]')?.addEventListener('click', () => promoteCodeToNotebook(String(code || ''), codeLang(lang)));
  shell._leeView = view;    // `enhanceCodeBlocks` re-parents the shell, and needs its view back
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
  if (['run_python', 'inspect_python', 'list_vars', 'inspect_var', 'run_cell'].includes(tool)) return 'run';
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
  if (tool === 'inspect_var') return `Inspect var · ${short(a.name)}`;
  if (tool === 'run_cell') return `Run cell · ${compactPath(a.path)} ${short(a.cell_id)}`;
  if (tool === 'web_search') return `Search web · ${short(a.query).slice(0, 92)}`;
  if (tool === 'read_url') return `Read web · ${short(a.url).slice(0, 92)}`;
  const body = Object.entries(a).slice(0, 2).map(([k, v]) => `${k}: ${short(v).slice(0, 54)}`).join(' · ');
  return `${tool.replaceAll('_', ' ')}${body ? ' · ' + body : ''}`;
}
function polishActivityGroup(el) {
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
/* The fold a step row replaces. Only a `result` fold holding this one block goes with it: climbing to
   the nearest `<details>` regardless took the whole "what I did" group, summary and later steps
   included, and left the rest of the loop working on nodes already off the page. */
function payloadContainer(code) {
  const pre = code.parentElement, fold = pre.closest('details');
  if (!fold) return pre;
  const body = [...fold.children].filter(n => n.tagName !== 'SUMMARY');
  const label = fold.querySelector(':scope > summary')?.textContent || '';
  return body.length === 1 && body[0] === pre && /^\s*result\b/i.test(label) ? fold : pre;
}
function upgradePortableToolMarkdown(el) {
  $$('pre > code', el).forEach(code => {
    if (!code.isConnected) return;
    const payload = portableToolPayload(code.textContent || ''); if (!payload) return;
    const row = document.createElement('details');
    renderAgentStep(row, {...payload, kind: portableToolKind(payload.tool), done: true, ok: true, secs: 0,
                          summary: portableToolSummary(payload.tool, payload.args)});
    payloadContainer(code).replaceWith(row);
  });
  $$('li', el).forEach(li => {
    if (/[⏳⌛]/u.test(li.textContent || '') && li.querySelector('code')) li.remove();
  });
  polishActivityGroup(el);
}
/* A streaming reply is re-rendered whole on every pass, and this used to destroy every code surface
   in it and build them all again. Measured on one nine-second turn ending in eight code blocks: 455
   CodeMirror views constructed, 447 thrown away, 1.7s of main thread, in the faster of the two
   engines Leela runs in. The surfaces are kept and re-parented instead, keyed by the code they
   hold, so a pass builds only the block whose text actually moved. `tools/profile_agent.py`. */
// The length is in the key so the parts cannot run together: no separator is safe inside code.
const codeKey = (lang, n, text) => `${lang}:${n}:${text.length}:${text}`;
/* Every snippet view on the page, read from the DOM rather than from a registry: a surface lives
   exactly as long as its shell, so the document is the register and nothing in it can go stale.
   `querySelectorAll` rather than `$$`, because `applyEditorPrefs` calls this at load, above the
   line `$$` is declared on, and reading a `const` before it is initialised throws. */
function codeSurfaceViews(root = document) {
  return [...root.querySelectorAll('.lee-code-surface')].map(s => s._leeView).filter(Boolean);
}
/* Reuse means the views under a subtree outlive the render that built them, so a caller that throws
   that subtree away has to say so. Every `innerHTML = ''` over rendered markdown is one of those. */
function dropCodeSurfaces(root) {
  if (!root) return;
  for (const el of [root, ...root.querySelectorAll('[data-markdown]')]) {
    for (const shell of (el._leeCodeSurfaces || new Map()).values())
      try { LeeCM.destroy(shell._leeView); } catch {}
    el._leeCodeSurfaces = new Map(); el._leeCodeViews = [];
  }
}
function enhanceCodeBlocks(el) {
  const held = el._leeCodeSurfaces instanceof Map ? el._leeCodeSurfaces : new Map();
  const kept = new Map(), seen = new Map();
  $$('pre > code', el).forEach(code => {
    const pre = code.parentElement, text = code.textContent || '';
    const declared = [...code.classList].find(x => x.startsWith('language-')) || '';
    const lang = codeLang(declared);
    const python = /^(language-)?(py|python)$/.test(declared.toLowerCase());
    const named = declared.replace(/^language-/, '').toLowerCase();
    if (!declared || !CODE_LANGS[named] || text.length > 40000) return;
    // Two blocks holding the same code are two surfaces, so the count is part of the key. Counted
    // per language, as the key is: counting on the text alone renumbered a Python block because a
    // shell block above it happened to hold the same characters.
    const n = (seen.get(codeKey(lang, 0, text)) || 0) + 1; seen.set(codeKey(lang, 0, text), n);
    const key = codeKey(lang, n, text);
    const host = document.createElement('div'); pre.replaceWith(host);
    const shell = held.get(key);
    if (shell && shell._leeView) {
      host.appendChild(shell); kept.set(key, shell);
      // It was measured while detached, or in a pane of another width.
      try { shell._leeView.requestMeasure(); } catch (_) { /* torn down under us */ }
      return;
    }
    const view = mountCodeSurface(host, text.replace(/\n$/, ''), lang,
                                  python && el.classList.contains('lee-reply'));
    const built = view && view.dom.closest('.lee-code-surface');
    if (built) kept.set(key, built);
  });
  for (const [key, shell] of held)
    if (!kept.has(key)) try { LeeCM.destroy(shell._leeView); } catch {}
  el._leeCodeSurfaces = kept;
  el._leeCodeViews = [...kept.values()].map(s => s._leeView);
}
/* This copies an answer into the open notebook, so it needs one. Hidden rather than disabled, and
   back the moment a notebook tab is focused. */
function markdownCellActionState(button) {
  const ready = lee.kind === 'notebook';
  const bar = button.closest('.lee-reply-actions') || button;
  bar.hidden = !ready;
  button.disabled = !ready;
  button.title = 'insert this as a markdown cell in the open notebook';
}
function refreshMarkdownCellActions() { $$('.lee-reply-actions button').forEach(markdownCellActionState); }
function addMarkdownCellAction(el) {
  if (!el.dataset.markdown.trim() ||
      (!el.classList.contains('lee-reply') && !el.classList.contains('lee-md-output'))) return;
  const bar = document.createElement('footer'); bar.className = 'lee-reply-actions';
  const button = document.createElement('button'); button.type = 'button';
  button.textContent = el.classList.contains('lee-reply')
    ? 'edit response as markdown cell' : 'edit as markdown cell';
  button.onclick = () => promoteCodeToNotebook(el.dataset.markdown, 'markdown');
  markdownCellActionState(button);
  bar.appendChild(button); el.appendChild(bar);
}

function resolveMarkdownImages(el) {
  const base = el.closest('[data-md-base]')?.dataset.mdBase || '';
  $$('img', el).forEach(img => {
    const src = img.getAttribute('src') || '';
    if (!src || /^(https?:|data:|blob:|\/file\/raw)/.test(src)) return;
    if (!src.startsWith('/') && !base) return;
    // `..` and `.` are resolved by URL, so a path cannot climb out through the query string.
    const abs = src.startsWith('/') ? src : new URL(src, 'file://' + base + '/').pathname;
    img.src = '/file/raw/' + encodeURIComponent(abs.split('/').pop()) + '?path=' + encodeURIComponent(abs);
    img.loading = 'lazy';
  });
}

/* pywebview injects its bridge asynchronously, so `window.pywebview` is undefined for the first
   moment of a packaged app's life. `lee.inShell` is what `shellReady` settled on; until it does,
   a `window.open` that comes back null is itself the answer, because WKWebView refuses a scripted
   one. Getting this wrong navigated the whole app window to the site, with no way back. */
const inDesktopShell = () => Boolean(window.pywebview || lee.inShell);

async function openExternal(url) {
  if (!url) return status('choose a source first', 'err');
  if (!inDesktopShell() && window.open(url, '_blank', 'noopener,noreferrer')) return;
  try { await post('/browser/external', {url}); }
  catch (e) { status(`could not open ${url}: ${e.message || e}`, 'err'); }
}

function routeMarkdownLinks(el) {
  $$('a[href]', el).forEach(a => {
    const href = a.getAttribute('href') || '';
    if (!/^https?:/i.test(href) || a.dataset.leeLink) return;
    a.dataset.leeLink = '1'; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.addEventListener('click', e => {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;  // the browser's to handle
      e.preventDefault(); e.stopPropagation();
      if (inDesktopShell()) return openExternal(href);
      if (!window.open(href, '_blank', 'noopener,noreferrer')) openExternal(href);
    });
  });
}

/* A prompt cell stores its work log twice: as `calls`, and again at the end of `reply`. The renderer
   has no raw HTML, so the second copy read as literal `<details>` tags over an unrolled result. */
const WORK_LOG = /\n*<details>\s*<summary>\s*what i did[^<]*<\/summary>[\s\S]*<\/details>\s*$/i;
function stripWorkLog(text) { return String(text || '').replace(WORK_LOG, '').trimEnd(); }

/* `delay` is the floor between renders. 32ms is right for a preview following a person's typing;
   a reply streaming from a model is re-rendered whole on every pass, so the agent pane asks for a
   longer one. See `AGENT_RENDER_GAP` in `blocks/agent/media.js`. */
function renderMarkdown(el, text, allowRaw = false, onRender = null, delay = 32) {
  if (!el) return;
  el.dataset.markdown = String(text || '');
  /* A render already on the wire is left to land. It used to be aborted on every call, so a
     reply streaming faster than one round trip repainted only when the model paused: each chunk
     cancelled the render the one before it had started. One request at a time now, and a follow-up
     when the text moved on while it was out. */
  if (el._leeMarkdownBusy) { el._leeMarkdownDirty = true; return; }
  /* At most one render every `delay`, and at least one: this used to restart the wait on every
     call, so text arriving faster than the gap held the render off for as long as it kept coming.
     The pending one reads `dataset.markdown` when it fires, so it always renders the latest. */
  if (el._leeMarkdownTimer) return;
  el._leeMarkdownTimer = setTimeout(async () => {
    el._leeMarkdownTimer = 0; el._leeMarkdownBusy = true; el._leeMarkdownDirty = false;
    const sent = el.dataset.markdown;
    try {
      const r = await fetch('/markdown/render', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: sent, allow_raw: allowRaw})});
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      const d = await r.json(); if (!el.isConnected) return;
      el.innerHTML = d.html;
      if (d.warnings?.length) el.dataset.markdownWarnings = d.warnings.join(' · ');
      else delete el.dataset.markdownWarnings;
      if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
      el._leeCodeFrame = requestAnimationFrame(() => {
        el._leeCodeFrame = 0;
        if (onRender) try { onRender(el); } catch (e) { console.warn('Leela markdown annotation:', e); }
        resolveMarkdownImages(el); routeMarkdownLinks(el);
        upgradePortableToolMarkdown(el); enhanceCodeBlocks(el); addMarkdownCellAction(el);
        // Only now is the text on the page. Anything that measures the result waits for this.
        el.dispatchEvent(new CustomEvent('lee-markdown-rendered', {bubbles: true}));
      });
    } catch (e) {
      if (!el.isConnected || el.dataset.markdown !== sent) return;
      el.textContent = el.dataset.markdown;
      el.dataset.markdownWarnings = `renderer unavailable: ${e.message || e}`;
      if (!el._leeMarkdownReported) {
        el._leeMarkdownReported = true;
        console.warn('Leela markdown fallback:', e);
      }
    } finally {
      el._leeMarkdownBusy = false;
      // the text moved on while this one was out, so the screen is a render behind
      if (el._leeMarkdownDirty || el.dataset.markdown !== sent)
        renderMarkdown(el, el.dataset.markdown, allowRaw, onRender, delay);
    }
  }, delay);
}

async function api(url, opts, retried) {
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (r.ok) return body;
  /* The kernel ceiling is the one failure a person can answer. Offer the room, then try once more. */
  if (!retried && body && body.kernel_limit && await offerKernelRoom(body)) return api(url, opts, true);
  /* Thread-aware routes answer with `code` and `message`, the rest with `error`. Either is the one
     sentence a person can act on, and `statusText` ("Conflict") never is. */
  throw new Error((body && (body.error || body.message)) || r.statusText);
}
const post = (url, data) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                      body: JSON.stringify(data || {})});

async function postEvents(url, data, onEvent, signal = null) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify(data || {}), signal});
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
  el.className = `lee-status ${tone}`;
  requestAnimationFrame(() => el.classList.add('show'));
  const ttl = tone === 'busy' ? 0 : tone === 'err' ? 8000 : tone === 'ok' ? 3200 : 5000;
  if (ttl) statusTimer = setTimeout(() => {
    if (el.textContent !== msg) return;
    el.classList.remove('show');
    setTimeout(() => { if (el.textContent === msg) { el.textContent = ''; el.hidden = true; } }, 220);
  }, ttl);
}

