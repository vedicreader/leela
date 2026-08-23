"The notebook document: cells, outputs, the .ipynb on disk, and source spans."

from __future__ import annotations
import ast, time, uuid
from base64 import b64encode
from copy import deepcopy
from dataclasses import dataclass, field
from fastcore.all import first, L, Path, ifnone
from fastcore.nbio import read_nb, write_nb, new_nb, nb2str
from ... import Dictable
from ..runtime.kernels import output_text
import json

__all__ = ['CELL_TYPES', 'Cell', 'Notebook', 'cell_id', 'read_cells', 'source_spans',
           'cell_lines', 'cell_at', 'cell_of', 'media_output', 'media_outputs', 'assigned_lines', 'inline_values', 'cell_extras']

CELL_TYPES = ('code', 'markdown', 'prompt')

MAX_CONTEXT = None
MAX_CELL_OUT = None
CONTEXT_MODES = ('auto', 'keep', 'discard')
MAX_UNDO = 100

def cell_id(): return uuid.uuid4().hex[:8]

def media_output(m):
    "One `{'mime','data'}` a model generated, as the nbformat output that draws it."
    mime = m.get('mime') or 'image/png'
    b64 = b64encode(m.get('data') or b'').decode()
    if mime == 'image/png': return dict(output_type='display_data', data={'image/png': b64}, metadata={})
    tag = 'video controls' if mime.startswith('video/') else 'img'
    html = f'<{tag} src="data:{mime};base64,{b64}">' + ('</video>' if mime.startswith('video/') else '')
    return dict(output_type='display_data', data={'text/html': html}, metadata={})

def media_outputs(media): return [media_output(m) for m in (media or [])]

def _detached(cell):
    "A copy of `cell` with a fresh identity and no running state."
    n = deepcopy(cell)
    n.id, n.running, n.fresh = cell_id(), False, False
    return n

@dataclass
class Cell(Dictable):
    "One notebook cell. `outputs` are nbformat dicts exactly as the kernel sent them."
    source: str = ''
    cell_type: str = 'code'
    outputs: list = field(default_factory=list)
    execution_count: int | None = None
    execution_ms: float | None = None
    id: str = field(default_factory=cell_id)
    running: bool = False
    reply: str = ''
    calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    approval: dict | None = None
    context_mode: str = 'auto'
    fresh: bool = False
    def __post_init__(self):
        if self.context_mode not in CONTEXT_MODES: self.context_mode = 'auto'
    @property
    def text(self): return output_text(self.outputs)
    @property
    def has_error(self): return any(o.get('output_type') == 'error' for o in self.outputs)
    @property
    def is_prompt(self): return self.cell_type == 'prompt'
    @property
    def is_approval(self): return self.approval is not None
    def clear(self):
        self.outputs, self.execution_count, self.execution_ms, self.fresh = [], None, None, False
        self.reply, self.calls, self.usage = '', [], {}
        return self
    def nbcell(self):
        "This cell in nbformat v4 shape. nbformat has no prompt cell, so one is written as markdown with `leela` metadata."
        c = dict(cell_type=self.cell_type, source=self.source, metadata={}, id=self.id)
        meta = {} if self.context_mode == 'auto' else {'context': self.context_mode}
        if self.cell_type == 'code':
            c['outputs'] = list(self.outputs)
            c['execution_count'] = self.execution_count
            if self.execution_ms is not None: meta['execution_ms'] = round(self.execution_ms, 3)
        elif self.is_prompt:
            c['cell_type'] = 'markdown'
            meta.update(kind='prompt', reply=self.reply, calls=list(self.calls), usage=dict(self.usage))
            if self.outputs: meta['outputs'] = list(self.outputs)   # markdown cells have nowhere else to keep them
            if self.execution_ms is not None: meta['execution_ms'] = round(self.execution_ms, 3)
        elif self.approval is not None: meta.update(self.approval, kind='approval')
        if meta: c['metadata'] = {'leela': meta}
        return c
    @classmethod
    def from_nb(cls, c):
        src = c.get('source', '')
        if isinstance(src, list): src = ''.join(src)
        meta = (c.get('metadata') or {}).get('leela') or {}
        return cls(source=src, outputs=list(c.get('outputs') or meta.get('outputs') or []),
            id=str(c.get('id') or cell_id()),
            cell_type='prompt' if meta.get('kind') == 'prompt' else c.get('cell_type', 'code'),
            execution_count=c.get('execution_count'), execution_ms=meta.get('execution_ms'),
            reply=str(meta.get('reply') or ''), calls=list(meta.get('calls') or []), usage=dict(meta.get('usage') or {}),
            context_mode=str(meta.get('context') or 'auto'), approval=dict(meta) if meta.get('kind') == 'approval' else None)

class Notebook:
    "An open .ipynb: an ordered list of `Cell`s that can run against a `Kernel`."
    def __init__(self, cells=None, path=None):
        self.cells = L(ifnone(cells, [Cell()]))
        self.path = str(path) if path else ''
        self.dirty = False
        self._undo, self._redo = [], []
    def __len__(self): return len(self.cells)
    def __getitem__(self, i): return self.cells[i]
    @classmethod
    def load(cls, path):
        "Open an `.ipynb`. A zero-byte file (what `touch` leaves) is a new document, not a parse error."
        p = Path(path)
        if p.exists() and p.stat().st_size == 0: return cls.blank(path)
        nb = read_nb(str(path))
        cells = [Cell.from_nb(c) for c in nb['cells']] or [Cell()]
        return cls(cells, path)
    @classmethod
    def blank(cls, path=None): return cls([Cell()], path)
    def save(self, path=None, sandbox=None):
        "Write the notebook; `sandbox` confines the write to the open folders."
        p = str(path or self.path)
        if not p: raise ValueError('notebook has no path')
        nb = new_nb([c.nbcell() for c in self.cells])
        if sandbox is not None: sandbox.write(p, nb2str(nb))
        else: write_nb(nb, p)
        self.path, self.dirty = p, False
        return p
    def _snapshot(self, i=0): return dict(cells=deepcopy(list(self.cells)), dirty=self.dirty, index=i)
    def _checkpoint(self, i=0):
        self._undo.append(self._snapshot(i))
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
    def _restore(self, src, dst):
        if not src: return None
        snap = src.pop()
        dst.append(self._snapshot(snap['index']))
        del dst[:-MAX_UNDO]
        self.cells, self.dirty = L(deepcopy(snap['cells'])), snap['dirty']
        return max(0, min(snap['index'], len(self.cells) - 1))
    def undo(self):
        "Restore the notebook before its last structural operation; return the focus index."
        return self._restore(self._undo, self._redo)
    def redo(self):
        "Reapply the last undone structural operation; return the focus index."
        return self._restore(self._redo, self._undo)
    def insert(self, i, cell=None):
        self._checkpoint(i)
        c = cell or Cell()
        self.cells.insert(max(0, min(i, len(self.cells))), c)
        self.dirty = True
        return c
    def delete(self, i):
        "Remove a cell; a notebook always keeps at least one."
        if not (0 <= i < len(self.cells)): return None
        self._checkpoint(i)
        c = self.cells.pop(i)
        if not self.cells: self.cells.append(Cell())
        self.dirty = True
        return c
    def move(self, i, d):
        "Move a cell by `d` positions, shifting the cells between rather than swapping endpoints."
        j = i + d
        if not (0 <= i < len(self.cells) and 0 <= j < len(self.cells)): return i
        self._checkpoint(i)
        self.cells.insert(j, self.cells.pop(i))
        self.dirty = True
        return j
    def set_type(self, i, t):
        self._checkpoint(i)
        c = self.cells[i]
        c.cell_type = t
        if t != 'code': c.clear()
        self.dirty = True
        return c
    def cycle_type(self, i):
        "Advance a cell through `CELL_TYPES`."
        c = self.cells[i]
        if c.cell_type not in CELL_TYPES: return self.set_type(i, 'code')
        return self.set_type(i, CELL_TYPES[(CELL_TYPES.index(c.cell_type) + 1) % len(CELL_TYPES)])
    def split(self, i, offset):
        "Split cell `i` at a character offset, keeping outputs with the first half."
        c = self.cells[i]
        self._checkpoint(i)
        head, tail = c.source[:offset], c.source[offset:]
        c.source = head
        n = Cell(source=tail, cell_type=c.cell_type)
        self.cells.insert(i+1, n)
        self.dirty = True
        return n
    def detached(self, i):
        "A clipboard-safe copy of cell `i`, with a fresh identity and no running state."
        if not (0 <= i < len(self.cells)): return None
        return _detached(self.cells[i])
    def paste(self, i, cell):
        "Insert a copy of `cell` at `i`, leaving the clipboard reusable."
        if not isinstance(cell, Cell): raise TypeError('cell clipboard must contain a Cell')
        return self.insert(i, _detached(cell))
    def duplicate(self, i):
        "Duplicate cell `i` below itself, including its current output but with a fresh id."
        if (n := self.detached(i)) is None: return None
        return self.insert(i + 1, n)
    def _live(self, indices):
        "The given cell indices, deduplicated, in order, and inside the document."
        return sorted({int(i) for i in indices if 0 <= int(i) < len(self.cells)})
    def delete_many(self, indices):
        "Delete a cell range as one undoable operation."
        indices = self._live(indices)
        if not indices: return []
        self._checkpoint(indices[0])
        removed = [self.cells[i] for i in indices]
        for i in reversed(indices): self.cells.pop(i)
        if not self.cells: self.cells.append(Cell())
        self.dirty = True
        return removed
    def paste_many(self, i, cells):
        "Paste detached cells as one undoable operation, assigning fresh identities."
        cells = list(cells or ())
        if not cells: return []
        i = max(0, min(int(i), len(self.cells)))
        self._checkpoint(i)
        out = []
        for raw in cells:
            if not isinstance(raw, Cell): raise TypeError('cell clipboard must contain Cells')
            n = _detached(raw)
            self.cells.insert(i + len(out), n)
            out.append(n)
        self.dirty = True
        return out
    def move_many(self, indices, target):
        "Move selected cells before `target` as one stable, undoable block."
        indices = self._live(indices)
        if not indices: return 0
        target = max(0, min(int(target), len(self.cells)))
        self._checkpoint(indices[0])
        picked = [self.cells[i] for i in indices]
        for i in reversed(indices): self.cells.pop(i)
        target -= sum(i < target for i in indices)
        for offset, cell in enumerate(picked): self.cells.insert(target + offset, cell)
        self.dirty = True
        return target
    def merge(self, i):
        "Merge cell `i+1` up into `i`."
        if i+1 >= len(self.cells): return None
        self._checkpoint(i)
        c, n = self.cells[i], self.cells.pop(i+1)
        c.source = c.source.rstrip('\n') + '\n' + n.source
        c.clear()
        self.dirty = True
        return c
    def clear_cell(self, i):
        "Clear one cell's output/reply as an undoable notebook operation."
        if not (0 <= i < len(self.cells)): return None
        self._checkpoint(i)
        return self.cells[i].clear()
    def clear_all(self):
        self._checkpoint(0)
        for c in self.cells: c.clear()
        self.dirty = True
    async def run(self, i, kernel, on_output=None):
        "Run cell `i` against `kernel`, replacing its outputs. Non-code cells are a no-op."
        c = self.cells[i]
        if c.cell_type != 'code': return c
        c.clear()
        c.running = True
        started = time.perf_counter()
        try:
            display_at = {}
            def receive(o):
                row = {k: v for k, v in o.items() if not k.startswith('_')}
                display_id = o.get('_display_id')
                if o.get('_update') and display_id in display_at: c.outputs[display_at[display_id]] = row
                else:
                    c.outputs.append(row)
                    if display_id: display_at[display_id] = len(c.outputs) - 1
                if on_output: on_output(i, row)
            r = await kernel.execute(c.source, on_output=receive)
            c.outputs = r.outputs
            c.execution_count = r.execution_count
        finally:
            c.running = False
            c.execution_ms = (time.perf_counter() - started) * 1000
            c.fresh = True
        self.dirty = True
        return c
    async def run_all(self, kernel, on_output=None, stop_on_error=True):
        "Run every code cell in order, stopping at the first error by default."
        done = L()
        for i, c in enumerate(self.cells):
            if c.cell_type != 'code' or not c.source.strip(): continue
            done.append(await self.run(i, kernel, on_output))
            if stop_on_error and c.has_error: break
        return done
    def code(self):
        "All code sources, for handing the whole notebook to something that wants a script."
        return '\n\n'.join(c.source for c in self.cells if c.cell_type == 'code' and c.source.strip())
    def prompt_start(self, i):
        "Prompt cells always read from the top of the document, not from backend chat history."
        return 0
    def _context_cell(self, c, out_chars=None):
        "One cell as explicit, compaction-aware context markup."
        src = c.source.strip()
        if not src and not c.reply: return ''
        attr = f'id="{c.id}" type="{c.cell_type}" compact="{c.context_mode}"'
        body = [f'<cell {attr}>']
        if src: body.append(f'<source>\n{src}\n</source>')
        if c.cell_type == 'code' and (t := c.text.strip()):
            shown = t if out_chars is None else t[:out_chars]
            body.append(f'<output>\n{shown}\n</output>')
        if c.is_prompt and c.reply: body.append(f'<answer>\n{c.reply.strip()}\n</answer>')
        body.append('</cell>')
        return '\n'.join(body)
    def context(self, i, since=0, max_chars=MAX_CONTEXT, out_chars=MAX_CELL_OUT):
        "Every cell above `i` in document order; under an explicit `max_chars`, `discard` cells go first."
        above = self.cells[max(0, since):max(0, i)]
        rows = [(c.context_mode, self._context_cell(c, out_chars)) for c in above]
        rows = [(mode, text) for mode, text in rows if text]
        txt = '\n'.join(text for _, text in rows)
        if max_chars is None or len(txt) <= max_chars: return txt
        kept = [text for mode, text in rows if mode == 'keep']
        available = max(0, max_chars - len('\n'.join(kept)))
        ordinary = [text for mode, text in rows if mode == 'auto']
        tail = '\n'.join(ordinary)
        if len(tail) > available: tail = ('…\n' + tail[-max(0, available-2):]) if available else ''
        return '\n'.join([*kept, tail] if tail else kept)
    def source_text(self):
        "The whole notebook as one diffable document: every cell's source under a jupytext `# %%` marker."
        return '\n'.join(f'# %% {c.cell_type} {c.id}\n{c.source.rstrip()}' for c in self.cells)


def read_cells(text):
    "The cells of a notebook's JSON text, or `None` when this is not a notebook we can read."
    try: nb = json.loads(text or '')
    except (TypeError, json.JSONDecodeError): return None
    if not isinstance(nb, dict): return None
    cells = nb.get('cells')
    return cells if isinstance(cells, list) else None

def source_spans(text, cells):
    "The 1-based file line numbers holding each cell's source strings, or `None` for a cell that cannot be located."
    lines, spans, idx = (text or '').splitlines(), [], 0
    for cell in cells:
        source = cell.get('source')
        count = len(source) if isinstance(source, list) else max(1, len(str(source or '').splitlines()))
        while idx < len(lines) and '"source"' not in lines[idx]: idx += 1
        if idx >= len(lines):
            spans.append(None)
            continue
        head, idx = lines[idx], idx + 1
        after = head.split('"source"', 1)[1]
        if ']' in after or '[' not in after: spans.append((idx, idx))
        else:
            spans.append((idx + 1, idx + count))
            idx += count
    return spans

def cell_lines(cell):
    "One cell's source as a list of lines, whichever of nbformat's two shapes it is in."
    source = cell.get('source') or ''
    return list(source) if isinstance(source, list) else str(source).splitlines(True)

def _at(cells, spans, i, line_in_cell):
    "The address of a line inside cell `i`. `id` is `''` before nbformat 4.5, so the index is carried too."
    span = spans[i]
    return dict(index=i, id=str(cells[i].get('id') or ''), line=line_in_cell,
        file_line=(span[0] + line_in_cell - 1) if span else 0, kind=str(cells[i].get('cell_type') or 'code'))

def cell_at(text, line, cells=None):
    "The cell containing file line `line`, or `None` when no cell's source does."
    cells = read_cells(text) if cells is None else cells
    if not cells: return None
    try: line = int(line)
    except (TypeError, ValueError): return None
    spans = source_spans(text, cells)
    for i, span in enumerate(spans):
        if span and span[0] <= line <= span[1]: return _at(cells, spans, i, line - span[0] + 1)
    return None

def cell_of(text, snippet, cells=None):
    "The cell holding `snippet`, when exactly one does; `None` for none or several."
    needle = str(snippet or '').strip().split('\n')[0].strip()
    if not needle: return None
    cells = read_cells(text) if cells is None else cells
    if not cells: return None
    spans, found = source_spans(text, cells), []
    for i, cell in enumerate(cells):
        for n, line in enumerate(cell_lines(cell), 1):
            if needle in str(line):
                found.append((i, n))
                break
    if len(found) != 1: return None
    i, n = found[0]
    return _at(cells, spans, i, n)

def assigned_lines(source):
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

def inline_values(source, groups, outputs=(), result_info=None):
    "Kernel values for bindings and a final expression, located on their source lines."
    rows = {n.get('name'): n for g in groups or [] for n in g.get('nodes', [])}
    out = []
    for line, name in assigned_lines(source):
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

async def cell_extras(k, cell):
    "Inspector rows and the rich last result for a finished cell, or `(None, None)`."
    if not k or cell.has_error: return None, None
    rows = await k.api('/api/rows', {'profile': 'full', 'sort': 'name'}, timeout=2)
    has_result = any(o.get('output_type') == 'execute_result' for o in cell.outputs)
    latest = await k.api('/api/result', timeout=2) if has_result else None
    return rows, (latest or {}).get('result')
