"""The notebook document: cells, outputs, and running them against a kernel.

Outputs are kept in nbformat shape all the way through -- the kernel's iopub
messages are normalised into nbformat dicts in `kernels.py`, held as-is here,
and written straight out as `.ipynb`. Nothing translates between an internal
representation and a file format, so a round-trip cannot lose anything the
kernel actually sent.

The document knows how to mutate itself and how to run a cell; it does not know
about FastHTML or CodeMirror. The browser and persistence layers drive the same object.

There is a third cell type here that Jupyter does not have: `prompt`. A prompt
cell is a question for the assistant, living in the notebook rather than in a
chat panel off to one side, and `context()` is what makes that worth doing --
running one sends the cells *above* it, so the code, what it printed, and the
prose around it are the conversation. The answer is stored in the cell, which
means it is saved with the document, read in order like everything else, and
re-runnable. (The idea is borrowed from Solveit, whose dialogs are notebooks of
`code`/`note`/`prompt` messages.)
"""

from __future__ import annotations
import json, time, uuid
from copy import deepcopy
from dataclasses import dataclass, field
from fastcore.all import L, ifnone
from fastcore.nbio import read_nb, write_nb, new_nb

from . import Dictable
from .kernels import output_text

__all__ = ['CELL_TYPES', 'Cell', 'Notebook', 'cell_id']

# The order `ctrl+alt+m` cycles through.
CELL_TYPES = ('code', 'markdown', 'prompt')

# Context is complete by default. A prompt cell is a view over the notebook above it, not
# a twelve-kilobyte excerpt of that notebook. Callers may still pass explicit limits for a
# constrained model; cells marked ``keep`` survive that compaction before ordinary cells.
MAX_CONTEXT = None
MAX_CELL_OUT = None
CONTEXT_MODES = ('auto', 'keep', 'discard')
MAX_UNDO = 100        # structural notebook snapshots kept in each direction


def cell_id(): return uuid.uuid4().hex[:8]


@dataclass
class Cell(Dictable):
    'One notebook cell. `outputs` are nbformat dicts exactly as the kernel sent them.'
    source: str = ''
    cell_type: str = 'code'                        # 'code' | 'markdown' | 'prompt' | 'raw'
    outputs: list = field(default_factory=list)
    execution_count: int | None = None
    execution_ms: float | None = None                 # last run duration, persisted in metadata
    id: str = field(default_factory=cell_id)
    running: bool = False
    reply: str = ''                                # a prompt cell's answer
    calls: list = field(default_factory=list)      # and the tools used to reach it
    usage: dict = field(default_factory=dict)      # per-answer token and estimated cost accounting
    # An approval exchange the agent raised while answering a prompt cell: the request, or
    # the person's answer to it, saved as an ordinary markdown cell so the negotiation is
    # read in order with everything else. `None` on every other cell.
    approval: dict | None = None
    # Compaction policy for this cell. ``keep`` means preserve its details when notebook
    # context has to be reduced; ``discard`` makes it the first candidate to remove. All
    # three modes are sent in full before compaction is necessary.
    context_mode: str = 'auto'                  # 'auto' | 'keep' | 'discard'
    fresh: bool = False                         # ran in this live kernel; deliberately not persisted

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
        """This cell in nbformat v4 shape.

        nbformat has no prompt cell, so one is written as *markdown* carrying its answer
        in metadata. That keeps the file valid and legible in plain Jupyter -- the
        question reads as prose -- while leela still round-trips the reply and the
        tool calls. Inventing a `cell_type` would have made the notebook unopenable
        everywhere else, which is too high a price for a nicer-looking file.
        """
        c = {'cell_type': self.cell_type, 'source': self.source, 'metadata': {}, 'id': self.id}
        meta = {} if self.context_mode == 'auto' else {'context': self.context_mode}
        if self.cell_type == 'code':
            c['outputs'] = list(self.outputs)
            c['execution_count'] = self.execution_count
            if self.execution_ms is not None: meta['execution_ms'] = round(self.execution_ms, 3)
        elif self.is_prompt:
            c['cell_type'] = 'markdown'
            meta.update(kind='prompt', reply=self.reply, calls=list(self.calls), usage=dict(self.usage))
            if self.execution_ms is not None: meta['execution_ms'] = round(self.execution_ms, 3)
        elif self.approval is not None:
            # Same trick as a prompt cell, for the same reason: the exchange is prose, so
            # it is written as markdown and only the structure lives in metadata.
            meta.update(self.approval, kind='approval')
        if meta: c['metadata'] = {'leela': meta}
        return c

    @classmethod
    def from_nb(cls, c):
        src = c.get('source', '')
        if isinstance(src, list): src = ''.join(src)
        meta = (c.get('metadata') or {}).get('leela') or {}
        return cls(source=src,
                   cell_type='prompt' if meta.get('kind') == 'prompt' else c.get('cell_type', 'code'),
                   outputs=list(c.get('outputs') or []),
                   execution_count=c.get('execution_count'),
                   execution_ms=meta.get('execution_ms'),
                   id=str(c.get('id') or cell_id()),
                   reply=str(meta.get('reply') or ''), calls=list(meta.get('calls') or []),
                   usage=dict(meta.get('usage') or {}),
                   approval=dict(meta) if meta.get('kind') == 'approval' else None,
                   context_mode=str(meta.get('context') or 'auto'))


class Notebook:
    "An open .ipynb: an ordered list of `Cell`s that can run against a `Kernel`."

    def __init__(self, cells=None, path=None):
        self.cells = L(ifnone(cells, [Cell()]))
        self.path = str(path) if path else ''
        self.dirty = False
        # Text editors own character-level undo. This history owns notebook operations:
        # deleting, moving, splitting, merging, changing type, and clearing output.
        self._undo, self._redo = [], []

    def __len__(self): return len(self.cells)
    def __getitem__(self, i): return self.cells[i]

    # -- io --------------------------------------------------------------------
    @classmethod
    def load(cls, path):
        # A file picker traditionally creates files with `touch`. Treat a zero-byte
        # notebook as a new document rather than surfacing a JSONDecodeError; saving it
        # will replace the placeholder with valid nbformat JSON. Non-empty malformed
        # notebooks still raise, because silently replacing their contents would lose data.
        from pathlib import Path
        p = Path(path)
        if p.exists() and p.stat().st_size == 0: return cls.blank(path)
        nb = read_nb(str(path))
        cells = [Cell.from_nb(c) for c in nb['cells']] or [Cell()]
        return cls(cells, path)

    @classmethod
    def blank(cls, path=None): return cls([Cell()], path)

    def save(self, path=None, sandbox=None):
        """Write the notebook. `sandbox` routes the write through `Sandbox.write`, so a
        notebook cannot be saved outside the open folders."""
        p = str(path or self.path)
        if not p: raise ValueError('notebook has no path')
        nb = new_nb([])
        nb['cells'] = [c.nbcell() for c in self.cells]
        if sandbox is not None:
            sandbox.write(p, json.dumps(nb, indent=1) + '\n')
        else:
            write_nb(nb, p)
        self.path, self.dirty = p, False
        return p

    # -- structure -------------------------------------------------------------
    def _snapshot(self, i=0):
        return {'cells': deepcopy(list(self.cells)), 'dirty': self.dirty, 'index': i}

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
        "Remove a cell. A notebook always keeps at least one, so there is somewhere to type."
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
        "Advance a cell through `CELL_TYPES`, so one key reaches all three instead of three keys."
        c = self.cells[i]
        nxt = (CELL_TYPES[(CELL_TYPES.index(c.cell_type) + 1) % len(CELL_TYPES)]
               if c.cell_type in CELL_TYPES else 'code')
        return self.set_type(i, nxt)

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
        n = deepcopy(self.cells[i])
        n.id, n.running, n.fresh = cell_id(), False, False
        return n

    def paste(self, i, cell):
        "Insert a detached copy at `i`; the clipboard remains reusable across notebooks."
        if not isinstance(cell, Cell): raise TypeError('cell clipboard must contain a Cell')
        n = deepcopy(cell)
        n.id, n.running, n.fresh = cell_id(), False, False
        return self.insert(i, n)

    def duplicate(self, i):
        "Duplicate cell `i` below itself, including its current output but with a fresh id."
        if (n := self.detached(i)) is None: return None
        return self.insert(i + 1, n)

    def delete_many(self, indices):
        "Delete a cell range as one undoable operation."
        indices = sorted({int(i) for i in indices if 0 <= int(i) < len(self.cells)})
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
            n = deepcopy(raw); n.id, n.running, n.fresh = cell_id(), False, False
            self.cells.insert(i + len(out), n); out.append(n)
        self.dirty = True
        return out

    def move_many(self, indices, target):
        "Move selected cells before `target` as one stable, undoable block."
        indices = sorted({int(i) for i in indices if 0 <= int(i) < len(self.cells)})
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

    # -- execution -------------------------------------------------------------
    async def run(self, i, kernel, on_output=None):
        """Run cell `i` against `kernel`, replacing its outputs.

        Markdown cells are a no-op rather than an error -- 'run' on a markdown cell means
        'render and move on', which is what the frontends do with the returned cell.
        """
        c = self.cells[i]
        if c.cell_type != 'code': return c
        c.clear(); c.running = True
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
            # Persist Kernel's reconciled final list as well. This strips callback-only
            # display metadata and covers kernels that do not emit incremental callbacks.
            c.outputs = r.outputs
            c.execution_count = r.execution_count
        finally:
            c.running = False
            c.execution_ms = (time.perf_counter() - started) * 1000
            c.fresh = True
        self.dirty = True
        return c

    async def run_all(self, kernel, on_output=None, stop_on_error=True):
        "Run every code cell in order. Stops at the first error by default, as Jupyter's 'run all' does."
        done = L()
        for i, c in enumerate(self.cells):
            if c.cell_type != 'code' or not c.source.strip(): continue
            done.append(await self.run(i, kernel, on_output))
            if stop_on_error and c.has_error: break
        return done

    def code(self):
        "All code sources, for handing the whole notebook to something that wants a script."
        return '\n\n'.join(c.source for c in self.cells if c.cell_type == 'code' and c.source.strip())

    # -- prompt cells ----------------------------------------------------------
    def prompt_start(self, i):
        """Prompt cells always read from the top of the document.

        The document is the source of truth, and an earlier cell may have been edited
        since its last prompt ran. Reusing only backend chat history makes that edit
        invisible. This mirrors dialoghelper/Solveit: every message above the current
        prompt is already-visible context.
        """
        return 0

    def _context_cell(self, c, out_chars=None):
        """One cell as explicit, compaction-aware context markup."""
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
        """Every cell above `i`, including complete outputs and replies, in document order.

        Nothing is silently clipped in the normal path. If an explicit ``max_chars`` is
        supplied, ``discard`` cells are removed first, then old ``auto`` cells; ``keep``
        cells are retained ahead of both. The ``compact`` attributes also travel into the
        agent history so later conversation compaction can make the same choice.
        """
        rows = [(c.context_mode, self._context_cell(c, out_chars))
                for c in self.cells[max(0, since):max(0, i)]]
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
        """The whole notebook as one diffable document: every cell's source under a marker line.

        Diffing the raw `.ipynb` would be useless -- it is JSON, and a one-character edit
        shows up as a rewritten line buried among outputs and execution counts. Cell
        sources under jupytext's `# %%` markers diff the way the user thinks about the
        document, and the marker carries the cell type and id so a hunk can be traced
        back to the cell it came from.
        """
        return '\n'.join(f'# %% {c.cell_type} {c.id}\n{c.source.rstrip()}' for c in self.cells)
