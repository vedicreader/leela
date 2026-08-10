"""The web IDE.

The server owns state and structure; the browser owns the editors. Anything
with a text cursor is CodeMirror talking JSON to these routes, and everything
else -- file tree, variable tree, tab bar, status -- is server-rendered htmx,
reusing the fragments leela already knows how to build.

Variable data is *proxied* rather than fetched cross-origin. Each kernel hosts
its own inspector on its own port; letting the page hit those ports directly
would mean CORS on every kernel and the owner token sitting in the browser.
Proxying keeps the token server-side and the page single-origin.

The exec strip's two scopes are genuinely different runtimes, not a flag:
`live` runs on the tab's kernel, sharing the notebook's namespace, while
`isolated` runs through the agent session's safepyrun sandbox, where writes are
discarded and escapes refused. (The older `scope='isolated'` copies the
namespace dict shallowly, so a mutating call still reached the real object --
routing the toggle at the sandbox makes the label true.)
"""

from __future__ import annotations
import ast, asyncio, ipaddress, json, os, re, shutil, subprocess, sys, warnings
from urllib.parse import quote
from fasthtml.common import *          # re-exports fastcore's Path, L, first, asdict, ...
from starlette.routing import WebSocketRoute

from dhrishti.core import PROFILES, SORTS
from .. import errstr
from ..blocks import editor as editor_block
from ..blocks import fs as fs_block
from ..blocks import git as git_block
from ..blocks import keys as keys_block
from ..blocks import lsp as lsp_block
from ..blocks import memory as memory_block
from ..blocks import releases as releases_block
from ..blocks import research as research_block
from ..blocks import runs as runs_block
from ..blocks import runtime as runtime_block
from ..blocks import search as search_block
from ..blocks import settings as settings_block
from ..blocks import term as term_block
from ..blocks import tabs as tabs_block
from ..blocks import vars as vars_block
from ..blocks import workflows as workflows_block
from ..blocks import workspace as workspace_block
from ..blocks.term.app import term_cwd
from ..buttons import bar as btn_bar
from ..core import DocStore, RunState, connect_all
from ..blocks.fs.ui import files_panel as _files_panel
from ..blocks.tabs.app import disk_version as _disk_version
from ..blocks.tabs.ui import kernel_pill as _kernel_pill
from ..blocks.tabs.ui import tab_bar as _tab_bar
from ..core.ui import action_bar as _action_bar
from ..core.ui import activity_icon as _activity_icon
from ..core.ui import btn as _btn
from ..core.ui import menu_button as _menu_button
from ..core.web import asset as _asset
from ..core.web import diff_payload as _diff
from ..core.web import fail as _fail
from ..core.web import off_loop as _off_loop
from ..core.web import sse as _sse
from ..core.web import static_dir
from ..diffs import did_you_mean, fuzzy_rank
from ..fs import lang_for
from ..git import GitRepo, GitError
from ..keys import by_scope, chord_display, toast_rows
from ..nb import Notebook, Cell
from ..term import TerminalGate, lazygit_argv
from ..workspace import Workspace
from ..agent.core import model_note

__all__ = ['ide_app', 'serve_ide']


# Connect your blocks. Order is registration order and the first route to match a path
# wins, so a block claiming a broad path belongs after the specific ones. The URL surface
# this produces is pinned by `tests/routes.txt`.
#
# Everything not listed here is still a closure inside `ide_app`; see `docs/blocks.md` for
# the extraction order and what remains.
BLOCKS = [keys_block, settings_block, search_block, memory_block,
          research_block, term_block, runs_block, workspace_block, git_block,
          workflows_block, releases_block,
          fs_block, lsp_block, vars_block, runtime_block, tabs_block, editor_block]


def _found(ws, hits):
    "A hit list plus the backend that produced it -- an empty result is never a mystery."
    return {'backend': ws.search.backend, 'note': ws.search.note, 'hits': [h.dict() for h in hits]}


def _python_diagnostics(source, filename='<cell>'):
    """Compile without executing and return Python's own errors and warnings as editor ranges."""
    source = str(source or '')
    lines = source.splitlines(keepends=True) or ['']
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)

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
            # Producing a code object performs the complete compiler warning pass, unlike
            # PyCF_ONLY_AST, but does not execute any user code.
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
    roots = [str(root) for root in ws.fs.roots]
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
    return ('## Open roots\n' + ('\n'.join(f'- {root}' for root in roots) or '- none') +
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
        from ..agent.tools import _cmds
        from exhash import exhash
        path = args.get('path', '')
        before = agent.host.text_at(path)
        if before is None: raise ValueError(f'no such file: {path}')
        result = exhash(before, _cmds(args.get('commands', '[]')))
        return {'kind': 'patch', 'text': str(result)}
    if tool == 'replace_text':
        # Previewed as the diff it would make, computed against the file on disk without
        # writing it -- the same guarantee `edit_file` above gives.
        from ..agent.tools import _apply_edits, _edits
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


def _tool_schemas(agent):
    "Browser-sized schemas for editable checkpoint forms; callable validation remains authoritative."
    import inspect
    from ..ai import WRITE_TOOLS
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
                    'group': ('Repository' if tool.__name__ in {'search_code', 'similar_code', 'outline', 'list_files',
                                                               'grep', 'ls', 'view_file', 'edit_file',
                                                               'replace_text', 'create_file'}
                              else 'Runtime' if tool.__name__ in {'run_python', 'inspect_python', 'list_vars',
                                                                  'read_terminal', 'run_shell'}
                              else 'Web' if tool.__name__ in {'web_search', 'read_url', 'research'}
                              else 'Notebook' if 'cell' in tool.__name__ or 'notebook' in tool.__name__
                              else 'Other'), 'fields': fields})
    return out


def _assigned_lines(source):
    """Top-level bindings made by Python source, as ``[(line, name)]``.

    This is deliberately syntax-aware rather than a regex: tuple unpacking, annotations,
    imports and assignments inside a top-level control block all count, while locals inside
    a function do not leak into the notebook namespace. The browser uses the line number to
    put the kernel's real value beside the statement that created it.
    """
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
    # Jupyter's useful last-expression result belongs beside that expression too. Keep the
    # marker tiny (the root name, e.g. ``df`` for ``df.dtypes``); clicking reveals the repr.
    output_result = next((o for o in reversed(outputs or ()) if o.get('output_type') == 'execute_result'), None)
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


def _history_sessions(turns, execution=()):
    """Turns grouped by durable model-context id; old untagged history splits after 30m."""
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
    """A kernel error with a `did you mean` appended, when a near-miss name exists.

    Guarded on the message rather than run for every failure: the suggestion costs an
    extra call to the kernel's inspector, and only a `NameError` can use one.
    """
    if not (err and 'is not defined' in err): return err
    return did_you_mean(err, await k.names(scope)) if k else err


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------
def _header(ws):
    """Project identity first, document tabs second, infrequent actions in menus.

    A branch is project context rather than a toolbar command, so it stays beside the
    workspace switcher. The former wall of run/editor controls now has named doors; the
    command palette remains the exhaustive surface.
    """
    root = ws.fs.roots[0] if ws.fs.roots else None
    return Header(
        Button(Span('leela', cls='lee-brand'), Span(Path(root).name if root else 'open workspace',
               id='workspacename', cls='lee-workspace-name'), cls='lee-workspace-switcher',
               id='workspacepill', title='switch or open workspace', onclick='leeWorkspaceMenu(this)'),
        Button('no git', id='gitpill', cls='lee-branch-switcher', title='switch branch',
               onclick='leeBranchMenu(this)'),
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
    """GitHub Actions for this project, read locally and reached through gheasy.

    The panel is deliberately useful before it is connected: the workflow files are on disk,
    so the graph draws with no token, no network and no `gheasy` installed, and the run
    history is the part that asks for those.
    """
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
                   onclick='leeLeft("releases")'), cls='lee-activity', aria_label='Project tools'),
        Div(_files_panel(ws.fs), _symbols_panel(), _git_panel(), _workflows_panel(),
            _releases_panel(), _toast_panel(), cls='lee-left-content'),
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
    """Only the actions used continuously; everything else lives in a named menu."""
    actions = {'run_cell', 'run_advance', 'run_file', 'run_selection', 'interrupt'}
    buttons = [_btn(b) for b in btn_bar('toolbar') if b.action in actions]
    return Div(*buttons, Span(cls='lee-spacer'),
               Button('⋯', cls='lee-more lee-toolbar-more', title='more editor actions',
                      aria_label='more editor actions', onclick='leeEditorMenu(this)'),
               cls='lee-toolbar', id='toolbar')


def _vars_panel(ws):
    """The right sidebar: owner or agent-session namespace, then filtering.

    The toggle governs both exec and this tree. Agent is the protected persistent layer
    used by run_python, so derived variables can be inspected and continued interactively.
    """
    return Section(
        Div(Span('variables', cls='lee-ptitle'),
            Div(Button('live', id='sc-live', cls='lee-seg active', onclick='leeScope("live")'),
                Button('agent', id='sc-agent', cls='lee-seg', onclick='leeScope("agent")'),
                cls='lee-segbar', title='live is your kernel · agent is its protected persistent layer'),
            # Named only when it is *not* the tab's kernel: a panel showing a running app
            # must never be mistaken for the notebook's own namespace.
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


def _editor_pane(ws):
    "The primary editor plus an optional second file editor mounted entirely by the client."
    t=ws.tab
    if t is None:
        primary=Div(Section(Span('L',cls='lee-empty-mark'),Strong('Start with a file'),
                    P('Open a file from this workspace, or create a notebook for exploratory work.'),
                    Div(Button('Open file',cls='lee-btn go',onclick='leeAct("quick_open")'),
                        Button('New notebook',cls='lee-btn',onclick='leeAct("new_notebook")'),
                        Button('Research a topic',cls='lee-btn',onclick='leeAct("research")'),cls='lee-empty-actions'),
                    Small('Press ',Kbd('ctrl+p'),' to open files without leaving the keyboard.'),cls='lee-empty'),
                    id='editor',cls='lee-editor',tabindex='-1')
    else: primary=Div(id='editor',cls='lee-editor',data_kind=t.kind,data_path=t.path,data_lang=t.lang or '',tabindex='-1')
    return Div(primary,Div(cls='lee-editor-splitter'),Div(id='editor2',cls='lee-editor lee-editor-secondary',hidden=True),
               cls='lee-editor-stage',id='editorstage')


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
    """The terminal drawer: hidden until `ctrl+alt+~` asks for it.

    Rendered even when terminals are disabled, so the reason shows up in the place the
    user looked for the feature rather than as silence.
    """
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
            Button('lazygit', cls='lee-icon', title='open lazygit tab', onclick='leeAct("git")'),
            Button('×', cls='lee-icon', title='close active terminal', onclick='leeAct("term_close")'),
            cls='lee-phead'),
        body,
        cls='lee-panel lee-termpanel', id='termwrap', data_term_src=_asset('lee-term.js'))


def _bottom_dock(ws, gate):
    "One bounded lower workspace: Exec and Terminal switch in place instead of stacking."
    return Section(
        Div(Button('exec', cls='lee-docktab active', data_dock='exec', onclick='leeDock("exec")'),
            Button('terminal', cls='lee-docktab', data_dock='term', onclick='leeDock("term")'),
            Span(cls='lee-spacer'),
            Button('−', cls='lee-pane-min', title='minimise bottom tools', aria_label='minimise bottom tools',
                   onclick='leePane("bottom", false)'),
            cls='lee-docktabs', role='tablist', aria_label='bottom tools'),
        Div(_exec_strip(), _term_panel(gate), cls='lee-dockbody'),
        cls='lee-bottomdock dock-exec', id='bottomdock')


def _memory_panel():
    return Section(
        Div(Span('memory', cls='lee-ptitle'), Span(id='memorystatus', cls='lee-keyscope'),
            Span(cls='lee-spacer'), Button('+', cls='lee-btn go lee-memory-add', title='new agent memory note',
                                            aria_label='new memory note', onclick='leeNewMemoryNote()'), cls='lee-phead'),
        Nav(Button('notes', cls='active', data_memory_view='notes', onclick='leeMemoryNotes()'),
            Button('sources', data_memory_view='sources', onclick='leeMemoryHome()'),
            Button('topics', data_memory_view='topics', onclick='leeMemoryTopics()'),
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
            Button('−', cls='lee-pane-min', title='minimise right tools',
                   aria_label='minimise right tools', onclick='leePane("right", false)'),
            cls='lee-righttabs', role='tablist', aria_label='right tools'),
        Div(_agent_panel(ws), _vars_panel(ws), _memory_panel(), cls='lee-rightbody'),
        cls='lee-right right-agent', id='right')


def _agent_panel(ws):
    "Bottom centre; model choices load asynchronously after the editor can paint."
    from ..agent.core import DFLT_LOCAL, env as _env

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
                Span('state active' if has_state else 'no state', id='agentnames', cls='lee-agent-state-badge'),
                cls='lee-agent-heading'),
            Span(cls='lee-spacer'),
            Div(Button('history', id='agenthistory', cls='lee-btn', title='toggle conversation history',
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
                           title='reasoning effort for cloud models'), cls='lee-composer-primary'),
                Details(Summary('settings'),
                    Div(Label('prompt cells', Select(Option('loading…', value=inline_model), id='inlinemodel',
                              cls='lee-select', onchange='leeAgentModel("inline", this.value)')),
                        Label('completion', Select(Option('loading…', value=completion_model), id='completionmodel',
                              cls='lee-select', onchange='leeAgentModel("completion", this.value)')),
                        Label(Input(type='checkbox', id='autocompact', checked=ws.compact_auto,
                                    onchange='leeAgentCompaction()'), ' compact automatically',
                              cls='lee-check-setting', title='rewrite old context before it reaches the model limit'),
                        Label('compaction', Select(Option('surgical · readable tool trail', value='surgical', selected=ws.compact_strategy == 'surgical'),
                                                   Option('summary · model checkpoint', value='summary', selected=ws.compact_strategy == 'summary'),
                                                   id='compactstrategy', cls='lee-select', onchange='leeAgentCompaction()')),
                        Label(Input(type='checkbox', id='localmultimodal', checked=ws.local_multimodal,
                                    onchange='leeLocalMultimodal(this.checked)'),
                              ' local image/audio encoders', cls='lee-check-setting',
                              title='Reload local LiteRT engines with vision and audio support'),
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
    ks = [k for k in (list(by_scope('global')) + list(by_scope('editor'))) if k.show == 'footer']
    kids = [Span(Kbd(k.keys[0]), Span(k.label), cls='lee-fkey') for k in ks]
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


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
def ide_app(ws: Workspace, gate: TerminalGate = None, workspace_catalog=None):
    # Registering makes asking possible: with nobody listening `Approvals` refuses every
    # gated write immediately rather than parking the model's thread on an answer that is
    # never coming. The browser counts as a listener for as long as the app is served.
    ws.approvals.listen()
    "Build the FastHTML IDE around an open workspace. `gate` decides who may open a terminal."
    gate = gate or TerminalGate()
    # (tab identity, cell id) -> (runtime, execution task). This keeps Stop aimed at the
    # cell that started the work even if the person switches tabs before pressing it.
    # `RunState` owns it so blocks can share it; `running_cells` is the same dict under its
    # old name, so the routes still in this function are untouched until they move.
    _runstate = RunState()
    running_cells = _runstate.cells
    # Everything is served from disk. FastHTML's default headers pull htmx and friends
    # from a CDN, which would make a local IDE need the network to start -- and fail
    # outright behind a proxy or on a plane. `default_hdrs=False` plus the vendored
    # bundles keeps it self-contained, the same reason CodeMirror is vendored.
    hdrs = (Link(rel='icon', href=_asset('favicon.svg'), type='image/svg+xml'),
            Script(src=_asset('htmx.min.js')),
            Script("""try { const t = localStorage.getItem('lee-theme') || 'system';
if (t !== 'system') document.documentElement.dataset.theme = t;
document.documentElement.style.colorScheme = t === 'system' ? 'light dark' : t; } catch (_) {}"""),
            Script(src=_asset('lee-cm6.js')),
            Link(rel='stylesheet', href=_asset('lee-term.css')),
            Link(rel='stylesheet', href=_asset('lee-ide.css')),
            Script(src=_asset('lee-ide.js'), defer=True))

    # The pty websocket is registered when the app is built, before any block connects, so
    # it cannot reach the term block's Ctx. It shares the block's definition instead.
    def _term_cwd(ref=None): return term_cwd(ws, ref)

    async def term_ws(sock):
        """One websocket, one pty. Binary frames are keystrokes; text frames are control.

        The split is what keeps the protocol free of escaping: a pty's traffic is
        arbitrary bytes, so anything that needs *structure* (the opening handshake, a
        resize) travels as text and everything else is passed through untouched.
        """
        await sock.accept()
        t = key = None
        try:
            hello = json.loads((await sock.receive()).get('text') or '{}')
            gate.check(hello.get('token'))          # raises unless this connection may have a pty
            kind = hello.get('kind', 'shell')
            cwd = _term_cwd(hello.get('cwd'))
            argv = lazygit_argv(cwd) if kind == 'git' else None
            key = hello.get('id') or kind
            env = None
            if kind != 'git' and (py := ws.pool.default_python):
                # Start the shell *inside* the project's uv/venv rather than asking the
                # user to activate it in every terminal tab. VIRTUAL_ENV is what uv reads;
                # UV_PROJECT_ENVIRONMENT also keeps `uv run/sync` pointed at this exact env.
                bindir = str(Path(py).parent)
                venv = str(Path(bindir).parent)
                env = os.environ.copy()
                env['VIRTUAL_ENV'] = venv
                env['UV_PROJECT_ENVIRONMENT'] = venv
                env['PATH'] = bindir + os.pathsep + env.get('PATH', '')
                env.pop('PYTHONHOME', None)
            t = ws.terms.open(key, argv=argv, cwd=cwd, env=env,
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
            if pump.done():                          # the child exited; say so before closing
                ws.terms.close(key)
                try: await sock.send_text(json.dumps({'t': 'exit', 'note': t.exit_note}))
                except Exception: pass
        finally:
            for task in (pump, recv):
                if not task.done(): task.cancel()
            try: await sock.close()
            except Exception: pass

    app, rt = fast_app(pico=False, default_hdrs=False, hdrs=hdrs,
                       routes=(Mount('/leestatic', StaticFiles(directory=str(static_dir()))),
                               WebSocketRoute('/term/ws', term_ws)))

    # Open notebooks, unsaved buffers and per-kernel run locks. `DocStore` owns them so the
    # extracted blocks can share them as a capability; the four names below are the same
    # objects under their old names, so the routes still in this function are untouched
    # until they move. See `leela/core/session.py`.
    _docstore = DocStore(ws)
    _docs: dict[str, Notebook] = _docstore.docs
    _buffers: dict[str, str] = _docstore.buffers
    _buffer_bases: dict[str, str] = _docstore.bases
    _run_locks: dict[str, asyncio.Lock] = _docstore.run_locks
    # A paused debugger belongs to the kernel that started it, not whichever tab becomes
    # active while stepping into another source file.
    _debug = {'kernel': None, 'origin_path': '', 'cell_id': ''}
    _direct_debug = {'session': None, 'task': None, 'name': ''}

    def _doc():
        t = ws.tab
        return None if t is None else _docs.get(t.path or t.title)

    def _debug_ui(state):
        "Map temporary cell sources back to the notebook and mark project files safe to open."
        state.update(origin_path=_debug.get('origin_path'), cell_id=_debug.get('cell_id'))
        temp = state.get('source')
        cell_sources = getattr(_debug.get('kernel'), '_debug_sources', {})
        for frame in state.get('frames', []):
            path = (frame.get('source') or {}).get('path') or ''
            cell_id = cell_sources.get(path)
            if path == temp or cell_id:
                frame['open_path'] = _debug.get('origin_path') or ''
                frame['cell_id'] = cell_id or _debug.get('cell_id') or ''
            else:
                try: frame['open_path'] = str(ws.fs._check(path, must_exist=True))
                except Exception: frame['open_path'] = ''
        return state

    def _direct_debug_ui(state):
        for frame in state.get('frames', []):
            path = (frame.get('source') or {}).get('path') or ''
            try: frame['open_path'] = str(ws.fs._check(path, must_exist=True))
            except Exception: frame['open_path'] = ''
        return state

    def _previous_runs():
        """A reset namespace makes every saved output historical, even though it remains useful."""
        _docstore.mark_all_stale()

    async def _k(tab=None):
        "The explicitly picked runtime, else the addressed tab's own project/notebook kernel."
        return await ws.runtime(tab)

    def _run_owner(d):
        "Resolve a notebook request to the tab that submitted it, even after a tab switch."
        ref = str(d.get('path') or '')
        tab = next((t for t in ws.tabs if (t.path or t.title) == ref), None) if ref else ws.tab
        if tab is None or tab.kind != 'notebook': return None, None, None
        nb = _docs.get(tab.path or tab.title)
        key = ws.kernel_key(tab)
        return tab, nb, _run_locks.setdefault(key, asyncio.Lock())

    async def _api(path, params=None, timeout=15):
        """Proxy inspection through the exact runtime used by Run.

        This intentionally resolves ``Workspace.runtime`` rather than independently
        peeking at an inspector. A selected venv may restart or replace the tab kernel;
        execution and Variables must cross the same runtime boundary on every request,
        not merely happen to agree while the old kernel is still cached.
        """
        client = await _k()
        return await client.api(path, params, timeout) if client else None

    # -- shell -------------------------------------------------------------
    @rt('/')
    def home():
        return Title('leela'), _shell(ws, gate)

    @rt('/markdown/render')
    async def markdown_render(req):
        """Paste-safe Markdown rendering through mdhtml's explicit dialect.

        Raw style/script tags become visible text; only an authored ``{=html}`` block is
        treated as deliberate passthrough by the dialect. References use id mode because
        an IDE fragment may point at a target in another cell.
        """
        d = await req.json()
        text = str(d.get('text') or '')
        if len(text) > 1_000_000: return _fail('markdown fragment is larger than 1 MB')
        # Explicit raw HTML is useful in a Markdown cell the person authored, but model,
        # kernel-output and fetched-web Markdown are untrusted. Turn their passthrough
        # fences into ordinary highlighted HTML code before mdhtml sees them.
        if not d.get('allow_raw', True):
            import re
            text = re.sub(r'(?m)^([ \t]*`{3,})\{=html\}([ \t]*)$', r'\1html\2', text)
        try:
            from mdhtml import to_mdhtml, to_html
            symbolic = to_mdhtml(text, math='on', implicit_figures=True,
                                 bare_autolinks=True, frontmatter=False)
            rendered = to_html(symbolic, refs='ids', auto_ids=False, hl='spans')
            warnings = list(getattr(symbolic, 'warnings', ())) + list(getattr(rendered, 'warnings', ()))
            return {'html': str(rendered), 'warnings': list(dict.fromkeys(map(str, warnings)))}
        except Exception as e: return _fail(e)

    # `keys` and `settings` are connected as blocks at the end of this function.

    # `runtime` is connected as a block; see BLOCKS.

    # `fs` is connected as a block; see BLOCKS. `/fs/add_root` stays here because it
    # re-renders the whole shell, which is the last thing left in this function.
    @rt('/fs/add_root')
    def add_root(path: str):
        try: ws.add_root(path); ws.save()
        except Exception as e: return _fail(str(e))
        return _shell(ws, gate)

    # -- tabs --------------------------------------------------------------
    # Tab routes swap only the tab bar, never the whole shell. Re-rendering everything
    # for a tab switch would collapse the file tree, drop the exec editor and reset the
    # variable panel -- the client re-mounts just the editor when #tabbar changes.
    # `tabs` and `editor` are connected as blocks; see BLOCKS.

    # -- notebooks ---------------------------------------------------------
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
        # Inline annotations are a bonus, never a reason for a completed cell to look
        # hung. A sick inspector gets two seconds; outputs return without the pills.
        rows = (await k.api('/api/rows', {'profile': 'full', 'sort': 'name'}, timeout=2)
                if k and not c.has_error else None)
        has_result = any(o.get('output_type') == 'execute_result' for o in c.outputs)
        latest = (await k.api('/api/result', timeout=2) if k and not c.has_error and has_result else None)
        result = (latest or {}).get('result')
        return {'ok': not c.has_error, 'i': i, 'cell': c.dict(), 'result': result,
                'inline': _inline_values(c.source, (rows or {}).get('groups', []), c.outputs, result)}

    @rt('/nb/run/stream')
    async def nb_run_stream(req):
        """Run a cell while streaming its evolving Jupyter outputs as SSE.

        Rishi's ``display_stream`` repeatedly updates one ``text/markdown`` display id.
        Sending the cell's reconciled output list on each callback lets the browser redraw
        that Markdown in place instead of looking frozen until inference ends.
        """
        d = await req.json()
        owner_tab, nb, run_lock = _run_owner(d)
        i = int(d.get('i', 0))
        if nb is None: return _fail('no notebook open')
        if not (0 <= i < len(nb)) or (d.get('id') and nb[i].id != d['id']):
            return _fail('that cell is no longer at this position', 409)
        nb[i].source = d.get('source', nb[i].source)
        # Code in this cell may immediately crawl the project and parse notebooks. Repair
        # zero-byte placeholders left by generic file creation before it can observe invalid
        # JSON on disk (PyCharm performs the equivalent initialization on save/run).
        await _off_loop(ws.initialize_empty_notebooks, ws.cwd_for(owner_tab))
        # Acquire before returning the StreamingResponse. If this lived inside `events`,
        # Starlette could schedule two new streams in reverse order after startup.
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
                    # Markdown display updates can arrive token-by-token. Keep the newest
                    # frame instead of making the browser render a backlog it can no longer see.
                    while not q.empty(): outputs = q.get_nowait()
                    yield _sse('output', {'i': i, 'outputs': outputs})
                c = await task
                if owner_tab: owner_tab.dirty = True
                rows = (await k.api('/api/rows', {'profile': 'full', 'sort': 'name'}, timeout=2)
                        if k and not c.has_error else None)
                has_result = any(o.get('output_type') == 'execute_result' for o in c.outputs)
                latest = (await k.api('/api/result', timeout=2) if k and not c.has_error and has_result else None)
                result = (latest or {}).get('result')
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
        """Debug one code cell through ipykernel's Jupyter Debug Protocol."""
        d = await req.json()
        owner_tab, nb, run_lock = _run_owner(d)
        i = int(d.get('i', 0))
        if nb is None or not (0 <= i < len(nb)):
            return _fail(f'no cell {i}')
        if d.get('id') and nb[i].id != d['id']:
            return _fail('that cell is no longer at this position', 409)
        if nb[i].cell_type != 'code': return _fail('only code cells can be debugged')
        nb[i].source = d.get('source', nb[i].source)
        # Debug configuration and execution share the same kernel channels as normal
        # cells. Reserve the runtime before startup so a definition cannot be overtaken
        # by its debugged use (or vice versa).
        await run_lock.acquire()
        try: k = await _k(owner_tab)
        except BaseException:
            run_lock.release()
            raise
        if getattr(k, 'kernel_kind', None) != 'ipykernel' or not hasattr(k, 'debug_start'):
            run_lock.release()
            return _fail('cell debugging currently requires a direct ipykernel runtime')
        # The debugger UI has one global frame/variable selection. Do not let a second
        # notebook replace that state while the first is paused, even on another kernel.
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
                        # Kernel owns the reconciled final output list; incremental debug
                        # output is intentionally only a repaint signal.
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
        k = _debug.get('kernel')
        if k is None or not hasattr(k, 'debug_state'): return _fail('no ipykernel debugger is active')
        try:
            state = await k.debug_state(frame_id=frame_id or None)
            return _debug_ui(state)
        except Exception as e: return _fail(e)

    @rt('/nb/debug/source')
    async def nb_debug_source(frame_id: int):
        "Source for a stack frame outside the workspace, addressed by trusted frame id—not a client path."
        k = _debug.get('kernel')
        if k is None: return _fail('no ipykernel debugger is active')
        try:
            state = await k.debug_state(frame_id=frame_id)
            frame = next((f for f in state.get('frames', []) if f.get('id') == frame_id), None)
            if frame is None: return _fail('debug frame is no longer available')
            source = frame.get('source') or {}
            reply = await k.debug_request('source', {'source': source,
                                                      'sourceReference': source.get('sourceReference', 0)})
            return {'content': reply.get('body', {}).get('content', ''), 'line': frame.get('line'),
                    'path': source.get('path', ''), 'name': frame.get('name', '')}
        except Exception as e: return _fail(e)

    @rt('/nb/debug/variables')
    async def nb_debug_variables(reference: int):
        k = _debug.get('kernel')
        if k is None or not hasattr(k, 'debug_variables'): return _fail('no ipykernel debugger is active')
        try: return {'variables': await k.debug_variables(reference)}
        except Exception as e: return _fail(e)

    @rt('/nb/debug/evaluate')
    async def nb_debug_evaluate(req):
        d, k = await req.json(), _debug.get('kernel')
        if k is None or not hasattr(k, 'debug_evaluate'): return _fail('no ipykernel debugger is active')
        try:
            body = await k.debug_evaluate(d.get('code', ''), d.get('frame_id'))
            return {'ok': True, **body}
        except Exception as e: return _fail(e)

    @rt('/nb/debug/control')
    async def nb_debug_control(req):
        d, k = await req.json(), _debug.get('kernel')
        if k is None or not hasattr(k, 'debug_control'): return _fail('no ipykernel debugger is active')
        try:
            await k.debug_control(d.get('command', ''), d.get('thread_id'))
            return {'ok': True, 'command': d.get('command')}
        except Exception as e: return _fail(e)

    @rt('/nb/debug/stop')
    async def nb_debug_stop():
        k = _debug.get('kernel')
        if k is None or not hasattr(k, 'debug_stop'): return _fail('no ipykernel debugger is active')
        try:
            await k.debug_stop()
            await k.interrupt()
            return {'ok': True}
        except Exception as e: return _fail(e)

    @rt('/nb/ask')
    async def nb_ask(req):
        """Run a prompt cell: the assistant answers, with the notebook above it as context.

        Off the loop like every other model call, and slow enough that it has to be --
        the file tree must keep responding while the answer is being written.
        """
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
                'cells': [x.dict() for x in nb.cells],   # approval/compaction cells may have landed
                'activity': a.activity.rows(mark=a.activity._mark),
                'edits': [{'path': p, **_diff(was, now)} for p, (was, now) in a.changes().items()]}

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

            def changed_activity():
                changed = []
                for row in a.activity.rows(mark=a.activity._mark):
                    version = (row.get('done'), row.get('ok'), row.get('line'), row.get('detail'), row.get('secs'))
                    if activity_versions.get(row['id']) != version:
                        activity_versions[row['id']] = version
                        changed.append(row)
                return changed

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
                                    'edits': [{'path': p, **_diff(was, now)}
                                              for p, (was, now) in a.changes().items()]})
            finally:
                nb[i].running = False
                if owner_tab is not None:
                    owner_tab.running = max(0, owner_tab.running - 1)
                    owner_tab.dirty = True

        from starlette.responses import StreamingResponse
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @rt('/nb/edit')
    async def nb_edit(req):
        "Structural edits: insert / delete / move / type / split / merge."
        d = await req.json()
        nb = _doc()
        if nb is None: return _fail('no notebook open')
        op, i = d.get('op'), int(d.get('i', 0))
        # Structural edits arrive with the current editor buffers in one request. Sending
        # one HTTP request per cell made changing a type appear broken on large notebooks.
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
        t=next((x for x in ws.tabs if x.path==path),None) if path else ws.tab
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

    @rt('/history/undo')
    async def operation_undo(req):
        try:
            d = await req.json(); op = ws.journal.undo(d.get('id', ''))
            for path in (r['path'] for r in op.get('resources', [])):
                _buffers.pop(path, None); _docs.pop(path, None)
                if (tab := next((t for t in ws.tabs if t.path == path), None)): tab.dirty = False
            return {'ok': True, 'operation': op}
        except Exception as e: return _fail(e, 409)

    @rt('/diff')
    async def diff_route(req):
        """What the editor holds, against what is on disk.

        The dirty dot says *that* a tab changed; this says what changed, which is the
        question actually worth answering before a save -- or after the assistant or
        lazygit has been at the file underneath the buffer.
        """
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

    # -- exec strip --------------------------------------------------------
    @rt('/exec')
    async def exec_route(req):
        """Run in the owner kernel or the agent's protected persistent overlay."""
        d = await req.json()
        code, scope = (d.get('code') or '').strip(), d.get('scope', 'live')
        if not code: return {'ok': True, 'text': '', 'outputs': []}
        k = _debug.get('kernel') or await _k()
        # A normal execute_request queues behind the paused cell forever. While debugging,
        # the same Exec strip becomes a frame REPL and evaluates through DAP instead.
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
        """Run the open .py as a script, in the tab's kernel.

        The editor's text is what runs, not the file on disk -- pressing run after typing
        should run what is on the screen -- and it runs *in* the kernel rather than in a
        subprocess, so everything the script defines is in the variable panel when it
        finishes.
        """
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
        """Compiler or structural diagnostics for an unsaved buffer; source is never run."""
        d = await req.json(); lang, code = d.get('lang'), str(d.get('code') or '')
        if lang == 'python':
            diagnostics = _python_diagnostics(code, d.get('path') or '<cell>')
            path = str(d.get('path') or '')
            if path.endswith('.py'):
                rows, note = await _off_loop(ws.lsp.diagnostics, path, code)
                lines = code.splitlines(keepends=True) or ['']; starts, at = [], 0
                for line in lines: starts.append(at); at += len(line)
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
        # Agent charters are ordinary Markdown, but these landmarks make state legible and
        # updateable. Report omissions as advice rather than rejecting free-form documents.
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

    # `lsp` is connected as a block; see BLOCKS.

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
        """One inline suggestion from the local model, for what belongs at the cursor.

        Never fired by typing: it costs a forward pass, and the kernel's own completions
        above are instant and know the real namespace. This answers the other question --
        what the next few lines should *say*.
        """
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
        # Completion models occasionally fence a replacement despite being told not to.
        # Reuse fastcore's structural fence parser rather than trimming backticks by hand.
        from fastcore.xtras import fenced_blocks
        if blocks := fenced_blocks(answer): answer = str(blocks[-1][1]).strip()
        if not answer: return _fail(ws.ai.note or 'the model returned no suggestion')
        return {'ok': True, 'text': answer, 'mode': mode,
                'model': ws.ai.routing.name_for('summary' if mode == 'summary' else 'completion')}

    # `vars` is connected as a block; see BLOCKS.

    # `search` is connected as a block; see BLOCKS.

    # `workspace` and `git` are connected as blocks; see BLOCKS.

    # `term` is connected as a block; see BLOCKS.

    # `research` is connected as a block; see BLOCKS.

    # -- live envs ---------------------------------------------------------
    # -- run configurations & dev servers ----------------------------------
    # `runs` is connected as a block; see BLOCKS.

    @rt('/debug/capabilities')
    def debug_capabilities():
        from ..debug import debugpy_available
        from ..kernels import project_python
        python = ws.pool.default_python or project_python(ws.fs.roots) or sys.executable
        return {'python': str(python), 'debugpy': debugpy_available(python),
                'notebook': True, 'direct': debugpy_available(python)}

    @rt('/debug/install')
    async def debug_install(req):
        from ..kernels import project_python
        d = await req.json(); python = d.get('python') or ws.pool.default_python or project_python(ws.fs.roots)
        if not python: return _fail('choose a project interpreter first')
        def install():
            cmd = [shutil.which('uv'), 'pip', 'install', '--python', str(python), 'debugpy'] if shutil.which('uv') else [str(python), '-m', 'pip', 'install', 'debugpy']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode: raise RuntimeError(result.stderr or result.stdout)
        try: await _off_loop(install); return {'ok': True, 'python': str(python)}
        except Exception as e: return _fail(e)

    @rt('/debug/start')
    async def debug_start(req):
        "Launch a Python file/module or attach through a direct debugpy DAP session."
        from ..debug import DebugSession
        from ..kernels import project_python
        d = await req.json(); name = d.get('name') or ''
        run = ws.runs.get(name) if name else None
        config = run.dict() if run else dict(d)
        root = ws.fs.roots[0] if ws.fs.roots else Path.cwd()
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

    # -- what the assistant can see ---------------------------------------
    @rt('/screen')
    async def screen(req):
        """Park a screenshot to go with the next question.

        The capture itself has to happen in the browser -- `getDisplayMedia` needs a user
        gesture and a real window server, neither of which a server-side grab has. So the
        page sends the frame here, and it waits in the workspace until something asks.
        """
        d = await req.json()
        url = d.get('data_url') or ''
        if not url.startswith('data:image'): return _fail('no image in that capture')
        # The browser scales ordinary captures, but this route is still a public input
        # boundary. Refuse an oversized encoded body before allocating its decoded copy.
        if len(url) > 12_000_000: return _fail('screen capture is larger than 9 MB', 413)
        import base64
        try: png = base64.b64decode(url.split(',', 1)[1], validate=True)
        except Exception as e: return _fail(e)
        if len(png) > 9_000_000: return _fail('screen capture is larger than 9 MB', 413)
        ws.put_screen(png=png, note='a screenshot from the browser')
        return {'ok': True, 'bytes': len(png)}

    # -- agent -------------------------------------------------------------
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

    @rt('/agent/history')
    async def agent_history():
        """All durable turns grouped by model-context session, newest session first."""
        execution = await _api('/agent/api/sessions') or {'sessions': []}
        # Scripted is the test harness backend. It can share the developer config directory,
        # but its fixture turns are not user conversations and must not bury real Luna history.
        turns = [t for t in ws.ai.history if t.get('model') != 'scripted']
        return {'sessions': _history_sessions(turns, execution.get('sessions', [])),
                'model': ws.ai.model.name, 'current': ws.ai.session_id}

    @rt('/agent/models')
    def agent_models(legacy: bool = True):
        from ..agent.core import DFLT_LOCAL, available_models, auth_status, resolve
        from ..model_store import load_models
        saved=load_models()
        rows = available_models(include_legacy=legacy)
        rows += [{'value':x['name'],'label':x['name'],'provider':x['runtime'],
                  'source':f"saved · {x['model_id']}",'custom':True} for x in saved]
        agent = ws.ai.model.name if ws._ai is not None else (ws.model or os.environ.get('LEELA_MODEL') or DFLT_LOCAL)
        inline = (ws.inline_ai.model.name if ws._inline_ai is not None else
                  (ws.inline_model or os.environ.get('LEELA_MODEL_INLINE') or 'gpt-mini'))
        completion = (ws.ai.routing.name_for('completion') if ws._ai is not None else
                      (ws.completion_model or os.environ.get('LEELA_MODEL_COMPLETION') or 'gpt-4.1'))
        # A durable choice remains visible even before its provider is authenticated. Hiding
        # it made the first local option look selected while requests still used the saved one.
        for current in (agent, inline, completion):
            try:
                spec = resolve(current)
                if not any(resolve(row['value']).model_id == spec.model_id for row in rows):
                    provider = spec.model_id.partition('/')[0] if not spec.local else spec.runtime
                    rows.append({'value': current, 'label': current, 'provider': provider,
                                 'source': 'saved choice · provider credentials may be required'})
            except Exception: pass
        def selected(current):
            try:
                mid = resolve(current).model_id
                return next((r['value'] for r in rows if resolve(r['value']).model_id == mid), current)
            except Exception: return current
        return {'models': rows, 'saved':saved, 'auth': auth_status(),
                'selected': {'agent': selected(agent), 'inline': selected(inline),
                             'completion': selected(completion)}}

    @rt('/agent/models/add')
    async def agent_models_add(req):
        "Save a Hugging Face repo/URL or hosted provider model alias."
        from ..model_store import save_model
        try:return {'ok':True,'model':save_model(await req.json())}
        except Exception as e:return _fail(e)

    @rt('/agent/models/remove')
    async def agent_models_remove(req):
        from ..model_store import delete_model
        try:return {'ok':True,'name':delete_model((await req.json()).get('name',''))}
        except Exception as e:return _fail(e)

    @rt('/agent/settings')
    async def agent_settings(req):
        "Set engine-level agent options. LiteRT engines reload lazily after a change."
        d = await req.json()
        try:
            enabled = d.get('local_multimodal')
            if not isinstance(enabled, bool): raise ValueError('local_multimodal must be true or false')
            live = [a for a in (ws._ai, ws._inline_ai) if a is not None]
            if any(a.busy for a in live): raise RuntimeError('cannot change local multimodal while an assistant is working')
            for a in live: a.set_local_multimodal(enabled)
            ws.local_multimodal = enabled
            ws.save()
            return {'ok': True, 'local_multimodal': enabled,
                    'note': f'local image/audio encoders {"enabled" if enabled else "disabled"}'}
        except Exception as e: return _fail(e)

    @rt('/agent/compaction')
    async def agent_compaction(req):
        "Configure visible automatic compaction without restarting the model conversation."
        d = await req.json(); strategy = d.get('strategy', ws.compact_strategy)
        if strategy not in {'surgical', 'summary'}: return _fail('strategy must be surgical or summary')
        auto = d.get('auto', ws.compact_auto)
        if not isinstance(auto, bool): return _fail('auto must be true or false')
        ws.compact_auto, ws.compact_strategy = auto, strategy
        for agent in (ws._ai, ws._inline_ai):
            if agent is not None:
                agent.compactor.auto, agent.compactor.strategy = auto, strategy
        ws.save()
        return {'ok': True, 'auto': auto, 'strategy': strategy,
                'note': f'auto compaction {"on" if auto else "off"} · {strategy}'}

    @rt('/agent/model')
    async def agent_model(req):
        d = await req.json()
        try:
            from ..model_store import load_models
            load_models()
            target = d.get('target', 'agent')
            assistant = ws.inline_ai if target == 'inline' else ws.ai
            job = 'completion' if target == 'completion' else 'turn'
            spec = assistant.set_model((d.get('model') or '').strip(), job=job)
            if target == 'inline': ws.inline_model = spec.name
            elif target == 'completion': ws.completion_model = spec.name
            elif target == 'agent': ws.model = spec.name
            ws.save()
            return {'ok': True, 'target': target, 'model': spec.name, 'note': model_note(spec)}
        except Exception as e: return _fail(e)

    @rt('/agent/memory')
    async def agent_memory():
        "Editable notes and their explicit per-model session routing."
        notes = await _off_loop(ws.memory.agent_notes)
        rows = []
        for note in notes:
            text = await _off_loop(ws.memory.exact_text, str(note['id']))
            rows.append({**note, 'text': text})
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
        for assistant in (ws._ai, ws._inline_ai):
            if assistant is not None: assistant.refresh()
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
        tokens = 0
        for value in selected:
            tokens += max(1, len(await _off_loop(ws.memory.exact_text, value)) // 4)
        return {'ok': True, 'target': target, 'ids': selected, 'tokens': tokens}

    @rt('/agent/memory/delete')
    async def agent_memory_delete(req):
        doc_id = str((await req.json()).get('id') or '')
        known = {str(note['id']) for note in await _off_loop(ws.memory.agent_notes)}
        if doc_id not in known: return _fail('unknown agent memory note')
        for target, ids in ws.agent_memory_selection.items():
            ws.agent_memory_selection[target] = [value for value in ids if value != doc_id]
        ok = await _off_loop(ws.memory.forget, doc_id); ws.save()
        for assistant in (ws._ai, ws._inline_ai):
            if assistant is not None: assistant.refresh()
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
        from ..ai import STATE_TEMPLATE
        tools = _tool_schemas(ws.ai)
        catalog = '\n'.join(f"- `{t['name']}` ({t['group']}): {t['description']}" for t in tools)
        return {'template': STATE_TEMPLATE, 'tools': tools,
                'catalog': '## Available tools\n' + (catalog or '- No tools are currently available.')}

    @rt('/agent/state/bootstrap')
    async def agent_state_bootstrap(req):
        "Ask the summary model to fill a transparent charter from the template and real tools."
        from ..ai import STATE_TEMPLATE
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
        from ..ai import STATE_TEMPLATE
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
        ids = []
        for hit in hits:
            doc_id = str(hit.get('doc_id') or '')
            if doc_id in states and doc_id not in ids: ids.append(doc_id)
        return {'query': q, 'states': [states[i] for i in ids[:5]]}

    @rt('/agent/state/diagnostics')
    async def agent_state_diagnostics(req):
        "Token budget, stale paths, and duplicate/conflicting headings for edited state."
        import re
        d = await req.json(); text = str(d.get('text') or '')
        tokens = ws.ai.backend.count_tokens(text) if ws._ai is not None else max(1, len(text)//4)
        paths = set(re.findall(r'(?<![\w.-])(?:[\w.-]+/)+[\w.-]+', text))
        missing = []
        for path in paths:
            try:
                if not ws.fs._check(path).exists(): missing.append(path)
            except Exception: missing.append(path)
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
        """Whether the assistant is loaded, what model it is on, and what it is doing right now.

        Polled while a turn runs, which is why `activity` is in here: an agentic loop that
        shows nothing for forty seconds is indistinguishable from a hang, and the client
        renders these rows as they arrive. `approval` is in the same payload so a write
        waiting on a person is picked up by the poll already in flight rather than needing
        a channel of its own.
        """
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
        """One turn as server-sent events, so the browser fills in as the model writes.

        SSE rather than a WebSocket because this is one-way and short-lived, and the
        terminal already owns the only socket in this app. Each event carries either a
        markdown chunk, an activity row, or the final payload with the diffs -- so the
        client renders the same three things it renders for a blocking turn, just sooner.

        The generator runs on a worker thread and hands chunks over a queue: the harness is
        synchronous by design (see `leela.agent.runtime`), and blocking the event loop on a
        model would freeze every other request this server is serving.
        """
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

            def changed_activity():
                """New calls and in-place transitions (pending -> done), not only appends."""
                changed = []
                for row in a.activity.rows(mark=a.activity._mark):
                    version = (row.get('done'), row.get('ok'), row.get('line'), row.get('detail'), row.get('secs'))
                    if activity_versions.get(row['id']) != version:
                        activity_versions[row['id']] = version
                        changed.append(row)
                return changed

            try:
                while True:
                    # A bounded wait both notices vanished browsers and publishes tool state
                    # changes while the model itself is silent inside a long-running call.
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
                        # A tool may have finished immediately before the worker's sentinel.
                        for row in changed_activity(): yield _sse('activity', row)
                        break
                    yield _sse(kind, {'text': val} if kind == 'chunk' else {'error': val})
            finally:
                if not finished:
                    try: a.cancel()
                    except Exception: pass
            if not finished: return
            await task
            # `problems` rather than `note` alone: a turn can finish looking fine while the
            # engine refused a compaction or a completion on the way, and those failures
            # have no other way out -- see `Agent.problems`.
            capabilities = a.turn_capabilities(a.current_turn_id)
            yield _sse('done', {'ok': a.ready, 'note': a.note,
                                'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                                'session_usage': a.use.dict(), 'session_usage_label': repr(a.use),
                                'model': a.model.name, 'turn_id': a.current_turn_id,
                                'branch_id': a.current_branch_id, 'capabilities': capabilities,
                                'problems': a.problems,
                                'activity': a.activity.rows(mark=a.activity._mark),
                                'edits': [{'path': p, **_diff(was, now)}
                                          for p, (was, now) in a.changes().items()]})

        from starlette.responses import StreamingResponse
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

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
        from ..ai import WRITE_TOOLS
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
        """Ask for a decision in this browser on behalf of an external Rishi session.

        Notebook kernels and ordinary Python processes cannot use ``input()`` through the
        web IDE. This endpoint lets Rishi's optional browser approval callback join the
        same queue and render the same approval card as Leela's own agent.
        """
        d = await req.json()
        tc = d.get('tool_call') or {}
        fn = tc.get('function') or {} if isinstance(tc, dict) else {}
        name, args = fn.get('name'), fn.get('arguments', {})
        if not name: return _fail('tool_call.function.name is required')
        if isinstance(args, str):
            try: args = json.loads(args)
            except Exception: return _fail('tool_call.function.arguments must be an object or JSON object')
        if not isinstance(args, dict): return _fail('tool_call.function.arguments must be an object')
        try: timeout = min(3600, max(1, float(d.get('timeout', ws.approvals.timeout))))
        except (TypeError, ValueError): return _fail('timeout must be a number of seconds')
        a = await _off_loop(ws.approvals.request, name, args, True, timeout)
        return {'ok': True, 'answer': a.dict()}

    @rt('/agent/approve')
    async def agent_approve(req):
        """Answer a pending approval. `note` is the reason, and the reason goes back to the model.

        Refusing with a reason is the point of the whole mechanism: "no, that file is
        generated, edit the notebook instead" redirects the agent, where a bare denial just
        makes it try the same edit again.
        """
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
        return {'ok': True, 'text': out}

    @rt('/agent/ask')
    async def agent_ask(req):
        """One turn with the assistant.

        The model runs on a worker thread and its tools call straight back into this
        workspace, so an edit it makes is on disk by the time the reply arrives.

        What comes back with the reply is a *diff per changed file*, taken from disk on
        either side of each write rather than from what the tools reported. That is the
        difference between the model's account of its work and the work: a tool result is
        a claim, and the file is the fact. It also lets the client decide whether
        reloading the tab would throw away something the user typed while it was thinking.
        """
        d = await req.json()
        q = (d.get('prompt') or '').strip()
        if not q: return _fail('nothing to ask')
        a = ws.ai
        text = await _off_loop(ws.ask, q)      # `ws.ask` attaches any pending screen capture
        return {'ok': a.ready, 'text': text, 'note': a.note,
                'activity': a.activity.rows(mark=a.activity._mark),
                'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                'session_usage': a.use.dict(), 'session_usage_label': repr(a.use), 'model': a.model.name,
                'edits': [{'path': p, **_diff(was, now)} for p, (was, now) in a.changes().items()]}

    # -- kernel control ----------------------------------------------------
    @rt('/nb/interrupt')
    async def nb_interrupt(req):
        "Interrupt one exact running cell, force-restarting its managed kernel if needed."
        d = await req.json()
        item = running_cells.get((d.get('path') or '', d.get('id') or ''))
        if item is None: return _fail('that cell is not running')
        k, _task = item
        if not hasattr(k, 'stop'): return _fail('this external runtime cannot be stopped safely')
        return await k.stop(timeout=2.0)


    # `runtime` also owns the /kernel/* routes; see BLOCKS.

    # -- blocks --------------------------------------------------------------
    # Routes extracted from this function so far. Order is the registration order, and the
    # first route to match a path wins; `tests/routes.txt` pins the resulting surface.
    # Blocks connect last for now, so anything still defined above keeps its precedence
    # while the extraction is in progress.
    # `debug` is not supplied yet: the debugger closures are still in this function, and a
    # Ctx must not hand a block a capability that is not the live one. It joins here when
    # the debug block moves.
    connect_all(app, ws, BLOCKS, docs=_docstore, running=_runstate, gate=gate,
                catalog=workspace_catalog)

    return app


def serve_ide(roots=(), port=5001, host='127.0.0.1', agent='restricted', kernel_port=8400,
              open_ws=True, kernel='ipykernel',
              model=None, approvals='ask', agent_scope='overlay', python=None,
              app_window=False, cdp_port=9223, transport='auto', gateway_port=8787):
    """Start one web workspace, or independent app-window workspaces under ``--app``.

    Independent workspaces share the ASGI/Chrome processes but not mutable IDE state.
    Host-based dispatch keeps all existing absolute browser routes valid:
    ``project.localhost:5001`` and ``tests.localhost:5001`` each own an ``ide_app``.
    """
    import uvicorn
    try:
        loopback = host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError('Leela executes code and may only bind to a loopback address')
    from .. import leela_cfg
    from .workspaces import WorkspaceHub, WorkspaceSite, workspace_slug

    roots = [Path(r).expanduser().resolve() for r in roots]
    gate = TerminalGate(host=host)
    requested_transport = transport
    transport = ('gateway' if app_window else 'direct') if transport == 'auto' else transport
    gateway = None
    if transport == 'gateway':
        try:
            from ..kernels import GatewayService
            gateway = GatewayService(port=gateway_port).start()
        except (ImportError, RuntimeError) as e:
            # App windows prefer the shared gateway, but a desktop/source install without
            # the optional gateway extra must still open and run code. Only an explicit
            # `--transport gateway` is a hard requirement; `auto` degrades to direct ZMQ.
            if requested_transport != 'auto': raise
            transport = 'direct'
            print(f'  gateway unavailable; using direct kernel transport: {errstr(e)}')
    if app_window and roots:
        from ..kernels import RuntimeBroker
        sites, used, hub, broker = [], [], None, RuntimeBroker()
        for i, root in enumerate(roots):
            slug = workspace_slug(root.name, used); used.append(slug)
            state = leela_cfg/'workspaces'/f'{slug}.json'
            kw = dict(port=kernel_port + i * 100, agent=agent, kernel=kernel, model=model,
                      approvals=approvals, agent_scope=agent_scope, python=python,
                      transport=transport, gateway=gateway)
            ws = Workspace.load(path=state, **kw) if open_ws else Workspace(**kw)
            state.parent.mkdir(parents=True, exist_ok=True)
            ws._state_path = state
            broker.register(ws.pool)
            if root not in ws.fs.roots: ws.add_root(root)
            if ws.restore_remembered_agent_state(): ws.save()
            app = ide_app(ws, gate, workspace_catalog=lambda: hub.catalog())
            sites.append(WorkspaceSite(slug, root.name, str(root), app))
        hub = WorkspaceHub(sites, port)
        app = hub
        urls = [row['url'] for row in hub.catalog()]
        print(f'leela  {len(sites)} independent workspaces on :{port}')
        for row in hub.catalog(): print(f"  {row['name']}: {row['url']}")
        if app_window:
            import threading, time, urllib.request
            def open_windows():
                probe = f'http://127.0.0.1:{port}/'
                for _ in range(150):
                    try: urllib.request.urlopen(probe, timeout=.25).close(); break
                    except Exception: time.sleep(.1)
                from .cdp import open_cdp_app
                for url in urls:
                    result = open_cdp_app(url, port=cdp_port)
                    print(f"  Chrome {'reused' if result['reused'] else 'started'}: {url}")
            threading.Thread(target=open_windows, daemon=True, name='leela-cdp-open').start()
    else:
        kw = dict(port=kernel_port, agent=agent, kernel=kernel, model=model, approvals=approvals,
                  agent_scope=agent_scope, python=python, transport=transport, gateway=gateway)
        if open_ws and not roots:
            ws = Workspace.load(**kw)
        else:
            # Opening an explicit folder starts a clean tab set, not a clean preference set.
            # Reuse the durable model choices so `leela .` does not reset routing each run.
            try: remembered = (leela_cfg/'workspace.json').read_json() if open_ws else {}
            except Exception: remembered = {}
            if model is None: kw['model'] = remembered.get('model')
            kw['inline_model'] = remembered.get('inline_model') or 'gpt-mini'
            kw['completion_model'] = remembered.get('completion_model') or 'gpt-4.1'
            ws = Workspace(**kw)
        for r in roots: ws.add_root(r)
        if not ws.fs.roots:
            import sys
            ws.add_root(Path.home() if getattr(sys, 'frozen', False) else os.getcwd())
        if ws.restore_remembered_agent_state(): ws.save()
        app = ide_app(ws, gate)
        print(f'leela  http://{host}:{port}   folders: ' + ', '.join(p.name for p in ws.fs.roots))
        if app_window:
            import threading, time, urllib.request
            def open_window():
                url = f'http://127.0.0.1:{port}/'
                for _ in range(150):
                    try: urllib.request.urlopen(url, timeout=.25).close(); break
                    except Exception: time.sleep(.1)
                from .cdp import open_cdp_app
                open_cdp_app(url, port=cdp_port)
            threading.Thread(target=open_window, daemon=True, name='leela-cdp-open').start()
    if not gate.enabled: print(f'  {gate.why}')
    from .workspaces import LoopbackHostGuard
    uvicorn.run(LoopbackHostGuard(app), host=host, port=port, log_level='warning')
