"Layered, validated IDE settings: defaults, then user, then workspace, then language."
from __future__ import annotations

import json
from copy import deepcopy
from fastcore.all import Path, atomic_save

from ... import leela_cfg
from ...core.backups import ENTRIES as BACKUP_ENTRIES, PRECIOUS

__all__ = ['DEFAULT_SETTINGS', 'Settings', 'user_settings_file', 'WORKSPACE_SETTINGS_FILE',
           'CODE_FOLDER', 'agent_cfg', 'start_folder', 'THEME_DEFAULT', 'theme_backgrounds', 'parse_theme',
           'theme_background']

#: Where the folder picker starts when nothing else names a folder. Home is mostly not projects.
CODE_FOLDER = '~/code'

WORKSPACE_SETTINGS_FILE = '.leela/settings.json'

# A call, not a constant: `leela_cfg` moves under a test, and a path fixed at import writes into
# somebody else's run. One expression, so redirecting it redirects every read and write.
def user_settings_file(): return Path(leela_cfg)/'settings.json'

DEFAULT_SETTINGS = {
    'editor': {
        'fontFamily': 'JetBrains Mono', 'fontSize': 13, 'lineHeight': 1.5,
        'ligatures': True, 'tabSize': 4, 'useTabs': False, 'detectIndentation': True,
        'wordWrap': 'off', 'wrapIndent': 'same', 'lineLength': 100,
        'guideColumns': '88', 'visualGuides': True, 'bracketMatching': True,
        'bracketColors': False, 'closeBrackets': True, 'activeLine': True,
        'overviewMode': 'long', 'overviewThreshold': 120, 'stickyNavigation': True,
        'lineNumbers': 'absolute', 'renderWhitespace': 'selection', 'indentGuides': True,
        'highlightSelection': True, 'methodSeparators': False, 'cursorStyle': 'line',
        'cursorBlinking': 'blink', 'scrollPastEnd': False, 'smoothScrolling': True,
        'scrollMargin': 3, 'folding': True, 'quickSuggestions': True,
        'parameterHints': True, 'inlayHints': True,
    },
    'files': {
        'autoSave': 'afterDelay', 'autoSaveDelay': 900, 'trimTrailingWhitespace': False,
        'trimFinalNewlines': False, 'insertFinalNewline': True, 'formatOnSave': False,
        'formatOnPaste': False, 'formatOnType': False, 'respectGitignore': True,
        'confirmDelete': True,
    },
    'workbench': {
        'breadcrumbs': 'pathAndSymbols', 'restoreEditors': True,
        'problemsScope': 'workspace', 'dependencyHints': True,
        'projectFolder': '',            # where the folder picker starts; empty means find one
        # Split is how a markdown file has always opened; the setting names it, it does not change it.
        'showHiddenFiles': False, 'markdownView': 'split', 'pinnedPanes': [],
    },
    #: Its own section so that resetting how Leela looks does not reach the folder picker or the
    #: breadcrumbs beside it. `theme` is `family:mode:density`; empty is the browser's own default.
    'appearance': {'theme': ''},
    'debug': {
        'justMyCode': True, 'stopOnEntry': False, 'subProcess': True,
        'showInlineValues': True, 'showBreakpointsInOverview': True,
        'breakOnRaised': False, 'breakOnUncaught': True,
    },
    'backups': {
        # `off` still keeps the copy taken before anything overwrites the conversation log.
        'cadence': 'daily', 'keepNewest': 5, 'ageBands': '2,14,60',
        'include': list(PRECIOUS),      # what a dated copy holds; the vault is opt-in
    },
    'agent': {
        # Empty means Leela's own config dir. Pointing it at Ramabana's makes one history
        # serve both surfaces.
        'configFolder': '',
        # On unless turned off, which is how the filter has always behaved.
        'notify': False, 'reasoning': '', 'historyLeelaOnly': True,
        # Whether the next new conversation is seeded from dhrona's reviewed rounds.
        'warm': False,
    },
    #: Whether the inline AI panel keeps a record of what it was asked and whether the answer was
    #: taken. `snippets` decides whether the selection and the suggestion are kept with it.
    'completions': {'telemetry': 'on', 'snippets': False},
    #: What `all` pays for each ranking signal, and what the search dialog may remember.
    #: `search.SETTING_WEIGHTS` maps these names onto the scorer's own.
    'search': {
        'telemetry': 'vault', 'snippets': False,
        'lastMode': '', 'lastScope': '', 'lastExts': '',
        'legFiles': 110.0, 'legSymbols': 100.0, 'legRg': 80.0, 'legFts': 60.0, 'legAnn': 40.0,
        'legRank': 10.0, 'symbolExact': 120.0, 'symbolPart': 55.0, 'queryInText': 40.0,
        'queryInFilename': 20.0, 'demoteNoise': 25.0,
    },
    'terminal': {
        'shell': '',
        'shellArgs': [],
        'loginShell': True,
        'external': '',
    },
    #: Off stops `core.watchdog.watch_cpu` at the next launch.
    'diagnostics': {'cpu_watchdog': True},
}

_ENUMS = {
    ('backups', 'cadence'): {'off', 'hourly', 'sixhourly', 'daily', 'weekly'},
    ('completions', 'telemetry'): {'on', 'off'},
    ('editor', 'wordWrap'): {'off', 'viewport', 'column'},
    ('editor', 'wrapIndent'): {'none', 'same', 'indent', 'deepIndent'},
    ('editor', 'overviewMode'): {'off', 'long', 'always'},
    ('editor', 'lineNumbers'): {'off', 'absolute', 'relative', 'hybrid'},
    ('editor', 'renderWhitespace'): {'none', 'selection', 'trailing', 'all'},
    ('editor', 'cursorStyle'): {'line', 'block', 'underline'},
    ('editor', 'cursorBlinking'): {'off', 'blink', 'smooth'},
    ('files', 'autoSave'): {'off', 'afterDelay', 'onFocusChange', 'onWindowChange'},
    ('workbench', 'breadcrumbs'): {'off', 'path', 'symbols', 'pathAndSymbols'},
    ('workbench', 'problemsScope'): {'file', 'workspace'},
    ('search', 'telemetry'): {'off', 'local', 'vault'},
    ('workbench', 'markdownView'): {'source', 'preview', 'split'},
}
_RANGES = {
    ('editor', 'fontSize'): (9, 28), ('editor', 'lineHeight'): (1, 2.4),
    ('editor', 'tabSize'): (1, 8), ('editor', 'lineLength'): (40, 240),
    ('editor', 'overviewThreshold'): (20, 5000), ('editor', 'scrollMargin'): (0, 20),
    ('files', 'autoSaveDelay'): (100, 60000),
    # The weights, found by being numbers: the section also holds the telemetry switches and what
    # the dialog was last set to.
    **{('search', k): (0, 500) for k, v in DEFAULT_SETTINGS['search'].items()
       if isinstance(v, (int, float)) and not isinstance(v, bool)},
}

def _read(path):
    try:
        value = Path(path).read_json(encoding='utf-8')
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError): return {}

def _write(path, data):
    "Replace a settings document atomically, never leaving a half-written JSON file."
    path = Path(path)
    text = json.dumps(data, indent=2, sort_keys=True) + '\n'
    with atomic_save(path, mode='w', encoding='utf-8') as file: file.write(text)

def _compact_legacy_snapshot(data):
    "Strip defaults from legacy full-section snapshots, which else outrank a later user change."
    data = deepcopy(data or {})
    def compact(target):
        for section, defaults in DEFAULT_SETTINGS.items():
            values = target.get(section)
            if isinstance(values, dict) and set(values) >= set(defaults):
                target[section] = {key: value for key, value in values.items()
                                   if key not in defaults or value != defaults[key]}
                if not target[section]: target.pop(section, None)
    compact(data)
    for values in (data.get('languages') or {}).values():
        if isinstance(values, dict): compact(values)
    return data

def _merge(base, overlay):
    out = deepcopy(base)
    for section, values in (overlay or {}).items():
        if section == 'languages' or not isinstance(values, dict): continue
        if section in out: out[section].update({k: v for k, v in values.items() if k in out[section]})
    return out

def _validated(section, values):
    if section not in DEFAULT_SETTINGS or not isinstance(values, dict):
        raise ValueError(f'unknown settings section {section!r}')
    out = {}
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS[section]: raise ValueError(f'unknown setting {section}.{key}')
        default = DEFAULT_SETTINGS[section][key]
        if (section, key) in _ENUMS:
            if value not in _ENUMS[section, key]:
                raise ValueError(f'{section}.{key} must be one of {sorted(_ENUMS[section, key])}')
        elif (section, key) in _RANGES:
            lo, hi = _RANGES[section, key]
            try: value = float(value) if isinstance(default, float) else int(value)
            except (TypeError, ValueError): raise ValueError(f'{section}.{key} must be a number')
            if not lo <= value <= hi: raise ValueError(f'{section}.{key} must be between {lo} and {hi}')
        elif isinstance(default, list): value = _names(section, key, value)
        elif isinstance(default, bool): value = bool(value)
        elif isinstance(default, str): value = str(value)
        out[key] = value
    return out

def _names(section, key, value):
    "A list setting: strings only, and for `backups.include` only entries that exist."
    if not isinstance(value, (list, tuple)): raise ValueError(f'{section}.{key} must be a list')
    out = [str(x) for x in value]
    if (section, key) == ('backups', 'include'):
        if unknown := [x for x in out if x not in BACKUP_ENTRIES]:
            raise ValueError(f'{section}.{key} does not know {unknown[0]!r}')
    return out

def _origin(section, key, user, workspace, language):
    "Which layer supplies `section.key`; the last layer that names it wins."
    def lang_values(scope): return ((scope.get('languages') or {}).get(language, {}).get(section)) or {}
    origin = 'default'
    if key in (user.get(section) or {}): origin = 'user'
    if key in (workspace.get(section) or {}): origin = 'workspace'
    if language and key in lang_values(user): origin = f'user:{language}'
    if language and key in lang_values(workspace): origin = f'workspace:{language}'
    return origin

class Settings:
    "Read and write user/workspace settings without allowing arbitrary paths or keys."
    def __init__(self, root=None, user_path=None):
        self.root = Path(root).resolve() if root else None
        self.user_path = Path(user_path or user_settings_file())
    @property
    def workspace_path(self): return self.root/WORKSPACE_SETTINGS_FILE if self.root else None
    def raw(self, scope):
        if scope == 'user': return _compact_legacy_snapshot(_read(self.user_path))
        if scope == 'workspace': return _compact_legacy_snapshot(_read(self.workspace_path)) if self.workspace_path else {}
        raise ValueError('scope must be user or workspace')
    def effective(self, language=''):
        user, workspace = self.raw('user'), self.raw('workspace')
        out = _merge(_merge(DEFAULT_SETTINGS, user), workspace)
        if language:
            out = _merge(out, (user.get('languages') or {}).get(language, {}))
            out = _merge(out, (workspace.get('languages') or {}).get(language, {}))
        return out
    def layers(self):
        "Every layer that names each key, least specific first."
        out = {}
        for scope in ('user', 'workspace'):
            data = self.raw(scope)
            for section, values in data.items():
                if section == 'languages' or not isinstance(values, dict): continue
                for key in values: out.setdefault(section, {}).setdefault(key, []).append(scope)
            for lang, block in (data.get('languages') or {}).items():
                for section, values in (block or {}).items():
                    if not isinstance(values, dict): continue
                    for key in values: out.setdefault(section, {}).setdefault(key, []).append(f'{scope}:{lang}')
        return out
    def describe(self, language=''):
        user, workspace = self.raw('user'), self.raw('workspace')
        effective = self.effective(language)
        origins = {section: {key: _origin(section, key, user, workspace, language) for key in values}
                   for section, values in DEFAULT_SETTINGS.items()}
        return {'effective': effective, 'origins': origins, 'layers': self.layers(),
                'user': user, 'workspace': workspace,
                'paths': {'user': str(self.user_path), 'workspace': str(self.workspace_path or '')},
                'language': language}
    def _path(self, scope, verb):
        "The file `scope` writes to. A workspace scope needs a project open to have one."
        path = {'user': self.user_path, 'workspace': self.workspace_path}.get(scope)
        if path is None: raise ValueError(f'open a project folder before {verb} workspace settings')
        return path
    def save(self, scope, section, values, language=''):
        values = _validated(section, values)
        path = self._path(scope, 'saving')
        current = self.raw(scope)
        target = current.setdefault('languages', {}).setdefault(language, {}) if language else current
        target.setdefault(section, {}).update(values)
        _write(path, current)
        return self.describe(language)
    def reset(self, scope, section=None, language=''):
        path = self._path(scope, 'resetting')
        current = self.raw(scope)
        target = (current.get('languages') or {}).get(language, {}) if language else current
        if section: target.pop(section, None)
        elif language: (current.get('languages') or {}).pop(language, None)
        else: current = {k: v for k, v in current.items() if k not in DEFAULT_SETTINGS and k != 'languages'}   # ramabana's `learning` shares the user file
        _write(path, current)
        return self.describe(language)

def agent_cfg(settings=None):
    "Where the agent's durable conversations live: `agent.configFolder`, else Leela's own config."
    folder = str(((settings or Settings()).effective().get('agent') or {}).get('configFolder') or '').strip()
    if not folder: return Path(leela_cfg)
    out = Path(folder).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    return out

def start_folder(root=None, settings=None):
    "Where the folder picker opens: `workbench.projectFolder`, else `~/code`, else home."
    values = (settings or Settings(root)).effective().get('workbench') or {}
    for want in (str(values.get('projectFolder') or '').strip(), CODE_FOLDER):
        if want and (p := Path(want).expanduser()).is_dir(): return p
    return Path.home()

#: `prefs.js` `THEME_DEFAULT`, and what a value naming nothing this build draws falls back to.
THEME_DEFAULT = 'cursor:light:tight'
_LEGACY_THEMES = {'system': 'leela:system:relaxed', 'dark': 'leela:dark:relaxed', 'light': 'leela:light:relaxed',
                  'cursor': THEME_DEFAULT}

def theme_backgrounds():
    "family -> {mode: --lee-bg}, for every family `lee-ide.css` draws. The stylesheet is the list."
    import re
    from ...core.web import asset_dir
    css = (asset_dir('static')/'lee-ide.css').read_text()
    out = {}
    for fam, mode, body in re.findall(r':root\[data-theme="(\w+)"\]\[data-mode="(dark|light)"\]\s*\{([^}]*)\}', css):
        if (m := re.search(r'--lee-bg:\s*(#[0-9a-fA-F]{6})', body)): out.setdefault(fam, {})[mode] = m[1]
    return out

def parse_theme(theme, families=None):
    "`(family, mode, density)` as `prefs.js` `parseTheme` reads `theme`: a family this build lacks is the default's."
    theme = str(theme or '')
    fam, mode, density = ((theme if ':' in theme else _LEGACY_THEMES.get(theme, THEME_DEFAULT)).split(':') + ['', ''])[:3]
    fam = fam if fam in (families or theme_backgrounds()) else 'cursor'
    return fam, mode if mode in ('system', 'dark', 'light') else 'light', density if density in ('tight', 'relaxed') else ('tight' if fam == 'cursor' else 'relaxed')

def theme_background(theme=None):
    "The saved theme's page background for the native window: one colour, or `(light, dark)` where it follows the system."
    bgs = theme_backgrounds()
    if theme is None:
        try: theme = (Settings().effective().get('appearance') or {}).get('theme')
        except Exception: theme = ''
    fam, mode, _ = parse_theme(theme, bgs)
    return (bgs[fam]['light'], bgs[fam]['dark']) if mode == 'system' else bgs[fam][mode]
