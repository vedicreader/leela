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
  // `?observer=1` is the agent looking at this UI from its own tab: it reads, and changes nothing.
  observer: new URLSearchParams(location.search).get('observer') === '1',
  keys: [], help: {}, scope: 'editor', execScope: 'live',
  editors: new Map(),        // cell id (or 'exec'/'file') -> CodeMirror view
  cells: [], sel: 0, cellSelection: new Set(), cellAnchor: 0, kind: null, path: '',
  rise: {}, present: null,   // the notebook's RISE settings, and the open slide deck
  hist: [], histIdx: 0,
  varOpen: new Set(), varPrev: {}, varStates: new Map(), varFingerprints: new Map(), varRuntime: '',
  term: null, terms: new Map(), activeTerm: '', termSeq: 0,
  cellObserver: null, cellMountTimer: 0, cellsOwed: null, lastDoc: null, buffers: new Map(), dirtyBuffers: new Set(), bufferTimers: new Map(),
  autoSaveTimer: null, saving: false, editVersion: 0, collapsedCells: new Set(), fileGit: null,
  headingHidden: new Set(), headingSync: new Map(),   // ids a folded heading hides, and each tab's chain of fold writes
  headingFolds: new Map(),   // tab -> cell id -> a fold the state the page holds may predate
  nbQueue: Promise.resolve(), nbLate: new Map(), nbVersions: new Map(), mountedAt: 0, srcSeq: 0,   // see `nbEdit`
  tabEdits: new Map(),   // tab -> how many changes `markDirty` has counted, for a save to tell whether it holds them all
  diskVersion: '', seenDiskVersion: '', watchingDisk: false,
  // `diskVersion` is the tab on screen. A split pane holds a second file, whose version is its
  // own: basing that pane's draft on the tab's version made every save look like somebody
  // else's write. Keyed by path, and `diskVersion` stays the one the rest of the editor reads.
  diskVersions: new Map(),
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
/* A preference that outlives this origin.

   `localStorage` is per origin, and the app's port moves, so a preference kept only there is empty
   at the next launch and reads as its default: notifications a person switched on came back off,
   and nobody could tell it from never having asked. These read settings.json, cache in
   `localStorage` for the paint before the settings arrive, and write through.
*/
function prefGet(section, key, fallback = undefined) {
  const held = lee.prefs?.[section];
  if (held && held[key] !== undefined && held[key] !== '') return held[key];
  const cached = localStorage.getItem(`lee-pref:${section}.${key}`);
  if (cached !== null) { try { return JSON.parse(cached); } catch (_) {} }
  return fallback;
}
async function prefSet(section, key, value, scope = 'user') {
  if (lee.observer) return;
  lee.prefs = {...lee.prefs, [section]: {...(lee.prefs?.[section] || {}), [key]: value}};
  localStorage.setItem(`lee-pref:${section}.${key}`, JSON.stringify(value));
  // Never the caller's problem: a preference that could not be written is not a failed action.
  try { await post('/settings/save', {scope, section, language: '', values: {[key]: value}}); }
  catch (_) {}
}
/* One migration per key: what the old per-origin key held becomes the durable one, once, and only
   where nothing durable was ever saved. Dropping it would silently reset everyone who has one.

   Asked of `origins`, not of the value: `/settings` merges the defaults into `effective`, so every
   key is always present and a never-saved one is told apart only by where it came from. No origins
   means the settings have not arrived, and migrating against them would race the answer. */
async function prefAdopt(section, key, legacyKey, parse = v => v) {
  if (lee.settingsMeta?.origins?.[section]?.[key] !== 'default') return;
  const old = localStorage.getItem(legacyKey);
  if (old === null) return;
  await prefSet(section, key, parse(old));
}
async function loadSettings(language = '') {
  try {
    const d = await api('/settings?language=' + encodeURIComponent(language));
    lee.settingsMeta = d; lee.filePrefs = d.effective.files || {};
    lee.workbenchPrefs = d.effective.workbench || {}; lee.debugPrefs = d.effective.debug || {};
    lee.backupPrefs = d.effective.backups || {}; lee.agentPrefs = d.effective.agent || {};
    lee.prefs = d.effective || {}; lee.appearancePrefs = d.effective.appearance || {};
    applyEditorPrefs(d.effective.editor || EDITOR_DEFAULTS);
  } catch (_) { applyEditorPrefs(lee.editorPrefs); }
}
applyEditorPrefs(lee.editorPrefs);
/* macOS hands a `contenteditable` to its own text checker, and WKWebView takes it up where a
   browser does not: the packaged app curled quotes, corrected identifiers and, because the rewrite
   lands behind CodeMirror's back, dropped the next character typed at the start of the line. The
   served workspace never did any of it, which is why this only ever looked like a Mac-app bug.
   `writingsuggestions` is the newer half of the same problem: an inline prediction is accepted with
   Tab, so the Tab meant for the completion list was taken by the system, which rewrote the line and
   left the caret at the start of it. `spellcheck` and `autocorrect` do not cover it.
   Set on the view rather than in the CodeMirror build, because `frontend/editor.js` needs esbuild
   and the bundle is committed; CodeMirror only clears attributes it set itself, so these survive.
   `leela/desktop.py:quiet_text_substitution` turns the same thing off one layer down. */
const TYPING_ATTRS = {spellcheck: 'false', autocorrect: 'off', autocapitalize: 'off',
                      'data-gramm': 'false', writingsuggestions: 'false'};
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
function recordDiskVersion(path, version) {
  "The version `path` is now at on disk. The tab on screen also moves the globals the editor reads."
  if (!path || !version) return version || '';
  lee.diskVersions.set(path, version);
  if (path === (lee.path || lee.tabKey)) { lee.diskVersion = version; lee.seenDiskVersion = version; }
  return version;
}
function diskVersionFor(documentKey) {
  "What `documentKey` was last seen at, falling back to the tab's own version for the tab itself."
  return lee.diskVersions.get(documentKey) || (documentKey === (lee.path || lee.tabKey) ? lee.diskVersion : '') || '';
}
function draftBaseFor(documentKey) {
  const values = [...lee.draftBases].filter(([key]) => key === documentKey || key.startsWith(documentKey + ':'))
    .map(([, value]) => value).filter(Boolean);
  return values[0] || diskVersionFor(documentKey) || '';
}
function writeDraftNow(key, payload) {
  const documentKey = payload.path || payload.title || lee.tabKey || key;
  if (!documentKey) return;
  const draftKey = payload.kind === 'notebook' ? `${documentKey}:${payload.id || payload.i}` : documentKey;
  if (!lee.draftBases.has(draftKey)) lee.draftBases.set(draftKey, diskVersionFor(documentKey) || '');
  draftPut({key: draftKey, document: documentKey, payload, baseDiskVersion: lee.draftBases.get(draftKey),
            updatedAt: Date.now()}).catch(() => {});
}
function persistDraft(key, payload) {
  const documentKey = payload.path || payload.title || lee.tabKey || key;
  if (!documentKey) return;
  const draftKey = payload.kind === 'notebook' ? `${documentKey}:${payload.id || payload.i}` : documentKey;
  if (!lee.draftBases.has(draftKey)) lee.draftBases.set(draftKey, diskVersionFor(documentKey) || '');
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
//: A stamp on every source write the page sends, so the server keeps the newest of two that arrive out of order.
const nextSeq = () => lee.srcSeq = Math.max(lee.srcSeq + 1, Date.now());
const headingSynced = (key = lee.tabKey) => lee.headingSync.get(key) || Promise.resolve();
async function restoreDrafts(st) {
  if (lee.observer) return false;   // the drafts are the person's, in storage this origin shares
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

/* A read about the tab on screen (language server, lint, git marks, outline) ends with that tab: each one
   holds a connection of the browser's six per host, and a slow one left the next `/tab/select` queued. */
const TAB_READS = /^\/(lsp\/(symbols|inlay-hints|hover)|lint|git\/file|outline|editor\/packages)(\?|$)/;
lee.tabReads = new AbortController();
const pageFetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => !opts.signal && typeof url === 'string' && TAB_READS.test(url)
  ? pageFetch(url, {...opts, signal: lee.tabReads.signal}) : pageFetch(url, opts);
function dropTabReads() { lee.tabReads.abort(); lee.tabReads = new AbortController(); }

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
  if (!await nbEdit({op: 'insert', i: at, source: code, cell_type: lang === 'markdown' ? 'markdown' : 'code'})) return;
  focusCell(at); status(`promoted to cell ${at + 1}`, 'ok');
}
const SNIPPET_LINES = 2000;
/* Running any command is a terminal's power, so a snippet run takes the terminal's token. */
async function runSnippet(surface, button, code) {
  const held = button._leeRun;
  if (held) return post(`/agent/shell/${encodeURIComponent(held.run)}/stop?thread=${encodeURIComponent(held.thread)}`)
    .catch(e => status(e.message || String(e), 'err'));
  let out = surface.querySelector('.lee-code-run');
  if (!out) { out = document.createElement('pre'); out.className = 'lee-code-run'; surface.appendChild(out); }
  out.textContent = ''; out.classList.remove('err'); button.disabled = true;
  let run = null, done = false;
  try {
    const term = await api('/term/info');
    if (!term.token) throw new Error(term.why || 'terminals are off here');
    run = button._leeRun = await post('/agent/shell-run', {thread: lee.agentThread || '', command: code, token: term.token});
    button.textContent = 'stop'; button.disabled = false;
    let since = 0, text = '', away = 0;
    while (away < 2) {   // a re-render detaches a kept surface for a frame, so one miss is not a teardown
      const d = await api(`/agent/runs/${encodeURIComponent(run.run)}/log?since=${since}&thread=${encodeURIComponent(run.thread)}`);
      since = d.since; text = (text + d.text).split('\n').slice(-SNIPPET_LINES).join('\n');
      out.textContent = d.done ? `${text}${text && !text.endsWith('\n') ? '\n' : ''}${d.state}` : text;
      if ((done = d.done)) { out.classList.toggle('err', d.state !== 'exit 0'); break; }
      await new Promise(r => setTimeout(r, 500));
      away = surface.isConnected ? 0 : away + 1;
    }
  } catch (e) { out.textContent += `${out.textContent ? '\n' : ''}${e.message || e}`; out.classList.add('err'); }
  finally {
    if (run && !done) post(`/agent/shell/${encodeURIComponent(run.run)}/stop?thread=${encodeURIComponent(run.thread)}`).catch(() => {});
    button._leeRun = null; button.textContent = 'run'; button.disabled = false;
  }
}
function mountCodeSurface(host, code, lang = 'python', promote = false, run = false) {
  // Not a `section`: reveal.js reads any section inside a slide as a stack of slides.
  const shell = document.createElement('div'); shell.className = 'lee-code-surface';
  const head = document.createElement('header'); head.className = 'lee-code-head';
  head.innerHTML = `<span>${esc(lang)}</span><span class="lee-spacer"></span>` +
    `<button type="button" data-copy>copy</button>` +
    (run ? `<button type="button" data-shell-run>run</button>` : '') +
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
  head.querySelector('[data-shell-run]')?.addEventListener('click', e => runSnippet(shell, e.currentTarget, String(code || '')));
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
  if (['search_code', 'similar_code', 'outline', 'ls'].includes(tool)) return 'search';
  if (['view_file', 'view_cell', 'notebook_cells', 'read_terminal'].includes(tool)) return 'view';
  if (['edit_file', 'create_file', 'edit_cell', 'add_cell'].includes(tool)) return 'edit';
  if (['web_search', 'read_url', 'research'].includes(tool)) return 'web';
  if (['run_python', 'inspect_python', 'run_cell'].includes(tool)) return 'run';
  if (tool === 'read_skill') return 'skill';
  if (tool.startsWith('delegate_')) return 'delegate';
  return 'tool';
}
function portableToolSummary(tool, args) {
  const a = args || {}, short = value => (typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value || '')).replace(/\s+/g, ' ').trim();
  if (tool === 'search_code') return `Search code · ${short(a.query).slice(0, 92)}`;
  if (tool === 'view_file') {
    const range = a.start || a.end ? `:${a.start || 1}–${a.end || 'end'}` : '';
    return `Read · ${compactPath(a.path)}${range}`;
  }
  if (tool === 'read_skill') return `Load skill · ${short(a.name)}`;
  if (tool === 'ls') return `Scan files · ${short(a.path) || '.'}${a.pattern ? ' ' + short(a.pattern) : ''}`;
  if (tool === 'run_python') return `Run Python · ${short(a.code).split(';')[0].slice(0, 82)}`;
  if (tool === 'inspect_python') return `Inspect · ${short(a.code).split(';')[0].slice(0, 82)}`;
  if (tool === 'run_cell') return `Run cell · ${compactPath(a.path)} ${short(a.cell_id)}`;
  if (tool === 'web_search') return `Search web · ${short(a.query).slice(0, 92)}`;
  if (tool === 'read_url') return `Read web · ${short(a.url).slice(0, 92)}`;
  const body = Object.entries(a).slice(0, 2).map(([k, v]) => `${k}: ${short(v).slice(0, 54)}`).join(' · ');
  return `${tool.replaceAll('_', ' ')}${body ? ' · ' + body : ''}`;
}
const activitySummary = (title, count) => `<span class="lee-activity-title">${title}</span>` +
  `<span class="lee-activity-count">${count}</span><span class="lee-agent-step-chevron" aria-hidden="true"></span>`;
function activityGroup(title, count, cls = '') {
  const group = document.createElement('details'), list = document.createElement('section');
  group.className = `lee-activity-group ${cls}`.trim(); list.className = 'lee-activity-list';
  group.innerHTML = `<summary>${activitySummary(title, count)}</summary>`; group.appendChild(list);
  return group;
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
    summary.innerHTML = activitySummary('Work log', `${count} ${count === 1 ? 'step' : 'steps'}`);
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
                                  python && el.classList.contains('lee-reply'),
                                  /^(sh|bash|shell|zsh|fish)$/.test(named) && !!el.closest('#agentlog'));
    const built = view && view.dom.closest('.lee-code-surface');
    if (built) kept.set(key, built);
  });
  for (const [key, shell] of held)
    if (!kept.has(key)) try { LeeCM.destroy(shell._leeView); } catch {}
  el._leeCodeSurfaces = kept;
  el._leeCodeViews = [...kept.values()].map(s => s._leeView);
}
const RUPAKA_MIME = 'application/vnd.rupaka+json';
const rupaka = {hosts: new Map(), passes: new Map(), load: null, sheet: null, seq: 0};
//: One promise, failure included: a missing bundle is one error line, not a refetch on every render. `retry` is the only way out.
function loadRupaka(retry = false) {
  if (retry) rupaka.load = null;
  return rupaka.load ||= (async () => {
    const css = fetch($('meta[name="lee-rupaka-css"]')?.content || '/leestatic/lee-rupaka.css')
      .then(r => r.ok ? r.text() : Promise.reject(new Error(`rupaka.css: ${r.status} ${r.statusText}`)));
    const js = window.Rupaka ? 0 : new Promise((ok, no) => {
      const s = document.createElement('script');
      s.src = $('meta[name="lee-rupaka-src"]')?.content || '/leestatic/lee-rupaka.js';
      s.onload = ok; s.onerror = () => { s.remove(); no(new Error('rupaka.js could not be loaded')); };
      document.head.appendChild(s);
    });
    return (await Promise.all([css, js]))[0];
  })();
}
//: rupaka's sizes are fixed px for a reading page; in Leela a demo takes the IDE's text and button sizes. Its fonts come from `--serif` and `--head` on `.lee-rupaka`.
const RUPAKA_LEE = `.rk{font-size:var(--lee-code-size);line-height:1.6}.rk-title{font-size:calc(var(--lee-code-size) + 3px)}
.rk-lbl,.rk kbd{font-size:var(--lee-size-min)}.rk-note,.rk-gate .verdict,.rk-gate .verdict .stale,.rk-gate textarea{font-size:inherit}
.rk button{font:inherit;font-size:11px;line-height:1.4;padding:3px 10px}`;
function rupakaStyle(root, css) {
  const text = css + RUPAKA_LEE + ':host{display:block}';
  if (!('adoptedStyleSheets' in root)) return root.prepend(Object.assign(document.createElement('style'), {textContent: text}));
  if (!rupaka.sheet) { rupaka.sheet = new CSSStyleSheet(); rupaka.sheet.replaceSync(text); }
  root.adoptedStyleSheets = [rupaka.sheet];
}
const rupakaErr = e => Object.assign(document.createElement('p'), {className: 'lee-rk-err', textContent: `rupaka: ${e.message || e}`});
const rupakaPass = owner => { const p = {owner, gen: ++rupaka.seq}; rupaka.passes.set(owner, p); return p; };
//: Hosts of `owner` that the pass did not touch are gone from the page, as `widgetSweep` does for widgets.
function rupakaSweep(p) {
  for (const [k, e] of rupaka.hosts) if (e.owner === p.owner && e.gen !== p.gen) rupaka.hosts.delete(k);
  if (rupaka.passes.get(p.owner) === p) rupaka.passes.delete(p.owner);
}
//: A host is kept under `key` so a re-render hands back the one already mounted, state intact; no key mounts fresh.
function rupakaDraw(spec, key = null, pass = null) {
  let e = key && rupaka.hosts.get(key);
  if (!e) {
    const host = Object.assign(document.createElement('div'), {className: 'lee-rupaka'}), inner = document.createElement('div');
    host.attachShadow({mode: 'open'}).append(inner);
    e = {host, ok: false, err: null, owner: pass?.owner};
    e.done = loadRupaka().then(css => { rupakaStyle(host.shadowRoot, css); window.Rupaka.mount(inner, spec); e.ok = true; })
      .catch(err => { e.err = err; });
    if (key) rupaka.hosts.set(key, e);
  }
  if (pass) e.gen = pass.gen;
  return e;
}
const katexLoad = {p: null};
//: One promise, failure included: a missing bundle is one console warning and the TeX left as text, never a refetch per render.
function loadKatex() {
  return katexLoad.p ||= new Promise((ok, no) => {
    if (window.katex) return ok(window.katex);
    document.head.appendChild(Object.assign(document.createElement('link'), {rel: 'stylesheet',
      href: $('meta[name="lee-katex-css"]')?.content || '/leestatic/katex/katex.min.css'}));
    const s = document.createElement('script');
    s.src = $('meta[name="lee-katex-src"]')?.content || '/leestatic/katex/katex.min.js';
    s.onload = () => window.katex ? ok(window.katex) : no(new Error('katex.js defined no katex'));
    s.onerror = () => { s.remove(); no(new Error('katex.js could not be loaded')); };
    document.head.appendChild(s);
  }).catch(e => { console.warn('Leela math:', e); return null; });
}
//: Fills each `span.math` and `div.math` of `el` in place, so the carriers a diff counts stay the same nodes. A promise while any is pending, else nothing.
function renderMath(el) {
  const todo = $$('span.math:not([data-mathed]), div.math:not([data-mathed])', el);
  if (!todo.length) return null;
  return loadKatex().then(k => k && todo.forEach(m => {
    if (!m.isConnected || m.dataset.mathed) return;
    m.dataset.mathed = '1';
    k.render(m.textContent, m, {displayMode: m.classList.contains('display'), throwOnError: false, trust: false});
  }));
}
const rupakaRendered = el => el.dispatchEvent(new CustomEvent('lee-markdown-rendered', {bubbles: true}));
//: SHA-256 for a page with no `crypto.subtle`: plain http at a LAN address is not a secure context.
function sha256Hex(bytes) {
  const K = [], H = [], prime = n => { for (let d = 2; d * d <= n; d++) if (n % d === 0) return false; return true; };
  for (let n = 2, i = 0; i < 64; n++) if (prime(n)) { if (i < 8) H[i] = (n ** .5 * 2 ** 32) | 0; K[i++] = (n ** (1 / 3) * 2 ** 32) | 0; }
  const l = bytes.length, words = new Array(((l + 72) >> 6) << 4).fill(0), r = (x, k) => (x >>> k) | (x << (32 - k)), w = [];
  for (let i = 0; i < l; i++) words[i >> 2] |= bytes[i] << (24 - (i % 4) * 8);
  words[l >> 2] |= 0x80 << (24 - (l % 4) * 8);
  words[words.length - 2] = Math.floor(l / 2 ** 29); words[words.length - 1] = (l * 8) | 0;
  for (let j = 0; j < words.length; j += 16) {
    const a = H.slice();
    for (let i = 0; i < 64; i++) {
      w[i] = i < 16 ? words[j + i] | 0 : (w[i - 16] + (r(w[i - 15], 7) ^ r(w[i - 15], 18) ^ (w[i - 15] >>> 3)) + w[i - 7] + (r(w[i - 2], 17) ^ r(w[i - 2], 19) ^ (w[i - 2] >>> 10))) | 0;
      const [A, B, C, D, E, F, G, X] = a;
      const t1 = (X + (r(E, 6) ^ r(E, 11) ^ r(E, 25)) + ((E & F) ^ (~E & G)) + K[i] + w[i]) | 0, t2 = ((r(A, 2) ^ r(A, 13) ^ r(A, 22)) + ((A & B) ^ (A & C) ^ (B & C))) | 0;
      a.splice(0, 8, (t1 + t2) | 0, A, B, C, (D + t1) | 0, E, F, G);
    }
    for (let i = 0; i < 8; i++) H[i] = (H[i] + a[i]) | 0;
  }
  return H.map(x => (x >>> 0).toString(16).padStart(8, '0')).join('');
}
//: `nb.src_hash` in the page: the first 12 hex digits of the SHA-256 of `text`.
const srcHash = async (text, b = new TextEncoder().encode(text)) => (globalThis.crypto?.subtle ? [...new Uint8Array(await crypto.subtle.digest('SHA-256', b))].map(x => x.toString(16).padStart(2, '0')).join('') : sha256Hex(b)).slice(0, 12);
//: Each `rupaka` fence in `el` becomes a demo; a bad one keeps its code and gains one error line. `src` is the cell source the host was drawn from.
function rupakaFences(el, owner = null, src = null) {
  const pass = owner && rupakaPass(owner), seen = new Map();
  $$('pre > code.language-rupaka', el).forEach(code => {
    const pre = code.parentElement, text = code.textContent, n = (seen.get(text) || 0) + 1; seen.set(text, n);
    const fail = err => { if (!pre.nextElementSibling?.matches('.lee-rk-err')) pre.after(rupakaErr(err)); };
    let spec; try { spec = JSON.parse(text); } catch (err) { return fail(err); }
    const e = rupakaDraw(spec, pass && `${owner}:${n}:${text.length}:${text}`, pass);
    if (src != null) e.host.leeSource = src;
    const settle = () => e.err ? fail(e.err) : pre.isConnected && pre.replaceWith(e.host);
    if (e.ok || e.err) settle(); else e.done.then(() => { settle(); rupakaRendered(e.host); });
  });
  if (pass) rupakaSweep(pass);
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
/* `window.open` with `noopener` returns null even when the tab opened, so a null meant "blocked" only
   without it: the opener is cut by hand instead, and the server is asked only when the browser refused. */
function openTab(url) { const w = window.open(url, '_blank'); if (w) w.opener = null; return Boolean(w); }

async function openExternal(url) {
  if (!url) return status('choose a source first', 'err');
  if (!inDesktopShell() && openTab(url)) return;
  try { await post('/browser/external', {url}); }
  catch (e) { status(`could not open ${url}: ${e.message || e}`, 'err'); }
}

function routeMarkdownLinks(el) {
  $$('a[href]', el).forEach(a => {
    const href = (a.getAttribute('href') || '').trim().replace(/[\t\r\n]/g, '');
    if (!href || href.startsWith('#') || a.dataset.leeLink) return;
    const web = /^https?:/i.test(href);
    a.dataset.leeLink = '1';
    if (web) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    const follow = async e => {
      if (e.type === 'auxclick' && e.button !== 1) return;
      if (web && !inDesktopShell() && (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) return;
      e.preventDefault(); e.stopPropagation();
      if (web) return openExternal(href);
      if (/^[a-z][a-z\d+.-]*:/i.test(href) || /^[\/\\]{2}/.test(href)) return status(`will not open ${href}`, 'err');
      let path = href;
      try {
        path = decodeURIComponent(href.split(/[?#]/)[0]);
        if (!path) throw new Error('empty path');
        const base = a.closest('[data-md-base]')?.dataset.mdBase || '';
        if (!path.startsWith('/') && base) {
          const encoded = path.split('/').map(encodeURIComponent).join('/');
          path = decodeURIComponent(new URL(encoded, 'file://' + base.split('/').map(encodeURIComponent).join('/') + '/').pathname);
        }
        await leeOpenFile(path);
      } catch (e) { status(`could not open ${path}: ${e.message || e}`, 'err'); }
    };
    a.addEventListener('click', follow); a.addEventListener('auxclick', follow);
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
      const ask = () => fetch('/markdown/render', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: sent, allow_raw: allowRaw})});
      // A network error, not a refusal: the request never reached the server, and rendering is side-effect free.
      const r = await ask().catch(e => { if (e instanceof TypeError) return ask(); throw e; });
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      const d = await r.json(); if (!el.isConnected) return;
      el.innerHTML = d.html;
      if (d.warnings?.length) el.dataset.markdownWarnings = d.warnings.join(' · ');
      else delete el.dataset.markdownWarnings;
      if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
      el._leeCodeFrame = requestAnimationFrame(() => {
        el._leeCodeFrame = 0;
        if (onRender) try { onRender(el, sent); } catch (e) { console.warn('Leela markdown annotation:', e); }
        resolveMarkdownImages(el); routeMarkdownLinks(el);
        upgradePortableToolMarkdown(el); enhanceCodeBlocks(el); addMarkdownCellAction(el);
        // Only now is the text on the page, math included. Anything that measures the result waits for this.
        const math = renderMath(el);
        if (math) math.then(() => rupakaRendered(el)); else rupakaRendered(el);
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
      // the text moved on while this one was out, so the screen is a render behind. A flush that
      // arrived mid-render is not made to wait out the gap it was asking to skip.
      if (el._leeMarkdownDirty || el.dataset.markdown !== sent)
        renderMarkdown(el, el.dataset.markdown, allowRaw, onRender, el._leeMarkdownNow ? 0 : delay);
      else el._leeMarkdownNow = false;
    }
  }, delay);
}

/* The end of a stream is not a moment to wait a throttle out. `agentTimeline` lengthens the gap
   between renders as a reply grows, so a turn could otherwise finish with a second of unparsed
   text on screen. The pending pass is dropped rather than left to repeat the work this one does. */
function flushMarkdown(el, allowRaw = false, onRender = null) {
  if (!el) return;
  clearTimeout(el._leeMarkdownTimer); el._leeMarkdownTimer = 0; el._leeMarkdownNow = true;
  renderMarkdown(el, el.dataset.markdown || '', allowRaw, onRender, 0);
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
  const err = new Error((body && (body.error || body.message)) || r.statusText);
  err.body = body;     // a screen that offers something for a `kind` reads it here
  throw err;
}
const post = (url, data) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                      body: JSON.stringify(data || {})});

/* `idle` is the most milliseconds the stream may send nothing, keep-alive comments included,
   before it is given up with an error whose `stalled` is true. An error whose `unsent` is true
   came before the stream began. */
async function postEvents(url, data, onEvent, signal = null, idle = 0) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify(data || {}), signal}).catch(e => { throw Object.assign(e, {unsent: true}); });
  if (!r.ok) throw Object.assign(new Error((await r.text()) || r.statusText), {unsent: true});
  const reader = r.body.getReader(), decoder = new TextDecoder();
  let pending = '';
  while (true) {
    let timer;
    const silent = idle && new Promise((_, no) => { timer = setTimeout(() => no(Object.assign(new Error('the stream went silent'), {stalled: true})), idle); });
    let got;
    try { got = await (silent ? Promise.race([reader.read(), silent]) : reader.read()); }
    catch (e) { if (e.stalled) reader.cancel().catch(() => {}); throw e; }
    finally { clearTimeout(timer); }
    const {value, done} = got;
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

