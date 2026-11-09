"Leela's own skill: what Leela can do and where, built from the keymap, menus, panes, settings and toolset."

import re
from functools import partial
from fastcore.all import Path
from shalya.skills import Skill
from shalya.tools import group_of, tool_groups

__all__ = ['SKILL_NAME', 'SKILL_DESC', 'FEATURES', 'leela_skill', 'skill_for']

SKILL_NAME = 'leela'
SKILL_DESC = ('What Leela can do, and where: menus, keys, panes, settings, tools. '
              'Read it when the user asks if Leela can do something, or how to do it in Leela.')

#: `(guide heading, where, what)`. `where` names keymap actions, which get their live label, chord and menu, or plain text.
FEATURES = (
    ('Editing', ('quick_open', 'recent_tabs', 'run_file', 'run_selection'),
     'Edit notebooks and files side by side. A `.py` file runs as a script in its own kernel. Autosave is on.'),
    ('Rust and JavaScript notebooks', ('`notebook language` in the palette',),
     'Run Rust and JavaScript cells on an installed Jupyter kernel, or on Leela\'s runner.'),
    ('Presenting a notebook', ('present_notebook', 'present_from_cell'),
     'Show the notebook as slides from the selected cell. Code cells run live. An audience window is optional.'),
    ('Staging a folder of a language you have just met', ('git_stage', 'the Git pane'),
     'Write the `.gitignore` rules it needs, then stage it. The file tree colours each file by git state.'),
    ('Live variables', ('focus_vars', 'switch_env'),
     'See each name in the kernel while a cell runs. Start the filter with `=` to evaluate.'),
    ('The agent', ('focus_agent', 'agent_selection', 'ask_ai'),
     'Ask a local or cloud model to read, change, run and test code. Each tool call is a card: approve, reject with steering, retry or roll back. '
     'The pane control sets the mode. Guided runs reads and stops before each write, command, kernel run and web call. Directed stops before every call. '
     'Edits runs file and notebook edits unstopped, and stops before other writes. Autopilot stops for nothing, except the third same call in a row, '
     'a question only a person can answer, and a host policy that asks. In every mode short of autopilot, these always stop: code the agent runs '
     '(an isolated check stays free), a watch or remember on a file, folder or URL, an API call other than GET or HEAD, image and video generation, '
     'and a write under `.git`, `.venv` or `.leela`. The notebook tools act on the open tab, unsaved edits included. Stop and Pause work in every mode.'),
    ('Lessons from abhyasa', ('new_lesson', 'Open in Leela in abhyasa', '`alt+s` checks the exercise at the cursor'),
     'Learn a topic step by step. A lesson runs in its own uv environment. The agent grades a checked exercise 0 to 10.'),
    ('The screen guide', ('the I don\'t get… button on a lesson cell',),
     'Say in one line what you do not understand. The guide explains it in steps and draws a board.'),
    ('Search and memory', ('code_search', 'find_definition', 'find_usages', 'vault_find'),
     'Search code with kosha: text, meaning, call graph and cells. Ripgrep is the fallback. The agent recalls saved vault pages.'),
    ('The vault', ('open_vault', 'clip_to_vault', 'vault_review'),
     'Keep pages, papers, repositories, videos and folders. Search them, and attach sections to a question. `@` completes documents.'),
    ('Research', ('research', 'web_search', 'read_url'),
     'Search the web for a digest that cites its sources. Sources stay beside the reader.'),
    ('The browser', ('browse_url', 'browse_tabs'),
     'Open a web page as a tab, on your signed-in sessions. **read** makes Markdown. **remember** files it in the vault.'),
    ('Git', ('panel_git', 'show_diff', 'git_blame', 'git'),
     'Changes, Review, Branches, History, Repository and All repos. Diffs open as tabs with hunk staging. Merge and rebase show a plan first. Fetch, pull and push run across repos.'),
    ('Ship it', ('panel_releases', 'panel_deploys', 'the Workflows and Drive panes', 'nbdev_prepare', 'fastship'),
     'Draw GitHub workflows and runs. Run the release flow of the project (nbdev, maturin, cargo or fastship). Deploy with `deploy.py`, or one library call at a time in Drive.'),
    ('Keys and buttons', ('palette', 'help', 'edit_keys'),
     'Every action has a button, a palette entry and a chord. Change chords in `keys.json` or in the keys editor.'),
    ('Watching something run', ('run_app', 'edit_runs', '`.leela/runs.json`'),
     'Start a run configuration under an inspector and watch its variables.'),
    ('Opening a project without a command line', ('open_folder', 'add_root', 'Open With > Leela in Finder'),
     'Open a folder or file from the welcome screen, the folder chooser, or the Dock. Leela remembers the open folders.'),
    ('Project settings', ('settings', '`.leela/settings.json`'),
     'Settings has a user file and a project file. `.leela/settings.json` in the project folder overrides the user file, key by key. Save to picks the file a change goes to.'),
    ('The venv notice', ('Set up .venv in the notice above the editor',),
     'A Python project with no environment runs no code until you choose. Set up .venv makes `.venv` with uv and installs only the kernel support. Choose interpreter… opens the kernel picker. Not now hides the notice.'),
    ('Updates', ('check_updates', 'setup_models'),
     'The Mac app checks for a release at start and each hour. Update installs it with Homebrew; Restart Leela opens the new version. A Leela from `uv tool install` updates with `uv tool upgrade leela`.'),
    ('Terminal and debugger', ('terminal', 'the Debug menu'),
     'Open terminals in the bottom pane. Debug a file with breakpoints and steps.'),
    ('Refactoring', ('rename_symbol', 'extract_variable', 'extract_method', 'move_symbol', 'replace_workspace'),
     'Rename, extract, inline and move code across the workspace. Undo an operation as one step.'),
)

def _menus():
    "Each menu-bar action and the menu it sits in."
    from ..keys.menus import BAR
    return {r.action: 'Leela' if t == '__app__' else t for t, rows in BAR for r in rows if getattr(r, 'action', None)}

def _key(a, menus=None):
    "`label (chord)` of keymap action `a`, with its menu when no chord names it; None when `a` is not an action."
    from ...core import keys as K
    if (k := K.lookup(a)) is None: return None
    c = K.chord_display(k)
    s = (k.label or a.replace('_', ' ')) + (f' {_code(c)}' if k.bound else '')
    return s + (f', {m} menu' if menus and not k.bound and (m := menus.get(a)) else '')

def _label(r):
    "A menu row as a person reads it."
    if getattr(r, 'action', None): return _key(r.action)
    return getattr(r, 'title', '') or ''

def _palette_extras(js=None):
    "Names of the palette commands that are not keymap rows, read from the shipped bundle. Raises `LookupError` when it finds none."
    js = js or (Path(__file__).parents[2]/'static'/'lee-ide.js').read_text(encoding='utf-8')
    i = js.find('function palette()'); j = js.find('const cmds', max(i, 0))
    names = [m[2] for m in re.finditer(r"""name:\s*(['"])(.*?)\1""", js[i:j])] if 0 <= i < j else []
    if not names: raise LookupError('no palette commands in lee-ide.js: `palette()` or its `const cmds` moved')
    return names

def _code(c): return f'`` {c} ``' if '`' in c else f'`{c}`'
SEP = ' · '   # labels hold commas

LEARN = """## Learn mode

- Learn mode teaches a topic through walks and checks. Its tools appear only while it is on.
- Quote only the quote a source shows. Say plainly when a text has no source.
- A research job finds web sources in the background.
"""

def _tools(ai):
    "Tool names by group: what this session offers now, then the rest Leela can offer. Each offered tool's schema says what it does."
    from .ai import HIDDEN
    now = {t.__name__ for t in ai._catalog_view.tools} if getattr(ai, '_tools', None) is not None else set()   # never rebuild mid-turn
    kinds = [(ai._news_toolset, 'while a feed is followed'), (ai._lesson_toolset, 'while a lesson tab is active'),
             (ai._session_toolset, ''), (ai._video_toolset, '')]   # a mode's tools reach the model as schemas while it is on
    own = {t.__name__: why for ts, why in kinds for t in ts}
    grp = lambda n: 'leela' if n in own else group_of(n, 'agent')
    def row(ns): return '; '.join((f'{w}: ' if w else '') + ', '.join(f'`{n}`' for n in sorted(ns) if own.get(n, '') == w)
                                  for w in sorted({own.get(n, '') for n in ns}))   # a condition is said once, not after each tool
    rows = lambda ns: ''.join(f'- **{g}**: ' + row([n for n in ns if grp(n) == g]) + '\n' for g in sorted({grp(n) for n in ns}))
    rest = {*tool_groups(), *own, *(f.__name__ for f in ai.registry.tools)} - now - HIDDEN
    return (f'Offered now:\n{rows(now - HIDDEN)}' if now else '') + (
        f'\nNot offered now. The host, the model profile, a setting or the active tab decides:\n{rows(rest)}' if rest else '')

def leela_skill(ai=None):
    "The skill text: features first, then menus, commands, keys, settings and agent tools."
    from ...core import keys as K
    from ...app import LEFT_PANES
    from ..keys.menus import BAR, MENUS
    from ..settings.settings import DEFAULT_SETTINGS, SECTIONS
    from .app import COMMAND_HELP, PAGE_COMMANDS
    menus = _menus()
    out = ['# What Leela can do\n\nLeela is an IDE for notebooks and code, with an agent, a vault, git, release and deploy. '
           'Each item says where it is: a menu, a pane, or a key. `mod` is Command on a Mac and Control elsewhere. '
           'The keys are the user\'s own, from `keys.json`. Every action is also in the command palette.\n\n## Features\n']
    for title, where, what in FEATURES:
        w = '; '.join(_key(a, menus) or a for a in where)
        out.append(f'- **{title}** ({w}): {what}\n')
    out.append('\n## Panes\n\n- Left bar: ' + ', '.join(t for _, _, t in LEFT_PANES) +
               '.\n- Centre: the editor tabs. Right: Variables and the agent. Bottom: exec, terminal and log.\n'
               '- Each pane has a `⋯` menu. Right-click opens the same menu.\n\n## Menu bar\n')
    for t, rows in BAR: out.append(f'- **{"Leela" if t == "__app__" else t}**: ' + SEP.join(l for r in rows if (l := _label(r))) + '\n')
    out.append('\n## Context menus (`⋯` or right-click)\n\nEach menu also holds the menu-bar commands that apply to it. These are only here:\n')
    for sf, rows in MENUS.items():
        if ls := list(dict.fromkeys(K.lookup(r.action).label or r.action for r in rows if r.action and r.action not in menus)): out.append(f'- **{sf.replace("_head", " pane header")}**: ' + SEP.join(ls) + '\n')
    seen = {*menus, *(r.action for rows in MENUS.values() for r in rows if r.action)}
    out.append('\n## Other commands, by where they work (palette or key)\n')
    for scope, rows in K.help_rows().items():
        if scope == 'present': rows = [(' / '.join(c.split()), l) for c, l in rows]
        else: rows = [(K.chord_display(k), k.label) for k in K.by_scope(scope) if k.label and k.action not in seen]
        if rows: out.append(f'- **{scope}**: ' + SEP.join(l + (f' {_code(c)}' if c and c != '–' else '') for c, l in rows) + '\n')
    if ex := _palette_extras(): out.append('- **palette only**: ' + SEP.join(ex) + '\n')
    cmds = list(ai.commands()) if ai is not None else list(COMMAND_HELP)
    reg = {n: h for n, (_, h) in ai.registry.commands.items()} if ai is not None else {}
    out.append('\n## Slash commands in the agent prompt\n\n' + ', '.join(
        f'`/{n}`' + (f' ({h})' if (h := reg.get(n) or COMMAND_HELP.get(n) or PAGE_COMMANDS.get(n)) else '')
        for n in sorted({*cmds, *PAGE_COMMANDS})) + '\n')
    out.append(f'\n## Settings ({_key("settings")})\n\nThe user file, and per project `.leela/settings.json`, which overrides it key by key. Sections and their keys:\n')
    for sec, d in DEFAULT_SETTINGS.items():   # a package section can hold many rows, so it gets one line
        out.append(f'- **{sec}**: ' + (f'{len(d)} {SECTIONS[sec]["owner"]} settings, user settings only' if sec in SECTIONS else ', '.join(d)) + '\n')
    out.append('\n'+LEARN)
    if ai is not None: out.append('\n## Agent tools\n\n' + _tools(ai))
    return ''.join(out)

def skill_for(ai):
    "The `leela` skill for agent `ai`; its text is built when it is read, so it shows the keys and tools of that moment."
    return Skill(name=SKILL_NAME, source='leela', description=SKILL_DESC, where='leela.blocks.agent.skill', _text=partial(leela_skill, ai))
