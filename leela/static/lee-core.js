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
  // This page's name and, by tab and cell, the source the server last confirmed to it: a row the page sends
  // names both, so a cell another window changed meanwhile is a conflict and not a silent overwrite.
  pageId: Math.random().toString(36).slice(2, 12), nbSeen: new Map(),
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
    // Said once per problem: `prefSet` callers swallow the refusal, so this is where a broken file shows.
    for (const said of Object.values(d.problems || {})) if (said !== lee.settingsSaid) { lee.settingsSaid = said; status(said, 'err'); }
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
const seenKey = (key, id) => `${key}\u0000${id}`;
function noteSeen(key, cells) { for (const c of cells || []) if (c?.id) lee.nbSeen.set(seenKey(key, c.id), c.source); }
//: What a source row adds so the server can tell this page's edit from a clash: the source it last saw, and who it is.
function seenRow(key, id) {
  const base = lee.nbSeen.get(seenKey(key, id));
  return base === undefined ? {} : {base, page: lee.pageId};
}
//: The rows of the cells whose text differs from what the server last confirmed, each with that base.
function changedRows(key, cells, seq) {
  return cells.map((c, i) => ({i, id: c.id, seq, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}))
    .filter(r => lee.nbSeen.get(seenKey(key, r.id)) !== r.source).map(r => ({...r, ...seenRow(key, r.id)}));
}
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
      // The draft was typed over the source it names, not over what the server holds now.
      if (row.payload.base !== undefined) lee.nbSeen.set(seenKey(documentKey, cell.id), row.payload.base);
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
//: A path as a person reads it: `root/rel` inside an open folder, `~/rel` under home, else as given. `lee.roots` and `lee.home` come from `/workspace/info`.
const shownPath = p => {
  p = String(p || ''); const r = (lee.roots || []).find(r => p === r.path || p.startsWith(r.path + '/'));
  if (r) return r.name + p.slice(r.path.length);
  return lee.home && (p === lee.home || p.startsWith(lee.home + '/')) ? '~' + p.slice(lee.home.length) : p;
};
//: A menu row in sentence case. The keymap's labels are lower case; a tool named in lower case keeps it.
const sentence = s => (s = String(s || '')) && !/^(nbdev|fastship|uv)\b/.test(s) ? s[0].toUpperCase() + s.slice(1) : s;

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
  if (['run_python', 'inspect_python', 'run_cell', 'own_python'].includes(tool)) return 'run';
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
  if (tool === 'own_python') return `Leela Python · ${short(a.code).split(';')[0].slice(0, 82)}`;
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
//: Closes each open gate of the demo in `inner` named in `picks`, `{gate: String of the pick, or null}`, as a host does: the pick an option whose `String` matches, else none. `inner.leePicks` keeps them for `rupakaRevive`.
function rupakaSettle(inner, picks) {
  for (const [id, a] of Object.entries(picks)) {
    if (inner.rupaka?.st.gate[id] !== 'open') continue;
    const pick = a == null ? null : (Rupaka.options(inner, id) || []).find(o => String(o) === a);
    if (Rupaka.settle(inner, id, pick ?? null)) (inner.leePicks ||= {})[id] = a;
  }
}
//: A kept demo whose 3D view lost its WebGL context is drawn again from its spec, with its inputs and its done gates. rupaka's scene drops the context when a frame or a theme change finds its stage off the page, and never makes a new one.
function rupakaRevive(e) {
  if (!e.ok || !e.host.isConnected) return;
  const lost = [...e.inner.querySelectorAll('[data-rk-gl="ready"] canvas')].some(c => c.getContext('webgl2')?.isContextLost());
  if (!lost) return;
  const s = e.inner.rupaka, state = Rupaka.state(e.inner), picks = {...e.inner.leePicks};
  for (const x of s.st.log || []) picks[x.gate] = x.picked == null ? null : String(x.picked);
  Rupaka.mount(e.inner, e.spec, e.opts); Rupaka.set(e.inner, state);
  rupakaSettle(e.inner, Object.fromEntries(Object.entries(s.st.gate).filter(([, v]) => v === 'done').map(([id]) => [id, picks[id] ?? null])));
}
//: `rupakaRevive` for each kept demo inside `root`, which was off the page.
const rupakaReviveIn = root => { for (const e of rupaka.hosts.values()) if (root.contains(e.host)) rupakaRevive(e); };
//: A host is kept under `key` so a re-render hands back the one already mounted, state intact; no key mounts fresh. `inner` is the element `Rupaka.mount` drew into. `restore(inner, spec)` runs once after the mount, before the host shows, and must not throw. `opts` goes to `Rupaka.mount`.
function rupakaDraw(spec, key = null, pass = null, restore = null, opts = undefined) {
  let e = key && rupaka.hosts.get(key);
  if (!e) {
    const host = Object.assign(document.createElement('div'), {className: 'lee-rupaka'}), inner = document.createElement('div');
    host.attachShadow({mode: 'open'}).append(inner);
    e = {host, inner, spec, opts, ok: false, err: null, owner: pass?.owner};
    e.done = loadRupaka().then(css => { rupakaStyle(host.shadowRoot, css); window.Rupaka.mount(inner, spec, opts); })
      .then(async () => { if (restore) await restore(inner, spec); e.ok = true; }, err => { e.err = err; });
    if (key) rupaka.hosts.set(key, e);
  }
  else if (e.ok) Promise.resolve().then(() => rupakaRevive(e));   // a kept host, which its caller puts back on the page at once
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
const texLoad = {p: null};
//: One promise, failure included, as `loadKatex`; without abhyasa's file a lesson formula is drawn plain.
function loadTexparts() {
  return texLoad.p ||= new Promise((ok, no) => {
    if (window.abhyasaTex) return ok(window.abhyasaTex);
    const s = document.createElement('script');
    s.src = $('meta[name="lee-texparts-src"]')?.content || '/leeboard/texparts.js';
    s.onload = () => window.abhyasaTex ? ok(window.abhyasaTex) : no(new Error('texparts.js defined no abhyasaTex'));
    s.onerror = () => { s.remove(); no(new Error('texparts.js could not be loaded')); };
    document.head.appendChild(s);
  }).catch(e => { console.warn('Leela math parts:', e); return null; });
}
//: Fills each `span.math` and `div.math` of `el` in place, so the carriers a diff counts stay the same nodes. In a lesson's markdown cell a formula gets `\htmlId` around its parts, and carries them in `data-parts`. At once, before KaTeX loads, each formula of a lesson gets its number in `data-guide-id` and its TeX in `data-tex`, which the guide sends as the one list of formulas. A promise while any is pending, else nothing.
function renderMath(el) {
  const todo = $$('span.math:not([data-mathed]), div.math:not([data-mathed])', el);
  if (!todo.length) return null;
  const cell = el.matches('.lee-md-cell') && el.closest('.lee-cell[data-id]'), lesson = cell && lessonNotebook(), all = lesson ? $$('span.math, div.math', el) : [];
  if (lesson) todo.forEach(m => { m.dataset.guideId = `f${all.indexOf(m) + 1}`; m.dataset.tex = m.textContent; });
  return Promise.all([loadKatex(), lesson ? loadTexparts() : null]).then(([k, tex]) => k && todo.forEach(m => {
    if (!m.isConnected || m.dataset.mathed) return;
    m.dataset.mathed = '1';
    const opts = {displayMode: m.classList.contains('display'), throwOnError: false, trust: false};
    if (!tex) return k.render(m.textContent, m, opts);
    const n = all.indexOf(m) + 1, [marked, parts] = tex.texParts(m.textContent, (+cell.dataset.i + 1) * 1000 + n);
    k.render(marked, m, {...opts, trust: tex.trust});
    m.dataset.parts = JSON.stringify(parts);
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
//: Each `rupaka` fence in `el` becomes a demo; a bad one keeps its code and gains one error line. `src` is the cell source the host was drawn from, and `restore` goes to `rupakaDraw` for a new host.
function rupakaFences(el, owner = null, src = null, restore = null) {
  const pass = owner && rupakaPass(owner), seen = new Map();
  $$('pre > code.language-rupaka', el).forEach(code => {
    const pre = code.parentElement, text = code.textContent, n = (seen.get(text) || 0) + 1; seen.set(text, n);
    const fail = err => { if (!pre.nextElementSibling?.matches('.lee-rk-err')) pre.after(rupakaErr(err)); };
    let spec; try { spec = JSON.parse(text); } catch (err) { return fail(err); }
    const e = rupakaDraw(spec, pass && `${owner}:${n}:${text.length}:${text}`, pass, restore);
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

function uriPath(s) { try { return decodeURIComponent(s); } catch { return s; } }

function resolveMarkdownImages(el) {
  const base = el.closest('[data-md-base]')?.dataset.mdBase || '';
  $$('img', el).forEach(img => {
    const src = img.getAttribute('src') || '';
    if (!src || /^(https?:|data:|blob:|attachment:|\/file\/raw)/i.test(src)) return;
    if (!src.startsWith('/') && !base) return;
    // `..` and `.` are resolved by URL, so a path cannot climb out through the query string.
    // `pathname` is percent-encoded, so `a b.png` would be asked for as `a%20b.png`.
    const abs = src.startsWith('/') ? src : uriPath(new URL(src, 'file://' + base + '/').pathname);
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
      if (/^\/learn(?:[?#\/]|$)/.test(href)) return window.leeSidePage?.open(href) || status(`could not open ${href}`, 'err');
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
  if (!r.ok) {
    const text = await r.text(); let said = text;
    let body = null;
    try { body = JSON.parse(text); said = body.error || body.message || text; } catch (_) {}
    throw Object.assign(new Error(said || r.statusText), {unsent: true, body});
  }
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

const MAC = /mac|iphone|ipad|ipod/i.test(navigator.userAgentData?.platform || navigator.platform || '');
//: A native window gets every chord; a browser tab never sees the ones Chrome keeps (`browser: false`).
const NATIVE = !!(window.pywebview || window.webkit?.messageHandlers);
//: Each chord as kavacha's `chord_glyph` writes it, from the server's table; a chord it lacks keeps the old spelling.
const displayChord = s => String(s || '').split(/(\s+)/).map(t =>
  /^\s*$/.test(t) || t === '/' ? t : lee.glyphs?.[MAC ? 'mac' : 'pc']?.[t] || t.replace(/\bmod\+/g, MAC ? '⌘' : 'ctrl+')).join('');
//: The chord to advertise for a row: its first, or in a browser tab its first one the tab receives.
const shownChord = k => { const cs = (k?.key || '').split(' ').filter(Boolean);
  return (NATIVE ? cs[0] : cs.find((c, i) => k.chords?.[i]?.browser !== false)) || ''; };
function paintKeyLabels(root = document) {
  $$('kbd', root).forEach(k => { if (k.textContent.includes('mod+')) k.textContent = displayChord(k.textContent); });
}

//: The server draws the footer once; its chords follow `lee.keys` from here.
function paintFooterKeys() {
  $$('.lee-fkey[data-action]').forEach(el => {
    const first = shownChord(lee.keys.find(k => k.action === el.dataset.action));
    el.style.display = first ? '' : 'none';
    const kbd = el.querySelector('kbd'); if (kbd && first) kbd.textContent = displayChord(first);
  });
}

//: `d` is a keymap the server pushed over `/fs/events`, so it is not fetched again.
async function loadKeys(d) {
  d ||= await api('/keys.json');
  lee.keys = d.keys; lee.help = d.help; lee.keyPath = d.path; lee.keyNotes = d.notes || [];
  lee.bars = d.bars || {}; lee.menus = d.menus || {}; lee.glyphs = d.glyphs || {}; lee.legacy = d.legacy || [];
  lee.menuChords = d.menuChords || [];
  paintFooterKeys(); paintKeyLabels();
  const prompt = $('#agentprompt'); if (prompt) prompt.placeholder = displayChord(prompt.placeholder);
  renderContextKeys(lee.scope);
  if (lee.keyNotes.length) status(lee.keyNotes[0] + '. See the keys panel', 'err');
}

function renderContextKeys(scope = lee.scope) {
  const host = $('#keytoast'), tag = $('#keyscope');
  if (!host || !lee.keys.length) return;
  // A glanceable contextual cheat sheet, not the full keymap. Help-only commands stay in the
  // searchable help and settings surfaces rather than pushing the file tree off screen.
  const local = lee.keys.filter(k => k.scope === scope && k.label && k.key && ['footer','toast'].includes(k.show)).slice(0, 8);
  const global = lee.keys.filter(k => k.scope === 'global' && k.show === 'toast' && k.label && k.key).slice(0, 4);
  const rows = local.concat(global);
  if (tag) tag.textContent = scope && scope !== 'global' ? `· ${scope}` : '';
  host.innerHTML = rows.length ? rows.map(k =>
    `<div class="lee-krow${k.scope === scope ? ' contextual' : ''}"><kbd>${esc(displayChord(shownChord(k)))}</kbd>` +
    `<span>${esc(k.label)}</span></div>`).join('') : '<div class="lee-dim">no keys in this context</div>';
}

/* One application-level keyboard router owns every app command. CodeMirror owns editing commands
 * and xterm owns pty input, and neither gets a duplicate copy of this map. The capturing listener
 * resolves an accepted app command before an editor can consume it. An unaccepted event continues
 * untouched. */
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'settings', 'toggle_left', 'toggle_right', 'leave_full_screen']);
const EDITING_SCOPES = new Set(['editor', 'exec', 'agent', 'term']);

function eventContext(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const inPath = selector => path.some(n => n instanceof Element && n.matches(selector));
  // Overlays own their keyboard while open, so commands behind a dialog never fire. A slide deck
  // owns it wherever focus has gone, since what is behind it cannot be seen.
  if (inPath('.lee-modal, .lee-ctxmenu') || lee.present) return 'overlay';
  if (inPath('#termwrap, .xterm')) return 'term';
  // A live page wants its own keyboard as much as a shell does, so the inline browser is routed
  // like the terminal. It has to come before `#editor`, which contains it.
  if (inPath('.lee-webview')) return 'web';
  if (inPath('#agentprompt, .lee-agent')) return 'agent';
  if (inPath('#execbox, .lee-exec')) return 'exec';
  // Before `#editor`, which holds the tab they are mounted in.
  if (inPath('.lee-vault-review')) return 'review';
  if (inPath('.lee-vault-docview')) return 'vault';
  // Before `.lee-cell`, which holds it: a widget's sliders and fields take arrows and letters, a rupaka demo's gate takes mod+enter.
  if (inPath('.lee-widget, .lee-rupaka')) return 'widget';
  if (inPath('#editor, .lee-cell, #filecm')) return 'editor';
  if (inPath('#vars, #varfilter, .lee-varspanel')) return 'vars';
  if (inPath('#filetree, .lee-files')) return 'files';
  return lee.scope || 'editor';
}

/* The window title ends with the kind of pane that has focus, so a tool outside the page (Sanketa)
 * can read it. The token comes from the same scope the key router uses; `title_scope` in Python
 * gives the same word for a tab before the page names the focused pane. */
function titleScope(scope, kind = lee.kind, path = lee.path) {
  if (scope === 'term') return 'terminal';
  if (scope && !['editor', 'global', 'widget'].includes(scope)) return scope;
  if (!kind) return 'files';
  if (scope === 'widget' || kind === 'notebook') return 'notebook';
  if (kind === 'vault' || kind === 'vaultwb') return 'vault';
  if (kind === 'web') return 'web';
  const ext = /\.([^./]+)$/.exec(path || '')?.[1]?.toLowerCase();
  return ext === 'py' ? 'py' : ext ? `editor:${ext}` : 'editor';
}
//: One part of the title: no control characters, never ` · ` inside, at most 60 characters. `title_part` in Python is the same.
function titlePart(s, most = 60) {
  s = String(s ?? '').replace(/[\u0000-\u001f\u007f]+/g, ' ');
  while (s.includes(' · ')) s = s.replaceAll(' · ', ' - ');
  return Array.from(s.trim()).slice(0, most).join('').trim();
}
//: `[prefix · ]Leela · <folder> · <scope>`, as `window_title` in Python builds it. `prefix` is the agent's attention marks.
const leelaTitle = (folder, token, prefix = '') => [prefix, 'Leela', titlePart(folder), token || 'files'].filter(Boolean).join(' · ');
//: The active folder's title name. The server puts it on the folder pill; `refreshProjectPills` keeps it current.
const titleFolder = () => lee.titleFolder ??= globalThis.document?.getElementById?.('workspacepill')?.dataset.folder || '';
//: An overlay keeps the scope it opened over. Native windows are told only when the string changes.
function paintTitle(scope) {
  if (scope && scope !== 'overlay') lee.titleScope = scope;
  clearTimeout(lee.titleTimer);
  lee.titleTimer = setTimeout(() => {
    const t = leelaTitle(titleFolder(), titleScope(lee.titleScope || lee.scope), lee.titlePrefix);
    if (t === lee.title) return;
    document.title = lee.title = t;
    window.pywebview?.api?.set_title?.(t, location.href)?.catch?.(() => {});
  }, 100);
}
document.addEventListener('focusin', e => paintTitle(eventContext(e)), true);
window.addEventListener('pywebviewready', () => { lee.title = ''; paintTitle(); });

//: The element a key went to. `e.target` is retargeted to the host of an open shadow root, such as a widget's.
const keyTarget = e => e.composedPath?.()[0] || e.target;
function isTextEntry(el) {
  if (!(el instanceof Element)) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
  return el.tagName === 'INPUT' &&
    !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(el.type);
}

function chordMatches(c, e) {
  if (e.isComposing || e.key === 'Process' || e.repeat) return false;
  // AltGr arrives as Ctrl+Alt on Windows and Linux; in a text field it is a character, not a chord.
  if (!MAC && e.getModifierState?.('AltGraph') && isTextEntry(keyTarget(e))) return false;
  // Hyper is all four modifiers, the shape macOS reports. Ctrl+Alt+Shift alone is AeroSpace's.
  const wantCtrl = !!c.ctrl || !!c.hyper || (!!c.mod && !MAC);
  const wantMeta = (!!c.mod || !!c.hyper) && MAC;
  if (wantCtrl !== e.ctrlKey || wantMeta !== e.metaKey || !!(c.alt || c.hyper) !== e.altKey || !!(c.shift || c.hyper) !== e.shiftKey)
    return false;
  // Matched by physical code where there is one: Karabiner and Hyper can transform `event.key`,
  // while `event.code` stays Enter, KeyR, ArrowDown.
  if (c.code && (c.mod || c.ctrl || c.alt || c.hyper)) return c.code === e.code;
  return c.key.toLowerCase() === (e.key || '').toLowerCase();
}

//: Cell actions whose first chord is also a CodeMirror line command (copy, cut, toggle comment).
//: While a cell's editor has focus CodeMirror gets that chord; the cell action answers it in command
//: mode, and on its other chords everywhere.
const CELL_ON_CM_CHORD = new Set(['cell_copy', 'cell_cut', 'comment']);
//: CodeMirror commands the table binds. Editors made with `tableKeys` have no chord of their own for them.
const CM_EDIT = {copy_line_up: 'copyLineUp', copy_line_down: 'copyLineDown', delete_line: 'deleteLine',
  select_line: 'selectLine', select_next_occurrence: 'selectNextOccurrence',
  select_all_occurrences: 'selectSelectionMatches', add_cursor_above: 'addCursorAbove',
  add_cursor_below: 'addCursorBelow', matching_bracket: 'cursorMatchingBracket',
  select_parent_syntax: 'selectParentSyntax', block_comment: 'toggleBlockComment'};
const inCellEditor = e => (e.composedPath?.() || [e.target]).some(n => n instanceof Element && n.matches('.lee-cell .cm-editor'));
//: A letter or shifted letter in the editor scope is a notebook command-mode key, as RISE's slide chords and
//: Jupyter's `a`, `b`, `d d`: a cell in command mode takes it, and every editor, field, tab or button types or keeps it.
const typesHere = e => lee.kind !== 'notebook' || isTextEntry(keyTarget(e)) ||
  (e.composedPath?.() || [e.target]).some(n => n instanceof Element && n.matches('.cm-editor'));
const commandChord = (k, c) => k.scope === 'editor' && !(c.mod || c.ctrl || c.alt || c.hyper) && c.key.length === 1 && c.key !== ' ';
function commandMode(e) {
  if (typesHere(e)) return false;
  const t = keyTarget(e);
  return t === document.body || (t instanceof Element && !!t.closest('.lee-cell, #editor') && !t.closest('button, a, summary, select, .lee-tab'));
}
//: `d d`: the first press arms, a second within the window runs. Any other key disarms.
const TWICE_MS = 800;
function twiceReady(k, chord, e) {
  if (!chord.twice) return true;
  const armed = lee.twice?.action === k.action && e.timeStamp - lee.twice.at < TWICE_MS;
  lee.twice = armed ? null : {action: k.action, at: e.timeStamp};
  return armed;
}
const firesInTextEntry = c => c.mod || c.ctrl || c.alt || /^F([1-9]|1[0-2])$/.test(c.key);
//: Plain copy, cut and paste stay the browser's in a text field, and copy and cut also with text
//: selected. Not a selection touching a cell's editor, which keeps one after it blurs, or the file
//: tree, where shift-click marks rows and drags a text selection along.
const selTouches = (n, sel) => (n?.nodeType === 1 ? n : n?.parentElement)?.closest(sel);
function nativeClipboard(e) {
  if (!['KeyC', 'KeyX', 'KeyV'].includes(e.code) || e.altKey || e.shiftKey || e.metaKey !== MAC || e.ctrlKey === MAC) return false;
  if (isTextEntry(keyTarget(e))) return true;
  const s = getSelection(), own = '.lee-cell .cm-editor, #filetree, .lee-files';
  return e.code !== 'KeyV' && !!s && !s.isCollapsed && !!String(s).trim() &&
    !selTouches(s.anchorNode, own) && !selTouches(s.focusNode, own);
}
//: An old default chord nothing is bound to now: run its action once and say where it went. Never while typing.
function legacyBinding(e, scope) {
  if (scope === 'overlay' || isTextEntry(keyTarget(e)) || (scope === 'editor' && lee.kind === 'notebook' && typesHere(e))) return null;
  const allowed = new Set(lee.keys.filter(k => k.scope === scope || k.scope === 'global').map(k => k.action));
  return (lee.legacy || []).find(r => allowed.has(r.action) && chordMatches(r.chord, e)) || null;
}
//: A chord the Mac menu bar owns, pressed over an overlay. The page swallows it, so the row does not run behind the overlay.
const menuChordOver = (e, scope) => scope === 'overlay' && (lee.menuChords || []).some(c => chordMatches(c, e));
function findBinding(e, scope) {
  if (scope === 'overlay' || nativeClipboard(e)) return null;
  // `term` and `web` hand the keyboard to something that is not Leela, keeping only the chords
  // that get you back out.
  const allowed = (scope === 'term' || scope === 'web')
    ? k => k.scope === scope || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action)
    : k => k.scope === scope || k.scope === 'global';
  const guard = !EDITING_SCOPES.has(scope) && isTextEntry(keyTarget(e));
  for (const k of lee.keys) {
    if (!allowed(k)) continue;
    const chord = k.chords.find(c => chordMatches(c, e));
    if (!chord || (guard && !firesInTextEntry(chord))) continue;
    // A widget keeps every plain key, and its own undo; only chords that leave it reach Leela.
    if (scope === 'widget' && (!firesInTextEntry(chord) || k.scope !== 'global' || DEFER_IN_TEXT[k.action])) continue;
    if (['cell_copy', 'cell_cut'].includes(k.action) && lee.kind !== 'notebook') continue;
    if (CELL_ON_CM_CHORD.has(k.action) && chord === k.chords[0] && inCellEditor(e)) continue;
    if (MD_KEYS[k.action] && !MD_KEYS[k.action](e)) continue;
    if (commandChord(k, chord) && !commandMode(e)) continue;
    // With no tab open ⌘W is the window's: the page leaves it alone and the window closes.
    if (k.action === 'close_tab' && chord.mod && !$$('.lee-tab').length) continue;
    if (['cell_first', 'cell_last', 'cell_page_up', 'cell_page_down', 'cell_move_up', 'cell_move_down'].includes(k.action)
        && lee.kind !== 'notebook') continue;
    // The find pane searches the open document. A CodeMirror that is not one of the page's own
    // editors keeps its own panel, which searches the text on screen there.
    if (k.action === 'find_in_file') {
      const cm = (e.composedPath ? e.composedPath() : [e.target])
        .find(n => n instanceof Element && n.matches('.cm-editor'));
      if (cm && !cm.closest('#editor, #filecm, .lee-cell')) continue;
    }
    return {binding: k, chord};
  }
  return null;
}

//: Chords CodeMirror owns while the caret is in a document, and what to try there first. Its
//: command returns false with nothing left to undo, which is when the cell operation is what
//: `mod+z` must mean instead.
const DEFER_IN_TEXT = {notebook_undo: 'undo', notebook_redo: 'redo',
                       indent_more: 'indentMore', indent_less: 'indentLess',
                       indent_selection: 'indentSelection'};

function textEditorOf(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const el = path.find(n => n instanceof Element && n.matches('.cm-content'));
  if (!el) return null;
  const host = el.closest('.cm-editor');
  return [...lee.editors.values()].find(v => v.dom === host) || null;
}

window.addEventListener('keydown', e => {
  const scope = eventContext(e), match = findBinding(e, scope);
  // Kept on `lee` so the key editor and DevTools can tell "Chrome did not deliver it" from "the
  // router rejected it".
  lee.lastKeyEvent = {key: e.key, code: e.code, ctrl: e.ctrlKey, alt: e.altKey,
                      shift: e.shiftKey, meta: e.metaKey, scope,
                      action: match?.binding.action || '', trusted: e.isTrusted};
  if (!match) {
    if (!['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) lee.twice = null;
    if (menuChordOver(e, scope)) return void e.preventDefault();
    const old = legacyBinding(e, scope); if (!old) return;
    e.preventDefault(); e.stopPropagation();
    status(old.now ? `${old.old} is now ${old.now}` : `${old.old} has no key now. Use the command palette.`, 'ok');
    return void leeAct(old.action);
  }
  if (!twiceReady(match.binding, match.chord, e)) return void (e.preventDefault(), e.stopPropagation());
  if (!match.chord.twice) lee.twice = null;
  // Run on the editor under the caret; any other CodeMirror keeps its own chord for the command.
  if (CM_EDIT[match.binding.action]) {
    const v = textEditorOf(e); if (!v) return;
    e.preventDefault(); e.stopPropagation();
    return void LeeCM[CM_EDIT[match.binding.action]](v);
  }
  const cmd = DEFER_IN_TEXT[match.binding.action], view = cmd && textEditorOf(e);
  if (view) {
    e.preventDefault(); e.stopPropagation();
    if (LeeCM[cmd](view)) return;          // the document had something to undo
    return void leeAct(match.binding.action);
  }
  e.preventDefault(); e.stopPropagation();
  leeAct(match.binding.action);
}, true);

const ACTIONS = {
  focus_files:  () => { leePane('left', true); leeLeft('files'); setScope('files'); $('#filetree')?.focus(); highlightTree(); },
  focus_editor: () => { setScope('editor'); if (lee.cells.length) focusCell(lee.sel); else $('#editor')?.focus(); },
  focus_exec:   () => { leePane('bottom', true); leeDock('exec'); setScope('exec'); lee.editors.get('exec')?.focus(); },
  focus_vars:   () => { leePane('right', true); leeRight('vars'); setScope('vars'); $('#varfilter')?.focus(); },
  focus_agent:  () => { leePane('right', true); leeRight('agent'); setScope('agent'); $('#agentprompt')?.focus(); },
  toggle_left:  () => leePane('left'),
  toggle_right: () => leePane('right'),
  toggle_bottom:() => leePane('bottom'),
  leave_full_screen: () => leeLeaveFullScreen(),
  term_option_meta: () => leeTermOptionMeta(),
  toggle_scope: () => leeScope(lee.execScope === 'live' ? 'agent' : 'live'),
  help:         () => showHelp(),
  settings:     () => editorSettings(),
  quick_open:   () => quickOpen(),
  code_search:  () => codeSearch(),
  find_definition: () => gotoDeclaration(),
  find_definition_only: () => findDefinition(),
  find_in_file: () => leeFind(),
  local_history: () => leeLocalHistory(),
  find_usages: () => findUsages(),
  rename_symbol: () => renameSymbol(),
  agent_selection: () => leeAgentSelection(),
  sync_index: () => syncCodeIndex(),
  nbdev_prepare: () => leeNbdevPrepare(),
  fastship:     () => leeFastship(),
  setup_models: () => leeSetupModal(),
  check_updates: () => leeUpdateCheck(),
  run_app:      () => runApp(),
  palette:      () => palette(),
  recent_tabs:  () => recentTabs(),
  save:         () => saveTab(),
  save_all:     () => saveAllTabs(),
  reload_file:  () => leeReloadFromDisk(),
  close_tab:    () => closeTab(),
  next_tab:     () => shiftTab(1),
  prev_tab:     () => shiftTab(-1),
  interrupt:    async () => {
    const r = await post('/kernel/interrupt');
    status(r.note || 'cell stopped', (r.forced || !r.ok) ? 'err' : 'ok');
  },
  restart:      async () => { status('restarting kernel…'); await post('/kernel/restart'); markPreviousRuns(); status('kernel restarted · saved outputs are from the previous kernel', 'ok'); leeVars(); },
  switch_env:   () => pickEnv(),
  edit_runs:    () => editRuns(),
  quit:         () => status('close the browser tab to leave'),

  run_cell:     () => lee.kind === 'text' ? runFile() : runCell(lee.sel, false),
  run_advance:  () => lee.kind === 'text' ? runFile() : runCell(lee.sel, true),
  run_insert:   () => lee.kind === 'text' ? runFile() : runCell(lee.sel, 'insert'),
  stop_cell:    () => stopCell(lee.sel),
  check_exercise: () => {
    if (lee.kind !== 'notebook' || lee.activeEditor === 'secondary') return;
    const at = document.activeElement?.closest?.('#editor .lee-cell[data-id]');
    const c = at ? lee.cells.find(x => x.id === at.dataset.id) : lee.cells[lee.sel], ex = c?.extra?.exercise;
    const id = isExercise(c) ? c.id : ex?.role === 'task' ? ex.for : '';
    if (id && isExercise(lee.cells.find(x => x.id === id))) return checkExercise(id);
  },
  run_above:    () => runRange(0, lee.sel, 'cells above'),
  run_below:    () => runRange(lee.sel, lee.cells.length, 'this cell and below'),
  run_all:      () => runAll(),
  restart_run_all: () => restartRunAll(),
  run_file:     () => runFile(),
  run_selection: () => runSelection(),
  pick_kernel:  () => pickKernel(),
  new_notebook: () => htmxPost('/tab/new?kind=notebook'),
  new_lesson:   async () => {
    const name = await inputDialog('new lesson notebook', 'name', '', 'lesson name');
    if (!name) return;
    await htmxPost('/lesson/new?name=' + encodeURIComponent(name));
    await refreshFileTree();
  },
  notebook_language: () => pickNotebookLanguage(),
  present_notebook: () => presentNotebook(),
  present_from_cell: () => presentNotebook('selected'),
  slide_none:     () => setCellSlide(selectedCellIndices(), 'none'),
  slide_slide:    () => setCellSlide(selectedCellIndices(), 'slide'),
  slide_subslide: () => setCellSlide(selectedCellIndices(), 'subslide'),
  slide_fragment: () => setCellSlide(selectedCellIndices(), 'fragment'),
  slide_skip:     () => setCellSlide(selectedCellIndices(), 'skip'),
  slide_notes:    () => setCellSlide(selectedCellIndices(), 'notes'),
  add_folder:   () => treeAddFolder(),
  edit_keys:    () => editKeys(),
  cell_select_above: () => focusCell(Math.max(visibleCell(lee.sel, -1), 0)),
  cell_select_below: () => { const j = visibleCell(lee.sel, 1); focusCell(j < 0 ? lee.sel : j); },
  cell_first: () => focusCell(0),
  cell_last: () => focusCell(shownAt(lee.cells.length - 1)),
  cell_page_up: () => focusCellPage(-1),
  cell_page_down: () => focusCellPage(1),
  cell_move_up: () => moveCellTo(lee.sel, lee.sel - 1),
  cell_move_down: () => moveCellTo(lee.sel, lee.sel + 1),
  cell_above:   async () => { const at = lee.sel; if (!await nbEdit({op: 'insert', i: at})) return; focusCell(at); status('cell inserted above', 'ok'); },
  cell_below:   async () => { const at = belowAt(lee.sel); if (!await nbEdit({op: 'insert', i: at})) return; focusCell(at); status('cell inserted below', 'ok'); },
  cell_delete:  async () => { const at = lee.sel; if (!await nbEdit({op: 'delete', i: at})) return; focusCell(shownAt(Math.min(at, lee.cells.length - 1))); status('cell deleted', 'ok'); },
  notebook_undo: async () => {
    if (lee.kind === 'text') return status('nothing to undo outside a notebook');
    const r = await nbEdit({op: 'undo', i: lee.sel}); if (!r) return;
    focusCell(r.index ?? lee.sel); status('cell operation undone', 'ok');
  },
  notebook_redo: async () => {
    if (lee.kind === 'text') return status('nothing to redo outside a notebook');
    const r = await nbEdit({op: 'redo', i: lee.sel}); if (!r) return;
    focusCell(r.index ?? lee.sel); status('cell operation redone', 'ok');
  },
  cell_to_markdown: () => setCellType('markdown'),
  cell_to_code: () => setCellType('code'),
  cell_type:    async () => {
    const id = lee.cells[lee.sel]?.id;
    const r = await nbEdit({op: 'type', i: lee.sel, cycle: true}); if (!r) return;
    const at = Math.max(0, r.cells.findIndex(c => c.id === id));
    focusCell(at); status(`cell ${at + 1} is now ${r.cells[at]?.cell_type || 'code'}`, 'ok');
  },
  capture:      () => captureScreen(),
  cell_split:   async () => {
    const at = lee.sel, v = lee.editors.get(lee.cells[at].id);
    if (!await nbEdit({op: 'split', i: at, offset: v ? LeeCM.cursor(v) : 0})) return;
    focusCell(at + 1); status('cell split', 'ok');
  },
  cell_split_symbols: async () => {
    const at = lee.sel, was = lee.cells.length;
    const r = await nbEdit({op: 'split_symbols', i: at}); if (!r) return;
    const made = r.cells.length - was;
    if (!made) return status('no top-level class or function to split out', 'err');
    focusCell(at); status(`split into ${made + 1} cells`, 'ok');
  },
  cell_collapse: () => setCellCollapsed(lee.sel),
  heading_toggle: () => toggleHeading(lee.sel),
  collapse_all_headings: () => setHeadings(null, true),
  expand_all_headings: () => setHeadings(null, false),
  cell_edit:    () => editMarkdownCell(lee.sel),
  cell_render:  () => lee.cells[lee.sel]?.cell_type === 'markdown' ? showRenderedMarkdown(lee.cells[lee.sel], true) : document.activeElement?.blur(),
  cell_duplicate: async () => {
    const at = lee.sel; if (!await nbEdit({op: 'duplicate', i: at})) return;
    focusCell(at + 1); status('cell duplicated', 'ok');
  },
  cell_copy: () => copyCell(lee.sel),
  cell_cut: () => cutCell(lee.sel),
  cell_paste_above: () => pasteCell(lee.sel),
  cell_paste_below: () => pasteCell(belowAt(lee.sel)),
  cell_merge_above: async () => {
    const at = lee.sel; if (at < 1) return status('there is no cell above', 'err');
    if (!await nbEdit({op: 'merge_above', i: at})) return;
    focusCell(at - 1); status('cells merged', 'ok');
  },
  cell_merge_below: async () => {
    const at = lee.sel; if (at + 1 >= lee.cells.length) return status('there is no cell below', 'err');
    if (!await nbEdit({op: 'merge_below', i: at})) return;
    focusCell(at); status('cells merged', 'ok');
  },
  clear_cell_output: async () => {
    const at = lee.sel; if (!await nbEdit({op: 'clear_cell', i: at})) return;
    focusCell(at); status('cell output cleared', 'ok');
  },
  clear_all_outputs: async () => {
    if (!await nbEdit({op: 'clear'})) return;
    focusCell(lee.sel); status('all outputs cleared', 'ok');
  },
  comment:      () => toggleComment(),
  cell_comment: () => toggleComment(),
  complete:     () => kernelComplete(),
  ai_complete:  () => aiComplete(),
  ask_ai:       () => askSelection('[data-ask]'),
  summarise:    () => askSelection('[data-summary]'),
  show_docs:    () => showDocs(),
  show_diff:    () => lee.menuSurface === 'file' ? treeDiff() : showDiff(),
  git_blame:    () => lee.menuSurface === 'file' ? treeBlame() : leeBlame(),
  git_stage:    () => treeGitAction('stage'),
  git_unstage:  () => treeGitAction('unstage'),
  git_discard:  () => treeGitAction('discard'),
  git_ignore:   () => treeGitAction('ignore'),
  clip_to_vault: () => leeClipToVault(),
  memory_notes: () => leeMemoryNotes(),
  new_memory_note: () => leeNewMemoryNote(),
  open_vault: () => leeVaultWorkbench(),
  vault_read: () => leeVaultRead(),
  vault_find: () => leeVaultWorkbench('find'),
  vault_settings: () => leeVaultWorkbench('settings'),
  vault_next_page: () => leeVaultPage(1),
  vault_prev_page: () => leeVaultPage(-1),
  vault_next_flag: () => leeVaultFlag(1),
  vault_prev_flag: () => leeVaultFlag(-1),
  vault_review: () => leeVaultReview(),
  learned_review: () => leeVaultReview('', '', '', 'learned'),
  vault_reread: () => leeVaultDoc('reread'),
  vault_history: () => leeVaultDoc('history'),
  vault_proofread: () => leeVaultDoc('proofread'),
  vault_as_sent: () => leeVaultDoc('sent'),
  vault_find_doc: () => leeVaultDoc('find'),
  vault_ask_page: () => leeVaultDoc('ask'),
  review_next: () => leeReview('step', 1),
  review_prev: () => leeReview('step', -1),
  review_accept: () => leeReview('accept'),
  review_reject: () => leeReview('reject'),
  review_accept_page: () => leeReview('page'),
  review_accept_doc: () => leeReview('doc'),
  review_doubts: () => leeReview('doubts'),
  review_edit: () => leeReview('edit'),
  review_undo: () => leeReview('undo'),
  indent_more:      () => leeIndent('indentMore'),
  indent_less:      () => leeIndent('indentLess'),
  indent_selection: () => leeIndent('indentSelection'),
  format_doc:   () => leeFormatDoc(),
  find_similar: () => findSimilar(),
  code_map:     () => codeMap(),

  exec_run:     () => runExec(),
  exec_newline: () => { const v = lee.editors.get('exec'); if (v) LeeCM.insert(v, '\n'); },
  exec_prev:    () => recall(-1),
  exec_next:    () => recall(1),
  exec_clear:   () => leeExecClear(),
  exec_promote: () => { leeScope('live'); runExec(); },

  file_copy:      () => fileClipboard(false),
  file_cut:       () => fileClipboard(true),
  file_paste:     () => pasteEntries(),
  file_duplicate: () => duplicateEntries(),
  tree_mark_up:   () => markTreeStep(-1),
  tree_mark_down: () => markTreeStep(1),
  open:         () => treeActivate(),
  tree_down:    () => moveTreeSelection(1),
  tree_up:      () => moveTreeSelection(-1),
  tree_expand:  () => treeExpand(),
  tree_collapse: () => treeCollapse(),
  new_file:     () => newEntry('file'),
  tree_new_file: () => newEntry('file'),
  new_dir:      () => newEntry('dir'),
  rename:       () => renameEntry(),
  delete:       () => deleteEntry(),
  open_folder:  () => openAny(),
  tree_open_folder: () => openFolderWindow(),
  add_root:     () => addRoot(),
  find_repo:    () => findRepo(),
  remove_root:  () => removeRoot(),
  refresh_files: () => refreshFileTree(),
  show_hidden:  () => toggleHidden(),
  up_dir:       () => treeCollapse(),
  filter_files: () => status('find a file with go to file'),

  expand:       () => $('.lee-vrow.sel')?.click(),
  filter_vars:  () => $('#varfilter')?.focus(),
  edit_value:   () => editSelectedVar(),
  grid:         () => openGrid(),
  copy_rel_path: () => copyFilePath('relative'),
  copy_abs_path: () => copyFilePath('absolute'),
  copy_value:   () => copyVar('value'),
  copy_path:    () => copyVar('path'),
  promote:      () => promoteVar(),
  sort:         () => { const s = $('#varsort'); s.selectedIndex = (s.selectedIndex + 1) % s.options.length; leeVars(); },
  profile_minimal:  () => setProfile('minimal'),
  profile_standard: () => setProfile('standard'),
  profile_full:     () => setProfile('full'),

  agent_new:    () => leeAgentNew(),
  agent_threads: () => { leePane('right', true); leeRight('agent'); leeAgentThreadsToggle(true); },
  agent_send:   () => sendAgent(),
  agent_steer_force: () => sendAgent(true),
  agent_stop:   () => stopAgent(),
  agent_tools:  () => agentTools(),
  agent_fold_turn: () => foldAgentTurn(currentAgentTurn(), !currentAgentTurn()?.classList.contains('folded')),
  agent_fold_all: () => foldAgentTurns(!agentTurnCards().every(c => c.classList.contains('folded'))),
  agent_menu:   () => leeAgentMenu(),
  agent_history: () => leeAgentHistory(),
  agent_assess: () => leeAgentAssess(),
  agent_round:  () => leeAgentCapture(),
  agent_accept: () => leeAgentAccept(),
  agent_calm:   () => leeAgentCalm(),
  agent_expand: () => leeAgentExpand(),
  agent_research: () => leeAgentOptinToggle('research'),
  agent_exhash: () => leeAgentOptinToggle('exhash'),
  agent_browser: () => leeAgentOptinToggle('browser'),
  agent_warm:   () => leeAgentWarmToggle(),
  agent_full:   () => leeAgentFullToggle(),
  agent_state:  () => leeAgentState(),

  close_others: () => closeTabs('others'),
  close_right:  () => closeTabs('right'),
  close_saved:  () => closeTabs('saved'),

  terminal:     () => openTerm('shell'),
  git:          () => openTerm('git'),
  panel_git:      () => leeLeft('git'),
  panel_releases: () => leeLeft('releases'),
  panel_deploys:  () => leeLeft('deploys'),
  term_new:     () => leeNewTerm(),
  term_next:    () => cycleTerm(1),
  term_prev:    () => cycleTerm(-1),
  term_close:   () => closeTerm(),

  web_search:   () => webSearch(),
  research:     () => researchQ(),
  read_url:     () => readUrl(),
  browse_url:   () => browseUrl(),
  browse_tabs:  () => pickWebTab(),
};
for (let i = 1; i <= 9; i++) ACTIONS['tab_' + i] = () => htmxPost('/tab/select?i=' + (i - 1));
for (const [a, cmd] of Object.entries(CM_EDIT)) ACTIONS[a] = () => leeIndent(cmd);
//: A rendered markdown cell keeps its editor mounted and hidden, so `offsetParent` is what says it is on screen.
ACTIONS.column_mode = () => {
  const v = curEditor();
  if (!v?.dom.offsetParent) return status('put the cursor in an editor first', 'err');
  LeeCM.focus(v);
  if (!LeeCM.toggleColumnMode(v)) status('column mode needs an editable editor', 'err');
};

async function setCellType(t) {
  if (lee.cells[lee.sel]?.cell_type === t) return;
  const at = lee.sel; if (!await nbEdit({op: 'type', i: at, cell_type: t})) return;
  selectCell(at); status(`cell ${at + 1} is now ${t}`, 'ok');
}

function leeAct(name) {
  const f = ACTIONS[name];
  if (!f) return status('no handler for ' + name);
  try { const r = f(); if (r && r.catch) r.catch(e => status(String(e.message || e), 'err')); return r; }
  catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAct = leeAct;

function setScope(s) {
  lee.scope = s;
  renderContextKeys(s);
  paintTitle(s);
}
const activeTabIndex = () => $$('.lee-tab').findIndex(t => t.classList.contains('active'));
async function closeTab(index = null) {
  const i = index == null ? (lee.menuTab == null ? activeTabIndex() : lee.menuTab) : Number(index);
  lee.menuTab = null;
  // No tab left: close the window, as ⌘W does in any Mac app. A browser tab ignores a script's close.
  if (i < 0) return void (window.pywebview || window.webkit?.messageHandlers ? window.close() : status('no tab is open'));
  const tab = $$('.lee-tab')[i];
  if (tab?.dataset.gitDiff) return closeGitDiffTab(tab.dataset.gitDiff);
  if (tab?.classList.contains('dirty') &&
      !await confirmDialog('close unsaved tab', `${$('.lee-tab-name', tab)?.textContent || 'This file'} has unsaved changes.`, 'close')) return;
  htmxPost('/tab/close?i=' + i);
}
window.leeCloseTab = closeTab;
async function closeTabs(which) {
  // `others`, `right` and `saved`. The reference point is the tab the menu was opened on, not the
  // active one: a right-click on a background tab selects it first, and the menu is still about
  // that tab.
  const at = lee.menuTab == null ? activeTabIndex() : lee.menuTab;
  lee.menuTab = null;
  if (at < 0) return;
  const tabs = $$('.lee-tab');
  const keep = i => which === 'others' ? i === at : which === 'right' ? i <= at
                  : tabs[i].classList.contains('dirty');
  // Git diff tabs live only in the browser and are appended after the real ones, so they are left
  // alone and cannot shift an index. Highest first, for the same reason.
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
  // The active file and its neighbours stay spatially meaningful, and every other open document
  // is one click away in the overflow menu.
  const breakpointCap = innerWidth >= 1700 ? 7 : innerWidth >= 1300 ? 5 : innerWidth >= 960 ? 4 : 2;
  // The bar is only as wide as the tabs it shows; the spacer beside it holds the rest of the row's room.
  const room = bar.clientWidth + ($(':scope > .lee-spacer', bar.parentElement)?.clientWidth || 0);
  const cap = Math.max(1, Math.min(breakpointCap, Math.floor(room / 138) || 1));
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
function binaryDiffHtml(data) {
  // An LFS pointer is text, so git diffs it as text: three lines of oid and size where the file
  // should be. Say which file it is and what it weighs instead of rendering the stand-in.
  const lfs = data.lfs || data.file?.lfs;
  const size = Number(lfs?.size);
  const detail = lfs
    ? `Stored with Git LFS${Number.isFinite(size) && size ? ` · ${(size / 1024).toFixed(0)} KB` : ''}`
    : 'Text comparison is not available for this file.';
  return `<div class="lee-git-empty-state"><strong>Binary file changed</strong><span>${esc(detail)}</span>` +
    `${lfs?.oid ? `<code>${esc(String(lfs.oid).replace(/^sha256:/, '').slice(0, 12))}</code>` : ''}</div>`;
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
    const at = data.root ? {repo: data.root} : {};
    try { const next = await gitDo('write_worktree', {path: data.path, content: data.mergeResult, before: data.worktreeBefore ?? null, ...at}), fresh = noteHl(await api(gitUrl('/git/diff', {path: data.path, staged: false, ...at}))); data.base = 'index'; data.head = 'worktree'; data.baseLabel = 'index'; data.headLabel = 'working tree'; data.left = fresh.left || ''; data.right = fresh.right || ''; data.patch = fresh.content || fresh.text || ''; data.rawPatch = fresh.text || ''; data.group = 'unstaged'; data.mergeResult = null; data.worktreeBefore = fresh.right || ''; gitUI.review = null; paintGitPill(next); await activateGitDiffTab(key); status(`${data.path} updated in the working tree`, 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  const body = host.querySelector('.lee-diff-document-body');
  if (data.binary || data.file?.binary) body.innerHTML = binaryDiffHtml(data);
  else if (data.view === 'rendered' && isMarkdownPath(data.path)) await mountMarkdownDiff(body, data);
  else if (data.view === 'split') {
    body.className += ' split';
    const changed = result => { data.mergeResult = result; const state = host.querySelector('.lee-diff-edit-state'), apply = host.querySelector('[data-apply-merge-result]'); if (state) state.hidden = false; if (apply) apply.hidden = false; };
    lee.gitMergeView = createMerge(body, {left: data.left || '', right: data.mergeResult ?? data.right ?? '', lang: codeLang('', data.path), settings: lee.editorPrefs, readOnlyRight: !data.allowWrite, revertControls: data.allowWrite ? 'a-to-b' : false, onChange: data.allowWrite ? changed : null});
  } else {
    body.innerHTML = gitDiffNotebookHtml(data.patch, data);
    body.querySelectorAll('[data-fold-diff]').forEach(b => b.onclick = () => { const cell = b.closest('.lee-diff-cell'), folded = cell.classList.toggle('collapsed'); b.textContent = folded ? '+' : '−'; });
  }
  setScope('editor'); layoutTabs();
}
function gitDiffNotebookHtml(patch, data) {
  const parts = gitPatchParts(patch);
  if (!parts.hunks.length) return `<div class="lee-git-empty-state"><strong>No textual patch</strong><span>${esc(data.path)} has no line-level changes in this comparison.</span></div>`;
  return `<div class="lee-diff-notebook">${parts.hunks.map((h, i) => { const title = h.split('\n')[0] || `hunk ${i + 1}`; return `<article class="lee-diff-cell"><header><button data-fold-diff aria-label="collapse hunk">−</button><strong>change ${i + 1}</strong><code>${esc(title)}</code><span class="lee-spacer"></span><small>${h.split('\n').filter(x => x.startsWith('+') && !x.startsWith('+++')).length} added · ${h.split('\n').filter(x => x.startsWith('-') && !x.startsWith('---')).length} removed</small></header><div class="lee-git-patch">${gitPatchHtml(h)}</div></article>`; }).join('')}</div>`;
}
window.openGitDiffTab = openGitDiffTab;

/* A Markdown diff read as Markdown: the new document rendered, a bar in the margin beside every
 * changed block, and the line-level change inside a fenced block.
 *
 * `/markdown/render` stays `allow_raw: false`, because Markdown out of a repository is untrusted
 * input. `/markdown/diff` pairs the two versions block against block. Lines cannot do this: a
 * rendered paragraph has no line numbers, and an edit at the top of a file moves every line
 * below it while moving no blocks.
 */
const MARKDOWN_PATH = /\.(?:md|markdown|mdown|mkdn?)$/i;
const isMarkdownPath = path => MARKDOWN_PATH.test(String(path || ''));

// mdhtml's own top-level nodes, in document order. The footnotes section is generated from the
// definitions rather than from a block of its own, so it never carries a mark. A comment counts
// as a carrier with nothing to draw beside it, because dropping it would shift every block after
// it.
function markdownCarriers(el) {
  return [...el.childNodes].filter(n => n.nodeType === 8 ||
    (n.nodeType === 1 && !(n.tagName === 'SECTION' && n.classList.contains('footnotes'))));
}
const markdownTagOf = n => n.nodeType === 1 ? n.tagName.toLowerCase() : '#comment';

/* Which element each block became, as positions rather than nodes: the code-block upgrade later
 * swaps each `<pre>` for an editor surface in the same place, so a caller that has to wait for a
 * request reads the tags now and the nodes again afterwards.
 *
 * One mismatch, or one node no block claimed, answers `null`, and the surface says why. A raw
 * HTML block that produced two elements shifts everything after it, and a change bar beside the
 * wrong paragraph is a false statement about the diff.
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

/* The line-level change inside one fenced block, with `tokenDiffHtml` marking the words that
 * moved in an edited line. A pathologically long fence falls back to "all of the old, then all of
 * the new" rather than allocating a large LCS matrix.
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
  // A removal immediately followed by an addition is one line somebody edited, so both halves
  // point at the words that changed in it.
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

// Pink for changed text, green for new, amber for a code fence, the same three the gutter uses.
const markdownChangeKind = row => row.status === 'added' ? 'added'
  : row.status !== 'modified' ? '' : row.type === 'code_block' ? 'code' : 'modified';

function paintMarkdownDiff(doc, rows) {
  const nodes = markdownCarriers(doc), pairs = alignMarkdownBlocks(nodes.map(markdownTagOf), rows);
  const note = doc.parentElement?.querySelector('[data-md-diff-note]');
  if (!pairs) { if (note) note.hidden = false; return false; }
  // A removed block has nothing left to render, so it is reported on the block that now stands
  // where it stood. Removals with nothing after them belong to the last block in the document.
  let removed = [], last = null;
  for (const {row, at} of pairs) {
    if (row.status === 'removed') { removed.push(row); continue; }
    const node = nodes[at];
    let host = node;
    // `enhanceCodeBlocks` replaces every `pre > code` with an editor surface a moment after this
    // runs. An edited fence becomes the interleaved diff, which has no `<code>` for the upgrade
    // to find, and a new fence keeps its rendering and gets a wrapper to hold the mark.
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
  renderMarkdown(doc, data.right || '', false, () => paintMarkdownDiff(doc, rows));
}

/* The same marks on the file's own rendered pane, from the ranges the gutter is already drawing.
 * `/git/file` reports changed lines in the working tree's own numbering, and a block owns a range
 * when the two overlap. Git points a pure deletion at the line that closed over it, so a removal
 * is reported on the block that now stands there.
 *
 * Only the first render asks. While the file is being typed the ranges describe the version on
 * disk, and no marks is the honest answer for a paragraph that has moved under them. The tags are
 * read before the request goes out, because by the time it answers the code-block upgrade has
 * replaced every `<pre>` with an editor surface.
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
  const doc=new DOMParser().parseFromString(html,'text/html'),fresh=doc.querySelector('#tabbar');
  // `/tab/open` answers a refusal with an error div and a 200, so the reason is in the body.
  if(!fresh)throw new Error(doc.querySelector('.lee-err')?.textContent?.trim()||'tab open returned no tab bar');
  path=fresh.querySelector('.lee-tab.active')?.title||path;lee.pendingFocusPath=path;
  // `#tabbar` is an htmx swap target, so a failed swap can replace it with an error string and
  // take it out of the page. Every open after that fails on the missing element, so put it back.
  const old=$('#tabbar');
  if(old)old.replaceWith(fresh);
  else $('#header')?.insertBefore(fresh,$('.lee-tab-overflow')||null);
  htmx.process(fresh);
  // The variables panel is beside the editor, not part of it, and awaiting it held the switch open
  // for as long as it took to paint: 97ms of the 113 a notebook switch cost in the window Leela
  // ships. The file is on screen; the panel catches up.
  await mountTab(path);leeVars();refreshProjectPills();requestAnimationFrame(layoutTabs);
  const after = $$('.lee-node').find(n => n.dataset.path === path);
  if (after) selectTreeNode(after);
}
window.leeOpenFile = leeOpenFile;

function updateToolbarForKind(kind) {
  const notebook = kind === 'notebook', text = kind === 'text';
  // `stop` interrupts the tab's kernel, and a document tab does not have one.
  const visibility = {run_cell: notebook, run_advance: notebook, run_file: text,
                      run_selection: text, interrupt: notebook || text};
  for (const [action, shown] of Object.entries(visibility)) {
    const button = $(`#toolbar [data-action="${action}"]`); if (button) button.hidden = !shown;
  }
  refreshMarkdownCellActions();   // whether a reply can become a cell depends on this tab
}

/* A save Leela made is not a change somebody else made. `/tabs/save-all` writes from the buffers the
   server holds, so the browser kept the version it had before that write: the next save read as
   `another process wrote it`, and the poll that watches the open file called it an outside edit and
   reloaded the tab. What was written comes back with the new version of each file, and both the
   editor's token and any draft that descends from it are moved on to it. */
function takeSavedVersions(d) {
  refreshKernelPill();
  const versions = (d && d.versions) || {};
  for (const [key, version] of Object.entries(versions)) {
    recordDiskVersion(key, version);
    rebaseDrafts(key, version);
  }
}

/* Background tabs' dots: lit for each the server holds unsaved, cleared only for each a save-all wrote. Never
   cleared from the strip alone, which has not seen a mirror still in flight or a draft not yet posted. */
function setTabDirt(titles, dirty) {
  for (const tab of $$('.lee-tab:not(.active)')) if (titles.has(tab.title)) { tab.classList.toggle('dirty', dirty); setTabSaveState(tab, dirty ? 'pending' : 'saved'); }
}
async function syncTabDirt() {
  const bar = new DOMParser().parseFromString(await (await fetch('/tab/bar')).text(), 'text/html');
  setTabDirt(new Set($$('.lee-tab.dirty', bar).map(t => t.title)), true);
}
let mountTabVersion=0;
function saveTabLocation() {
  const view = curEditor(), key = lee.path || lee.tabKey;
  if (!view || !key) return;
  // A Map keeps a re-set key at its first insertion point, so the delete is what moves the key to
  // the end for the tail slice below.
  lee.locations.delete(key);
  // Two scrollers, and only the inner one was kept. A notebook scrolls in `#editor`, and each cell's
  // CodeMirror is its own scroller sitting at zero, so coming back to a tab landed at the top.
  lee.locations.set(key, {pos: LeeCM.cursor(view), scroll: view.scrollDOM.scrollTop,
    host: $('#editor')?.scrollTop || 0,
    cell: lee.kind === 'notebook' ? lee.sel : -1});
  // Nothing else prunes this: a closed, renamed or deleted file leaves its entry behind, so the
  // cap is what keeps a long session and sessionStorage bounded.
  for (const stale of [...lee.locations.keys()].slice(0, lee.locations.size - 80)) lee.locations.delete(stale);
  try { localStorage.setItem('lee-tab-locations', JSON.stringify([...lee.locations])); } catch (_) {}
}
function restoreTabLocation(st, skip = false) {
  const key = st.path || st.title, loc = lee.locations.get(key);
  if (!loc || skip || lee.pendingLocation) return;
  requestAnimationFrame(() => {
    let view = lee.editors.get('file');
    if (st.kind === 'notebook' && loc.cell >= 0 && loc.cell < lee.cells.length) {
      selectCell(loc.cell); view = ensureCellMounted(loc.cell);
    }
    // The cells of a long notebook mount as they are reached, so the height the offset was taken
    // against arrives a frame late. Setting it twice lands on the second one.
    const host = $('#editor');
    if (host && loc.host) {
      host.scrollTop = loc.host;
      requestAnimationFrame(() => { if (host.scrollTop !== loc.host) host.scrollTop = loc.host; });
    }
    if (!view) return;
    LeeCM.setCursor(view, loc.pos); view.scrollDOM.scrollTop = loc.scroll || 0;
  });
}
async function mountTab(expectedPath = '') {
  saveTabLocation();
  dropTabReads();
  const hadPendingLocation = Boolean(lee.pendingLocation);
  const mountVersion=++mountTabVersion;
  lee.activeGitTab = '';
  if (lee.gitMergeView) { LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; }
  syncGitDiffTabs();
  // A queued autosave belongs to the tab being left, and cancelling it was all this did, so typing
  // and switching inside the delay left that tab dirty with nothing left to save it. The server
  // holds a buffer for every tab, so it persists what is dirty, once the last mirror has landed.
  clearTimeout(lee.autoSaveTimer);
  // The strip just swapped in is the server's, which has not yet seen a fold or edit still out for the tab
  // being left. Those land first, then the strip says what the server holds and the save goes by that.
  const leaving = lee.tabKey;
  setTimeout(() => Promise.all([headingSynced(leaving), lee.nbQueue]).then(syncTabDirt)
    .then(() => autoSaveEnabled() && !lee.observer && ($('.lee-tab.dirty:not(.untitled)') || lee.bufferTimers.size) && post('/tabs/save-all')
      .then(d => { takeSavedVersions(d); setTabDirt(new Set(Object.keys(d.versions || {})), false); }))
    .catch(() => {}), 160);
  lee.editVersion += 1; // invalidates an autosave response belonging to the previous tab
  // A notebook this page still holds comes back without its cells when the server's copy is the same version.
  const have = JSON.stringify(heldNotebookVersions());
  const st=await api('/tab/state?'+new URLSearchParams({...(expectedPath?{path:expectedPath}:{}), have}));
  if(mountVersion!==mountTabVersion)return;
  if (st.kind === 'notebook' && st.same) st.cells = heldNotebookCells(st.path || st.title);
  if (st.kind === 'notebook') noteSeen(st.path || st.title, st.cells);
  const recoveredDraft = await restoreDrafts(st);
  // `/tab/state` serves the cached copy and flags that the file has moved under it, which is what a
  // run of `nbdev-prepare` over an open notebook does. Nobody read the flag, so the tab showed the
  // version from before the run with nothing saying so.
  if (st.stale) noteStaleTab(st, recoveredDraft);
  // Only the tab's own editors are torn down. The exec strip belongs to the app, and destroying
  // it here would silently leave the box unmounted.
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  // The notebook being left keeps its shells, so coming back to it is a reattach rather than a
  // hundred elements built and laid out again. A dirty one is not kept: its summaries and outputs
  // describe a version that is not on disk.
  if (lee.kind === 'notebook' && !$('.lee-tab.active.dirty')) keepNotebookShells($('#editor'), lee.tabKey, lee.diskVersion && `${lee.diskVersion}@${lee.nbVersions.get(lee.tabKey)}`);
  // A screencast is a live encode in Chrome while it runs, so leaving the tab stops it. The page
  // stays open and the tab reattaches on the way back.
  closeWebView();
  const host = $('#editor'); if (!host) return;
  lee.kind = st.kind; lee.path = st.path || ''; lee.tabKey = st.path || st.title || ''; lee.cells = st.cells || [];
  lee.rise = st.rise || {};
  window.leeFolderOffer?.(st);
  paintTitle();
  // A notebook's kernelspec, so cells highlight and lint as the language they are.
  lee.nbLang = st.kind === 'notebook' ? (st.lang || 'python') : '';
  execLang();
  await loadSettings(st.lang || (st.kind === 'notebook' ? 'python' : ''));
  updateToolbarForKind(st.kind);
  rememberRecentTab(st);
  lee.diskVersion = st.disk_version || ''; lee.seenDiskVersion = lee.diskVersion;
  recordDiskVersion(st.path || lee.path, lee.diskVersion);
  // Tab navigation always returns Run and Variables to that tab's private kernel.
  paintEnv('');
  // The empty state is authored once, in Python's `_empty_editor`, and shipped as a template.
  if (!st.kind) {
    host.replaceChildren($('#leeempty')?.content.cloneNode(true) ?? '');
    paintKeyLabels(host); paintRecent();
    return;
  }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (st.kind === 'vault') await mountVault(host, st);
  else if (st.kind === 'vaultwb') await mountVaultWorkbench(host, st);
  else if (st.kind === 'web') mountWeb(host, st);
  else if (st.kind === 'pdf') mountPdf(host, st);
  else if (st.kind === 'image') mountImage(host, st);
  else if (st.kind === 'office') await mountOffice(host, st);
  else if (st.kind === 'audio' || st.kind === 'video') mountMedia(host, st);
  else if (st.kind === 'notebook') { takeLate(st); mountNotebook(host, st); lee.mountedAt = mountVersion; }
  else await mountFile(host, st);
  if (recoveredDraft) {
    const tab = $('.lee-tab.active'); tab?.classList.add('dirty'); setTabSaveState(tab, 'pending');
    status('restored an unsaved browser draft · autosave will persist it', 'ok');
    scheduleAutoSave();
  }
  // Only the newest mount takes the place: a mount that started after this one (a disk reload at boot) draws the cells again and would lose it.
  if (lee.pendingLocation && mountVersion === mountTabVersion && (!lee.pendingLocation.path || lee.pendingLocation.path === st.path)) {
    const loc = lee.pendingLocation; lee.pendingLocation = null;
    requestAnimationFrame(() => {
      // A notebook is a column of editors, each with its own line 1, so a location has to name
      // the cell. `cellIndex` is the fallback for cells with no ids of their own, written before
      // nbformat 4.5. The debug decorations are only for the debugger, since a search result is
      // somewhere to go rather than the line being executed.
      if ((loc.cellId || loc.cellIndex >= 0) && lee.kind === 'notebook') {
        let i = loc.cellId ? lee.cells.findIndex(c => c.id === loc.cellId) : -1;
        if (i < 0 && loc.cellIndex >= 0 && loc.cellIndex < lee.cells.length) i = loc.cellIndex;
        if (i >= 0) {
          // `focusCell` scrolls `#editor` to the cell: `jumpToLine` below scrolls only a code cell, so a hand-off to a section heading stayed off screen.
          focusCell(i); const view = ensureCellMounted(i);
          // The outputs and late cells above it still grow, so the cell is shown again while they settle, until the learner scrolls, types or moves on.
          let moved = false; const off = () => { moved = true; };
          $('#editor')?.addEventListener('wheel', off, {once: true, passive: true}); addEventListener('keydown', off, {once: true});
          for (const ms of [150, 400, 900, 1800]) setTimeout(() => { if (!moved && lee.sel === i) revealCell($(`.lee-cell[data-i="${i}"]`)); }, ms);
          if (loc.debug && view) {
            LeeCM.setDebugLine(view, loc.line);
            paintDebugInlineValues(view, loc.line, lee.debugState?.variables);
          }
          jumpToLine(loc.line);
          if (loc.column && view) { const at = view.state.doc.line(loc.line).from + loc.column; LeeCM.setSelection(view, at, at + String(loc.symbol || '').length); }
        }
      } else {
        jumpToLine(loc.line);
        const view = lee.editors.get('file');
        if (view && loc.column) { const at = view.state.doc.line(loc.line).from + loc.column; LeeCM.setSelection(view, at, at + String(loc.symbol || '').length); }
        if (loc.debug && view) {
          LeeCM.setDebugLine(lee.editors.get('file'), loc.line);
          paintDebugInlineValues(lee.editors.get('file'), loc.line, lee.debugState?.variables);
        }
      }
    });
  }
  restoreTabLocation(st, hadPendingLocation);
  refreshKernelPill();
  if (lee.kind === 'text' || lee.kind === 'notebook') leeSymbols();
  paintAgentAttachments();
  const split = leeSavedSplit(localStorage.getItem('lee-editor-split'));
  if (split === false) leeCloseSplit();
  else if (split?.page) { if (!lee.sidePage?.frame?.isConnected && !mountPage(split.page, split.title, split.direction)) leeCloseSplit(); }
  else if (split?.path && split.path !== st.path) {
    try { await mountSecondary(split.path, split.direction); } catch (_) { localStorage.removeItem('lee-editor-split'); }
  }
  if (lee.pendingFocusPath === st.path) {
    lee.pendingFocusPath = '';
    requestAnimationFrame(() => {
      const view = st.kind === 'text' ? lee.editors.get('file') : lee.editors.get(lee.cells[lee.sel]?.id);
      if (view) { LeeCM.focus(view); setScope('editor'); }
    });
  }
}

//: What `/tab/state` said, with the newest edit response that landed while the tab was away and the folds not yet written.
function takeLate(st) {
  const key = st.path || st.title, late = lee.nbLate.get(key); lee.nbLate.delete(key);
  if (late && late.version > (st.version ?? 0)) Object.assign(st, {cells: late.cells, version: late.version});
  lee.cells = st.cells = foldsSince(key, st.cells, st.version);
  lee.nbVersions.set(key, st.version);
}
function rememberBuffer(key, payload) {
  payload = {...payload, seq: nextSeq(), ...(payload.kind === 'notebook' ? seenRow(payload.title || payload.path, payload.id) : {})};
  lee.buffers.set(key, payload.text); lee.dirtyBuffers.add(key); persistDraft(key, payload);
  clearTimeout(lee.bufferTimers.get(key));
  lee.bufferTimers.set(key, setTimeout(() => {
    lee.bufferTimers.delete(key);
    const documentKey = payload.path || payload.title || lee.tabKey || key;
    post('/tab/buffer', {...payload, base_disk_version: draftBaseFor(documentKey)})
      .catch(e => status(String(e.message || e), 'err'));
  }, 120));
}

// A PDF, in the viewer the browser already ships: an `<iframe>` pointed at the bytes, plus the two
// things an iframe cannot do for itself, which are opening the file outside Leela and saying
// something useful if the viewer is disabled.
function mountPdf(host, st) {
  // The filename goes in the path as well as the query, because the browser's own viewer titles
  // itself from the last path segment.
  // The segment is decoration: the server still resolves the file from `path` alone, and must, or
  // a name in a URL would become a way to ask for a different file.
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

function noteStaleTab(st, recoveredDraft) {
  const name = (st.path || st.title || 'this file').split('/').pop();
  // A recovered draft is the user's own unsaved work, so it is never dropped for a disk change.
  if (st.dirty || recoveredDraft) {
    status(`${name} changed on disk; your unsaved version is what you are looking at`, 'err');
    return;
  }
  status(`${name} changed on disk. Reloading…`, 'busy');
  takeDiskVersion(st.path).then(() => status(`${name} reloaded from disk`, 'ok'))
                          .catch(e => status(String(e.message || e), 'err'));
}
// A later tab must not take the answers asked for an earlier one.
let fileExtrasVersion = 0;

/* An image, in the same chrome as a PDF. Fit is the default because an image opened from a vault
   or a file tree is being identified rather than inspected. The dimensions are shown either way,
   since "is this the 2x asset" is the usual question. */
function mountImage(host, st) {
  const name = (st.path || '').split('/').pop() || 'image';
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  host.innerHTML =
    `<div class="lee-doc">` +
    `<div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-dim" data-image-size></span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-image-fit>actual size</button>` +
    `<a class="lee-btn" href="${esc(raw)}" target="_blank" rel="noopener noreferrer">open externally</a>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body lee-image-body fit">` +
    `<img class="lee-image" alt="${esc(st.title || name)}" src="${esc(raw)}"></div></div>`;
  const img = $('.lee-image', host), body = $('.lee-image-body', host), button = $('[data-image-fit]', host);
  img.onload = () => { $('[data-image-size]', host).textContent = `${img.naturalWidth}×${img.naturalHeight}`; };
  img.onerror = () => { body.innerHTML = `<div class="lee-err">${esc(name)} could not be displayed</div>`; };
  button.onclick = () => {
    const fit = body.classList.toggle('fit');
    button.textContent = fit ? 'actual size' : 'fit to window';
  };
}

/* The WebKit in some macOS versions plays no Ogg or WebM, so a file that fails says so and offers the
   system's own player rather than a silent, empty control. */
function mountMedia(host, st) {
  const name = (st.path || '').split('/').pop() || st.kind;
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  const tag = st.kind === 'audio' ? 'audio' : 'video';
  host.innerHTML =
    `<div class="lee-doc"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-spacer"></span><button class="lee-btn" data-media-open>open in default app</button>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body lee-media-body"><${tag} class="lee-media" controls preload="metadata" src="${esc(raw)}"></${tag}></div></div>`;
  const open = () => post('/media/open?path=' + encodeURIComponent(st.path))
    .then(() => status('opened in the default app', 'ok')).catch(e => status(String(e.message || e), 'err'));
  $('[data-media-open]', host).onclick = open;
  $('.lee-media', host).onerror = () => {
    const body = $('.lee-media-body', host);
    if (!body) return;   // the tab has moved on
    body.innerHTML = `<div class="lee-err" data-media-error>${esc(name)} cannot play here. ` +
      `Open it in the default app.<br><button class="lee-btn" data-media-open>open in default app</button></div>`;
    $('.lee-media-body [data-media-open]', host).onclick = open;
  };
}

/* The setting names the three views `source`, `preview` and `split`; the buttons and the stage's
   CSS have always said `edit`, `rendered` and `split`, so the names meet here and nowhere else.
   Adopted once a page: `origins` still says `default` until the settings are read again, so a
   second adoption would put the old key back over a view chosen since. */
const MD_VIEWS = {source: 'edit', preview: 'rendered', split: 'split'};
const MD_PREFS = {edit: 'source', rendered: 'preview', split: 'split'};
let mdAdopted = false;
async function adoptMdView() {
  if (mdAdopted) return;
  mdAdopted = true;
  await prefAdopt('workbench', 'markdownView', 'lee-md-view', v => MD_PREFS[v] || 'split');
}

const lspAnswers = new Map();
function paintCrumbSymbols(d) {
  const el = $('#editorcrumbs'); if (!el) return;
  const names = (d.symbols || []).slice(0, 40).map(s => `<button data-line="${(s.range?.start?.line || 0) + 1}">${esc(s.name)}</button>`).join('');
  el.insertAdjacentHTML('beforeend', `<i>›</i><span class="lee-breadcrumb-symbols">${names}</span>`);
  el.onclick = e => { const b = e.target.closest('[data-line]'); if (b) jumpToLine(b.dataset.line); };
}
// The server answers a mount's two questions slowly or not at all, so they are asked once the tab has
// painted and is still the one on screen, and a clean file's answer is kept for its disk version.
function lspExtras(v, st, crumbMode, mine, dirty) {
  if (!servedLang(st.lang) || !st.path) return;
  const asks = [];
  if (lee.editorPrefs.inlayHints) asks.push(['/lsp/inlay-hints', d => LeeCM.setInlayHints?.(v, d.hints || [])]);
  if (['symbols', 'pathAndSymbols'].includes(crumbMode)) asks.push(['/lsp/symbols', paintCrumbSymbols]);
  if (!asks.length) return;
  const live = () => mine === fileExtrasVersion && lee.editors.get('file') === v;
  requestAnimationFrame(() => setTimeout(() => {
    if (!live()) return;
    const text = LeeCM.getDoc(v);
    for (const [url, paint] of asks) {
      const key = `${url} ${st.path} ${st.disk_version}`, known = !dirty && lspAnswers.get(key);
      if (known) { paint(known); continue; }
      api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: st.path, text})})
        .then(d => {
          if (!live()) return;
          if (!dirty && st.disk_version && (d.hints || d.symbols || []).length) {
            lspAnswers.set(key, d); if (lspAnswers.size > 60) lspAnswers.delete(lspAnswers.keys().next().value);
          }
          paint(d);
        }).catch(() => {});
    }
  }, 300));
}

async function mountFile(host, st) {
  const isProject = st.path?.endsWith('/pyproject.toml') || st.title === 'pyproject.toml';
  const crumbMode=lee.workbenchPrefs.breadcrumbs||'pathAndSymbols',crumb=crumbMode==='off'?'':`<nav class="lee-breadcrumbs" id="editorcrumbs" aria-label="File and symbol path"><span>${esc(compactPath(st.path||st.title||''))}</span></nav>`;
  // Markdown gets a rendered pane beside the editor. The editor stays mounted in every view and is
  // only hidden by CSS, so saving, autosave, blame, the change gutter and jump-to-line all keep
  // reaching `lee.editors.get('file')`.
  const isMd = (st.lang || '') === 'markdown';
  if (isMd) await adoptMdView();
  const view = isMd ? (MD_VIEWS[prefGet('workbench', 'markdownView', 'source')] || 'split') : '';
  host.innerHTML = crumb + (isProject ? '<div class="lee-package-summary" id="packagebar" hidden></div>' : '') +
    (isMd ? `<div class="lee-doc-head lee-md-bar"><div class="lee-segbar" id="mdview" aria-label="markdown view">` +
            ['edit', 'split', 'rendered'].map(v =>
              `<button class="lee-seg${v === view ? ' active' : ''}" data-md-view="${v}">${v}</button>`).join('') +
            `</div><span class="lee-spacer"></span>` +
            `<span class="lee-dim">the change gutter and blame stay on the source</span></div>` : '') +
    // `data-md-base` is this file's folder: a figure written `![](img/a.png)` is relative to the
    // document, not to the page the renderer drops it into.
    (isMd ? `<div class="lee-md-stage" data-view="${view}" data-md-base="${esc((st.path || '').slice(0, (st.path || '').lastIndexOf('/')))}">` +
            `<div class="lee-cm" id="filecm"></div>` +
            `<div class="lee-md-preview" id="mdpreview" data-markdown=""></div></div>`
          : '<div class="lee-cm" id="filecm"></div>');
  if (st.note) host.insertAdjacentHTML('afterbegin', `<div class="lee-doc-head lee-readonly-note" role="note">${esc(st.note)}</div>`);
  // Nothing in the editor depends on these two answers, and awaiting them held an empty box on
  // screen for as long as they took: `/editor/packages` starts an interpreter to read version
  // metadata, and `/git/file` is four git subprocesses. Together they were 80 to 200ms of blank
  // pyproject. The file is mounted from the text `/tab/state` already carried, and each answer is
  // applied when it lands, to the editor it was asked for.
  let git = {ranges: []}, packages = null;
  lee.fileGit = git;
  const key = st.path || st.title;
  const v = createEditor($('#filecm'), {
    // A cached value is authoritative only after a real user edit, or a stale empty entry blanks
    // a freshly loaded file.
    doc: lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : (st.text || ''),
    lang: st.lang || 'python', readOnly: !!st.read_only, lineNums: true, lintPath: st.path || '', tableKeys: true,
    completeUrl: '/complete', changedLines: git.ranges || [], breakpoints: lee.breakpoints.get(st.path)||[],
    onBreakpoint: st.lang==='python' ? lines=>{rememberBreakpoints(st.path,lines);if(lee.directDebug)post('/debug/breakpoints',{path:st.path,breakpoints:lines}).catch(e=>status(e.message||String(e),'err'));} : null,
    onChangeClick: line => showChangePopup(st.path, line),
    onDefinition: name => findDefinition(name), onSelection: () => {
      clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120);
    },
    onChange: txt => {
      rememberBuffer(key, {path: key, kind: 'text', text: txt}); markDirty();
      // The preview follows the buffer, not the file. `renderMarkdown` is debounced and drops
      // superseded renders, so this is safe on every keystroke.
      if (isMd) renderMarkdown($('#mdpreview'), txt, false, el => rupakaFences(el, `file:${key}`));
    },
  });
  lee.editors.set('file', v);
  if (isMd) {
    // The rendered pane carries the same change marks as the gutter, placed by block rather than
    // by line. Only this first render is annotated. See `paintMarkdownFileChanges`.
    renderMarkdown($('#mdpreview'), LeeCM.getDoc(v), false,
                   el => { paintMarkdownFileChanges(el, git.ranges || []); rupakaFences(el, `file:${key}`); });
    $('#mdview').onclick = e => {
      const b = e.target.closest('[data-md-view]'); if (!b) return;
      const next = b.dataset.mdView;
      prefSet('workbench', 'markdownView', MD_PREFS[next] || 'split');
      $('.lee-md-stage').dataset.view = next;
      $$('#mdview .lee-seg').forEach(x => x.classList.toggle('active', x === b));
      // The editor was display:none a moment ago, so CodeMirror has stale measurements and draws
      // the cursor in the wrong place until it re-measures.
      if (next !== 'rendered') requestAnimationFrame(() => LeeCM.focus(v));
    };
  }
  const mine = ++fileExtrasVersion;
  lspExtras(v, st, crumbMode, mine, lee.dirtyBuffers.has(key));
  if (packages) paintPackageVersions(v, packages);
  if (st.path) {
    api('/git/file?path=' + encodeURIComponent(st.path)).then(d => {
      if (mine !== fileExtrasVersion || !d) return;
      lee.fileGit = d;
      LeeCM.setChangedLines(v, d.ranges || []);
      if (isMd) paintMarkdownFileChanges($('#mdpreview'), d.ranges || []);
    }).catch(() => {});
    if (isProject && lee.workbenchPrefs.dependencyHints !== false)
      api('/editor/packages?path=' + encodeURIComponent(st.path))
        .then(d => { if (mine === fileExtrasVersion && d) paintPackageVersions(v, d); }).catch(() => {});
  }
  closeChangePopup(); armChangeGutter($('#filecm'));
  $('#filecm').addEventListener('focusin', () => { lee.activeEditor='primary'; setScope('editor'); });
}

/* What the second pane can hold. A notebook goes in as a reading copy: its cells are what a person
   compares across a merge, and the editors, the kernel and the selection all belong to one notebook
   at a time. The live surfaces are bound to the pane they were opened in and are not offered. */
const SPLIT_KINDS = {text: 'editable', notebook: 'reading copy', pdf: 'view', image: 'view', office: 'view'};

function secondaryNotebook(host, st) {
  "The cells of a notebook, to read beside something else. No editors, no outputs, no execution."
  const cells = (st.cells || []).map((c, i) =>
    `<article class="lee-split-cell ${esc(c.cell_type)}"><header>${i + 1} · ${esc(c.cell_type)}` +
    `${c.execution_count != null ? ` · [${esc(String(c.execution_count))}]` : ''}</header>` +
    `<pre>${esc(String(c.source || ''))}</pre></article>`).join('');
  host.querySelector('.lee-split-body').innerHTML =
    cells || '<div class="lee-dim">this notebook has no cells</div>';
}

function splitStage(direction) {
  "The second pane, shown beside the editor with its editor destroyed and its side page dropped."
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return null;
  if (lee.editors.get('secondary')) { LeeCM.destroy(lee.editors.get('secondary')); lee.editors.delete('secondary'); }
  lee.sidePage = null;
  stage.classList.add('split',`split-${direction}`); stage.classList.remove(`split-${direction==='vertical'?'horizontal':'vertical'}`);
  host.hidden=false; setSplitSize(localStorage.getItem(SPLIT_SIZE)); return host;
}

async function mountSecondary(path, direction = 'vertical') {
  const stage=$('#editorstage'),host=$('#editor2'); if (!stage || !host) return;
  const st=await api('/tab/state?path='+encodeURIComponent(path));
  if (!SPLIT_KINDS[st.kind]) return status(`a ${st.kind || 'blank'} tab cannot be opened beside another; text, notebooks, PDFs, images and office files can`,'err');
  if (st.kind !== 'text') {
    splitStage(direction);
    host.innerHTML=`<div class="lee-split-head"><span>${esc(compactPath(st.path||path))}</span>` +
      `<span class="lee-dim">${esc(SPLIT_KINDS[st.kind])}</span>` +
      `<button class="lee-btn" onclick="leeCloseSplit()">close</button></div>` +
      `<div class="lee-split-body" id="filecm2"></div>`;
    if (st.kind === 'notebook') secondaryNotebook(host, st);
    else if (st.kind === 'pdf') mountPdf($('.lee-split-body', host), st);
    else if (st.kind === 'office') mountOffice($('.lee-split-body', host), st);
    else mountImage($('.lee-split-body', host), st);
    recordDiskVersion(st.path || path, st.disk_version || '');
    lee.secondaryPath = path; lee.activeEditor = 'primary';
    localStorage.setItem('lee-editor-split', JSON.stringify({path, direction}));
    return;
  }
  splitStage(direction); host.innerHTML=`<div class="lee-split-head"><span>${esc(compactPath(st.path))}</span><button class="lee-btn" onclick="leeCloseSplit()">close</button></div><div class="lee-cm" id="filecm2"></div>`;
  const key=st.path,view=createEditor($('#filecm2'),{doc:lee.dirtyBuffers.has(key)?lee.buffers.get(key):(st.text||''),lang:st.lang||'python',readOnly:!!st.read_only,lineNums:true,lintPath:st.path||'',completeUrl:'/complete',tableKeys:true,
    onDefinition:name=>findDefinition(name),onChange:txt=>{rememberBuffer(key,{path:key,kind:'text',text:txt});lee.editVersion+=1;const tab=$$('.lee-tab').find(x=>x.title===key);tab?.classList.add('dirty');setTabSaveState(tab,'pending');scheduleAutoSave();}});
  recordDiskVersion(st.path || path, st.disk_version || '');
  lee.editors.set('secondary',view);lee.secondaryPath=path;$('#filecm2').addEventListener('focusin',()=>{lee.activeEditor='secondary';setScope('editor');});localStorage.setItem('lee-editor-split',JSON.stringify({path,direction}));LeeCM.focus(view);
}
function mountPage(url, title = '', direction = 'vertical') {
  "The local Leela page `url` in the second pane, in a frame with `pane=1`. False when `url` is not local or there is no second pane."
  const src = leePaneURL(url), host = src && splitStage(direction === 'horizontal' ? 'horizontal' : 'vertical');
  if (!host) return false;
  const head = document.createElement('div'), trail = document.createElement('span'), own = document.createElement('a'),
    x = document.createElement('button'), frame = document.createElement('iframe');
  head.className = 'lee-split-head'; trail.className = 'lee-split-trail'; own.className = 'lee-split-own';
  own.textContent = 'Open in a tab'; own.target = '_blank'; own.rel = 'noopener'; own.title = 'Open this page in a new tab';
  x.className = 'lee-btn'; x.type = 'button'; x.textContent = 'close'; x.onclick = leeCloseSplit;
  frame.src = src; head.append(trail, own, x); host.replaceChildren(head, frame);
  const page = lee.sidePage = {frame, url: leeOwnURL(url), title: String(title || ''), trail: [], direction: direction === 'horizontal' ? 'horizontal' : 'vertical',
    at(u, t) { page.url = leeOwnURL(u); if (t) page.title = t; paintSidePage(page); },
    open(u) { const p = leePaneURL(u); if (!p) return; try { frame.contentWindow.location.replace(p); } catch (_) { frame.src = p; } },
    link: openExternal,
    key: k => document.body.dispatchEvent(new KeyboardEvent('keydown', {...k, bubbles: true, cancelable: true})),   // the keymap on `window` decides
    close: leeCloseSplit};
  lee.secondaryPath = ''; lee.activeEditor = 'primary';
  paintSidePage(page);
  return true;
}
function paintSidePage(page) {
  "The trail, the title and the Open in a tab link of the side page, as text, and the page kept for a reload."
  const head = page.frame.previousElementSibling, trail = $('.lee-split-trail', head), b = document.createElement('strong');
  trail.replaceChildren();
  for (const [label, href] of page.trail) {
    const a = document.createElement('a'); a.textContent = label; a.href = href;
    a.onclick = e => { e.preventDefault(); page.trail = []; page.open(href); };
    trail.append(a, ' › ');
  }
  b.textContent = page.title || 'Side page'; trail.append(b);
  page.frame.title = b.textContent; $('.lee-split-own', head).href = leeOwnURL(page.url);
  localStorage.setItem('lee-editor-split', JSON.stringify({page: page.url, title: page.title, direction: page.direction}));
}
function leeCloseSplit(){const stage=$('#editorstage'),host=$('#editor2'),v=lee.editors.get('secondary');if(v)LeeCM.destroy(v);lee.editors.delete('secondary');lee.sidePage=null;lee.secondaryPath='';lee.activeEditor='primary';stage?.classList.remove('split','split-vertical','split-horizontal');if(host){host.hidden=true;host.innerHTML='';}localStorage.removeItem('lee-editor-split');}
window.leeCloseSplit=leeCloseSplit;
function leeSplit(direction='vertical') {
  // Any open tab the second pane can hold, not only the text ones: two notebooks beside each other
  // is what a person merging them is looking for.
  const rows=$$('.lee-tab').filter(t=>SPLIT_KINDS[t.dataset.kind]&&t.title!==lee.path)
    .map(t=>({path:t.title,kind:t.dataset.kind,label:$('.lee-tab-name',t)?.textContent||t.title}));
  if (!rows.length) return status('open another file before splitting','err');
  const m=modal(`<div class="lee-mhead">Split editor<span class="sub">${direction==='vertical'?'side by side':'top and bottom'}</span></div><div class="lee-modallist">${rows.map((r,i)=>`<button class="lee-mrow" data-i="${i}"><strong>${esc(r.label)}</strong><span class="sub">${esc(r.kind)} · ${esc(compactPath(r.path))}</span></button>`).join('')}</div>`);
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
  return cells.flatMap((c, i) => c.cell_type === 'markdown' ? String(c.source || '').split('\n').flatMap((line, n) => {
    const m = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    return m ? [{i, level: m[1].length, text: m[2].replace(/[*_`]/g, ''), folds: n === 0 && headingLevel(c) > 0}] : [];
  }) : []);
}
function notebookToc(cells) {
  const headings = notebookHeadings(cells);
  const toc = document.createElement('details'); toc.className = 'lee-nb-toc';
  toc.innerHTML = `<summary>contents <span>${headings.length || 'no'} sections</span></summary><nav></nav>`;
  const nav = toc.querySelector('nav');
  if (!headings.length) nav.innerHTML = '<div class="lee-dim">Add Markdown headings to build the outline.</div>';
  else headings.forEach(h => {
    const row = document.createElement('div'); row.className = 'lee-toc-row'; row.style.setProperty('--level', h.level);
    // Only a cell's first line is a heading that folds; a later one in the same cell is a place to go.
    row.innerHTML = `<button class="lee-toc-jump">${esc(h.text)}</button>` + (h.folds
      ? `<button class="lee-toc-fold" data-i="${h.i}" title="collapse or expand this section">${headingFolded(cells[h.i]) ? '+' : '−'}</button>` : '');
    row.querySelector('.lee-toc-jump').onclick = () => { toc.open = false; focusCell(h.i); };
    const fold = row.querySelector('.lee-toc-fold'); if (fold) fold.onclick = () => toggleHeading(h.i);
    nav.appendChild(row);
  });
  return toc;
}
function observeNotebookCells(host, cells) {
  // Cell shells preserve the notebook's geometry, and CodeMirror is only created near the
  // viewport, so a 150-cell notebook paints immediately instead of constructing 150 editors in
  // one uninterruptible task.
  //
  // Built when the pane stops, not while it moves. Constructing one editor costs a whole frame in
  // the engine the packaged app runs, and scrolling a 155-cell notebook end to end crosses about
  // eighty of them: 103ms frames against 17 idle. Waiting for the scroll to settle builds the same
  // editors and holds 60fps throughout.
  lee.cellObserver?.disconnect();
  clearTimeout(lee.cellMountTimer);
  const owed = lee.cellsOwed = new Set();
  const drain = () => {
    lee.cellMountTimer = 0;
    for (const i of owed) ensureCellMounted(i);
    owed.clear();
  };
  lee.cellObserver = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) {
      owed.add(+e.target.dataset.i); lee.cellObserver?.unobserve(e.target);
    }
    if (!owed.size) return;
    clearTimeout(lee.cellMountTimer);
    lee.cellMountTimer = setTimeout(drain, 120);
  }, {root: host, rootMargin: '700px 0px'});
  $$('.lee-cell', host).forEach((el, i) => {
    if (i === lee.sel || cells[i]?.running) ensureCellMounted(i);
    else lee.cellObserver.observe(el);
  });
}

/* Coming back to a notebook built every cell of it again, and laying a hundred of those out is what
   a switch costs: 319KB of elements for a 100-cell notebook, about 160ms of layout in the window
   Leela ships and 10 to 30 in Chrome. The shells are kept per file on the way out and reattached on
   the way back, so only the editors near the viewport are built again.

   Kept only for a file that was clean, and taken only when the file has not moved under it: a shell
   carries the cell's summary line and its outputs, and both are answers about a particular version. */
const nbShells = new Map();
const NB_SHELLS = 4;

function keepNotebookShells(host, key, version) {
  if (!host || !key || !version || !$('.lee-cell', host)) return;
  const frag = document.createDocumentFragment();
  while (host.firstChild) frag.appendChild(host.firstChild);
  // The views are already destroyed. What they left behind is not a shell, so it goes.
  frag.querySelectorAll('.lee-cm').forEach(cm => { cm.innerHTML = ''; });
  nbShells.delete(key);
  nbShells.set(key, {frag, version, ids: [...frag.querySelectorAll('.lee-cell')].map(el => el.dataset.id).join(), cells: lee.cells});
  for (const stale of [...nbShells.keys()].slice(0, nbShells.size - NB_SHELLS)) nbShells.delete(stale);
}

//: `{key: version}` of each kept notebook, which `/tab/state` answers with `same` instead of its cells.
function heldNotebookVersions() {
  return Object.fromEntries([...nbShells].map(([key, held]) => [key, Number(held.version.split('@').pop())]));
}
function heldNotebookCells(key) { return nbShells.get(key)?.cells || []; }

function takeNotebookShells(host, st) {
  const key = st.path || st.title, held = key && nbShells.get(key);
  if (!held || held.version !== `${st.disk_version}@${st.version}` || held.ids !== st.cells.map(c => c.id).join()) return false;
  nbShells.delete(key);          // moving a fragment empties it, so it is good for one mount
  host.appendChild(held.frag);
  rupakaReviveIn(host);
  return true;
}

function mountNotebook(host, st) {
  lee.cellObserver?.disconnect();
  for (const [key, view] of [...lee.editors.entries()]) {
    if (key === 'exec' || key === 'file') continue;
    LeeCM.destroy(view); lee.editors.delete(key);
  }
  host.innerHTML = '';
  lee.headingHidden = hiddenIds(st.cells);
  if (!takeNotebookShells(host, st)) {
    host.appendChild(notebookToc(st.cells));
    st.cells.forEach((c, i) => host.appendChild(cellEl(c, i)));
  }
  paintHeadings(st.cells);
  for (const c of st.cells) if (isExercise(c)) renderExercise(c);
  selectCell(Math.min(lee.sel, st.cells.length - 1));
  observeNotebookCells(host, st.cells);
  lee.notebookGit = {};       // marks belong to the notebook that was open, not the next one
  paintNotebookGitMarks();
  queueNotebookOverview();    // a notebook outside a repository still gets its viewport thumb
}

function patchNotebook(host, before, cells, op = '') {
  // Keep unchanged cell DOM and CodeMirror views alive. Moving those nodes is free and, unlike
  // rebuilding the notebook, cannot flash blank or reset the viewport.
  lee.cellObserver?.disconnect();
  const oldCells = new Map(before.map(c => [c.id, c]));
  const oldEls = new Map($$('.lee-cell', host).map(el => [el.dataset.id, el]));
  const ids = new Set(cells.map(c => c.id));
  lee.headingHidden = hiddenIds(cells);
  for (const [id, el] of oldEls) if (!ids.has(id)) {
    const view = lee.editors.get(id); if (view) LeeCM.destroy(view);
    lee.editors.delete(id); el.remove();
  }
  const toc = notebookToc(cells), oldToc = $('.lee-nb-toc', host);
  if (oldToc) oldToc.replaceWith(toc); else host.prepend(toc);
  cells.forEach((c, i) => {
    const old = oldCells.get(c.id);
    let el = oldEls.get(c.id);
    // Against what the editor holds now: `before` shares its cell objects with code that rewrites them.
    const ed = lee.editors.get(c.id), held = ed ? LeeCM.getDoc(ed) : old?.source;
    const changed = !old || held !== c.source || old.cell_type !== c.cell_type;
    if (!el || changed) {
      const view = lee.editors.get(c.id); if (view) LeeCM.destroy(view);
      lee.editors.delete(c.id);
      const key = `${lee.tabKey}:${c.id}`;
      lee.buffers.set(key, c.source); lee.dirtyBuffers.add(key);
      const fresh = cellEl(c, i);
      if (el) el.replaceWith(fresh);
      el = fresh;
    } else {
      el.dataset.i = i;
      el.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '') + (lee.headingHidden.has(c.id) ? ' heading-hidden' : '');
      const buttons = $('.lee-cellbtns', el); if (buttons) buttons.innerHTML = cellButtons(i);
      const summary = $('.lee-cell-summary', el);
      if (summary) summary.textContent = String(c.source || '').trim().split('\n')[0] || 'empty cell';
      paintCellMeta(el, c, i);   // an insert above renumbers every cell after it
      const gutter = $('#g-' + c.id); if (gutter) gutter.textContent = gutterFor(c);
      const context = $('.lee-cell-context', el); if (context) paintCellContext(context, c);
      const slide = $('.lee-cell-slide', el); if (slide) paintCellSlide(slide, c);
      setCellState(c, cellState(c)); setCellTime(c, c.execution_ms, c.running);
      if (op === 'clear' || op === 'clear_cell') renderOutputs(c);
    }
    host.appendChild(el); // appending an existing node reorders it without remounting
    if (c.extra?.lesson) { paintLessonCell(el, c); renderLessonReveal(c); }
    paintGuideButton(el, c);
    if (isExercise(c)) renderExercise(c, el);
  });
  paintHeadings(cells);
  paintSel();
  observeNotebookCells(host, cells);
  // `className` is rewritten above for every reused cell, so the marks are reapplied from what
  // was last read rather than refetched. Only the DOM moved.
  repaintNotebookGitMarks();
  queueNotebookOverview();
}

function ensureCellMounted(i) {
  const c = lee.cells[i];
  if (!c || lee.editors.has(c.id)) return lee.editors.get(c?.id);
  mountCell(c, i);
  return lee.editors.get(c.id);
}

// A prompt cell's gutter is its own mark, so the three kinds are told apart without reading them.
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
  refreshCellMeta(c);           // the run count and the outputs it left are in the tooltip
  queueNotebookOverview();      // a failure is one of the two things the stripe reports
}
//: The kernel is a new one: a presentation clears what it showed from the old one.
const kernelRestarted = () => dispatchEvent(new CustomEvent('lee-kernel-restart'));
function markPreviousRuns() {
  for (const c of lee.cells) {
    if (c.cell_type !== 'code' || c.execution_count == null) continue;
    c.fresh = false; setCellState(c, 'previous'); setCellTime(c, c.execution_ms, false);
  }
  kernelRestarted();
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

/* The banner says where a cell sits and how big it is. The gutter carries the execution count,
 * which is blank until the cell runs and renumbers on every rerun. */
//: The gutter tag. A code cell is tagged with the notebook's own language, not always Python.
const LANG_TAGS = {python: 'py', rust: 'rs', javascript: 'js', typescript: 'ts'};
const cellKind = (c) => c.cell_type === 'code' ? (LANG_TAGS[nbLang()] || nbLang())
  : ({markdown: 'md', prompt: 'prompt'}[c.cell_type] || c.cell_type);
const cellLines = (c) => String(c.source || '').split('\n').length;
const plural = (n, word, many = word + 's') => `${n} ${+n === 1 ? word : many}`;
function cellMetaTitle(c, i) {
  const src = String(c.source || '');
  const rows = [`cell ${i + 1} of ${lee.cells.length} · ${c.cell_type} · ${plural(cellLines(c), 'line')}, ${src.length} chars`];
  if (c.cell_type === 'code')
    rows.push([c.execution_count == null ? 'not run' : `run ${c.execution_count}`,
               formatCellTime(c.execution_ms), plural((c.outputs || []).length, 'output')].filter(Boolean).join(' · '));
  rows.push('click to copy the id');
  return rows.join('\n');
}
function paintCellMeta(el, c, i) {
  const meta = el && $('.lee-cell-meta', el); if (!meta) return;
  $('.lee-cell-no', meta).textContent = '#' + (i + 1);
  $('.lee-cell-size', meta).textContent = `${cellKind(c)} · ${plural(cellLines(c), 'line')}`;
  const id = $('.lee-cell-id', meta); if (id) id.textContent = c.id;
  meta.dataset.cellId = c.id; meta.title = cellMetaTitle(c, i);
}
function copyCellId(button) {
  navigator.clipboard?.writeText(button.dataset.cellId || '');
  status('cell id copied', 'ok');
}
function refreshCellMeta(c) {
  const el = $(`.lee-cell[data-id="${c.id}"]`);
  if (el) paintCellMeta(el, c, +el.dataset.i);
}
window.leeCopyCellId = copyCellId;

/* The per-cell controls, from the same table the toolbar comes from. They act on the cell they are
 * drawn in rather than on the selected one, so ▶ on the third cell runs the third cell. */
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
  const r = await nbEdit({op: 'context', i, mode}); if (!r) return;
  Object.assign(c, r.cells?.find(x => x.id === c.id));
  const button = $(`.lee-cell[data-i="${i}"] .lee-cell-context`); if (button) paintCellContext(button, c);
  status(`cell ${i + 1}: ${contextLabel(mode)}`, 'ok');
}
window.leeCellContext = cycleCellContext;
//: RISE writes `-` for a cell that continues the slide above, which is what no type means too.
const SLIDE_TYPES = ['none', 'slide', 'subslide', 'fragment', 'skip', 'notes'];
const SLIDE_TAGS = {slide: 'slide', subslide: 'sub', fragment: 'frag', skip: 'skip', notes: 'notes'};
const slideType = c => { const t = c.extra?.slideshow?.slide_type; return SLIDE_TYPES.includes(t) ? t : 'none'; };
function paintCellSlide(button, c) {
  const t = slideType(c), cell = button.closest('.lee-cell');
  button.dataset.type = t; button.textContent = SLIDE_TAGS[t] || 'slide';
  button.title = t === 'none' ? 'continues the slide above; click to start a slide' : `slide type: ${t}; click for the next type`;
  if (cell) cell.dataset.slide = t;
}
async function setCellSlide(indices, type) {
  const r = await nbEdit({op: 'slide', i: indices[0], indices, type});
  if (r?.cells) status(`${indices.length === 1 ? `cell ${indices[0] + 1}` : plural(indices.length, 'cell')}: ${type === 'none' ? 'no slide type' : type}`, 'ok');
}
function cycleCellSlide(i) {
  const c = lee.cells[i]; if (!c) return;
  return setCellSlide([i], SLIDE_TYPES[(SLIDE_TYPES.indexOf(slideType(c)) + 1) % SLIDE_TYPES.length]);
}
window.leeCellSlide = button => cycleCellSlide(+button.closest('.lee-cell').dataset.i)?.catch(e => status(String(e.message || e), 'err'));

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
  d.className = 'lee-cell ' + c.cell_type + (lee.collapsedCells.has(c.id) ? ' collapsed' : '') + (lee.headingHidden.has(c.id) ? ' heading-hidden' : '');
  d.dataset.i = i; d.dataset.id = c.id;
  d.style.setProperty('--lee-cell-lines', Math.min(20, Math.max(2, String(c.source || '').split('\n').length)));
  const state = cellState(c);
  d.innerHTML =
    `<div class="lee-gutter" draggable="true" title="drag to move cell">` +
    `<button class="lee-cell-fold" title="collapse cell" aria-label="collapse cell">${lee.collapsedCells.has(c.id) ? '+' : '−'}</button>` +
    (c.cell_type === 'markdown' ? `<button class="lee-heading-caret" aria-label="collapse or expand this section"></button>` : '') +
    `<div class="lee-execution-count" id="g-${esc(c.id)}">${gutterFor(c)}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cell-chrome">` +
    `<button class="lee-cell-meta" data-cell-id="${esc(c.id)}" title="${esc(cellMetaTitle(c, i))}" ` +
    `onclick="event.stopPropagation();leeCopyCellId(this)">` +
    `<span class="lee-cell-no">#${i + 1}</span>` +
    `<span class="lee-cell-size">${esc(cellKind(c))} · ${esc(plural(cellLines(c), 'line'))}</span>` +
    `<span class="lee-cell-id">${esc(c.id)}</span></button>` +
    `<span class="lee-cell-summary">${esc(String(c.source || '').trim().split('\n')[0] || 'empty cell')}</span>` +
    `<span class="lee-cell-state ${state}" id="state-${esc(c.id)}" ` +
    `title="${state === 'done' ? 'ran successfully in the current kernel' : state === 'error' ? 'run failed in the current kernel' : state === 'previous' ? 'saved output from a previous kernel; run to restore variables' : 'not run'}">${stateSvg(state)}</span>` +
    `<time class="lee-cell-time" id="time-${esc(c.id)}" title="last execution time" ` +
    `${c.execution_ms == null ? 'hidden' : ''}>${esc(formatCellTime(c.execution_ms))}</time>` +
    `<button class="lee-cell-context" data-mode="${esc(c.context_mode || 'auto')}" ` +
    `onclick="event.stopPropagation();leeCellContext(${i})">${esc(contextLabel(c.context_mode || 'auto'))}</button>` +
    `<button class="lee-cell-slide" onclick="event.stopPropagation();leeCellSlide(this)"></button>` +
    `<div class="lee-model-running" id="model-${esc(c.id)}" role="status" aria-live="polite" hidden>` +
    `<span class="lee-running-dot" aria-hidden="true">●</span>` +
    `<span class="lee-running-copy">Model is running</span>` +
    `<span class="lee-running-time"> · starting</span></div>` +
    `<div class="lee-cellbtns">${cellButtons(i)}</div></div>` +
    `${c.cell_type === 'markdown' ? mdCellHost(c) + '<button class="lee-heading-badge" hidden></button>' : ''}<div class="lee-cm" id="cm-${esc(c.id)}"></div><div id="out-${esc(c.id)}"></div>` +
    `${isExercise(c) ? `<div class="lee-exercise" id="ex-${esc(c.id)}" data-guide-id="check"></div>` : ''}</div>`;
  paintCellSlide($('.lee-cell-slide', d), c);
  if (c.cell_type === 'markdown') {
    d.tabIndex = -1; paintMarkdownCell(d, c);
    d.querySelector('.lee-md-cell').addEventListener('dblclick', () => editMarkdownCell(+d.dataset.i));
    d.querySelector('.lee-heading-caret').onclick = e => { e.stopPropagation(); toggleHeading(+d.dataset.i); };
    d.querySelector('.lee-heading-badge').onclick = e => { e.stopPropagation(); setHeadings([+d.dataset.i], false); };
  }
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
  if (c.extra?.lesson) paintLessonCell(d, c);
  paintGuideButton(d, c);
  if (isExercise(c)) renderExercise(c, d);
  return d;
}

function setCellCollapsed(i, value = null) {
  const c = lee.cells[i]; if (!c) return;
  const collapsed = value === null ? !lee.collapsedCells.has(c.id) : value;
  if (collapsed) lee.collapsedCells.add(c.id); else lee.collapsedCells.delete(c.id);
  const el = $(`.lee-cell[data-i="${i}"]`); el?.classList.toggle('collapsed', collapsed);
  const button = el?.querySelector('.lee-cell-fold'); if (button) button.textContent = collapsed ? '+' : '−';
}

/* A heading cell is a markdown cell whose first line is a heading, and JupyterLab's
   `heading_collapsed` is its fold. What a fold hides is worked out from the headings every time
   and never stored. The same rules as `heading_level` and `section_end` in `nb.py`. */
const headingLevel = c => c?.cell_type === 'markdown' ? (/^(#{1,6})[ \t]+\S/.exec(String(c.source || ''))?.[1].length || 0) : 0;
const headingFolded = c => !!(headingLevel(c) && c.extra?.heading_collapsed);
function sectionEnd(cells, i) {
  const lv = headingLevel(cells[i]); let j = i + 1;
  while (j < cells.length && !(headingLevel(cells[j]) && headingLevel(cells[j]) <= lv)) j++;
  return j;
}
function hiddenCells(cells = lee.cells) {
  const out = new Set();
  for (let i = 0; i < cells.length;) {
    if (!headingFolded(cells[i])) { i++; continue; }
    const e = sectionEnd(cells, i);
    for (let j = i + 1; j < e; j++) out.add(j);
    i = e;
  }
  return out;
}
const hiddenIds = cells => new Set([...hiddenCells(cells)].map(i => cells[i].id));
function headingAncestors(i, cells = lee.cells) {
  let bound = headingLevel(cells[i]) || 7; const out = [];
  for (let j = i - 1; j >= 0; j--) { const lv = headingLevel(cells[j]); if (lv && lv < bound) { out.push(j); bound = lv; } }
  return out;
}
//: The next shown cell from `i` in direction `step`, or -1.
function visibleCell(i, step) {
  const hid = hiddenCells();
  for (let j = i + step; j >= 0 && j < lee.cells.length; j += step) if (!hid.has(j)) return j;
  return -1;
}
//: `i`, or the shown cell above it, which is the folded heading hiding it.
function shownAt(i) { const hid = hiddenCells(); while (i > 0 && hid.has(i)) i--; return i; }
//: Where a cell inserted below `i` goes: after a folded heading's section, not into it.
const belowAt = i => headingFolded(lee.cells[i]) ? sectionEnd(lee.cells, i) : i + 1;
function paintHeadings(cells = lee.cells) {
  const hid = hiddenCells(cells);
  lee.headingHidden = new Set([...hid].map(i => cells[i].id));
  $$('#editor .lee-cell').forEach(el => {
    const i = +el.dataset.i, c = cells[i]; if (!c) return;
    const folded = headingFolded(c);
    el.classList.toggle('heading-hidden', hid.has(i));
    el.classList.toggle('heading', !!headingLevel(c)); el.classList.toggle('heading-collapsed', folded);
    const caret = $('.lee-heading-caret', el);
    if (caret) { caret.textContent = folded ? '▸' : '▾'; caret.title = folded ? 'expand this section' : 'collapse this section'; }
    const badge = $('.lee-heading-badge', el); if (!badge) return;
    badge.hidden = !folded;
    if (folded) { badge.textContent = `${plural(sectionEnd(cells, i) - i - 1, 'cell')} hidden`; badge.title = 'expand this section'; }
  });
  $$('#editor .lee-toc-fold').forEach(b => { b.textContent = headingFolded(cells[+b.dataset.i]) ? '+' : '−'; });
  queueNotebookOverview();
}
/* Folds or unfolds heading cells, every one when `indices` is null. Painted here at once and
   written behind by cell id to this tab's notebook, chained per tab so its `nbEdit` and `saveTab` see
   the write land first. Not an undo step. `lee.headingFolds` keeps each fold, with the notebook version
   its write made once it lands, for `foldsSince`. */
function setHeadings(indices, collapsed) {
  const idx = (indices ?? lee.cells.map((_, i) => i)).filter(i => {
    const c = lee.cells[i]; return c && (collapsed ? headingLevel(c) && !c.extra?.heading_collapsed : c.extra?.heading_collapsed);
  });
  if (!idx.length) return;
  for (const i of idx) {
    const c = lee.cells[i]; c.extra = {...c.extra};
    if (collapsed) c.extra.heading_collapsed = true; else delete c.extra.heading_collapsed;
  }
  paintHeadings();
  const key = lee.tabKey, ids = idx.map(i => lee.cells[i].id), fold = {collapsed};
  const folds = lee.headingFolds.get(key) || lee.headingFolds.set(key, new Map()).get(key);
  for (const id of ids) folds.set(id, fold);
  lee.headingSync.set(key, headingSynced(key).then(() => post('/nb/edit', {op: 'heading', collapsed, ids, path: key}))
    .then(r => { fold.version = r.version; })
    .catch(e => { for (const id of ids) if (folds.get(id) === fold) folds.delete(id); status(String(e.message || e), 'err'); }));
  markDirty();
  if (collapsed && hiddenCells().has(lee.sel)) focusCell(shownAt(lee.sel));
}
//: Puts back on `cells`, tab `key`'s notebook at `version`, each fold it cannot hold yet; forgets the folds it holds.
function foldsSince(key, cells, version) {
  const folds = lee.headingFolds.get(key); if (!folds) return cells;
  for (const c of cells) {
    const f = folds.get(c.id); if (!f) continue;
    if (f.version && f.version <= version) { folds.delete(c.id); continue; }
    c.extra = {...c.extra};
    if (f.collapsed && headingLevel(c)) c.extra.heading_collapsed = true; else delete c.extra.heading_collapsed;
  }
  return cells;
}
//: A heading cell folds itself; any other cell folds the section it sits in.
function toggleHeading(i) {
  const h = headingLevel(lee.cells[i]) ? i : headingAncestors(i)[0];
  if (h == null) return status('this cell is under no heading', 'err');
  setHeadings([h], !headingFolded(lee.cells[h]));
}
function unfoldTo(i) {
  if (hiddenCells().has(i)) setHeadings(headingAncestors(i).filter(j => headingFolded(lee.cells[j])), false);
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
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} copied. Open another notebook and paste.`, 'ok');
}
async function cutCell(i) {
  const indices = selectedCellIndices(i), cells = indices.map(cellClipboardPayload).filter(Boolean);
  if (!cells.length) return status('select notebook cells to cut', 'err');
  lee.cellClipboard = {cells, cell: cells[0], from: lee.path || lee.tabKey || 'scratch'};
  if (!await nbEdit({op: 'delete_many', i: indices[0], indices})) return;
  focusCell(shownAt(Math.min(indices[0], lee.cells.length - 1)));
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} cut`, 'ok');
}
async function pasteCell(i) {
  if (lee.kind !== 'notebook') return status('cells can only be pasted into a notebook', 'err');
  const cells = lee.cellClipboard?.cells || (lee.cellClipboard?.cell ? [lee.cellClipboard.cell] : []);
  if (!cells.length) return status('copy or cut cells first', 'err');
  const at = Math.max(0, Math.min(i, lee.cells.length));
  if (!await nbEdit({op: 'paste_many', i: at, cells})) return;
  focusCell(at); lee.cellSelection = new Set(cells.map((_, n) => at + n)); paintSel();
  status(`${cells.length} cell${cells.length === 1 ? '' : 's'} pasted from ${compactPath(lee.cellClipboard.from)}`, 'ok');
}

async function moveCellsTo(indices, to) {
  indices = [...new Set(indices)].sort((a,b) => a-b);
  const r = await nbEdit({op: 'move_many', i: indices[0], indices, target: to}); if (!r) return;
  const at = r.index ?? to; focusCell(at); lee.cellSelection = new Set(indices.map((_, n) => at + n));
  paintSel(); status(`${indices.length} cells moved`, 'ok');
}

async function moveCellTo(from, to) {
  const last = lee.cells.length - 1;
  to = Math.max(0, Math.min(to, last));
  if (from === to || from < 0 || from > last) return focusCell(from);
  // Dragged, a folded heading takes its section along. Stepped, the server moves it a block at a time.
  const end = headingFolded(lee.cells[from]) ? sectionEnd(lee.cells, from) : from + 1;
  if (end > from + 1 && Math.abs(to - from) > 1) {
    if (to > from && to < end) return focusCell(from);
    return moveCellsTo(Array.from({length: end - from}, (_, n) => from + n), to > from ? to + 1 : to);
  }
  const r = await nbEdit({op: 'move', i: from, d: to - from}); if (!r) return;
  const at = r.index ?? to; focusCell(at);
  status(at === from ? 'nothing to move past' : `cell moved to ${at + 1}`, at === from ? 'info' : 'ok');
}

function mountCell(c, i) {
  if (lee.editors.has(c.id)) return;
  const key = `${lee.tabKey}:${c.id}`;
  // Only a docChanged transaction marks a buffer authoritative. A stale empty cache must never
  // replace the non-empty source `/tab/state` returned after running a cell.
  const source = lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source;
  c.source = source;
  const v = createEditor($('#cm-' + c.id), {
    doc: source, lang: c.cell_type === 'code' ? nbLang() : c.cell_type === 'markdown' ? 'markdown' : '',
    placeholder: c.cell_type === 'prompt' ? `ask the inline model · ${displayChord('mod+enter')} answers here`
      : c.cell_type === 'markdown' && c.extra?.lesson?.role === 'prediction' ? 'Your guess: what will the code below print?' : '',
    completeUrl: c.cell_type === 'code' ? '/complete' : null,
    lintPath: lee.path || 'scratch.ipynb',
    onDefinition: c.cell_type === 'code' ? name => findDefinition(name) : null,
    breakpoints: lee.breakpoints.get(c.id) || [],
    // Line numbers relative to this cell. A cell mounted after the marks arrived would otherwise
    // stay unmarked until the next save.
    changedLines: (lee.notebookGit?.lines || {})[c.id] || [],
    onBreakpoint: c.cell_type === 'code' ? lines => rememberBreakpoints(c.id, lines) : null,
    settings: {overviewMode:'off'}, tableKeys: true,
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
    onChange: (txt) => {
      const at = lee.cells.findIndex(cell => cell.id === c.id); if (at < 0) return;
      const level = headingLevel(lee.cells[at]);
      lee.cells[at].source = txt;
      rememberBuffer(key, {path: lee.path, title: lee.tabKey, kind: 'notebook', i: at, id: c.id, text: txt});
      if (cellState(lee.cells[at]) !== 'idle') setCellState(lee.cells[at], 'stale', 'code changed since the last run');
      if (lee.cells[at].extra?.lesson) renderLessonReveal(lee.cells[at]);
      if (isExercise(lee.cells[at])) { lee.cells[at].graded_current = false; renderExercise(lee.cells[at]); }
      if (headingLevel(lee.cells[at]) !== level) paintHeadings();
      markDirty();
    },
  });
  lee.editors.set(c.id, v);
  $('#cm-' + c.id).addEventListener('focusin', () => {
    const at = lee.cells.findIndex(cell => cell.id === c.id);
    if (at >= 0) { lee.activeEditor='primary'; lee.sel = at; setScope('editor'); paintSel(); }
  });
  renderOutputs(c);
  if (c.extra?.lesson) renderLessonReveal(c);
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

/* A markdown cell is read rendered and edited on demand. Its editor stays mounted and hidden, so the
   buffer, undo and save are the ones every other cell has. `data-md-edit` marks the editing ones. */
const mdEditing = new Set();
const mdSource = c => { const v = lee.editors.get(c.id); return v ? LeeCM.getDoc(v) : String(c.source || ''); };
const nbBase = () => (lee.path || '').slice(0, (lee.path || '').lastIndexOf('/'));
const mdAttached = c => el => $$('img[src^="attachment:"]', el).forEach(img => {
  const a = c.attachments?.[img.getAttribute('src').slice(11)], t = a && Object.keys(a)[0];
  if (t) img.src = `data:${t};base64,${[].concat(a[t]).join('')}`;
});
//: What a notebook markdown surface runs after each render; `c` is null on a slide that keeps no cache.
const mdPaint = (c, cached = true) => (el, src) => { if (c) mdAttached(c)(el); const k = cached && c; rupakaFences(el, k ? `md:${c.id}` : null, k ? src : null, k ? lessonRestore(c.id, src) : null); };
const mdCellHost = c => `<div class="lee-md-cell lee-md" id="mdr-${esc(c.id)}" title="double-click to edit · ${esc(displayChord('enter'))}"></div>`;
const mdCellOf = i => $(`.lee-cell[data-i="${i}"]`);
function paintMarkdownCell(el, c, now = false) {
  const host = $('.lee-md-cell', el); if (!host) return;
  const src = mdSource(c);
  el.toggleAttribute('data-md-edit', mdEditing.has(c.id));
  host.classList.toggle('empty', !src.trim());
  host.dataset.mdBase = nbBase();
  if (now) { host.dataset.markdown = src; flushMarkdown(host, true, mdPaint(c)); } else renderMarkdown(host, src, true, mdPaint(c));
}
function editMarkdownCell(i) {
  const c = lee.cells[i], el = mdCellOf(i); if (c?.cell_type !== 'markdown' || !el) return;
  mdEditing.add(c.id); el.setAttribute('data-md-edit', '');
  const v = ensureCellMounted(i);
  requestAnimationFrame(() => { v.dispatch({selection: {anchor: v.state.doc.length}}); LeeCM.focus(v); v.requestMeasure(); });
}
function showRenderedMarkdown(c, refocus = false) {
  if (c?.cell_type !== 'markdown') return;
  const el = $(`.lee-cell[data-id="${c.id}"]`); if (!el) return;
  const hadFocus = el.contains(document.activeElement);
  mdEditing.delete(c.id); paintMarkdownCell(el, c, true);
  if (hadFocus || refocus) el.focus({preventScroll: true});
}
function leaveOtherMarkdownEdits(keep) {
  const stay = lee.cells[keep]?.id;
  for (const id of [...mdEditing]) if (id !== stay) showRenderedMarkdown(lee.cells.find(c => c.id === id));
}
// A cell with nothing in it starts in the editor, which is how a new markdown cell arrives.
function focusRenderedMarkdown(i) {
  const c = lee.cells[i]; if (c?.cell_type !== 'markdown') return false;
  if (!mdSource(c).trim() && !mdEditing.has(c.id)) editMarkdownCell(i);
  if (mdEditing.has(c.id)) return false;
  mdCellOf(i)?.focus({preventScroll: true}); return true;
}
const MD_KEYS = {
  cell_edit: e => { const el = e.target.closest?.('.lee-cell.markdown');
    return !!el && !el.hasAttribute('data-md-edit') && !isTextEntry(keyTarget(e)) && !keyTarget(e).closest?.('button, a, summary'); },
  // A markdown cell renders; a code cell's editor lets go, so the cell is in command mode.
  cell_render: e => { const el = e.target.closest?.('.lee-cell'), v = el && lee.editors.get(el.dataset.id);
    return !!el && (el.classList.contains('markdown') ? el.hasAttribute('data-md-edit') : !$('.lee-inline-popover')) &&
      inCellEditor(e) && !el.querySelector('.cm-panel') && !(v && LeeCM.holdsEscape(v)); },
};

function renderOutputs(c) {
  const box = $('#out-' + c.id); if (!box) return;
  $$('[data-markdown]', box).forEach(el => {
    if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  });
  widgetDetach(c);
  const rkPass = rupakaPass(`out:${c.id}`);
  box.innerHTML = '';
  // A prompt cell's "output" is the answer, stored in the cell rather than in an nbformat output,
  // so it renders from its own fields.
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
      renderMarkdown(reply, (c.calls || []).length ? stripWorkLog(c.reply) : c.reply);
      const usage = usageMeta(c.usage, '', c.usage?.model); if (usage) box.appendChild(usage);
    }
    // pictures and video the turn generated do arrive as nbformat outputs, and draw as any other
    (c.outputs || []).forEach((o, i) => box.appendChild(outputEl(o, c, i)));
    rupakaSweep(rkPass);
    return widgetSweep(c);
  }
  (c.outputs || []).forEach((o, i) => box.appendChild(outputEl(o, c, i)));
  rupakaSweep(rkPass);
  widgetSweep(c);
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
  if (!item || lee.present) return;
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
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !lee.present) closeInlinePopover(); }, true);

function outputTone(o) {
  if (o.output_type === 'error') return 'error';
  if (o.output_type === 'stream' && o.name === 'stderr')
    return /\b(?:warning|warns?|deprecated|deprecation)\b/i.test(String(o.text || '')) ? 'warning' : 'log';
  if (o.output_type === 'execute_result' || o.output_type === 'display_data') return 'result';
  return 'output';
}
const PLOTLY_JS = 'https://cdn.plot.ly/plotly-4.1.1.min.js';
const PLOTLY_MIME = 'application/vnd.plotly.v1+json';
function sandboxFrame(d, srcdoc, height) {
  const f = document.createElement('iframe'); f.className = 'lee-out-frame';
  f.setAttribute('sandbox', 'allow-scripts'); f.srcdoc = srcdoc;
  f.style.cssText = `width:100%;height:${height}px;border:0;resize:vertical;overflow:auto;display:block`;
  d.classList.add('lee-out-media'); d.appendChild(f); return d;
}
function plotlyFrame(d, fig) {
  const json = JSON.stringify({data: fig.data || [], layout: fig.layout || {}, config: fig.config || {}}).replace(/</g, '\\u003c');
  const h = +(fig.layout && fig.layout.height) || 450;
  return sandboxFrame(d, `<!doctype html><meta charset="utf-8"><body style="margin:0"><div id="p" style="width:100%;height:100vh"></div>` +
    `<script src="${PLOTLY_JS}" onerror="document.getElementById('p').innerHTML=` +
    `'<p style=&quot;font:13px sans-serif;color:#888;padding:1em&quot;>plotly.js could not load, so this chart cannot be drawn offline</p>'"><\/script>` +
    `<script>const f = ${json}; if (window.Plotly) Plotly.newPlot('p', f.data, Object.assign({}, f.layout, {autosize: true, width: undefined, height: undefined}), Object.assign({responsive: true}, f.config));<\/script>`, h);
}
//: A rupaka output is drawn here, so the `text/html` fallback `rupaka.show` sends beside it never reaches a frame.
function rupakaEl(d, raw, pass, i) {
  const text = typeof raw === 'string' ? raw : JSON.stringify(raw);
  const fail = err => d.append(rupakaErr(err), Object.assign(document.createElement('pre'), {textContent: text}));
  let spec; try { spec = JSON.parse(text); } catch (err) { fail(err); return d; }
  d.classList.add('lee-out-media');
  const e = rupakaDraw(spec, pass && `${pass.owner}:${i}:${text.length}:${text}`, pass);
  if (e.err) fail(e.err); else d.append(e.host);
  if (!e.ok && !e.err) e.done.then(() => { if (e.err) { e.host.remove(); fail(e.err); } rupakaRendered(d); });
  return d;
}
//: Rich output markup that runs no script and sends no request to Leela: allowlisted HTML, SVG and MathML, no handlers, links only to other sites, images also as `data:`, and no Leela class names.
const RICH_TAGS = new Set(('a abbr address article aside b bdi bdo blockquote br caption center cite code col colgroup data dd del details dfn div dl dt em figcaption figure font footer h1 h2 h3 h4 h5 h6 header hr i img input ins kbd label legend li main mark meter nav ol p picture pre progress q rp rt ruby s samp section small source span strike strong style sub summary sup table tbody td tfoot th thead time tr tt u ul var wbr video audio ' +
  'svg g defs symbol use path rect circle ellipse line polyline polygon text tspan textpath title desc metadata clippath mask pattern marker image lineargradient radialgradient stop filter foreignobject switch ' +
  'feblend fecolormatrix fecomponenttransfer fecomposite feconvolvematrix fediffuselighting fedisplacementmap fedistantlight fedropshadow feflood fefunca fefuncb fefuncg fefuncr fegaussianblur femerge femergenode femorphology feoffset fepointlight fespecularlighting fespotlight fetile feturbulence ' +
  'math semantics annotation annotation-xml mrow mi mo mn ms mtext mspace msup msub msubsup munder mover munderover mfrac msqrt mroot mtable mtr mtd mlabeledtr mstyle mpadded mphantom menclose merror mfenced mmultiscripts mprescripts none').split(' '));
const RICH_ATTR_GONE = new Set('srcdoc srcset is formaction formtarget form name action attributename popover popovertarget popovertargetaction commandfor command interestfor autofocus accesskey ping background codebase longdesc lowsrc dynsrc'.split(' '));
const RICH_OURS = /^(lee-|cm-|xterm|rk|stage-)/;
const RICH_GONE = new Set('script iframe frame frameset object embed applet noscript noembed noframes template textarea select xmp button form base meta link set animate animatemotion animatetransform discard portal dialog slot'.split(' '));
const RICH_MEDIA = /^data:(image\/(png|jpe?g|gif|webp|avif|svg\+xml)|video\/(mp4|webm|ogg)|audio\/(mpeg|mp4|wav|ogg|webm));base64,/i;
//: Whether URL `v` on attribute `n` of `tag` may stay: `#…` inside the output, `data:` media where it is drawn, a link or an image on a site that is not this computer.
function richUrl(tag, n, v) {
  const u = v.replace(/[\x00-\x20\x7f-\x9f]+/g, '');
  if (u.startsWith('#')) return true;
  const media = n === 'src' && ['img', 'video', 'audio', 'source'].includes(tag) || n === 'href' && tag === 'image';
  if (/^data:/i.test(u)) return media && RICH_MEDIA.test(u);
  if (tag === 'a' && n === 'href') return /^mailto:/i.test(u) || richSite(u);
  return (tag === 'img' && n === 'src' || tag === 'image' && n === 'href') && richSite(u);
}
function richSite(u) {
  let url; try { url = new URL(u, location.href); } catch (_) { return false; }
  const h = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return /^https?:$/.test(url.protocol) && url.origin !== location.origin && !/^(localhost|127\.\d+\.\d+\.\d+|::1|0\.0\.0\.0)$|\.localhost$/.test(h);
}
//: CSS with no request in it: no `@import`, and no `url()` or `image-set()` but an in-output `#` reference or a `data:` image.
function richCss(css) {
  css = String(css).replace(/\\([0-9a-f]{1,6})\s?/gi, (_, h) => String.fromCodePoint(Math.min(parseInt(h, 16), 0x10ffff) || 0xfffd)).replace(/\\(.)/g, '$1');
  return css.replace(/@import[^;]*;?/gi, '').replace(/(-webkit-)?image-set\s*\(/gi, 'none(')
    .replace(/url\s*\(\s*(['"]?)([^)]*)\)/gi, (m, q, v) => /^#|^data:image\/(png|jpe?g|gif|webp|avif|svg\+xml);base64,/i.test(v.replace(/['"\s]/g, '')) ? m : 'none');
}
//: Clean the children of `root` in place.
function richWalk(root) {
  for (const el of [...root.children]) {
    const tag = el.localName.toLowerCase();
    if (RICH_GONE.has(tag)) { el.remove(); continue; }
    if (!RICH_TAGS.has(tag)) { richWalk(el); el.replaceWith(...el.childNodes); continue; }
    if (tag === 'input' && (el.getAttribute('type') || '').toLowerCase() !== 'checkbox') { el.remove(); continue; }
    for (const a of [...el.attributes]) {
      const n = a.localName.toLowerCase();
      if (n.startsWith('on') || RICH_ATTR_GONE.has(n) || (['href', 'src', 'poster', 'data', 'cite'].includes(n) && !richUrl(tag, n, a.value))) el.removeAttributeNode(a);
      else if (n === 'style') a.value = richCss(a.value);
      else if (n === 'class') a.value = a.value.split(/\s+/).filter(c => c && !RICH_OURS.test(c)).join(' ');
      else if (/url\s*\(/i.test(a.value) && !/^\s*url\s*\(\s*#[^)]*\)\s*$/i.test(a.value)) el.removeAttributeNode(a);
    }
    if (tag === 'style') el.textContent = richCss(el.textContent);
    if (tag === 'input') el.setAttribute('disabled', '');
    if (tag === 'a') { el.setAttribute('target', '_blank'); el.setAttribute('rel', 'noopener noreferrer'); }
    richWalk(el);
  }
}
//: `html` as a clean fragment. Parsed in a `<template>`, so nothing in it loads or runs before the walk.
//: A pandas table in the theme's colours. An adopted sheet comes before the output's own `<style>`, which wins where it says something; `border="1"` loses to any rule.
const RICH_TABLE_CSS = new CSSStyleSheet(); RICH_TABLE_CSS.replaceSync('table{border-collapse:collapse;border:0;margin:2px 0;font:12px/1.4 var(--lee-mono);color:var(--lee-output)}' +
  'th,td{border:0;border-bottom:1px solid var(--lee-border);padding:3px 10px;text-align:right}' +
  'thead th{border-bottom-color:var(--lee-fg4);color:var(--lee-fg2);font-weight:600}tbody th{color:var(--lee-fg2);font-weight:600}' +
  'tbody tr:hover{background:var(--lee-active-line)}');
function richHtml(html) {
  const t = document.createElement('template'); t.innerHTML = html;
  richWalk(t.content);
  return document.importNode(t.content, true);
}
//: `html` as clean markup for code that sets `innerHTML` on a `div`: parsed as that `div` parses it, in a document with no window, until it reads back the same; empty when it never does.
function richString(html) {
  const d = (richString.doc ||= document.implementation.createHTMLDocument('')).createElement('div');
  let s = String(html ?? '');
  for (let i = 0; i < 4; i++) { d.innerHTML = s; richWalk(d); if (d.innerHTML === s) return s; s = d.innerHTML; }
  return '';
}
//: A mime value as text: a saved notebook may keep it as a list of lines.
const mimeText = v => Array.isArray(v) ? v.join('') : typeof v === 'string' ? v : null;
function outputEl(o, c = null, i = 0) {
  const d = document.createElement('div');
  const tone = outputTone(o);
  d.className = `lee-out ${tone}`;
  if (o.output_type === 'stream') { outputText(d, o.text); return d; }
  if (o.output_type === 'error') {
    outputText(d, stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`);
    if (o.ename === 'ShellStopped') {
      const b = document.createElement('button');
      b.className = 'lee-btn'; b.dataset.restartKernel = ''; b.textContent = 'Restart kernel'; b.onclick = () => restartKernel();
      d.appendChild(b);
    }
    return d;
  }
  const data = o.data || {};
  if (data[WIDGET_MIME] != null) return widgetEl(o, c, i);
  if (data[RUPAKA_MIME] != null) return rupakaEl(d, data[RUPAKA_MIME], c?.id && rupaka.passes.get(`out:${c.id}`), i);
  if (data[PLOTLY_MIME] != null) return plotlyFrame(d, data[PLOTLY_MIME]);
  if (data['image/png']) {
    const i = document.createElement('img'), m = o.metadata?.['image/png'] || {};
    i.src = 'data:image/png;base64,' + mimeText(data['image/png']);
    // A retina figure's width and height are half its pixels.
    if (m.width) i.width = m.width;
    if (m.height) i.height = m.height;
    d.classList.add('lee-out-media'); d.appendChild(i); return d;
  }
  // Presence, not truthiness. Clearing a rich display is publishing an empty one of the same type:
  // fastprogress ends a progress bar with `HTML('')`, and testing the string sent that output down
  // to its `text/plain`, which for any rich object is the placeholder `<... object>` repr.
  const html = mimeText(data['text/html']), svgText = mimeText(data['image/svg+xml']), rich = html ?? svgText;
  if (html != null && /<script[\s/>]/i.test(html)) return sandboxFrame(d, html, 450);
  const svg = html == null && svgText != null;
  if (svg) d.classList.add('lee-out-media');
  if (rich != null) {
    // Rich reprs get their own shadow root: pandas ships a <style> block with every DataFrame and
    // `scoped` has been dead for years, so an output could restyle the IDE around it. Very large
    // HTML stays unparsed until requested, because parsing a multi-megabyte table on the main
    // thread triggers Chrome's hang dialog.
    // The shadow host sits inside `d`, which contains its paint: a `:host` or `position: fixed` rule cannot cover the IDE.
    const show = () => {
      d.textContent = ''; d.style.contain = 'paint';
      const r = d.appendChild(Object.assign(document.createElement('div'), {className: 'lee-out-rich'})).attachShadow({mode: 'open'});
      if (svg) r.append(Object.assign(document.createElement('style'), {textContent: 'svg{display:block;max-width:100%;height:auto}'}));
      else r.adoptedStyleSheets = [RICH_TABLE_CSS];
      r.append(richHtml(rich));
    };
    if (rich.length > MAX_OUTPUT_CHARS) {
      const folded = document.createElement('button'); folded.className = 'lee-output-fold';
      folded.textContent = `render large rich output (${Math.round(rich.length / 1024).toLocaleString()}kb)`;
      folded.onclick = show; d.appendChild(folded);
    } else show();
    return d;
  }
  // After the rich types, as Jupyter ranks them: a FastHTML object sends its markup as `text/html` and
  // again as a fenced `text/markdown` block, and the fence is source, not the thing to draw.
  if (data['text/markdown'] != null) {
    d.classList.add('lee-md-output'); d.dataset.mdBase = nbBase(); renderMarkdown(d, data['text/markdown'], false, el => rupakaFences(el, c?.id ? `outmd:${c.id}:${i}` : null)); return d;
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
  paintSel(); leaveOtherMarkdownEdits(lee.sel);
}
/* Bring a cell into view with room around it.

   `scrollIntoView({block: 'nearest'})` moves the minimum distance, so a cell arriving from below
   parks flush against the bottom edge with nothing under it, which is the whole of what a reader
   wants to see after running it. Moving the minimum is still right once the cell is comfortably
   on screen, or stepping to a neighbour would jump the page, so the margin is what decides. */
function revealCell(cell) {
  const host = $('#editor'); if (!host || !cell) return;
  const box = host.getBoundingClientRect(), r = cell.getBoundingClientRect();
  const margin = Math.min(120, Math.max(24, box.height * .18));
  const above = r.top - box.top - margin, below = r.bottom - box.bottom + margin;
  // A cell taller than the room left over can only be shown from its top.
  if (r.height > box.height - margin * 2 || above < 0) host.scrollTop += above;
  else if (below > 0) host.scrollTop += below;
}
function focusCell(i) {
  unfoldTo(Math.max(0, Math.min(i, lee.cells.length - 1)));
  selectCell(i);
  const c = lee.cells[lee.sel]; if (!c) return;
  // Mounted first: an unmounted cell is a shell whose height is a guess, and the reveal measures it.
  const v = ensureCellMounted(lee.sel), rendered = focusRenderedMarkdown(lee.sel);
  const reveal = () => revealCell($(`.lee-cell[data-i="${lee.sel}"]`));
  reveal();
  // CodeMirror focuses its own scroller and reveals the caret minimally, which spends the margin
  // again, so the reveal is repeated after it and after the layout mounting just caused.
  requestAnimationFrame(() => { if (v && !rendered) LeeCM.focus(v); reveal(); });
}
function focusCellPage(direction) {
  if (!lee.cells.length) return;
  const host = $('#editor'), current = $(`.lee-cell[data-i="${lee.sel}"]`);
  if (!host || !current) return focusCell(lee.sel + direction);
  const target = current.getBoundingClientRect().top + direction * Math.max(180, host.clientHeight * .78);
  const cells = $$('.lee-cell', host);
  const candidates = cells.filter(el => !el.classList.contains('heading-hidden') && (direction < 0 ? +el.dataset.i < lee.sel : +el.dataset.i > lee.sel));
  if (!candidates.length) return focusCell(direction < 0 ? 0 : shownAt(lee.cells.length - 1));
  const next = candidates.reduce((best, el) =>
    Math.abs(el.getBoundingClientRect().top - target) < Math.abs(best.getBoundingClientRect().top - target) ? el : best);
  focusCell(+next.dataset.i);
}
//: The autosave mode in effect: `off` while a presentation is open, which writes no file; the setting does not change.
const autoSaveMode = () => lee.present ? 'off' : lee.filePrefs.autoSave || 'afterDelay';
function autoSaveEnabled() { return autoSaveMode() !== 'off'; }
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
    pending: lee.path ? 'Changes queued for autosave' : 'Not saved. Choose a file name to save it',
    saving: 'Saving changes…', saved: 'Saved on disk', error: 'Autosave failed',
  };
  dot.className = `lee-save-state ${state}`;
  dot.title = detail || labels[state] || state;
  dot.setAttribute('aria-label', dot.title);
  tab.dataset.saveState = state;
}
function scheduleAutoSave() {
  clearTimeout(lee.autoSaveTimer);
  if (autoSaveMode() !== 'afterDelay' || !lee.path || lee.heldSaveConflicts.has(lee.path)) return;
  const version = lee.editVersion;
  lee.autoSaveTimer = setTimeout(async () => {
    if (autoSaveMode() !== 'afterDelay') return;
    if (lee.saving || version !== lee.editVersion) return scheduleAutoSave();
    lee.saving = true;
    setTabSaveState($('.lee-tab.active'), 'saving');
    try { await saveTab(true, version); }
    finally { lee.saving = false; if (version !== lee.editVersion) scheduleAutoSave(); }
  }, Math.max(100, Number(lee.filePrefs.autoSaveDelay) || 900));
}
document.addEventListener('focusout',e=>{if(autoSaveMode()==='onFocusChange'&&!lee.heldSaveConflicts.has(lee.path)&&e.target.closest?.('.cm-editor')&&$('.lee-tab.active.dirty'))saveTab(true);});
window.addEventListener('blur',()=>{if(autoSaveMode()==='onWindowChange'&&!lee.heldSaveConflicts.has(lee.path)&&$('.lee-tab.active.dirty'))saveTab(true);});
function markDirty() {
  lee.editVersion += 1; lee.tabEdits.set(lee.tabKey, (lee.tabEdits.get(lee.tabKey) || 0) + 1);
  const t = $('.lee-tab.active');
  if (t) { t.classList.add('dirty'); setTabSaveState(t, 'pending'); }
  scheduleAutoSave();
}

/* A notebook's language is its kernelspec, so choosing one here writes the file and drops the
   runtime the old language was using. Unbound by default: a button and a palette entry, like every
   other action whose chord is not worth spending. */
async function pickNotebookLanguage() {
  if (lee.kind !== 'notebook') return status('open a notebook first', 'err');
  const o = await post('/nb/language', {path: lee.tabKey || ''});
  const rows = (o.langs || []).map(l =>
    `<div class="lee-mrow${l.current ? ' sel' : ''}" data-lang="${esc(l.id)}">` +
    `${l.current ? '● ' : '○ '}${esc(l.label)}<span class="sub">${esc(l.how)}</span></div>`).join('');
  const m = modal(
    `<div class="lee-mhead">notebook language<span class="sub">${esc(o.path || '')}</span></div>` +
    `<div class="lee-dim">this is written into the notebook, and closes the runtime it is using</div>` +
    `<div class="lee-modallist">${rows}</div>`);
  m.querySelectorAll('[data-lang]').forEach(el => el.onclick = async () => {
    m.remove();
    try {
      const d = await post('/nb/language', {path: lee.tabKey || '', lang: el.dataset.lang});
      status(`this notebook is ${d.lang} now`, 'ok');
      await mountTab(lee.tabKey);
    } catch (e) { status(String(e.message || e), 'err'); }
  });
}
function learnDiff(guess, actual) {
  const lines = text => text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)
    .map(line => line.split(/[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/).filter(Boolean).join(' ')).filter(Boolean);
  const g = lines(guess), a = lines(actual);
  return Array.from({length: Math.max(g.length, a.length)}, (_, i) => {
    const x = g[i] ?? null, y = a[i] ?? null;
    return {guess: x, actual: y, kind: x === null ? 'missing' : y === null ? 'extra' : x === y ? 'match' : 'mismatch'};
  });
}

function lessonActual(c) {
  const text = value => Array.isArray(value) ? value.join('') : String(value ?? '');
  const outputs = c.outputs || [], error = outputs.find(o => o.output_type === 'error');
  if (error) {
    const last = stripAnsi(text((error.traceback || []).join('\n'))).trim().split('\n').pop();
    return 'It raised ' + (last || `${error.ename}: ${error.evalue}`);
  }
  return stripAnsi(outputs.map(o => o.output_type === 'stream' ? text(o.text) : text(o.data?.['text/plain'])).filter(Boolean).join('\n'));
}
function lessonRevealText(c) {
  const lesson = c.extra.lesson, rows = learnDiff(String(lesson.prediction || ''), lessonActual(c));
  const different = rows.filter(r => r.kind !== 'match');
  if (!different.length) return 'Right. You saw that before running it.';
  const lines = rows.filter(r => r.kind === 'match').map(r => r.actual);
  for (const r of different) lines.push(r.kind === 'missing' ? `It printed ${r.actual}, which you did not expect.`
    : r.kind === 'extra' ? `You expected ${r.guess}, which did not appear.` : `You wrote ${r.guess}. It printed ${r.actual}.`);
  if (lesson.confidence >= 60) lines.push('You were sure, and it went another way. That is the part worth a look.');
  return lines.join('\n');
}
//: The line a failed lesson write shows: the server's own sentence when it sent one, else a line that says what to do.
const lessonSaid = (err, b = err?.body) => (b && typeof b === 'object' && (b.error || b.message)) || (typeof b === 'string' && b.trim() && !b.trim().startsWith('<') && b.trim().slice(0, 300)) || 'Leela did not save this. Try again.';
function lessonRevealActions(cell, el) {
  const lesson = cell.extra.lesson, key = `${cell.id}:${cell.execution_count}`;
  const row = document.createElement('div'); row.className = 'lee-reveal-save'; el.appendChild(row);
  if (lesson.saved === key) { row.textContent = lesson.saved_message || 'Saved to your learning shelf.'; return; }
  const button = document.createElement('button'); button.type = 'button'; button.className = 'lee-btn'; button.textContent = 'Save card';
  row.appendChild(button);
  button.onmousedown = e => { e.preventDefault(); e.stopPropagation(); };
  button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true;
    const path = lee.path, tabKey = lee.tabKey;
    try {
      await lee.nbQueue;
      const stop = lee.tabKey !== tabKey ? 'Return to the lesson notebook, then save.' : $('.lee-tab.active')?.classList.contains('dirty') ? 'Save the notebook first.' : '';
      if (stop) { status(stop, 'err'); button.disabled = false; return; }
      const d = await post('/lesson/save', {path, cell_id: cell.id});
      lesson.saved = d.saved; lesson.saved_message = d.message;
      const current = lee.tabKey === tabKey && lee.cells.find(c => c.id === cell.id && c.execution_count === cell.execution_count);
      if (current) Object.assign(current.extra.lesson, {saved: d.saved, saved_message: d.message});
      row.textContent = d.message;
      refreshLessonDue();
      if (d.disk_version) { recordDiskVersion(path, d.disk_version); await rebaseDrafts(path, d.disk_version); noteSelfWrite(path); }
    } catch (e) { status(lessonSaid(e), 'err'); button.disabled = false; }
  };
}
function renderLessonReveal(c) {
  const cell = $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`); if (!cell) return;
  $('.lee-reveal', cell)?.remove();
  if (c.cell_type !== 'code' || !c.extra?.lesson || c.extra.lesson.for_count !== c.execution_count
      || c.stale || $('#state-' + c.id)?.classList.contains('stale') || c.running || !c.outputs?.length) return;
  const el = document.createElement('div'); el.className = 'lee-reveal';
  el.textContent = lessonRevealText(c);
  $('#out-' + c.id, cell).after(el);
  lessonRevealActions(c, el);
}
//: A gate locked in a notebook cell's demo goes to the server, which files it only in a lesson. The server checks a literal answer itself and files the page's `ans` and `ok` for a state-path answer. The gate reveals once the server answers ok. A failure opens the gate again with the server's message.
async function lessonPredict(e) {
  const at = e.composedPath(), host = at.find(n => n.classList?.contains('lee-rupaka')), cell = at.find(n => n.matches?.('.lee-cell[data-id]'));
  if (!cell || host?.leeSource == null) return;
  // rupaka 0.0.1 has no settle, and its gate reveals on lock-in.
  const held = typeof e.detail?.settle === 'function', settle = held ? e.detail.settle : () => {};
  if (held) e.preventDefault();
  try {
    const {demo, gate, picked, ans, ok, why} = e.detail, path = lee.path;
    const src = await srcHash(host.leeSource);
    await lee.nbQueue;
    const d = await post('/lesson/predict', {path, cell_id: cell.dataset.id, demo, gate, picked, ans, ok, why, src});
    settle(true);
    status(d.message || '', 'ok');   // an ok answer also clears the toast of a failed try
  } catch (err) {
    const said = lessonSaid(err);
    settle(false, said);
    status(said, 'err');
  }
}
//: The `restore` of a lesson cell's demo: each gate with a prediction filed for source `src` is closed with its pick, so a reload shows what it hid. Null outside a lesson; after 2s, a tab change or a failure the gates stay open.
function lessonRestore(id, src) {
  if (!lessonNotebook()) return null;
  const path = lee.path, tab = lee.tabKey;
  return async (inner, spec) => {
    try {
      const d = await Promise.race([srcHash(src).then(h => post('/lesson/predictions', {path, cell_id: id, src: h})), new Promise(ok => setTimeout(ok, 2000))]);
      if (!d?.picks || lee.tabKey !== tab) return;
      const at = `${spec.id}:`, picks = Object.fromEntries(Object.entries(d.picks).filter(([k]) => k.startsWith(at)).map(([k, v]) => [k.slice(at.length), v]));
      rupakaSettle(inner, picks);
    } catch (e) { console.warn('Leela demo restore:', e); }
  };
}
//: The demo's own words for an ask: its id, its step and the values of its state, as `rk-ask` gives them.
const askAbout = d => [d.demo && `the demo "${d.demo}"`, d.step != null && `step ${d.step}`,
  Object.keys(d.state || {}).length && 'values ' + Object.entries(d.state).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(', ')].filter(Boolean).join(', ');
//: "Ask about this" in a notebook cell's demo: in a lesson, to the screen guide; else to the agent; each with the cell as context. Only a sent ask is taken (`preventDefault`), so rupaka says "Sent to the tutor".
function lessonAsk(e) {
  const at = e.composedPath(), cell = at.find(n => n.matches?.('.lee-cell[data-id]')), d = e.detail || {};
  const c = cell && at.some(n => n.classList?.contains('lee-rupaka')) && lee.cells.find(x => x.id === cell.dataset.id);
  if (!c) return;
  const about = askAbout(d), n = lee.cells.indexOf(c) + 1;
  if (lessonNotebook() && guideCell(c)) { e.preventDefault(); return lessonGuide(c.id, '', `${d.text || GUIDE_START + 'this demo.'}${about ? ` (${about})` : ''}`); }
  if (lee.agentBusy || lee.agentSending) return status('The agent is working. Ask again when it finishes.', 'err');
  leeAct('focus_agent');
  const prompt = $('#agentprompt');
  if (!prompt) return;
  if (prompt.value.trim()) return status('Send or clear your message to the agent first.', 'err');
  e.preventDefault();
  prompt.value = `About cell ${n} of ${lee.path ? lee.path.split('/').pop() : 'this notebook'}${about ? `, ${about}` : ''}: ${d.text || 'What does this demo show?'}`;
  return sendAgent();
}
// The Node harnesses load this file with no `document`.
globalThis.document?.addEventListener('rk-predict', lessonPredict);
globalThis.document?.addEventListener('rk-ask', lessonAsk);
//: "I don't get…" on a lesson cell: one line goes to the screen guide, and its steps and sources show as plain text in the cell's output area until the board is drawn.
const GUIDE_START = "I don't get ";
const lessonNotebook = () => lee.cells.some(c => c.extra?.lesson);
const guideCell = c => c.cell_type === 'markdown' ? !['prediction', 'card'].includes(c.extra?.lesson?.role) : isExercise(c);
const guideText = d => [...(d.steps || []).map(s => s.say), ...(d.sources || []).map(s => `Source ${s.n}: ${s.label}, ${s.title}`), d.end].filter(Boolean).join('\n');
const boardLoad = {p: null};
//: abhyasa's board, loaded on the first guide: `abhyasaBoard`, or null after one warning, and the next guide tries again.
function loadBoard() {
  if (window.abhyasaBoard) return Promise.resolve(window.abhyasaBoard);
  return boardLoad.p ||= (async () => {
    const meta = n => $(`meta[name="${n}"]`)?.content;
    document.head.appendChild(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: meta('lee-board-css') || '/leeboard/board.css'}));
    await new Promise((ok, no) => {
      const s = document.createElement('script');
      s.src = meta('lee-board-src') || '/leeboard/board.js'; s.onload = ok;
      s.onerror = () => { s.remove(); no(new Error('board.js could not be loaded')); };
      document.head.appendChild(s);
    });
    return window.abhyasaBoard || Promise.reject(new Error('board.js defined no abhyasaBoard'));
  })().catch(e => { console.warn('Leela guide:', e); return null; }).finally(() => { boardLoad.p = null; });
}
//: Gives the parts of a lesson cell the ids `guide_context` names them by. The demo's inputs and readouts get theirs from abhyasa's `demoAnchors` when the guide asks.
function guideStamp(cell, c) {
  const tag = (e, id) => { if (e) e.dataset.guideId = id; }, md = $('.lee-md-cell', cell);
  if (!md) return;
  tag(md, c.extra?.exercise?.role === 'task' ? 'check' : 'passage');
  $$('img', md).forEach((img, n) => tag(img, `img${n + 1}`));
  tag($('.lee-rupaka', md), 'demo');
}
//: The code and the output in `cell`, as `code1` to `code4` in page order: the values that the board's panel copies. A markdown cell gives its code blocks; a code cell its code and its text outputs.
function guideCode(cell, c) {
  $$('[data-guide-id^="code"]', cell).forEach(e => delete e.dataset.guideId);
  $$(c?.cell_type === 'markdown' ? '.lee-md-cell pre, .lee-md-cell .cm-content' : '.cm-content, [id^="out-"] pre', cell).filter(e => e.textContent.trim()).slice(0, 4).forEach((e, n) => { e.dataset.guideId = `code${n + 1}`; });
}
//: The rupaka demo in `cell` as `{anchors, demo}` from the board's `demoAnchors`, which also stamps its ids; null with no demo or an older board.
const guideDemoAnchors = (cell, b) => { const inner = [...($('.lee-rupaka', cell)?.shadowRoot?.children || [])].find(n => n.rupaka); return inner && b?.demoAnchors ? b.demoAnchors(inner) : null; };
globalThis.document?.addEventListener('lee-markdown-rendered', e => {
  const cell = e.target.closest?.('.lee-cell[data-id]'), c = cell && lee.cells.find(x => x.id === cell.dataset.id);
  if (c && lessonNotebook() && guideCell(c)) guideStamp(cell, c);
});
//: The formulas, figures and code Leela drew in `cell`, in page order, as the one list the server takes them from: `{id, text, parts}` for each `f<n>`, `{id, text}` for each `img<n>` and `code<n>`. A figure on its own line has an empty `alt` and its text in the `figcaption`.
const guideAnchors = cell => $$('[data-guide-id]', cell).flatMap(e => { const id = e.dataset.guideId;
  return /^f\d+$/.test(id) ? [{id, text: (e.dataset.tex || '').trim(), parts: JSON.parse(e.dataset.parts || '[]').map(p => p[0])}] : /^img\d+$/.test(id) ? [{id, text: (e.alt || e.closest('figure')?.querySelector('figcaption')?.textContent || '').trim()}]
    : /^code[1-4]$/.test(id) ? [{id, text: e.textContent.trim().slice(0, 300)}] : []; });
const guideFind = (cell, id) => { const q = `[data-guide-id="${CSS.escape(id)}"]`; return $(q, cell) || $$('.lee-rupaka', cell).map(h => h.shadowRoot && $(q, h.shadowRoot)).find(Boolean) || null; };
const guideDemo = (cell, open) => set => { const inner = open && [...(guideFind(cell, 'demo')?.shadowRoot?.children || [])].find(n => n.rupaka); if (inner) Rupaka.set(inner, set); };
//: Draws the board in the cell it was asked from; false when the board is missing or fails, so the plain text stays.
//: Leela speaks with the browser's voice, on this computer: the board's strip names it after the Voice button, with `local` so that it is never called hosted.
const GUIDE_VOICE = {model: 'Browser voice', local: true};
//: "Show me …" to the guide: the hand-off to the demo of this idea in abhyasa, in place of a board.
function guideShowCard(sh, cell, id) {
  $('.lee-guide-out', cell)?.remove();
  const el = document.createElement('div'); el.className = 'lee-guide-out lee-guide-show'; el.textContent = `Show: ${sh.title}. `;
  if (sh.href) el.append(Object.assign(document.createElement('a'), {href: sh.href, target: '_blank', rel: 'noopener', textContent: 'Open in abhyasa ↗'}));
  else el.append('Start abhyasa to see the demo of this idea.');
  $('#out-' + id, cell).after(el);
}
//: Puts the board's side panel in the notebook area: under its tab bar, left of the side panes, and at most 45 % of its width (lee-ide.css).
function guideRoom() {
  const r = $('#editorstage')?.getBoundingClientRect();
  if (!r?.width) return;
  const s = document.documentElement.style;
  s.setProperty('--lee-panel-top', `${Math.round(r.top + 8)}px`);
  s.setProperty('--lee-panel-right', `${Math.round(innerWidth - r.right + 12)}px`);
  s.setProperty('--panel-w', `${Math.round(Math.min(440, r.width * .45))}px`);
}
globalThis.addEventListener?.('resize', () => { if (document.getElementById('board-panel')) guideRoom(); });
async function guidePlay(d, cell, board) {
  if (!board) return false;
  guideRoom();
  const assets = $('meta[name="lee-board-assets"]')?.content || '/leeboard/libs/';
  try { await board.play(d, {host: {resolve: i => guideFind(cell, i), demo: guideDemo(cell, d.demo_open), assets}, voiceAt: GUIDE_VOICE}); return true; }
  catch (e) { console.warn('Leela guide:', e); return false; }
}
//: The board of the stream (`live`, the promise of its first play) gets the whole board: `finish` when its steps begin that board, else the whole board plays; a board the learner stopped stays stopped. With no board drawn, the plain text shows.
async function guideShow(d, id, cell, b, live, mine) {
  const drawn = live && await live, s = drawn && b.state;
  if (!mine() || (drawn && (!s || !s.streaming || b.finish(d)))) return;
  $('.lee-guide-out', cell)?.remove();
  if (await guidePlay(d, cell, b) || !mine()) return;
  const el = document.createElement('div'); el.className = 'lee-guide-out'; el.textContent = guideText(d);
  $('#out-' + id, cell).after(el);
}
const guideAsk = {n: 0, ctl: null};
globalThis.document?.addEventListener('board:stop', e => { if (e.detail?.by === 'learner') guideAsk.ctl?.abort(); });
//: Asks with events: the first step starts a streaming board and each next step is added to it, so step 1 draws before the model ends. A newer question aborts the older one, whose events then go nowhere.
async function lessonGuide(id, picked = String(globalThis.getSelection?.() ?? '').trim(), asked = null) {
  const said = asked ?? await inputDialog('screen guide', 'ask', GUIDE_START + picked.replace(/\s+/g, ' '));
  if (!said) return;
  const path = lee.path, tabKey = lee.tabKey, find = () => lee.tabKey === tabKey && $(`.lee-cell[data-id="${CSS.escape(id)}"]`);
  guideAsk.ctl?.abort();
  const n = ++guideAsk.n, ctl = guideAsk.ctl = new AbortController(), mine = () => n === guideAsk.n;
  let live = null, whole = false, failed = '', chain = Promise.resolve();
  const got = [];
  try {
    status('Asking the tutor…', 'ok');
    await lee.nbQueue;
    const asked = find();
    if (!asked) return status('', 'ok');
    guideCode(asked, lee.cells.find(x => x.id === id));
    const anchors = guideAnchors(asked), board = loadBoard(), demo = guideDemoAnchors(asked, await board);
    const on = async (ev, d) => {
      if (!mine()) return;
      if (ev === 'error') { failed = d.error; return; }
      if (ev === 'wait') return status(d.wait, 'ok');
      if (ev === 'step') { const k = (d.step.n || got.length + 1) - 1; if (k < got.length) got[k] = d.step; else got.push(d.step); }   // a step comes again as it grows
      const b = await board, cell = mine() && find();
      if (!cell) return;
      if (ev === 'show') { whole = true; b?.stop(); status('', 'ok'); return guideShowCard(d.show, cell, id); }
      if (ev === 'step') {
        if (!b) return;
        if (!live) { $('.lee-guide-out', cell)?.remove(); status('', 'ok'); live = guidePlay({steps: [d.step], tier: d.tier, sources: [], streaming: true, demo_open: d.demo_open}, cell, b); }
        else if (await live && mine() && b.state?.streaming) b.add(d.step);
      } else if (ev === 'board') { whole = true; status('', 'ok'); await guideShow(d, id, cell, b, live, mine); }
    };
    await postEvents('/nb/guide/stream', {path, cell_id: id, said, anchors, ...(demo && {demo})}, (ev, d) => { chain = chain.then(() => on(ev, d)).catch(e => console.warn('Leela guide:', e)); }, ctl.signal);
    await chain;
    const b = await board;
    if (!mine()) return;
    if (live && !whole && await live && mine() && b.state?.streaming) b.finish({steps: got, tier: 'tutor', sources: [], end: ''});
    status(failed, failed ? 'err' : 'ok');
  } catch (e) {
    if (e.name === 'AbortError') { if (mine()) status('', 'ok'); return; }
    status(lessonSaid(e, e.body ?? e.message), 'err');
  }
}
function lessonGuideSelected(picked) {
  const c = lee.cells[lee.sel];
  if (!lessonNotebook() || !c || !guideCell(c)) return status('Pick a lesson cell first.', 'err');
  return lessonGuide(c.id, picked);
}
function paintGuideButton(cell, c) {
  $('.lee-guide', cell)?.remove();
  if (!lessonNotebook() || !guideCell(c)) return;
  const button = document.createElement('button'); button.type = 'button'; button.className = 'lee-btn lee-guide'; button.textContent = GUIDE_START.trim() + '…';
  button.onmousedown = e => { e.preventDefault(); e.stopPropagation(); };
  button.onclick = () => lessonGuide(c.id);
  $('.lee-cellmain', cell).appendChild(button);
}
function paintLessonCell(cell, c) {
  const role = c.cell_type === 'markdown' ? c.extra?.lesson?.role : '';
  cell.dataset.lessonRole = role || '';
  $('.lee-confidence', cell)?.remove();
  if (role !== 'prediction') return;
  const row = document.createElement('div'); row.className = 'lee-confidence';
  const label = document.createElement('span'); label.textContent = 'Sure?'; row.appendChild(label);
  for (const [value, name] of [[10, 'not'], [30, 'a little'], [50, 'half'], [70, 'fairly'], [90, 'very']]) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = name;
    button.setAttribute('aria-pressed', String(c.extra.lesson.confidence === value));
    button.onclick = async () => {
      const at = lee.cells.findIndex(x => x.id === c.id), current = lee.cells[at]; if (!current) return;
      const previous = current.extra.lesson.confidence, confidence = previous === value ? null : value;
      if (confidence === null) delete current.extra.lesson.confidence; else current.extra.lesson.confidence = confidence;
      for (const b of row.querySelectorAll('button')) { b.disabled = true; b.setAttribute('aria-pressed', String(b === button && confidence !== null)); }
      try { await nbEdit({op: 'lesson_confidence', i: at, confidence}); }
      catch (e) {
        if (previous == null) delete current.extra.lesson.confidence; else current.extra.lesson.confidence = previous;
        status(lessonSaid(e), 'err');
      } finally {
        const now = lee.cells.find(x => x.id === c.id), host = $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`);
        if (now && host) paintLessonCell(host, now);
      }
    };
    row.appendChild(button);
  }
  $('.lee-cellmain', cell).appendChild(row);
}
const EXERCISE_MARKS = {pass: '✓', fail: '✗', error: '!', timeout: '…'};
const isExercise = c => c?.cell_type === 'code' && !!c.extra?.exercise?.tests;

function exEl(tag, cls, text) {
  const e = document.createElement(tag); e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function exerciseState(key) {
  const all = lee.exerciseResults ||= new Map();
  if (!all.has(key)) all.set(key, {});
  return all.get(key);
}

function exerciseGradeLine(c) {
  const g = c.extra?.exercise?.state?.grade;
  return g && c.graded_current ? `Grade ${g.score}/10. ${g.note}` : '';
}

function exerciseTutorMessage(c, r) {
  const rows = r.checks.map(k => `- ${k.say}: ${k.message}`);
  return [`I pressed Check on the exercise in cell ${lee.cells.indexOf(c) + 1} (id ${c.id}). ${r.summary}`, ...rows,
          'Please look at my code and give me one hint, not the answer.'].join('\n');
}

function renderExercise(c, root) {
  const host = $('.lee-exercise', root || $(`.lee-cell[data-id="${CSS.escape(c.id)}"]`)); if (!host) return;
  const st = exerciseState(`${lee.tabKey}:${c.id}`), r = st.result, fresh = !!r && r.source === c.source;
  const kept = host.contains?.(document.activeElement) ? document.activeElement.getAttribute('data-ex') : '';
  const check = exEl('button', 'lee-btn' + (st.busy ? ' busy' : ''), st.busy ? 'Checking…' : 'Check');
  check.type = 'button'; check.setAttribute('aria-label', 'Check my code'); check.setAttribute('data-ex', 'check');
  check.setAttribute('aria-busy', String(!!st.busy)); check.setAttribute('aria-disabled', String(!!st.busy || !!c.running));
  check.onclick = () => checkExercise(c.id);
  const ask = exEl('button', 'lee-btn', 'Ask the tutor');
  ask.type = 'button'; ask.setAttribute('aria-label', 'Ask the tutor about this result'); ask.setAttribute('data-ex', 'ask'); ask.disabled = !fresh;
  ask.onclick = () => askTutor(c.id);
  const bar = exEl('div', 'lee-ex-bar'); bar.appendChild(check); bar.appendChild(ask);
  host.replaceChildren(bar);
  if (st.error) host.appendChild(exEl('div', 'lee-ex-error', st.error));
  if (r) {
    const summary = exEl('div', 'lee-ex-summary', r.summary); summary.setAttribute('role', 'status'); host.appendChild(summary);
    if (r.source !== c.source) host.appendChild(exEl('div', 'lee-ex-note', 'Out of date: the code has changed since this check.'));
    const list = exEl('ul', 'lee-ex-list' + (fresh ? '' : ' stale'));
    for (const k of r.checks) {
      const row = exEl('li', 'lee-ex-row'); row.setAttribute('data-status', k.status);
      const mark = exEl('span', 'lee-ex-mark', EXERCISE_MARKS[k.status] || '?'); mark.setAttribute('aria-label', k.status);
      row.appendChild(mark); row.appendChild(exEl('span', 'lee-ex-say', k.say)); row.appendChild(exEl('span', 'lee-ex-msg', k.message));
      list.appendChild(row);
    }
    host.appendChild(list);
  }
  const grade = exerciseGradeLine(c);
  if (grade) host.appendChild(exEl('div', 'lee-ex-grade', grade));
  ({check, ask})[kept]?.focus();
}

async function checkExercise(cellId) {
  await lee.nbQueue;
  const runKey = lee.tabKey, st = exerciseState(`${runKey}:${cellId}`);
  const cur = () => lee.tabKey === runKey ? lee.cells.find(x => x.id === cellId) : null;
  const c = cur(); if (!c || st.busy) return;
  if (c.running) return status('this cell is already running', 'err');
  st.busy = true; c.running = true; st.error = '';
  renderExercise(c);
  try {
    if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) throw new Error('the notebook could not be saved first');
    const i = lee.cells.findIndex(x => x.id === cellId); if (!cur() || i < 0) throw new Error('the notebook changed before the check began');
    const v = ensureCellMounted(i), source = v ? LeeCM.getDoc(v) : lee.cells[i].source;
    const {cell, ...verdict} = await withPython(() => post('/exercise/check', {i, id: cellId, path: runKey, source, seq: nextSeq(), ...seenRow(runKey, cellId)}));
    st.result = {...verdict, source};
    const at = cur();
    if (at && cell) {
      const view = lee.editors.get(cellId), typed = view ? LeeCM.getDoc(view) : source;
      Object.assign(at, cell);
      if (typed !== source) { at.source = typed; at.graded_current = false; }
      renderOutputs(at);
      $('#g-' + cellId).textContent = '[' + (cell.execution_count ?? ' ') + ']';
      setCellState(at, (at.outputs || []).some(o => o.output_type === 'error') ? 'error' : 'done');
      status(verdict.summary, verdict.passed === verdict.total ? 'ok' : 'info');
      if (lee.path && autoSaveEnabled()) saveTab(true).catch(() => {});
      leeVars();
    }
  } catch (e) { st.error = String(e.message || e); status(st.error, 'err'); }
  finally {
    st.busy = false;
    for (const x of [c, cur()]) if (x) x.running = false;
    const at = cur(); if (at) renderExercise(at);
  }
}

function askTutor(cellId) {
  const c = lee.cells.find(x => x.id === cellId), r = exerciseState(`${lee.tabKey}:${cellId}`).result;
  if (!c || !r || r.source !== c.source) return;
  if (lee.agentBusy || lee.agentSending) return status('The tutor is working. Ask again when it finishes.', 'err');
  leeAct('focus_agent');
  const prompt = $('#agentprompt');
  if (prompt.value.trim()) return status('Send or clear your message to the agent first.', 'err');
  prompt.value = exerciseTutorMessage(c, r);
  return sendAgent();
}
/* ipywidgets in notebook cells. Each notebook has one link: a socket on `/nb/comm/ws` following its
   kernel, and the vendored manager, loaded once a widget has to be drawn. A view is kept per cell,
   output and model, so re-rendering a cell's outputs moves the live widget rather than rebuilding it.
   Where a widget cannot be live its `text/plain` repr shows, with a muted line saying why. */
const WIDGET_MIME = 'application/vnd.jupyter.widget-view+json';
//: How long a drawn output waits for its model before saying so. It keeps waiting while a cell runs.
const WIDGET_WAIT = 10000;
const WIDGET_BADGE = 'interactive widget: run the cell';
const WIDGET_THEME = `:host { display: block; color: var(--lee-fg); font-size: 13px;
  --jp-layout-color0: var(--lee-bg); --jp-layout-color1: var(--lee-bg1); --jp-layout-color2: var(--lee-bg2);
  --jp-layout-color3: var(--lee-bg3); --jp-inverse-layout-color0: var(--lee-fg);
  --jp-border-color1: var(--lee-border); --jp-border-color2: var(--lee-border); --jp-border-width: 1px;
  --jp-ui-font-color0: var(--lee-fg); --jp-ui-font-color1: var(--lee-fg); --jp-ui-font-color2: var(--lee-fg2);
  --jp-content-font-color0: var(--lee-fg); --jp-content-font-color1: var(--lee-fg);
  --jp-ui-inverse-font-color0: var(--lee-bg); --jp-ui-inverse-font-color1: var(--lee-bg);
  --jp-inverse-ui-font-color0: var(--lee-bg); --jp-inverse-ui-font-color1: var(--lee-bg);
  --jp-brand-color0: var(--lee-accent); --jp-brand-color1: var(--lee-accent); --jp-brand-color2: var(--lee-accent);
  --jp-error-color0: var(--lee-red); --jp-error-color1: var(--lee-red); --jp-warn-color0: var(--lee-orange);
  --jp-warn-color1: var(--lee-orange); --jp-success-color0: var(--lee-green); --jp-success-color1: var(--lee-green);
  --jp-info-color0: var(--lee-blue); --jp-info-color1: var(--lee-blue);
  --jp-ui-font-family: inherit; --jp-ui-font-size1: 13px; --jp-code-font-family: var(--lee-mono);
  --jp-code-font-size: 13px; --jp-code-line-height: 1.4; --jp-code-padding: 2px;
  --jp-cell-prompt-width: 0px; --jp-cell-prompt-font-family: var(--lee-mono); --jp-cell-prompt-letter-spacing: 0;
  --jp-cell-prompt-opacity: 1; --jp-cell-outprompt-font-color: var(--lee-fg3);
  --jp-flat-button-height: 24px; --jp-flat-button-padding: 8px 12px; }
.lee-widget-mount { overflow: auto; }`;
const widgetLinks = new Map();
let widgetBundle = null, widgetSeq = 0, widgetSheet = null;
const widgetKey = () => lee.path || lee.tabKey || '';

function loadWidgetBundle() {
  if (window.LeeWidgets) return Promise.resolve();
  return widgetBundle ||= new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = $('meta[name="lee-widgets-src"]')?.content || '/leestatic/lee-widgets.js';
    s.onload = () => {
      for (const family of ['Font Awesome 5 Free', 'FontAwesome'])
        document.fonts.add(new FontFace(family, 'url(/leestatic/fonts/fa-solid-900.woff2)', {weight: '900'}));
      resolve();
    };
    s.onerror = () => { widgetBundle = null; reject(new Error('the widget bundle failed to load')); };
    document.head.appendChild(s);
  });
}
function widgetStyle(root) {
  const text = LeeWidgets.css + WIDGET_THEME;
  if (!('adoptedStyleSheets' in root)) return root.prepend(Object.assign(document.createElement('style'), {textContent: text}));
  if (!widgetSheet) { widgetSheet = new CSSStyleSheet(); widgetSheet.replaceSync(text); }
  root.adoptedStyleSheets = [widgetSheet];
}

function widgetLink(key) {
  let l = widgetLinks.get(key);
  if (!l) widgetLinks.set(key, l = {key, state: 'connecting', views: new Map(), dead: new Set(), logs: new Map(),
                                    queue: [], asks: new Map(), seq: 0, gen: 0, mgr: null, kernel: null});
  if (l.sock && l.sock.readyState <= WebSocket.OPEN) return l;
  l.state = 'connecting';
  l.ready = new Promise(res => l.settle = res);
  const sock = l.sock = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/nb/comm/ws?path=${encodeURIComponent(key)}`);
  sock.onmessage = e => widgetHeard(l, JSON.parse(e.data));
  sock.onclose = () => {
    if (l.sock !== sock) return;
    const live = l.state === 'ready' && [...l.views.values()].some(v => v.view);
    l.sock = null; l.state = 'closed'; l.settle();
    if (live) setTimeout(() => widgetLink(key), 1000);
  };
  return l;
}
//: A run waits for its notebook's socket to be following the kernel, so the widgets it makes are heard.
async function widgetWatch(key, cellId) {
  const l = widgetLink(key);
  l.logs.get(cellId)?.remove(); l.logs.delete(cellId);
  for (const [k, v] of l.views) if (v.log && v.cell === cellId) { widgetUnmount(v); l.views.delete(k); }
  await Promise.race([l.ready, new Promise(res => setTimeout(res, 2000))]);
}
function widgetAsk(l, f) {
  const id = `ask-${++l.seq}`;
  return new Promise(res => {
    if (l.sock?.readyState !== WebSocket.OPEN) return res({});
    l.asks.set(id, res);
    setTimeout(() => { if (l.asks.delete(id)) res({}); }, 20000);
    l.sock.send(JSON.stringify({...f, id}));
  });
}
function widgetHeard(l, m) {
  if (m.type === 'ready') {
    if (l.kernel && l.kernel !== m.kernel) widgetReset(l);
    const again = !!l.mgr;
    l.kernel = m.kernel; l.state = 'ready'; l.settle();
    if (again) widgetReconcile(l);
    else if (l.views.size || l.queue.length) widgetManager(l);
    return widgetPaintAll(l);
  }
  if (['waiting', 'kernel_gone', 'kernel_restart', 'unsupported'].includes(m.type)) {
    widgetReset(l);
    l.state = {unsupported: 'unsupported', kernel_restart: 'ready'}[m.type] || 'gone';
    if (l.state === 'gone') l.kernel = null;
    l.settle();
    return widgetPaintAll(l);
  }
  if (m.type === 'resync') return l.mgr && widgetReconcile(l);
  if (m.type === 'reply' || m.type === 'error') {
    const res = l.asks.get(m.id);
    if (res) { l.asks.delete(m.id); res(m.content || {}); }
    else if (m.type === 'error') status(`widget: ${m.error}`, 'err');
    return;
  }
  widgetClean(l, m);
  if (l.mgr) return l.mgr.receive(m);
  if (l.queue.length < 5000) l.queue.push(m);
  widgetManager(l);
}
//: The views that write a kernel string as HTML: `value` of HTML and HTMLMath, and a description with `description_allow_html`. The kernel runs code the agent can write, so the string is cleaned on its way in.
const WIDGET_HTML = new Set(['HTMLModel', 'HTMLMathModel']);
function widgetClean(l, m) {
  const c = m.content || {}, all = c.data?.states;
  // a page that loads from the kernel gets every model's state in one reply on the control comm
  if (all && typeof all === 'object') return Object.entries(all).forEach(([id, x]) => x?.state && widgetCleanState(l, id, {_model_name: x.model_name, ...x.state}, x.state));
  if (c.data?.state && typeof c.data.state === 'object' && c.comm_id) widgetCleanState(l, c.comm_id, c.data.state, c.data.state);
}
//: `st` read as model `id`'s state; the cleaned values are written to `out`.
function widgetCleanState(l, id, st, out) {
  const kinds = l.kinds ||= new Map(), was = kinds.get(id) || {};
  const now = {name: st._model_name ?? was.name, html: st.description_allow_html ?? was.html, desc: typeof st.description === 'string' ? st.description : was.desc};
  kinds.set(id, now);
  if (WIDGET_HTML.has(now.name) && typeof st.value === 'string') out.value = richString(st.value);
  // turning HTML on later draws the description already held, so it is cleaned then too
  if (now.html && typeof now.desc === 'string' && ('description' in st || 'description_allow_html' in st)) out.description = richString(now.desc);
}
function widgetReset(l) {
  const mgr = l.mgr;
  l.kinds = new Map();
  l.mgr = l.loading = null; l.loaded = false; l.queue = []; l.gen += 1;
  mgr?.kill().catch(() => {});
  for (const v of l.views.values()) { l.dead.add(v.id); widgetUnmount(v); }
}
function widgetManager(l) {
  if (l.state !== 'ready') return Promise.resolve(null);
  const gen = l.gen;
  return l.loading ||= (async () => {
    try { await loadWidgetBundle(); }
    catch (e) { if (l.gen === gen) l.loading = null; status(String(e.message || e), 'err'); return null; }
    if (l.gen !== gen || l.state !== 'ready') return null;
    const mgr = l.mgr = new LeeWidgets.Manager({
      post: f => l.sock?.readyState === WebSocket.OPEN && l.sock.send(JSON.stringify(f)),
      info: target_name => widgetAsk(l, {op: 'info', target_name}),
      output: (view, m) => widgetCallbackOutput(l, view, m),
      refused: () => widgetPaintAll(l),
      // A model can arrive after its view gave up on it: the load answered empty while a cell still ran.
      registered: id => { if (l.mgr !== mgr || !l.dead.delete(id)) return; for (const v of l.views.values()) if (v.id === id) widgetPaint(l, v); }});
    for (const m of l.queue.splice(0)) mgr.receive(m);
    widgetLoad(l, mgr);
    return mgr;
  })();
}
//: Every widget the kernel holds, so a reloaded page re-mounts the live ones.
function widgetLoad(l, mgr) {
  l.loaded = false;
  mgr._loadFromKernel().catch(() => {}).finally(() => { if (l.mgr === mgr) { l.loaded = true; widgetPaintAll(l); } });
}
//: The same kernel after a dropped socket: whatever it closed meanwhile goes, and the rest is read again.
async function widgetReconcile(l) {
  if (l.reconciling) return;
  const mgr = l.reconciling = l.mgr;
  try {
    const r = await widgetAsk(l, {op: 'info', target_name: mgr.comm_target_name});
    if (r.comms && l.mgr === mgr) await mgr.forget(r.comms);
    if (l.mgr === mgr) widgetLoad(l, mgr);
  } catch {} finally { l.reconciling = null; }
}

function widgetEl(o, c, i) {
  const d = o.data[WIDGET_MIME] || {}, text = o.data['text/plain'] || '';
  if (!c || !d.model_id || d.version_major !== 2) {
    const host = document.createElement('div'); host.className = 'lee-out result lee-widget';
    widgetFallback({host, text}, c ? 'interactive widget: made by an ipywidgets this page does not draw' : '');
    return host;
  }
  const l = widgetLink(widgetKey()), vk = `${c.id}:${i}:${d.model_id}`;
  let v = l.views.get(vk);
  if (!v) {
    const host = document.createElement('div'), root = host.attachShadow({mode: 'open'}), mount = document.createElement('div');
    host.className = 'lee-out result lee-widget'; host.dataset.cell = c.id; mount.className = 'lee-widget-mount';
    root.append(document.createElement('slot'), mount);
    for (const ev of ['pointerdown', 'keydown']) host.addEventListener(ev, () => { l.lastCell = c.id; });
    l.views.set(vk, v = {key: vk, cell: c.id, id: d.model_id, host, root, mount, text, view: null, log: String(i).startsWith('log')});
  }
  if (!v.view && !v.trying) widgetPaint(l, v);
  v.seen = widgetSeq;
  return v.host;
}
function widgetRefusal(l, id) {
  const r = l.mgr?.refusal(id);
  if (!r) return '';
  return r.module ? `interactive widget: ${r.module} is not available in Leela, so this is its text form`
    : `interactive widget: protocol ${r.protocol || 'unknown'} is not ipywidgets 8, so this is its text form`;
}
function widgetFallback(v, note) {
  if (v.note === note && v.host.firstChild) return;
  v.note = note;
  v.host.replaceChildren(Object.assign(document.createElement('span'), {textContent: v.text}));
  if (note) v.host.append(Object.assign(document.createElement('div'), {className: 'lee-dim lee-widget-note', textContent: note}));
}
function widgetPaint(l, v) {
  if (v.view) return;
  const why = l.state === 'unsupported' ? 'interactive widget: this kernel cannot run widgets'
    : l.dead.has(v.id) || l.state === 'gone' || l.state === 'closed' ? WIDGET_BADGE : widgetRefusal(l, v.id);
  if (why) return widgetFallback(v, why);
  if (!v.host.firstChild) widgetFallback(v, '');
  if (l.state === 'ready') widgetTry(l, v);
}
function widgetPaintAll(l) { for (const v of l.views.values()) widgetPaint(l, v); }
const widgetRunning = l => widgetKey() === l.key && (lee.cells || []).some(c => c.running);
async function widgetTry(l, v) {
  if (v.trying) return;
  v.trying = true;
  try {
    const mgr = await widgetManager(l), until = Date.now() + WIDGET_WAIT;
    while (mgr && l.mgr === mgr && l.views.get(v.key) === v && !v.view) {
      if (mgr.has_model(v.id)) return await widgetShow(l, mgr, v);
      if (mgr.refusal(v.id)) return;
      if (l.loaded && !widgetRunning(l)) return void l.dead.add(v.id);
      if (Date.now() > until) widgetFallback(v, 'interactive widget: waiting for the kernel to send it');
      await new Promise(res => setTimeout(res, 150));
    }
  } catch (e) {
    widgetFallback(v, `interactive widget: ${e.message || e}`);
  } finally {
    v.trying = false;
    if (!v.view && l.views.get(v.key) === v && (l.dead.has(v.id) || l.mgr?.refusal(v.id))) widgetPaint(l, v);
  }
}
async function widgetShow(l, mgr, v) {
  const view = await mgr.create_view(await mgr.get_model(v.id), {});
  // A view for a notebook no longer on screen waits briefly; the next render of its cell tries again.
  for (const until = Date.now() + 5000; !v.mount.isConnected && Date.now() < until;) await new Promise(res => setTimeout(res, 50));
  if (l.mgr !== mgr || l.views.get(v.key) !== v || v.view || !v.mount.isConnected) return view.remove();
  widgetStyle(v.root);
  v.host.replaceChildren(); v.note = null;
  v.view = view;
  await mgr.display_view(view, v.mount);
}
function widgetUnmount(v) {
  if (!v.view) return;
  try { v.view.remove(); } catch {}
  v.view = null; v.mount.replaceChildren();
}
//: `renderOutputs` empties the box; the live hosts leave it first and come back through `widgetEl`.
function widgetDetach(c) {
  widgetSeq += 1;
  for (const v of widgetLinks.get(widgetKey())?.views.values() || []) if (v.cell === c.id && !v.log) v.host.remove();
}
function widgetSweep(c) {
  const l = widgetLinks.get(widgetKey()); if (!l) return;
  for (const [k, v] of l.views) if (v.cell === c.id && !v.log && v.seen !== widgetSeq) { widgetUnmount(v); l.views.delete(k); }
  const log = l.logs.get(c.id), box = $('#out-' + c.id);
  if (log && box) box.appendChild(log);
}

function widgetAsOutput(m) {
  const t = m.msg_type, c = m.content || {};
  if (t === 'stream') return {output_type: 'stream', name: c.name, text: c.text};
  if (t === 'error') return {output_type: 'error', ename: c.ename, evalue: c.evalue, traceback: c.traceback};
  if (t === 'display_data' || t === 'execute_result' || t === 'update_display_data') return {output_type: 'display_data', data: c.data || {}, metadata: c.metadata || {}};
  return t === 'clear_output' ? {output_type: 'clear'} : null;
}
//: What a widget's own callback prints, with no Output widget to take it, goes under the widget's cell.
function widgetCallbackOutput(l, view, m) {
  const o = widgetAsOutput(m); if (!o) return;
  const id = view?.el?.getRootNode?.()?.host?.dataset?.cell || l.lastCell;
  const c = widgetKey() === l.key ? (lee.cells || []).find(x => x.id === id) : null;
  if (!c) return o.output_type === 'clear' || status(`from widget: ${String(o.text ?? o.data?.['text/plain'] ?? o.evalue ?? '').trim()}`);
  let log = l.logs.get(c.id);
  if (!log) {
    log = Object.assign(document.createElement('div'), {className: 'lee-widget-log lee-dim'});
    log.append(Object.assign(document.createElement('div'), {className: 'lee-widget-from', textContent: 'from widget'}));
    l.logs.set(c.id, log);
  }
  if (o.output_type === 'clear') log.replaceChildren(log.firstChild);
  else log.appendChild(outputEl(o, c, `log${++l.seq}`));
  const box = $('#out-' + c.id);
  if (box && log.parentNode !== box) box.appendChild(log);
}
/* Put a position in the middle of the view rather than merely inside it.

   `scrollIntoView` moves the minimum distance, so a match below the fold arrives on the last
   visible line with nothing under it. Written against `scrollDOM` rather than CodeMirror's own
   centring effect, because the vendored bundle is committed and rebuilding it needs node.

   A notebook scrolls its column of cells, not the cell's own editor, so the element that can move
   is the one that gets scrolled. */
function centreOnPos(v, pos) {
  const coords = v.coordsAtPos(pos); if (!coords) return;
  const own = v.scrollDOM, host = own.scrollHeight - own.clientHeight > 4 ? own : $('#editor');
  if (!host) return;
  const box = host.getBoundingClientRect();
  host.scrollTop += (coords.top + coords.bottom) / 2 - (box.top + box.height / 2);
}

function jumpToLine(line) {
  const v = lee.kind === 'notebook' ? lee.editors.get(lee.cells[lee.sel]?.id) : lee.editors.get('file');
  if (!v) return;
  const n = Math.max(1, Math.min(Number(line) || 1, v.state.doc.lines));
  const pos = v.state.doc.line(n).from;
  v.dispatch({selection: {anchor: pos}, scrollIntoView: true}); v.focus();
  requestAnimationFrame(() => centreOnPos(v, pos));
}

async function openLocation(hit) {
  const name = hit.path.split('/').pop();
  const inCell = Number(hit.cell_line) > 0;
  try {
    if (!inCell && /\.ipynb$/i.test(hit.path)) {
      await leeOpenFile(hit.path);
      return status(`${name}: line ${hit.line} of the notebook file is in no cell`, 'info');
    }
    const line = inCell ? Number(hit.cell_line) : hit.line;
    lee.pendingLocation = {path: hit.path, line, column: Number(hit.column || 0), symbol: hit.symbol || '',
                           cellId: hit.cell || '',
                           cellIndex: Number.isFinite(hit.cell_index) ? Number(hit.cell_index) : -1};
    await leeOpenFile(hit.path);
    status(`${name}${inCell ? ` · cell ${Number(hit.cell_index) + 1}` : ''}:${line}`);
  } catch (e) { return status(e.message || String(e), 'err');}
}

async function stopCell(i) {
  const c = lee.cells[i];
  if (!c) return status(`cell ${i + 1} is not running`, 'err');
  // The page's flag can lag the run (an undo rebuilds the cells), so a cell the page thinks idle is still put to the server.
  const was = c.running;
  if (!was && c.cell_type === 'prompt') return status(`cell ${i + 1} is not running`, 'err');   // the server stops an agent turn for any prompt cell it is asked about
  if (was) { status(`stopping cell ${i + 1}…`); lee.promptRuns?.get(c.id)?.abort(); }
  let r;
  try { r = await post('/nb/interrupt', {path: lee.tabKey || '', id: c.id}); }
  catch (e) { if (was) throw e; return status(`cell ${i + 1} is not running`, 'err'); }
  status(r.forced ? 'cell stopped · kernel restarted because interrupt was ignored' : 'cell stopped',
         r.forced ? 'err' : 'ok');
  if (r.forced) kernelRestarted();
}

/* A run stream that ended without its result leaves the server knowing how the cell stands. Ask it,
   and keep asking, slower each time, while the cell is still running. */
async function settleRun(path, id) {
  for (let wait = 2000, misses = 0; ; wait = Math.min(wait * 2, 10000)) {
    const s = await post('/nb/run/state', {path, id}).catch(e => { if (++misses > 3) throw e; return {running: true}; });
    if (!s.running) {
      if (!s.cell) throw new Error('the cell is no longer in the notebook');
      const failed = (s.cell.outputs || []).some(o => o.output_type === 'error');
      if (s.cell.execution_count == null && !failed) throw new Error('the run stream ended, and the kernel kept no record of this cell');
      return {ok: !failed, cell: s.cell, inline: [], result: null};
    }
    await new Promise(res => setTimeout(res, wait));
  }
}

/* Resolves to `{ok, error}`. The slide deck runs cells with the status line hidden under it, so it
   reads the outcome here and follows the outputs through `lee-cell-output`. `save: false` runs the
   live text and writes no file: no save before or after, and no placeholder made valid. */
const cellOutputEvent = (id, outputs) => dispatchEvent(new CustomEvent('lee-cell-output', {detail: {id, outputs}}));
//: A run stream's `output` message on the outputs shown: `n` outputs, each op a stream's new text or a whole output.
function applyOutputOps(outputs, {n, ops}) {
  const outs = (outputs || []).slice(0, n);
  for (const [k, kind, v] of ops) outs[k] = kind === 'append' ? {...outs[k], text: (outs[k]?.text || '') + v} : v;
  return outs;
}
async function runCell(i, advance, {save = true} = {}) {
  // An edit still in flight (a confidence click) replaces the cells when it lands, and lands mid-save and refuses it.
  await lee.nbQueue;
  const c = lee.cells[i]; if (!c) return {ok: false, error: 'that cell is no longer in the notebook'};
  if (c.running) {
    status(`cell ${i + 1} is already running`, 'err');
    return {ok: false, error: `cell ${i + 1} is already running`};
  }
  const runKey = lee.tabKey, cellId = c.id;
  // The cell that runs, wherever an insert, move or delete above has put it since; null once its tab is not shown.
  const cur = () => lee.tabKey === runKey ? lee.cells.find(x => x.id === cellId) : null;
  let res = {ok: true, error: ''};
  const v = ensureCellMounted(i);
  const src = v ? LeeCM.getDoc(v) : c.source, seq = nextSeq();
  const el = $(`.lee-cell[data-i="${i}"]`);
  if (c.cell_type === 'markdown') showRenderedMarkdown(c, true);
  else if (c.cell_type === 'prompt') {
    c.running = true;
    try { await askCell(i, src, el); }
    finally { c.running = false; }
  } else {
    const p = lee.cells.find(x => x.cell_type === 'markdown' && x.extra?.lesson?.role === 'prediction' && x.extra.lesson.for === cellId);
    const pv = p && lee.editors.get(p.id), guess = p ? {prediction: pv ? LeeCM.getDoc(pv) : p.source, confidence: p.extra.lesson.confidence} : {};
    if (save && lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) return {ok: false, error: 'the notebook could not be saved first'};
    const began = performance.now();
    c.running = true;
    if (c.extra?.lesson) $('.lee-reveal', el)?.remove();
    el?.classList.add('running');
    setCellState(c, 'running');
    setCellTime(c, 0, true);
    const cellClock = setInterval(() => { if (cur()) setCellTime(c, performance.now() - began, true); }, 100);
    $('#g-' + c.id).textContent = '[*]';
    status(`running cell ${i + 1}…`);
    try {
      let r = null, failed = null;
      await widgetWatch(runKey, cellId);
      try {
        await withPython(() => postEvents('/nb/run/stream', {i, id: cellId, path: runKey, source: src, seq, ...seenRow(runKey, cellId), ...guess, ...(save ? {} : {save: false})}, (event, data) => {
          if (event === 'error') throw failed = new Error(data.text || 'cell execution failed');
          if (event === 'done') r = data;
          const at = cur();
          if (at && event === 'output') { at.outputs = data.ops ? applyOutputOps(at.outputs, data) : data.outputs || []; renderOutputs(at); cellOutputEvent(cellId, at.outputs); }
        }, null, 45000));
      } catch (e) { if (e === failed || e.unsent) throw e; }
      if (!r) r = await settleRun(runKey, cellId);
      const at = cur();
      if (!at) {
        c.running = false; el?.classList.remove('running'); leeVars();
        return {ok: false, error: 'the notebook changed while the cell ran'};
      }
      Object.assign(at, r.cell);
      renderOutputs(at); cellOutputEvent(cellId, at.outputs || []);
      const view = lee.editors.get(cellId); if (view) LeeCM.setInlineValues(view, r.inline || []);
      if (r.result) requestAnimationFrame(() => openValueLens(r.result, $('#out-' + cellId) || el, 'expression result'));
      $('#g-' + cellId).textContent = '[' + (r.cell.execution_count ?? ' ') + ']';
      const elapsed = Number(at.execution_ms ?? (performance.now() - began));
      const duration = formatCellTime(elapsed), n = lee.cells.indexOf(at) + 1;
      setCellTime(at, elapsed, false);
      setCellState(at, r.ok ? 'done' : 'error', r.ok ? `ran successfully in ${duration}` : `failed after ${duration}`);
      status(r.ok ? `cell ${n} ran in ${duration}${r.lost ? ' · some of its last outputs are lost' : ''}`
             : r.reason === 'shell_stopped' ? `cell ${n}: the kernel's shell stopped answering · restart the kernel` : `cell ${n} failed after ${duration}`,
             r.ok ? 'ok' : 'err');
      res = {ok: !!r.ok, error: r.ok ? '' : `cell ${n} failed after ${duration}`};
    } catch (e) {
      const elapsed = performance.now() - began, at = cur() || c;
      at.execution_ms = elapsed; setCellTime(at, elapsed, false);
      setCellState(at, 'error', `run failed after ${formatCellTime(elapsed)}`);
      status(String(e.message || e), 'err');
      res = {ok: false, error: String(e.message || e)};
    } finally { clearInterval(cellClock); }
    for (const x of [c, cur()]) if (x) x.running = false;
    if (cur()?.extra?.lesson) renderLessonReveal(cur());
    if (isExercise(cur())) renderExercise(cur());
    if (cur()) $(`#editor .lee-cell[data-id="${CSS.escape(cellId)}"]`)?.classList.remove('running');
    if (save && lee.path && cur() && autoSaveEnabled()) saveTab(true).catch(() => {});
    leeVars();
  }
  if (!advance || (i = cur() ? lee.cells.findIndex(x => x.id === cellId) : -1) < 0) return res;
  if (advance === 'insert') { const at = belowAt(i); if (await nbEdit({op: 'insert', i: at})) focusCell(at); }
  else if (advance) {
    const j = visibleCell(i, 1), at = lee.cells.length;
    if (j >= 0) focusCell(j); else if (await nbEdit({op: 'insert', i: at})) focusCell(at);
  }
  return res;
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
  // Exactly one source line is current. Clear the old marker before moving, including when
  // step-in changes files.
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
        unfoldTo(i); selectCell(i); const view = ensureCellMounted(i);
        LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line);
      }
    } else {
      const view = lee.editors.get('file');
      if (view) { LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line); }
    }
    return;
  }
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
  host._leeView = createEditor(host, {doc: src.content || '', lang: nbLang(), readOnly: true, lineNums: true});
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
  const view = ensureCellMounted(i), source = LeeCM.getDoc(view), key = lee.tabKey;
  let breakpoints = lee.breakpoints.get(c.id) || [];
  if (!breakpoints.length) {
    breakpoints = [LeeCM.lineOf(view)]; rememberBreakpoints(c.id, breakpoints);
    LeeCM.setBreakpoints(view, breakpoints);
  }
  lee.debugCell = i; c.running = true; setCellState(c, 'running');
  status(`starting ipykernel debugger for cell ${i + 1}…`);
  let done = null;
  try {
    await withPython(() => postEvents('/nb/debug/stream', {i, id: c.id, path: key, source, seq: nextSeq(), ...seenRow(key, c.id), breakpoints}, (event, data) => {
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
    }));
    const at = lee.tabKey === key && lee.cells.find(x => x.id === c.id);
    if (done?.cell && at) {
      Object.assign(at, done.cell); renderOutputs(at);
      $('#g-' + c.id).textContent = '[' + (at.execution_count ?? ' ') + ']';
      setCellState(at, done.ok ? 'done' : 'error');
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
/* A prompt cell answers into the cell, so the reply saves with the notebook. The tab is not re-mounted afterwards:
 * `/tab/state` would reload from disk and drop an answer not yet saved. */
async function askCell(i, src, el) {
  const c = lee.cells[i], runKey = lee.tabKey, cellId = c.id;
  // The cell that was asked, wherever an insert, move or delete has put it; null once its tab is not shown.
  const cur = () => lee.tabKey === runKey ? lee.cells.find(x => x.id === cellId) : null;
  const notice = $('#model-' + cellId);
  const began = performance.now();
  let clock = null;
  el?.classList.add('running');
  $('#g-' + cellId).textContent = '…';
  if (notice) {
    notice.hidden = false;
    const tick = () => {
      const elapsed = performance.now() - began;
      const seconds = Math.floor(elapsed / 1000);
      const at = cur(); if (at) setCellTime(at, elapsed, true);
      const time = notice.querySelector('.lee-running-time');
      if (time) time.textContent = seconds < 2 ? ' · starting' : ` · ${seconds}s elapsed`;
    };
    tick();
    clock = setInterval(tick, 1000);
  }
  status('model running…');
  try {
    let r = null, raw = '';
    const seen = new Map();
    // An insert or move re-renders the cell, so its reply area is made again when it has gone.
    const area = (sel, fresh = false) => {
      const out = $('#out-' + cellId); if (!out) return null;
      if (fresh || !out.querySelector('.lee-reply')) seen.clear(), out.innerHTML = '<div class="lee-agent-steps lee-cell-agent-steps"></div><div class="lee-reply"></div>';
      return out.querySelector(sel);
    };
    area('.lee-reply', true);
    // Held so Stop can end the turn here as well as asking the agent to stop.
    lee.promptRuns = lee.promptRuns || new Map();
    const abort = new AbortController();
    lee.promptRuns.set(cellId, abort);
    await postEvents('/nb/ask/stream', {i, id: cellId, path: runKey, source: src, seq: nextSeq(), ...seenRow(runKey, cellId)}, (event, data) => {
      const shown = cur();
      if (event === 'chunk') {
        raw += data.text || '';
        const reply = shown && area('.lee-reply'); if (reply) renderMarkdown(reply, raw);
      } else if (event === 'activity') {
        const steps = shown && area('.lee-agent-steps');
        let row = seen.get(data.id);
        if (!row && steps) { row = document.createElement('details'); steps.appendChild(row); seen.set(data.id, row); }
        if (row) renderAgentStep(row, data);
      } else if (event === 'approval') showApproval(data);
      else if (event === 'error') throw new Error(data.text || 'model failed');
      else if (event === 'done') r = data;
    }, abort.signal);
    if (!r) throw new Error('the model stream ended without a result');
    const at = cur();
    if (!at) { leeVars(); return; }
    Object.assign(at, r.cell);
    renderOutputs(at);
    for (const e of (r.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const here = (r.edits || []).some(e => e.path === lee.path);
    showProblems(r.problems);
    status((r.problems || []).length ? r.problems[r.problems.length - 1]
           : here ? 'this notebook also changed on disk. Your text stays until you save'
                  : (r.note || 'answered'),
           r.ok && !here && !(r.problems || []).length ? 'ok' : 'err');
    markDirty();
    leeVars();
  } catch (e) {
    if (e?.name === 'AbortError') { const n = lee.cells.indexOf(cur()); status(n < 0 ? 'prompt cell stopped' : `prompt cell ${n + 1} stopped`, 'ok'); }
    else status(String(e.message || e), 'err');
  }
  finally {
    lee.promptRuns?.delete(cellId);
    if (clock) clearInterval(clock);
    const at = cur() || c;
    if (at.execution_ms == null) at.execution_ms = performance.now() - began;
    if (cur()) setCellTime(at, at.execution_ms, false);
    if (notice) notice.hidden = true;
  }
  if (cur()) $('#g-' + cellId).textContent = '✦';
  el?.classList.remove('running');
}
/* The shared slide renderer: one 1280x720 canvas that the presenter screen in the IDE and the audience window draw the same way.
   It reads no global of the IDE page: each input is an argument. The audience page loads it alone as `lee-slides.js`, and it posts nothing. */
const SLIDES_TAGS = new Set('p pre code span div b i em strong br hr h1 h2 h3 h4 h5 h6 table thead tbody tr th td ul ol li img figure figcaption blockquote sup sub del s kbd a'.split(' '));
const SLIDES_GONE = new Set('script style svg math iframe object embed template noscript textarea title select button'.split(' '));
const SLIDES_DATA = /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]*$/;
//: Leela's own class names: a notebook that used them could cover the slide with the blank screen or the IDE's chrome.
const SLIDES_OURS = /^(lee-|stage-|rk)/;
//: The body is 28px; the fit shrinks it to 20px and stops.
const SLIDES_FLOOR = 20/28;
//: rupaka's sizes are fixed px for a reading page; on a slide a demo takes the slide's text size and Leela's colours, in both windows.
const SLIDES_RK = `:host{display:block}.rk{font-size:inherit;line-height:1.45;max-width:100%;font-family:var(--lee-sans)}.rk-title{font-size:1.1em}
.rk button,.rk-gate textarea,.rk-gate .verdict,.rk-note{font:inherit}.rk button{padding:.3em .6em;line-height:1.2}.rk-gate .verdict .stale{font-size:inherit}
.rk-lbl,.rk-slider output,.rk kbd{font-size:.85em;letter-spacing:normal;text-transform:none}.rk kbd{font-size:.6em;color:var(--lee-fg2)}.rk-lbl{color:var(--lee-fg)}.rk-note,.rk-gate .note{color:var(--lee-fg2)}
.rk-slider input{font-size:inherit;max-width:24em;accent-color:var(--lee-accent)}.rk-gate{border-color:var(--lee-border)}.rk-gate .verdict .ok{color:var(--lee-green)}`;
//: The room copy has no keys to press, no box to type in and no gate button: an explanation shows as text, an empty one not at all.
const SLIDES_ROOM = `.rk kbd,.rk-gate .acts{display:none}.rk-gate textarea{border:0;padding:0;resize:none;background:none;color:var(--lee-fg);overflow:hidden}.rk-gate textarea.lee-empty{display:none}`;

//: Server HTML as a fragment with only the tags, classes, links and image sources a slide may have; `key` names the images of this presentation.
function slidesSafe(html, key = '') {
  const doc = new DOMParser().parseFromString(`<!doctype html><body>${html || ''}</body>`, 'text/html'), out = document.createDocumentFragment();
  const own = key && /^[0-9a-f]+$/.test(key) ? new RegExp(`^/present/img/[0-9a-f]{64}\\?k=${key}$`) : null;
  const walk = (from, to) => {
    for (const n of from.childNodes) {
      if (n.nodeType === 3) { to.append(n.textContent); continue; }
      if (n.nodeType !== 1) continue;
      const t = n.localName;
      if (SLIDES_GONE.has(t)) continue;
      if (!SLIDES_TAGS.has(t)) { walk(n, to); continue; }
      const el = document.createElement(t), cls = (n.getAttribute('class') || '').split(/\s+/).filter(c => c && !SLIDES_OURS.test(c));
      if (cls.length) el.className = cls.join(' ');
      if (t === 'img') {
        const src = (n.getAttribute('src') || '').trim();
        if (!SLIDES_DATA.test(src) && !own?.test(src)) continue;
        el.setAttribute('src', src);
        for (const a of ['width', 'height']) if (/^\d{1,5}$/.test(n.getAttribute(a) || '')) el.setAttribute(a, n.getAttribute(a));
        if (n.getAttribute('alt')) el.alt = n.getAttribute('alt');
      }
      if (t === 'a' && /^(https?:|mailto:)/i.test((n.getAttribute('href') || '').trim()))
        for (const [a, v] of [['href', n.getAttribute('href').trim()], ['target', '_blank'], ['rel', 'noopener noreferrer']]) el.setAttribute(a, v);
      walk(n, el); to.append(el);
    }
  };
  walk(doc.body, out);
  return out;
}

//: Shrink the text of canvas `el` in steps until it fits, down to the floor; `{fits}`.
function slidesFit(el) {
  let f = 1; el.style.setProperty('--slide-fit', 1);
  const over = () => el.scrollHeight > el.clientHeight + 1;
  while (over() && f > SLIDES_FLOOR) el.style.setProperty('--slide-fit', f = Math.max(SLIDES_FLOOR, f - .04));
  return {fits: !over()};
}

/* Draw slide `i` of `deck` at `step` into canvas `el`: a block shows when its fragment group is below `step`; a later one keeps its place, hidden.
   `mount(spec, id)` turns each demo into a host; `math(el)` fills the formulas; `outs` maps a code cell to the room output of its last run, in place of
   the deck's. Only the body is redrawn, so the laser dot and the blank screen stay. */
function slidesDraw(el, deck, i, step, {key = '', size = 10, mount = null, math = null, outs = null} = {}) {
  const s = deck?.slides?.[i], body = document.createElement('div');
  body.className = 'lee-slide-body';
  el.style.setProperty('--slide-size', size/10);
  for (const b of s?.blocks || []) {
    const box = body.appendChild(document.createElement('div'));
    box.className = `lee-block ${b.kind}${b.frag >= step ? ' lee-frag-hidden' : ''}`; box.dataset.cell = b.cell;
    box.append(slidesSafe(b.html, key));
    if (b.kind === 'code') box.appendChild(Object.assign(document.createElement('div'), {className: 'lee-out'})).append(slidesSafe(outs && Object.hasOwn(outs, b.cell) ? outs[b.cell] : b.out, key));
    if (!mount) continue;
    [...box.querySelectorAll('pre > code.language-rupaka')].forEach((code, n) => {
      let spec; try { spec = JSON.parse(code.textContent); } catch { return; }
      const host = mount(spec, `${b.cell}:${n}`); if (host) code.parentElement.replaceWith(host);
    });
  }
  el.querySelector(':scope > .lee-slide-body')?.remove();
  el.prepend(body);
  math?.(body);
  return slidesFit(el);
}

//: Output `html` in the box of code cell `cell` on canvas `el`, then the fit again; `{fits}`, or null when that cell is not on the slide drawn.
function slidesOut(el, cell, html, key = '') {
  const box = [...el.querySelectorAll(':scope > .lee-slide-body > .lee-block.code')].find(b => b.dataset.cell === cell)?.querySelector(':scope > .lee-out');
  if (!box) return null;
  box.replaceChildren(slidesSafe(html, key));
  return slidesFit(el);
}
//: Whether output `m` of a run is newer than `old`: a later run `gen`, or a later `seq` of the same run.
const slidesNewer = (m, old) => !old || m.gen > old.gen || m.gen === old.gen && m.seq > old.seq;
//: The room output of each code cell in `outs` (`{cell: {html}}`), as `slidesDraw` takes it.
const slidesHtml = outs => Object.fromEntries(Object.entries(outs).map(([c, o]) => [c, o.html]));

//: The slide sizes on a demo's shadow root `root`, after the sheets it has; `room` adds the rules of the room copy.
function slidesRk(root, room = false) {
  const css = SLIDES_RK + (room ? SLIDES_ROOM : '');
  if (!('adoptedStyleSheets' in root)) return root.append(Object.assign(document.createElement('style'), {textContent: css}));
  const s = (slidesRk.sheets ||= {})[css] ||= new CSSStyleSheet();
  if (!s.cssRules.length) s.replaceSync(css);
  if (!root.adoptedStyleSheets.includes(s)) root.adoptedStyleSheets = [...root.adoptedStyleSheets, s];
}
//: Mark each empty explanation box of a room demo, so the room does not see an empty field.
const slidesWhy = inner => inner.querySelectorAll('.rk-gate textarea').forEach(t => t.classList.toggle('lee-empty', !t.value.trim()));

//: A room demo in a shadow root with rupaka's CSS and the slide's sizes, mounted as `rupakaDraw` mounts it in the IDE; `{host, inner}`.
function slidesMount(spec) {
  const host = Object.assign(document.createElement('div'), {className: 'lee-rupaka'}), inner = document.createElement('div'), root = host.attachShadow({mode: 'open'});
  const css = document.querySelector('meta[name="lee-rupaka-css"]')?.content;
  if (css) root.append(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: css}));
  root.append(inner); slidesRk(root, true);
  try { window.Rupaka.mount(inner, spec, {askable: false}); slidesWhy(inner); } catch (e) { inner.textContent = `This demo could not be drawn: ${e.message || e}`; }
  return {host, inner};
}

//: Fit the 1280x720 canvas inside `root` at the largest scale that shows all of it.
function slidesScale(root) {
  const fit = () => root.style.setProperty('--slide-scale', Math.min(root.clientWidth/1280, root.clientHeight/720) || 1);
  fit(); new ResizeObserver(fit).observe(root);
}

//: Leela's theme `family:mode:density` on `html`, following the system for `system`, and the editor font as `--lee-mono`.
function slidesTheme(theme, mono = '') {
  const [family = 'cursor', mode = 'light', density = 'tight'] = String(theme || '').split(':'), root = document.documentElement;
  const q = slidesTheme.q ||= matchMedia('(prefers-color-scheme: dark)');
  const paint = () => { const m = mode === 'system' ? (q.matches ? 'dark' : 'light') : mode; Object.assign(root.dataset, {theme: family, mode: m, density}); root.style.colorScheme = m; };
  q.onchange = paint; paint();
  if (mono) root.style.setProperty('--lee-mono', `${mono}, ui-monospace, monospace`);
}

//: KaTeX for the formulas of `el`, loaded from the page's own copy the first time a slide has one.
function slidesMath(el) {
  const todo = [...el.querySelectorAll('span.math, div.math')];
  if (!todo.length) return;
  const meta = n => document.querySelector(`meta[name="${n}"]`)?.content;
  slidesMath.p ||= new Promise(ok => {
    if (window.katex) return ok(window.katex);
    document.head.append(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: meta('lee-katex-css')}));
    document.head.append(Object.assign(document.createElement('script'), {src: meta('lee-katex-src'), onload: () => ok(window.katex), onerror: () => ok(null)}));
  });
  slidesMath.p.then(k => k && todo.forEach(m => { try { k.render(m.textContent, m, {displayMode: m.classList.contains('display'), throwOnError: false, trust: false}); } catch {} }));
}

//: The audience window waits this long before it asks again after a failure, doubling from the first to the most.
const SLIDES_WAIT = [1000, 15000];
/* The audience window: the room copy and the room stream, with abhyasa's `stage.js` for the laser dot, the blank screen and the mirrored demos.
   The audience key stays in the address, because a reload asks the server for the page with it. It uses GET only. One room stream at a time,
   one retry at a time with a growing wait, and nothing after the end. */
function slidesAudience() {
  const k = new URLSearchParams(location.search).get('k') || '';
  // a window the IDE opened gets a copy of the IDE tab's storage, the presenter record among it
  for (const n of Object.keys(sessionStorage)) if (n.startsWith('lee-present:')) sessionStorage.removeItem(n);
  sessionStorage.setItem('lee-present-k', k);
  const root = document.body.appendChild(Object.assign(document.createElement('div'), {className: 'lee-stage'}));
  const canvas = root.appendChild(Object.assign(document.createElement('div'), {className: 'lee-slide'}));
  const q = `?k=${encodeURIComponent(k)}`, demos = new Map(), fns = {};
  let deck = null, at = {slide: 's1', step: 0, blank: false, size: 10}, held = {demo: {}, answers: {}, outs: {}}, es = null, stage = null, done = false;
  let boot = '', wait = 0, timer = 0;
  slidesScale(root);
  const name = () => String(deck?.title || '').replace(/\.ipynb$/i, '');
  const card = (text, title = name()) => {
    done = true; es?.close(); es = null; clearTimeout(timer); stage?.stop();
    const c = Object.assign(document.createElement('div'), {className: 'lee-end'});
    c.append(Object.assign(document.createElement('h1'), {textContent: text}));
    if (title) c.append(Object.assign(document.createElement('p'), {textContent: title}));
    root.replaceChildren(c);
  };
  const ended = (b = '') => card('The presentation has ended.', b && boot && b !== boot ? 'Leela restarted. The presenter can start again.' : name());
  // only the server's 403 means a bad link and its 410 the end; any other failure asks again later
  const ask = then => fetch('/present/deck' + q).then(r => {
    if (done) return;
    if (r.status === 410) return ended(r.headers.get('X-Leela-Boot') || '');
    if (r.status === 403) return card('This presentation link is not valid.');
    return r.ok ? then(r) : again(then);
  }).catch(() => again(then));
  const again = then => {
    if (done || timer) return;
    timer = setTimeout(() => { timer = 0; ask(then); }, wait);
    wait = Math.min(SLIDES_WAIT[1], wait ? wait*2 : SLIDES_WAIT[0]);
  };
  const ch = {on(t, f) { (fns[t] ||= []).push(f); return () => { fns[t] = fns[t].filter(x => x !== f); }; }, send() {}, close() {}};
  const emit = m => { m = {v: 1, ...m}; if (abhyasaStage.valid(m)) for (const f of fns[m.t] || []) f(m); };
  const show = (d, slug) => {
    if (!d.mirror) return;
    const s = held.demo[slug], a = held.answers[slug];
    try { d.mirror.apply(s?.state || {}, s?.gates || {}, s?.pick || {}); if (a) d.mirror.reveal(a.gates); else d.mirror.forget(); } catch {}
    slidesWhy(d.inner);
  };
  const mount = (spec, id) => {
    let d = demos.get(id);
    if (!d) {
      d = {...slidesMount(spec), slug: spec.id};
      try { d.mirror = abhyasaStage.mirror(d.inner); } catch {}
      demos.set(id, d);
    }
    return d.host;
  };
  const draw = () => {
    if (done || !deck) return;
    const i = Math.max(0, Math.min(deck.slides.length - 1, +at.slide.slice(1) - 1));
    slidesDraw(canvas, deck, i, at.step, {key: k, size: at.size, mount, math: slidesMath, outs: slidesHtml(held.outs)});
    for (const d of demos.values()) if (canvas.contains(d.host)) show(d, d.slug);
  };
  // a demo state drops the answers of each gate it does not list as done, as the server does, so a reopened gate never shows an old answer
  const keep = m => {
    const a = m.t === 'demo' && held.answers[m.slug], g = a && Object.fromEntries(Object.entries(a.gates).filter(([id]) => m.gates[id] === 'done'));
    if (a) { if (Object.keys(g).length) held.answers[m.slug] = {...a, gates: g}; else delete held.answers[m.slug]; }
    held[m.t][m.slug] = m; for (const d of demos.values()) if (d.slug === m.slug && canvas.contains(d.host)) show(d, d.slug);
  };
  const on = {
    state: d => { wait = 0; at = d.at; held = {demo: Object.fromEntries(d.demo.map(x => [x.slug, {t: 'demo', ...x}])), answers: Object.fromEntries(d.answers.map(x => [x.slug, {t: 'answers', ...x}])),
                                  outs: Object.fromEntries((d.outs || []).map(x => [x.cell, x]))};
                  slidesTheme(d.look?.theme, deck.look?.mono); emit({t: 'point', off: true}); emit({t: 'blank', on: !!at.blank}); draw(); },
    at: d => { if (d.slide !== at.slide) held.answers = {}; at = d; emit({t: 'go', slide: d.slide, beat: Math.min(50, d.step + 1)}); emit({t: 'blank', on: !!d.blank}); },
    point: d => emit({t: 'point', ...d}),
    demo: d => emit({t: 'demo', ...d}),
    answers: d => emit({t: 'answers', ...d}),
    look: d => slidesTheme(d.theme, deck.look?.mono),
    out: d => { if (!slidesNewer(d, held.outs[d.cell])) return; held.outs[d.cell] = d; if (!done && deck) slidesOut(canvas, d.cell, d.html, k); },
    end: () => emit({t: 'end'}),
  };
  // the browser connects an open stream again by itself; a closed one is asked about first, so a 403 or 410 shows its card
  const listen = () => {
    if (done) return;
    es?.close();
    const s = es = new EventSource('/present/room' + q);
    for (const [t, f] of Object.entries(on)) s.addEventListener(t, e => { if (s === es) try { f(JSON.parse(e.data)); } catch {} });
    s.onerror = () => { if (s === es && s.readyState === EventSource.CLOSED) again(listen); };
  };
  addEventListener('keydown', e => { if (e.code === 'KeyF' && !e.metaKey && !e.ctrlKey && !e.altKey) document.documentElement.requestFullscreen?.().catch(() => {}); });
  addEventListener('dblclick', () => document.documentElement.requestFullscreen?.().catch(() => {}));
  const load = async r => {
    boot = r.headers.get('X-Leela-Boot') || '';
    try { deck = await r.json(); } catch { return again(load); }
    document.title = name() || 'Presentation';
    slidesTheme(deck.look?.theme, deck.look?.mono);
    stage = abhyasaStage.audience(canvas, {ch, title: name(), draw: m => m.t === 'go' ? draw() : m.t === 'end' ? ended() : (m.t === 'demo' || m.t === 'answers') && keep(m)});
    listen();
  };
  ask(load);
}

if (typeof document !== 'undefined' && document.body?.dataset.page === 'audience') slidesAudience();
/* The open notebook presented as slides. Cells group the way RISE groups them, from `metadata.slideshow.slide_type`, into one line.
   The server builds the presenter copy and the room copy; `slides.js` draws them; each move goes to the server, which sends it to the audience windows. */
const PRESENT_NOT_NOTEBOOK = 'only a notebook can be presented as slides';
const PRESENT_NOTHING = 'this notebook has nothing to present: every cell is empty or skipped';
const PRESENT_KINDS = new Set(['markdown', 'code', 'raw', 'prompt']);
//: A start the server refused because the notebook is too large to send.
const PRESENT_LARGE = /characters of (output|source)|larger than 32 MB|at most 2,000 cells/;
const PRESENT_GONE = /^This presentation (has ended|link is not valid)\.$/;
const PRESENT_HINT = 'Move the audience window to the projector. In that window, press F for full screen.';
const PRESENT_ENDED = 'This presentation has ended.', PRESENT_RESTARTED = 'Leela restarted, so the presentation stopped.';
const PRESENT_AWAY = 'Leela is not reachable, so the presentation is closed on this screen. Reload this page to try again.';
//: This tab's presenter record lives in `sessionStorage` under the presentation id, so another IDE tab never gets the key by itself.
const PRESENT_REC = 'lee-present:';
//: Laser points go at most once in this many ms, one at a time behind the other posts; the dot fades as `stage.js` fades it; Esc this soon after full screen ends is the browser's.
const PRESENT_POINT_MS = 33, PRESENT_FADE = 1500, PRESENT_FULL_MS = 400;
//: What Space or Enter presses by itself when it has focus.
const PRESENT_PRESSES = 'button, summary, [role="button"], input[type="checkbox"], input[type="radio"], input[type="button"], input[type="submit"], input[type="reset"]';
const presentClamp = v => Math.round(Math.min(1, Math.max(0, v))*1e4)/1e4;

//: The text scale after one press of A- (`d = -1`) or A+ (`d = 1`): tenths, from half to two and a half.
const presentStep = (s, d) => Math.min(2.5, Math.max(.5, Math.round((s + d/10)*10)/10));
const presentKey = (what = 'text') => `lee-present-${what}:${lee.path || lee.tabKey}`;
function presentStored() {
  try { const s = +localStorage.getItem(presentKey()); return s >= .5 && s <= 2.5 ? s : 1; } catch { return 1; }
}

//: Whether markdown text has an H2 line outside a backtick or tilde fence.
function presentH2(s) {
  let fence = '';
  for (const l of s.split(/\r?\n/)) {
    const m = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(l);
    if (fence) { if (m && m[1][0] === fence[0] && m[1].length >= fence.length && !m[2].trim()) fence = ''; }
    else if (m && !(m[1][0] === '`' && m[2].includes('`'))) fence = m[1];
    else if (/^ {0,3}##(?:[ \t]|$)/.test(l)) return true;
  }
  return false;
}

/* `[[slide, ...subslides], ...]`, each slide `{items: [{i, frag}], notes: [i]}` with `i` an index
   into `cells`. `src` reads a cell's text, so unsaved edits are what gets presented. With no `slide`
   or `subslide` cell, a markdown cell with an H2 line opens a slide; with no H2 either, each cell does. */
function presentSlides(cells, src = c => String(c.source || '')) {
  const kind = c => c.extra?.slideshow?.slide_type, ok = c => c.approval == null;
  // only a slide boundary makes unmarked cells continue a slide; a skip or notes mark alone does not
  const typed = cells.some(c => ok(c) && (kind(c) === 'slide' || kind(c) === 'subslide'));
  const heads = typed ? [] : cells.map(c => ok(c) && c.cell_type === 'markdown' && presentH2(src(c))), byH2 = heads.some(Boolean);
  const deck = []; let stack = null, slide = null;
  const open = sub => { slide = {items: [], notes: [], frag: -1}; if (!sub || !stack) deck.push(stack = []); stack.push(slide); };
  cells.forEach((c, i) => {
    if (!ok(c)) return;
    const k = kind(c), t = byH2 && (!k || k === '-') ? (heads[i] ? 'slide' : '-') : k || (typed ? '-' : 'slide');
    if (t === 'skip') return;
    const empty = !src(c).trim() && !(c.outputs || []).length && !c.reply;
    if (t === 'slide' || t === 'subslide') open(t === 'subslide');
    else if (!slide) open(false);
    if (empty) return;
    if (t === 'notes') return void slide.notes.push(i);
    if (t === 'fragment') slide.frag++;
    slide.items.push({i, frag: slide.frag});
  });
  return deck.map(s => s.filter(x => x.items.length || x.notes.length)).filter(s => s.length);
}

//: Where cell `i` is in the grouped deck, or the nearest visible cell above it: slide `h`, subslide `v`, fragment `f`.
function presentAt(deck, i) {
  for (let j = i; j >= 0; j--)
    for (const [h, stack] of deck.entries()) for (const [v, s] of stack.entries()) {
      const it = s.items.find(x => x.i === j); if (it) return {h, v, f: it.frag};
    }
  return {h: 0, v: 0, f: -1};
}

//: The most fragment groups a slide shows: stage `go.beat` is one plus the groups shown, at most 50.
const PRESENT_GROUPS = 49;
/* The deck as one line `[{items: [{i, frag}], notes: [i], groups, warn}]`: subslides in order, a notes-only
   slide's notes on the next slide with items (on the last one at the end), groups past the 49th in the 49th. */
function presentLine(deck) {
  const line = []; let held = [];
  for (const s of deck.flat()) {
    if (!s.items.length) { held.push(...s.notes); continue; }
    const top = s.items.reduce((m, x) => Math.max(m, x.frag), -1);
    line.push({items: s.items.map(({i, frag}) => ({i, frag: Math.min(frag, PRESENT_GROUPS - 1)})), notes: [...held, ...s.notes],
               groups: Math.min(top + 1, PRESENT_GROUPS), warn: top >= PRESENT_GROUPS});
    held = [];
  }
  if (line.length) line.at(-1).notes.push(...held);
  return line;
}
//: `{slide, step}` where cell `i` shows, or the nearest visible cell above it; a fragment's own group is not yet shown.
function presentPlace(line, i) {
  const at = new Map(line.flatMap((s, slide) => s.items.map(x => [x.i, {slide, step: Math.max(0, x.frag)}])));
  for (let j = i; j >= 0; j--) if (at.has(j)) return at.get(j);
  return {slide: 0, step: 0};
}
//: One fragment group forward (`d = 1`) or back (`d = -1`), else the next slide at its start or the previous one in full.
function presentMove(line, {slide, step}, d) {
  const s = line[slide]; if (!s) return {slide: 0, step: 0};
  if (d > 0) return step < s.groups ? {slide, step: step + 1} : slide + 1 < line.length ? {slide: slide + 1, step: 0} : {slide, step};
  if (d < 0) return step > 0 ? {slide, step: step - 1} : slide > 0 ? {slide: slide - 1, step: line[slide - 1].groups} : {slide, step};
  return {slide, step};
}


//: The one RISE setting Leela reads: where the presentation starts. Every other `rise` key is ignored.
function riseConfig(rise) {
  const r = rise && typeof rise === 'object' && !Array.isArray(rise) ? rise : {};
  return {start: r.start_slideshow_at === 'beginning' ? 'beginning' : 'selected'};
}
const presentError = m => { try { return JSON.parse(m).error || m; } catch { return m; } };
const presentRefused = e => PRESENT_LARGE.test(e.message || '') ? `${e.message} Clear large outputs, then try again.` : `slides could not start: ${e.message || e}`;
const presentAtBody = p => ({slide: `s${p.at.slide + 1}`, step: p.at.step, blank: p.blank, size: Math.round(p.text*10)});
const presentIndex = at => ({slide: +String(at.slide).slice(1) - 1, step: at.step});
//: Place `at` moved onto `line`: a slide past the end is the last one, a step past the groups is the last group.
function presentNear(line, at) {
  const slide = Math.max(0, Math.min(line.length - 1, at.slide | 0));
  return {slide, step: Math.max(0, Math.min(line[slide].groups, at.step | 0))};
}
//: Whether code cell `id` no longer matches the stored deck: gone from the open notebook, or edited since the start. Task 7 disables Run for it.
const presentStale = (p, id) => { const c = (lee.cells || []).find(x => x.id === id); return !c || !Object.hasOwn(p.src, id) || mdSource(c) !== p.src[id]; };
const presentTheme = () => lee.theme ? `${lee.theme.family}:${lee.theme.mode}:${lee.theme.density}` : '';

function presentSay(text) {
  const m = lee.present && $('.lee-present-msg', lee.present.root); if (!m) return;
  m.textContent = text; m.hidden = !text;
  clearTimeout(m._leeTimer); if (text) m._leeTimer = setTimeout(() => { m.hidden = true; }, 6000);
}
//: Post to the server in order with this presenter's other posts; a refused key closes the presenter screen.
function presentPost(p, url, body = {}, always = false) {
  return p.chain = p.chain.then(() => (always || lee.present === p) && post(url, {...body, k: p.key})).catch(e => {
    if (lee.present !== p) return;
    if (e.message === PRESENT_ENDED) { closePresentation(); presentGone(p); }
    else if (PRESENT_GONE.test(e.message || '')) { closePresentation(); presentForget(p.id); status(PRESENT_ENDED, 'err'); }
    else presentSay('Moves are not reaching the audience window.');
  });
}
//: Post the place; the server's reply is the place a reload of this tab promises.
const presentGo = p => presentPost(p, '/present/at', presentAtBody(p)).then(r => { if (r?.at && lee.present === p) { p.acked = presentIndex(r.at); presentKeep(p); } });

function presentRecs() {
  try { return Object.keys(sessionStorage).filter(n => n.startsWith(PRESENT_REC)).map(n => ({...JSON.parse(sessionStorage.getItem(n)), id: n.slice(PRESENT_REC.length)})); }
  catch { return []; }
}
//: Keep `p`'s key, boot, notebook and last acknowledged place for a reload of this tab; the history entry keeps the same without the key, for a tab whose storage was cleared.
function presentKeep(p) {
  const rec = JSON.stringify({key: p.key, boot: p.boot, path: p.path, at: p.acked}); if (rec === p.kept) return;
  p.kept = rec;
  try { for (const r of presentRecs()) if (r.id !== p.id) sessionStorage.removeItem(PRESENT_REC + r.id); sessionStorage.setItem(PRESENT_REC + p.id, rec); } catch {}
  try { history.replaceState({...history.state, leePresent: {id: p.id, path: p.path, at: p.acked}}, ''); } catch {}
}
function presentForget(id) {
  try { sessionStorage.removeItem(PRESENT_REC + id); } catch {}
  try { if (history.state?.leePresent?.id === id) { const {leePresent, ...s} = history.state; history.replaceState(s, ''); } } catch {}
}
//: A presenter POST that tells a refusal from a network failure: `{ok, status, body, boot}`. A network failure throws.
async function presentAsk(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  return {ok: r.ok, status: r.status, body: await r.json().catch(() => ({})), boot: r.headers.get('X-Leela-Boot') || ''};
}
//: The live presentation `{id, boot, holder}` from the first event of `/present/events`; null when the server does not answer in 5 s.
const presentLive = () => new Promise(ok => {
  const es = new EventSource('/present/events'), t = setTimeout(() => { es.close(); ok(null); }, 5000);
  es.addEventListener('presentation', e => { clearTimeout(t); es.close(); try { ok(JSON.parse(e.data)); } catch { ok(null); } });
});

//: At page load. A reload of this tab brings its presenter screen back from the server's state; a tab that copied the record asks first; a tab that lost its key says so.
async function presentResume() {
  const rec = presentRecs()[0], mark = history.state?.leePresent;
  if (!rec) return mark?.id && presentLost(mark);
  if (performance.getEntriesByType?.('navigation')[0]?.type === 'reload') return presentRecover(rec);
  if ((await presentLive())?.id !== rec.id) return presentForget(rec.id);
  const take = await confirmDialog('Present from this tab?', 'This presentation is open in another tab. Take over to control it from this tab. The other tab stops presenting.', 'Take over');
  take ? presentRecover(rec) : presentForget(rec.id);
}
async function presentRecover(rec) {
  const ticket = lee.presentTicket = (lee.presentTicket || 0) + 1;
  let r; try { r = await presentAsk('/present/resume', {k: rec.key}); } catch { return status(PRESENT_AWAY, 'err'); }
  if (ticket !== lee.presentTicket || lee.present) return;
  if (r.ok) return presentOpen(r.body, false, rec.path);
  presentForget(rec.id);
  if (r.status === 410) presentAgain(rec, !!r.boot && r.boot !== rec.boot);
}
//: The server holds no presentation for `p`: ask once with its key; only a confirmed 410 offers Start again, never a network failure.
async function presentGone(p) {
  const m = {id: p.id, key: p.key, boot: p.boot, path: p.path, at: p.acked};
  let r; try { r = await presentAsk('/present/resume', {k: m.key}); } catch { return status(PRESENT_AWAY, 'err'); }
  if (r.ok) return lee.present || presentOpen(r.body, false, m.path);
  presentForget(m.id);
  if (r.status === 410) return presentAgain(m, !!r.boot && r.boot !== m.boot);
  status('Another presentation started.', 'err');
}
async function presentAgain(m, restarted) {
  status(restarted ? PRESENT_RESTARTED : PRESENT_ENDED, 'err');
  const why = restarted ? 'The presentation stopped when Leela restarted.' : 'The server no longer holds this presentation.';
  if (await confirmDialog(restarted ? 'Leela restarted' : 'The presentation has ended',
    `${why} Start again to present from slide ${(m.at?.slide || 0) + 1}. The audience window must open again.`, 'Start again')) presentRestart(m);
}
async function presentLost(mark) {
  if ((await presentLive())?.id !== mark.id) return presentForget(mark.id);
  const go = await confirmDialog('This tab lost its presenter key', 'The presentation is still running, but this tab can no longer control it. ' +
    `Start again to present from slide ${(mark.at?.slide || 0) + 1} in this tab. This ends the running presentation, and the audience window must open again.`, 'Start again');
  presentForget(mark.id);
  if (go) presentRestart(mark);
}
//: A new presentation of notebook `m.path`, from the live cells, at its last acknowledged place.
async function presentRestart(m) {
  if (m.path && m.path !== (lee.path || lee.tabKey)) try { await leeOpenFile(m.path); } catch (e) { return status(String(e.message || e), 'err'); }
  presentNotebook(m.at || '');
}
//: What `/present/events` says on each connect and for each new holder: another id or another holder closes this presenter screen at once.
function presentCheck(p, d) {
  if (lee.present !== p || d.id === p.id && (!d.holder || d.holder === p.holder)) return;
  closePresentation();
  if (d.id === p.id) { presentForget(p.id); return status('The presentation moved to another tab.', 'err'); }
  if (d.id) { presentForget(p.id); return status('Another presentation started.', 'err'); }
  presentGone(p);
}
//: Post the body `make()` gives, `[url, body]` or null, for `slot`: one post of a slot in the chain at a time, and only the newest of those that wait; `then` gets the reply.
function presentLatest(p, slot, make, then) {
  const s = (p.slots ||= {})[slot] ||= {busy: false, next: null};
  s.next = {make, then};
  if (!s.busy) presentDrain(p, s);
}
function presentDrain(p, s) {
  const m = s.next; if (!m) return;
  s.next = null;
  const b = m.make(); if (!b) return presentDrain(p, s);
  s.busy = true;
  presentPost(p, ...b).then(r => { s.busy = false; m.then?.(r); presentDrain(p, s); });
}
//: Post the newest outputs of run `gen` of code cell `id`; a run from before the last kernel restart sends nothing. `seq` counts the posts of one run.
function presentOut(p, id, gen, outputs, done) {
  const q = p.outq[id] ||= {gen: 0, seq: 0};
  if (gen <= p.floor || gen < q.gen) return;
  presentLatest(p, 'out:' + id, () => {
    if (gen <= p.floor || gen < q.gen) return null;
    if (gen !== q.gen) { q.gen = gen; q.seq = 0; }
    return ['/present/out', {cell: id, gen, seq: ++q.seq, outputs, done}];
  }, r => { if (r?.msg && lee.present === p && gen > p.floor) presentShown(p, id, r, done, gen); });
}
//: The room copy the server made of a run's outputs, drawn on the presenter screen too; a finished run that failed opens the private error panel.
function presentShown(p, id, r, done, gen) {
  if (!slidesNewer(r.msg, p.outs[id])) return;
  p.outs[id] = r.msg; presentBox(p, id);
  if (done && r.error) presentErr(p, {cell: id, gen, ...r.error});
  else if (done && p.err?.cell === id) presentErr(p, null);
}
function presentBox(p, id) {
  const f = slidesOut(p.canvas, id, p.outs[id]?.html || '', p.ak);
  if (f && !f.fits) presentSay(`Slide ${p.at.slide + 1} has more than fits. Split it or trim it.`);
}
//: The private error panel for error `e` of a run, `{cell, gen, ename, evalue, traceback}`, or closed for null.
function presentErr(p, e) {
  const box = $('.lee-present-err', p.root); p.err = e; if (!box) return;
  if (!e && box.contains(document.activeElement)) p.root.focus({preventScroll: true});
  box.hidden = !e; if (!e) return;
  $('[data-err-sum]', box).textContent = `${e.ename}: ${e.evalue}`;
  $('[data-err-tb]', box).textContent = (e.traceback || []).join('\n');
}
//: Show error: the server sends the error to the room only while run `gen` is the last run of the cell.
function presentShowError(p) {
  const e = p.err; if (!e) return;
  presentPost(p, '/present/show-error', {cell: e.cell, gen: e.gen}).then(r => {
    if (lee.present !== p || !r) return;
    if (p.err === e) presentErr(p, null);
    if (r.stale) return presentSay('A newer run of this cell replaced that error.');
    if (slidesNewer(r.msg, p.outs[e.cell])) { p.outs[e.cell] = r.msg; presentBox(p, e.cell); }
    presentSay('The audience window shows the error.');
  });
}
//: The kernel restarted, died or was stopped by force: every code cell of the deck empty on both screens, no private error, and each older run stale.
function presentReset(p) {
  if (lee.present !== p) return;
  p.floor = p.gen = Math.max(p.gen, p.floor) + 1;
  for (const id of Object.keys(p.src)) p.outs[id] = {cell: id, gen: p.floor, seq: 0, html: ''};
  presentErr(p, null); p.draw();
  presentPost(p, '/present/clear', {gen: p.floor});
}
//: A run that ended with no count and no error: kunda settles the runs of a kernel that died that way.
const presentDied = c => !!c && c.execution_count == null && !(c.outputs || []).some(o => o.output_type === 'error');
//: Run the live text of code cell `id` with no save; its outputs stream to the room as it runs.
async function presentRun(p, id) {
  const i = lee.cells.findIndex(c => c.id === id);
  if (p.runs[id] || i < 0 || presentStale(p, id)) return presentStrip(p);
  const gen = p.gen = Math.max(p.gen, p.floor) + 1, run = p.runs[id] = {gen};
  if (p.err?.cell === id) presentErr(p, null);
  presentStrip(p);
  presentOut(p, id, gen, [], false);
  const r = await runCell(i, false, {save: false});
  if (p.runs[id] === run) delete p.runs[id];
  if (lee.present !== p) return;
  const c = lee.cells.find(x => x.id === id);
  if (r.ok && presentDied(c)) presentReset(p);
  else {
    presentOut(p, id, gen, c?.outputs || [], true);
    if (!r.ok && !(c?.outputs || []).some(o => o.output_type === 'error')) presentSay(presentError(r.error));
  }
  presentStrip(p);
}
//: A run the server still holds after a reload of this page: its final outputs from `/nb/run/state`, posted as the same run.
async function presentFollow(p, id, o) {
  const run = p.runs[id] = {gen: o.gen};
  p.outq[id] = {gen: o.gen, seq: o.seq};
  presentStrip(p);
  let s = null; try { s = await settleRun(p.path, id); } catch {}
  if (p.runs[id] === run) delete p.runs[id];
  if (lee.present !== p) return;
  if (s?.cell) presentOut(p, id, o.gen, s.cell.outputs || [], true);
  presentStrip(p);
}
//: Stop code cell `id` by the exact-cell path; a run that this page did not start, after a reload, goes to the same route.
async function presentStop(p, id) {
  const i = lee.cells.findIndex(c => c.id === id);
  try {
    if (lee.cells[i]?.running) return await stopCell(i);
    if ((await post('/nb/interrupt', {path: p.path, id})).forced) kernelRestarted();
  } catch (e) { presentSay(String(e.message || e)); }
}
//: Run and Stop for each code cell of the slide, in one group each: Stop shows while the cell runs and keeps its slot while idle, and Run is off while it runs or no longer matches the deck.
function presentStrip(p) {
  const s = p.deck.slides[p.at.slide] || {}, code = (s.blocks || []).filter(b => b.kind === 'code'), n = code.length > 1;
  const btn = (text, title, fn) => Object.assign(document.createElement('button'), {type: 'button', textContent: text, title, onclick: fn});
  $('[data-runs]', p.root).replaceChildren(...code.flatMap((b, j) => {
    const id = b.cell, on = !!p.runs[id], stale = presentStale(p, id), tag = n ? ` ${j + 1}` : '';
    const run = btn('Run' + tag, stale ? 'Run is off: this cell changed or left the notebook after the presentation started.' : 'Run this code cell', () => presentRun(p, id));
    const stop = btn('Stop' + tag, 'Stop this code cell', () => presentStop(p, id));
    run.dataset.run = stop.dataset.stop = id; run.disabled = on || stale; stop.hidden = !on;
    const g = Object.assign(document.createElement('span'), {className: 'lee-present-run'}); g.append(run, stop);
    return [g];
  }));
  if (document.activeElement === document.body && lee.present === p) p.root.focus({preventScroll: true});
}

//: The `demo` move of mirror snapshot `s` of demo `slug`: the stage fields only; null when it is over the 65536 units of a stage message.
function presentDemoMove(slug, s) {
  const m = {t: 'demo', slug, state: s.state, gates: s.gates, pick: s.pick};
  return JSON.stringify({v: 1, ...m}).length > 65536 ? null : m;
}
const presentGate = (inner, id) => [...inner.querySelectorAll('.rk-gate .q[id]')].find(q => q.id.endsWith(`-${id}-q`))?.closest('.rk-gate');
//: Presenter demo `d` mirrored to the room: the server's state first after a reload, one watch for the mount, a first snapshot, then each change.
function presentMirror(p, d) {
  try { d.mirror = abhyasaStage.mirror(d.inner); } catch { return; }
  presentHydrate(p, d);
  d.unwatch = d.mirror.watch(() => presentDemo(p, d));
  presentDemo(p, d);
}
/* The server's demo state on the presenter copy, which stays writable: its inputs, and each done gate settled with the pick. The mirror does not
   count a gate settled this way, so `d.kept` holds it as done while it stays closed. */
function presentHydrate(p, d) {
  d.kept = {gates: {}, pick: {}, answers: {}};
  const s = p.held.demo[d.slug], a = p.held.answers[d.slug]?.gates || {}; if (!s) return;
  try {
    const now = Rupaka.state(d.inner), keys = Object.keys(now).filter(k => Object.hasOwn(s.state, k) && JSON.stringify(now[k]) !== JSON.stringify(s.state[k]));
    if (keys.length) Rupaka.set(d.inner, Object.fromEntries(keys.map(k => [k, s.state[k]])));
    for (const [id, v] of Object.entries(s.gates)) {
      const os = Rupaka.options(d.inner, id) || [], i = s.pick?.[id], pick = Array.isArray(i) ? i.map(x => os[x]) : os[i];
      if (v === 'done' && Rupaka.settle(d.inner, id, pick ?? null)) Object.assign(d.kept, {gates: {...d.kept.gates, [id]: 'done'}, pick: i == null ? d.kept.pick : {...d.kept.pick, [id]: i},
                                                                             answers: a[id] ? {...d.kept.answers, [id]: a[id]} : d.kept.answers});
    }
  } catch {}
}
//: The mirror's snapshot of `d`, with each kept gate that is still closed.
function presentSnap(d) {
  const s = d.mirror.snapshot(), k = d.kept;
  for (const id of Object.keys(k.gates)) {
    const go = presentGate(d.inner, id)?.querySelector('button.go');
    if (go?.hidden && !s.gates[id]) { s.gates[id] = 'done'; if (k.pick[id] != null) s.pick[id] = k.pick[id]; }
    else { delete k.gates[id]; delete k.pick[id]; delete k.answers[id]; }
  }
  return s;
}
//: A changed snapshot of demo `d` as a `demo` move; its answers follow in a move of their own, after the server has the snapshot of the settled gate.
function presentDemo(p, d) {
  if (lee.present !== p || !d.mirror) return;
  const m = presentDemoMove(d.slug, presentSnap(d));
  if (!m || !abhyasaStage.valid({v: 1, ...m})) return presentSay('The demo is too large for the room screen.');
  const was = p.held.demo[d.slug], key = x => JSON.stringify([x.state, x.gates, x.pick || {}]);
  if (was && key(was) === key(m)) return p.slots?.['demo:' + d.slug]?.busy || presentAnswers(p, d);
  p.held.demo[d.slug] = m;
  const a = p.held.answers[d.slug], g = a && Object.fromEntries(Object.entries(a.gates).filter(([id]) => m.gates[id] === 'done'));
  if (a) { if (Object.keys(g).length) p.held.answers[d.slug] = {...a, gates: g}; else delete p.held.answers[d.slug]; }
  presentLatest(p, 'demo:' + d.slug, () => ['/present/move', m], () => presentAnswers(p, d));
}
//: The answers of the settled gates of demo `d` for the room, once the server holds those gates as done; never from `rk-predict` itself.
function presentAnswers(p, d) {
  if (lee.present !== p || !d.mirror || !p.canvas.contains(d.host)) return;
  const done = p.held.demo[d.slug]?.gates || {}, got = {...d.kept.answers, ...d.mirror.answers()};
  const gates = Object.fromEntries(Object.entries(got).filter(([id]) => done[id] === 'done'));
  if (!Object.keys(gates).length || JSON.stringify(p.held.answers[d.slug]?.gates) === JSON.stringify(gates)) return;
  const m = {t: 'answers', slide: `s${p.at.slide + 1}`, slug: d.slug, gates};
  if (!abhyasaStage.valid({v: 1, ...m})) return;
  p.held.answers[d.slug] = m;
  presentPost(p, '/present/move', m);
}
function presentEnd(p) { presentForget(p.id); lee.presentWait = presentPost(p, '/present/end', {}, true); closePresentation(); }

async function presentNotebook(start = '') {
  if (lee.kind !== 'notebook') return status(PRESENT_NOT_NOTEBOOK, 'err');
  const cells = lee.cells, line = presentLine(presentSlides(cells, mdSource));
  if (!line.length) return status(PRESENT_NOTHING, 'err');
  closePresentation();
  const ticket = lee.presentTicket = (lee.presentTicket || 0) + 1, name = lee.path || lee.tabKey;
  const at = typeof start === 'object' ? presentNear(line, start) : (start || riseConfig(lee.rise).start) === 'selected' ? presentPlace(line, lee.sel) : {slide: 0, step: 0};
  status('Preparing slides…');
  const body = {path: name, title: String(name).split('/').pop(), start: at, line: line.map(({items, notes, groups}) => ({items, notes, groups})),
    cells: cells.map(c => ({id: c.id, cell_type: PRESENT_KINDS.has(c.cell_type) ? c.cell_type : 'raw', source: mdSource(c), outputs: c.outputs || [],
      attachments: c.cell_type === 'markdown' && c.attachments || {}}))};
  // the server keeps the start whose body it reads last and refuses a start an end overtakes, so one start at a time, after the last end
  const sent = (lee.presentWait || Promise.resolve()).then(() => ticket === lee.presentTicket ? post('/present/start', body) : null);
  lee.presentWait = sent.catch(() => {});
  let r;
  try { r = await sent; } catch (e) { if (ticket === lee.presentTicket) status(presentRefused(e), 'err'); return; }
  if (!r || ticket !== lee.presentTicket || lee.present) return;
  status('');
  presentOpen(r, true, name);
}

const PRESENT_HTML = '<div class="lee-present-main"><div class="lee-stage"><div class="lee-slide"></div></div>' +
  '<aside class="lee-present-notes" id="lee-present-notes" aria-label="Speaker notes" hidden><div class="lee-present-notes-head"><h2>Speaker notes</h2>' +
  '<button type="button" data-close title="Close the notes (Esc)">Close</button></div>' +
  '<p class="lee-present-warn">The room can see these notes when you share this screen.</p>' +
  '<div data-notes-body></div><p data-upcoming></p><p data-clock></p></aside>' +
  '<div class="lee-present-err" role="alert" hidden><p data-err-sum></p><p class="lee-present-warn">The audience window does not show this error. The room can see it when you share this screen.</p>' +
  '<details><summary>Traceback</summary><pre data-err-tb></pre></details><div class="lee-present-err-acts">' +
  '<button type="button" data-show-error title="Show this error in the audience window">Show error to audience</button><button type="button" data-err-close title="Close (Esc)">Close</button></div></div>' +
  '<div class="lee-present-msg" role="status" hidden></div></div>' +
  '<div class="lee-present-strip" role="toolbar" aria-label="Presentation controls">' +
  '<span class="lee-present-group"><button type="button" data-prev title="Previous (Left arrow)">Previous</button><button type="button" data-next title="Next (Right arrow or Space)">Next</button>' +
  '<span data-where></span><span data-runs></span></span>' +
  '<span class="lee-present-group"><button type="button" data-audience title="Open a window to show on the projector">Audience window</button><span data-conn role="status">Audience window: not connected</span></span>' +
  '<span class="lee-present-group lee-present-tools"><button type="button" data-notes title="Notes (N)" aria-controls="lee-present-notes" aria-expanded="false">Notes</button>' +
  '<button type="button" data-smaller title="Smaller text" aria-label="Smaller text">A−</button><span data-size title="Body text size on the 1280 by 720 slide"></span>' +
  '<button type="button" data-bigger title="Larger text" aria-label="Larger text">A+</button>' +
  '<button type="button" data-full title="Full screen (F)">Full screen</button></span><span class="lee-gap"></span>' +
  '<button type="button" data-end title="End the presentation">End</button></div>';

/* The presenter screen for presentation `r` of notebook `path`, as the server holds it: place, blank, size, look, clock and the stored deck.
   A `fresh` start then posts this page's text size and theme; a resumed one posts nothing until the presenter acts. */
function presentOpen(r, fresh, path) {
  const root = Object.assign(document.createElement('div'), {className: 'lee-present', tabIndex: -1, innerHTML: PRESENT_HTML});
  root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'Presentation');
  const q = s => $(s, root), canvas = q('.lee-slide'), notes = q('.lee-present-notes'), strip = q('.lee-present-strip'), end = q('[data-end]'), notesBtn = q('[data-notes]');
  const dot = canvas.appendChild(Object.assign(document.createElement('div'), {className: 'stage-dot'}));
  dot.setAttribute('aria-hidden', 'true');
  canvas.appendChild(Object.assign(document.createElement('div'), {className: 'stage-blank', textContent: String(r.presenter?.title || '').replace(/\.ipynb$/i, '')}));
  const at = presentIndex(r.at), ide = presentTheme();
  const live = r.live || {}, outs = Object.values(live.outs || {});
  const p = lee.present = {root, canvas, key: r.key, ak: r.ak, id: r.id, boot: r.boot, holder: r.holder, path, src: r.src || {}, audience: r.audience, deck: r.presenter,
                           line: r.presenter.slides.map(s => ({groups: s.groups || 0})), at, acked: at, text: fresh ? presentStored() : r.at.size/10,
                           blank: !fresh && !!r.at.blank, outs: Object.fromEntries(outs.map(o => [o.cell, {cell: o.cell, gen: o.gen, seq: o.seq, html: o.html}])),
                           gen: Math.max(0, ...outs.map(o => o.gen)), floor: 0, runs: {}, outq: {}, err: null, held: {demo: {...live.demo}, answers: {...live.answers}},
                           demos: new Map(), slugs: new Set(r.presenter.slides.flatMap(s => (s.blocks || []).flatMap(b => (b.demo || []).map(x => x.id)))), chain: Promise.resolve(), started: Date.now() - (r.elapsed || 0)*1000, win: null,
                           ide, look: fresh ? ide : r.look?.theme || '', laser: false, pt: null, frame: 0, busy: false, lit: false, sent: 0, dotT: 0, left: -Infinity, inert: []};
  canvas.classList.toggle('blank', p.blank);
  // the presenter's own demo, with its answers, is the source of the room copy: one mirror for each mount, once rupaka has drawn it
  const demo = spec => {
    const e = rupakaDraw(spec, null, null, null, {askable: false}), d = {host: e.host, inner: e.inner, slug: spec.id, mirror: null, kept: {gates: {}, pick: {}, answers: {}}};
    // a demo that a run's output shows is not in the deck, so the server takes no move for it; both windows draw it from the room copy
    e.done.then(() => { if (!e.ok) return; slidesRk(e.host.shadowRoot); if (lee.present === p && p.slugs.has(d.slug)) presentMirror(p, d); });
    return d;
  };
  const mount = (spec, id) => (p.demos.get(id) || p.demos.set(id, demo(spec)).get(id)).host;
  const stuck = d => { const a = presentMove(p.line, p.at, d); return a.slide === p.at.slide && a.step === p.at.step; };
  p.draw = () => {
    const s = p.deck.slides[p.at.slide] || {}, {fits} = slidesDraw(canvas, p.deck, p.at.slide, p.at.step, {key: p.ak, size: Math.round(p.text*10), mount, math: renderMath, outs: slidesHtml(p.outs)});
    for (const d of p.demos.values()) presentAnswers(p, d);
    const g = p.line[p.at.slide]?.groups || 0;
    q('[data-where]').textContent = `${p.at.slide + 1} / ${p.deck.slides.length}` + (g ? ` · step ${p.at.step + 1} / ${g + 1}` : '');
    q('[data-prev]').disabled = stuck(-1); q('[data-next]').disabled = stuck(1);
    if (document.activeElement?.disabled && root.contains(document.activeElement)) root.focus({preventScroll: true});
    q('[data-size]').textContent = `Text ${Math.round(28*p.text*(+canvas.style.getPropertyValue('--slide-fit') || 1))} px`;
    q('[data-notes-body]').replaceChildren(slidesSafe(s.notes || '', p.ak));
    q('[data-upcoming]').textContent = s.next ? `Next: ${s.next}` : 'This is the last slide.';
    presentStrip(p);
    if (!fits) presentSay(`Slide ${p.at.slide + 1} has more than fits. Split it or trim it.`);
  };
  const go = d => {
    const a = presentMove(p.line, p.at, d); if (a.slide === p.at.slide && a.step === p.at.step) return;
    if (a.slide !== p.at.slide) p.held.answers = {};
    p.at = a; p.draw(); presentGo(p);
  };
  const resize = d => {
    p.text = presentStep(p.text, d);
    try { localStorage.setItem(presentKey(), String(p.text)); } catch {}
    p.draw(); presentSay(`text ${Math.round(p.text*100)}%`); presentGo(p);
  };
  const full = () => document.fullscreenElement ? document.exitFullscreen().catch(() => {})
    : root.requestFullscreen ? root.requestFullscreen().catch(() => presentSay('Use View › Enter Full Screen to fill the screen.')) : presentSay('Use View › Enter Full Screen to fill the screen.');
  const setNotes = open => {
    const inside = notes.contains(document.activeElement);
    notes.hidden = !open; root.classList.toggle('lee-notes-open', open); notesBtn.setAttribute('aria-expanded', String(open));
    if (!open && inside) notesBtn.focus({preventScroll: true});
  };
  const toggleNotes = () => setNotes(notes.hidden);
  // the newest point waits here; at most one is in the post chain, so slow replies queue nothing behind them
  const send = () => {
    p.frame = 0;
    if (lee.present !== p || !p.laser || p.blank || !p.pt || p.busy) return;
    if (performance.now() - p.sent < PRESENT_POINT_MS) return void (p.frame = requestAnimationFrame(send));
    const [x, y] = p.pt; p.pt = null; p.busy = p.lit = true; p.sent = performance.now();
    presentPost(p, '/present/move', {t: 'point', x, y}).finally(() => { p.busy = false; if (p.pt) p.frame ||= requestAnimationFrame(send); });
  };
  const point = e => {
    if (!p.laser || p.blank) return;
    const b = canvas.getBoundingClientRect(); if (!b.width || !b.height) return;
    const [x, y] = p.pt = [presentClamp((e.clientX - b.left)/b.width), presentClamp((e.clientY - b.top)/b.height)];
    dot.style.left = x*100 + '%'; dot.style.top = y*100 + '%'; dot.classList.add('on');
    clearTimeout(p.dotT); p.dotT = setTimeout(() => dot.classList.remove('on'), PRESENT_FADE);
    p.frame ||= requestAnimationFrame(send);
  };
  // the dot off on both screens; the laser stays on for the next move
  const dark = () => {
    cancelAnimationFrame(p.frame); p.frame = 0; p.pt = null; clearTimeout(p.dotT); dot.classList.remove('on');
    if (p.lit) { p.lit = false; presentPost(p, '/present/move', {t: 'point', off: true}); }
  };
  const laser = (on = !p.laser) => { if (!on) dark(); p.laser = on; root.classList.toggle('lee-laser', on); };
  const blank = () => { p.blank = !p.blank; canvas.classList.toggle('blank', p.blank); if (p.blank) dark(); presentGo(p); };
  const esc = () => {
    if ($('.lee-modal')) return false;
    if (document.fullscreenElement) return false;
    if (performance.now() - p.left < PRESENT_FULL_MS) return true;
    if (p.err) return presentErr(p, null), true;
    if (!notes.hidden) return setNotes(false), true;
    if (p.laser) return laser(false), true;
    const a = document.activeElement;
    if (a !== root && root.contains(a) && (a.closest('.lee-rupaka') || isTextEntry(a))) root.focus({preventScroll: true});
    return true;
  };
  p.keys = {ArrowRight: () => go(1), ArrowDown: () => go(1), Space: () => go(1), PageDown: () => go(1),
            ArrowLeft: () => go(-1), ArrowUp: () => go(-1), 'Shift+Space': () => go(-1), PageUp: () => go(-1),
            KeyN: toggleNotes, KeyF: full, KeyX: () => laser(), KeyB: blank, Escape: esc};
  // the rules of `abhyasaStage.presenter`, which the IDE page does not load: a key is its `e.code`; no Alt, AltGraph, Cmd or Ctrl key, no held key,
  // no key in a field or a demo but Esc; Space or Enter presses a focused button and nothing else; a function that gives false lets the key go on
  p.onKey = e => {
    if (lee.present !== p || e.metaKey || e.ctrlKey || e.altKey || e.getModifierState?.('AltGraph') || e.isComposing || e.key === 'Process') return;
    const a = document.activeElement, t = keyTarget(e);
    if (a && a !== document.body && !root.contains(a)) return;
    if (e.code !== 'Escape' && (isTextEntry(t) || a?.closest('.lee-rupaka'))) return;
    if ((e.code === 'Space' || e.code === 'Enter') && t?.matches?.(PRESENT_PRESSES)) { if (e.repeat) e.preventDefault(); return; }
    const name = (e.shiftKey ? 'Shift+' : '') + e.code, fn = Object.hasOwn(p.keys, name) && p.keys[name]; if (!fn) return;
    if (!e.repeat && fn(e) === false) return;
    e.preventDefault(); e.stopPropagation();
  };
  p.onFull = () => { if (!document.fullscreenElement) p.left = performance.now(); };
  p.onFocus = e => { if (lee.present === p && !root.contains(e.target) && !e.target.closest?.('.lee-modal')) root.focus({preventScroll: true}); };
  p.onBlur = () => dark();
  canvas.addEventListener('pointermove', point); canvas.addEventListener('pointerleave', dark); canvas.addEventListener('pointercancel', dark);
  p.onOutput = e => { const run = lee.present === p && p.runs[e.detail.id]; if (run) presentOut(p, e.detail.id, run.gen, e.detail.outputs || [], false); };
  p.onRestart = () => presentReset(p);
  q('[data-show-error]').onclick = () => presentShowError(p); q('[data-err-close]').onclick = () => presentErr(p, null);
  q('[data-prev]').onclick = () => go(-1); q('[data-next]').onclick = () => go(1);
  q('[data-smaller]').onclick = () => resize(-1); q('[data-bigger]').onclick = () => resize(1);
  notesBtn.onclick = toggleNotes; q('[data-close]').onclick = () => setNotes(false); q('[data-full]').onclick = full;
  q('[data-audience]').onclick = () => {
    const url = location.origin + p.audience;
    if (inDesktopShell()) { openExternal(url); return presentSay(PRESENT_HINT); }
    const w = p.win && !p.win.closed ? p.win : window.open('', 'leela-audience', 'popup,width=1280,height=720');
    if (!w) return presentSay('The browser blocked the window. Click again.');
    let mine = false; try { mine = w.location.pathname === '/present/audience' && w.sessionStorage.getItem('lee-present-k') === p.ak; } catch {}
    if (!mine) w.location.href = url;
    p.win = w; w.focus(); presentSay(PRESENT_HINT);
  };
  end.onclick = () => {
    if (end.dataset.armed) return presentEnd(p);
    end.dataset.armed = '1'; end.textContent = 'End now?';
    clearTimeout(p.endT); p.endT = setTimeout(() => { delete end.dataset.armed; end.textContent = 'End'; }, 3000);
  };
  const wake = () => {
    root.classList.remove('lee-idle'); clearTimeout(p.idle);
    p.idle = setTimeout(() => { if (!strip.contains(document.activeElement)) root.classList.add('lee-idle'); }, 3000);
  };
  root.addEventListener('pointermove', e => { if (innerHeight - e.clientY <= Math.max(80, strip.offsetHeight + 24)) wake(); });
  strip.addEventListener('focusin', wake); strip.addEventListener('pointerdown', wake);
  root.addEventListener('lee-markdown-rendered', e => $$('.lee-reply-actions', e.target).forEach(x => x.remove()));
  // one stream; the browser connects it again by itself, and a closed one opens again with a growing wait; each connect starts with the live id
  const listen = () => {
    const s = p.events = new EventSource('/present/events'), on = (t, f) => s.addEventListener(t, e => { if (p.events === s) f(JSON.parse(e.data)); });
    on('presentation', d => { p.wait = 0; presentCheck(p, d); }); on('presenter', d => presentCheck(p, d));
    on('audience', d => { if (d.id === p.id) q('[data-conn]').textContent = d.n ? 'Audience window: connected' : 'Audience window: not connected'; });
    on('presentation-ended', d => {
      if (d.id !== p.id || lee.present !== p) return;
      presentForget(p.id); closePresentation(); status(d.reason === 'replaced' ? 'Another presentation started.' : PRESENT_ENDED, 'err');
    });
    s.onerror = () => {
      if (p.events !== s || s.readyState !== EventSource.CLOSED || lee.present !== p || p.again) return;
      p.again = setTimeout(() => { p.again = 0; if (lee.present === p && p.events === s) listen(); }, p.wait = Math.min(15000, (p.wait || 500)*2));
    };
  };
  listen();
  // the IDE theme changing during the show is a look move; the look the server holds at a resume is kept until then
  p.watch = new MutationObserver(() => { const t = presentTheme(); if (t && t !== p.ide) presentPost(p, '/present/move', {t: 'look', theme: p.ide = p.look = t}); });
  p.watch.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-mode', 'data-density']});
  p.clock = setInterval(() => {
    const s = Math.floor((Date.now() - p.started)/1000);
    q('[data-clock]').textContent = `Time: ${Math.floor(s/60)}:${String(s % 60).padStart(2, '0')}`;
  }, 1000);
  document.addEventListener('keydown', p.onKey, true); addEventListener('lee-cell-output', p.onOutput); addEventListener('lee-kernel-restart', p.onRestart);
  clearTimeout(lee.autoSaveTimer);
  document.addEventListener('fullscreenchange', p.onFull); document.addEventListener('focusin', p.onFocus, true); addEventListener('blur', p.onBlur);
  document.documentElement.classList.add('talk');
  closeInlinePopover(); document.body.appendChild(root); slidesScale(q('.lee-stage'));
  // the page under the presentation takes no focus and no key; a dialog opened later still can
  p.inert = [...document.body.children].filter(el => el !== root && !el.inert && !el.matches('.lee-modal'));
  for (const el of p.inert) el.inert = true;
  root.focus({preventScroll: true});
  const m = root.appendChild(Object.assign(document.createElement('div'), {className: 'lee-slide lee-measure'}));
  const long = p.deck.slides.map((s, i) => slidesDraw(m, p.deck, i, s.groups, {key: p.ak, size: Math.round(p.text*10)}).fits ? 0 : i + 1).filter(Boolean);
  m.remove();
  p.draw(); wake();
  if (long.length) presentSay(long.length === 1 ? `Slide ${long[0]} has more than fits. Split it or trim it.` : `Slides ${long.join(', ')} have more than fits. Split them or trim them.`);
  if (fresh) { presentGo(p); if (p.look) presentPost(p, '/present/move', {t: 'look', theme: p.look}); }
  const failed = outs.filter(o => o.error && o.html === o.room).sort((a, b) => b.gen - a.gen)[0];
  if (failed) presentErr(p, {cell: failed.cell, gen: failed.gen, ...failed.error});
  for (const o of outs) if (!o.done) presentFollow(p, o.cell, o);
  presentKeep(p);
  root.dataset.ready = '';
}

function closePresentation() {
  const p = lee.present; if (!p) return;
  lee.present = null;
  document.removeEventListener('keydown', p.onKey, true); removeEventListener('lee-cell-output', p.onOutput); removeEventListener('lee-kernel-restart', p.onRestart);
  for (const d of p.demos.values()) d.unwatch?.();
  document.removeEventListener('fullscreenchange', p.onFull); document.removeEventListener('focusin', p.onFocus, true); removeEventListener('blur', p.onBlur);
  cancelAnimationFrame(p.frame); clearTimeout(p.dotT);
  for (const el of p.inert || []) el.inert = false;
  p.events?.close(); clearTimeout(p.again); p.watch?.disconnect(); clearTimeout(p.idle); clearTimeout(p.endT); clearInterval(p.clock);
  document.documentElement.classList.remove('talk');
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  $$('[data-markdown]', p.root).forEach(el => {
    clearTimeout(el._leeMarkdownTimer); if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of el._leeCodeViews || []) try { LeeCM.destroy(v); } catch {}
  });
  $$('iframe', p.root).forEach(f => f.remove());
  p.root.remove();
  if (lee.kind === 'notebook' && lee.cells.length) focusCell(lee.sel);
  if ($('.lee-tab.active.dirty')) scheduleAutoSave();
}
/* The exec log holds anything run outside a notebook cell: the exec box, a selection, a whole
 * file. One place to look for what this kernel has been asked to do. */
function execLine(code, text, ok) {
  const log = $('#execlog'); if (!log) return;
  const line = document.createElement('div');
  line.className = 'lee-runline' + (ok ? '' : ' err');
  line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                   `<span class="res">${esc((text || 'ok').trim())}</span>`;
  log.appendChild(line); log.scrollTop = log.scrollHeight;
}

/* Run the open .py in its own process, on the project's interpreter, with a terminal to watch it
 * in and a pill that says it is running. The tab's kernel is not used, so a server that never
 * returns holds nothing and its output goes to a terminal on screen.
 *
 * A saved configuration for this file still wins, so `python -m x` or an argv is honoured. Scratch
 * code is `run selection`, which is still the kernel. */
async function runFile() {
  if (lee.kind !== 'text') return status('this is a notebook. Run its cells, or use “▶ all”', 'err');
  const path = lee.path || '';
  if (!path.endsWith('.py')) return status('only a .py file can run. Use “run selection” instead', 'err');
  if ($('.lee-tab.active.dirty') && !await saveTab(true))
    return status('save the file before running it', 'err');
  const here = path.split('/').pop();
  let cfg = null;
  try {
    const d = await api('/runs');
    cfg = (d.runs || []).find(r => r.cmd === path || (r.cmd || '').split(/\s+/).some(a => a === path || a.endsWith('/' + here) || a === here));
  } catch (_) {}
  return startRun(cfg || {name: '', cmd: path});
}

/* Just the selected code, read straight off the CodeMirror state rather than through `LeeCM`. The
 * bundle in static/ is committed and rebuilding it needs node, so the client cannot depend on a
 * wrapper that is not in the shipped build. */
async function runSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const s = v.state.selection.main;
  const code = s.empty ? '' : v.state.doc.sliceString(s.from, s.to);
  if (!code.trim()) return status('select some code first', 'err');
  let r;
  try { r = await withPython(() => post('/run/code', {code, path: lee.tabKey || ''})); }
  catch (e) { return status(String(e.message || e), 'err'); }
  const head = code.trim().split('\n')[0].slice(0, 60);
  execLine(head + (code.trim().includes('\n') ? ' …' : ''), r.text, r.ok);
  status(r.ok ? 'ran the selection' : 'the selection raised an error. See the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Execute a bounded notebook range in order, code cells only: "run above" must not send every
 * prompt cell above it to a model. */
async function runRange(start, end, label) {
  if (lee.kind !== 'notebook') return runFile();
  start = Math.max(0, start); end = Math.min(end, lee.cells.length);
  for (let i = start; i < end; i++) {
    const c = lee.cells[i];
    if (c.cell_type !== 'code' || !(c.source || '').trim()) continue;
    status(`running cell ${i + 1}…`);
    const r = await runCell(i, false);
    if (!r.ok) return status(`${r.error || `cell ${i + 1} failed`}. Stopped there.`, 'err');
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

/* Two questions, two lists: which interpreter's packages this tab can import, and which launcher
 * runs it. Both restart the kernel, so what that costs is on screen while the choice is made.
 * Resolves true once an interpreter is chosen and its kernel is up, false when the picker closes without one. */
async function pickKernel() {
  let picked, picking = false;
  const chosen = new Promise(r => picked = r);
  const o = await api('/kernel/options');
  const models = await loadedModels();
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
    (o.notice ? `<div class="lee-err">${esc(o.notice.message)} <button class="lee-btn" data-kernel-upgrade>Upgrade ipykernel</button></div>` : '') +
    `<div class="lee-dim">choosing either of these restarts the kernel. Its variables are lost</div>` +
    `<h4>launcher</h4><div class="lee-modallist">${kinds}</div>` +
    `<h4>interpreter</h4><div class="lee-modallist">${pys}</div>` +
    engineSection(models) +
    `<div class="lee-runtime-cwd"><span>working directory</span><code>${esc(o.cwd || '')}</code>` +
    `<button class="lee-btn" id="kernelcwd">change</button></div>` +
    `<label class="lee-check-setting"><input type="checkbox" id="kernel-auto-manage"${o.auto_manage ? ' checked' : ''}> leela manages the runtime limit</label>` +
    `<div class="lee-dim">at the limit, closes the longest-idle runtime instead of asking</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="kernelattach">` +
    `${o.private ? 'attach to folder kernel' : 'give this tab its own kernel'}</button>` +
    `<span class="lee-dim">notebooks default to their own kernel; files share by folder</span></div>`,
    null, () => { if (!picking) picked(false); });
  const clearWeights = m.querySelector('#clearengines');
  if (clearWeights) clearWeights.onclick = () => clearEngines(m);
  const reconnect = $('[data-kernel-reconnect]', m);
  if (reconnect) reconnect.onclick = () => { m.remove(); restartKernel(); };
  const upgrade = $('[data-kernel-upgrade]', m);
  if (upgrade) upgrade.onclick = () => { m.remove(); upgradeIpykernel(o.python); };
  m.querySelector('#kernel-auto-manage').onchange = async (e) => {
    try { e.target.checked = await setKernelAutoManage(e.target.checked); }
    catch (err) { e.target.checked = !e.target.checked; status(String(err.message || err), 'err'); }
  };
  m.querySelector('#kernelcwd').onclick = async () => {
    const cwd = await inputDialog('kernel working directory', 'folder inside an open project',
                                  o.cwd || '', '/path/to/project');
    if (!cwd || cwd === o.cwd) return;
    m.remove(); status('restarting kernel in ' + cwd + '…');
    let d;
    try { d = await withPython(() => post('/kernel/cwd', {cwd})); }
    catch (e) { return status(String(e.message || e), 'err'); }
    markPreviousRuns(); paintEnv(''); status('kernel cwd: ' + d.cwd, 'ok'); refreshKernelPill(); leeVars();
  };
  m.querySelector('#kernelattach').onclick = async () => {
    const privateKernel = !o.private; m.remove(); status('changing kernel attachment…');
    let d;
    try { d = await withPython(() => post('/kernel/select', {private: privateKernel})); }
    catch (e) { return status(String(e.message || e), 'err'); }
    markPreviousRuns(); paintEnv('');
    status(privateKernel ? 'this tab now has its own kernel' : 'attached to the folder kernel', 'ok');
    refreshKernelPill(); leeVars();
  };
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r || r.dataset.engine) return;
    if (r.dataset.off) {
      if (!o.python) return status('choose a project interpreter before installing kernel support', 'err');
      m.remove(); status('installing ipykernel and ipymini with uv…');
      const support = await post('/runtime/support', {python: o.python});
      status(support.ok ? 'kernel support installed · ipykernel + ipymini' : support.error,
             support.ok ? 'ok' : 'err');
      return pickKernel();
    }
    picking = !r.dataset.kind; m.remove();
    status('starting the new kernel…');
    const pick = () => post('/kernel/select', r.dataset.kind ? {kind: r.dataset.kind} : {python: r.dataset.py});
    let d;
    try { d = await (r.dataset.kind ? withPython(pick) : pick()); }
    catch (e) { picked(false); return status(String(e.message || e), 'err'); }
    picked(true);
    markPreviousRuns();
    // Picking a runtime also makes its namespace the live variable source, so the panel must not
    // stay pinned, on screen or server-side, to the process watched before the switch.
    paintEnv('');
    status(`kernel: ${d.running_kind} · ${(d.python || 'leela’s own python').split('/').pop()} · variables connected`, 'ok');
    refreshKernelPill(); leeVars();
  });
  return chosen;
}

/* A project with no venv and no chosen interpreter runs no Python. The person answers once: set up
 * .venv, or choose an interpreter; then `go` runs again. Runs that ask together share one answer. */
let pythonAsked = null;
async function withPython(go) {
  try { return await go(); }
  catch (e) {
    if (e.body?.kind !== 'no_venv') throw e;
    if (!await (pythonAsked ||= askPython(e.body).finally(() => { pythonAsked = null; }))) throw e;
    return go();
  }
}
window.withPython = withPython;

async function setUpVenv(root, name) {
  status(`setting up .venv for ${name}…`);
  try {
    const r = await post('/runtime/create', {root});
    status(r.note || `the Python environment for ${name} is ready`, 'ok');
    refreshKernelPill(); return true;
  } catch (e) { status(String(e.message || e), 'err'); return false; }
}

function askPython(body) {
  const root = (body.refs || [])[0] || '', name = root.split('/').pop() || 'this project';
  return new Promise(resolve => {
    let settled = false;
    const done = v => { if (!settled) { settled = true; resolve(v); } };
    const m = modal(`<div class="lee-mhead">No Python environment for ${esc(name)}</div>` +
      `<div class="lee-dialogcopy">Leela runs no code in ${esc(name)} until it has a Python environment. ` +
      `Set up a <code>.venv</code> in the project, or choose an interpreter. Then the run starts.</div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" id="pyvenv">Set up .venv</button>` +
      `<button class="lee-btn" id="pypick">Choose interpreter…</button>` +
      `<button class="lee-btn" id="pylater">Not now</button></div>`, null, () => done(false), {className: 'lee-python-ask'});
    m.querySelector('#pyvenv').onclick = async () => {
      m.querySelectorAll('button').forEach(b => b.disabled = true);
      if (!await setUpVenv(root, name)) return m.querySelectorAll('button').forEach(b => b.disabled = false);
      done(true); m.remove();
    };
    m.querySelector('#pypick').onclick = async () => { settled = true; m.remove(); resolve(await pickKernel()); };
    m.querySelector('#pylater').onclick = () => m.remove();
  });
}

//: Every Restart kernel button: the saved outputs turn historical, and the pill and the variables follow.
async function restartKernel() {
  status('restarting the kernel…');
  try { await post('/kernel/restart'); } catch (e) { return status(String(e.message || e), 'err'); }
  markPreviousRuns(); status('kernel restarted', 'ok'); refreshKernelPill(); if (window.leeVars) leeVars();
}

//: Install kernel support into `python` again, which asks for ipykernel 7.4 or later, then restart the kernel onto it.
async function upgradeIpykernel(python) {
  status('installing ipykernel 7.4 or later…');
  try { await post('/runtime/support', python ? {python} : {}); } catch (e) { return status(String(e.message || e), 'err'); }
  await restartKernel();
}

/* The weights the local models are loaded into, beside the kernels: one modal for what this machine
 * is holding open. The broker is the only thing that knows, and one that cannot answer must not keep
 * the kernel picker shut, since this is where a person comes when a runtime is misbehaving. */
async function loadedModels() {
  try { return (await api('/runtime/broker')).models || null; }
  catch (e) { console.warn('Leela could not read the model engine broker:', e); return null; }
}

function engineSection(models) {
  if (!models) return '';
  const idle = s => s >= 60 ? `idle ${Math.round(s / 60)}m` : `idle ${Math.max(0, Math.round(s))}s`;
  const rows = (models.engines || []).map(e =>
    `<div class="lee-mrow" data-engine="1" style="cursor: default">${esc(e.runtime + '/' + e.model)}` +
    `<span class="sub">${e.in_use ? 'in use' : idle(e.idle_for || 0)}</span></div>`).join('');
  return `<h4>loaded models</h4>` +
    (rows ? `<div class="lee-modallist">${rows}</div>` +
            `<div class="lee-dim">${models.live} of ${models.limit} loaded · ` +
            `weights outlive the chats built on them</div>` +
            `<div class="lee-mfoot"><button class="lee-btn" id="clearengines">clear weights</button></div>`
          : `<div class="lee-dim">no local model weights are loaded</div>`);
}

/* Releasing weights a session is answering on interrupts it, so the refusal is the server's own
 * sentence and the force is a second, deliberate answer to it. */
async function clearEngines(m) {
  let d;
  try { d = await post('/runtime/engines/clear', {}); }
  catch (e) {
    const refusal = String(e.message || e);
    const held = ((await loadedModels())?.engines || []).filter(x => x.in_use);
    if (!held.length) return status(refusal, 'err');   // not the one refusal a person can answer
    if (!await confirmDialog('a session is using a loaded model',
                             `${refusal} That session loses the model it is answering on.`,
                             'clear anyway')) return status(refusal, 'err');
    try { d = await post('/runtime/engines/clear', {force: true}); }
    catch (err) { return status(String(err.message || err), 'err'); }
  }
  const freed = (d.freed || []).map(e => `${e.runtime}/${e.model}`).join(', ');
  m.remove();
  status(freed ? `released ${freed}${d.live ? ` · ${d.live} still loaded` : ''}` : d.note, 'ok');
}

/* The kernel ceiling names the runtime it would close and waits for an answer. `settings > runtimes`
 * mutes this, and leela closes the longest-idle one itself. */
async function offerKernelRoom(body) {
  const c = body.candidate;
  if (!c) return false;                       // every runtime is busy, so there is nothing to offer
  const mins = Math.round((c.idle_for || 0) / 60);
  const idle = mins >= 1 ? `, idle ${mins} min` : '';
  if (!await confirmDialog('kernel limit reached',
      `${body.kernel_limit} runtimes are open, which is the limit. ` +
      `Close ${c.name}${idle} to make room?`, `close ${c.name}`)) return false;
  try { await post('/runtime/close', {key: c.key}); return true; }
  catch (e) { console.warn('Leela could not close that runtime:', e); return false; }
}

async function setKernelAutoManage(enabled) {
  const r = await post('/runtime/auto-manage', {enabled: !!enabled});
  return r.enabled;
}
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
  const notes = (ns, tk) => {                     // refusals are errors; what a chord of yours took from a default is only told
    const host = m.querySelector('#keynotes');
    host.innerHTML = (ns || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('') +
                     (tk || []).map(n => `<div style="opacity:.75">${esc(n)}</div>`).join('');
    host.hidden = !((ns || []).length || (tk || []).length);
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
    if (!edited.size) return notes(d.notes, d.took);
    clearTimeout(checking);
    checking = setTimeout(async () => {
      try {
        const r = await post('/keys/check', {keys: merged()});
        notes(r.notes, r.took);
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
    edited.clear(); notes(r.notes, r.took); paint();
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
  notes(d.notes, d.took); paint();
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
      return status(`screen captured (${Math.round(r.bytes / 1024)}kb). It goes with your next question.`, 'ok');
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
    status(`screen captured (${Math.round(r.bytes / 1024)}kb). It goes with your next question.`, 'ok');
  } catch (e) { status('capture failed: ' + (e.message || e), 'err'); }
}

/* Edits go one at a time, each to the notebook it was made in, naming cells by id. A response is applied
   only while that notebook is still the one mounted and only when it is no older than what is shown, and
   text typed while it was in flight stays. One arriving while its tab is away waits in `lee.nbLate`.
   Resolves to the response it applied, or null, so a caller leaves focus and selection alone. */
async function nbEdit(d) {
  // A file is one document, not a column of cells, and a structural edit would split the buffer.
  if (lee.kind !== 'notebook') { status('this tab is a file. Cells are in notebooks only', 'err'); return null; }
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

// Whichever editor has the cursor: a cell, a whole file, or the exec box.
function curEditor() {
  if (lee.scope === 'exec') return lee.editors.get('exec');
  if (lee.activeEditor === 'secondary') return lee.editors.get('secondary');
  if (lee.kind === 'notebook') { const c = lee.cells[lee.sel]; return c && lee.editors.get(c.id); }
  return lee.editors.get('file');
}
function curLang() {
  if (lee.scope === 'exec') return 'python';
  if (lee.kind === 'notebook') return lee.cells[lee.sel]?.cell_type === 'markdown' ? 'markdown' : nbLang();
  return $('#editor')?.dataset.lang || 'python';
}

/* Indent from the palette, or from a chord the caret did not reach a document with. `curEditor`
   answers for a notebook cell and for a whole file alike, which is what these have to cover. */
function leeIndent(cmd) {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  LeeCM.focus(v);
  LeeCM[cmd](v);
}

function kernelComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  LeeCM.startCompletion(v);
}

/* Two completions, two different questions. alt+/ asks the kernel what names exist, which is
 * instant and right by construction. This asks the model what should come next, which costs a
 * forward pass, so it is never fired by typing and stays ghost text until tab accepts it. */
function closeSelectionHelp() { $('.lee-selection-tools')?.remove(); }
function selectionEditor() {
  if (!['editor', 'exec'].includes(lee.scope)) return null;
  return curEditor();
}
/* Place a floating panel beside `rect`, wholly inside the viewport.

   `offsetHeight`, not `getBoundingClientRect`: these panels animate in from a transform, and the
   rect is of the transformed box, which is short by a few pixels on the first frame. Callers place
   twice, once while the panel is a skeleton and again once it has its content, so appending is
   conditional and the second call only moves it. */
function positionFloating(el, rect) {
  if (!el.isConnected) document.body.appendChild(el);
  const w = el.offsetWidth, h = el.offsetHeight, below = innerHeight - rect.bottom - 15;
  const top = h <= below || below >= rect.top - 15 ? rect.bottom + 7 : rect.top - h - 7;
  el.style.left = Math.max(8, Math.min(rect.left, innerWidth - w - 8)) + 'px';
  el.style.top = Math.max(8, Math.min(top, innerHeight - h - 8)) + 'px';
}
/* Returns the panel it raised, or null. The chords below ask for one of its controls, and the four
   guards here are the only place that knows whether there is a selection to act on. */
function showSelectionHelp() {
  if ($('.lee-selection-reply') || document.activeElement?.closest?.('.lee-selection-tools')) return null;
  const view = selectionEditor(); if (!view) return closeSelectionHelp(), null;
  const selected = LeeCM.selection(view); if (!selected?.text.trim()) return closeSelectionHelp(), null;
  const rect = LeeCM.selectionCoords(view); if (!rect) return closeSelectionHelp(), null;
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
  return tools;
}
/* The chords reach the panel's own controls rather than the route behind them, so the selection, the
   coordinates and the four guards stay in one place. Each way of being unavailable says which one it
   is: a reply already on screen is not a missing selection, and an ask already open is not a second
   ask. Silence would be worse than either, because a chord that does nothing reads as broken. */
function askSelection(control) {
  if ($('.lee-selection-reply')) return status('finish or discard the open suggestion first', 'err');
  if ($('.lee-selection-tools')?.classList.contains('asking')) return status('the ask box is already open', 'err');
  const tools = showSelectionHelp();
  if (!tools) return status('select some text in an editor first', 'err');
  $(control, tools).click();
}
/* What the model looked at before answering, named rather than counted: a rewrite that read the
   file around the selection is worth more trust than one that read nothing, and the reader is the
   one deciding whether to take it. */
function trailHtml(activity) {
  if (!Array.isArray(activity)) return '';   // an older server: say nothing rather than guess
  const used = activity.filter(a => a.tool).map(a => a.tool);
  // An empty trail is a fact about the answer, not a missing feature. Rendering nothing for it
  // leaves the reader unable to tell "it looked at nothing" from "the trail is broken".
  if (!used.length) return `<div class="lee-selection-trail lee-trail-none">` +
    `<span>answered without looking anything up</span></div>`;
  const counts = used.reduce((n, t) => ({...n, [t]: (n[t] || 0) + 1}), {});
  const named = Object.entries(counts).map(([t, n]) => esc(n > 1 ? `${t} x${n}` : t)).join(', ');
  return `<div class="lee-selection-trail"><span>looked at</span> ${named}</div>`;
}
/* One panel's judgement, reported as it happens.

   The outcome is a click, so only the browser ever learns it, and the `ask_id` the server minted is
   what ties the answer to what became of it. Every send is swallowed: `post` rejects on a non-2xx,
   and a recording failure must never be what stops a replace. */
function completionLog() {
  let queue = [], timer = null, done = false;
  const flush = () => {
    clearTimeout(timer); timer = null;
    const events = queue; queue = [];
    if (events.length) post('/ai/events', {events}).catch(() => {});
  };
  const add = (kind, row = {}) => {
    if (done) return;
    /* One panel, one verdict -- and `stale` is not one. The selection moved out from under a
       replace, which leaves the panel open and the suggestion still there to accept once the
       caret is back. Ending the log on it threw away the accept that followed. */
    if (['replace', 'discard', 'abandon'].includes(kind)) done = true;
    queue.push({kind, at: Date.now() / 1000, ...row});
    clearTimeout(timer); timer = setTimeout(flush, done ? 0 : 2500);
  };
  return {add, flush, settled: () => done};
}
async function runSelectionHelp(view, selected, rect, mode, instruction = '') {
  closeSelectionHelp();
  const log = completionLog();
  status(mode === 'summary' ? 'summarising selection with the local model…' : 'asking the inline model to rewrite the selection…');
  const panel = document.createElement('aside'); panel.className = 'lee-selection-reply loading';
  panel.innerHTML = `<header><strong>${mode === 'summary' ? 'Summarising selection' : 'Inline AI help'}</strong>` +
    `<span>working locally when available</span></header><div class="lee-selection-skeleton"><i></i><i></i><i></i></div>`;
  // The reader can scroll or resize while the model answers, so the anchor is asked for again
  // rather than reused. `selectionCoords` gives nothing once the selection is gone.
  const anchor = () => { try { return LeeCM.selectionCoords(view) || rect; } catch (_) { return rect; } };
  positionFloating(panel, anchor());
  /* Minted here, not by the route. The ask is logged before the request and the verdict long after
     it, so a server-minted id reached the reply and the outcome and never the ask: the instruction
     and the selected code sat on disk with nothing to join them to. Declared outside the `try`,
     because the `error` a failed ask records is the half of the judgement that matters most. */
  const ask_id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  try {
    // The path and the lines are what the read-only tools need to open anything around the
    // selection. Without them a model asked about `check` can only see the range it was given.
    const doc = LeeCM.getDoc(view), lineAt = i => doc.slice(0, i).split('\n').length;
    log.add('ask', {ask_id, mode, instruction, lang: curLang(), path: lee.path || '',
                    chars: selected.text.length, text: selected.text});
    const result = await post('/complete/selection', {
      ask_id, text: selected.text, mode, instruction, lang: curLang(), path: lee.path || '',
      line_from: lineAt(selected.from), line_to: lineAt(selected.to)});
    log.add('reply', {ask_id, model: result.model, ms: result.ms, tools: result.tools,
                      reply: result.text});
    panel.classList.remove('loading'); panel.innerHTML = `<header><strong>${mode === 'summary' ? 'Summary' : 'Suggested replacement'}</strong>` +
      `<span title="the inline model, set beside 'prompt cells · inline AI' in the agent settings">` +
      `${esc(result.model || '')}${mode === 'summary' ? '' : ' · inline model'}</span></header>` +
      `<pre></pre>${trailHtml(result.activity)}<footer>` +
      `<button class="lee-btn" data-completions title="what you have asked, and what you kept">log</button>` +
      `<button class="lee-btn" data-discard>discard</button><button class="lee-btn go" data-replace>replace selection</button></footer>`;
    $('pre', panel).textContent = result.text;
    panel._leeLog = log; panel._leeAsk = ask_id;
    $('[data-discard]', panel).onclick = () => { log.add('discard', {ask_id}); panel.remove(); };
    /* `completionLog` holds events for 2500ms, so the ask on screen is not in the store yet and the
       log would open without it. Flushed first, and the panel is left alone: reading the record is
       not a verdict on this suggestion. */
    $('[data-completions]', panel)?.addEventListener('click', () => { log.flush(); showCompletions(); });
    $('[data-replace]', panel).onclick = () => {
      // Not an accept: nothing was applied. Counting it as one would flatter the model.
      if (LeeCM.slice(view, selected.from, selected.to) !== selected.text) {
        log.add('stale', {ask_id});
        return status('selection changed while the model was answering; suggestion left open', 'err');
      }
      log.add('replace', {ask_id});
      LeeCM.replaceRange(view, selected.from, selected.to, result.text); panel.remove(); status('selection replaced', 'ok');
    };
    panel.onkeydown = e => {
      if (e.key === 'Escape') { log.add('abandon', {ask_id}); panel.remove(); }
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('[data-replace]', panel).click();
    };
    $('[data-replace]', panel).focus();
    positionFloating(panel, anchor());
    status(`${mode === 'summary' ? 'summary' : 'replacement'} ready from ${result.model || 'the inline model'} · review before replacing`, 'ok');
  } catch (e) {
    // Asked and got nothing is the signal a rejection rate would otherwise hide.
    log.add('error', {ask_id, mode, model: '', instruction});
    panel.classList.remove('loading'); panel.innerHTML = `<div class="lee-selection-error">${esc(e.message || e)}</div>` +
      `<footer><button class="lee-btn" data-completions title="what you have asked, and what you kept">log</button>` +
      `<button class="lee-btn" data-discard>close</button></footer>`;
    // An ask that failed is when somebody most wants to know whether it has been failing all day
    $('[data-completions]', panel).onclick = () => { log.flush(); showCompletions(); };
    $('[data-discard]', panel).onclick = () => panel.remove();
    positionFloating(panel, anchor());
  }
}
/* The panel's own `onkeydown` only fires while the focus is inside it, which the first click
   elsewhere ends. Escape closes it from anywhere, and defers to a modal above it. */
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || $$('.lee-modal').length || lee.present) return;
  const panel = $('.lee-selection-reply'); if (!panel) return;
  abandonReply(panel); panel.remove(); e.stopPropagation();
}, true);

/* A panel closed without a verdict is still an answer nobody took, and leaving it unrecorded makes
   the accept rate a ratio over a denominator that quietly drops them. */
function abandonReply(panel) {
  const log = panel?._leeLog;
  if (log && !log.settled()) log.add('abandon', {ask_id: panel._leeAsk || ''});
}
addEventListener('pagehide', () => {
  const panel = $('.lee-selection-reply'); if (!panel?._leeLog || panel._leeLog.settled()) return;
  // `post` will not survive the unload; a beacon will.
  const body = JSON.stringify({events: [{kind: 'abandon', ask_id: panel._leeAsk || '',
                                         at: Date.now() / 1000}]});
  try { navigator.sendBeacon('/ai/events', new Blob([body], {type: 'application/json'})); } catch (_) {}
});
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

const diffHtml = (rows) => rows.map(r =>
  `<div class="lee-drow ${r.kind}"><span class="lee-dnum">${r.line || ''}</span>` +
  (r.html ? `<span class="lee-dtext hl">${r.html}</span></div>` : `<span class="lee-dtext">${esc(r.text)}</span></div>`)).join('');

function diffModal(title, label, rows) {
  return modal(`<div class="lee-mhead">${esc(title)}<span class="sub">${esc(label)}</span></div>
                <div class="lee-diff">${diffHtml(rows)}</div>`);
}

/* Local history. Undo is one step back, and after an agent, a tool or another editor has been
   through the tree the question is what the file said an hour ago. Every version Leela saw is
   kept, and this is where one gets picked. */
async function leeLocalHistory(path = lee.path) {
  if (!path) return status('open a file to see its history', 'err');
  let d;
  try { d = await api('/history/file?path=' + encodeURIComponent(path)); }
  catch (e) { return status(String(e.message || e), 'err'); }
  const versions = d.versions || [], name = path.split('/').pop();
  const m = modal(`<div class="lee-mhead">local history<span class="sub">${esc(name)}</span></div>` +
    `<div class="lee-lh"><nav class="lee-lh-list" id="lhrows" aria-label="kept versions"></nav>` +
    `<div class="lee-lh-view" id="lhview"></div></div>`, null, null, {storageKey: 'localhistory'});
  const rows = $('#lhrows', m), view = $('#lhview', m);
  if (!versions.length) {
    view.innerHTML = '<div class="lee-dim">Nothing kept for this file yet. A save, an agent edit, ' +
      'or a write from outside Leela starts its history.</div>';
    return;
  }
  const when = at => new Date((at || 0) * 1000).toLocaleString();
  rows.innerHTML = versions.map((v, i) =>
    `<button type="button" class="lee-lh-row${i ? '' : ' active'}" data-version="${esc(v.id)}">` +
    `<strong>${esc(v.label)}</strong><span>${esc(when(v.at))} · ${Number(v.bytes || 0).toLocaleString()} bytes` +
    `</span></button>`).join('');
  const show = async id => {
    $$('[data-version]', m).forEach(b => b.classList.toggle('active', b.dataset.version === id));
    view.innerHTML = '<div class="lee-dim">reading…</div>';
    let held;
    try { held = await api('/history/version?id=' + encodeURIComponent(id)); }
    catch (e) { view.innerHTML = `<div class="lee-err">${esc(String(e.message || e))}</div>`; return; }
    view.innerHTML = `<header class="lee-lh-head"><span>${esc(held.label)} · ${esc(when(held.at))}</span>` +
      `<span class="lee-spacer"></span>` +
      `<button type="button" class="lee-btn go" data-restore="${esc(id)}">restore this version</button></header>` +
      ((held.rows || []).length ? `<div class="lee-diff">${diffHtml(held.rows)}</div>`
        : '<div class="lee-dim">identical to what is on disk now</div>');
  };
  m.addEventListener('click', async e => {
    const pick = e.target.closest('[data-version]');
    if (pick) return show(pick.dataset.version);
    const back = e.target.closest('[data-restore]');
    if (!back) return;
    back.disabled = true;
    try {
      const out = await post('/history/restore', {id: back.dataset.restore});
      m.remove();
      await post('/tab/reload', {path: out.path});
      await mountTab(out.path);
      status(`${out.path.split('/').pop()} restored · ${out.label || 'from local history'}`, 'ok');
    } catch (err) { back.disabled = false; status(String(err.message || err), 'err'); }
  });
  show(versions[0].id);
}
window.leeLocalHistory = leeLocalHistory;

// The dirty dot says that a tab changed. This says what changed, before a save or after something
// moved the file underneath.
function bufferBody() {
  return lee.kind === 'notebook'
    ? {cells: lee.cells.map((c, i) => ({i, id: c.id, seq: nextSeq(), source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}))}
    : {text: lee.editors.has('file') ? LeeCM.getDoc(lee.editors.get('file')) : ''};
}

async function showDiff() {
  if (!lee.kind) return status('nothing open', 'err');
  const d = await post('/diff', {path: lee.tabKey, ...bufferBody()});
  if (!d.rows.length) return status('no unsaved changes', 'ok');
  status(`${d.label} unsaved`, 'ok');
  diffModal('unsaved changes: ' + d.title, d.label, d.rows);
}

async function openMergeConflict(conflictBox, theirs = []) {
  if (!lee.path) return status('save the document before merging it', 'err');
  const disk = await api('/tab/disk?path=' + encodeURIComponent(lee.path));
  if (lee.kind === 'notebook') {
    // A clash with another window names its side of each cell; the rest of the left side is the disk.
    const other = new Map(theirs.map(c => [c.id, c]));
    if (other.size) disk.cells = lee.cells.map((c, i) => other.get(c.id) || disk.cells?.find(d => d.id === c.id) || disk.cells?.[i] || {source: ''});
    conflictBox?.remove(); const merges = [];
    const count = Math.max(lee.cells.length, (disk.cells || []).length);
    const m = modal(`<div class="lee-mhead">Resolve notebook conflict<span class="sub">cell-aware disk / draft merge</span></div>` +
      `<div class="lee-notebook-merge">${Array.from({length: count}, (_, i) => `<section><header>Cell ${i + 1} · ${esc(lee.cells[i]?.cell_type || disk.cells?.[i]?.cell_type || 'code')}</header><div data-cell-merge="${i}"></div></section>`).join('')}</div>` +
      `<div class="lee-mfoot"><span class="lee-dim">Disk is left; the result saved to the notebook is right.</span><span class="lee-spacer"></span><button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save-merge>save merged notebook</button></div>`,
      null, () => merges.forEach(LeeCM.destroyMerge), {className:'lee-merge-modal', storageKey:'notebook-merge'});
    for (let i = 0; i < count; i++) {
      const view = lee.cells[i] && lee.editors.get(lee.cells[i].id);
      const draft = view ? LeeCM.getDoc(view) : (lee.cells[i]?.source || '');
      merges[i] = createMerge($(`[data-cell-merge="${i}"]`, m), {left: disk.cells?.[i]?.source || '', right: draft,
        lang: lee.cells[i]?.cell_type === 'markdown' ? 'markdown' : nbLang(), settings: lee.editorPrefs});
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
      if (added.length && !await nbEdit({op:'paste_many', i:lee.cells.length, cells:added})) return;
      m.remove(); await saveTab(false, null, true); status('merged notebook saved', 'ok');
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
  mergeView = createMerge($('.lee-merge-host', m), {left: disk.text || '', right: draft,
    lang: curLang(), settings: lee.editorPrefs});
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save-merge]', m).onclick = async () => {
    const result = LeeCM.mergeResult(mergeView), view = lee.editors.get('file');
    LeeCM.setDoc(view, result); rememberBuffer(lee.path, {path: lee.path, kind: 'text', text: result});
    m.remove(); await saveTab(false, null, true); status('merged file saved', 'ok');
  };
}
function showSaveConflict(message, theirs = []) {
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
  $('[data-merge]', box).onclick = () => openMergeConflict(box, theirs);
  $('[data-overwrite]', box).onclick = async () => { lee.heldSaveConflicts.delete(lee.path); box.remove(); await saveTab(false, null, true); };
  $('[data-disk]', box).onclick = async () => { lee.heldSaveConflicts.delete(lee.path); box.remove(); await takeDiskVersion(lee.path); status('loaded disk version; browser draft discarded', 'ok'); };
}
async function saveTab(quiet = false, expectedVersion = null, force = false) {
  // A document the browser renders has no editor behind it, so `getDoc` would be called on
  // nothing. Reporting success is honest: the file on disk is what is being shown.
  if (['pdf', 'image', 'office', 'audio', 'video'].includes(lee.kind)) {
    if (!quiet) status(`${{pdf: 'a PDF', image: 'an image', office: 'an office file', audio: 'an audio file', video: 'a video'}[lee.kind]} is read-only here`);
    return true;
  }
  let saveTabEl = $('.lee-tab.active');
  setTabSaveState(saveTabEl, 'saving');
  try {
    if (lee.activeEditor==='secondary' && lee.editors.get('secondary') && lee.secondaryPath) {
      const path=lee.secondaryPath,base_disk_version=draftBaseFor(path);
      const d=await post('/nb/save',{path,text:normalizeSavedText(LeeCM.getDoc(lee.editors.get('secondary'))),seq:nextSeq(),base_disk_version,force});
      noteSelfWrite(path);
      // Without this the pane saved and learned nothing, so the next edit began from the same
      // stale base and was refused all over again.
      await rebaseDrafts(path, recordDiskVersion(path, d.disk_version || diskVersionFor(path)));
      lee.buffers.delete(path);lee.dirtyBuffers.delete(path);await clearDrafts(path);
      saveTabEl = $$('.lee-tab').find(x=>x.title===path); saveTabEl?.classList.remove('dirty');
      setTabSaveState(saveTabEl, 'saved');
      if(!quiet)status(`saved ${path.split('/').pop()}`,'ok');return true;
    }
    // The tab being saved, held: a switch while the save is out must not clear the next tab's state.
    const tabKey = lee.tabKey, kind = lee.kind, cellKey = tabKey + ':';
    const edits = () => lee.tabEdits.get(tabKey) || 0;
    let editAt = expectedVersion ?? lee.editVersion, tabAt = edits();
    const bufferKeys = kind === 'notebook'
      ? [...lee.bufferTimers.keys()].filter(k => k.startsWith(cellKey))
      : [lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || ''];
    for (const k of bufferKeys) { clearTimeout(lee.bufferTimers.get(k)); lee.bufferTimers.delete(k); }
    let d;
    const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
    const base_disk_version = draftBaseFor(documentKey);
    if (kind === 'notebook') {
      const cells = changedRows(tabKey, lee.cells, nextSeq());
      await headingSynced(tabKey);
      d = await post('/nb/save', {tab: tabKey, cells, base_disk_version, force});
      noteSeen(tabKey, cells);
    } else {
      let text=normalizeSavedText(LeeCM.getDoc(lee.editors.get('file')));
      if(lee.filePrefs.formatOnSave){try{const formatted=await post('/editor/format',{path:lee.path,lang:curLang(),text});text=formatted.text;if(text!==LeeCM.getDoc(lee.editors.get('file')))LeeCM.setDoc(lee.editors.get('file'),text);editAt=expectedVersion??lee.editVersion;tabAt=edits();}catch(e){status(`format skipped: ${e.message||e}`,'err');}}
      d = await post('/nb/save', {tab: tabKey, text, seq: nextSeq(), base_disk_version, force});
    }
    const written = recordDiskVersion(documentKey, d.disk_version || diskVersionFor(documentKey));
    // A keystroke, fold or edit made while the save was out is not in what it wrote: the disk has its
    // snapshot, the tab stays dirty, and the newer draft is rebased on our own write so the next save
    // is not mistaken for an external conflict.
    if ((expectedVersion !== null && editAt !== lee.editVersion) || tabAt !== edits()) {
      await rebaseDrafts(documentKey, written);
      setTabSaveState(saveTabEl, 'pending', 'Changed while saving; not saved yet');
      return false;
    }
    const key = documentKey;
    if (kind === 'notebook') {
      for (const k of [...lee.buffers.keys()]) if (k.startsWith(cellKey)) {
        lee.buffers.delete(k); lee.dirtyBuffers.delete(k);
      }
    } else { lee.buffers.delete(key); lee.dirtyBuffers.delete(key); }
    await clearDrafts(documentKey);
    lee.heldSaveConflicts.delete(documentKey);
    saveTabEl?.classList.remove('dirty');
    setTabSaveState(saveTabEl, 'saved');
    if (!quiet) status('saved', 'ok');
    noteSelfWrite(documentKey, lee.path);
    refreshProjectPills();
    refreshOpenGitMarks();      // a notebook's marks are per cell, a file's per line
    if (lee.path?.endsWith('/pyproject.toml')) refreshPackageVersions();
    return true;
  } catch (e) {
    const message = String(e.message || e);
    setTabSaveState(saveTabEl, 'error', `Autosave failed: ${message}`);
    if (e.body?.kind === 'save_conflict' || message.includes('changed on disk after this browser draft began')) {
      const documentKey = lee.path || $('.lee-tab.active .lee-tab-name')?.textContent || '';
      if (!quiet || !lee.heldSaveConflicts.has(documentKey)) showSaveConflict(message, e.body?.cells || []);
    }
    else status(message, 'err');
    return false;
  }
}

/* Every JSON config here is written by a program and read by a person, so most arrive as one long
   line. The same formatter as format-on-save, asked for on purpose, editing the buffer rather than
   the file so it stays undoable. */
async function leeFormatDoc() {
  const view = lee.editors.get(lee.scope === 'exec' ? 'exec' : 'file');
  if (!view) return status('open a file to format', 'err');
  const text = LeeCM.getDoc(view), lang = curLang();
  try {
    const d = await post('/editor/format', {path: lee.path, lang, text});
    if (d.text === text) return status(`${lang} already formatted`, 'ok');
    LeeCM.setDoc(view, d.text);
    status(`formatted ${lang}${lee.path ? ' · ' + lee.path.split('/').pop() : ''} · save to keep it`, 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}
window.leeFormatDoc = leeFormatDoc;

async function saveAllTabs() {
  // The active editor is saved through the same version-checked path as ordinary autosave.
  // Inactive editors are mirrored to the server within 120ms, and pending mirrors are left to
  // arrive rather than cancelled, which would save the previous snapshot.
  if (!lee.kind) return status('nothing to save', 'err');
  if (!lee.path) return status('save the unnamed tab individually first', 'err');
  const activeDirty = !!$('.lee-tab.active.dirty');
  if (activeDirty && !await saveTab(true)) return;
  await new Promise(resolve => setTimeout(resolve, 140));
  await Promise.all([...lee.headingSync.values(), lee.nbQueue]);   // folds and edits still out are in what it writes
  try {
    const d = await post('/tabs/save-all'), saved = d.saved + (activeDirty ? 1 : 0);
    for (const tab of $$('.lee-tab')) {
      if (tab.classList.contains('dirty')) await clearDrafts(tab.title || $('.lee-tab-name', tab)?.textContent || '');
      tab.classList.remove('dirty'); setTabSaveState(tab, 'saved');
    }
    status(`saved ${saved} tab${saved === 1 ? '' : 's'}`, 'ok');
  } catch (e) {
    // A conflict is resolved in its own tab, where saving offers keep, merge, overwrite and load.
    if (e.body?.kind === 'save_conflict') takeSavedVersions(e.body);
    status(e.body?.kind === 'save_conflict' ? `${(e.body.paths || []).map(p => p.split('/').pop()).join(', ')} changed elsewhere · open the tab and save to choose what to keep` : e.message || String(e), 'err');
  }
}

// `/exec` runs in whatever runtime the open tab runs in, so a Rust notebook makes this box Rust.
// The placeholder is built at mount and the bundle exposes no way to rewrite one, so a language
// change remounts rather than saying `python` over a box that runs something else.
function execLang() {
  const lang = lee.kind === 'notebook' ? nbLang() : 'python';
  if (lee.execLang === lang) return;
  lee.execLang = lang;
  const v = lee.editors.get('exec');
  if (!v) return;                     // not mounted yet; `mountExec` reads `lee.execLang` itself
  LeeCM.destroy(v);
  lee.editors.delete('exec');
  mountExec();
}

function mountExec() {
  const host = $('#execbox'); if (!host || lee.editors.has('exec')) return;
  const lang = lee.execLang || 'python';
  const v = createEditor(host, {
    doc: '', lang, placeholder: `${lang} · ${displayChord('mod+enter')} runs · ${displayChord('ctrl+shift+up')}/↓ history`,
    completeUrl: '/complete', onDefinition: name => findDefinition(name),
    onSelection: () => { clearTimeout(selectionHelpTimer); selectionHelpTimer = setTimeout(showSelectionHelp, 120); },
  });
  lee.editors.set('exec', v);
  leeScope(lee.execScope);
  if (host.dataset.wired) return;     // a remount replaces the editor, not the box around it
  host.dataset.wired = '1';
  host.addEventListener('focusin', () => setScope('exec'));
  // An empty box hands Tab back to the page, so a keyboard walk passes through it. With code in it, Tab indents and Escape then Tab leaves.
  host.addEventListener('keydown', e => {
    if (e.key === 'Tab' && !e.altKey && !e.ctrlKey && !e.metaKey && !LeeCM.getDoc(lee.editors.get('exec')).trim()) e.stopPropagation();
  }, true);
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
    const r = await withPython(() => post('/exec', {code, path: lee.tabKey || '', scope: lee.execScope, frame_id: lee.debugState?.frame_id}));
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

async function leeVars() {
  const box = $('#vars'); if (!box || document.hidden) return;
  // Polling is a refresh, not a queue: coalesce every request that arrives while one is in
  // flight, or a slow inspector stacks fetches and full-tree DOM rebuilds without bound.
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
      // An install runs for minutes and the panel polls every 2.5 seconds; repainting would throw
      // away the disabled button and the progress line every poll.
      if (lee.varsInstalling) return;
      const pkgs = (d.packages || []).join(' and ');
      box.innerHTML = `<div class="lee-err"><strong>Dhrishti inspector unavailable</strong><span>${esc(d.error)}</span>` +
        (d.can_install ? `<button class="lee-btn go" data-install-inspector>Install ${esc(pkgs)} into this environment</button>` : '') +
        `<button class="lee-btn" data-repair-inspector>Restart kernel and repair</button></div>`;
      $('[data-repair-inspector]', box).onclick = async () => {
        if (!await confirmDialog('Restart kernel', 'Repairing the inspector restarts this kernel and clears its live variables.', 'restart and repair')) return;
        await post('/kernel/restart'); markPreviousRuns(); await leeVars(); refreshKernelPill();
      };
      const install = $('[data-install-inspector]', box);
      if (install) install.onclick = async () => {
        if (!await confirmDialog('Install into this environment',
            `Leela will install ${pkgs} into ${d.python}, then restart this kernel, which clears its live variables.`,
            'install and restart')) return;
        install.disabled = true; lee.varsInstalling = true;
        status(`installing ${pkgs} into ${d.python.split('/').slice(-3).join('/')}…`);
        try {
          await post('/runtime/inspector', {python: d.python});
          await post('/kernel/restart'); markPreviousRuns();
          status('inspector ready · live variables connected', 'ok');
        } catch (e) { status(String(e.message || e), 'err'); }
        finally { lee.varsInstalling = false; install.disabled = false; }
        await leeVars(); refreshKernelPill();
      };
      return;
    }
    if (d.python) paintEnv(String(d.python).split('/').slice(-3).join('/'));
    const envTag = $('#envtag');
    if (envTag && d.inspector) envTag.title = `${d.inspector} inspector · ${d.python || d.runtime}${d.cwd ? ' · cwd ' + d.cwd : ''}`;
  }

  // Every runtime gets its own view memory, so switching notebooks does not leak open rows and
  // the filter between them.
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

  // Most polls are identical, and rebuilding the whole variable DOM every 2.5 seconds competes
  // with CodeMirror selection and streamed Markdown painting.
  const fingerprint = JSON.stringify(d.groups || []);
  if (!lee.varRestore && lee.varFingerprints.get(runtime) === fingerprint) return;
  lee.varFingerprints.set(runtime, fingerprint);

  // A changed poll must not cost the user their place: remember what is open, what is selected
  // and where the panel is scrolled, re-render, then put all three back.
  const scroll = lee.varRestore ? lee.varRestore.scroll : box.scrollTop;
  const selName = lee.varRestore ? lee.varRestore.selected : selVar()?.dataset.name;
  lee.varRestore = null;
  const cur = {}, tpl = document.createElement('template'), frag = document.createDocumentFragment();
  const old = new Map([...box.querySelectorAll(':scope > .lee-vrow')].map(r => [r.dataset.key, [r, r.nextElementSibling]]));
  for (const g of d.groups || []) {
    if (g.label) frag.append(Object.assign(document.createElement('div'), {className: 'lee-vgroup', textContent: g.label}));
    for (const n of g.nodes || []) {
      cur[n.name] = n.value;
      const key = `${g.label || ''}\0${n.name}`, html = varRow(n), prev = old.get(key);
      if (prev && prev[0].dataset.sig === html) { frag.append(...prev); continue; }
      tpl.innerHTML = html;
      const [row, kids] = tpl.content.children;
      Object.assign(row.dataset, {key, sig: html});
      frag.append(row, prev && prev[1].id === kids.id ? prev[1] : kids);
    }
  }
  box.replaceChildren(frag.childElementCount ? frag : Object.assign(document.createElement('div'), {className: 'lee-dim', textContent: '(no variables yet)'}));
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
  // new/edited is a statement about the namespace, so it is for top-level names only. Tagging a
  // DataFrame's own `shape` as "(new)" is noise, as is the first render, where everything is new.
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
    const html = kids.map(k => varRow(k, 1)).join('');
    if (box.dataset.sig !== html) { box.innerHTML = html; box.dataset.sig = html; }
  } catch (e) { lee.varOpen.delete(acc); delete box.dataset.sig; box.innerHTML = `<div class="lee-err">${esc(e.message)}</div>`; }
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
  if (lee.varOpen.has(acc)) { lee.varOpen.delete(acc); box.innerHTML = ''; delete box.dataset.sig; return; }
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
    const r = await withPython(() => post('/vars/eval', {code, scope: lee.execScope}));
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
async function liveHas(name) {
  try {
    const d = await api('/vars?profile=minimal&sort=name&scope=live');
    return (d.groups || []).some(g => (g.nodes || []).some(n => n.name === name));
  } catch (e) { return false; }
}

/* Promoting over a live name cannot be undone, so the refusal is the server's own sentence and the
 * replace is a second, deliberate answer to it. Only the pane can send one: the agent's tool is
 * refused outright. */
async function promoteVar(replace) {
  const r = selVar(); if (!r) return status('select a variable first');
  let res;
  try { res = await post('/vars/promote?accessor=' + r.dataset.acc + (replace ? '&replace=1' : '')); }
  catch (e) {
    const refusal = String(e.message || e);
    if (replace || !await liveHas(r.dataset.name)) return status(refusal, 'err');
    if (!await confirmDialog('replace a live variable', refusal, 'replace it')) return status(refusal, 'err');
    return promoteVar(true);
  }
  res.ok ? (status('promoted ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}
function copyVar(what) {
  const r = selVar(); if (!r) return status('select a variable first');
  const txt = what === 'path' ? decodeURIComponent(r.dataset.acc) : r.querySelector('.lee-vval').textContent;
  navigator.clipboard?.writeText(txt);
  status('copied ' + what, 'ok');
}

