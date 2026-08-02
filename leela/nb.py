"""The notebook document: cells, outputs, and running them against a kernel.

Outputs are kept in nbformat shape all the way through -- the kernel's iopub
messages are normalised into nbformat dicts in `kernels.py`, held as-is here,
and written straight out as `.ipynb`. Nothing translates between an internal
representation and a file format, so a round-trip cannot lose anything the
kernel actually sent.

The document knows how to mutate itself and how to run a cell; it does not know
about Textual or FastHTML. Both frontends drive the same object.

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
import json, uuid
from dataclasses import dataclass, field
from fastcore.all import L, ifnone
from fastcore.nbio import read_nb, write_nb, new_nb

from . import Dictable
from .kernels import output_text

__all__ = ['CELL_TYPES', 'Cell', 'Notebook', 'cell_id']

# The order `ctrl+alt+m` cycles through.
CELL_TYPES = ('code', 'markdown', 'prompt')

MAX_CONTEXT = 12000   # chars of notebook sent with a prompt cell
MAX_CELL_OUT = 800    # chars of any one cell's output within that


def cell_id(): return uuid.uuid4().hex[:8]


@dataclass
class Cell(Dictable):
    'One notebook cell. `outputs` are nbformat dicts exactly as the kernel sent them.'
    source: str = ''
    cell_type: str = 'code'                        # 'code' | 'markdown' | 'prompt' | 'raw'
    outputs: list = field(default_factory=list)
    execution_count: int | None = None
    id: str = field(default_factory=cell_id)
    running: bool = False
    reply: str = ''                                # a prompt cell's answer
    calls: list = field(default_factory=list)      # and the tools used to reach it
    # An approval exchange the agent raised while answering a prompt cell: the request, or
    # the person's answer to it, saved as an ordinary markdown cell so the negotiation is
    # read in order with everything else. `None` on every other cell.
    approval: dict | None = None

    @property
    def text(self): return output_text(self.outputs)

    @property
    def has_error(self): return any(o.get('output_type') == 'error' for o in self.outputs)

    @property
    def is_prompt(self): return self.cell_type == 'prompt'

    @property
    def is_approval(self): return self.approval is not None

    def clear(self):
        self.outputs, self.execution_count = [], None
        self.reply, self.calls = '', []
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
        if self.cell_type == 'code':
            c['outputs'] = list(self.outputs)
            c['execution_count'] = self.execution_count
        elif self.is_prompt:
            c['cell_type'] = 'markdown'
            c['metadata'] = {'leela': {'kind': 'prompt', 'reply': self.reply, 'calls': list(self.calls)}}
        elif self.approval is not None:
            # Same trick as a prompt cell, for the same reason: the exchange is prose, so
            # it is written as markdown and only the structure lives in metadata.
            c['metadata'] = {'leela': dict(self.approval, kind='approval')}
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
                   id=str(c.get('id') or cell_id()),
                   reply=str(meta.get('reply') or ''), calls=list(meta.get('calls') or []),
                   approval=dict(meta) if meta.get('kind') == 'approval' else None)


class Notebook:
    "An open .ipynb: an ordered list of `Cell`s that can run against a `Kernel`."

    def __init__(self, cells=None, path=None):
        self.cells = L(ifnone(cells, [Cell()]))
        self.path = str(path) if path else ''
        self.dirty = False

    def __len__(self): return len(self.cells)
    def __getitem__(self, i): return self.cells[i]

    # -- io --------------------------------------------------------------------
    @classmethod
    def load(cls, path):
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
    def insert(self, i, cell=None):
        c = cell or Cell()
        self.cells.insert(max(0, min(i, len(self.cells))), c)
        self.dirty = True
        return c

    def delete(self, i):
        "Remove a cell. A notebook always keeps at least one, so there is somewhere to type."
        if not (0 <= i < len(self.cells)): return None
        c = self.cells.pop(i)
        if not self.cells: self.cells.append(Cell())
        self.dirty = True
        return c

    def move(self, i, d):
        j = i + d
        if not (0 <= i < len(self.cells) and 0 <= j < len(self.cells)): return i
        self.cells[i], self.cells[j] = self.cells[j], self.cells[i]
        self.dirty = True
        return j

    def set_type(self, i, t):
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
        head, tail = c.source[:offset], c.source[offset:]
        c.source = head
        n = Cell(source=tail, cell_type=c.cell_type)
        self.cells.insert(i+1, n)
        self.dirty = True
        return n

    def merge(self, i):
        "Merge cell `i+1` up into `i`."
        if i+1 >= len(self.cells): return None
        c, n = self.cells[i], self.cells.pop(i+1)
        c.source = c.source.rstrip('\n') + '\n' + n.source
        c.clear()
        self.dirty = True
        return c

    def clear_all(self):
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
        try:
            r = await kernel.execute(c.source, on_output=lambda o: (c.outputs.append(o), on_output and on_output(i, o)))
            c.execution_count = r.execution_count
        finally:
            c.running = False
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
        """Where a prompt cell at `i` should start reading from: just after the last answered prompt above it.

        The assistant keeps one conversation per workspace, so everything up to the
        previous answered prompt has already been sent -- re-sending it would burn the
        context window restating what the model was told a moment ago. This is the same
        rule Solveit states as "messages above the current message are already visible".
        """
        for j in range(min(i, len(self.cells)) - 1, -1, -1):
            if self.cells[j].is_prompt and self.cells[j].reply: return j + 1
        return 0

    def context(self, i, since=0, max_chars=MAX_CONTEXT, out_chars=MAX_CELL_OUT):
        """Cells `since` up to (not including) `i`, as one block a model can read.

        Code with what it actually printed, prose as prose, and earlier questions with
        their answers -- in order, the way a person reading the page would take it in.
        Outputs are the part that runs away with the context window (one `df.describe()`
        can be thousands of tokens), so they are clipped per cell.

        When the whole thing is still too long the *front* is dropped, not the back: the
        cell immediately above the question is the one it is most likely about.
        """
        out = L()
        for c in self.cells[max(0, since):max(0, i)]:
            src = c.source.strip()
            if not src and not c.reply: continue
            if c.is_prompt:
                out.append(f'<asked>\n{src}\n</asked>')
                if c.reply: out.append(f'<answered>\n{c.reply.strip()}\n</answered>')
            elif c.cell_type == 'code':
                body = f'<code id="{c.id}">\n{src}\n</code>'
                if (t := c.text.strip()): body += f'\n<output>\n{t[:out_chars]}\n</output>'
                out.append(body)
            else:
                out.append(f'<note>\n{src}\n</note>')
        txt = '\n'.join(out)
        return txt if len(txt) <= max_chars else '…\n' + txt[-max_chars:]

    def source_text(self):
        """The whole notebook as one diffable document: every cell's source under a marker line.

        Diffing the raw `.ipynb` would be useless -- it is JSON, and a one-character edit
        shows up as a rewritten line buried among outputs and execution counts. Cell
        sources under jupytext's `# %%` markers diff the way the user thinks about the
        document, and the marker carries the cell type and id so a hunk can be traced
        back to the cell it came from.
        """
        return '\n'.join(f'# %% {c.cell_type} {c.id}\n{c.source.rstrip()}' for c in self.cells)
