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
  cellObserver: null, lastDoc: null, buffers: new Map(), dirtyBuffers: new Set(), bufferTimers: new Map(),
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
function createEditor(el, opts = {}) { return LeeCM.create(el, {...opts, settings: {...lee.editorPrefs, ...(opts.settings||{})}}); }
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
  if (['run_python', 'inspect_python', 'list_vars', 'promote_var'].includes(tool)) return 'run';
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
  if (tool === 'promote_var') return `Give to user · ${short(a.name)}`;
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
function enhanceCodeBlocks(el) {
  for (const v of (el._leeCodeViews || [])) try { LeeCM.destroy(v); } catch {}
  el._leeCodeViews = [];
  $$('pre > code', el).forEach(code => {
    const pre = code.parentElement, text = code.textContent || '';
    const declared = [...code.classList].find(x => x.startsWith('language-')) || '';
    const lang = codeLang(declared);
    const python = /^(language-)?(py|python)$/.test(declared.toLowerCase());
    const named = declared.replace(/^language-/, '').toLowerCase();
    if (!declared || !CODE_LANGS[named] || text.length > 40000) return;
    const host = document.createElement('div'); pre.replaceWith(host);
    el._leeCodeViews.push(mountCodeSurface(host, text.replace(/\n$/, ''), lang,
                                           python && el.classList.contains('lee-reply')));
  });
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

async function openExternal(url) {
  if (!url) return status('choose a source first', 'err');
  if (!window.pywebview && window.open(url, '_blank', 'noopener,noreferrer')) return;
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
      if (!window.pywebview) return;
      e.preventDefault(); e.stopPropagation();
      openExternal(href);
    });
  });
}

/* A prompt cell stores its work log twice: as `calls`, and again at the end of `reply`. The renderer
   has no raw HTML, so the second copy read as literal `<details>` tags over an unrolled result. */
const WORK_LOG = /\n*<details>\s*<summary>\s*what i did[^<]*<\/summary>[\s\S]*<\/details>\s*$/i;
function stripWorkLog(text) { return String(text || '').replace(WORK_LOG, '').trimEnd(); }

function renderMarkdown(el, text, allowRaw = false, onRender = null) {
  if (!el) return;
  el.dataset.markdown = String(text || '');
  el._leeMarkdownSeq = (el._leeMarkdownSeq || 0) + 1;
  const seq = el._leeMarkdownSeq;
  clearTimeout(el._leeMarkdownTimer);
  el._leeMarkdownAbort?.abort();
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
        resolveMarkdownImages(el); routeMarkdownLinks(el);
        upgradePortableToolMarkdown(el); enhanceCodeBlocks(el); addMarkdownCellAction(el);
      });
    } catch (e) {
      if (e.name === 'AbortError' || seq !== el._leeMarkdownSeq || !el.isConnected) return;
      el.textContent = el.dataset.markdown;
      el.dataset.markdownWarnings = `renderer unavailable: ${e.message || e}`;
      if (!el._leeMarkdownReported) {
        el._leeMarkdownReported = true;
        console.warn('Leela markdown fallback:', e);
      }
    }
  }, 32);
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
  el.className = `lee-status ${tone}`;
  requestAnimationFrame(() => el.classList.add('show'));
  const ttl = tone === 'busy' ? 0 : tone === 'err' ? 8000 : tone === 'ok' ? 3200 : 5000;
  if (ttl) statusTimer = setTimeout(() => {
    if (el.textContent !== msg) return;
    el.classList.remove('show');
    setTimeout(() => { if (el.textContent === msg) { el.textContent = ''; el.hidden = true; } }, 220);
  }, ttl);
}

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
  // A glanceable contextual cheat sheet, not the full keymap. Help-only commands stay in the
  // searchable help and settings surfaces rather than pushing the file tree off screen.
  const local = lee.keys.filter(k => k.scope === scope && k.label && k.key && ['footer','toast'].includes(k.show)).slice(0, 8);
  const global = lee.keys.filter(k => k.scope === 'global' && k.show === 'toast' && k.label && k.key).slice(0, 4);
  const rows = local.concat(global);
  if (tag) tag.textContent = scope && scope !== 'global' ? `· ${scope}` : '';
  host.innerHTML = rows.length ? rows.map(k =>
    `<div class="lee-krow${k.scope === scope ? ' contextual' : ''}"><kbd>${esc(displayChord(k.key))}</kbd>` +
    `<span>${esc(k.label)}</span></div>`).join('') : '<div class="lee-dim">no keys in this context</div>';
}

/* One application-level keyboard router owns every app command. CodeMirror owns editing commands
 * and xterm owns pty input, and neither gets a duplicate copy of this map. The capturing listener
 * resolves an accepted app command before an editor can consume it. An unaccepted event continues
 * untouched. */
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'settings', 'toggle_left', 'toggle_right']);
const EDITING_SCOPES = new Set(['editor', 'exec', 'agent', 'term']);

function eventContext(e) {
  const path = e.composedPath ? e.composedPath() : [e.target];
  const inPath = selector => path.some(n => n instanceof Element && n.matches(selector));
  // Overlays own their keyboard while open, so commands behind a dialog never fire.
  if (inPath('.lee-modal, .lee-ctxmenu')) return 'overlay';
  if (inPath('#termwrap, .xterm')) return 'term';
  // A live page wants its own keyboard as much as a shell does, so the inline browser is routed
  // like the terminal. It has to come before `#editor`, which contains it.
  if (inPath('.lee-webview')) return 'web';
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
  // macOS reports Caps Lock remapped to Hyper as all four modifiers. Other platforms and some
  // Karabiner or browser combinations expose only Ctrl+Alt+Shift, where the Meta bit is not
  // portable. Hyper accepts either shape. Ordinary `mod` stays strict.
  if (c.hyper) {
    // Safari and Chrome occasionally omit either the synthetic Shift or the Meta bit for named
    // keys, so require the stable Ctrl+Alt pair plus one of the two high modifiers.
    if (!e.ctrlKey || !e.altKey || !(e.shiftKey || e.metaKey)) return false;
  } else {
    const wantCtrl = !!c.ctrl || (!!c.mod && !MAC);
    const wantMeta = !!c.mod && MAC;
    if (wantCtrl !== e.ctrlKey || wantMeta !== e.metaKey || !!c.alt !== e.altKey || !!c.shift !== e.shiftKey)
      return false;
  }
  // Matched by physical code where there is one: Karabiner and Hyper can transform `event.key`,
  // while `event.code` stays Enter, KeyR, ArrowDown.
  if (c.code && (c.mod || c.ctrl || c.alt || c.hyper)) return c.code === e.code;
  return c.key.toLowerCase() === (e.key || '').toLowerCase();
}

const firesInTextEntry = c => c.mod || c.ctrl || c.alt || /^F([1-9]|1[0-2])$/.test(c.key);
function findBinding(e, scope) {
  if (scope === 'overlay') return null;
  // `term` and `web` hand the keyboard to something that is not Leela, keeping only the chords
  // that get you back out.
  const allowed = (scope === 'term' || scope === 'web')
    ? k => k.scope === scope || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action)
    : k => k.scope === scope || k.scope === 'global';
  const guard = !EDITING_SCOPES.has(scope) && isTextEntry(e.target);
  for (const k of lee.keys) {
    if (!allowed(k)) continue;
    const chord = k.chords.find(c => chordMatches(c, e));
    if (!chord || (guard && !firesInTextEntry(chord))) continue;
    // Copy and Cut become whole-cell operations only when a notebook cell has no text selection.
    if (['cell_copy', 'cell_cut'].includes(k.action)) {
      if (lee.kind !== 'notebook') continue;
      const inEditor = e.composedPath?.().some(n => n instanceof Element && n.matches('.cm-editor'));
      const selection = curEditor() ? LeeCM.selection(curEditor()) : null;
      if (inEditor && selection?.from !== selection?.to) continue;
    }
    if (['cell_first', 'cell_last', 'cell_page_up', 'cell_page_down'].includes(k.action)
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
  if (!match) return;
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
  run_app:      () => runApp(),
  palette:      () => palette(),
  recent_tabs:  () => recentTabs(),
  save:         () => saveTab(),
  save_all:     () => saveAllTabs(),
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
  run_above:    () => runRange(0, lee.sel, 'cells above'),
  run_below:    () => runRange(lee.sel, lee.cells.length, 'this cell and below'),
  run_all:      () => runAll(),
  restart_run_all: () => restartRunAll(),
  run_file:     () => runFile(),
  run_selection: () => runSelection(),
  pick_kernel:  () => pickKernel(),
  new_notebook: () => htmxPost('/tab/new?kind=notebook'),
  edit_keys:    () => editKeys(),
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
    if (lee.kind === 'text') return status('nothing to undo outside a notebook');
    const r = await nbEdit({op: 'undo', i: lee.sel});
    focusCell(r.index ?? lee.sel); status('cell operation undone', 'ok');
  },
  notebook_redo: async () => {
    if (lee.kind === 'text') return status('nothing to redo outside a notebook');
    const r = await nbEdit({op: 'redo', i: lee.sel});
    focusCell(r.index ?? lee.sel); status('cell operation redone', 'ok');
  },
  cell_type:    async () => {
    const id = lee.cells[lee.sel]?.id;
    const r = await nbEdit({op: 'type', i: lee.sel, cycle: true});
    const at = Math.max(0, r.cells.findIndex(c => c.id === id));
    focusCell(at); status(`cell ${at + 1} is now ${r.cells[at]?.cell_type || 'code'}`, 'ok');
  },
  capture:      () => captureScreen(),
  cell_split:   async () => {
    const at = lee.sel, v = lee.editors.get(lee.cells[at].id);
    await nbEdit({op: 'split', i: at, offset: v ? LeeCM.cursor(v) : 0});
    focusCell(at + 1); status('cell split', 'ok');
  },
  cell_split_symbols: async () => {
    const at = lee.sel, was = lee.cells.length;
    const r = await nbEdit({op: 'split_symbols', i: at});
    const made = (r?.cells?.length ?? was) - was;
    if (!made) return status('no top-level class or function to split out', 'err');
    focusCell(at); status(`split into ${made + 1} cells`, 'ok');
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
  comment:      () => toggleComment(),
  complete:     () => kernelComplete(),
  ai_complete:  () => aiComplete(),
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
  new_dir:      () => newEntry('dir'),
  rename:       () => renameEntry(),
  delete:       () => deleteEntry(),
  open_folder:  () => openFolderWindow(),
  add_root:     () => addRoot(),
  find_repo:    () => findRepo(),
  remove_root:  () => removeRoot(),
  refresh_files: () => refreshFileTree(),
  show_hidden:  () => toggleHidden(),
  up_dir:       () => treeCollapse(),
  filter_files: () => status('filter the tree with ctrl+p'),

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
  agent_threads: () => $('#agentthreads')?.focus(),
  agent_send:   () => sendAgent(),
  agent_steer_force: () => sendAgent(true),
  agent_stop:   () => stopAgent(),
  agent_tools:  () => agentTools(),
  agent_fold_turn: () => foldAgentTurn(currentAgentTurn(), !currentAgentTurn()?.classList.contains('folded')),
  agent_fold_all: () => foldAgentTurns(!agentTurnCards().every(c => c.classList.contains('folded'))),

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
    try { const next = await gitDo('write_worktree', {path: data.path, content: data.mergeResult, before: data.worktreeBefore ?? null, ...at}), fresh = await api(gitUrl('/git/diff', {path: data.path, staged: false, ...at})); data.base = 'index'; data.head = 'worktree'; data.baseLabel = 'index'; data.headLabel = 'working tree'; data.left = fresh.left || ''; data.right = fresh.right || ''; data.patch = fresh.content || fresh.text || ''; data.rawPatch = fresh.text || ''; data.group = 'unstaged'; data.mergeResult = null; data.worktreeBefore = fresh.right || ''; gitUI.review = null; paintGitPill(next); await activateGitDiffTab(key); status(`${data.path} updated in the working tree`, 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  const body = host.querySelector('.lee-diff-document-body');
  if (data.binary || data.file?.binary) body.innerHTML = binaryDiffHtml(data);
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
  // `#tabbar` is an htmx swap target, so a failed swap can replace it with an error string and
  // take it out of the page. Every open after that fails on the missing element, so put it back.
  const old=$('#tabbar');
  if(old)old.replaceWith(fresh);
  else $('#header')?.insertBefore(fresh,$('.lee-tab-overflow')||null);
  htmx.process(fresh);
  await mountTab(path);await leeVars();refreshProjectPills();requestAnimationFrame(layoutTabs);
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

let mountTabVersion=0;
function saveTabLocation() {
  const view = curEditor(), key = lee.path || lee.tabKey;
  if (!view || !key) return;
  // A Map keeps a re-set key at its first insertion point, so the delete is what moves the key to
  // the end for the tail slice below.
  lee.locations.delete(key);
  lee.locations.set(key, {pos: LeeCM.cursor(view), scroll: view.scrollDOM.scrollTop,
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
  // `/tab/state` serves the cached copy and flags that the file has moved under it, which is what a
  // run of `nbdev-prepare` over an open notebook does. Nobody read the flag, so the tab showed the
  // version from before the run with nothing saying so.
  if (st.stale) noteStaleTab(st, recoveredDraft);
  // Only the tab's own editors are torn down. The exec strip belongs to the app, and destroying
  // it here would silently leave the box unmounted.
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  // A screencast is a live encode in Chrome while it runs, so leaving the tab stops it. The page
  // stays open and the tab reattaches on the way back.
  closeWebView();
  const host = $('#editor'); if (!host) return;
  lee.kind = st.kind; lee.path = st.path || ''; lee.tabKey = st.path || st.title || ''; lee.cells = st.cells || [];
  await loadSettings(st.lang || (st.kind === 'notebook' ? 'python' : ''));
  updateToolbarForKind(st.kind);
  rememberRecentTab(st);
  lee.diskVersion = st.disk_version || ''; lee.seenDiskVersion = lee.diskVersion;
  // Tab navigation always returns Run and Variables to that tab's private kernel.
  paintEnv('');
  // The empty state is authored once, in Python's `_empty_editor`, and shipped as a template.
  if (!st.kind) {
    host.replaceChildren($('#leeempty')?.content.cloneNode(true) ?? '');
    paintRecent();
    return;
  }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (st.kind === 'vault') await mountVault(host, st);
  else if (st.kind === 'vaultwb') await mountVaultWorkbench(host, st);
  else if (st.kind === 'web') mountWeb(host, st);
  else if (st.kind === 'pdf') mountPdf(host, st);
  else if (st.kind === 'image') mountImage(host, st);
  else if (st.kind === 'audio' || st.kind === 'video') mountMedia(host, st);
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
      // A notebook is a column of editors, each with its own line 1, so a location has to name
      // the cell. `cellIndex` is the fallback for cells with no ids of their own, written before
      // nbformat 4.5. The debug decorations are only for the debugger, since a search result is
      // somewhere to go rather than the line being executed.
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
          if (loc.column) { const at = view.state.doc.line(loc.line).from + loc.column; LeeCM.setSelection(view, at, at + String(loc.symbol || '').length); }
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
  status(`${name} changed on disk — reloading`, 'busy');
  takeDiskVersion(st.path).then(() => status(`${name} reloaded from disk`, 'ok'))
                          .catch(e => status(String(e.message || e), 'err'));
}
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

function mountMedia(host, st) {
  const name = (st.path || '').split('/').pop() || st.kind;
  const raw = '/file/raw/' + encodeURIComponent(name) + '?path=' + encodeURIComponent(st.path);
  const tag = st.kind === 'audio' ? 'audio' : 'video';
  host.innerHTML =
    `<div class="lee-doc"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-spacer"></span><a class="lee-btn" href="${esc(raw)}" target="_blank" rel="noopener noreferrer">open externally</a>` +
    `<a class="lee-btn" href="${esc(raw)}&download=true" download>download</a></div>` +
    `<div class="lee-doc-body lee-media-body"><${tag} class="lee-media" controls src="${esc(raw)}">` +
    `${esc(name)} could not be played by this browser.</${tag}></div></div>`;
}

async function mountFile(host, st) {
  const isProject = st.path?.endsWith('/pyproject.toml') || st.title === 'pyproject.toml';
  const crumbMode=lee.workbenchPrefs.breadcrumbs||'pathAndSymbols',crumb=crumbMode==='off'?'':`<nav class="lee-breadcrumbs" id="editorcrumbs" aria-label="File and symbol path"><span>${esc(compactPath(st.path||st.title||''))}</span></nav>`;
  // Markdown gets a rendered pane beside the editor. The editor stays mounted in every view and is
  // only hidden by CSS, so saving, autosave, blame, the change gutter and jump-to-line all keep
  // reaching `lee.editors.get('file')`.
  const isMd = (st.lang || '') === 'markdown';
  const view = isMd ? (localStorage.getItem('lee-md-view') || 'split') : '';
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
  let git = {ranges: []}, packages = null;
  if (st.path) {
    const requests = [api('/git/file?path=' + encodeURIComponent(st.path)).catch(() => git)];
    if (isProject && lee.workbenchPrefs.dependencyHints !== false) requests.push(api('/editor/packages?path=' + encodeURIComponent(st.path)).catch(() => null));
    [git, packages] = await Promise.all(requests);
  }
  lee.fileGit = git;
  const key = st.path || st.title;
  const v = createEditor($('#filecm'), {
    // A cached value is authoritative only after a real user edit, or a stale empty entry blanks
    // a freshly loaded file.
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
      // The preview follows the buffer, not the file. `renderMarkdown` is debounced and drops
      // superseded renders, so this is safe on every keystroke.
      if (isMd) renderMarkdown($('#mdpreview'), txt);
    },
  });
  lee.editors.set('file', v);
  if (isMd) {
    // The rendered pane carries the same change marks as the gutter, placed by block rather than
    // by line. Only this first render is annotated. See `paintMarkdownFileChanges`.
    renderMarkdown($('#mdpreview'), LeeCM.getDoc(v), false,
                   el => paintMarkdownFileChanges(el, git.ranges || []));
    $('#mdview').onclick = e => {
      const b = e.target.closest('[data-md-view]'); if (!b) return;
      const next = b.dataset.mdView;
      localStorage.setItem('lee-md-view', next);
      $('.lee-md-stage').dataset.view = next;
      $$('#mdview .lee-seg').forEach(x => x.classList.toggle('active', x === b));
      // The editor was display:none a moment ago, so CodeMirror has stale measurements and draws
      // the cursor in the wrong place until it re-measures.
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
  // Cell shells preserve the notebook's geometry, and CodeMirror is only created near the
  // viewport, so a 150-cell notebook paints immediately instead of constructing 150 editors in
  // one uninterruptible task.
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
  // Keep unchanged cell DOM and CodeMirror views alive. Moving those nodes is free and, unlike
  // rebuilding the notebook, cannot flash blank or reset the viewport.
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
      paintCellMeta(el, c, i);   // an insert above renumbers every cell after it
      const gutter = $('#g-' + c.id); if (gutter) gutter.textContent = gutterFor(c);
      const context = $('.lee-cell-context', el); if (context) paintCellContext(context, c);
      setCellState(c, cellState(c)); setCellTime(c, c.execution_ms, c.running);
      if (op === 'clear' || op === 'clear_cell') renderOutputs(c);
    }
    host.appendChild(el); // appending an existing node reorders it without remounting
  });
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

/* The banner says where a cell sits and how big it is. The gutter carries the execution count,
 * which is blank until the cell runs and renumbers on every rerun. */
const cellKind = (c) => ({code: 'py', markdown: 'md', prompt: 'prompt'}[c.cell_type] || c.cell_type);
const cellLines = (c) => String(c.source || '').split('\n').length;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
function cellMetaTitle(c, i) {
  const src = String(c.source || '');
  const rows = [`cell ${i + 1} of ${lee.cells.length} · ${c.cell_type} · ${plural(cellLines(c), 'line')}, ${src.length} chars`];
  if (c.cell_type === 'code')
    rows.push([c.execution_count == null ? 'not run' : `run ${c.execution_count}`,
               formatCellTime(c.execution_ms), plural((c.outputs || []).length, 'output')].filter(Boolean).join(' · '));
  rows.push(`id ${c.id}`, 'click to copy the id');
  return rows.join('\n');
}
function paintCellMeta(el, c, i) {
  const meta = el && $('.lee-cell-meta', el); if (!meta) return;
  $('.lee-cell-no', meta).textContent = '#' + (i + 1);
  $('.lee-cell-size', meta).textContent = `${cellKind(c)} · ${plural(cellLines(c), 'line')}`;
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
    `<button class="lee-cell-meta" data-cell-id="${esc(c.id)}" title="${esc(cellMetaTitle(c, i))}" ` +
    `onclick="event.stopPropagation();leeCopyCellId(this)">` +
    `<span class="lee-cell-no">#${i + 1}</span>` +
    `<span class="lee-cell-size">${esc(cellKind(c))} · ${esc(plural(cellLines(c), 'line'))}</span></button>` +
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
  // Only a docChanged transaction marks a buffer authoritative. A stale empty cache must never
  // replace the non-empty source `/tab/state` returned after running a cell.
  const source = lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source;
  c.source = source;
  const v = createEditor($('#cm-' + c.id), {
    doc: source, lang: c.cell_type === 'code' ? 'python' : c.cell_type === 'markdown' ? 'markdown' : '',
    placeholder: c.cell_type === 'prompt' ? `ask the inline model — ${displayChord('mod+enter')} answers in place` : '',
    completeUrl: c.cell_type === 'code' ? '/complete' : null,
    onDefinition: c.cell_type === 'code' ? name => findDefinition(name) : null,
    breakpoints: lee.breakpoints.get(c.id) || [],
    // Line numbers relative to this cell. A cell mounted after the marks arrived would otherwise
    // stay unmarked until the next save.
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
    for (const o of (c.outputs || [])) box.appendChild(outputEl(o));
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
    // Rich reprs get their own shadow root: pandas ships a <style> block with every DataFrame and
    // `scoped` has been dead for years, so an output could restyle the IDE around it. Very large
    // HTML stays unparsed until requested, because parsing a multi-megabyte table on the main
    // thread triggers Chrome's hang dialog.
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
  // CodeMirror focuses its own scroller but cannot reveal itself inside the notebook's outer
  // scroller, so the cell is scrolled into view here.
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
  // After the layout `scrollIntoView` just caused, or the measurement is of the old position.
  requestAnimationFrame(() => centreOnPos(v, pos));
}
function openLocation(hit) {
  // A hit in a notebook reports two coordinates: `line` in the .ipynb JSON, which is what ripgrep
  // and blame speak, and the cell plus the line inside it, which is the only pair an editor can
  // open. Prefer the second when the server placed the hit. A hit it could not place keeps the
  // file line rather than opening a cell chosen at random.
  const name = hit.path.split('/').pop();
  const inCell = Number(hit.cell_line) > 0;
  if (!inCell && /\.ipynb$/i.test(hit.path)) {
    // Nowhere to scroll to: the JSON line is not a line of any cell's editor, and jumping to it
    // inside whichever cell is selected would look like an answer.
    leeOpenFile(hit.path);
    return status(`${name} — line ${hit.line} of the notebook file is in no cell`, 'info');
  }
  const line = inCell ? Number(hit.cell_line) : hit.line;
  lee.pendingLocation = {path: hit.path, line, column: Number(hit.column || 0), symbol: hit.symbol || '',
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
    // Rendering must not make the source editor disappear permanently. The preview is evidence of
    // Run, and the source stays one click away.
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
    // Code run from a file-backed notebook has to be visible to code that reads that notebook
    // during the cell, such as indexers, nbdev and papermill. Flush the whole browser document
    // first, or a newly created .ipynb is still zero-byte on disk while its cell runs.
    // `saveTab` has already said why, in the status line or the conflict dialog. Repeating a
    // generic `save the notebook` over the top of it hid the only diagnosable part.
    if (lee.path && $('.lee-tab.active.dirty') && !await saveTab(true)) return;
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
      // Preserve the mounted cell object and its editor relationship.
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
        selectCell(i); const view = ensureCellMounted(i);
        LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line);
      }
    } else {
      const view = lee.editors.get('file');
      if (view) { LeeCM.setDebugLine(view, frame.line); paintDebugInlineValues(view, frame.line, state.variables); jumpToLine(frame.line); }
    }
    return;
  }
  // Library frames are outside the workspace sandbox. Ask by frame id, never by a browser path,
  // and show a read-only source view so step-in stays useful.
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

/* Running a prompt cell. The answer arrives in the cell rather than the pane below, so it saves
 * with the notebook and reads in order.
 *
 * The tab is deliberately not re-mounted afterwards, even though the assistant's tools may have
 * edited files: `/tab/state` reloads the notebook from disk, which would throw away the answer
 * that has not been saved yet. Files it changed are reported instead. */
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
  if (lee.kind !== 'text') return status('this is a notebook — run its cells, or “▶ all”', 'err');
  const path = lee.path || '';
  if (!path.endsWith('.py')) return status('only a .py file can be run — try “run selection”', 'err');
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
  const r = await post('/run/code', {code});
  const head = code.trim().split('\n')[0].slice(0, 60);
  execLine(head + (code.trim().includes('\n') ? ' …' : ''), r.text, r.ok);
  status(r.ok ? 'ran the selection' : 'the selection raised — see the exec log', r.ok ? 'ok' : 'err');
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

/* Two questions, two lists: which interpreter's packages this tab can import, and which launcher
 * runs it. Both restart the kernel, so what that costs is on screen while the choice is made. */
async function pickKernel() {
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
    `<div class="lee-dim">choosing either of these restarts the kernel — its variables are lost</div>` +
    `<h4>launcher</h4><div class="lee-modallist">${kinds}</div>` +
    `<h4>interpreter</h4><div class="lee-modallist">${pys}</div>` +
    engineSection(models) +
    `<div class="lee-runtime-cwd"><span>working directory</span><code>${esc(o.cwd || '')}</code>` +
    `<button class="lee-btn" id="kernelcwd">change</button></div>` +
    `<label class="lee-check-setting"><input type="checkbox" id="kernel-auto-manage"${o.auto_manage ? ' checked' : ''}> leela manages the runtime limit</label>` +
    `<div class="lee-dim">at the limit, closes the longest-idle runtime instead of asking</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="kernelattach">` +
    `${o.private ? 'attach to folder kernel' : 'give this tab its own kernel'}</button>` +
    `<span class="lee-dim">notebooks default to their own kernel; files share by folder</span></div>`);
  const clearWeights = m.querySelector('#clearengines');
  if (clearWeights) clearWeights.onclick = () => clearEngines(m);
  const reconnect = $('[data-kernel-reconnect]', m);
  if (reconnect) reconnect.onclick = async () => { await post('/kernel/restart'); m.remove(); status('kernel restarted', 'ok'); };
  m.querySelector('#kernel-auto-manage').onchange = async (e) => {
    try { e.target.checked = await setKernelAutoManage(e.target.checked); }
    catch (err) { e.target.checked = !e.target.checked; status(String(err.message || err), 'err'); }
  };
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
    const r = e.target.closest('.lee-mrow'); if (!r || r.dataset.engine) return;
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
    // Picking a runtime also makes its namespace the live variable source, so the panel must not
    // stay pinned, on screen or server-side, to the process watched before the switch.
    paintEnv('');
    status(`kernel: ${d.running_kind} · ${(d.python || 'leela’s own python').split('/').pop()} · variables connected`, 'ok');
    refreshKernelPill(); leeVars();
  });
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
const CHORD_SKIP = new Set(['Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Dead']);
function chordFromEvent(e) {
  if (CHORD_SKIP.has(e.key)) return '';
  const mac = navigator.platform.toLowerCase().includes('mac');
  const parts = [];
  if (mac ? e.metaKey : e.ctrlKey) parts.push('mod');
  if (mac && e.ctrlKey) parts.push('ctrl');
  if (e.altKey) parts.push('alt');
  if (e.shiftKey) parts.push('shift');
  const base = CHORD_BASE[e.key] || (e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase());
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
  mountTab();
}

/* Screen capture. The grab happens here because `getDisplayMedia` needs a user gesture and a real
 * display, and a server process has neither. The track is kept across captures, so only the first
 * press asks permission. */
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
  // A file is one document, not a column of cells, and a structural edit would split the buffer.
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
  if (lee.kind === 'notebook') return lee.cells[lee.sel]?.cell_type === 'markdown' ? 'markdown' : 'python';
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

const diffHtml = (rows) => rows.map(r =>
  `<div class="lee-drow ${r.kind}"><span class="lee-dnum">${r.line || ''}</span>` +
  `<span class="lee-dtext">${esc(r.text)}</span></div>`).join('');

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
      await mountTab();
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
  // A document the browser renders has no editor behind it, so `getDoc` would be called on
  // nothing. Reporting success is honest: the file on disk is what is being shown.
  if (lee.kind === 'pdf' || lee.kind === 'image') {
    if (!quiet) status(`${lee.kind === 'pdf' ? 'a PDF' : 'an image'} is read-only here`);
    return true;
  }
  let saveTabEl = $('.lee-tab.active');
  setTabSaveState(saveTabEl, 'saving');
  try {
    if (lee.activeEditor==='secondary' && lee.editors.get('secondary') && lee.secondaryPath) {
      const path=lee.secondaryPath,base_disk_version=draftBaseFor(path);
      const d=await post('/nb/save',{path,text:normalizeSavedText(LeeCM.getDoc(lee.editors.get('secondary'))),base_disk_version,force});
      noteSelfWrite(path);
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
    // An autosave request can finish after another keystroke. The disk has its snapshot, but the
    // newer browser buffer stays authoritative and schedules the next save.
    if (expectedVersion !== null && expectedVersion !== lee.editVersion) {
      // This request wrote an older snapshot, and newer typing is still in the editor and
      // IndexedDB. Rebase that draft on our own disk write, or the follow-up autosave is mistaken
      // for an external conflict.
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
    noteSelfWrite(documentKey, lee.path);
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
  try {
    const d = await post('/tabs/save-all'), saved = d.saved + (activeDirty ? 1 : 0);
    for (const tab of $$('.lee-tab')) {
      if (tab.classList.contains('dirty')) await clearDrafts(tab.title || $('.lee-tab-name', tab)?.textContent || '');
      tab.classList.remove('dirty'); setTabSaveState(tab, 'saved');
    }
    status(`saved ${saved} tab${saved === 1 ? '' : 's'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}

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

