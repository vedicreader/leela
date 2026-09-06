"The canvas document: prose and bricks in one markdown file, and the dataflow between them."

from __future__ import annotations
import ast, re, uuid
from dataclasses import dataclass, field
from fastcore.all import L, Path, first, ifnone
from ... import Dictable

__all__ = ['FENCED', 'WRAPPED', 'KINDS', 'Brick', 'Canvas', 'brick_id', 'defs_of', 'reads_of', 'order', 'downstream']

#: Bricks whose body is opaque to markdown, written as a fenced block.
FENCED = ('code', 'ask', 'brick', 'sim', 'data', 'pdf', 'video')
#: Bricks whose body is markdown a plain renderer should still show, wrapped in comments.
WRAPPED = ('reply', 'note', 'quiz')
KINDS = ('text',) + FENCED + WRAPPED

FENCE = re.compile(r'^(`{3,})canvas +(\w+)([^\n]*)$')
TICKS = re.compile(r'^(`{3,})')
WRAP = re.compile(r'^<!--canvas +(\w+)(.*?)-->$')
SHUT = '<!--/canvas-->'
ATTR = re.compile(r'(\w+)=("[^"]*"|\S+)')
DIRECTIVE = re.compile(r'^(bind|prop) +([\w.]+) *= *(.+)$')
FRONT = re.compile(r'\A---\n(.*?)\n---\n', re.S)

def brick_id(): return uuid.uuid4().hex[:8]

def _shut(tick): return re.compile(r'`{%d,}[ \t]*$' % len(tick))

def _scan(text):
    """One pass over the lines: `('text', '', body)` for prose and `(kind, attrs, body)` for a brick.

    Line by line rather than by regex because a canvas fence inside a longer markdown fence is an
    example of one, not one, and a document about canvases is a canvas."""
    lines, i, prose, out = text.split('\n'), 0, [], []
    def flush():
        if ''.join(prose).strip(): out.append(('text', '', '\n'.join(prose).strip()))
        prose.clear()
    def upto(j, shut, keep):
        body = []
        while j < len(lines) and not shut(lines[j]): body.append(lines[j]); j += 1
        if keep and j < len(lines): body.append(lines[j])
        return j, body
    while i < len(lines):
        line = lines[i]
        if (m := FENCE.match(line)):
            flush()
            end = _shut(m[1])
            i, body = upto(i + 1, lambda l: end.match(l), False)
            out.append((m[2], m[3], '\n'.join(body) + ('\n' if body else '')))
        elif (m := TICKS.match(line)):                     # a plain fence is prose, and nothing in it is read
            end = _shut(m[1])
            prose.append(line)
            i, body = upto(i + 1, lambda l: end.match(l), True)
            prose.extend(body)
        elif (m := WRAP.match(line)):
            flush()
            i, body = upto(i + 1, lambda l: l.strip() == SHUT, False)
            out.append((m[1], m[2], '\n'.join(body) + ('\n' if body else '')))
        else:
            prose.append(line); i += 1; continue
        i += 1
    flush()
    return out

def _attrs(s):
    "The `key=value` pairs on a brick's opening line."
    return {k: v.strip('"') for k, v in ATTR.findall(s or '')}

def _attrstr(d):
    return ''.join(f' {k}={v}' if re.fullmatch(r'[\w./:-]+', str(v)) else f' {k}="{v}"' for k, v in d.items() if v not in (None, ''))

def _directives(body):
    "Split a brick body into its `bind`/`prop` lines and whatever is left."
    binds, props, rest = {}, {}, []
    for line in (body or '').splitlines():
        m = DIRECTIVE.match(line.strip())
        if not m: rest.append(line)
        elif m[1] == 'bind': binds[m[2]] = m[3].strip()
        else: props[m[2]] = m[3].strip()
    return binds, props, '\n'.join(rest).strip()

def _directive_lines(binds, props):
    return ''.join([f'bind {k} = {v}\n' for k, v in binds.items()] + [f'prop {k} = {v}\n' for k, v in props.items()])

@dataclass
class Brick(Dictable):
    "One node of a canvas: prose, a code cell, an embedded component, a simulation, a question."
    kind: str = 'text'
    body: str = ''
    id: str = field(default_factory=brick_id)
    attrs: dict = field(default_factory=dict)
    binds: dict = field(default_factory=dict)
    props: dict = field(default_factory=dict)
    def __post_init__(self):
        if self.kind not in KINDS: self.kind = 'text'
    @property
    def src(self): return self.attrs.get('src', '')
    @property
    def runs(self): return self.kind == 'code'
    @property
    def reactive(self): return bool(self.binds)
    def dict(self): return {**super().dict(), 'defs': list(self.defs), 'reads': list(self.reads)}
    @property
    def defs(self): return defs_of(self.body) if self.runs else L()
    @property
    def reads(self):
        "Names this brick needs: what its code reads, or what its bindings evaluate."
        if self.runs: return reads_of(self.body)
        return L(self.binds.values()).map(reads_of).concat().unique()
    def md(self):
        "This brick as it is written in the file."
        a = _attrstr({'id': self.id, **self.attrs})
        if self.kind == 'text': return self.body.strip() + '\n'
        body = _directive_lines(self.binds, self.props) + (self.body.strip() + '\n' if self.body.strip() else '')
        if self.kind in WRAPPED: return f'<!--canvas {self.kind}{a}-->\n{body}<!--/canvas-->\n'
        return f'```canvas {self.kind}{a}\n{body}```\n'

def _walk(source):
    try: return ast.parse(source or '')
    except SyntaxError: return None

def defs_of(source):
    "Top-level names a code brick defines."
    t = _walk(source)
    if t is None: return L()
    out = L()
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): out.append(n.name)
        elif isinstance(n, ast.Assign): out += L(n.targets).map(_targets).concat()
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)): out += _targets(n.target)
        elif isinstance(n, (ast.Import, ast.ImportFrom)): out += L(n.names).map(lambda a: (a.asname or a.name).split('.')[0])
    return out.unique()

def _targets(node):
    if isinstance(node, ast.Name): return L([node.id])
    if isinstance(node, (ast.Tuple, ast.List)): return L(node.elts).map(_targets).concat()
    return L()

def reads_of(source):
    "Free names an expression or a block of code loads."
    t = _walk(source)
    if t is None: return L()
    return L(ast.walk(t)).filter(lambda n: isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)).map(lambda n: n.id).unique()

def order(bricks):
    "Runnable bricks in dependency order, falling back to document order on a cycle."
    live = L(bricks).filter(lambda b: b.runs)
    owner = {n: b.id for b in live for n in b.defs}
    need = {b.id: {owner[n] for n in b.reads if n in owner and owner[n] != b.id} for b in live}
    out, seen = [], set()
    def visit(b, path):
        if b.id in seen or b.id in path: return
        for dep in need[b.id]: visit(first(x for x in live if x.id == dep), path | {b.id})
        seen.add(b.id); out.append(b)
    for b in live: visit(b, set())
    return L(out)

def downstream(bricks, names):
    "Every brick whose result depends on one of `names`, transitively, in run order."
    names, hit = set(names), []
    for b in order(bricks):
        if set(b.reads) & names: hit.append(b); names |= set(b.defs)
    reactive = L(bricks).filter(lambda b: b.reactive and set(b.reads) & names)
    return L(hit) + reactive

@dataclass
class Canvas(Dictable):
    "A living document: an ordered list of bricks, a title, and the file it came from."
    bricks: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    path: str = ''
    def __len__(self): return len(self.bricks)
    def __getitem__(self, i): return self.bricks[i]
    def __iter__(self): return iter(self.bricks)
    @property
    def title(self): return self.meta.get('title') or (Path(self.path).name if self.path else 'untitled')
    def by_id(self, id): return first(b for b in self.bricks if b.id == id)
    def index(self, id): return first(i for i, b in enumerate(self.bricks) if b.id == id)
    def insert(self, i, brick): self.bricks.insert(max(0, min(i, len(self))), brick); return brick
    def remove(self, id):
        i = self.index(id)
        return self.bricks.pop(i) if i is not None else None
    def replace(self, id, **kw):
        b = self.by_id(id)
        if b: [setattr(b, k, v) for k, v in kw.items()]
        return b
    def reply_to(self, id): return first(b for b in self.bricks if b.kind == 'reply' and b.attrs.get('of') == id)
    @classmethod
    def parse(cls, text, path=''):
        "Read a canvas file: prose becomes text bricks, fences and comment wraps become the rest."
        text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
        meta, m = {}, FRONT.match(text)
        if m:
            for line in m[1].splitlines():
                if ':' in line: k, v = line.split(':', 1); meta[k.strip()] = v.strip()
            text = text[m.end():]
        bricks, seen = [], set()
        for kind, attrline, body in _scan(text):
            if kind == 'text': bricks.append(Brick(kind='text', body=body)); continue
            a = _attrs(attrline)
            binds, props, body = _directives(body) if kind != 'code' else ({}, {}, body)
            id = a.pop('id', None)
            if not id or id in seen: id = brick_id()       # two bricks sharing an id would answer to each other's ops
            seen.add(id)
            bricks.append(Brick(kind=kind, body=body, id=id, attrs=a, binds=binds, props=props))
        return cls(bricks=bricks, meta=meta, path=path)
    def md(self):
        "The whole document, as it goes to disk."
        front = ''.join(f'{k}: {v}\n' for k, v in self.meta.items())
        head = f'---\n{front}---\n\n' if front else ''
        return head + '\n'.join(b.md() for b in self.bricks)
    @classmethod
    def load(cls, path): return cls.parse(Path(path).read_text(), str(path))
    def save(self, path=None):
        p = Path(path or self.path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(self.md()); return p
    def dict(self): return {'title': self.title, 'path': self.path, 'meta': self.meta, 'bricks': [b.dict() for b in self.bricks]}
