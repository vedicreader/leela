"The web IDE."

from __future__ import annotations
import ast, asyncio, ipaddress, json, os, re, sys, warnings
from itertools import accumulate, count
from fasthtml.common import *
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import WebSocketRoute

from .blocks import BLOCKS
from .core.inspectors import PROFILES, SORTS
from . import errstr
from .blocks.term.app import term_cwd
from .core.ui import bar as btn_bar
from .blocks.agent.models import JOB_HELP

def help_mark(job):
    "The `?` beside a model control, saying what that job spends its model on."
    return Span('?', cls='lee-hint', tabindex='0', role='note',
                title=JOB_HELP.get(job, ''), aria_label=JOB_HELP.get(job, ''))
from .core import DebugState, DocStore, RunState, connect_all
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
from .core.web import Assets, IDE_BUNDLES, static_dirs
from .core.text import did_you_mean
from .core.text import md_block_diff, md_blocks, md_change_kinds
from .core.keys import by_scope, chord_display, toast_rows
from .blocks.debug.debug import notebook_state_ui, paused_kernel
from .blocks.nb.nb import Notebook
from .blocks.term.term import TerminalGate, gh_auth_argv, lazygit_argv, path_prelude, shell_argv
from .workspace import STEP_RANGE, TOOL_RANGE, Workspace

__all__ = ['ide_app', 'serve_ide']

def _patch_fasttransport():
    "Keep the response context as the sole owner of an SSE iterator's cleanup."
    import fasttransport.core as ft
    if getattr(ft.AsyncTransport.stream, '_leela_patched', False): return
    from inspect import isasyncgen
    import httpcore2._utils as core_utils
    import httpcore2._async.connection_pool as connection_pool
    import httpcore2._async.http11 as http11
    import httpcore2._async.http2 as http2
    class safe_async_iterate:
        """`httpcore2`'s helper as a class, because a generator-based one cannot always stop.

        An `@asynccontextmanager` misses its `GeneratorExit` under the loop's asyncgen shutdown.
        `__aexit__` is told which case it is, because `sys.exc_info()` is not reliably ours during
        that finalisation. Closing must not await, because the response context owns the iterator.
        """
        def __init__(self, source):
            self.it = source if hasattr(source, '__anext__') else source.__aiter__()
        async def __aenter__(self): return self.it
        async def __aexit__(self, typ, exc, tb):
            if isasyncgen(self.it) and typ is not GeneratorExit: await self.it.aclose()
            return False
    core_utils.safe_async_iterate = safe_async_iterate
    connection_pool.safe_async_iterate = safe_async_iterate
    http11.safe_async_iterate = safe_async_iterate
    http2.safe_async_iterate = safe_async_iterate
    async def stream(self, method, url, *, headers=None, params=None, json=None, data=None, files=None):
        async with self._client() as client:
            async with client.sse(url, method=method, headers=self._request_headers(headers, files=files),
                                  params=params, json=json, data=data, files=files, max_event_size=None) as source:
                resp = source.response
                try: resp.raise_for_status()
                except ft.httpx2.HTTPStatusError as e:
                    try: await resp.aread()
                    except Exception: pass
                    e.args = (f'{e}\n{resp.text}',)
                    raise
                if 'content-type' not in resp.headers: resp.headers['content-type'] = 'text/event-stream'
                async for event in source:
                    if not event.data: continue
                    if event.data == '[DONE]': return
                    try: raw = ft.jsonlib.loads(event.data)
                    except ft.jsonlib.JSONDecodeError as e: raise ft.ProtocolError(f'Invalid SSE JSON: {e}') from e
                    if isinstance(raw, dict): yield raw
                    else: raise ft.ProtocolError(f'Expected SSE JSON object, got {type(raw).__name__}')
    stream._leela_patched = True
    ft.AsyncTransport.stream = stream

_patch_fasttransport()


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
        # Filled in by the poll that already reads /dev/list; server-rendered only so the header
        # does not reflow when the first one arrives.
        Button('○ runs', id='runspill', cls='lee-pill lee-pill-off',
               title='scripts running under leela', onclick='leeRunsMenu(this)'),
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
            Button('\u2922', cls='lee-pane-min', type='button', data_pane_expand='left',
                   data_pane_expand_icon='1', title='expand the left pane',
                   aria_label='expand the left pane', aria_pressed='false',
                   onclick='leeExpandPane("left")'),
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
            Button('Open the vault', cls='lee-btn', onclick='leeVaultWorkbench()'),
            Button('Research a topic', cls='lee-btn', onclick='leeAct("research")'),
            Button('Ask the agent', cls='lee-btn', onclick='leeAct("focus_agent")'),
            cls='lee-empty-actions'),
        # Filled by the client from `/fs/recent`: live, because a packaged shell is built once.
        Div(id='leerecent', cls='lee-empty-recent', hidden=True),
        # And from `/agent/setup`, which answers with nothing outside a packaged app: a virtualenv
        # install chose its own dependencies already.
        Div(id='leesetup', cls='lee-empty-setup', hidden=True),
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
            Button('expand', id='termexpand', cls='lee-icon', data_pane_expand='bottom',
                   title='expand the bottom pane', aria_pressed='false', onclick='leeTermExpand()'),
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
            Div(Button(Span('conversations', cls='lee-thread-toggle-label'),
                       Span('1', id='agentthreadcount', cls='lee-thread-count'),
                       id='agentthreads', cls='lee-btn lee-thread-toggle', aria_expanded='false',
                       aria_controls='agentthreadlist', title='every live conversation',
                       onclick='leeAgentThreadsToggle()'),
                Button('+', id='agentnew', cls='lee-btn', title='new conversation', aria_label='new conversation',
                       onclick='leeAgentNew()'),
                Button('history', id='agenthistory', cls='lee-btn', title='toggle conversation history',
                       onclick='leeAgentHistory()'),
                Button('memory', id='agentmemory', cls='lee-btn', title='choose notes for agent, prompt cells, and completion',
                       onclick='leeMemoryNotes()'),
                Button('state', id='agentstate', cls='lee-btn', title='review or refresh the active agent state',
                       onclick='leeAgentState()'),
                Button('expand', id='agentexpand', cls='lee-btn', data_pane_expand='right',
                       title='expand the right pane', aria_pressed='false',
                       onclick='leeAgentExpand()'), cls='lee-agent-head-actions'),
            cls='lee-phead lee-agent-head'),
        Div(welcome, id='agentlog', cls='lee-agentlog'),
        Div(Span(cls='lee-agent-run-state'),
            Button('Pause after current', cls='lee-btn', type='button', data_agent_pause='1'),
            Button('Stop', cls='lee-btn warn', type='button', data_agent_stop='1'),
            cls='lee-agent-runstrip', id='agentrunstrip', hidden=True, aria_live='polite'),
        Div(Strong('Cursor agent mode.'),
            ' Cursor runs a tool only in agent mode, and its own shell and file edits come with that. '
            'They act in this workspace without passing through Leela\u2019s approvals, held only by '
            'Cursor\u2019s sandbox. Another runtime if you want every write gated.',
            id='agentharnessbanner', cls='lee-agent-harness-banner', hidden=True, role='status'),
        Div(id='agentthreadlist', cls='lee-thread-list', role='listbox',
            aria_label='live conversations', hidden=True),
        Div(id='agentattention', cls='lee-agent-attention', role='status', aria_live='polite', hidden=True),
        Div(Div(id='agentattachments', cls='lee-agent-attachments', aria_live='polite'),
            Div(Button('attach image', id='agentattach', cls='lee-btn', type='button', title='attach a workspace image path or paste a screenshot', onclick='leeAgentAttach()'), cls='lee-agent-attachbar'),
            Textarea(id='agentprompt', cls='lee-input lee-prompt', rows='2',
                     placeholder=f'ask, / for commands, @ for files…  ({chord_display("agent_send")})',
                     autocomplete='off', aria_autocomplete='list', aria_controls='agentsuggest'),
            Div(id='agentsuggest', cls='lee-agent-suggest', role='listbox', hidden=True),
            Div(Div(Select(Option('loading…', value=agent_model), id='agentmodel',
                           cls='lee-select lee-composer-model', onchange='leeAgentModel("agent", this.value)',
                           aria_label='conversation model', title=JOB_HELP['turn']),
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
                    Div(Label(Span('prompt cells', help_mark('inline'), cls='lee-routing-name'),
                              Select(Option('loading…', value=inline_model), id='inlinemodel',
                              cls='lee-select', onchange='leeAgentModel("inline", this.value)')),
                        Label(Span('completion', help_mark('completion'), cls='lee-routing-name'),
                              Select(Option('loading…', value=completion_model), id='completionmodel',
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
                        Label(Input(type='checkbox', id='kernels-auto-manage', checked=ws.kernels_auto_manage,
                                    onchange='setKernelAutoManage(this.checked)'),
                              ' leela manages the runtime limit', cls='lee-check-setting',
                              title='At the kernel limit, close the longest-idle runtime instead of asking'),
                        Label(Input(type='checkbox', id='workspace-repo-writes', checked=ws.allow_workspace_repo_writes,
                                    onchange='leeWorkspaceRepoWrites(this.checked)'), ' allow writes to other workspace repos',
                              cls='lee-check-setting', title='Keep approval prompts, but allow approved writes to any repository added to this workspace'),
                        Label(Input(type='checkbox', id='subagent-writes', checked=ws.subagent_writes,
                                    onchange='leeSubagentWrites(this.checked)'), ' sub-agents may write',
                              cls='lee-check-setting',
                              title='Delegated sub-agents get the write tools as well as the read ones. Edits, commands and Python, each recorded and put through the same approval prompts. Off, they can only report what they found'),
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
                Button('Send', id='agentsend', cls='lee-btn go lee-composer-send',
                       onclick='sendAgent(event.shiftKey)', aria_label='Send',
                       title='send this as a turn'),
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

def _warm_probes():
    """Pay for the model probes while the window is still opening.

    `available_models` reaches for every backend and `auth_status` asks every account: together
    they were most of a seven-second first paint of the model picker. On a thread, so a slow or
    absent network delays nothing.
    """
    import threading
    from .blocks.agent.models import warm_probes
    threading.Thread(target=warm_probes, daemon=True, name='leela-warm-probes').start()

def ide_app(ws: Workspace, gate: TerminalGate = None, workspace_catalog=None):
    "Build the FastHTML IDE around an open workspace. `gate` decides who may open a terminal."
    gate = gate or TerminalGate()
    _runstate = RunState()
    running_cells = _runstate.cells
    # The mark is line work with no plate, so the tab strip's own colour shows through it and
    # which ink reads depends on the browser's scheme, not on Leela's theme.
    hdrs = (Link(rel='icon', href=_asset('favicon.svg'), type='image/svg+xml',
                 media='(prefers-color-scheme: light)'),
            Link(rel='icon', href=_asset('favicon-dark.svg'), type='image/svg+xml',
                 media='(prefers-color-scheme: dark)'),
            Script(src=_asset('htmx.min.js'), defer=True),
            Script("""try { const legacy = {system: 'leela:system:relaxed', dark: 'leela:dark:relaxed', light: 'leela:light:relaxed', cursor: 'cursor:light:tight'};
const stored = localStorage.getItem('lee-theme') || 'cursor:light:tight';
const [family, mode, density] = (stored.includes(':') ? stored : legacy[stored] || 'cursor:light:tight').split(':');
const resolved = mode === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : mode;
document.documentElement.dataset.theme = family;
document.documentElement.dataset.mode = resolved;
document.documentElement.dataset.density = density || (family === 'cursor' ? 'tight' : 'relaxed');
document.documentElement.style.colorScheme = resolved; } catch (_) {}"""),
            Script(src=_asset('lee-cm6.js'), defer=True),
            Link(rel='stylesheet', href=_asset('lee-term.css')),
            Link(rel='stylesheet', href=_asset('lee-ide.css')),
            *[Script(src=_asset(b), defer=True) for b in IDE_BUNDLES])
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
    # `fast_app` imports `fasthtml.pico` whatever `pico=` says: 212ms and IPython, for a
    # stylesheet link this app never uses.
    # Starlette's exclusion list spares `text/event-stream`. The streams stay unbuffered.
    app = FastHTML(default_hdrs=False, hdrs=hdrs,
                   middleware=(Middleware(GZipMiddleware, minimum_size=512),),
                   on_startup=[ws.opened, _warm_probes], on_shutdown=[ws.shutdown],
                   routes=(Mount('/leestatic', Assets(*static_dirs())),
                           WebSocketRoute('/term/ws', term_ws)))
    app.static_route_exts()
    rt = app.route
    _docstore = DocStore(ws)
    _docs: dict[str, Notebook] = _docstore.docs
    _buffers: dict[str, str] = _docstore.buffers
    _buffer_bases: dict[str, str] = _docstore.bases
    _doc_versions: dict[str, str] = _docstore.versions
    _run_locks: dict[str, asyncio.Lock] = _docstore.run_locks
    _debugstate = DebugState()
    def _doc():
        t = ws.tab
        return None if t is None else _docs.get(t.path or t.title)
    def _dbg(method=None): return paused_kernel(_debugstate, method)
    def _open_path(path):
        "The workspace file a debug frame refers to, or '' when it is outside the sandbox."
        try: return str(ws.fs._check(path, must_exist=True))
        except Exception: return ''
    def _frame_path(frame): return (frame.get('source') or {}).get('path') or ''
    def _debug_ui(state): return notebook_state_ui(_debugstate, ws.fs, state)
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
                _doc_versions[key] = _disk_version(t.path)
                saved += 1
            except Exception as e: errors.append(f'{t.title}: {errstr(e)}')
        ws.save()
        if errors: return _fail('; '.join(errors))
        return {'ok': True, 'saved': saved}
    def _on_disk(path):
        "What the file says now, or None when it is not there."
        try: return Path(path).read_text(encoding='utf-8', errors='replace')
        except OSError: return None
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
        k = _debugstate.kernel or await _k()
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
        "Run an arbitrary block, as the `run selection` button sends, in the tab's kernel."
        d = await req.json()
        code = (d.get('code') or '').strip()
        if not code: return _fail('nothing to run')
        k = await _k()
        res = await k.execute(code)
        return {'ok': res.ok, 'outputs': res.outputs,
                'text': await _explain(k, res.error) or res.text or 'ok'}
    @rt('/exec/history')
    async def exec_history(n: int = 200):
        "The rolling history notebook, oldest first, as ctrl+up/down cycles through it."
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
        k = _debugstate.kernel or await _k()
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


    ws.start_backups()

    connect_all(app, ws, BLOCKS, docs=_docstore, debug=_debugstate, running=_runstate, gate=gate,
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
    from .hub import WorkspaceHub, WorkspaceSite, assign_slugs
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
    from .blocks.runtime.kernels import RuntimeBroker
    broker = RuntimeBroker()   # every shape gets the ceiling
    from .core.projects import now_serving, served
    hub = None
    pool_ports = count(kernel_port, 100)
    def site_for_root(root, slug):
        "One independent workspace: its own state file, its own kernel pool, its own window."
        state = leela_cfg/'workspaces'/f'{slug}.json'
        kw = dict(port=next(pool_ports), agent=agent, kernel=kernel, model=model,
                  approvals=approvals, agent_scope=agent_scope, python=python,
                  transport=transport, gateway=gateway, cdp_port=cdp_port)
        ws = (Workspace.load(path=state, **kw) if open_ws else Workspace(**kw)).at_exit()
        state.parent.mkdir(parents=True, exist_ok=True)
        ws._state_path = state
        broker.register(ws.pool)
        if ws.kernels_auto_manage: broker.auto_manage = True
        if root not in ws.fs.roots: ws.add_root(root)
        if ws.restore_remembered_agent_state(): ws.save()
        ws.jobs.tick()
        # Only for a folder opened at runtime: at launch the whole set is written below.
        if hub is not None:
            now_serving(host, port, [s.root for s in hub.sites.values()] + [str(root)])
        return WorkspaceSite(slug, root.name, str(root),
                             ide_app(ws, gate, workspace_catalog=lambda: hub.catalog()))
    if app_window and roots:
        sites = [site_for_root(r, s) for r, s in zip(roots, assign_slugs(roots))]
        app = hub = WorkspaceHub(sites, port, build=site_for_root)
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
        kw = dict(port=next(pool_ports), agent=agent, kernel=kernel, model=model,
                  approvals=approvals, agent_scope=agent_scope, python=python,
                  transport=transport, gateway=gateway, cdp_port=cdp_port)
        if open_ws and not roots:
            ws = Workspace.load(**kw)
        else:
            try: remembered = (leela_cfg/'workspace.json').read_json() if open_ws else {}
            except Exception: remembered = {}
            if model is None: kw['model'] = remembered.get('model')
            kw['inline_model'] = remembered.get('inline_model') or 'gpt-mini'
            kw['completion_model'] = remembered.get('completion_model') or 'gpt-4.1'
            ws = Workspace(**kw).restore_settings(remembered)
        ws.at_exit()
        broker.register(ws.pool)
        # one ceiling for the process, so any workspace asking leela to manage it turns it on
        if ws.kernels_auto_manage: broker.auto_manage = True
        for r in roots: ws.add_root(r)
        # A shell launch means "here". A frozen one has no such answer.
        if not ws.fs.roots and not getattr(sys, 'frozen', False): ws.add_root(os.getcwd())
        if open_ws and not ws.tabs: ws.reopen_saved_tabs()
        if ws.restore_remembered_agent_state(): ws.save()
        app = ide_app(ws, gate, workspace_catalog=lambda: hub.catalog() if hub else [])
        if app_window:
            # A launch with no folder still gets a hub, because the welcome screen is exactly
            # where a folder is opened from, and a folder opens as a workspace the hub serves.
            r0 = first(ws.fs.roots)
            app = hub = WorkspaceHub(
                [WorkspaceSite(assign_slugs([r0])[0] if r0 else 'leela',
                               r0.name if r0 else 'leela', str(r0 or ''), app)],
                port, build=site_for_root)
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
    now_serving(host, port, [str(r) for r in (roots or ws.fs.roots)])
    try: uvicorn.run(LoopbackHostGuard(app), host=host, port=port, log_level='warning')
    finally: served()
