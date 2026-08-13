'Layered, validated IDE settings: defaults, then user, then workspace, then language.'
from __future__ import annotations

import json
from copy import deepcopy
from fastcore.all import Path, atomic_save

from ... import leela_cfg

__all__ = ['DEFAULT_SETTINGS', 'Settings', 'USER_SETTINGS_FILE', 'WORKSPACE_SETTINGS_FILE']

USER_SETTINGS_FILE = Path(leela_cfg)/'settings.json'
WORKSPACE_SETTINGS_FILE = '.leela/settings.json'

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
    },
    'debug': {
        'justMyCode': True, 'stopOnEntry': False, 'subProcess': True,
        'showInlineValues': True, 'showBreakpointsInOverview': True,
        'breakOnRaised': False, 'breakOnUncaught': True,
    },
    'terminal': {
        'shell': '',            # '' means $SHELL
        'shellArgs': [],
        'loginShell': True,     # macOS puts PATH and tool setup in login config
        'external': '',         # '' means the first installed of EXTERNAL_TERMINALS
    },
}

_ENUMS = {
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
}
_RANGES = {
    ('editor', 'fontSize'): (9, 28), ('editor', 'lineHeight'): (1, 2.4),
    ('editor', 'tabSize'): (1, 8), ('editor', 'lineLength'): (40, 240),
    ('editor', 'overviewThreshold'): (20, 5000), ('editor', 'scrollMargin'): (0, 20),
    ('files', 'autoSaveDelay'): (100, 60000),
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
        elif isinstance(default, bool): value = bool(value)
        elif isinstance(default, str): value = str(value)
        out[key] = value
    return out


class Settings:
    "Read and write user/workspace settings without allowing arbitrary paths or keys."
    def __init__(self, root=None, user_path=None):
        self.root = Path(root).resolve() if root else None
        self.user_path = Path(user_path or USER_SETTINGS_FILE)

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

    def describe(self, language=''):
        user, workspace = self.raw('user'), self.raw('workspace')
        effective = self.effective(language)
        origins = {}
        for section, values in DEFAULT_SETTINGS.items():
            origins[section] = {}
            for key in values:
                origin = 'default'
                if key in (user.get(section) or {}): origin = 'user'
                if key in (workspace.get(section) or {}): origin = 'workspace'
                if language and key in (((user.get('languages') or {}).get(language, {}).get(section)) or {}):
                    origin = f'user:{language}'
                if language and key in (((workspace.get('languages') or {}).get(language, {}).get(section)) or {}):
                    origin = f'workspace:{language}'
                origins[section][key] = origin
        return {'effective': effective, 'origins': origins, 'user': user, 'workspace': workspace,
                'paths': {'user': str(self.user_path), 'workspace': str(self.workspace_path or '')},
                'language': language}

    def save(self, scope, section, values, language=''):
        values = _validated(section, values)
        path = self.user_path if scope == 'user' else self.workspace_path if scope == 'workspace' else None
        if path is None: raise ValueError('open a project folder before saving workspace settings')
        current = self.raw(scope)
        target = current.setdefault('languages', {}).setdefault(language, {}) if language else current
        target.setdefault(section, {}).update(values)
        _write(path, current)
        return self.describe(language)

    def reset(self, scope, section=None, language=''):
        path = self.user_path if scope == 'user' else self.workspace_path if scope == 'workspace' else None
        if path is None: raise ValueError('open a project folder before resetting workspace settings')
        current = self.raw(scope)
        target = (current.get('languages') or {}).get(language, {}) if language else current
        if section: target.pop(section, None)
        elif language: (current.get('languages') or {}).pop(language, None)
        else: current = {}
        _write(path, current)
        return self.describe(language)
