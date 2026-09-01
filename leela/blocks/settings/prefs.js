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
// Density is its own axis, so the tight chrome can be had with another family's colours.
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
const themeText = theme => {const {family, mode, density} = parseTheme(theme); return `${family}:${mode}:${density}`;};
async function saveTheme(theme, scope = 'user') {
  "Write the theme to settings.json. Never under `languages.<lang>`: a theme is not per language."
  const value = themeText(theme);
  await post('/settings/save', {scope, language: '', section: 'appearance', values: {theme: value}});
  lee.appearancePrefs = {...lee.appearancePrefs, theme: value};
}
/* `localStorage` is per origin and Leela's port moves whenever 5001 is taken, so a theme kept only
   there is gone on the next launch. settings.json is the theme; `lee-theme` is the first-paint
   cache the boot script in `app.py` reads, and the store one already-set theme is migrated from. */
function readTheme() {
  const durable = lee.appearancePrefs?.theme ?? lee.workbenchPrefs?.theme,
        cached = localStorage.getItem('lee-theme');
  if (!durable && cached && cached !== THEME_DEFAULT) saveTheme(cached).catch(() => {});
  return parseTheme(durable || cached);
}
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
  localStorage.setItem('lee-theme', `${family}:${mode}:${density}`);   // the cache, not the record
  paintTheme();
}
// Following the system means following it now, not at the next reload.
darkQuery().addEventListener('change', () => { if (lee.theme?.mode === 'system') paintTheme(); });
async function editorSettings(languageScope = null) {
  if(typeof languageScope!=='string'){
    // Default to All languages, never to the focused tab's language. Saving remembers the scope,
    // so one derived from `curLang()` would send every later edit into `languages.<lang>`. A
    // language scope is only ever chosen explicitly.
    const remembered=localStorage.getItem('lee-settings-language-scope');
    languageScope=remembered!==null?remembered:'';
  }
  const rememberedScope=localStorage.getItem('lee-settings-save-scope')||'user';
  await loadSettings(languageScope);
  const original = {...lee.editorPrefs}, originalFiles = {...lee.filePrefs},
        originalWorkbench = {...lee.workbenchPrefs}, originalDebug = {...lee.debugPrefs},
        originalTheme = lee.theme || readTheme();
  let saved = false, previewView = null;
  const selected = (value, current) => value === current ? ' selected' : '';
  const prefsOf = section => section === 'editor' ? lee.editorPrefs : section === 'files' ? lee.filePrefs :
    section === 'workbench' ? lee.workbenchPrefs : section === 'backups' ? (lee.backupPrefs || {}) :
    section === 'agent' ? (lee.agentPrefs || {}) : lee.debugPrefs;
  const checked = (section, key) => prefsOf(section)[key] ? ' checked' : '';
  const fontSelect = CODE_FONTS.map(([name, detail]) =>
    `<option value="${esc(name)}"${selected(name, lee.editorPrefs.fontFamily)}>${esc(name)} — ${esc(detail)}</option>`).join('');
  const field = (section, key, label, input, help='') => `<label>${label}${input.replace('data-setting', `data-pref-section="${section}" data-pref="${key}"`)}${help ? `<small>${help}</small>` : ''}</label>`;
  const check = (section, key, label, help='') => `<label class="lee-settings-toggle"><input type="checkbox" data-pref-section="${section}" data-pref="${key}"${checked(section,key)}><span>${label}${help ? `<small>${help}</small>` : ''}</span></label>`;
  const select = (section, key, label, values, help='') => field(section,key,label,
    `<select class="lee-select" data-setting>${values.map(([value,text]) => `<option value="${value}"${selected(value,prefsOf(section)[key])}>${text}</option>`).join('')}</select>`,help);
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
    `<div class="lee-settings-shadow" data-settings-shadow hidden></div>` +
    `<div class="lee-settings-layout"><nav class="lee-settings-nav" aria-label="Settings sections">` +
    `<button class="active" data-settings-page="editor">Text editor</button><button data-settings-page="appearance">Appearance</button>` +
    `<button data-settings-page="files">Files & save</button><button data-settings-page="debug">Run & debug</button>` +
    `<button data-settings-page="agent">Agent</button>` +
    `<button data-settings-page="environment">Environment</button>` +
    `<button data-settings-page="backups">Backups</button>` +
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
    `<div class="lee-settings-group"><h4>Opening folders</h4><div class="lee-settings-grid">` +
    `<label class="wide">Where the folder picker starts<input class="lee-input" data-pref-section="workbench" data-pref="projectFolder" value="${esc(lee.workbenchPrefs.projectFolder||'')}" placeholder="~/code"><small>Empty falls back to ~/code, then your home folder.</small></label></div></div>` +
    `<div class="lee-setting-row"><span><strong>Crash recovery</strong><small>Unsaved drafts stay in IndexedDB and external writes require review.</small></span><span class="lee-setting-state">always on</span></div></section>` +
    `<section data-settings-section="debug" hidden><h3>Run & debug</h3><p>Defaults for notebook DAP and direct debugpy sessions.</p><div class="lee-settings-checks">` +
    `${check('debug','justMyCode','Just my code')}${check('debug','stopOnEntry','Stop on entry')}${check('debug','subProcess','Debug subprocesses')}${check('debug','showInlineValues','Inline paused values')}${check('debug','breakOnRaised','Break on raised exceptions')}${check('debug','breakOnUncaught','Break on uncaught exceptions')}</div>` +
    `<div class="lee-setting-row"><span><strong>debugpy</strong><small>Python files, modules, tests, applications, and attach sessions use the selected project interpreter.</small></span><button class="lee-btn" data-open-runs>Run configurations…</button></div></section>` +
    `<section data-settings-section="agent" hidden><h3>Agent</h3>` +
    `<p>Where this agent's durable conversations live. Ramabana writes the log, the session names, ` +
    `the branches and the plans from the same code Leela drives, so one folder can serve both: ` +
    `point this at Ramabana's config dir and the conversations you had in the CLI are the ` +
    `conversations you see here.</p>` +
    `<div class="lee-settings-grid"><label class="wide">Conversation folder` +
    `<input class="lee-input" data-pref-section="agent" data-pref="configFolder" spellcheck="false" ` +
    `placeholder="${esc(lee.settingsMeta?.paths?.user?.replace(/settings\.json$/, '') || '')}" ` +
    `value="${esc(lee.agentPrefs?.configFolder || '')}">` +
    `<small>Empty means Leela's own config dir, which is where it has always been. ` +
    `Backups and the pre-write copy follow this folder. Conversations already open keep the folder ` +
    `they started in, so restart Leela after changing it.</small></label></div></section>` +
    `<section data-settings-section="backups" hidden><h3>Backups</h3>` +
    `<p>Dated copies of what cannot be rebuilt: conversations and their titles, branches, notes, ` +
    `workspaces, keymaps and settings. A copy is also taken before anything overwrites the ` +
    `conversation log, whatever the cadence says.</p>` +
    `<div class="lee-settings-group"><div class="lee-settings-grid">` +
    select('backups','cadence','Cadence',[['off','Off (pre-write copies only)'],['hourly','Hourly'],['sixhourly','Every six hours'],['daily','Daily'],['weekly','Weekly']],'How often a dated copy is taken while Leela is running.') +
    field('backups','keepNewest','Keep newest',`<input class="lee-input" data-setting type="number" min="1" max="50" value="${lee.backupPrefs?.keepNewest??5}">`) +
    `<label class="wide">Age bands (days)<input class="lee-input" data-pref-section="backups" data-pref="ageBands" value="${esc(lee.backupPrefs?.ageBands||'2,14,60')}"><small>One copy is kept inside each band, so a mistake noticed weeks later still has something to go back to.</small></label>` +
    `</div></div>` +
    `<div class="lee-settings-group"><h4>What a copy holds</h4>` +
    `<div class="lee-settings-checks" data-backup-entries>reading…</div>` +
    `<small>Anything unticked is not copied. Journals alone are tens of megabytes; the vault is a live database outside the config dir.</small></div>` +
    `<div class="lee-setting-row"><span><strong>Take one now</strong><small data-backup-dir></small></span>` +
    `<button class="lee-btn" data-backup-now>Back up now</button></div>` +
    `<div class="lee-settings-group"><h4>Restore</h4><div data-backup-list class="lee-backup-list">reading…</div></div></section>` +
    `<section data-settings-section="environment" hidden><h3>Environment</h3>` +
    `<p>What Leela exports to the models, the kernels and the terminals it starts. Leela asks your ` +
    `shell for these at startup; anything set here is used instead, which is the way out when ` +
    `asking the shell gives the wrong answer.</p>` +
    `<div class="lee-settings-group"><div data-env-list class="lee-env-list">reading…</div></div>` +
    `<div class="lee-settings-group"><h4>Add or replace</h4><div class="lee-settings-grid">` +
    `<label>Name<input class="lee-input" data-env-key placeholder="OPENAI_API_KEY" spellcheck="false"></label>` +
    `<label>Value<input class="lee-input" data-env-value type="password" autocomplete="off" spellcheck="false"></label>` +
    `</div><div class="lee-setting-row"><span data-env-note class="lee-dim"></span>` +
    `<button class="lee-btn go" data-env-save>Set variable</button></div></div></section>` +
    `<section data-settings-section="keys" hidden><h3>Keybindings</h3><p>Every command can be rebound from the same single-source keymap.</p><button class="lee-btn" data-open-keys>Edit keybindings…</button></section>` +
    `</div></div><div class="lee-mfoot"><button class="lee-btn" data-reset>Reset this section</button><span class="lee-spacer"></span><button class="lee-btn" data-cancel>Cancel</button><button class="lee-btn go" data-save>Save settings</button></div>`,
    null,()=>{if(previewView)LeeCM.destroy(previewView);if(!saved){applyEditorPrefs(original);lee.filePrefs=originalFiles;lee.workbenchPrefs=originalWorkbench;lee.debugPrefs=originalDebug;applyTheme(originalTheme);}},
    {className:'lee-settings-modal',storageKey:'settings'});
  api('/lsp/status').then(d=>{const el=$('[data-lsp-state]',m);if(el){el.textContent=d.available?(d.alive?'connected':'available'):'optional';el.title=d.note||'';}}).catch(()=>{});
  await document.fonts.ready;
  previewView=createEditor($('#settingspreview',m),{doc:'# Programming ligatures and line guides\nfrom pathlib import Path\n\ndef compare(left: int, right: int) -> bool:\n    return left != right and left <= 100  # => result\n',lang:'python',lineNums:true});
  const sections={editor:lee.editorPrefs,files:lee.filePrefs,workbench:lee.workbenchPrefs,debug:lee.debugPrefs,backups:lee.backupPrefs||{},agent:lee.agentPrefs||{}};
  const initialSections=Object.fromEntries(Object.entries(sections).map(([name,values])=>[name,{...values}]));
  const update=()=>{$$('[data-pref]',m).forEach(input=>{const target=sections[input.dataset.prefSection];target[input.dataset.pref]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;});
    const entries=$$('[data-backup-entry]',m); if(entries.length)sections.backups.include=entries.filter(b=>b.checked).map(b=>b.dataset.backupEntry);
    applyEditorPrefs(sections.editor);LeeCM.configure(previewView,sections.editor);};
  $$('[data-pref]',m).forEach(input=>input.addEventListener('input',update));
  let page='editor';
  $$('[data-settings-page]',m).forEach(button=>button.onclick=()=>{page=button.dataset.settingsPage;$$('[data-settings-page]',m).forEach(x=>x.classList.toggle('active',x===button));$$('[data-settings-section]',m).forEach(x=>x.hidden=x.dataset.settingsSection!==page);paintSettingsOrigins();});
  /* Which layer supplies a value is the one thing this panel could not say, and the reason
     "I saved it to user and nothing happened" is a fair thing to think: a `languages.python` block
     in the same file beats the plain section, and a workspace file beats both. The server has
     always worked this out; `describe` returns it as `origins` and nothing read it. */
  const ORIGIN_RANK = target => ({default: 0, user: 1, workspace: 2}[target] ?? (target.startsWith('workspace:') ? 4 : 3));
  // Every layer holding the key, not just the one in charge: a `languages.python` block is
  // invisible from the all-languages view, and that is exactly the case worth warning about.
  const layersOf = (section, key) => lee.settingsMeta?.layers?.[section]?.[key] || [];
  const originOf = (section, key) =>
    layersOf(section, key).slice().sort((a, b) => ORIGIN_RANK(a) - ORIGIN_RANK(b)).pop()
    || lee.settingsMeta?.origins?.[section]?.[key] || 'default';
  const savingAs = () => scope.value + (language.value ? ':' + language.value : '');
  function paintSettingsOrigins() {
    const here = ORIGIN_RANK(savingAs()), over = new Map();
    for (const input of $$('[data-pref]', m)) {
      const section = input.dataset.prefSection, origin = originOf(section, input.dataset.pref);
      const row = input.closest('label') || input.parentElement;
      $('[data-origin]', row)?.remove();
      if (origin === 'default') continue;
      const beats = ORIGIN_RANK(origin) > here;
      row.insertAdjacentHTML('beforeend',
        `<small data-origin class="lee-origin${beats ? ' beats' : ''}" title="${beats
          ? 'set in ' + esc(origin) + ', which is more specific than what you are saving to, so it wins'
          : 'the value in effect comes from ' + esc(origin)}">from ${esc(origin)}</small>`);
      if (beats && input.offsetParent !== null) over.set(origin, (over.get(origin) || 0) + 1);
    }
    const note = $('[data-settings-shadow]', m); if (!note) return;
    note.hidden = !over.size;
    if (!over.size) return;
    const [origin, n] = [...over.entries()][0];
    note.innerHTML = `<span><strong>${n} of these come from ${esc(origin)}</strong>` +
      `<small>More specific than ${esc(savingAs())}, so it wins whatever you save here. ` +
      `Saving to all languages does not clear it.</small></span>` +
      `<button class="lee-btn" data-clear-shadow="${esc(origin)}">Clear ${esc(origin)} for this section</button>`;
    $('[data-clear-shadow]', note).onclick = async () => {
      const [oscope, olang] = origin.split(':');
      const section = page === 'appearance' ? 'editor' : page;
      if (!sections[section]) return status('nothing to clear on this page', 'err');
      try {
        await post('/settings/reset', {scope: oscope, section, language: olang || ''});
        await loadSettings(language.value);
        status(`${origin} cleared for ${section}`, 'ok');
        saved = true; m.remove(); setTimeout(() => editorSettings(language.value), 0);
      } catch (e) { status(String(e.message || e), 'err'); }
    };
  }
  const scope=$('[data-settings-scope]',m),language=$('[data-settings-language]',m),path=$('[data-settings-path]',m),target=$('[data-settings-target]',m);
  const paintPath=()=>{path.textContent=lee.settingsMeta?.paths?.[scope.value]||'';target.textContent=`${scope.value} · ${language.value||'all languages'}`;paintSettingsOrigins();};
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
  $('[data-reset]',m).onclick=async()=>{const targets=page==='appearance'?['appearance','editor']:[page]; if(!targets.every(t=>t==='appearance'||sections[t]))return;for(const section of targets)await post('/settings/reset',{scope:scope.value,section,language:section==='appearance'?'':language.value});saved=true;m.remove();applyEditorPrefs(EDITOR_DEFAULTS);setTimeout(editorSettings,0);};
  $('[data-cancel]',m).onclick=()=>m.remove();
  const same=(a,b)=>Array.isArray(a)||Array.isArray(b)?JSON.stringify(a)===JSON.stringify(b):a===b;
  $('[data-save]',m).onclick=async()=>{update();let count=0;for(const [section,values] of Object.entries(sections)){const changed=Object.fromEntries(Object.entries(values).filter(([key,value])=>!same(value,initialSections[section][key])));if(Object.keys(changed).length){await post('/settings/save',{scope:scope.value,language:language.value,section,values:changed});count+=Object.keys(changed).length;}}const themeSaved=themeText(lee.theme)!==themeText(originalTheme);if(themeSaved){await saveTheme(lee.theme,scope.value);count++;}localStorage.setItem('lee-settings-save-scope',scope.value);localStorage.setItem('lee-settings-language-scope',language.value);localStorage.removeItem('lee-editor-settings');await loadSettings(language.value);saved=true;m.remove();status(`${count||'no'} setting${count===1?'':'s'} saved to ${scope.value} · ${language.value||'all languages'} (${lee.settingsMeta?.paths?.[scope.value]||''})${themeSaved&&language.value?', and the theme to all languages':''}`,'ok');};
  /* A secret's value never comes back from the server, so a row says that it is set, not what it is. */
  const paintEnv=async(d=null)=>{
    const list=$('[data-env-list]',m); if(!list) return;
    try{ d=d||await api('/settings/env'); }catch(e){ list.textContent=String(e.message||e); return; }
    $('[data-env-note]',m).textContent=d.note||'';
    list.innerHTML=(d.entries||[]).map(e=>`<div class="lee-env-row"><span><strong>${esc(e.key)}</strong>`+
      `<small>${e.set?(e.secret?'set':esc(e.value)):'not set'}${e.source?` · ${esc(e.source)}`:''}</small></span>`+
      (e.removable?`<button class="lee-btn" data-env-remove="${esc(e.key)}">Remove</button>`:'')+`</div>`).join('');
    $$('[data-env-remove]',m).forEach(b=>b.onclick=async()=>{
      try{ paintEnv(await post('/settings/env/remove',{key:b.dataset.envRemove})); status(`${b.dataset.envRemove} removed`,'ok'); }
      catch(e){ status(String(e.message||e),'err'); }});
  };
  $('[data-env-save]',m).onclick=async()=>{
    const key=$('[data-env-key]',m).value.trim(), value=$('[data-env-value]',m).value;
    try{ const d=await post('/settings/env/save',{key,value});
      $('[data-env-key]',m).value=''; $('[data-env-value]',m).value='';
      paintEnv(d); status(`${key} set`,'ok'); }
    catch(e){ status(String(e.message||e),'err'); }};
  paintEnv();
  /* Restoring is a write over live state, so the list says what each copy holds and asks first. */
  const paintBackups=async()=>{
    const list=$('[data-backup-list]',m); if(!list) return;
    let d; try{ d=await api('/backups'); }catch(e){ list.textContent=String(e.message||e); return; }
    $('[data-backup-dir]',m).textContent=d.dir;
    /* Painted once: a repaint after a run would drop ticks the person has not saved yet. */
    const chooser=$('[data-backup-entries]',m);
    if(chooser&&!$('[data-backup-entry]',chooser)){
      chooser.innerHTML=(d.entries||[]).map(e=>`<label class="lee-settings-toggle">`+
        `<input type="checkbox" data-backup-entry="${esc(e.name)}"${e.chosen?' checked':''}>`+
        `<span>${esc(e.label)}<small>${esc(e.name)}</small></span></label>`).join('');
      chooser.addEventListener('change',update);
    }
    if(!d.backups.length){ list.innerHTML='<div class="lee-dim">no copies yet</div>'; return; }
    list.innerHTML=d.backups.map(b=>`<div class="lee-backup-row"><span><strong>${esc(b.name)}</strong>`+
      `<small>${b.files} file${b.files===1?'':'s'} · ${Math.max(1,Math.round(b.bytes/1024))} KB`+
      `${b.archived?'':' · uncompressed'}${b.reason?` · ${esc(b.reason)}`:''}`+
      `${b.entries&&b.entries.length?`<br>${esc(b.entries.join(', '))}`:''}</small></span>`+
      `<button class="lee-btn" data-restore="${esc(b.name)}">restore</button></div>`).join('');
    $$('[data-restore]',list).forEach(button=>button.onclick=async()=>{
      const name=button.dataset.restore;
      if(!await confirmDialog('Restore this backup',
        `Put the copy from ${name} back over the current conversations, notes and settings? `+
        `A copy of what it replaces is kept first.`,'restore')) return;
      try{ const out=await post('/backups/restore',{name});
           status(`restored ${out.restored.length} item(s) from ${name} · ${out.note}`,'ok'); }
      catch(e){ status(String(e.message||e),'err'); }
    });
  };
  $('[data-backup-now]',m).onclick=async()=>{
    try{ const out=await post('/backups/run',{reason:'asked for'});
         status(out.name?`backed up as ${out.name}`:'nothing to back up yet','ok'); await paintBackups(); }
    catch(e){ status(String(e.message||e),'err'); }
  };
  paintBackups();
  $('[data-open-keys]',m).onclick=()=>{saved=true;m.remove();editKeys();};
  $('[data-open-runs]',m).onclick=()=>{saved=true;m.remove();editRuns();};
}
function leeTheme() { editorSettings(); }
window.leeTheme = leeTheme; window.leeEditorSettings = editorSettings;

