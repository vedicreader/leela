"The web IDE."

from __future__ import annotations
import ast, asyncio, ipaddress, json, os, re, shutil, subprocess, sys, warnings
from itertools import accumulate
from urllib.parse import quote
from fasthtml.common import *
from starlette.routing import WebSocketRoute

from .core.inspectors import PROFILES, SORTS
from . import errstr
from .blocks import browser as browser_block
from .blocks import drive as drive_block
from .blocks import editor as editor_block
from .blocks import fs as fs_block
from .blocks import git as git_block
from .blocks import jobs as jobs_block
from .blocks import keys as keys_block
from .blocks import lsp as lsp_block
from .blocks import memory as memory_block
from .blocks import pipelines as pipelines_block
from .blocks import research as research_block
from .blocks import refactor as refactor_block
from .blocks import runs as runs_block
from .blocks import runtime as runtime_block
from .blocks import search as search_block
from .blocks import settings as settings_block
from .blocks import stack as stack_block
from .blocks import term as term_block
from .blocks import tabs as tabs_block
from .blocks import vars as vars_block
from .blocks import workflows as workflows_block
from .blocks import workspace as workspace_block
from .blocks.term.app import term_cwd
from .core.ui import bar as btn_bar
from .core import DocStore, RunState, connect_all
from .blocks.fs.ui import files_panel as _files_panel
from .blocks.tabs.app import disk_version as _disk_version
from .blocks.tabs.ui import kernel_pill as _kernel_pill
from .blocks.tabs.ui import tab_bar as _tab_bar
from .core.ui import action_bar as _action_bar
from .core.ui import activity_icon as _activity_icon
from .core.ui import btn as _btn
from .core.ui import menu_button as _menu_button
from .core.web import asset as _asset
from .core.web import diff_payload as _diff
from .core.web import fail as _fail
from .core.web import off_loop as _off_loop
from .core.web import sse as _sse
from .core.web import Assets, static_dirs
from .core.text import did_you_mean, fuzzy_rank
from .core.text import md_block_diff, md_blocks, md_change_kinds
from .blocks.fs.fs import lang_for
from .blocks.git.git import GitRepo, GitError
from .core.keys import by_scope, chord_display, toast_rows
from .blocks.nb.nb import Notebook, Cell
from .blocks.term.term import TerminalGate, gh_auth_argv, lazygit_argv, path_prelude, shell_argv
from .workspace import STEP_RANGE, TOOL_RANGE, Workspace
from .agent.core import model_note
from .agent.runtime import estimate_tokens

__all__ = ['ide_app', 'serve_ide']

BLOCKS = [keys_block, settings_block, search_block, memory_block, jobs_block,
          research_block, browser_block, term_block, runs_block, workspace_block, git_block,
          workflows_block, pipelines_block, drive_block, stack_block,
          fs_block, lsp_block, vars_block, runtime_block, tabs_block, editor_block, refactor_block]

def _term_python(ws, cwd=None):
    "The interpreter a terminal opened at `cwd` should be inside. See `python_for`."
    from .blocks.runtime.kernels import python_for
    return python_for(cwd, ws)

def _line_starts(text):
    "The lines of `text`, keeping their ends, and the character offset each one begins at."
    lines = text.splitlines(keepends=True) or ['']
    return lines, list(accumulate(map(len, lines), initial=0))[:-1]

def _python_diagnostics(source, filename='<cell>'):
    "Compile without executing and return Python's own errors and warnings as editor ranges."
    source = str(source or '')
    lines, starts = _line_starts(source)
    def point(line, column):
        row = max(1, min(int(line or 1), len(lines)))
        text = lines[row - 1].rstrip('\r\n')
        col = max(0, min((int(column) - 1) if column else 0, len(text)))
        return starts[row - 1] + col
    def line_range(line):
        row = max(1, min(int(line or 1), len(lines)))
        text = lines[row - 1].rstrip('\r\n')
        leading = len(text) - len(text.lstrip())
        start = starts[row - 1] + leading
        return start, max(start + (1 if start < len(source) else 0), starts[row - 1] + len(text))
    found = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            compile(source, filename or '<cell>', 'exec')
        except SyntaxError as error:
            start = point(error.lineno, error.offset)
            end = point(error.end_lineno or error.lineno, error.end_offset)
            if end <= start:
                end = min(len(source), start + 1)
                if end == start and start: start -= 1
            found.append({'from': start, 'to': end, 'severity': 'error',
                          'message': error.msg or str(error),
                          'source': 'Python', 'code': type(error).__name__})
        for warning in caught:
            start, end = line_range(warning.lineno)
            found.append({'from': start, 'to': end, 'severity': 'warning',
                          'message': str(warning.message), 'source': 'Python',
                          'code': warning.category.__name__})
    return found

def _project_state_context(ws, max_files=120, max_chars=12_000):
    "Bounded, current-disk evidence used when a person asks the charter to follow the code."
    files = [p for p in ws.fs.walk(limit=max_files) if p.is_file()]
    names = '\n'.join(f'- {p}' for p in files)
    preferred = ('README.md', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod',
                 'requirements.txt', 'Makefile')
    excerpts, used = [], 0
    for path in sorted(files, key=lambda p: (p.name not in preferred, len(p.parts), str(p))):
        if path.name not in preferred and len(excerpts) >= 4: continue
        try: text = ws.fs.read(path)
        except Exception: continue
        room = max_chars - used
        if room <= 0: break
        excerpt = text[:min(3000, room)].strip()
        if excerpt:
            excerpts.append(f'### {path}\n{excerpt}')
            used += len(excerpt)
    return ('## Open roots\n' + ('\n'.join(f'- {root}' for root in ws.fs.roots) or '- none') +
            '\n\n## Current file map\n' + (names or '- no files') +
            '\n\n## Project-file excerpts\n' + ('\n\n'.join(excerpts) or '- none'))

def _tool_preview(agent, tool, args):
    "Dry-run preview for editable calls; never invokes the tool or mutates the workspace."
    args = dict(args or {})
    if tool == 'create_file':
        path = args.get('path', '')
        before = agent.host.text_at(path) or ''
        return {'kind': 'diff', **_diff(before, str(args.get('text', '')))}
    if tool == 'edit_file':
        from .agent.tools import _cmds
        from exhash import exhash
        path = args.get('path', '')
        before = agent.host.text_at(path)
        if before is None: raise ValueError(f'no such file: {path}')
        result = exhash(before, _cmds(args.get('commands', '[]')))
        return {'kind': 'patch', 'text': str(result)}
    if tool == 'replace_text':
        from .agent.tools import _apply_edits, _edits
        path = args.get('path', '')
        before = agent.host.text_at(path)
        if before is None: raise ValueError(f'no such file: {path}')
        return {'kind': 'diff', **_diff(before, _apply_edits(before, _edits(args.get('edits', '[]'))))}
    if tool in {'run_python', 'inspect_python'}:
        return {'kind': 'code', 'text': str(args.get('code', '')), 'language': 'python'}
    if tool == 'run_shell':
        return {'kind': 'code', 'text': str(args.get('command', '')), 'language': 'bash'}
    if tool in {'edit_cell', 'add_cell'}:
        return {'kind': 'code', 'text': str(args.get('source') or args.get('commands') or ''), 'language': 'python'}
    if tool in {'web_search', 'read_url', 'research'}:
        return {'kind': 'network', 'text': str(args.get('url') or args.get('query') or '')}
    return {'kind': 'json', 'text': json.dumps(args, indent=2, default=str)}

TOOL_GROUPS = {
    'Repository': {'search_code', 'similar_code', 'outline', 'list_files', 'grep', 'ls',
                   'view_file', 'edit_file', 'replace_text', 'create_file'},
    'Runtime': {'run_python', 'inspect_python', 'list_vars', 'read_terminal', 'run_shell'},
    'Web': {'web_search', 'read_url', 'research'},
}

def _tool_group(name):
    "Which browser-facing family a tool belongs to."
    group = first(g for g, names in TOOL_GROUPS.items() if name in names)
    if group: return group
    return 'Notebook' if 'cell' in name or 'notebook' in name else 'Other'

def _tool_schemas(agent):
    "Browser-sized schemas for editable checkpoint forms; callable validation remains authoritative."
    import inspect
    from .blocks.agent.ai import WRITE_TOOLS
    out = []
    for tool in agent.tools:
        sig = inspect.signature(tool)
        fields = []
        for name, p in sig.parameters.items():
            ann = p.annotation
            kind = ('boolean' if ann is bool else 'integer' if ann is int else
                    'number' if ann is float else 'string')
            fields.append({'name': name, 'kind': kind, 'required': p.default is inspect.Parameter.empty,
                           'default': None if p.default is inspect.Parameter.empty else p.default,
                           'multiline': name in {'code', 'text', 'commands', 'edits', 'source',
                                                 'questions', 'command'}})
        out.append({'name': tool.__name__, 'description': (inspect.getdoc(tool) or '').split('\n')[0],
                    'changes_state': tool.__name__ in WRITE_TOOLS,
                    'retryable': tool.__name__ not in WRITE_TOOLS,
                    'group': _tool_group(tool.__name__), 'fields': fields})
    return out

def _assigned_lines(source):
    "Top-level bindings made by Python source, as ``[(line, name)]``."
    try: tree = ast.parse(source or '')
    except SyntaxError: return []
    found = []
    def target(node, line=None):
        if isinstance(node, ast.Name): found.append((line or node.lineno, node.id))
        elif isinstance(node, (ast.Tuple, ast.List)):
            for child in node.elts: target(child, line)
        elif isinstance(node, ast.Starred): target(node.value, line)
    class Bindings(ast.NodeVisitor):
        def visit_Assign(self, node):
            for t in node.targets: target(t, node.lineno)
            self.visit(node.value)
        def visit_AnnAssign(self, node):
            target(node.target, node.lineno)
            if node.value: self.visit(node.value)
        def visit_AugAssign(self, node): target(node.target, node.lineno); self.visit(node.value)
        def visit_NamedExpr(self, node): target(node.target, node.lineno); self.visit(node.value)
        def visit_For(self, node):
            target(node.target, node.lineno)
            for child in (*node.body, *node.orelse): self.visit(child)
        visit_AsyncFor = visit_For
        def visit_With(self, node):
            for item in node.items:
                if item.optional_vars: target(item.optional_vars, node.lineno)
            for child in node.body: self.visit(child)
        visit_AsyncWith = visit_With
        def visit_Import(self, node):
            for a in node.names: found.append((node.lineno, a.asname or a.name.split('.')[0]))
        visit_ImportFrom = visit_Import
        def visit_FunctionDef(self, node): found.append((node.lineno, node.name))
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_ClassDef(self, node): found.append((node.lineno, node.name))
    Bindings().visit(tree)
    return list(dict.fromkeys(found))

def _inline_values(source, groups, outputs=(), result_info=None):
    "Kernel values for bindings and a final expression, located on their source lines."
    rows = {n.get('name'): n for g in groups or [] for n in g.get('nodes', [])}
    out = []
    for line, name in _assigned_lines(source):
        if (row := rows.get(name)) is not None:
            out.append({'line': line, 'name': name, 'value': row.get('value', ''),
                        'type': row.get('type', ''), 'shape': row.get('shape'),
                        'dtype': row.get('dtype'), 'is_grid': bool(row.get('is_grid')),
                        'accessor': row.get('accessor') or [name]})
    output_result = first(o for o in reversed(outputs or ()) if o.get('output_type') == 'execute_result')
    if output_result:
        try:
            expr = ast.parse(source or '').body[-1]
            if isinstance(expr, ast.Expr):
                root = expr.value
                while isinstance(root, (ast.Attribute, ast.Subscript, ast.Call)):
                    root = root.value if not isinstance(root, ast.Call) else root.func
                name = root.id if isinstance(root, ast.Name) else 'result'
                value = (output_result.get('data') or {}).get('text/plain', '')
                info = dict(result_info or {})
                out.append({'line': expr.lineno, 'name': name, 'value': info.get('value', value),
                            'type': info.get('type', 'result'), 'shape': info.get('shape'),
                            'dtype': info.get('dtype'), 'is_grid': bool(info.get('is_grid')),
                            'is_container': bool(info.get('is_container')),
                            'accessor': info.get('accessor') or ['_']})
        except (SyntaxError, IndexError): pass
    return out

async def _cell_extras(k, cell):
    "Inspector rows and the rich last result for a finished cell, or `(None, None)`."
    if not k or cell.has_error: return None, None
    rows = await k.api('/api/rows', {'profile': 'full', 'sort': 'name'}, timeout=2)
    has_result = any(o.get('output_type') == 'execute_result' for o in cell.outputs)
    latest = await k.api('/api/result', timeout=2) if has_result else None
    return rows, (latest or {}).get('result')

def _edit_diffs(a):
    "Per-file diffs for what an assistant turn actually wrote."
    return [{'path': p, **_diff(was, now)} for p, (was, now) in a.changes().items()]

def _activity_changes(a, versions):
    "Activity rows that moved since the last poll: new calls and in-place transitions"
    changed = []
    for row in a.activity.rows(mark=a.activity._mark):
        version = (row.get('done'), row.get('ok'), row.get('line'), row.get('detail'), row.get('secs'))
        if versions.get(row['id']) != version:
            versions[row['id']] = version
            changed.append(row)
    return changed

def _history_sessions(turns, execution=()):
    "Turns grouped by durable model-context id; old untagged history splits after 30m."
    groups, by_id, legacy_n, legacy_last = [], {}, 0, None
    for turn in turns or ():
        sid, at = turn.get('session') or '', float(turn.get('at') or 0)
        if not sid:
            if legacy_last is None or at - legacy_last > 1800: legacy_n += 1
            sid, legacy_last = f'legacy-{legacy_n}', at
        if sid not in by_id:
            by_id[sid] = {'id': sid, 'started': at, 'ended': at, 'turns': [], 'models': [],
                          'context_continues': True, 'code': 0}
            groups.append(by_id[sid])
        g = by_id[sid]; g['turns'].append(turn); g['ended'] = max(g['ended'], at)
        if (model := turn.get('model')) and model not in g['models']: g['models'].append(model)
    for row in execution or ():
        sid = row['id']
        if sid in by_id: by_id[sid]['code'] = row.get('code', 0)
        else: groups.append({'id': sid, 'started': 0, 'ended': 0, 'turns': [], 'models': [],
                             'context_continues': True, 'code': row.get('code', 0)})
    return list(reversed(groups))

async def _explain(k, err, scope='live'):
    "A kernel error with a `did you mean` appended, when a near-miss name exists."
    if not (err and 'is not defined' in err): return err
    return did_you_mean(err, await k.names(scope)) if k else err

def _header(ws):
    "Project identity first, document tabs second, infrequent actions in menus."
    root = ws.project_root
    return Header(
        Button(Span('leela', cls='lee-brand'), Span(Path(root).name if root else 'open workspace',
               id='workspacename', cls='lee-workspace-name'), cls='lee-workspace-switcher',
               id='workspacepill', title='switch or open workspace', onclick='leeWorkspaceMenu(this)'),
        Button('no git', id='gitpill', cls='lee-branch-switcher', title='switch branch',
               onclick='leeBranchMenu(this)'),
        Div(*(Button(glyph, id=f'git{op}', cls='lee-git-quick', title=title, aria_label=title,
                     onclick=f'leeGitQuick("{op}")')
              for op, glyph, title in (('fetch', '⭮', 'fetch from remotes'),
                                       ('pull', '↓', 'pull (fast-forward, autostash)'),
                                       ('push', '↑', 'push this branch'))),
            cls='lee-git-quickbar', aria_label='remote actions'),
        Nav(Button('File', cls='lee-menubar-btn', onclick='leeMenuAt("files", this)'),
            Button('Tools', cls='lee-menubar-btn', onclick='leeToolsMenu(this)'),
            Button('Debug', cls='lee-menubar-btn', onclick='leeDebugMenu(this)'),
            cls='lee-menubar', aria_label='application menus'),
        _tab_bar(ws),
        Button('↔',cls='lee-tab-overflow',title='split editor side by side',aria_label='split editor vertically',onclick='leeSplit("vertical")'),
        Button('↕',cls='lee-tab-overflow',title='split editor top and bottom',aria_label='split editor horizontally',onclick='leeSplit("horizontal")'),
        Button('⋯', id='taboverflow', cls='lee-tab-overflow', title='all open files',
               aria_label='all open files', onclick='leeTabOverflow(this)'),
        Span(cls='lee-spacer'),
        _kernel_pill(ws),
        cls='lee-header', id='header')

def _git_panel():
    return Section(
        Div(Span('source control', cls='lee-ptitle'), Span(cls='lee-spacer'),
            Button('refresh', cls='lee-btn', onclick='leeGitRefresh()', title='refresh repository'),
            Button('−', cls='lee-pane-min', title='minimise source control',
                   aria_label='minimise source control', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('loading repository…', cls='lee-dim lee-git-empty'), id='gitpanel', cls='lee-git-panel'),
        cls='lee-panel lee-source-control')

def _workflows_panel():
    "GitHub Actions for this project, read locally and reached through gheasy."
    return Section(
        Div(Span('workflows', cls='lee-ptitle'), Span(cls='lee-spacer'),
            Button('refresh', cls='lee-btn', onclick='leeWorkflows()', title='reread the workflow files'),
            Button('−', cls='lee-pane-min', title='minimise workflows',
                   aria_label='minimise workflows', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('reading workflows…', cls='lee-dim'), id='workflowspanel', cls='lee-workflows-panel'),
        cls='lee-panel lee-workflows')

def _releases_panel():
    "The release pipeline, its state, and the terminal the steps run on."
    return Section(
        Div(Span('release', cls='lee-ptitle'), Span(cls='lee-spacer'),
            Button('refresh', cls='lee-btn', onclick='leeReleases()', title='reread the pipeline'),
            Button('−', cls='lee-pane-min', title='minimise release',
                   aria_label='minimise release', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('reading the pipeline…', cls='lee-dim'), id='releasespanel', cls='lee-releases-panel'),
        cls='lee-panel lee-releases')

def _deploy_panel():
    "Where this app runs, what it is missing, and the stages that put it there."
    return Section(
        Div(Span('deploy', cls='lee-ptitle'), Span(cls='lee-spacer'),
            Button('refresh', cls='lee-btn', onclick='leeDeploys()', title='reread the deploy plan'),
            Button('−', cls='lee-pane-min', title='minimise deploy',
                   aria_label='minimise deploy', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('reading the deploy plan…', cls='lee-dim'), id='deploypanel', cls='lee-releases-panel'),
        cls='lee-panel lee-deploys')

def _drive_panel():
    "The same deploy as `deploy.py`, taken apart into the library calls it makes."
    return Section(
        Div(Span('drive', cls='lee-ptitle'), Span(cls='lee-spacer'),
            Button('refresh', cls='lee-btn', onclick='leeDrive()', title='re-read the values'),
            Button('−', cls='lee-pane-min', title='minimise drive',
                   aria_label='minimise drive', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('reading the parts…', cls='lee-dim'), id='drivepanel', cls='lee-releases-panel'),
        cls='lee-panel lee-drive')

def _symbols_panel():
    return Section(
        Div(Span('structure', cls='lee-ptitle'), Span(id='symbolfile', cls='lee-keyscope'),
            Span(cls='lee-spacer'), Button('refresh', cls='lee-btn', onclick='leeSymbols()'),
            Button('−', cls='lee-pane-min', title='minimise structure',
                   aria_label='minimise structure', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('Open a source file to see its symbols.', cls='lee-dim'), id='symbols',
            cls='lee-symbols', role='tree', aria_label='file structure'),
        cls='lee-panel lee-structure')

def _left_workspace(ws):
    return Aside(
        Nav(Button(_activity_icon('files'), Span('Project', cls='sr-only'), cls='lee-activity-btn active',
                   data_left='files', title='Project files', aria_label='Project files',
                   onclick='leeLeft("files")'),
            Button(_activity_icon('symbols'), Span('Structure', cls='sr-only'), cls='lee-activity-btn',
                   data_left='symbols', title='File structure', aria_label='File structure',
                   onclick='leeLeft("symbols")'),
            Button(_activity_icon('git'), Span('Git', cls='sr-only'), cls='lee-activity-btn',
                   data_left='git', title='Git source control', aria_label='Git source control',
                   onclick='leeLeft("git")'),
            Button(_activity_icon('workflows'), Span('Workflows', cls='sr-only'), cls='lee-activity-btn',
                   data_left='workflows', title='GitHub workflows', aria_label='GitHub workflows',
                   onclick='leeLeft("workflows")'),
            Button(_activity_icon('releases'), Span('Release', cls='sr-only'), cls='lee-activity-btn',
                   data_left='releases', title='Release pipeline', aria_label='Release pipeline',
                   onclick='leeLeft("releases")'),
            Button(_activity_icon('deploys'), Span('Deploy', cls='sr-only'), cls='lee-activity-btn',
                   data_left='deploys', title='Deploy to a server', aria_label='Deploy to a server',
                   onclick='leeLeft("deploys")'),
            Button(_activity_icon('drive'), Span('Drive', cls='sr-only'), cls='lee-activity-btn',
                   data_left='drive', title='Drive the packages one call at a time',
                   aria_label='Drive the packages one call at a time',
                   onclick='leeLeft("drive")'),
            Span(cls='lee-activity-spacer'),
            Button('●', cls='lee-pane-pin pinned', type='button', data_pane_pin='left',
                   title='pinned open — unpin to close it when you click away',
                   aria_label='pin the file pane open', aria_pressed='true',
                   onclick='leePinPane("left")'),
            Button('−', cls='lee-pane-min', type='button', title='minimise the file pane',
                   aria_label='minimise the file pane', onclick='leePane("left", false)'),
            cls='lee-activity', aria_label='Project tools'),
        Div(_files_panel(ws.fs), _symbols_panel(), _git_panel(), _workflows_panel(),
            _releases_panel(), _deploy_panel(), _drive_panel(), _toast_panel(), cls='lee-left-content'),
        cls='lee-left left-files', id='left')

def _toast_panel():
    "The left-sidebar cheatsheet: the keys that earn space but do not fit the footer."
    rows = [Div(Kbd(k), Span(lbl), cls='lee-krow') for k, lbl in toast_rows()]
    return Section(
        Div(Span('keys', cls='lee-ptitle'), Span(id='keyscope', cls='lee-keyscope'),
            Span(cls='lee-spacer'), _action_bar('keys'), cls='lee-phead'),
        Div(*rows, id='keytoast', cls='lee-toast', aria_live='polite'),
        cls='lee-panel lee-keys')

def _toolbar():
    "Only the actions used continuously; everything else lives in a named menu."
    actions = {'run_cell', 'run_advance', 'run_file', 'run_selection', 'interrupt'}
    buttons = [_btn(b) for b in btn_bar('toolbar') if b.action in actions]
    return Div(*buttons, Span(cls='lee-spacer'),
               Button('⋯', cls='lee-more lee-toolbar-more', title='more editor actions',
                      aria_label='more editor actions', onclick='leeEditorMenu(this)'),
               cls='lee-toolbar', id='toolbar')

def _vars_panel(ws):
    "The right sidebar: owner or agent-session namespace, then filtering."
    return Section(
        Div(Span('variables', cls='lee-ptitle'),
            Div(Button('live', id='sc-live', cls='lee-seg active', onclick='leeScope("live")'),
                Button('agent', id='sc-agent', cls='lee-seg', onclick='leeScope("agent")'),
                cls='lee-segbar', title='live is your kernel · agent is its protected persistent layer'),
            Span(id='envtag', cls='lee-pill lee-pill-on', style='display:none'),
            Span(cls='lee-spacer'), _action_bar('web_vars'), _action_bar('vars'), _menu_button('variable'),
            cls='lee-phead'),
        Div(Input(id='varfilter', placeholder='filter names · = Python expression', cls='lee-input',
                  oninput='leeFilterVars()', onkeydown='leeEvalVarFilter(event)'),
            Select(*[Option(p, value=p, selected=(p == 'minimal')) for p in PROFILES],
                   id='varprofile', cls='lee-select', onchange='leeVars()'),
            Select(*[Option(s, value=s, selected=(s == 'recent')) for s in SORTS],
                   id='varsort', cls='lee-select', onchange='leeVars()'),
            cls='lee-filterbar'),
        Div(Div('connect a kernel to see variables', cls='lee-dim'), id='vars', cls='lee-vars'),
        cls='lee-panel lee-varspanel')

def _empty_editor():
    "First paint with no tab: brand + one path into each main surface."
    features = (
        ('Notebooks & files', 'CodeMirror 6 beside runnable cells; scripts get their own kernel.'),
        ('Live variables', 'Inspect the kernel namespace while cells run — expand nested values.'),
        ('Research & memory', 'Fossick web digests into a Vishalakshi vault; recall before re-fetching.'),
        ('Code search', 'Kosha FTS5 + embeddings + call graph; peers and clusters when you need them.'),
        ('Agent', 'Ramabana sees the index, open files, and live namespace — local or cloud models.'),
        ('Git, release, deploy', 'Source control and pipeline panels without leaving the workspace.'),
    )
    return Section(
        Span('leela', cls='lee-empty-mark'),
        Strong('Creative workspace that starts with coding'),
        P('Notebooks, files, live variables, research memory, and an agent that sees what you see.'),
        # Actions before the tour: reopening a project should not mean reading past it.
        Div(Button('Open a folder', cls='lee-btn go', onclick='leeAct("add_root")'),
            Button('Open file', cls='lee-btn', onclick='leeAct("quick_open")'),
            Button('New notebook', cls='lee-btn', onclick='leeAct("new_notebook")'),
            Button('Research a topic', cls='lee-btn', onclick='leeAct("research")'),
            Button('Ask the agent', cls='lee-btn', onclick='leeAct("focus_agent")'),
            cls='lee-empty-actions'),
        # Filled by the client from `/fs/recent`: live, because a packaged shell is built once.
        Div(id='leerecent', cls='lee-empty-recent', hidden=True),
        Ul(*[Li(Strong(title), Span(blurb)) for title, blurb in features], cls='lee-empty-features'),
        Small('Keyboard: ', Kbd('ctrl+p'), ' open · ', Kbd('ctrl+shift+p'), ' commands · ',
              Kbd('mod+e'), ' recent files'),
        cls='lee-empty')

def _editor_pane(ws):
    "Primary editor plus an optional client-mounted second pane."
    t = ws.tab
    primary = (Div(_empty_editor(), id='editor', cls='lee-editor', tabindex='-1') if t is None else
               Div(id='editor', cls='lee-editor', data_kind=t.kind, data_path=t.path,
                   data_lang=t.lang or '', tabindex='-1'))
    return Div(primary, Div(cls='lee-editor-splitter'),
               Div(id='editor2', cls='lee-editor lee-editor-secondary', hidden=True),
               Template(_empty_editor(), id='leeempty'),
               cls='lee-editor-stage', id='editorstage')

def _exec_strip():
    "The merged exec box. One editor; the live/agent toggle decides where it runs."
    return Section(
        Div(Span('exec', cls='lee-ptitle'), Span(id='execscope', cls='lee-scope-tag'),
            Span(cls='lee-spacer'),
            _action_bar('exec'), _menu_button('exec'),
            cls='lee-phead'),
        Div(id='execlog', cls='lee-execlog'),
        Div(id='execbox', cls='lee-execbox'),
        cls='lee-panel lee-exec')

def _term_panel(gate):
    "The terminal drawer: hidden until `ctrl+alt+~` asks for it."
    body = (Div(Div('open a terminal with + or ctrl+`', cls='lee-termempty', id='termempty'),
                id='terms', cls='lee-terms')
            if gate.enabled else Div(gate.why, cls='lee-dim lee-termoff'))
    return Section(
        Div(Span('terminal', cls='lee-ptitle'),
            Div(id='termtabs', cls='lee-termtabs', role='tablist', aria_label='terminal tabs'),
            Button('+', cls='lee-icon', title='new terminal', aria_label='new terminal',
                   onclick='leeNewTerm()'),
            Span(cls='lee-spacer'),
            Button('expand', id='termexpand', cls='lee-icon', title='expand or restore terminal',
                   onclick='leeTermExpand()'),
            Button('external', id='termexternal', cls='lee-icon', hidden=True,
                   title='open this project in your terminal application',
                   onclick='leeExternalTerm()'),
            Button('lazygit', cls='lee-icon', title='open lazygit tab', onclick='leeAct("git")'),
            cls='lee-phead'),
        body,
        cls='lee-panel lee-termpanel', id='termwrap', data_term_src=_asset('lee-term.js'))

def _log_panel():
    "Where the detail a toast cannot hold goes: git output, and what a running app prints."
    return Section(
        Div(Span('logs', cls='lee-ptitle'),
            Button('all', cls='lee-logfilter active', data_log_filter='', onclick='leeLogFilter("")'),
            Button('git', cls='lee-logfilter', data_log_filter='git', onclick='leeLogFilter("git")'),
            Button('history', cls='lee-logfilter', data_log_filter='history', onclick='leeLogFilter("history")'),
            Button('runs', cls='lee-logfilter', data_log_filter='runs', onclick='leeLogFilter("runs")'),
            Span(cls='lee-spacer'),
            Button('copy', cls='lee-icon', title='copy the visible log', onclick='leeLogCopy()'),
            Button('clear', cls='lee-icon', title='clear the log', onclick='leeLogClear()'),
            cls='lee-phead'),
        Div(cls='lee-logbody', id='loglist'),
        cls='lee-panel lee-logpanel', id='logwrap')

def _bottom_dock(ws, gate):
    "One bounded lower workspace: Exec, Terminal and Logs switch in place instead of stacking."
    return Section(
        Div(Button('exec', cls='lee-docktab active', data_dock='exec', onclick='leeDock("exec")'),
            Button('terminal', cls='lee-docktab', data_dock='term', onclick='leeDock("term")'),
            Button('logs', cls='lee-docktab', data_dock='logs', onclick='leeDock("logs")'),
            Span(cls='lee-spacer'),
            Button('−', cls='lee-pane-min', title='minimise bottom tools', aria_label='minimise bottom tools',
                   onclick='leePane("bottom", false)'),
            cls='lee-docktabs', role='tablist', aria_label='bottom tools'),
        Div(_exec_strip(), _term_panel(gate), _log_panel(), cls='lee-dockbody'),
        cls='lee-bottomdock dock-exec', id='bottomdock')

def _memory_panel():
    return Section(
        Div(Span('memory', cls='lee-ptitle'), Span(id='memorystatus', cls='lee-keyscope'),
            Span(cls='lee-spacer'), Button('+', cls='lee-btn go lee-memory-add', title='new agent memory note',
                                            aria_label='new memory note', onclick='leeNewMemoryNote()'), cls='lee-phead'),
        Nav(Button('notes', cls='active', data_memory_view='notes', onclick='leeMemoryNotes()'),
            Button('sources', data_memory_view='sources', onclick='leeMemoryHome()'),
            Button('topics', data_memory_view='topics', onclick='leeMemoryTopics()'),
            Button('vault', data_memory_view='vault', onclick='setMemoryView("vault")',
                   hx_get='/vault/panel', hx_target='#memorybody', hx_swap='innerHTML'),
            Span(cls='lee-spacer'), Button('manage', cls='warn', title='remove remembered items', onclick='leeMemoryPurge()'),
            cls='lee-memory-nav', aria_label='memory views'),
        Form(Input(id='memoryquery', cls='lee-input', placeholder='search remembered research…',
                   autocomplete='off'), Button('search', cls='lee-btn go', type='submit'),
             cls='lee-memory-search', onsubmit='event.preventDefault();leeMemorySearch()'),
        Div(Div('Pages you read and research will appear here.', cls='lee-memory-empty'),
            id='memorybody', cls='lee-memory-body'),
        cls='lee-panel lee-memory')

def _right_workspace(ws):
    "Agent, variables and durable research memory share the right-hand work area."
    return Aside(
        Div(Button('agent', cls='lee-righttab active', data_right='agent', onclick='leeRight("agent")'),
            Button('variables', cls='lee-righttab', data_right='vars', onclick='leeRight("vars")'),
            Button('memory', cls='lee-righttab', data_right='memory', onclick='leeRight("memory")'),
            Button('●', cls='lee-pane-pin pinned', type='button', data_pane_pin='right',
                   title='pinned open — unpin to close it when you click away',
                   aria_label='pin right tools open', aria_pressed='true',
                   onclick='leePinPane("right")'),
            Button('−', cls='lee-pane-min', title='minimise right tools',
                   aria_label='minimise right tools', onclick='leePane("right", false)'),
            cls='lee-righttabs', role='tablist', aria_label='right tools'),
        Div(_agent_panel(ws), _vars_panel(ws), _memory_panel(), cls='lee-rightbody'),
        cls='lee-right right-agent', id='right')

def _agent_panel(ws):
    "Bottom centre; model choices load asynchronously after the editor can paint."
    from .agent.core import DFLT_LOCAL, env as _env
    agent_model = ws.model or _env('MODEL') or DFLT_LOCAL
    inline_model = ws.inline_model or _env('MODEL_INLINE') or 'gpt-mini'
    completion_model = ws.completion_model or _env('MODEL_COMPLETION') or 'gpt-4.1'
    has_state = any(str(layer.get('text') or '').strip() for layer in ws.agent_state_layers.values())
    control = getattr(ws.approvals, 'control', 'guided')
    welcome = None if has_state else Div(
        Strong('Set up this workspace agent'),
        Span('Create a reviewed charter from this codebase. Leela remembers it and can refresh it as the project changes.'),
        Button('Set up agent state', cls='lee-btn go', type='button', onclick='leeAgentState()'),
        cls='lee-agent-welcome')
    return Section(
        Div(Div(Span('agent', cls='lee-ptitle'),
                Span(Span(cls='lee-agent-status-dot'), 'ready', id='agentstatus', cls='lee-agent-status ready', title='agent ready'),
                Span('state active' if has_state else 'no state', id='agentnames', cls='lee-agent-state-badge'),
                cls='lee-agent-heading'),
            Span(cls='lee-spacer'),
            Div(Button('new chat', id='agentnew', cls='lee-btn', title='start a new conversation',
                       onclick='leeAgentNew()'),
                Button('history', id='agenthistory', cls='lee-btn', title='toggle conversation history',
                       onclick='leeAgentHistory()'),
                Button('memory', id='agentmemory', cls='lee-btn', title='choose notes for agent, prompt cells, and completion',
                       onclick='leeMemoryNotes()'),
                Button('state', id='agentstate', cls='lee-btn', title='review or refresh the active agent state',
                       onclick='leeAgentState()'),
                Button('expand', id='agentexpand', cls='lee-btn', title='focus the agent workspace',
                       onclick='leeAgentExpand()'), cls='lee-agent-head-actions'),
            cls='lee-phead lee-agent-head'),
        Div(welcome, id='agentlog', cls='lee-agentlog'),
        Div(Span(cls='lee-agent-run-state'), Span(cls='lee-spacer'),
            Button('Pause after current', cls='lee-btn', type='button', data_agent_pause='1'),
            Button('Stop', cls='lee-btn warn', type='button', data_agent_stop='1'),
            cls='lee-agent-runstrip', id='agentrunstrip', hidden=True, aria_live='polite'),
        Div(Div(id='agentsteerqueue', cls='lee-agent-steerqueue', aria_live='polite'),
            Div(Input(id='agentsteer', cls='lee-input', placeholder='Steer after the current call…'),
                Button('Queue', cls='lee-btn', type='button', onclick='leeQueueSteer()'),
                cls='lee-agent-steer'),
            Div(id='agentattachments', cls='lee-agent-attachments', aria_live='polite'),
            Div(Button('attach image', id='agentattach', cls='lee-btn', type='button', title='attach a workspace image path or paste a screenshot', onclick='leeAgentAttach()'), cls='lee-agent-attachbar'),
            Textarea(id='agentprompt', cls='lee-input lee-prompt', rows='2',
                     placeholder=f'ask, / for commands, @ for files…  ({chord_display("agent_send")})',
                     autocomplete='off', aria_autocomplete='list', aria_controls='agentsuggest'),
            Div(id='agentsuggest', cls='lee-agent-suggest', role='listbox', hidden=True),
            Div(Div(Select(Option('loading…', value=agent_model), id='agentmodel',
                           cls='lee-select lee-composer-model', onchange='leeAgentModel("agent", this.value)',
                           aria_label='conversation model', title='model for this conversation'),
                    Select(Option('autopilot', value='autopilot', selected=control == 'autopilot'),
                           Option('guided', value='guided', selected=control == 'guided'),
                           Option('directed', value='directed', selected=control == 'directed'),
                           id='agentcontrol', cls='lee-select lee-composer-control',
                           onchange='leeAgentControl(this.value)', aria_label='agent mode',
                           title='autopilot: writes pause · guided: writes and network pause · directed: every tool pauses'),
                    Select(Option('automatic reasoning', value='auto'), Option('low reasoning', value='low'),
                           Option('medium reasoning', value='medium'), Option('high reasoning', value='high'),
                           id='agentreasoning', cls='lee-select lee-composer-reasoning',
                           title='reasoning effort for cloud models'),
                    Select(*[Option(v, value=v, selected=str(ws.tool_budget) == v)
                             for v in ('auto', '80', '160', '240', '400')],
                           id='agenttoolbudget', cls='lee-select lee-composer-budget',
                           onchange='leeAgentQuickBudget()', aria_label='tool calls per turn',
                           title='tool calls allowed per turn'),
                    Span(id='agentbudgetstatus', cls='lee-agent-budget-status',
                         title='tool calls used in this turn'), cls='lee-composer-primary'),
                Details(Summary('settings'),
                    Div(Label('prompt cells', Select(Option('loading…', value=inline_model), id='inlinemodel',
                              cls='lee-select', onchange='leeAgentModel("inline", this.value)')),
                        Label('completion', Select(Option('loading…', value=completion_model), id='completionmodel',
                              cls='lee-select', onchange='leeAgentModel("completion", this.value)')),
                        Div(id='jobmodels'),   # the harness's other jobs, drawn from /agent/models
                        Label(Input(type='checkbox', id='autocompact', checked=ws.compact_auto,
                                    onchange='leeAgentCompaction()'), ' compact automatically',
                              cls='lee-check-setting', title='rewrite old context before it reaches the model limit'),
                        Label('compaction', Select(Option('surgical · readable tool trail', value='surgical', selected=ws.compact_strategy == 'surgical'),
                                                   Option('summary · model checkpoint', value='summary', selected=ws.compact_strategy == 'summary'),
                                                   id='compactstrategy', cls='lee-select', onchange='leeAgentCompaction()')),
                        Label('tool calls per turn',
                              Input(id='toolbudget', cls='lee-input', value=str(ws.tool_budget),
                                    list='toolbudgets', autocomplete='off', spellcheck='false',
                                    title=f'auto, or {TOOL_RANGE[0]}–{TOOL_RANGE[1]}',
                                    onchange='leeAgentBudget()')),
                        Datalist(*[Option(value=v) for v in ('auto', '80', '160', '240', '400')], id='toolbudgets'),
                        Label('steps per turn',
                              Input(id='stepbudget', cls='lee-input', value=str(ws.step_budget),
                                    list='stepbudgets', autocomplete='off', spellcheck='false',
                                    title=f'auto, or {STEP_RANGE[0]}–{STEP_RANGE[1]}',
                                    onchange='leeAgentBudget()')),
                        Datalist(*[Option(value=v) for v in ('auto', '20', '40', '60', '80')], id='stepbudgets'),
                        Label(Input(type='checkbox', id='localmultimodal', checked=ws.local_multimodal,
                                    onchange='leeLocalMultimodal(this.checked)'),
                              ' local image/audio encoders', cls='lee-check-setting',
                              title='Reload local LiteRT engines with vision and audio support'),
                        Label(Input(type='checkbox', id='workspace-repo-writes', checked=ws.allow_workspace_repo_writes,
                                    onchange='leeWorkspaceRepoWrites(this.checked)'), ' allow writes to other workspace repos',
                              cls='lee-check-setting', title='Keep approval prompts, but allow approved writes to any repository added to this workspace'),
                        Label(Input(type='checkbox', id='agent-read-outside', checked=ws.agent_read_outside,
                                    onchange='leeAgentReadOutside(this.checked)'), ' read outside the open folders',
                              cls='lee-check-setting',
                              title='Let the agent read a named path anywhere (a sibling checkout, a library in the venv). Writes stay confined; credential files stay refused'),
                        Label(Input(type='checkbox', id='legacymodels', checked=True,
                                    onchange='leeLoadModels(this.checked)'), ' show older models',
                              cls='lee-check-setting'),
                        Button('+ model',type='button',cls='lee-btn',onclick='leeAddModel()',
                               title='save a Hugging Face repo or hosted API model'),
                        cls='lee-routing-popover'), cls='lee-routing lee-agent-settings lee-dismissable'),
                Button('Send', cls='lee-btn go lee-composer-send', onclick='leeAct("agent_send")'),
                cls='lee-composer-footer'),
            cls='lee-promptbar lee-agent-composer'),
        cls='lee-panel lee-agent')

def _footer():
    "Always-visible keys plus status."
    ks = (by_scope('global') + by_scope('editor')).filter(lambda k: k.show == 'footer')
    kids = ks.map(lambda k: Span(Kbd(k.keys[0]), Span(k.label), cls='lee-fkey'))
    return Footer(*kids, Span(cls='lee-spacer'),
                  Span(id='status', cls='lee-status', role='status', aria_live='polite', hidden=True),
                  cls='lee-footer')

def _shell(ws, gate):
    "The whole app body; every structural route returns this so the client re-mounts consistently."
    return Div(
        _header(ws),
        _toolbar(),
        Div(
            _left_workspace(ws),
            Div(cls='lee-split', data_split='left'),
            Div(_editor_pane(ws), Div(cls='lee-hsplit lee-dock-split'),
                _bottom_dock(ws, gate), cls='lee-centre'),
            Div(cls='lee-split', data_split='right'),
            _right_workspace(ws),
            cls='lee-body'),
        _footer(),
        Button('files', cls='lee-pane-restore restore-left', onclick='leePane("left", true)'),
        Button('tools', cls='lee-pane-restore restore-right', onclick='leePane("right", true)'),
        Button('terminal / exec', cls='lee-pane-restore restore-bottom', onclick='leePane("bottom", true)'),
        id='shell', cls='lee-app')

def ide_app(ws: Workspace, gate: TerminalGate = None, workspace_catalog=None):
    "Build the FastHTML IDE around an open workspace. `gate` decides who may open a terminal."
    ws.approvals.listen()
    gate = gate or TerminalGate()
    _runstate = RunState()
    running_cells = _runstate.cells
    hdrs = (Link(rel='icon', href=_asset('favicon.svg'), type='image/svg+xml'),
            Script(src=_asset('htmx.min.js')),
            Script("""try { const legacy = {system: 'leela:system:relaxed', dark: 'leela:dark:relaxed', light: 'leela:light:relaxed', cursor: 'cursor:light:tight'};
const stored = localStorage.getItem('lee-theme') || 'cursor:light:tight';
const [family, mode, density] = (stored.includes(':') ? stored : legacy[stored] || 'cursor:light:tight').split(':');
const resolved = mode === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : mode;
document.documentElement.dataset.theme = family;
document.documentElement.dataset.mode = resolved;
document.documentElement.dataset.density = density || (family === 'cursor' ? 'tight' : 'relaxed');
document.documentElement.style.colorScheme = resolved; } catch (_) {}"""),
            Script(src=_asset('lee-cm6.js')),
            Link(rel='stylesheet', href=_asset('lee-term.css')),
            Link(rel='stylesheet', href=_asset('lee-ide.css')),
            Script(src=_asset('lee-ide.js'), defer=True))
    def _term_cwd(ref=None): return term_cwd(ws, ref)
    def _term_settings(session):
        "The `terminal` settings block, layered user-then-workspace as everything else is."
        from .blocks.settings.settings import Settings
        try: return Settings(session.project_root).effective().get('terminal', {}) or {}
        except Exception: return {}
    async def term_ws(sock):
        "One websocket, one pty. Binary frames are keystrokes; text frames are control."
        await sock.accept()
        t = key = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            gate.check(hello.get('token'))
            kind = hello.get('kind', 'shell')
            cwd = _term_cwd(hello.get('cwd'))
            argv = (lazygit_argv(cwd) if kind == 'git' else
                    gh_auth_argv() if kind == 'gh-auth' else None)
            shell = _term_settings(ws)
            key = hello.get('id') or kind
            from .blocks.runtime.kernels import venv_env
            py = _term_python(ws, cwd)
            env = venv_env(py) if py else None
            prelude = path_prelude(py, shell.get('shell')) if argv is None else ''
            if argv is None:
                argv = shell_argv(shell.get('shell'), shell.get('shellArgs'), shell.get('loginShell'))
            t = ws.terms.open(key, argv=argv, cwd=cwd, env=env, prelude=prelude,
                              cols=int(hello.get('cols') or 80), rows=int(hello.get('rows') or 24))
        except Exception as e:
            await sock.send_text(json.dumps({'t': 'error', 'error': errstr(e)}))
            await sock.close()
            return
        async def to_browser(data): await sock.send_bytes(data)
        async def from_browser():
            while True:
                m = await sock.receive()
                if m['type'] == 'websocket.disconnect': return
                if (b := m.get('bytes')) is not None: t.write(b)
                elif (s := m.get('text')) is not None:
                    c = json.loads(s)
                    if c.get('t') == 'size': t.resize(c.get('cols', 80), c.get('rows', 24))
        pump = asyncio.create_task(t.stream(to_browser))
        recv = asyncio.create_task(from_browser())
        try:
            await asyncio.wait({pump, recv}, return_when=asyncio.FIRST_COMPLETED)
            if pump.done():
                ws.terms.close(key)
                try: await sock.send_text(json.dumps({'t': 'exit', 'note': t.exit_note}))
                except Exception: pass
        finally:
            for task in (pump, recv):
                if not task.done(): task.cancel()
            try: await sock.close()
            except Exception: pass
    app, rt = fast_app(pico=False, default_hdrs=False, hdrs=hdrs,
                       routes=(Mount('/leestatic', Assets(*static_dirs())),
                               WebSocketRoute('/term/ws', term_ws)))
    _docstore = DocStore(ws)
    _docs: dict[str, Notebook] = _docstore.docs
    _buffers: dict[str, str] = _docstore.buffers
    _buffer_bases: dict[str, str] = _docstore.bases
    _run_locks: dict[str, asyncio.Lock] = _docstore.run_locks
    _debug = {'kernel': None, 'origin_path': '', 'cell_id': ''}
    _direct_debug = {'session': None, 'task': None, 'name': ''}
    def _doc():
        t = ws.tab
        return None if t is None else _docs.get(t.path or t.title)
    def _live_assistants():
        "Only the assistants already built -- reaching for `ws.ai` here would construct one."
        return L(ws._ai, ws._inline_ai).filter(lambda a: a is not None)
    def _refresh_assistants():
        for a in _live_assistants(): a.refresh()
    def _dbg(method=None):
        "The kernel holding the paused notebook debugger, when it can serve `method`."
        k = _debug.get('kernel')
        return k if k is not None and (method is None or hasattr(k, method)) else None
    def _open_path(path):
        "The workspace file a debug frame refers to, or '' when it is outside the sandbox."
        try: return str(ws.fs._check(path, must_exist=True))
        except Exception: return ''
    def _frame_path(frame): return (frame.get('source') or {}).get('path') or ''
    def _debug_ui(state):
        "Map temporary cell sources back to the notebook and mark project files safe to open."
        state.update(origin_path=_debug.get('origin_path'), cell_id=_debug.get('cell_id'))
        temp = state.get('source')
        cell_sources = getattr(_debug.get('kernel'), '_debug_sources', {})
        for frame in state.get('frames', []):
            path = _frame_path(frame)
            cell_id = cell_sources.get(path)
            if path == temp or cell_id:
                frame['open_path'] = _debug.get('origin_path') or ''
                frame['cell_id'] = cell_id or _debug.get('cell_id') or ''
            else:
                frame['open_path'] = _open_path(path)
        return state
    def _direct_debug_ui(state):
        for frame in state.get('frames', []): frame['open_path'] = _open_path(_frame_path(frame))
        return state
    def _previous_runs():
        "A reset namespace makes every saved output historical, even though it remains useful."
        _docstore.mark_all_stale()
    async def _k(tab=None):
        "The explicitly picked runtime, else the addressed tab's own project/notebook kernel."
        return await ws.runtime(tab)
    def _run_owner(d):
        "Resolve a notebook request to the tab that submitted it, even after a tab switch."
        ref = str(d.get('path') or '')
        tab = (first(t for t in ws.tabs if (t.path or t.title) == ref) if ref else ws.tab)
        if tab is None or tab.kind != 'notebook': return None, None, None
        nb = _docs.get(tab.path or tab.title)
        key = ws.kernel_key(tab)
        return tab, nb, _run_locks.setdefault(key, asyncio.Lock())
    async def _api(path, params=None, timeout=15):
        "Proxy inspection through the exact runtime used by Run."
        client = await _k()
        return await client.api(path, params, timeout) if client else None
    @rt('/')
    def home():
        return Title('leela'), _shell(ws, gate)
    @rt('/markdown/render')
    async def markdown_render(req):
        "Paste-safe Markdown rendering through mdhtml's explicit dialect."
        d = await req.json()
        text = str(d.get('text') or '')
        if len(text) > 1_000_000: return _fail('markdown fragment is larger than 1 MB')
        if not d.get('allow_raw', True):
            text = re.sub(r'(?m)^([ \t]*`{3,})\{=html\}([ \t]*)$', r'\1html\2', text)
        try:
            from mdhtml import to_mdhtml, to_html
            symbolic = to_mdhtml(text, math='on', implicit_figures=True,
                                 bare_autolinks=True, frontmatter=False)
            rendered = to_html(symbolic, refs='ids', auto_ids=False, hl='spans')
            warnings = list(getattr(symbolic, 'warnings', ())) + list(getattr(rendered, 'warnings', ()))
            return {'html': str(rendered), 'warnings': list(dict.fromkeys(map(str, warnings)))}
        except Exception as e: return _fail(e)
    @rt('/markdown/blocks')
    async def markdown_blocks(req):
        "Top-level block spans of one Markdown document, for placing change marks."
        d = await req.json()
        text = str(d.get('text') or '')
        if len(text) > 1_000_000: return _fail('markdown fragment is larger than 1 MB')
        blocks = md_blocks(text)
        ranges = d.get('ranges') or ()
        return {'blocks': blocks, 'kinds': md_change_kinds(blocks, ranges) if ranges else []}
    @rt('/markdown/diff')
    async def markdown_diff(req):
        "Two versions of a Markdown document paired block against block, in the new order."
        d = await req.json()
        left, right = str(d.get('left') or ''), str(d.get('right') or '')
        if max(len(left), len(right)) > 1_000_000: return _fail('markdown fragment is larger than 1 MB')
        return md_block_diff(left, right)
    @rt('/fs/add_root')
    def add_root(path: str):
        from .core.projects import note_folder
        # `note_folder`: so the next launch reopens it, and the welcome screen offers it.
        try: ws.add_root(path); ws.save(); note_folder(path)
        except Exception as e: return _fail(str(e))
        return _shell(ws, gate)
    @rt('/nb/run')
    async def nb_run(req):
        "Run one cell against its submitting tab's kernel and return its outputs."
        d = await req.json()
        owner_tab, nb, run_lock = _run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return _fail('that cell is no longer at this position', 409)
        nb[i].source = d.get('source', nb[i].source)
        async with run_lock:
            k = await _k(owner_tab)
            owner_tab.running += 1
            try: c = await nb.run(i, k)
            finally: owner_tab.running = max(0, owner_tab.running - 1)
        if owner_tab: owner_tab.dirty = True
        rows, result = await _cell_extras(k, c)
        return {'ok': not c.has_error, 'i': i, 'cell': c.dict(), 'result': result,
                'inline': _inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)}
    @rt('/nb/run/stream')
    async def nb_run_stream(req):
        "Run a cell while streaming its evolving Jupyter outputs as SSE."
        d = await req.json()
        owner_tab, nb, run_lock = _run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return _fail('that cell is no longer at this position', 409)
        nb[i].source = d.get('source', nb[i].source)
        await _off_loop(ws.initialize_empty_notebooks, ws.cwd_for(owner_tab))
        await run_lock.acquire()
        try: k = await _k(owner_tab)
        except BaseException:
            run_lock.release()
            raise
        async def events():
            q = asyncio.Queue()
            if owner_tab: owner_tab.running += 1
            def emitted(_i, _output): q.put_nowait([dict(x) for x in nb[i].outputs])
            task = asyncio.create_task(nb.run(i, k, on_output=emitted))
            run_key = ((owner_tab.path or owner_tab.title) if owner_tab else '', nb[i].id)
            running_cells[run_key] = (k, task)
            try:
                while not task.done() or not q.empty():
                    try: outputs = await asyncio.wait_for(q.get(), 0.12)
                    except asyncio.TimeoutError: continue
                    while not q.empty(): outputs = q.get_nowait()
                    yield _sse('output', {'i': i, 'outputs': outputs})
                c = await task
                if owner_tab: owner_tab.dirty = True
                rows, result = await _cell_extras(k, c)
                yield _sse('done', {'ok': not c.has_error, 'i': i, 'cell': c.dict(), 'result': result,
                                    'inline': _inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)})
            except Exception as e:
                yield _sse('error', {'text': errstr(e)})
            finally:
                owner_tab.running = max(0, owner_tab.running - 1)
                if running_cells.get(run_key, (None,))[1:] == (task,): running_cells.pop(run_key, None)
                if not task.done(): task.cancel()
                run_lock.release()
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/debug/stream')
    async def nb_debug_stream(req):
        "Debug one code cell through ipykernel's Jupyter Debug Protocol."
        d = await req.json()
        owner_tab, nb, run_lock = _run_owner(d)
        i = int(d.get('i', 0))
        if nb is None or not (0 <= i < len(nb)):
            return _fail(f'no cell {i}')
        if d.get('id') and nb[i].id != d['id']:
            return _fail('that cell is no longer at this position', 409)
        if nb[i].cell_type != 'code': return _fail('only code cells can be debugged')
        nb[i].source = d.get('source', nb[i].source)
        await run_lock.acquire()
        try: k = await _k(owner_tab)
        except BaseException:
            run_lock.release()
            raise
        if getattr(k, 'kernel_kind', None) != 'ipykernel' or not hasattr(k, 'debug_start'):
            run_lock.release()
            return _fail('cell debugging currently requires a direct ipykernel runtime')
        if _debug.get('kernel') is not None:
            run_lock.release()
            return _fail('a debugger session is already active', 409)
        breakpoints = d.get('breakpoints') or []
        _debug.update(kernel=k, origin_path=owner_tab.path, cell_id=nb[i].id)
        async def events():
            q, c = asyncio.Queue(), nb[i]
            c.clear(); c.running = True
            if owner_tab: owner_tab.running += 1
            started = asyncio.get_running_loop().time()
            try:
                notebook_sources = [(cell.id, cell.source) for cell in nb.cells if cell.cell_type == 'code']
                verified = await k.debug_start(c.source, breakpoints, notebook_sources)
                yield _sse('ready', {'i': i, 'breakpoints': verified})
                def output(_out): q.put_nowait(('output', None))
                def debug(event): q.put_nowait(('debug', event))
                task = asyncio.create_task(k.execute(c.source, on_output=output, on_debug=debug))
                while not task.done() or not q.empty():
                    try: kind, value = await asyncio.wait_for(q.get(), .12)
                    except asyncio.TimeoutError: continue
                    if kind == 'output':
                        continue
                    if value.get('event') == 'stopped':
                        state = await k.debug_state((value.get('body') or {}).get('threadId'))
                        yield _sse('stopped', _debug_ui(state))
                    elif value.get('event') == 'continued':
                        yield _sse('continued', value.get('body') or {})
                result = await task
                c.outputs, c.execution_count = result.outputs, result.execution_count
                c.execution_ms = (asyncio.get_running_loop().time() - started) * 1000
                c.fresh = True
                if owner_tab: owner_tab.dirty = True
                yield _sse('done', {'ok': result.ok, 'i': i, 'cell': c.dict(),
                                    'error': result.error})
            except Exception as e:
                yield _sse('error', {'text': errstr(e)})
            finally:
                c.running = False
                owner_tab.running = max(0, owner_tab.running - 1)
                try: await k.debug_stop()
                except Exception: pass
                if _debug.get('kernel') is k: _debug.update(kernel=None, origin_path='', cell_id='')
                run_lock.release()
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/debug/state')
    async def nb_debug_state(frame_id: int = 0):
        if (k := _dbg('debug_state')) is None: return _fail('no ipykernel debugger is active')
        try:
            state = await k.debug_state(frame_id=frame_id or None)
            return _debug_ui(state)
        except Exception as e: return _fail(e)
    @rt('/nb/debug/source')
    async def nb_debug_source(frame_id: int):
        "Source for a stack frame outside the workspace, addressed by trusted frame id—not a client path."
        if (k := _dbg()) is None: return _fail('no ipykernel debugger is active')
        try:
            state = await k.debug_state(frame_id=frame_id)
            frame = first(f for f in state.get('frames', []) if f.get('id') == frame_id)
            if frame is None: return _fail('debug frame is no longer available')
            source = frame.get('source') or {}
            reply = await k.debug_request('source', {'source': source,
                                                      'sourceReference': source.get('sourceReference', 0)})
            return {'content': reply.get('body', {}).get('content', ''), 'line': frame.get('line'),
                    'path': source.get('path', ''), 'name': frame.get('name', '')}
        except Exception as e: return _fail(e)
    @rt('/nb/debug/variables')
    async def nb_debug_variables(reference: int):
        if (k := _dbg('debug_variables')) is None: return _fail('no ipykernel debugger is active')
        try: return {'variables': await k.debug_variables(reference)}
        except Exception as e: return _fail(e)
    @rt('/nb/debug/evaluate')
    async def nb_debug_evaluate(req):
        d, k = await req.json(), _dbg('debug_evaluate')
        if k is None: return _fail('no ipykernel debugger is active')
        try:
            body = await k.debug_evaluate(d.get('code', ''), d.get('frame_id'))
            return {'ok': True, **body}
        except Exception as e: return _fail(e)
    @rt('/nb/debug/control')
    async def nb_debug_control(req):
        d, k = await req.json(), _dbg('debug_control')
        if k is None: return _fail('no ipykernel debugger is active')
        try:
            await k.debug_control(d.get('command', ''), d.get('thread_id'))
            return {'ok': True, 'command': d.get('command')}
        except Exception as e: return _fail(e)
    @rt('/nb/debug/stop')
    async def nb_debug_stop():
        if (k := _dbg('debug_stop')) is None: return _fail('no ipykernel debugger is active')
        try:
            await k.debug_stop()
            await k.interrupt()
            return {'ok': True}
        except Exception as e: return _fail(e)
    @rt('/nb/ask')
    async def nb_ask(req):
        "Run a prompt cell: the assistant answers, with the notebook above it as context."
        d = await req.json()
        nb, i = _doc(), int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if not (0 <= i < len(nb)): return _fail(f'no cell {i}')
        nb[i].source = d.get('source', nb[i].source)
        try: c = await _off_loop(ws.ask_cell, nb, i)
        except Exception as e: return _fail(e)
        if ws.tab: ws.tab.dirty = True
        a = ws.inline_ai
        return {'ok': a.ready, 'i': i, 'cell': c.dict(), 'note': a.note,
                'problems': a.problems,
                'cells': [x.dict() for x in nb.cells],
                'activity': a.activity.rows(mark=a.activity._mark),
                'edits': _edit_diffs(a)}
    @rt('/nb/ask/stream')
    async def nb_ask_stream(req):
        "Stream a prompt cell into its own reply area as markdown arrives."
        d = await req.json()
        nb, i = _doc(), int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if not (0 <= i < len(nb)): return _fail(f'no cell {i}')
        nb[i].source = d.get('source', nb[i].source)
        nb[i].running = True
        owner_tab = ws.tab
        if owner_tab: owner_tab.running += 1
        a = ws.inline_ai
        async def events():
            import queue as _q
            out, done = _q.Queue(), object()
            def pump():
                try:
                    for chunk in ws.ask_cell_stream(nb, i): out.put(('chunk', chunk))
                except Exception as e: out.put(('error', errstr(e)))
                finally: out.put((done, None))
            task = asyncio.get_running_loop().run_in_executor(None, pump)
            approval_id, activity_versions = None, {}
            def changed_activity(): return _activity_changes(a, activity_versions)
            try:
                while True:
                    try: kind, value = await _off_loop(out.get, True, 0.25)
                    except _q.Empty: kind = value = None
                    pending = ws.pending_approval
                    if pending is not None and pending.id != approval_id:
                        approval_id = pending.id
                        proposal = {**pending.dict(), 'schemas': _tool_schemas(a)}
                        yield _sse('approval', proposal)
                    for row in changed_activity(): yield _sse('activity', row)
                    if await req.is_disconnected():
                        a.cancel()
                        return
                    if kind is None: continue
                    if kind is done:
                        for row in changed_activity(): yield _sse('activity', row)
                        break
                    yield _sse(kind, {'text': value})
                await task
                c = nb[i]
                yield _sse('done', {'ok': a.ready, 'i': i, 'cell': c.dict(), 'note': a.note,
                                    'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                                    'problems': a.problems,
                                    'cells': [x.dict() for x in nb.cells],
                                    'activity': a.activity.rows(mark=a.activity._mark),
                                    'edits': _edit_diffs(a)})
            finally:
                nb[i].running = False
                if owner_tab is not None:
                    owner_tab.running = max(0, owner_tab.running - 1)
                    owner_tab.dirty = True
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/nb/edit')
    async def nb_edit(req):
        "Structural edits: insert / delete / move / type / split / merge."
        d = await req.json()
        nb = _doc()
        if nb is None: return _fail('no notebook open')
        op, i = d.get('op'), int(d.get('i', 0))
        for src in d.get('sources', []):
            j = int(src.get('i', -1))
            if 0 <= j < len(nb): nb[j].source = src.get('source', nb[j].source)
        if op == 'insert': nb.insert(i, Cell(source=d.get('source', ''), cell_type=d.get('cell_type', 'code')))
        elif op == 'delete': nb.delete(i)
        elif op == 'delete_many': nb.delete_many(d.get('indices') or [i])
        elif op == 'move': nb.move(i, int(d.get('d', 1)))
        elif op == 'move_many': i = nb.move_many(d.get('indices') or [i], int(d.get('target', i)))
        elif op == 'type':
            nb.cycle_type(i) if d.get('cycle') else nb.set_type(i, d.get('cell_type', 'code'))
        elif op == 'split': nb.split(i, int(d.get('offset', 0)))
        elif op == 'duplicate': nb.duplicate(i)
        elif op in ('paste', 'paste_many'):
            raws = d.get('cells') if op == 'paste_many' else [d.get('cell')]
            if not isinstance(raws, list) or not raws or not all(isinstance(raw, dict) for raw in raws):
                return _fail('cell clipboard is empty')
            fields = Cell.__dataclass_fields__
            try: pasted = [Cell(**{name: raw[name] for name in fields if name in raw}) for raw in raws]
            except (TypeError, ValueError) as e: return _fail(f'invalid cell clipboard: {e}')
            nb.paste_many(i, pasted)
        elif op == 'merge_above': nb.merge(i - 1) if i > 0 else None
        elif op == 'merge_below': nb.merge(i)
        elif op == 'clear_cell': nb.clear_cell(i)
        elif op == 'undo':
            if (at := nb.undo()) is None: return _fail('no cell operation to undo')
        elif op == 'redo':
            if (at := nb.redo()) is None: return _fail('no cell operation to redo')
        elif op == 'merge': nb.merge(i)
        elif op == 'source':
            nb[i].source = d.get('source', '')
            nb.dirty = True
        elif op == 'context':
            mode = str(d.get('mode') or 'auto')
            if mode not in ('auto', 'keep', 'discard'): return _fail('context mode must be auto, keep or discard')
            nb._checkpoint(i)
            nb[i].context_mode = mode
            nb.dirty = True
        elif op == 'clear': nb.clear_all()
        else: return _fail(f'unknown op {op!r}')
        if ws.tab: ws.tab.dirty = nb.dirty
        return {'ok': True, 'cells': [c.dict() for c in nb.cells],
                'index': at if op in ('undo', 'redo') else i}
    @rt('/nb/save')
    async def nb_save(req):
        d=await req.json();path=str(d.get('path') or '')
        t=(first(x for x in ws.tabs if x.path==path) if path else ws.tab)
        if t is None:return _fail('nothing open')
        current_version = _disk_version(t.path)
        base_version = str(d.get('base_disk_version') or '')
        if base_version and current_version != base_version and not d.get('force'):
            return _fail('the file changed on disk after this browser draft began; review it before overwriting', 409)
        try:
            target = t.path or d.get('path')
            before = Path(target).read_text(encoding='utf-8', errors='replace') if target and Path(target).exists() else None
            if t.kind == 'notebook':
                nb=_docs.get(t.path or t.title)
                if nb is None:
                    try:nb=Notebook.load(t.path) if t.path else Notebook.blank()
                    except Exception:return _fail('no notebook')
                    _docs[t.path or t.title]=nb
                for c in d.get('cells', []):
                    if 0 <= c['i'] < len(nb): nb[c['i']].source = c['source']
                nb.save(t.path or d.get('path'), sandbox=ws.fs)
            else:
                ws.fs.write(t.path, d.get('text', ''))
                _buffers.pop(t.path or t.title, None)
            t.dirty = False
            _buffer_bases.pop(t.path or t.title, None)
            after = Path(target).read_text(encoding='utf-8', errors='replace') if target and Path(target).exists() else None
            operation = ws.journal.record(f'Save {t.title}', [(target, before, after)], kind='save')
            return {'ok': True, 'path': t.path, 'disk_version': _disk_version(t.path),
                    'operation_id': operation['id'] if operation else ''}
        except Exception as e:
            return _fail(e)
    @rt('/tabs/save-all')
    async def tabs_save_all():
        "Persist every dirty open tab, including buffers belonging to inactive tabs."
        saved, errors = 0, []
        for t in ws.tabs:
            if not t.dirty: continue
            key = t.path or t.title
            try:
                if not t.path: raise ValueError(f'{t.title} needs a filename before it can be saved')
                base = _buffer_bases.get(key)
                if base and _disk_version(t.path) != base:
                    raise ValueError('changed on disk after this browser draft began; open the tab to review it')
                if t.kind == 'notebook':
                    nb = _docs.get(key)
                    if nb is None: nb = Notebook.load(t.path)
                    nb.save(t.path, sandbox=ws.fs)
                else:
                    ws.fs.write(t.path, _buffers.get(key, ws.fs.read(t.path)))
                    _buffers.pop(key, None)
                t.dirty = False
                _buffer_bases.pop(key, None)
                saved += 1
            except Exception as e: errors.append(f'{t.title}: {errstr(e)}')
        ws.save()
        if errors: return _fail('; '.join(errors))
        return {'ok': True, 'saved': saved}
    @rt('/history/operations')
    def operation_history(limit: int = 50):
        return {'operations': ws.journal.rows(limit)}
    def _forget_operation_buffers(op):
        for path in (r['path'] for r in op.get('resources', [])):
            _docstore.forget(path)
            if (tab := first(t for t in ws.tabs if t.path == path)): tab.dirty = False
    @rt('/history/undo')
    async def operation_undo(req):
        try:
            d = await req.json(); op = ws.journal.undo(d.get('id', ''))
            _forget_operation_buffers(op)
            return {'ok': True, 'operation': op}
        except Exception as e: return _fail(e, 409)
    @rt('/history/redo')
    async def operation_redo(req):
        try:
            d = await req.json(); op = ws.journal.redo(d.get('id', ''))
            _forget_operation_buffers(op)
            return {'ok': True, 'operation': op}
        except Exception as e: return _fail(e, 409)
    @rt('/diff')
    async def diff_route(req):
        "What the editor holds, against what is on disk."
        d = await req.json()
        t = ws.tab
        if t is None: return _fail('nothing open')
        disk = ws.disk_text(t)
        if disk is None: return _fail(f'{t.title} has never been saved')
        if t.kind == 'notebook':
            nb = _doc()
            if nb is None: return _fail('no notebook open')
            for c in d.get('cells', []):
                if 0 <= c['i'] < len(nb): nb[c['i']].source = c['source']
            buf = nb.source_text()
        else:
            buf = d.get('text', '')
        return {'path': t.path, 'title': t.title, **_diff(disk, buf)}
    @rt('/exec')
    async def exec_route(req):
        "Run in the owner kernel or the agent's protected persistent overlay."
        d = await req.json()
        code, scope = (d.get('code') or '').strip(), d.get('scope', 'live')
        if not code: return {'ok': True, 'text': '', 'outputs': []}
        k = _debug.get('kernel') or await _k()
        if scope == 'live' and getattr(k, '_debug_thread', None) and hasattr(k, 'debug_evaluate'):
            try:
                body = await k.debug_evaluate(code, d.get('frame_id'))
                return {'ok': True, 'text': body.get('result') or 'ok', 'outputs': [],
                        'scope': 'debug', 'debug': True, 'variablesReference': body.get('variablesReference', 0)}
            except Exception as e:
                return {'ok': False, 'text': errstr(e), 'outputs': [], 'scope': 'debug', 'debug': True}
        if scope == 'agent':
            r = await k.api('/agent/api/exec', {'code': code, 'scope': 'overlay'})
            if r is None: return {'ok': False, 'text': 'no agent session on this kernel', 'outputs': []}
            txt = r.get('stdout') or ''
            if r.get('result'): txt += (('\n' if txt else '') + (r['result'].get('value') or ''))
            err = await _explain(k, r.get('error'), 'overlay')
            return {'ok': bool(r.get('ok')), 'text': (err or txt or 'ok'), 'scope': 'agent',
                    'result': r.get('result')}
        res = await k.execute(code)
        has_result = any(o.get('output_type') == 'execute_result' for o in res.outputs)
        latest = await k.api('/api/result', timeout=2) if res.ok and has_result else None
        return {'ok': res.ok, 'text': await _explain(k, res.error) or res.text or 'ok',
                'outputs': res.outputs, 'count': res.execution_count, 'scope': 'live',
                'result': (latest or {}).get('result')}
    @rt('/run/file')
    async def run_file(req):
        "Run the open .py as a script, in the tab's kernel."
        d = await req.json()
        code, label = ws.run_file_code(src=d.get('text'))
        if code is None: return _fail(label)
        k = await _k()
        res = await k.execute(code)
        return {'ok': res.ok, 'label': label, 'outputs': res.outputs,
                'text': await _explain(k, res.error) or res.text or 'ok'}
    @rt('/run/code')
    async def run_code(req):
        "Run an arbitrary block -- what the `run selection` button sends -- in the tab's kernel."
        d = await req.json()
        code = (d.get('code') or '').strip()
        if not code: return _fail('nothing to run')
        k = await _k()
        res = await k.execute(code)
        return {'ok': res.ok, 'outputs': res.outputs,
                'text': await _explain(k, res.error) or res.text or 'ok'}
    @rt('/exec/history')
    async def exec_history(n: int = 200):
        "The rolling history notebook, oldest first -- what ctrl+up/down cycles through."
        r = await _api('/api/history', {'n': n})
        return {'cells': (r or {}).get('cells', [])}
    @rt('/lint')
    async def lint_route(req):
        "Compiler or structural diagnostics for an unsaved buffer; source is never run."
        d = await req.json(); lang, code = d.get('lang'), str(d.get('code') or '')
        if lang == 'python':
            diagnostics = _python_diagnostics(code, d.get('path') or '<cell>')
            path = str(d.get('path') or '')
            if path.endswith('.py'):
                rows, note = await _off_loop(ws.lsp.diagnostics, path, code)
                lines, starts = _line_starts(code)
                def offset(pos):
                    row = max(0, min(int(pos.get('line', 0)), len(lines)-1))
                    return starts[row] + min(int(pos.get('character', 0)), len(lines[row].rstrip('\r\n')))
                severity = {1:'error', 2:'warning', 3:'info', 4:'info'}
                diagnostics += [{'from': offset(x.get('range', {}).get('start', {})),
                                 'to': offset(x.get('range', {}).get('end', {})),
                                 'severity': severity.get(x.get('severity'), 'info'),
                                 'message': x.get('message', ''), 'source': x.get('source') or 'Pyright',
                                 'code': str(x.get('code') or '')} for x in rows]
                return {'diagnostics': diagnostics, 'lsp': {'available': ws.lsp.available, 'note': note}}
            return {'diagnostics': diagnostics}
        if lang != 'markdown': return {'diagnostics': []}
        diagnostics = []
        try:
            from mdhtml import to_mdhtml
            symbolic = to_mdhtml(code, math='on', implicit_figures=True,
                                 bare_autolinks=True, frontmatter=False)
            for warning in getattr(symbolic, 'warnings', ()):
                diagnostics.append({'from': 0, 'to': min(1, len(code)), 'severity': 'warning',
                                    'message': str(warning), 'source': 'markdown'})
        except Exception as e:
            diagnostics.append({'from': 0, 'to': min(1, len(code)), 'severity': 'error',
                                'message': str(e), 'source': 'markdown'})
        if d.get('path') == '<agent-state>':
            required = ('Role', 'Goal', 'Hard boundaries', 'Routing rules', 'Tool practices',
                        'Verification', 'Progress', 'Key decisions', 'Next steps', 'Critical context')
            headings = {m.group(1).strip().lower() for m in re.finditer(r'^#{1,3}\s+(.+)$', code, re.M)}
            for heading in required:
                if heading.lower() not in headings:
                    diagnostics.append({'from': len(code), 'to': len(code), 'severity': 'info',
                                        'message': f'Consider adding “{heading}” to keep this charter complete.',
                                        'source': 'agent state'})
        return {'diagnostics': diagnostics}
    @rt('/complete')
    async def complete_route(req, pos: int = 0):
        "Completions from the kernel, so venv modules complete like they do in a real shell."
        d = await req.json()
        k = _debug.get('kernel') or await _k()
        code, at=d.get('code',''),int(d.get('pos',pos))
        if getattr(k, '_debug_thread', None) and hasattr(k, 'debug_complete'):
            try: runtime=await k.debug_complete(code,at)
            except Exception: runtime={'from':at,'matches':[]}
        else:
            try: runtime=await k.complete(code,at)
            except Exception: runtime={'from':at,'matches':[]}
        return await _off_loop(ws.search.merge_completions,code,at,runtime)
    @rt('/complete/warm')
    async def complete_warm():
        "Load the configured completion engine before the first requested suggestion."
        c = ws.completer
        b = await _off_loop(c.a._be_or_none, 'completion')
        return {'ok': b is not None, 'model': b.spec.name if b else '', 'note': c.a.note}
    @rt('/complete/ai')
    async def ai_complete_route(req):
        "One inline suggestion from the local model, for what belongs at the cursor."
        d = await req.json()
        c = ws.completer
        context = ''
        if (nb := _doc()) is not None:
            i = max(0, min(int(d.get('cell', 0)), len(nb) - 1))
            context = '\n\n'.join(x.source for j, x in enumerate(nb.cells)
                                    if j != i and x.cell_type == 'code' and x.source.strip())[-6000:]
        code,at=d.get('code',''),int(d.get('pos',0))
        graph=await _off_loop(ws.search.completion_patches,code,at)
        patches='\n'.join(f"{x['type']}.{x['name']}: {x['doc']}" for x in graph.get('details',[]))
        context='\n\n'.join(x for x in (context,patches) if x)
        text = await _off_loop(c.complete,code,at,d.get('lang') or 'python',context)
        return {'text':text,'note':c.note,'ready':c.ready,'model':c.a.routing.name_for('completion'),
                'graph_methods':len(graph.get('details',[]))}
    @rt('/complete/selection')
    async def selection_help(req):
        "One throwaway AI response for selected editor text; never edits until the browser accepts it."
        d = await req.json()
        text = str(d.get('text') or '')
        instruction = str(d.get('instruction') or '').strip()
        mode, lang = d.get('mode', 'instruction'), str(d.get('lang') or 'text')
        if not text.strip(): return _fail('select some text first')
        if len(text) > 120_000: return _fail('selection is larger than 120,000 characters')
        if len(instruction) > 4000: return _fail('instruction is larger than 4,000 characters')
        if mode == 'summary':
            sp = ('Summarise the selected text faithfully and concisely. Preserve important names, values, '
                  'constraints and conclusions. Output only the proposed replacement, without a preamble.')
            answer = await _off_loop(ws.ai.summarise, text, sp)
        else:
            if not instruction: return _fail('tell the AI what help you want')
            sp = ('You are inline editor help. Follow the instruction against only the selected text. '
                  'Return only the proposed replacement text: no preamble, no markdown fence, no commentary '
                  'outside the replacement. Preserve the source language and formatting unless asked otherwise.')
            prompt = f'Language: {lang}\nInstruction: {instruction}\n\n<selection>\n{text}\n</selection>'
            answer = await _off_loop(ws.ai.oneshot, prompt, sp, 'completion', 2048)
        answer = str(answer or '').strip()
        from fastcore.xtras import fenced_blocks
        if blocks := fenced_blocks(answer): answer = str(blocks[-1][1]).strip()
        if not answer: return _fail(ws.ai.note or 'the model returned no suggestion')
        return {'ok': True, 'text': answer, 'mode': mode,
                'model': ws.ai.routing.name_for('summary' if mode == 'summary' else 'completion')}
    @rt('/debug/capabilities')
    def debug_capabilities():
        from .blocks.debug.debug import debugpy_available
        from .blocks.runtime.kernels import project_python
        python = ws.pool.default_python or project_python(ws.fs.roots) or sys.executable
        return {'python': str(python), 'debugpy': debugpy_available(python),
                'notebook': True, 'direct': debugpy_available(python)}
    @rt('/debug/install')
    async def debug_install(req):
        from .blocks.runtime.kernels import project_python
        d = await req.json(); python = d.get('python') or ws.pool.default_python or project_python(ws.fs.roots)
        if not python: return _fail('choose a project interpreter first')
        def install():
            uv = shutil.which('uv')
            cmd = ([uv, 'pip', 'install', '--python', str(python), 'debugpy'] if uv else
                   [str(python), '-m', 'pip', 'install', 'debugpy'])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode: raise RuntimeError(result.stderr or result.stdout)
        try: await _off_loop(install); return {'ok': True, 'python': str(python)}
        except Exception as e: return _fail(e)
    @rt('/debug/start')
    async def debug_start(req):
        "Launch a Python file/module or attach through a direct debugpy DAP session."
        from .blocks.debug.debug import DebugSession
        from .blocks.runtime.kernels import project_python
        d = await req.json(); name = d.get('name') or ''
        run = ws.runs.get(name) if name else None
        config = run.dict() if run else dict(d)
        root = ws.project_root or Path.cwd()
        python = d.get('python') or ws.pool.default_python or project_python(ws.fs.roots) or sys.executable
        cwd = config.get('cwd') or str(root)
        if cwd and not Path(cwd).is_absolute(): cwd = str((root/str(cwd)).resolve())
        program = config.get('program') or (ws.tab.path if ws.tab and (ws.tab.path or '').endswith('.py') else '')
        if program and not Path(program).is_absolute(): program = str((root/program).resolve())
        config.update(program=program, cwd=cwd, justMyCode=config.get('justMyCode', True),
                      stopOnEntry=config.get('stopOnEntry', False), subProcess=config.get('subProcess', True),
                      breakOnRaised=config.get('breakOnRaised', False), breakOnUncaught=config.get('breakOnUncaught', True))
        if not config.get('program') and not config.get('module') and config.get('request','launch') == 'launch':
            return _fail('open a Python file or set program/module in the run configuration')
        previous = _direct_debug.get('session')
        if previous: await _off_loop(previous.disconnect)
        session = DebugSession(python, cwd)
        breakpoints = d.get('breakpoints') or ({program: d.get('lines') or []} if program else {})
        try:
            await _off_loop(session.start_adapter)
            await _off_loop(session.launch, config, breakpoints)
        except Exception as e:
            await _off_loop(session.disconnect)
            return _fail(e)
        _direct_debug.update(session=session, name=config.get('name') or Path(program or config.get('module','python')).name)
        return {'ok': True, 'name': _direct_debug['name'], 'python': str(python)}
    @rt('/debug/events')
    async def debug_events(req):
        "Stream direct DAP output, stops, continuation, exit, and errors."
        session = _direct_debug.get('session')
        if session is None: return _fail('no direct debugger is active')
        async def events():
            while session.alive or not session.events.empty():
                if await req.is_disconnected(): break
                try: event = await _off_loop(session.events.get, True, .25)
                except Exception: continue
                name, body = event.get('event'), event.get('body') or {}
                if name == 'stopped':
                    try: body = _direct_debug_ui(await _off_loop(session.state, body.get('threadId')))
                    except Exception as e: body = {'message': errstr(e)}; name = 'error'
                yield _sse(name or 'event', body)
                if name in ('terminated', 'exited'): break
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @rt('/debug/state')
    async def debug_state(frame_id: int = 0):
        session = _direct_debug.get('session')
        if session is None: return _fail('no direct debugger is active')
        try: return _direct_debug_ui(await _off_loop(session.state, None, frame_id or None))
        except Exception as e: return _fail(e)
    @rt('/debug/variables')
    async def debug_variables(reference: int):
        session = _direct_debug.get('session')
        if session is None: return _fail('no direct debugger is active')
        try: return {'variables': await _off_loop(session.variables, reference)}
        except Exception as e: return _fail(e)
    @rt('/debug/evaluate')
    async def debug_evaluate(req):
        session = _direct_debug.get('session'); d = await req.json()
        if session is None: return _fail('no direct debugger is active')
        try: return await _off_loop(session.evaluate, d.get('expression',''), d.get('frame_id'))
        except Exception as e: return _fail(e)
    @rt('/debug/control')
    async def debug_control(req):
        session = _direct_debug.get('session'); d = await req.json()
        if session is None: return _fail('no direct debugger is active')
        try: return {'ok': True, **(await _off_loop(session.control, d.get('command')))}
        except Exception as e: return _fail(e)
    @rt('/debug/breakpoints')
    async def debug_breakpoints(req):
        session = _direct_debug.get('session'); d = await req.json()
        if session is None: return _fail('no direct debugger is active')
        try: return {'ok': True, 'breakpoints': await _off_loop(session.set_breakpoints, d.get('path'), d.get('breakpoints') or [])}
        except Exception as e: return _fail(e)
    @rt('/debug/stop')
    async def debug_stop_direct():
        session = _direct_debug.get('session')
        if session: await _off_loop(session.disconnect)
        _direct_debug.update(session=None, name='')
        return {'ok': True}
    @rt('/runs/file')
    def runs_file():
        "The configurations file as text, or a template for one, for the in-IDE editor."
        p = ws.runs.path
        t = ws.tab
        try: text = p.read_text() if (p and p.exists()) else ''
        except Exception: text = ''
        if not text:
            text = json.dumps(ws.runs.template(t.path if t else None), indent=2) + '\n'
        return {'path': str(p or ''), 'exists': bool(p and p.exists()), 'text': text,
                'note': ws.runs.note}
    @rt('/screen')
    async def screen(req):
        "Park a screenshot to go with the next question."
        d = await req.json()
        url = d.get('data_url') or ''
        if not url.startswith('data:image'): return _fail('no image in that capture')
        if len(url) > 12_000_000: return _fail('screen capture is larger than 9 MB', 413)
        import base64
        try: png = base64.b64decode(url.split(',', 1)[1], validate=True)
        except Exception as e: return _fail(e)
        if len(png) > 9_000_000: return _fail('screen capture is larger than 9 MB', 413)
        ws.put_screen(png=png, note='a screenshot from the browser')
        return {'ok': True, 'bytes': len(png)}
    @rt('/agent/attachment')
    async def agent_attachment(req):
        """Save a pasted image inside the active workspace and return its attachment path."""
        d = await req.json()
        path = str(d.get('path') or '').strip()
        if path:
            image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
            p = ws.fs._check(path, must_exist=True)
            if not p.is_file() or p.suffix.lower() not in image_exts:
                return _fail('attachment is not a workspace image')
            return {'ok': True, 'path': str(p), 'name': p.name}
        url = str(d.get('data_url') or '')
        if not url.startswith('data:image/'):
            return _fail('no image attachment')
        if len(url) > 12_000_000:
            return _fail('image attachment is larger than 9 MB', 413)
        import base64
        try: data = base64.b64decode(url.split(',', 1)[1], validate=True)
        except Exception as e: return _fail(e)
        if len(data) > 9_000_000: return _fail('image attachment is larger than 9 MB', 413)
        ext = '.png' if url.startswith('data:image/png') else '.jpg'
        folder = ws.cwd_for() / '.leela-attachments'
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f'paste-{os.urandom(6).hex()}{ext}'
        p.write_bytes(data)
        return {'ok': True, 'path': str(p), 'name': p.name}

    @rt('/agent/info')
    async def agent_info(): return await _api('/agent/api/info') or {'mode': 'off'}
    @rt('/agent/sessions')
    async def agent_sessions():
        return await _api('/agent/api/sessions') or {'current': None, 'sessions': []}
    @rt('/agent/transcript')
    async def agent_transcript(session: str = ''):
        live = await _api('/agent/api/transcript', {'session': session}) or {'cells': []}
        return {'id': live.get('id'), 'path': live.get('path'), 'cells': live.get('cells', []),
                'agent': list(ws.ai.history) if not session else [],
                'inline': list(ws.inline_ai.history) if not session else []}
    @rt('/agent/resume')
    async def agent_resume(req):
        "Continue a saved conversation: its turns go back into the model's context, and onto the screen."
        d = await req.json()
        if ws.ai.busy: return _fail('cannot resume while the agent is working', 409)
        try: s = await _off_loop(ws.ai.resume_session, str(d.get('session') or 'latest'))
        except Exception as e: return _fail(e)
        return {'ok': True, 'session': s['id'], 'note': ws.ai.note,
                'turns': [t for t in ws.ai.history if t.get('session') == s['id']]}

    @rt('/agent/new')
    async def agent_new():
        if ws.ai.busy: return _fail('cannot start a new conversation while the agent is working', 409)
        from .blocks.agent.ai import Assistant
        old = ws._ai
        ws._ai = Assistant(ws, model=old.model.name, surface='agent', local_multimodal=ws.local_multimodal,
                           on_compact=ws._compacted, history_name='agent')
        ws.approvals.host = ws._ai.host
        old.close()
        return {'ok': True, 'session': ws.ai.session_id}

    @rt('/agent/history')
    async def agent_history():
        "All durable turns grouped by model-context session, newest session first."
        execution = await _api('/agent/api/sessions') or {'sessions': []}
        turns = [t for t in ws.ai.history if t.get('model') != 'scripted']
        return {'sessions': _history_sessions(turns, execution.get('sessions', [])),
                'model': ws.ai.model.name, 'current': ws.ai.session_id}
    @rt('/agent/models')
    def agent_models(legacy: bool = True):
        from .agent.core import DFLT_LOCAL, available_models, auth_status, resolve
        from .blocks.agent.models import load_models, mark_models, runtimes
        notes = {}
        def _try(what, f, dflt=None):
            "`f()`, or `dflt` and a note saying why: no one failure may blank the picker."
            try: return f()
            except Exception as e: notes[what] = errstr(e); return dflt
        def _spec(name): return _try(name, lambda: resolve(name))
        def _name(what, get, dflt): return _try(what, get, dflt) or dflt
        saved = _try('saved models', load_models, []) or []
        rows = _try('model catalog', lambda: available_models(include_legacy=legacy), []) or []
        rows += [{'value':x['name'],'label':x['name'],'provider':x['runtime'],
                  'source':f"saved · {x['model_id']}",'custom':True} for x in saved]
        agent_dflt = ws.model or os.environ.get('LEELA_MODEL') or DFLT_LOCAL
        agent = _name('agent model', lambda: ws.ai.model.name, agent_dflt) if ws._ai is not None else agent_dflt
        inline_dflt = ws.inline_model or os.environ.get('LEELA_MODEL_INLINE') or 'gpt-mini'
        inline = (_name('inline model', lambda: ws.inline_ai.model.name, inline_dflt)
                  if ws._inline_ai is not None else inline_dflt)
        completion_dflt = ws.completion_model or os.environ.get('LEELA_MODEL_COMPLETION') or 'gpt-4.1'
        completion = (_name('completion model', lambda: ws.ai.routing.name_for('completion'), completion_dflt)
                      if ws._ai is not None else completion_dflt)
        for current in (agent, inline, completion):
            spec = _spec(current)
            if spec is None:
                why = f'unavailable ({notes.get(current, "")})'
                row = first(r for r in rows if r['value'] == current)
                if row is None: rows.append(row := {'value': current, 'label': current})
                row.update(provider='unavailable', source=why, unavailable=True)
                continue
            if not any((s := _spec(r['value'])) and s.model_id == spec.model_id for r in rows):
                provider = spec.model_id.partition('/')[0] if not spec.local else spec.runtime
                rows.append({'value': current, 'label': current, 'provider': provider,
                             'source': 'saved choice · provider credentials may be required'})
        def selected(current):
            spec = _spec(current)
            if spec is None: return current
            return ifnone(first(r['value'] for r in rows
                                if (s := _spec(r['value'])) and s.model_id == spec.model_id), current)
        # The routed jobs with no field of their own, reported chosen or not.
        jobs = {}
        if ws._ai is not None:
            from .agent.core import JOBS
            jobs = {j: _name(f'{j} model', lambda j=j: ws.ai.routing.name_for(j), '')
                    for j in JOBS if j not in ('turn', 'completion')}
        return {'models': mark_models(rows), 'saved':saved, 'notes': notes,
                'auth': _try('auth', auth_status, {}) or {}, 'runtimes': _try('runtimes', runtimes, []) or [],
                'jobs': jobs,
                'selected': {'agent': selected(agent), 'inline': selected(inline),
                             'completion': selected(completion), **jobs}}
    @rt('/agent/models/add')
    async def agent_models_add(req):
        "Save a Hugging Face repo/URL or hosted provider model alias."
        from .blocks.agent.models import save_model
        try:return {'ok':True,'model':save_model(await req.json())}
        except Exception as e:return _fail(e)
    @rt('/agent/models/remove')
    async def agent_models_remove(req):
        from .blocks.agent.models import delete_model
        try:return {'ok':True,'name':delete_model((await req.json()).get('name',''))}
        except Exception as e:return _fail(e)
    @rt('/agent/settings')
    async def agent_settings(req):
        "Set engine-level agent options. LiteRT engines reload lazily after a change."
        d = await req.json()
        if 'litert_backend' in d:
            try:
                from .blocks.agent.ai import Assistant
                which = str(d.get('litert_backend') or '').strip().lower()
                if which not in Assistant.LITERT_BACKENDS:
                    raise ValueError(f'litert backend must be one of {", ".join(Assistant.LITERT_BACKENDS)}')
                live = _live_assistants()
                for a in live: a.set_litert_backend(which)
                if not live: os.environ['LEELA_LITERT_BACKEND'] = which
                ws.litert_backend = which
                ws.save()
                return {'ok': True, 'litert_backend': which,
                        'note': f'LiteRT runs on the {which.upper()}; engines reload on the next request'}
            except Exception as e: return _fail(e)
        try:
            enabled = d.get('local_multimodal')
            if not isinstance(enabled, bool): raise ValueError('local_multimodal must be true or false')
            live = _live_assistants()
            if any(a.busy for a in live): raise RuntimeError('cannot change local multimodal while an assistant is working')
            for a in live: a.set_local_multimodal(enabled)
            ws.local_multimodal = enabled
            ws.save()
            return {'ok': True, 'local_multimodal': enabled,
                    'note': f'local image/audio encoders {"enabled" if enabled else "disabled"}'}
        except Exception as e: return _fail(e)
    @rt('/agent/workspace-repo-writes')
    async def agent_workspace_repo_writes(req):
        d = await req.json(); enabled = d.get('enabled')
        if not isinstance(enabled, bool): return _fail('enabled must be true or false')
        ws.allow_workspace_repo_writes = enabled; ws.save()
        return {'ok': True, 'enabled': enabled,
                'note': f'workspace repository writes {"enabled" if enabled else "disabled"}; approval rules still apply'}
    @rt('/agent/read-outside')
    async def agent_read_outside(req):
        "Reads outside the open folders. Writes are unaffected, and credentials stay refused."
        d = await req.json(); enabled = d.get('enabled')
        if not isinstance(enabled, bool): return _fail('enabled must be true or false')
        ws.agent_read_outside = enabled; ws.save()
        return {'ok': True, 'enabled': enabled,
                'note': f'reads outside the open folders {"allowed" if enabled else "refused"}; writes are unchanged'}

    @rt('/agent/compaction')
    async def agent_compaction(req):
        "Configure visible automatic compaction without restarting the model conversation."
        d = await req.json(); strategy = d.get('strategy', ws.compact_strategy)
        if strategy not in {'surgical', 'summary'}: return _fail('strategy must be surgical or summary')
        auto = d.get('auto', ws.compact_auto)
        if not isinstance(auto, bool): return _fail('auto must be true or false')
        ws.compact_auto, ws.compact_strategy = auto, strategy
        for agent in _live_assistants():
            agent.compactor.auto, agent.compactor.strategy = auto, strategy
        ws.save()
        return {'ok': True, 'auto': auto, 'strategy': strategy,
                'note': f'auto compaction {"on" if auto else "off"} · {strategy}'}
    @rt('/agent/budget')
    async def agent_budget(req):
        "How much work one turn may do, changed without restarting the conversation."
        from .workspace import budget_value
        d = await req.json()
        for key, given in (('tool_budget', d.get('tools')), ('step_budget', d.get('steps'))):
            if given is None: continue
            lo, hi = TOOL_RANGE if key == 'tool_budget' else STEP_RANGE
            value = budget_value(given, lo, hi)
            if value == 'auto' and str(given).strip().lower() != 'auto':
                return _fail(f'{key}: use auto, or a number from {lo} to {hi}')
            setattr(ws, key, value)
        for agent in _live_assistants(): agent.tool_budget, agent.step_budget = ws.tool_budget, ws.step_budget
        ws.save()
        return {'ok': True, 'tools': ws.tool_budget, 'steps': ws.step_budget,
                'note': f'tool budget {ws.tool_budget} · steps {ws.step_budget}'}
    @rt('/agent/budget/state')
    def agent_budget_state():
        "What is actually in force, so a refused edit can put the box back rather than blank it."
        return {'ok': True, 'tools': ws.tool_budget, 'steps': ws.step_budget,
                'tool_range': list(TOOL_RANGE), 'step_range': list(STEP_RANGE)}
    @rt('/agent/model')
    async def agent_model(req):
        d = await req.json()
        try:
            from .agent.core import JOBS
            from .blocks.agent.models import load_models
            load_models()
            # `agent` and `inline` are two assistants, each on its own `turn`; the rest are jobs.
            target = d.get('target', 'agent')
            if target not in ('agent', 'inline') and target not in JOBS:
                return _fail(f'unknown model target {target!r}')
            assistant = ws.inline_ai if target == 'inline' else ws.ai
            job = 'turn' if target in ('agent', 'inline') else target
            spec = assistant.set_model((d.get('model') or '').strip(), job=job)
            if target == 'inline': ws.inline_model = spec.name
            elif target == 'completion': ws.completion_model = spec.name
            elif target == 'agent': ws.model = spec.name
            else: ws.job_models[job] = spec.name
            ws.save()
            return {'ok': True, 'target': target, 'model': spec.name, 'note': model_note(spec)}
        except Exception as e: return _fail(e)
    @rt('/agent/memory')
    async def agent_memory():
        "Editable notes and their explicit per-model session routing."
        notes = await _off_loop(ws.memory.agent_notes)
        rows = [{**note, 'text': await _off_loop(ws.memory.exact_text, str(note['id']))} for note in notes]
        return {'notes': rows, 'selected': ws.agent_memory_selection,
                'targets': {'agent': 'Agent conversation', 'inline': 'Prompt cells',
                            'completion': 'Code completion'}}
    @rt('/agent/memory/save')
    async def agent_memory_save(req):
        d = await req.json(); title = (d.get('title') or '').strip(); text = (d.get('text') or '').strip()
        if not text: return _fail('memory note is empty')
        previous = str(d.get('id') or '')
        saved = await _off_loop(ws.memory.remember_agent_note, title, text, previous)
        if not saved: return _fail(ws.memory.note)
        new_id = str(saved.get('doc_id') or '')
        if previous and new_id:
            for target, ids in ws.agent_memory_selection.items():
                ws.agent_memory_selection[target] = [new_id if value == previous else value for value in ids]
        requested = d.get('targets', [])
        if not isinstance(requested, list): return _fail('targets must be a list')
        for target in requested:
            if target not in ws.agent_memory_selection: return _fail('targets must contain only agent, inline, or completion')
            if new_id and new_id not in ws.agent_memory_selection[target]: ws.agent_memory_selection[target].append(new_id)
        ws.save()
        _refresh_assistants()
        return {'ok': True, 'id': new_id, 'note': ws.memory.note}
    @rt('/agent/memory/select')
    async def agent_memory_select(req):
        d = await req.json(); target = str(d.get('target') or '')
        if target not in ws.agent_memory_selection: return _fail('target must be agent, inline, or completion')
        ids = d.get('ids')
        if not isinstance(ids, list): return _fail('ids must be a list')
        known = {str(note['id']) for note in await _off_loop(ws.memory.agent_notes)}
        selected = list(dict.fromkeys(str(value) for value in ids if str(value) in known))
        ws.agent_memory_selection[target] = selected; ws.save()
        assistant = ws._ai if target in {'agent', 'completion'} else ws._inline_ai
        if assistant is not None: assistant.refresh()
        tokens = sum([estimate_tokens(await _off_loop(ws.memory.exact_text, v)) for v in selected])
        return {'ok': True, 'target': target, 'ids': selected, 'tokens': tokens}
    @rt('/agent/memory/delete')
    async def agent_memory_delete(req):
        doc_id = str((await req.json()).get('id') or '')
        known = {str(note['id']) for note in await _off_loop(ws.memory.agent_notes)}
        if doc_id not in known: return _fail('unknown agent memory note')
        for target, ids in ws.agent_memory_selection.items():
            ws.agent_memory_selection[target] = [value for value in ids if value != doc_id]
        ok = await _off_loop(ws.memory.forget, doc_id); ws.save()
        _refresh_assistants()
        return {'ok': ok, 'note': ws.memory.note}
    @rt('/agent/states')
    def agent_states():
        "Saved conversation states and the state currently injected into the briefing."
        active = any(str(layer.get('text') or '').strip() and layer.get('enabled', True)
                     for layer in ws.agent_state_layers.values())
        return {'active': active, 'active_text': ws.agent_state,
                'layers': ws.agent_state_layers, 'states': ws.memory.agent_states()}
    @rt('/agent/state/template')
    def agent_state_template():
        "A complete, usable rules template with this workspace's actual tool catalog."
        from .blocks.agent.ai import STATE_TEMPLATE
        tools = _tool_schemas(ws.ai)
        catalog = '\n'.join(f"- `{t['name']}` ({t['group']}): {t['description']}" for t in tools)
        return {'template': STATE_TEMPLATE, 'tools': tools,
                'catalog': '## Available tools\n' + (catalog or '- No tools are currently available.')}
    @rt('/agent/state/bootstrap')
    async def agent_state_bootstrap(req):
        "Ask the summary model to fill a transparent charter from the template and real tools."
        from .blocks.agent.ai import STATE_TEMPLATE
        d = await req.json(); intent = (d.get('intent') or '').strip()
        tools = _tool_schemas(ws.ai)
        catalog = '\n'.join(f"- {t['name']} [{t['group']}]: {t['description']}" for t in tools)
        project = '\n'.join(f'- {root}' for root in ws.ai.host.roots) or '- no folder open'
        prompt = (f'<workspace>\n{project}\n</workspace>\n\n<available-tools>\n{catalog}\n</available-tools>\n\n'
                  f'<user-intent>\n{intent or "Help me configure a safe, effective coding agent for this workspace."}\n</user-intent>\n\n'
                  f'<template>\n{STATE_TEMPLATE}\n</template>\n\nFill every bracketed field with concrete, concise guidance. '
                  'Keep the headings exactly. Mention tools only when they actually appear in available-tools. '
                  'Do not invent project facts; mark unknown facts as needing confirmation.')
        text = await _off_loop(ws.ai.oneshot, prompt,
                               'Design a user-owned coding-agent charter. Return complete Markdown only.', 'summary', 1800)
        if not text: text = STATE_TEMPLATE + '\n\n## Available tools\n' + catalog
        return {'ok': True, 'text': text, 'tools': tools,
                'model': ws.ai.routing.name_for('summary'), 'generated': text != STATE_TEMPLATE}
    @rt('/agent/state/draft')
    def agent_state_draft():
        "A structured, editable state distilled deterministically from the visible conversation."
        turns = list(ws.ai.history[-12:]) if ws._ai is not None else []
        conversation = '\n\n'.join(f"### User\n{t.get('prompt','')}\n\n### Agent\n{t.get('reply','')}"
                                   for t in turns)
        from .blocks.agent.ai import STATE_TEMPLATE
        state = ws.agent_state or STATE_TEMPLATE
        return {'state': state, 'layers': ws.agent_state_layers,
                'conversation': conversation, 'turns': len(turns)}
    @rt('/agent/state/save')
    async def agent_state_save(req):
        "Save the user's edited state to durable semantic memory and optionally activate it."
        d = await req.json(); text = (d.get('text') or '').strip()
        if not text: return _fail('agent state is empty')
        title = (d.get('title') or '').strip() or 'Agent state'
        saved = await _off_loop(ws.memory.remember_agent_state, title, text,
                                 {'session': ws.ai.session_id if ws._ai is not None else '',
                                  'turns': len(ws.ai.history) if ws._ai is not None else 0,
                                  'roots': [str(root) for root in ws.fs.roots]})
        if not saved: return _fail(ws.memory.note)
        layer = (d.get('layer') or 'task').strip()
        if d.get('activate', True): ws.ai.set_state(text, layer=layer, source='memory')
        return {'ok': True, 'saved': saved, 'active': ws.agent_state}
    @rt('/agent/state/suggest')
    def agent_state_suggest(q: str = ''):
        "Relevant saved states remain advisory; the browser decides whether to attach one."
        states = {str(s['id']): s for s in ws.memory.agent_states()}
        hits = ws.memory.search(q, limit=12) if q.strip() else []
        ids = [i for i in dict.fromkeys(str(h.get('doc_id') or '') for h in hits) if i in states]
        return {'query': q, 'states': [states[i] for i in ids[:5]]}
    @rt('/agent/state/diagnostics')
    async def agent_state_diagnostics(req):
        "Token budget, stale paths, and duplicate/conflicting headings for edited state."
        d = await req.json(); text = str(d.get('text') or '')
        tokens = estimate_tokens(text, ws.ai.backend.count_tokens if ws._ai is not None else None)
        paths = set(re.findall(r'(?<![\w.-])(?:[\w.-]+/)+[\w.-]+', text))
        def absent(path):
            try: return not ws.fs._check(path).exists()
            except Exception: return True
        missing = [p for p in paths if absent(p)]
        headings = [h.strip().lower() for h in re.findall(r'^#{1,3}\s+(.+)$', text, re.M)]
        duplicate = sorted({h for h in headings if headings.count(h) > 1})
        return {'tokens': tokens, 'context': ws.ai.model.ctx if ws._ai is not None else None,
                'missing_paths': sorted(missing), 'duplicate_headings': duplicate}
    @rt('/agent/state/update')
    async def agent_state_update(req):
        "Use the summary model to propose a reviewed state replacement; never activate automatically."
        d = await req.json(); current = str(d.get('current') or ''); conversation = str(d.get('conversation') or '')
        project = _project_state_context(ws)
        prompt = (f'<current-state>\n{current}\n</current-state>\n\n<conversation>\n{conversation[-20000:]}\n</conversation>\n\n'
                  f'<current-project>\n{project}\n</current-project>\n\n'
                  'Return the complete updated state using Goal, Constraints, Progress (Done/In progress/Blocked), '
                  'Key decisions, Next steps, and Critical context. Reconcile stale assumptions with current-project evidence. '
                  'Preserve still-valid user preferences, remove completed next steps, and never invent project facts.')
        text = await _off_loop(ws.ai.oneshot, prompt,
                               'Update explicit agent state. Return Markdown only, without a fence.', 'summary', 1600)
        if not text: return _fail(ws.ai.note or 'state update model returned nothing')
        return {'ok': True, 'text': text, 'diff': _diff(current, text)}
    @rt('/agent/state/activate')
    async def agent_state_activate(req):
        "Activate an edited state without adding it to durable memory."
        d = await req.json(); text = (d.get('text') or '').strip(); layer = d.get('layer') or 'task'
        try: ws.ai.set_state(text, layer=layer, enabled=d.get('enabled', True), source='user')
        except ValueError as e: return _fail(e)
        return {'ok': True, 'state': text, 'layer': layer}
    @rt('/agent/state/compare')
    async def agent_state_compare(req):
        "Compare one remembered revision with edited text before replacing or merging it."
        d = await req.json(); text = await _off_loop(ws.memory.agent_state_text, str(d.get('id') or ''))
        if not text: return _fail(ws.memory.note or 'saved state is empty')
        current = str(d.get('current') or '')
        return {'ok': True, 'state': text, 'diff': _diff(current, text)}
    @rt('/agent/state/load')
    async def agent_state_load(req):
        "Load a remembered state into the live agent briefing, preserving its conversation history."
        d = await req.json(); doc_id = str(d.get('id') or ''); layer = d.get('layer') or 'task'
        text = await _off_loop(ws.memory.agent_state_text, doc_id)
        if not text: return _fail(ws.memory.note or 'saved state is empty')
        try: ws.ai.set_state(text, layer=layer, source='memory')
        except ValueError as e: return _fail(e)
        return {'ok': True, 'state': text, 'layer': layer}
    @rt('/agent/commands')
    def agent_commands():
        "Slash-command metadata for the prompt's inline command picker."
        help_by_name = {name: help for name, (_, help) in ws.ai.registry.commands.items()}
        builtins = {
            'model': 'show or change the model', 'cost': 'show token and cost totals',
            'compact': 'compact the current context', 'skills': 'list available skills',
            'skill': 'read one skill', 'tools': 'list tools available to the agent',
            'extensions': 'show loaded tool extensions', 'reload': 'reload tools, skills and extensions',
        }
        describe = lambda item: (getattr(item, '__doc__', '') or '').strip().split('\n')[0]
        return {
            'commands': [{'name': n, 'help': help_by_name.get(n) or builtins.get(n, '')}
                         for n in ws.ai.commands()],
            'tools': [{'name': t.__name__, 'help': describe(t)} for t in ws.ai.tools],
            'skills': [{'name': s.name, 'help': s.description} for s in ws.ai.skills],
        }
    @rt('/agent/status')
    def agent_status():
        "Whether the assistant is loaded, what model it is on, and what it is doing right now."
        return ws.ai.status()
    @rt('/agent/stop')
    def agent_stop():
        "Ask the model to stop generating. The turn in flight returns whatever it already had."
        try:
            if ws.ai.cancel(): return {'ok': True}
            return {'ok': False, 'error': 'the assistant is not running'}
        except Exception as e:
            return {'ok': False, 'error': errstr(e)}
    @rt('/agent/stream')
    async def agent_stream(req):
        "One turn as server-sent events, so the browser fills in as the model writes."
        q = (req.query_params.get('prompt') or '').strip()
        if not q: return _fail('nothing to ask')
        try: attachments = json.loads(req.query_params.get('attachments') or '[]')
        except Exception: return _fail('attachments must be a JSON array')
        if not isinstance(attachments, list): return _fail('attachments must be a JSON array')
        reasoning = (req.query_params.get('reasoning') or '').lower()
        if reasoning not in ('', 'auto', 'low', 'medium', 'high'):
            return _fail('reasoning must be auto, low, medium or high')
        reasoning = None if reasoning in ('', 'auto') else reasoning
        a = ws.ai
        if a.busy: return _fail('the assistant is already working; use steering or stop it first', 409)
        async def events():
            import queue as _q
            out, done = _q.Queue(), object()
            def pump():
                try:
                    nb = _doc()
                    context = nb.context(len(nb)) if nb is not None else ''
                    context_path = nb.path if nb is not None else ''
                    for c in ws.ask_stream(q, attachments=attachments, reasoning=reasoning,
                                           context=context, context_path=context_path): out.put(('chunk', c))
                except Exception as e: out.put(('error', errstr(e)))
                finally: out.put((done, None))
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(None, pump)
            finished, approval_id, activity_versions, execution_version = False, None, {}, None
            compact_count = a.compactor.count
            def changed_activity(): return _activity_changes(a, activity_versions)
            try:
                while True:
                    try:
                        kind, val = await _off_loop(out.get, True, 0.25)
                    except _q.Empty:
                        kind = val = None
                    if a.compactor.count != compact_count:
                        compact_count = a.compactor.count
                        yield _sse('compaction', {'count': compact_count, 'strategy': a.compactor.strategy,
                                                  'note': a.compactor.note, 'text': a.compactor.last})
                    state = ws.approvals.state()
                    version = json.dumps(state, sort_keys=True)
                    if version != execution_version:
                        execution_version = version
                        yield _sse('execution', state)
                    pending = ws.pending_approval
                    if pending is not None and pending.id != approval_id:
                        approval_id = pending.id
                        proposal = {**pending.dict(), 'schemas': _tool_schemas(a)}
                        yield _sse('approval', proposal)
                    for row in changed_activity(): yield _sse('activity', row)
                    if await req.is_disconnected(): break
                    if kind is None: continue
                    if kind is done:
                        finished = True
                        for row in changed_activity(): yield _sse('activity', row)
                        break
                    yield _sse(kind, {'text': val} if kind == 'chunk' else {'error': val})
            finally:
                if not finished:
                    try: a.cancel()
                    except Exception: pass
            if not finished: return
            await task
            capabilities = a.turn_capabilities(a.current_turn_id)
            yield _sse('done', {'ok': a.ready, 'note': a.note, 'media': _turn_media(a),
                                'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                                'session_usage': a.use.dict(), 'session_usage_label': repr(a.use),
                                'model': a.model.name, 'turn_id': a.current_turn_id,
                                'branch_id': a.current_branch_id, 'capabilities': capabilities,
                                'problems': a.problems,
                                'activity': a.activity.rows(mark=a.activity._mark),
                                'edits': _edit_diffs(a)})
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    def _turn_media(a):
        "Pictures the turn produced, as data URLs. A tool result is a path, which a browser cannot draw."
        import base64
        out = []
        for m in (getattr(a, 'turn_media', None) or []):
            data = m.get('data')
            if not data: continue
            out.append({'mime': m.get('mime') or 'image/png',
                        'url': f"data:{m.get('mime') or 'image/png'};base64,{base64.b64encode(data).decode()}"})
        return out

    @rt('/agent/approval')
    def agent_approval():
        "The call waiting for a person, or None. It stays inline so the rest of the IDE remains usable."
        a = ws.pending_approval
        pending = ({**a.dict(), 'schemas': _tool_schemas(ws.ai)} if a is not None else None)
        return {'pending': pending, 'control': getattr(ws.approvals, 'control', 'guided')}
    @rt('/agent/control')
    async def agent_control(req):
        "Choose how often tool proposals become editable checkpoints."
        d = await req.json()
        try: control = ws.approvals.set_control((d.get('control') or '').strip())
        except ValueError as e: return _fail(e)
        return {'ok': True, 'control': control}
    @rt('/agent/run-policy')
    async def agent_run_policy(req):
        "Run through bounded future calls, or pause immediately after the current one."
        d = await req.json()
        if d.get('policy') == 'pause':
            ws.approvals.set_pause_next()
            return {'ok': True, **ws.approvals.state()}
        try: policy = ws.approvals.set_run_policy(d.get('policy') or 'once', d.get('count') or 1)
        except (ValueError, TypeError) as e: return _fail(e)
        return {'ok': True, 'policy': policy, **ws.approvals.state()}
    @rt('/agent/steer')
    async def agent_steer(req):
        "Queue guidance after the current tool; the next proposed call is skipped and replaced by it."
        d = await req.json()
        text = (d.get('text') or '').strip()
        if d.get('cancel'):
            ws.approvals.queue_steer('')
            return {'ok': True, **ws.approvals.state()}
        if not text: return _fail('steering instruction is empty')
        ws.approvals.queue_steer(text)
        return {'ok': True, **ws.approvals.state()}
    @rt('/agent/tool-preview')
    async def agent_tool_preview(req):
        "Preview the resolved call without executing it."
        d = await req.json()
        tool, args = (d.get('tool') or '').strip(), d.get('args')
        if tool not in {t.__name__ for t in ws.ai.tools}: return _fail(f'unknown tool {tool}')
        if not isinstance(args, dict): return _fail('tool arguments must be an object')
        try: return {'ok': True, 'preview': _tool_preview(ws.ai, tool, args)}
        except Exception as e: return _fail(e)
    @rt('/agent/branches')
    def agent_branches():
        "Turn boundaries available for a true model-context fork in this running session."
        a = ws.ai
        return {'active': a.current_branch_id,
                'turns': [{'turn_id': tid, 'branch_id': cp.get('branch_id', 'main'),
                           'before': 'before' in cp, 'after': 'after' in cp}
                          for tid, cp in a.checkpoints.items()]}
    @rt('/agent/fork')
    async def agent_fork(req):
        "Restore a model-history checkpoint as a new active conversation branch."
        d = await req.json()
        try: branch = ws.ai.fork(d.get('turn_id') or '', d.get('stage') or 'after', d.get('branch_id') or '')
        except Exception as e: return _fail(e)
        return {'ok': True, **branch}
    @rt('/agent/revise')
    async def agent_revise(req):
        "Create a branch whose last assistant prose is the user's edited response."
        d = await req.json(); text = (d.get('text') or '').strip()
        if not text: return _fail('revised response is empty')
        try: branch = ws.ai.revise(d.get('turn_id') or '', text, d.get('branch_id') or '')
        except Exception as e: return _fail(e)
        return {'ok': True, **branch}
    @rt('/agent/retry-tool')
    async def agent_retry_tool(req):
        "Rerun a completed read-only call; return its result without changing model history."
        from .blocks.agent.ai import WRITE_TOOLS
        d = await req.json()
        tool, args = (d.get('tool') or '').strip(), d.get('args')
        if tool in WRITE_TOOLS: return _fail('only read-only calls can be retried from a checkpoint')
        choices = {t.__name__: t for t in ws.ai.tools}
        if tool not in choices: return _fail(f'unknown tool {tool}')
        if not isinstance(args, dict): return _fail('tool arguments must be an object')
        try: result = await _off_loop(choices[tool], **args)
        except Exception as e: return _fail(e)
        return {'ok': True, 'tool': tool, 'args': args, 'result': str(result)}
    @rt('/agent/turn-transaction')
    def agent_turn_transaction(turn_id: str = ''):
        tx = ws.ai.turn_transactions.get(turn_id)
        if tx is None: return _fail(f'no transaction for {turn_id}', 404)
        return {'transaction': {**tx, 'files': [{'path': p, **_diff(s['before'], s['after'])}
                                                for p, s in tx['files'].items()]}}
    @rt('/agent/rollback-turn')
    async def agent_rollback_turn(req):
        d = await req.json()
        try: tx = ws.ai.rollback_turn(d.get('turn_id') or '')
        except Exception as e: return _fail(e)
        return {'ok': True, 'turn_id': tx['turn_id'], 'paths': list(tx['files']),
                'irreversible': tx['irreversible']}
    @rt('/agent/rollback-tool')
    async def agent_rollback_tool(req):
        "Rollback one snapshotted file call when its output is still the current file."
        d = await req.json()
        try: path = ws.approvals.rollback((d.get('id') or '').strip())
        except Exception as e: return _fail(e)
        return {'ok': True, 'path': path}
    @rt('/agent/approval/request')
    async def agent_approval_request(req):
        "Ask for a decision in this browser on behalf of an external Rishi session."
        try: d = await req.json()
        except Exception as e: return _fail(f'approval request must be valid JSON: {e}')
        tc = d.get('tool_call') or {}
        fn = tc.get('function') or {} if isinstance(tc, dict) else {}
        name, args = fn.get('name'), fn.get('arguments', {})
        if args in (None, ''): args = {}
        if not name: return _fail('tool_call.function.name is required')
        if isinstance(args, str):
            try: args = json.loads(args)
            except json.JSONDecodeError as e: return _fail(f'tool_call.function.arguments is not valid JSON at position {e.pos}')
        if not isinstance(args, dict): return _fail('tool_call.function.arguments must be an object')
        try: timeout = min(3600, max(1, float(d.get('timeout', ws.approvals.timeout))))
        except (TypeError, ValueError): return _fail('timeout must be a number of seconds')
        a = await _off_loop(ws.approvals.request, name, args, True, timeout)
        return {'ok': True, 'answer': a.dict()}
    @rt('/agent/approve')
    async def agent_approve(req):
        "Answer a pending approval. `note` is the reason, and the reason goes back to the model."
        d = await req.json()
        args = d.get('args')
        if args is not None and not isinstance(args, dict): return _fail('tool arguments must be an object')
        tool = (d.get('tool') or '').strip() or None
        choices = {t.__name__: t for t in ws.ai.tools}
        if tool and tool not in choices: return _fail(f'unknown tool {tool}')
        if bool(d.get('ok')) and tool and args is not None:
            import inspect
            try: inspect.signature(choices[tool]).bind(**args)
            except TypeError as e: return _fail(f'invalid {tool} arguments: {e}')
        a = ws.answer_approval(d.get('id') or '', bool(d.get('ok')), (d.get('note') or '').strip(),
                               session=bool(d.get('session')), tool=tool, args=args)
        if a is None: return _fail('nothing is waiting for an answer')
        return {'ok': True, 'answer': a.dict()}
    @rt('/agent/command')
    async def agent_command(req):
        "Run a slash command (`/model`, `/cost`, `/compact`, `/skills`, `/tools`, `/reload`)."
        d = await req.json()
        line = (d.get('line') or '').strip()
        if not line: return {'ok': True, 'text': 'commands: ' + ', '.join('/' + c for c in ws.ai.commands())}
        out = await _off_loop(ws.ai.command, line)
        if out is None: return _fail(f'unknown command {line.split()[0]}')
        if line.lstrip('/').split(' ')[0] in ('tool-budget', 'steps'):
            ws.tool_budget, ws.step_budget = ws.ai.tool_budget, ws.ai.step_budget
            for agent in _live_assistants(): agent.tool_budget, agent.step_budget = ws.tool_budget, ws.step_budget
            ws.save()
        return {'ok': True, 'text': out}
    @rt('/agent/ask')
    async def agent_ask(req):
        "One turn with the assistant."
        d = await req.json()
        q = (d.get('prompt') or '').strip()
        if not q: return _fail('nothing to ask')
        a = ws.ai
        text = await _off_loop(ws.ask, q)
        return {'ok': a.ready, 'text': text, 'note': a.note,
                'activity': a.activity.rows(mark=a.activity._mark),
                'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                'session_usage': a.use.dict(), 'session_usage_label': repr(a.use), 'model': a.model.name,
                'edits': _edit_diffs(a)}
    @rt('/nb/interrupt')
    async def nb_interrupt(req):
        "Interrupt one exact running cell, force-restarting its managed kernel if needed."
        d = await req.json()
        item = running_cells.get((d.get('path') or '', d.get('id') or ''))
        if item is None: return _fail('that cell is not running')
        k, _task = item
        if not hasattr(k, 'stop'): return _fail('this external runtime cannot be stopped safely')
        return await k.stop(timeout=2.0)
    connect_all(app, ws, BLOCKS, docs=_docstore, running=_runstate, gate=gate,
                catalog=workspace_catalog)
    return app

def serve_ide(roots=(), port=5001, host='127.0.0.1', agent='restricted', kernel_port=8400,
              open_ws=True, kernel='ipykernel',
              model=None, approvals='ask', agent_scope='overlay', python=None,
              app_window=False, cdp_port=9223, transport='auto', gateway_port=8787,
              shell=None):
    "Start one web workspace, or independent app-window workspaces under ``--app``."
    import uvicorn
    shell = ifnone(shell, 'chrome' if app_window else 'none')
    try:
        loopback = host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError('Leela executes code and may only bind to a loopback address')
    from . import leela_cfg
    from .hub import WorkspaceHub, WorkspaceSite, workspace_slugs
    roots = [Path(r).expanduser().resolve() for r in roots]
    gate = TerminalGate(host=host)
    requested_transport = transport
    transport = ('gateway' if app_window else 'direct') if transport == 'auto' else transport
    gateway = None
    if transport == 'gateway':
        try:
            from .blocks.runtime.kernels import GatewayService
            gateway = GatewayService(port=gateway_port).start()
        except (ImportError, RuntimeError) as e:
            if requested_transport != 'auto': raise
            transport = 'direct'
            print(f'  gateway unavailable; using direct kernel transport: {errstr(e)}')
    if app_window and roots:
        from .blocks.runtime.kernels import RuntimeBroker
        sites, hub, broker = [], None, RuntimeBroker()
        for i, (root, slug) in enumerate(zip(roots, workspace_slugs(r.name for r in roots))):
            state = leela_cfg/'workspaces'/f'{slug}.json'
            kw = dict(port=kernel_port + i * 100, agent=agent, kernel=kernel, model=model,
                      approvals=approvals, agent_scope=agent_scope, python=python,
                      transport=transport, gateway=gateway, cdp_port=cdp_port)
            ws = Workspace.load(path=state, **kw) if open_ws else Workspace(**kw)
            state.parent.mkdir(parents=True, exist_ok=True)
            ws._state_path = state
            broker.register(ws.pool)
            if root not in ws.fs.roots: ws.add_root(root)
            if ws.restore_remembered_agent_state(): ws.save()
            ws.jobs.tick()
            app = ide_app(ws, gate, workspace_catalog=lambda: hub.catalog())
            sites.append(WorkspaceSite(slug, root.name, str(root), app))
        hub = WorkspaceHub(sites, port)
        app = hub
        urls = [row['url'] for row in hub.catalog()]
        print(f'leela  {len(sites)} independent workspaces on :{port}')
        for row in hub.catalog(): print(f"  {row['name']}: {row['url']}")
        if shell == 'chrome':
            import threading, time, urllib.request
            def open_windows():
                probe = f'http://127.0.0.1:{port}/'
                for _ in range(150):
                    try: urllib.request.urlopen(probe, timeout=.25).close(); break
                    except Exception: time.sleep(.1)
                from fossick.cdp import cdp_app
                for url in urls:
                    result = cdp_app(url, port=cdp_port)
                    print(f"  Chrome {'reused' if result['reused'] else 'started'}: {url}")
            threading.Thread(target=open_windows, daemon=True, name='leela-cdp-open').start()
    else:
        kw = dict(port=kernel_port, agent=agent, kernel=kernel, model=model, approvals=approvals,
                  agent_scope=agent_scope, python=python, transport=transport, gateway=gateway,
                  cdp_port=cdp_port)
        if open_ws and not roots:
            ws = Workspace.load(**kw)
        else:
            try: remembered = (leela_cfg/'workspace.json').read_json() if open_ws else {}
            except Exception: remembered = {}
            if model is None: kw['model'] = remembered.get('model')
            kw['inline_model'] = remembered.get('inline_model') or 'gpt-mini'
            kw['completion_model'] = remembered.get('completion_model') or 'gpt-4.1'
            ws = Workspace(**kw)
        for r in roots: ws.add_root(r)
        # A shell launch means "here"; a frozen one has no such answer, so: welcome screen.
        if not ws.fs.roots and not getattr(sys, 'frozen', False): ws.add_root(os.getcwd())
        if ws.restore_remembered_agent_state(): ws.save()
        app = ide_app(ws, gate)
        if (secs := ws.jobs.tick()): print(f'  vault watches polled every {secs}s')
        print(f'leela  http://{host}:{port}   folders: '
              + (', '.join(p.name for p in ws.fs.roots) or 'no folder open yet'))
        if shell == 'chrome':
            import threading, time, urllib.request
            def open_window():
                url = f'http://127.0.0.1:{port}/'
                for _ in range(150):
                    try: urllib.request.urlopen(url, timeout=.25).close(); break
                    except Exception: time.sleep(.1)
                from fossick.cdp import cdp_app
                cdp_app(url, port=cdp_port)
            threading.Thread(target=open_window, daemon=True, name='leela-cdp-open').start()
    if not gate.enabled: print(f'  {gate.why}')
    from .hub import LoopbackHostGuard
    uvicorn.run(LoopbackHostGuard(app), host=host, port=port, log_level='warning')
