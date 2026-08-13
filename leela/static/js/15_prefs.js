/* ---------------------------------------------------------- web preferences */
const THEMES = ['system', 'dark', 'light', 'cursor'];
function applyTheme(theme) {
  theme = THEMES.includes(theme) ? theme : 'cursor';
  localStorage.setItem('lee-theme', theme);
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme === 'system' ? 'light dark' : theme === 'cursor' ? 'light' : theme;
  const pill = $('#themepill'); if (pill) pill.textContent = theme;
  for (const t of lee.terms.values()) t.view.retheme();
}
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
        originalTheme = localStorage.getItem('lee-theme') || 'cursor';
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
  const themeBlurb = t => t === 'system' ? 'follow your device' : t === 'cursor' ? 'thin light chrome' : t + ' interface';
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
    `<div class="lee-theme-options">${THEMES.map(t=>`<button class="lee-theme-choice${t===originalTheme?' active':''}" data-theme="${t}"><span class="lee-theme-swatch ${t}"></span><strong>${t}</strong><span>${themeBlurb(t)}</span></button>`).join('')}</div>` +
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
  $$('[data-theme]',m).forEach(b=>b.onclick=()=>{applyTheme(b.dataset.theme);$$('[data-theme]',m).forEach(x=>x.classList.toggle('active',x===b));});
  $('[data-reset]',m).onclick=async()=>{const section=page==='appearance'?'editor':page; if(!sections[section])return;await post('/settings/reset',{scope:scope.value,section,language:language.value});saved=true;m.remove();applyEditorPrefs(EDITOR_DEFAULTS);setTimeout(editorSettings,0);};
  $('[data-cancel]',m).onclick=()=>m.remove();
  $('[data-save]',m).onclick=async()=>{update();let count=0;for(const [section,values] of Object.entries(sections)){const changed=Object.fromEntries(Object.entries(values).filter(([key,value])=>value!==initialSections[section][key]));if(Object.keys(changed).length){await post('/settings/save',{scope:scope.value,language:language.value,section,values:changed});count+=Object.keys(changed).length;}}localStorage.setItem('lee-settings-save-scope',scope.value);localStorage.setItem('lee-settings-language-scope',language.value);localStorage.removeItem('lee-editor-settings');await loadSettings(language.value);saved=true;m.remove();status(`${count||'no'} setting${count===1?'':'s'} saved to ${scope.value} · ${language.value||'all languages'} (${lee.settingsMeta?.paths?.[scope.value]||''})`,'ok');};
  $('[data-open-keys]',m).onclick=()=>{saved=true;m.remove();editKeys();};
  $('[data-open-runs]',m).onclick=()=>{saved=true;m.remove();editRuns();};
}
function leeTheme() { editorSettings(); }
window.leeTheme = leeTheme; window.leeEditorSettings = editorSettings;

