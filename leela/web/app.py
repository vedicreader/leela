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
from ..buttons import bar as btn_bar
from ..diffs import diff_label, diff_rows, did_you_mean, fuzzy_rank, udiff
from ..fs import lang_for
from ..git import GitRepo, GitError
from .. import keys as keymap
from ..keys import (web_keymap, help_rows, toast_rows, by_scope, chord_display, keymap_path,
                    keymap_json)
from ..menus import web_menus
from ..nb import Notebook, Cell
from ..research import MAX_DOC_CHARS
from ..settings import Settings
from ..term import TerminalGate, lazygit_argv, LazygitMissing
from ..workspace import Workspace
from ..agent.core import model_note

__all__ = ['ide_app', 'serve_ide']


def static_dir():
    "Web assets in a normal install, py2app Resources, or a py2exe distribution."
    import sys
    candidates = [Path(__file__).parent/'static']
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve()
        candidates += [exe.parent/'leela'/'web'/'static',
                       exe.parent.parent/'Resources'/'leela'/'web'/'static']
    return next((p for p in candidates if p.exists()), candidates[0])


def _asset(name):
    "A static URL that changes when the local asset does, preventing mixed JS/CSS revisions."
    p = static_dir()/name
    try: version = p.stat().st_mtime_ns
    except OSError: version = 0
    return f'/leestatic/{name}?v={version}'


def _fail(err, code=400):
    "The IDE's JSON error shape. `err` is an exception (reported `Type: message`) or a ready string."
    return JSONResponse({'ok': False, 'error': errstr(err) if isinstance(err, Exception) else str(err)},
                        status_code=code)


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


def _sse(event, data):
    "One server-sent event. Newlines in the payload would end the frame, so it goes as JSON."
    return f'event: {event}\ndata: {json.dumps(data)}\n\n'


from fastcore.aio import athreaded

@athreaded
def _off_loop(fn, *a, **kw):
    """Run blocking research, indexing and model work on fastcore's worker thread."""
    return fn(*a, **kw)


def _diff(was, now):
    "One text-vs-text comparison in the shape every diff surface in the client consumes."
    return {'label': diff_label(was, now), 'rows': [r.dict() for r in diff_rows(udiff(was, now))]}


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


def _project_package_rows(path, python=None):
    """Declared pyproject requirements with installed versions and source-line addresses.

    The selected project interpreter is queried in one short subprocess. Nothing is
    imported from the project and no package code executes: importlib.metadata reads only
    installed distribution metadata.
    """
    import tomllib
    p = Path(path)
    source = p.read_text(encoding='utf-8')
    data = tomllib.loads(source)
    project = data.get('project') or {}
    declared = list(project.get('dependencies') or [])
    for values in (project.get('optional-dependencies') or {}).values(): declared += list(values or [])
    for values in (data.get('dependency-groups') or {}).values():
        declared += [x for x in (values or []) if isinstance(x, str)]
    try:
        from packaging.requirements import Requirement
        parsed = [(Requirement(x), x) for x in declared]
    except Exception:
        parsed = []
    names = list(dict.fromkeys(r.name for r, _raw in parsed))
    versions = {}
    if names:
        # Keep the child snippet explicit and exception-safe; a missing distribution is
        # data for a pill, not a failed endpoint.
        script = ('import importlib.metadata as m,json,sys\n'
                  'out={}\n'
                  'for n in json.loads(sys.argv[1]):\n'
                  ' try: out[n]=m.version(n)\n'
                  ' except m.PackageNotFoundError: out[n]=None\n'
                  'print(json.dumps(out))')
        try:
            proc = subprocess.run([str(python or sys.executable), '-c', script, json.dumps(names)],
                                  capture_output=True, text=True, timeout=8, check=True)
            versions = json.loads(proc.stdout)
        except Exception: versions = {n: None for n in names}
    rows, used = [], set()
    lines = source.splitlines()
    for req, raw in parsed:
        try:
            if req.marker and not req.marker.evaluate(): continue
        except Exception: pass
        # Match the complete declaration, not merely the package name. A package name may
        # also occur in keywords, comments or URLs; annotating that nearest text is exactly
        # the kind of plausible-looking wrong answer an editor must avoid. The address is
        # immediately after the closing quote, before a trailing comma/comment.
        found = None
        for i, line in enumerate(lines, 1):
            for quote in ('"', "'"):
                token = f'{quote}{raw}{quote}'
                at = line.find(token)
                key = (i, at, token)
                if at >= 0 and key not in used:
                    found = (i, at + len(token)); used.add(key); break
            if found: break
        if not found: continue
        installed = versions.get(req.name)
        compatible = None
        if installed is not None and str(req.specifier):
            try: compatible = req.specifier.contains(installed, prereleases=True)
            except Exception: compatible = None
        rows.append({'line': found[0], 'column': found[1], 'name': req.name,
                     'required': str(req.specifier), 'marker': str(req.marker or ''),
                     'installed': installed, 'compatible': compatible,
                     'python': str(python or sys.executable)})
    return rows


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
def _tab_bar(ws):
    "The open tabs. `alt+1..9` selects, the x closes."
    if not ws.tabs: return Div(Span('no files open', cls='lee-dim'), id='tabbar', cls='lee-tabbar', role='tablist')
    kids=[];counts={}
    for t in ws.tabs:counts[t.title]=counts.get(t.title,0)+1
    def label(t):
        if counts[t.title]<2 or not t.path:return t.title
        try:
            root=ws.fs.root_of(t.path);return f'{root.name}/{Path(t.path).relative_to(root)}'
        except Exception:return t.path
    for i,t in enumerate(ws.tabs):
        cls='lee-tab'+(' active' if i==ws.active else '')+(' dirty' if t.dirty else '')
        kids.append(Div(
            Span(cls='lee-tab-run', title=f'{t.running} cell(s) running') if t.running else '',
            Span(cls='lee-save-state '+('pending' if t.dirty else 'saved'),
                 title='changes waiting for autosave' if t.dirty else 'saved on disk',
                 aria_label='changes waiting for autosave' if t.dirty else 'saved on disk'),
            Span(label(t),cls='lee-tab-name'),
            Button('×', cls='lee-tab-x', title=f'close {t.title}', aria_label=f'close {t.title}',
                   onclick=f'event.stopPropagation();leeCloseTab({i})'),
            cls=cls,title=t.path or t.title,data_i=i,data_kind=t.kind,role='tab',
            aria_selected='true' if i == ws.active else 'false', tabindex='0' if i == ws.active else '-1',
            hx_post=f'/tab/select?i={i}', hx_target='#tabbar', hx_swap='outerHTML'))
    return Div(*kids, id='tabbar', cls='lee-tabbar', role='tablist', aria_label='open files')


def _kernel_pill(ws):
    "Kernel identity and liveness for the active tab. Clicking it opens the picker."
    common = dict(id='kpill', onclick='leeAct("pick_kernel")')
    if (k := ws.runtime_peek()) is None:
        return Span('no kernel', cls='lee-pill lee-pill-off', title='choose a kernel', **common)
    if not k.alive: return Span('kernel dead', cls='lee-pill lee-pill-err', title='choose a kernel', **common)
    nm = getattr(k, 'name', '') or Path(ws.kernel_key()).name or 'kernel'
    return Span(f'⏺ {nm}', cls='lee-pill lee-pill-on',
                title=f'{k.base or "no inspector"} · pid {k.pid} — click to change', **common)


def _btn(b):
    "One button from the shared table. The click runs the same action its key runs."
    return Button(b.label, cls='lee-btn ' + (b.kind or 'plain'), title=b.tooltip,
                  data_action=b.action, onclick=f'leeAct("{b.action}")')


def _action_bar(name, **kw):
    "A whole bar of them, in the order `leela.buttons` declares."
    return Div(*[_btn(b) for b in btn_bar(name)], cls=f'lee-bar lee-bar-{name}', **kw)


def _menu_button(surface):
    "Mouse-discoverable door into the same contextual registry used by right-click."
    return Button('⋯', cls='lee-more', title=f'{surface} actions', aria_label=f'{surface} actions',
                  onclick=f'leeMenuAt("{surface}", this)')


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


def _git_tree_state(ws):
    "Absolute changed paths for file-tree decoration, across every open repository."
    out = {}
    seen = set()
    for root in ws.fs.roots:
        try: repo = GitRepo.at(root)
        except GitError: continue
        if repo.root in seen: continue
        seen.add(repo.root)
        try:
            for c in repo.changes():
                out[str((repo.root/c['path']).resolve())] = c
        except GitError: pass
    return out


def _tree_node(e, git_state=None):
    "One file-tree row; directories lazily fetch their children on first open."
    if e.is_dir:
        return Details(
            Summary(Span('▸', cls='lee-caret'), Span(e.name, cls='lee-fname'),
                    hx_get=f'/tree?path={quote(e.path)}', hx_target='next .lee-kids', hx_trigger='click once'),
            Div(cls='lee-kids'),
            cls='lee-node lee-dir' + (' lee-root' if e.is_root else ''), data_path=e.path,
            role='treeitem', aria_expanded='false', aria_selected='false')
    change = (git_state or {}).get(str(Path(e.path).resolve()))
    state = ('conflict' if change and change['conflicted'] else 'untracked' if change and change['untracked']
             else 'staged' if change and change['staged'] and not change['unstaged'] else 'modified' if change else '')
    return Div(Span(e.name, cls='lee-fname'), Span(state[:1].upper(), cls='lee-tree-git') if state else '',
               cls='lee-node lee-file' + (f' git-{state}' if state else ''), data_path=e.path, data_lang=e.lang or '',
               role='treeitem',aria_selected='false',
               onclick=f'event.preventDefault();event.stopPropagation();leeOpenFile({json.dumps(e.path)})')


def _activity_icon(kind):
    "Small monochrome activity-bar icons; labels remain available to assistive tech."
    if kind == 'files':
        return NotStr('<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2.5 5.5h6l1.7 2h7.3v8.5h-15zM2.5 5.5V4h5l1.5 1.5"/></svg>')
    if kind == 'symbols':
        return NotStr('<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 3.5h10M5 10h10M5 16.5h10"/><circle cx="3" cy="3.5" r="1"/><circle cx="3" cy="10" r="1"/><circle cx="3" cy="16.5" r="1"/></svg>')
    return NotStr('<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="5" cy="4" r="2"/><circle cx="15" cy="6" r="2"/><circle cx="5" cy="16" r="2"/><path d="M5 6v8m2-7h4a4 4 0 0 1 4 4v-3"/></svg>')


def _files_panel(ws):
    state = _git_tree_state(ws)
    body = [_tree_node(e, state) for e in ws.fs.ls(None)] or [Div('no folder open', cls='lee-dim')]
    return Section(
        Div(Span('files', cls='lee-ptitle'), Span(cls='lee-spacer'), _action_bar('web_files'),
            _action_bar('files'), _menu_button('files'),
            Button('−', cls='lee-pane-min', title='minimise files', aria_label='minimise files',
                   onclick='leePane("left", false)'), cls='lee-phead'),
        Div(*body, id='filetree', cls='lee-tree', tabindex='0', role='tree', aria_label='project files'),
        cls='lee-panel lee-files')


def _git_panel():
    return Section(
        Div(Span('source control', cls='lee-ptitle'), Span(cls='lee-spacer'),
            Button('refresh', cls='lee-btn', onclick='leeGitRefresh()', title='refresh repository'),
            Button('−', cls='lee-pane-min', title='minimise source control',
                   aria_label='minimise source control', onclick='leePane("left", false)'), cls='lee-phead'),
        Div(Div('loading repository…', cls='lee-dim lee-git-empty'), id='gitpanel', cls='lee-git-panel'),
        cls='lee-panel lee-source-control')


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
                   onclick='leeLeft("git")'), cls='lee-activity', aria_label='Project tools'),
        Div(_files_panel(ws), _symbols_panel(), _git_panel(), _toast_panel(), cls='lee-left-content'),
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
    running_cells = {}
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

    def _term_cwd(ref=None):
        "Where a new terminal starts. Ergonomics, not confinement -- a shell can `cd` anywhere."
        if ref:
            try: return ws.fs._check(ref, must_exist=True)
            except Exception: pass
        return ws.cwd_for() or (ws.fs.roots[0] if ws.fs.roots else None)

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

    # Open notebooks, keyed by tab. The server holds the document so structural
    # edits and runs stay consistent across reloads of the page.
    _docs: dict[str, Notebook] = {}
    _buffers: dict[str, str] = {}       # unsaved text files survive tab switches
    _buffer_bases: dict[str, str] = {}  # disk version each browser draft began from
    # Admission happens before kernel startup. Kernel.execute serialises live requests, but
    # two first cells can both wait for the same startup and then reach that lock in the
    # opposite order. Definitions and their tests must execute in submission order.
    _run_locks: dict[str, asyncio.Lock] = {}
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
        for nb in _docs.values():
            for c in nb.cells: c.fresh = False

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

    @rt('/keys.json')
    def keys_json():
        "The keymap, and the buttons that run the same actions -- one fetch, one source."
        from ..buttons import BARS
        return JSONResponse({'keys': web_keymap(), 'help': help_rows(), 'menus': web_menus(),
                             'path': str(keymap_path()), 'notes': list(keymap.NOTES),
                             'bars': {n: [{'action': b.action, 'label': b.label, 'title': b.tooltip,
                                           'kind': b.kind} for b in btn_bar(n)] for n in BARS}})

    # -- the user's keymap -------------------------------------------------
    # Editable from the IDE and applied without a restart: rewriting the file, re-reading
    # it, and returning the rebuilt browser map is the entire update path.
    @rt('/keys/file')
    def keys_file():
        p = keymap_path()
        try: text = p.read_text()
        except Exception: text = json.dumps(keymap_json(), indent=2) + '\n'
        return {'path': str(p), 'exists': p.exists(), 'text': text, 'notes': list(keymap.NOTES)}

    @rt('/keys/save')
    async def keys_save(req):
        "Write the keymap, re-read it, and hand back what it now says -- including what it refused."
        d = await req.json()
        text = d.get('text') or ''
        try: json.loads(text)
        except Exception as e: return _fail(f'that is not valid JSON — {errstr(e)}')
        p = keymap_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        except Exception as e: return _fail(e)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES),
                'keys': web_keymap(), 'help': help_rows()}

    @rt('/keys/reset')
    def keys_reset():
        "Put leela's own defaults back, so a keymap you cannot use is one click from gone."
        p = keymap.write_keymap(keys=keymap.DEFAULTS)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES),
                'keys': web_keymap(), 'help': help_rows()}

    # -- layered settings --------------------------------------------------
    def _settings(): return Settings(ws.fs.roots[0] if ws.fs.roots else None)

    @rt('/settings')
    def settings_get(language: str = ''):
        "Effective defaults + user + workspace + language values and their origins."
        return _settings().describe(language)

    @rt('/settings/save')
    async def settings_save(req):
        d = await req.json()
        try:
            return {'ok': True, **_settings().save(d.get('scope', 'user'), d.get('section', 'editor'),
                                                    d.get('values') or {}, d.get('language') or '')}
        except Exception as e: return _fail(e)

    @rt('/settings/reset')
    async def settings_reset(req):
        d = await req.json()
        try:
            return {'ok': True, **_settings().reset(d.get('scope', 'user'), d.get('section'),
                                                     d.get('language') or '')}
        except Exception as e: return _fail(e)


    # -- project runtime ---------------------------------------------------
    @rt('/runtime/broker')
    def runtime_broker():
        broker = getattr(ws.pool, 'broker', None)
        return broker.status() if broker else {'live': len(ws.pool.kernels), 'limit': None, 'runtimes': []}

    @rt('/runtime/info')
    async def runtime_info():
        from ..kernels import project_python
        from ..runtime_support import kernel_support
        root = ws.fs.roots[0] if ws.fs.roots else None
        py = project_python([root]) if root else None
        support = await _off_loop(kernel_support, py) if py else {}
        return {'root': str(root or ''), 'python': py or '', 'needs_create': bool(root and not py),
                'needs_support': bool(py and not support.get('ipykernel', {}).get('available')),
                'support': support, 'active': ws.pool.default_python or ''}

    @rt('/runtime/support')
    async def runtime_support(req):
        from ..runtime_support import install_kernel_support
        d = await req.json()
        py = d.get('python') or ws.pool.default_python
        if not py: return _fail('choose a project interpreter first')
        try:
            result = await _off_loop(install_kernel_support, py)
            # The selected launcher becomes available immediately; no Leela restart needed.
            return result
        except Exception as e: return _fail(f'could not install project kernel support — {errstr(e)}')

    @rt('/runtime/create')
    async def runtime_create():
        "Create an explicit .venv for the project and install only its kernel transport."
        if not ws.fs.roots: return _fail('open a folder first')
        root, target = ws.fs.roots[0], ws.fs.roots[0]/'.venv'
        if target.exists(): return _fail(f'{target} already exists')
        def create():
            import subprocess, sys, venv
            if uv := shutil.which('uv'):
                subprocess.run([uv, 'venv', str(target)], check=True, env=os.environ.copy())
            else: venv.EnvBuilder(with_pip=True).create(target)
            py = target/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            from ..runtime_support import install_kernel_support
            install_kernel_support(py)
            return str(py)
        try: py = await _off_loop(create)
        except Exception as e: return _fail(f'could not create .venv — {errstr(e)}')
        ws.pool.choose(python=py)
        return {'ok': True, 'python': py}

    # -- files -------------------------------------------------------------
    @rt('/tree')
    def tree(path: str):
        try:
            state = _git_tree_state(ws)
            return tuple(_tree_node(e, state) for e in ws.fs.ls(path))
        except Exception as e: return Div(errstr(e), cls='lee-err')

    @rt('/files/panel')
    def files_panel():
        "Refresh only the file pane; the client restores expansion, selection and scroll."
        return _files_panel(ws)

    @rt('/fs/add_root')
    def add_root(path: str):
        try: ws.add_root(path); ws.save()
        except Exception as e: return _fail(str(e))
        return _shell(ws, gate)

    @rt('/fs/add-root')
    async def add_root_json(req):
        "Add a root without rebuilding the editor, model controls and every other pane."
        d = await req.json()
        try: ws.add_root(d.get('path') or ''); ws.save()
        except Exception as e: return _fail(e)
        return {'ok': True}

    @rt('/fs/browse')
    def fs_browse(path: str = ''):
        "Directories for the in-app folder picker. Files are intentionally never exposed here."
        try:
            p = Path(path or Path.home()).expanduser().resolve()
            if not p.is_dir(): raise NotADirectoryError(str(p))
            dirs = sorted((x for x in p.iterdir() if x.is_dir() and not x.name.startswith('.')),
                          key=lambda x: x.name.lower())
            parent = p.parent if p.parent != p else None
            return {'path': str(p), 'parent': str(parent) if parent else '',
                    'dirs': [{'name': x.name, 'path': str(x)} for x in dirs]}
        except Exception as e: return _fail(e)

    @rt('/fs/new')
    async def fs_new(req):
        "Create a file or folder. `kind` is 'file' or 'dir'."
        d = await req.json()
        parent, name, kind = d.get('parent') or '', d.get('name') or '', d.get('kind', 'file')
        if not name: return _fail('name required')
        try:
            target = Path(parent)/name
            e = ws.fs.mkdir(target) if kind == 'dir' else ws.create_document(target)
            if kind != 'dir': ws.journal.record(f'Create {name}', [(e.path, None, Path(e.path).read_text())], kind='create')
            return {'ok': True, 'entry': e.dict()}
        except Exception as e: return _fail(e)

    @rt('/fs/rename')
    async def fs_rename(req):
        d = await req.json()
        try:
            old = ws.fs._check(d['path'], must_exist=True)
            before = old.read_text(encoding='utf-8', errors='replace') if old.is_file() else None
            entry = ws.fs.rename(old, d['name'])
            if before is not None: ws.journal.record(f'Rename {old.name} to {entry.name}', [(old, before, None), (entry.path, None, before)], kind='rename')
            return {'ok': True, 'entry': entry.dict()}
        except Exception as e: return _fail(e)

    @rt('/fs/remove-root')
    async def fs_remove_root(req):
        "Remove an open root from the workspace without touching anything on disk."
        d = await req.json()
        try:
            ws.drop_root(d['path']); ws.save()
            return {'ok': True}
        except Exception as e: return _fail(e)

    @rt('/fs/delete')
    async def fs_delete(req):
        d = await req.json()
        try:
            p = ws.fs._check(d['path'], must_exist=True)
            before = p.read_text(encoding='utf-8', errors='replace') if p.is_file() else None
            ws.fs.delete(p)
            if before is not None: ws.journal.record(f'Delete {p.name}', [(p, before, None)], kind='delete')
            if (i := ws.find(d['path'])) is not None: ws.close(i)
            return {'ok': True}
        except Exception as e: return _fail(e)

    @rt('/fs/find')
    def fs_find(q: str = '', limit: int = 200):
        "Quick-open: fuzzy match over every file in the open folders, best match first."
        hits = fuzzy_rank(q, ws.fs.walk(), key=str, limit=limit)
        return {'hits': [{'path': str(p), 'name': p.name, 'lang': lang_for(p) or ''} for p in hits]}

    # -- tabs --------------------------------------------------------------
    # Tab routes swap only the tab bar, never the whole shell. Re-rendering everything
    # for a tab switch would collapse the file tree, drop the exec editor and reset the
    # variable panel -- the client re-mounts just the editor when #tabbar changes.
    @rt('/tab/open')
    def tab_open(path: str):
        try:
            ws.open(path)
            # Notebook tabs own kernels by default. A manually watched app belongs to the
            # tab it was chosen from; changing tabs restores the new tab's own runtime.
            ws.watch_env(None)
            ws.save()
        except Exception as e: return Div(errstr(e), cls='lee-err')
        return _tab_bar(ws)

    @rt('/tab/select')
    def tab_select(i: int):
        ws.activate(i)
        ws.watch_env(None)
        return _tab_bar(ws)

    @rt('/tab/close')
    async def tab_close(i: int):
        key = ws.kernel_key(ws.tabs[i]) if 0 <= i < len(ws.tabs) else None
        private = bool(0 <= i < len(ws.tabs) and ws.tabs[i].private_kernel)
        ws.close(i); ws.watch_env(None); ws.save()
        if private and key: await ws.pool.close(key)
        return _tab_bar(ws)

    @rt('/tab/new')
    def tab_new(kind: str = 'notebook'):
        ws.new_scratch(kind)
        ws.watch_env(None)
        return _tab_bar(ws)

    def _disk_version(path):
        "A cheap browser-watch token; changes whenever the active file is replaced or written."
        if not path: return ''
        try:
            s = Path(path).stat()
            return f'{s.st_mtime_ns}:{s.st_size}'
        except OSError: return 'missing'

    @rt('/tab/state')
    def tab_state(path: str = ''):
        "Everything needed to mount the active tab, or an open tab addressed by absolute path."
        t=next((x for x in ws.tabs if x.path==str(Path(path).expanduser().resolve())),None) if path else ws.tab
        if t is None: return {'kind': None}
        if t.kind == 'notebook':
            key = t.path or t.title
            try:
                # The in-memory document owns unsaved outputs and running state. Reloading
                # from disk on every tab switch erased both while work was still in flight.
                nb = _docs.get(key)
                if nb is None: nb = Notebook.load(t.path) if t.path else Notebook.blank()
            except Exception as e: return {'kind': 'error', 'error': errstr(e)}
            _docs[key] = nb
            return {'kind': 'notebook', 'path': t.path, 'title': t.title, 'dirty': t.dirty,
                    'disk_version': _disk_version(t.path), 'cells': [c.dict() for c in nb.cells]}
        try:
            key = t.path or t.title
            text = _buffers[key] if key in _buffers else (ws.fs.read(t.path) if t.path else '')
        except Exception as e: return {'kind': 'error', 'error': errstr(e)}
        return {'kind': 'text', 'path': t.path, 'title': t.title, 'lang': t.lang or '',
                'disk_version': _disk_version(t.path), 'text': text}

    @rt('/editor/format')
    async def editor_format(req):
        "Format without writing; the browser reviews and saves the returned text."
        d = await req.json(); text = str(d.get('text') or ''); lang = d.get('lang') or ''
        if len(text) > 2_000_000: return _fail('formatter input is larger than 2 MB')
        try:
            if lang == 'json':
                formatted = json.dumps(json.loads(text), indent=2, ensure_ascii=False) + '\n'
            elif lang == 'python':
                from ..kernels import project_python
                python = ws.pool.default_python or project_python(ws.fs.roots) or sys.executable
                cwd = str(ws.fs.roots[0]) if ws.fs.roots else None
                def format_python():
                    choices = [[str(python), '-m', 'ruff', 'format', '-'], [str(python), '-m', 'black', '-q', '-']]
                    failures=[]
                    for cmd in choices:
                        result=subprocess.run(cmd,input=text,text=True,capture_output=True,cwd=cwd,timeout=30)
                        if result.returncode == 0: return result.stdout
                        failures.append(result.stderr.strip())
                    raise RuntimeError('install ruff or black in the project environment · ' + ' · '.join(x for x in failures if x))
                formatted = await _off_loop(format_python)
            else: return _fail(f'no formatter configured for {lang or "this file"}')
            return {'ok': True, 'text': formatted}
        except Exception as e: return _fail(e)

    @rt('/editor/packages')
    def editor_packages(path: str):
        "Installed-version annotations for a workspace pyproject.toml."
        try:
            p = ws.fs._check(path, must_exist=True)
            if p.name != 'pyproject.toml': return {'packages': [], 'summary': {}}
            python = ws.pool.default_python or sys.executable
            rows = _project_package_rows(p, python)
            return {'packages': rows, 'summary': {
                'total': len(rows), 'installed': sum(r['installed'] is not None for r in rows),
                'missing': sum(r['installed'] is None for r in rows),
                'mismatch': sum(r['compatible'] is False for r in rows),
                'python': str(python),
            }}
        except Exception as e: return _fail(e)

    @rt('/tab/disk')
    def tab_disk(path: str = ''):
        "Current on-disk text for the explicit conflict/merge editor."
        try:
            p = ws.fs._check(path or (ws.tab.path if ws.tab else ''), must_exist=True)
            if p.suffix == '.ipynb':
                return {'path': str(p), 'kind': 'notebook', 'cells': [c.dict() for c in Notebook.load(p).cells],
                        'disk_version': _disk_version(p)}
            return {'path': str(p), 'kind': 'text', 'text': ws.fs.read(p),
                    'disk_version': _disk_version(p)}
        except Exception as e: return _fail(e)

    @rt('/tab/watch')
    def tab_watch():
        "Pollable disk identity for the open document; no file contents cross the wire."
        t = ws.tab
        return {'path': t.path if t else '', 'disk_version': _disk_version(t.path) if t else ''}

    @rt('/tab/reload')
    async def tab_reload(req):
        """Drop server-side editor caches so the next state read comes straight from disk.

        Agent edits happen outside the open document objects. Without this invalidation a
        browser remount could faithfully redisplay the stale notebook it had cached.
        """
        d = await req.json()
        t = ws.tab
        if t is None or (d.get('path') and d.get('path') != t.path): return _fail('that tab is no longer active')
        key = t.path or t.title
        _docs.pop(key, None); _buffers.pop(key, None); _buffer_bases.pop(key, None)
        t.dirty = False
        return {'ok': True, 'path': t.path}

    @rt('/tab/buffer')
    async def tab_buffer(req):
        "Persist an editor buffer in memory so a tab switch cannot discard unsaved typing."
        d = await req.json()
        path, kind, text = d.get('path') or d.get('title') or '', d.get('kind'), d.get('text', '')
        tab = next((t for t in ws.tabs if (t.path or t.title) == path), None)
        if tab is None: return _fail('that tab is no longer open')
        _buffer_bases.setdefault(path, str(d.get('base_disk_version') or _disk_version(tab.path)))
        if kind == 'notebook':
            nb = _docs.get(path)
            i = int(d.get('i', -1))
            if nb is not None and 0 <= i < len(nb) and (not d.get('id') or nb[i].id == d.get('id')):
                nb[i].source = text; nb.dirty = True
        else: _buffers[path] = text
        tab.dirty = True
        return {'ok': True}

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

    @rt('/lsp/status')
    def lsp_status():
        return {'provider':'pyright', 'available':ws.lsp.available, 'alive':ws.lsp.alive, 'note':ws.lsp.note}

    @rt('/lsp/symbols')
    async def lsp_symbols(req):
        d=await req.json()
        try:
            rows=await _off_loop(ws.lsp.request,'textDocument/documentSymbol',d.get('path'),d.get('text',''),None,0,None,8)
            return {'symbols':rows or []}
        except Exception as e:return _fail(e)

    @rt('/lsp/hover')
    async def lsp_hover(req):
        d=await req.json()
        try:return {'hover':await _off_loop(ws.lsp.request,'textDocument/hover',d.get('path'),d.get('text',''),d.get('line',0),d.get('character',0))}
        except Exception as e:return _fail(e)

    @rt('/lsp/inlay-hints')
    async def lsp_inlay_hints(req):
        d=await req.json(); text=d.get('text',''); lines=text.splitlines()
        end={'line':max(0,len(lines)-1),'character':len(lines[-1]) if lines else 0}
        try:
            rows=await _off_loop(ws.lsp.request,'textDocument/inlayHint',d.get('path'),text,None,0,
                                 {'range':{'start':{'line':0,'character':0},'end':end}},8)
            return {'hints':rows or []}
        except Exception as e:return _fail(e)

    @rt('/lsp/rename')
    async def lsp_rename(req):
        "Preview or atomically apply Pyright's workspace rename edit within open roots."
        from urllib.parse import unquote, urlparse
        d=await req.json()
        try:
            edit=await _off_loop(ws.lsp.request,'textDocument/rename',d.get('path'),d.get('text',''),
                                 d.get('line',0),d.get('character',0),{'newName':d.get('newName','')},12)
            changes=(edit or {}).get('changes') or {}
            previews=[]
            for uri, edits in changes.items():
                path=unquote(urlparse(uri).path); p=ws.fs._check(path,must_exist=True); before=ws.fs.read(p)
                source=before; ls=source.splitlines(keepends=True) or ['']; starts=[];at=0
                for line in ls:starts.append(at);at+=len(line)
                def offset(pos):
                    row=max(0,min(int(pos.get('line',0)),len(ls)-1));return starts[row]+min(int(pos.get('character',0)),len(ls[row].rstrip('\r\n')))
                replacements=sorted([(offset(x['range']['start']),offset(x['range']['end']),x.get('newText','')) for x in edits],reverse=True)
                after=source
                for start,end,new in replacements:after=after[:start]+new+after[end:]
                previews.append({'path':str(p),'before':before,'after':after,'edits':len(edits)})
            if d.get('apply'):
                operation=[]
                for row in previews:ws.fs.write(row['path'],row['after']);operation.append((row['path'],row['before'],row['after']))
                ws.journal.record(f"Rename to {d.get('newName','')}",operation,kind='rename-symbol')
            return {'ok':True,'applied':bool(d.get('apply')),'files':previews}
        except Exception as e:return _fail(e)

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

    @rt('/inspect')
    async def inspect_route(req):
        "Signature and docstring for the name at the cursor, from the object that is actually loaded."
        d = await req.json()
        k = await _k()
        txt = await k.inspect_obj(d.get('code', ''), int(d.get('pos', 0)), int(d.get('detail', 0))) if k else ''
        return {'text': txt, 'note': '' if txt else 'the kernel knows nothing about that name'}

    # -- variables (proxied from the kernel's own inspector) ---------------
    @rt('/vars/eval')
    async def vars_eval(req):
        "Evaluate a Python expression from the Variables filter and return an expandable result."
        d = await req.json()
        code, scope = (d.get('code') or '').strip(), d.get('scope', 'live')
        if not code: return _fail('enter a Python expression after =')
        k = await _k()
        path = '/agent/api/exec' if scope == 'agent' else '/api/exec'
        params = {'code': code, 'scope': 'overlay' if scope == 'agent' else 'global'}
        r = await k.api(path, params, timeout=120) if k else None
        if r is None: return _fail('no runtime answered')
        return {'ok': bool(r.get('ok')), 'error': r.get('error'), 'stdout': r.get('stdout') or '',
                'result': r.get('result'), 'scope': scope}

    @rt('/vars')
    async def vars_route(profile: str = 'minimal', sort: str = 'recent', scope: str = 'live'):
        base = '/agent/api/rows' if scope == 'agent' else '/api/rows'
        runtime = await _k()
        r = await runtime.api(base, {'profile': profile, 'sort': sort}, 15) if runtime else None
        identity = ((getattr(runtime, 'base', None) or
                     (f'kernel:{ws.kernel_key()}' if runtime is not None else 'none')) + f':{scope}')
        problem = (getattr(runtime, 'boot_error', '') or getattr(runtime, 'last_api_error', '') or
                   'no dhrishti inspector') if not r else ''
        return {**(r or {'groups': [], 'error': problem}), 'runtime': identity,
                'inspector': 'dhrishti', 'python': str(getattr(runtime, 'python', '') or ''),
                'cwd': str(getattr(runtime, 'cwd', '') or '')}

    @rt('/vars/expand')
    async def vars_expand(accessor: str, offset: int = 0, scope: str = 'live'):
        base = '/agent/api/expand' if scope == 'agent' else '/api/expand'
        return JSONResponse(await _api(base, {'accessor': accessor, 'offset': offset}) or [])

    @rt('/vars/grid')
    async def vars_grid(accessor: str, roff: int = 0, coff: int = 0, scope: str = 'live'):
        base = '/agent/api/grid' if scope == 'agent' else '/api/grid'
        return JSONResponse(await _api(base, {'accessor': accessor, 'roff': roff, 'coff': coff}))

    @rt('/vars/set')
    async def vars_set(req):
        d = await req.json()
        r = await _api('/api/set', {'accessor': d['accessor'], 'expr': d['expr']})
        return r or {'ok': False, 'error': 'no kernel inspector'}

    @rt('/vars/promote')
    async def vars_promote(accessor: str):
        r = await _api('/api/promote', {'accessor': accessor})
        return r or {'ok': False, 'error': 'no kernel inspector'}

    # -- code search -------------------------------------------------------
    @rt('/search')
    async def search_route(q: str = '', regex: bool = False, limit: int = 60, mode: str = 'rg'):
        "Ripgrep by default; every blocking search backend runs off the web event loop."
        if mode not in ('context', 'repo', 'env', 'all', 'rg', 'symbols', 'fts', 'ann'): return _fail(f'unknown search mode {mode!r}')
        hits = await _off_loop(ws.search.search, q, limit=limit, regex=regex, mode=mode)
        return _found(ws, hits)

    @rt('/code/status')
    async def code_status():
        return await _off_loop(ws.search.status)

    @rt('/code/package-api')
    async def code_package_api(package: str = ''):
        rows = await _off_loop(ws.search.package_api, package)
        return {'package': package, 'note': ws.search.note, 'symbols': rows}

    @rt('/outline')
    async def outline_route(path: str):
        return {'symbols': [h.dict() for h in await _off_loop(ws.search.symbols, path)]}

    @rt('/code/definition')
    async def code_definition(name: str = '', path: str = '', limit: int = 30):
        return _found(ws, await _off_loop(ws.search.definitions, name, path, limit))

    @rt('/code/usages')
    async def code_usages(name: str = '', limit: int = 200):
        return _found(ws, await _off_loop(ws.search.usages, name, limit))

    @rt('/code/sync')
    async def code_sync():
        try: return await ws.search.async_sync(True, True)
        except Exception as e: return _fail(e)

    @rt('/similar')
    async def similar_route(path: str, line: int = 1, mode: str = 'cluster', limit: int = 25):
        """Code like the function at `path:line`.

        `mode=cluster` answers "the family this belongs to" via usearch clustering;
        `mode=knn` answers "the N closest things". The first is usually what you want
        when hunting for every place a pattern was already implemented.
        """
        fn = ws.search.peers if mode == 'cluster' else ws.search.similar
        return _found(ws, await _off_loop(fn, path, line, limit=limit))

    @rt('/clusters')
    async def clusters_route(limit: int = 40):
        "An ANN clustering of the whole indexed corpus -- a map of the codebase by shape."
        cs = await _off_loop(ws.search.clusters)
        return {'note': ws.search.note, 'clusters': [c.dict() for c in cs[:limit]]}

    # -- working directory & git ------------------------------------------
    def _repo():
        cwd = ws.cwd_for()
        if cwd is None: raise GitError('open a folder first')
        return GitRepo.at(cwd)

    def _git_paths(values):
        "Pathspecs accepted from the browser, constrained to repository-relative files."
        out = []
        for value in values or ():
            p = Path(str(value))
            if p.is_absolute() or '..' in p.parts: raise GitError(f'invalid repository path: {value}')
            out.append(str(p))
        if not out: raise GitError('select at least one changed file')
        return out

    @rt('/workspace/info')
    def workspace_info():
        "The current multi-root project plus independently hosted workspace windows."
        active = ws.fs.root_of(ws.tab.path) if ws.tab and ws.tab.path else (ws.fs.roots[0] if ws.fs.roots else None)
        sites = workspace_catalog() if callable(workspace_catalog) else list(workspace_catalog or ())
        return {'active': str(active or ''),
                'roots': [{'path': str(root), 'name': root.name} for root in ws.fs.roots],
                'workspaces': sites}

    @rt('/cwd')
    def cwd_info():
        t = ws.tab
        return {'cwd': str(ws.cwd_for() or ''), 'explicit': bool(t and t.cwd),
                'root': str(ws.fs.root_of(t.path) if t and t.path else (ws.fs.roots[0] if ws.fs.roots else ''))}

    @rt('/cwd/set')
    async def cwd_set(req):
        d = await req.json()
        try:
            p = ws.set_cwd(d.get('path'))
            ws.save()
            return {'ok': True, 'cwd': str(p), 'explicit': bool(ws.tab and ws.tab.cwd)}
        except Exception as e: return _fail(e)

    @rt('/git/info')
    async def git_info():
        try: return await _off_loop(lambda: _repo().info())
        except Exception as e: return _fail(e)

    @rt('/git/action')
    async def git_action(req):
        """Perform one explicit Git mutation and return the one refreshed snapshot.

        The browser renders this response directly; it must not follow each mutation with
        several duplicate status requests. Destructive operations remain confirmed by the
        client and Git itself remains the final safety check.
        """
        d = await req.json()
        try:
            def act():
                repo, op = _repo(), str(d.get('op') or '')
                if op == 'stage': repo.stage(_git_paths(d.get('paths')))
                elif op == 'unstage': repo.unstage(_git_paths(d.get('paths')))
                elif op == 'discard': repo.discard(_git_paths(d.get('paths')))
                elif op == 'resolve_conflict': repo.resolve_conflict(_git_paths([d.get('path')])[0], d.get('choice') or '')
                elif op == 'apply_patch': repo.apply_patch(d.get('patch') or '', bool(d.get('staged', True)), bool(d.get('reverse')))
                elif op == 'checkout': repo.checkout(d.get('branch') or '')
                elif op == 'create': repo.create(d.get('branch') or '', d.get('start') or 'HEAD')
                elif op == 'rename_branch': repo.rename_branch(d.get('branch') or '', d.get('name') or '')
                elif op == 'set_upstream': repo.set_upstream(d.get('branch') or '', d.get('upstream') or '')
                elif op == 'unset_upstream': repo.unset_upstream(d.get('branch') or '')
                elif op == 'delete': repo.delete(d.get('branch') or '', bool(d.get('force')))
                elif op == 'delete_remote': repo.delete_remote(d.get('remote') or 'origin', d.get('branch') or '')
                elif op == 'commit': repo.commit(d.get('message') or '', bool(d.get('amend')))
                elif op == 'fetch': repo.fetch(d.get('remote') or '', bool(d.get('prune', True)))
                elif op == 'pull': repo.pull()
                elif op == 'push': repo.push(bool(d.get('publish')), bool(d.get('force_with_lease')))
                elif op == 'stash': repo.stash(d.get('message') or '')
                elif op == 'stash_pop': repo.stash_pop(d.get('ref') or 'stash@{0}')
                elif op == 'stash_apply': repo.stash_apply(d.get('ref') or 'stash@{0}')
                elif op == 'stash_drop': repo.stash_drop(d.get('ref') or 'stash@{0}')
                elif op == 'merge': repo.merge(d.get('branch') or '')
                elif op == 'rebase': repo.rebase(d.get('branch') or '')
                elif op == 'cherry_pick': repo.cherry_pick(d.get('ref') or '')
                elif op == 'revert': repo.revert(d.get('ref') or '')
                elif op == 'reset': repo.reset(d.get('ref') or 'HEAD', d.get('mode') or 'mixed')
                elif op.startswith('operation_'): repo.operation_action(op.removeprefix('operation_'))
                elif op == 'abort_merge': repo.operation_action('abort')
                elif op == 'abort_rebase': repo.operation_action('abort')
                elif op == 'tag': repo.tag(d.get('name') or '', d.get('message') or '', d.get('ref') or 'HEAD')
                elif op == 'delete_tag': repo.delete_tag(d.get('name') or '', d.get('remote') or '')
                elif op == 'add_remote': repo.add_remote(d.get('name') or '', d.get('url') or '')
                elif op == 'set_remote': repo.set_remote(d.get('name') or '', d.get('url') or '', bool(d.get('push')))
                elif op == 'remove_remote': repo.remove_remote(d.get('name') or '')
                elif op == 'add_worktree': repo.add_worktree(d.get('path') or '', d.get('branch') or '', bool(d.get('create')))
                elif op == 'remove_worktree': repo.remove_worktree(d.get('path') or '', bool(d.get('force')))
                else: raise GitError(f'unknown Git action: {op}')
                return repo.info()
            return await _off_loop(act)
        except Exception as e: return _fail(e)

    @rt('/git/history')
    async def git_history(limit: int = 100, skip: int = 0, query: str = '', ref: str = '--all', path: str = ''):
        try:
            clean = _git_paths([path])[0] if path else ''
            return {'commits': await _off_loop(_repo().history, limit, skip, query, ref, clean)}
        except Exception as e: return _fail(e)

    @rt('/git/reflog')
    async def git_reflog(limit: int = 100):
        try: return {'entries': await _off_loop(_repo().reflog, limit)}
        except Exception as e: return _fail(e)

    @rt('/git/conflict')
    async def git_conflict(path: str = ''):
        try: return await _off_loop(_repo().conflict_versions, _git_paths([path])[0])
        except Exception as e: return _fail(e)

    @rt('/git/commit')
    async def git_commit_detail(ref: str = 'HEAD'):
        try: return await _off_loop(_repo().commit_detail, ref)
        except Exception as e: return _fail(e)

    @rt('/git/compare')
    async def git_compare(left: str = 'HEAD', right: str = ''):
        try:
            if not right: raise GitError('choose two refs to compare')
            return await _off_loop(_repo().compare, left, right)
        except Exception as e: return _fail(e)

    @rt('/git/blame')
    async def git_blame(path: str = '', start: int = 1, end: int = 0):
        try: return {'lines': await _off_loop(_repo().blame, _git_paths([path])[0], start, end)}
        except Exception as e: return _fail(e)

    @rt('/git/resources')
    async def git_resources():
        try:
            repo = _repo()
            worktrees, submodules = await __import__('asyncio').gather(
                _off_loop(repo.worktrees), _off_loop(repo.submodules))
            return {'worktrees': worktrees, 'submodules': submodules}
        except Exception as e: return _fail(e)

    @rt('/git/diff')
    async def git_diff(path: str = '', staged: bool = False):
        try:
            clean = _git_paths([path])[0]
            view = await _off_loop(lambda: _repo().diff_view(clean, staged))
            return {'path': path, 'staged': staged, **view}
        except Exception as e: return _fail(e)

    @rt('/git/file')
    async def git_file(path: str = ''):
        try:
            repo = _repo()
            absolute = ws.fs._check(path, must_exist=False)
            try: relative = str(absolute.relative_to(repo.root))
            except ValueError: raise GitError('the active file is outside this repository')
            return await _off_loop(repo.file_changes, relative)
        except Exception as e: return _fail(e)

    # -- terminal ----------------------------------------------------------
    @rt('/term/info')
    def term_info():
        """What the client needs to open a terminal, including the token.

        The token is handed out over this same-origin route and nowhere else. That is the
        whole point: a websocket is not bound by the same-origin policy, so any page the
        user visits can reach `127.0.0.1` -- only one that can *read* this response is the IDE.
        """
        try: lazygit_argv(); git, git_why = True, ''
        except LazygitMissing as e: git, git_why = False, str(e)
        return {'enabled': gate.enabled, 'why': gate.why, 'token': gate.token if gate.enabled else '',
                'cwd': str(_term_cwd() or ''), 'lazygit': git, 'lazygit_why': git_why,
                'open': [t.state() for t in ws.terms.all()]}

    @rt('/term/close')
    def term_close(id: str = 'shell'):
        ws.terms.close(id)
        return {'ok': True}

    # -- research ----------------------------------------------------------
    @rt('/research/search')
    async def research_search(q: str = '', n: int = 15):
        "Web search: titles and urls only, so it stays fast enough to drive from a prompt box."
        n = min(50, max(1, int(n)))
        docs = await _off_loop(ws.research.search, q, n)
        return {'note': ws.research.note, 'docs': [d.dict() for d in docs]}

    @rt('/research/read')
    async def research_read(url: str = '', remember: bool = True):
        "One page (or GitHub file, or arxiv paper) as markdown."
        d = await _off_loop(ws.research.read, url, None, remember)
        return {'note': ws.research.note, 'doc': d.dict() if d else None}

    @rt('/research/dig')
    async def research_dig(q: str = '', n: int = 5, remember: bool = True):
        "Search and read the top results into one cited digest."
        n = min(12, max(1, int(n)))
        docs, digest = await _off_loop(ws.research.dig, q, n, MAX_DOC_CHARS, remember)
        return {'note': ws.research.note, 'digest': digest, 'docs': [d.dict() for d in docs]}

    # -- durable research memory --------------------------------------------
    @rt('/memory/info')
    async def memory_info():
        status = await _off_loop(ws.memory.status)
        docs = await _off_loop(ws.memory.documents, 80)
        return {**status, 'items': docs}

    @rt('/memory/forget')
    async def memory_forget(req):
        d = await req.json(); doc_id = str(d.get('id') or '')
        ok = await _off_loop(ws.memory.forget, doc_id)
        if ok:
            for target, ids in ws.agent_memory_selection.items():
                ws.agent_memory_selection[target] = [value for value in ids if value != doc_id]
            ws.save()
            for assistant in (ws._ai, ws._inline_ai):
                if assistant is not None: assistant.refresh()
        return {'ok': ok, 'note': ws.memory.note}

    @rt('/memory/purge')
    async def memory_purge(req):
        d = await req.json()
        ids = d.get('ids')
        if ids is not None and not isinstance(ids, list): return _fail('ids must be a list')
        removed_ids = ({str(value) for value in ids} if ids is not None else
                       {str(note['id']) for note in await _off_loop(ws.memory.agent_notes)})
        removed = await _off_loop(ws.memory.purge, ids)
        for target, selected in ws.agent_memory_selection.items():
            ws.agent_memory_selection[target] = [value for value in selected if value not in removed_ids]
        ws.save()
        for assistant in (ws._ai, ws._inline_ai):
            if assistant is not None: assistant.refresh()
        return {'ok': True, 'removed': removed, 'note': ws.memory.note}

    @rt('/memory/search')
    async def memory_search(q: str = '', limit: int = 8):
        rows = await _off_loop(ws.memory.search, q, min(30, max(1, int(limit))))
        return {'note': ws.memory.note, 'results': rows}

    @rt('/memory/toc')
    async def memory_toc(doc: str = '', depth: int = 3):
        rows = await _off_loop(ws.memory.toc, doc or None, depth)
        return {'note': ws.memory.note, 'documents': rows}

    @rt('/memory/read')
    async def memory_read(node: str = ''):
        return {'note': ws.memory.note, 'section': await _off_loop(ws.memory.read, node)}

    @rt('/memory/clusters')
    async def memory_clusters(limit: int = 20):
        return await _off_loop(ws.memory.clusters, min(50, max(1, int(limit))))

    @rt('/research/save')
    async def research_save(req):
        "Keep a fetched page: markdown by default, or a runnable notebook with kind='notebook'."
        d = await req.json()
        try:
            if d.get('kind') == 'notebook':
                e = await _off_loop(ws.research.save_notebook, d['url'], d.get('path'))
            else:
                from ..research import Doc
                doc = Doc(title=d.get('title') or '', url=d.get('url') or '', text=d.get('text') or '')
                e = await _off_loop(ws.research.save, doc, d.get('path'))
            if e is None: return _fail(ws.research.note)
            return {'ok': True, 'entry': e.dict(), 'note': ws.research.note}
        except Exception as e: return _fail(e)

    # -- live envs ---------------------------------------------------------
    @rt('/envs')
    def envs_route():
        """Everything the variable panel could point at, and what it is pointing at now.

        A process only appears here if it has an inspector in it. That is the whole answer
        to "will you pick up the uvicorn I started in a terminal": not unless it says
        `dhrishti.serving.serve()`, or leela started it from a run configuration.
        """
        return {'envs': ws.envs(), 'watching': ws.env_base,
                'hint': 'import dhrishti.serving as ds; ds.serve(name="api")'}

    @rt('/envs/watch')
    async def envs_watch(req):
        d = await req.json()
        return {'ok': True, 'watching': ws.watch_env(d.get('base'))}

    # -- run configurations & dev servers ----------------------------------
    @rt('/runs')
    def runs_route():
        "The project's run configurations, plus one for the open file so the picker is never empty."
        t = ws.tab
        here = ws.runs.for_file(t.path) if (t is not None and (t.path or '').endswith('.py')) else None
        names = {r.name for r in ws.runs.runs}
        return {'runs': [r.dict() for r in ws.runs.runs],
                'here': here.dict() if (here and here.name not in names) else None,
                'path': str(ws.runs.path or ''), 'note': ws.runs.note,
                'servers': [s.state() for s in ws.dev.all()]}

    @rt('/runs/save')
    async def runs_save(req):
        "Write the configurations file, creating it from a template when there is none yet."
        d = await req.json()
        try:
            if (text := d.get('text')) is not None:
                json.loads(text)                      # refuse to write a file we could not read back
                p = ws.runs.path
                if p is None: return _fail('open a folder first')
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            ws.runs.load()
        except Exception as e: return _fail(e)
        return {'ok': True, 'path': str(ws.runs.path or ''), 'note': ws.runs.note,
                'runs': [r.dict() for r in ws.runs.runs]}

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

    @rt('/dev/list')
    def dev_list(): return {'servers': [s.state() for s in ws.dev.all()]}

    @rt('/dev/start')
    async def dev_start(path: str = '', name: str = ''):
        """Start a run configuration, or a file, under a live inspector.

        The inspector is in the process the command runs in -- that is what makes its
        module namespace watchable while it serves. `name` picks a configuration; `path`
        runs a file directly.
        """
        try:
            s = await ws.run(name or path)
            return {'ok': s.alive, **s.state(), 'log': s.tail(20)}
        except Exception as e:
            return _fail(e)

    @rt('/dev/stop')
    async def dev_stop(path: str):
        await ws.dev.stop(path)
        return {'ok': True}

    @rt('/dev/log')
    def dev_log(path: str, n: int = 60):
        s = ws.dev.get(path)
        return {'log': s.tail(n) if s else [], **(s.state() if s else {})}

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
    @rt('/kernel/interrupt')
    async def k_interrupt():
        k = ws.runtime_peek()
        if k is None: return _fail('no running kernel')
        if hasattr(k, 'stop'): return await k.stop(timeout=2.0)
        await k.interrupt()
        return {'ok': True, 'forced': False, 'note': 'interrupt sent'}

    @rt('/nb/interrupt')
    async def nb_interrupt(req):
        "Interrupt one exact running cell, force-restarting its managed kernel if needed."
        d = await req.json()
        item = running_cells.get((d.get('path') or '', d.get('id') or ''))
        if item is None: return _fail('that cell is not running')
        k, _task = item
        if not hasattr(k, 'stop'): return _fail('this external runtime cannot be stopped safely')
        return await k.stop(timeout=2.0)

    @rt('/kernel/restart')
    async def k_restart():
        k = ws.runtime_peek()
        if k: await k.restart()
        _previous_runs()
        return {'ok': True, 'base': k.base if k else None}

    @rt('/kernel/info')
    async def k_info():
        k = await _k()
        return {'alive': bool(k and k.alive), 'base': k.base if k else None,
                'pid': k.pid if k else None,
                'key': getattr(k, 'name', '') or Path(ws.kernel_key()).name or 'kernel',
                'boot_error': k.boot_error if k else None,
                'api_error': getattr(k, 'last_api_error', '') if k else '',
                'cwd': str(ws.cwd_for() or ''),
                'tabs': [{'running': t.running, 'dirty': t.dirty} for t in ws.tabs]}

    @rt('/kernel/options')
    def k_options():
        "What the kernel picker shows: the launchers, the interpreters, and what is running."
        return ws.kernel_options()

    @rt('/kernel/cwd')
    async def k_cwd(req):
        "Set this tab's working directory and restart its kernel so the process adopts it."
        d = await req.json()
        t = ws.tab
        if t is None: return _fail('no active tab')
        raw = (d.get('cwd') or '').strip()
        try:
            cwd = ws.fs._check(raw, must_exist=True) if raw else None
            if cwd is not None and not cwd.is_dir(): return _fail(f'{cwd} is not a directory')
        except Exception as e: return _fail(e)
        key = ws.kernel_key(t)
        ws.watch_env(None)
        t.cwd = str(cwd) if cwd else ''
        await ws.pool.close(key)
        k = await ws.kernel(t)
        _previous_runs()
        ws.save()
        return {'ok': True, 'cwd': str(ws.cwd_for(t) or ''), 'base': k.base if k else None}

    @rt('/kernel/select')
    async def k_select(req):
        """Choose a launcher and/or an interpreter, and start the kernel on it.

        This restarts, and restarting loses the namespace -- so the client says so before
        it posts, rather than this route deciding on the user's behalf that it was fine.
        """
        d = await req.json()
        try:
            o = await ws.set_kernel(kind=d.get('kind'),
                                    python=d['python'] if 'python' in d else False,
                                    private=d.get('private'))
            # A shell cannot change its inherited VIRTUAL_ENV after it starts. Closing it
            # lets the client reopen immediately with the newly selected project runtime.
            ws.terms.close('shell')
            _previous_runs()
        except Exception as e: return _fail(e)
        return {'ok': True, **o}

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
