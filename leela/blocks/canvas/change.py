"A unit of change: its goal, its tasks, its prose, its code and its diff."

from __future__ import annotations
import re
from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatch
from fastcore.all import L, Path, first

from .context import strip_work_log
from .doc import Brick, Canvas
from .export import modules

__all__ = ['Bundle', 'bundles', 'bundle_of', 'coverage', 'state', 'pr', 'review', 'value',
           'hunks', 'diff_stat', 'place_diff', 'snip', 'STATES']

def _list(v): return [x.strip() for x in str(v or '').split(',') if x.strip()]

@dataclass
class Bundle:
    "One change: a bundle brick, and everything the region it sits in holds."
    id: str
    doc: Canvas
    brick: Brick
    @property
    def title(self): return self.brick.title or self.brick.region or self.id
    @property
    def goal(self): return self.doc.by_id(self.brick.attrs.get('goal', ''))
    @property
    def contributes(self): return self.brick.attrs.get('contributes', '')
    @property
    def refs(self):
        "Packages, files and documents attached for review. Same vocabulary as a context pin."
        return _list(self.brick.attrs.get('refs'))
    @property
    def members(self):
        "Bricks in this change: its region, plus what `covers=` names. Never the goal."
        want = {self.brick.region} | set(_list(self.brick.attrs.get('covers')))
        return L(b for b in self.doc.bricks
                 if b.id != self.id and not b.heading and b.kind != 'goal'
                 and (b.region in want or b.id in want))
    def of(self, *kinds): return self.members.filter(lambda b: b.kind in set(kinds))
    @property
    def paths(self):
        "Files this change owns: what its code exports, then what `paths=` declares."
        mine = {b.id for b in self.of('code')}
        one = Canvas(bricks=[b for b in self.doc.bricks if b.id in mine], meta=self.doc.meta)
        return sorted(set(modules(one)) | set(_list(self.brick.attrs.get('paths'))))

def bundles(doc): return L(Bundle(b.id, doc, b) for b in doc.of('bundle'))

def bundle_of(doc, bid):
    "The change a brick belongs to, or None."
    return first(b for b in bundles(doc) if any(m.id == bid for m in b.members))

def _matches(claim, path): return fnmatch(path, claim) or path == claim

#: Where a change stands. Read off the document, never set by hand.
STATES = ('todo', 'doing', 'blocked', 'done')

def state(
    b,             # the `Bundle`
    changed=(),    # paths a diff says moved, else no evidence about files
):
    "Where one change stands, read off the document."
    st = [t.attrs.get('status', 'todo') for t in b.of('task')]
    hit = {p for c in b.paths for p in changed if _matches(c, p)}
    unmet = [c for c in b.paths if not any(_matches(c, p) for p in changed)]
    files_ok = not changed or not b.paths or not unmet
    if 'blocked' in st: return 'blocked'
    if st and all(x == 'done' for x in st) and files_ok: return 'done'
    if 'doing' in st or 'done' in st or hit: return 'doing'
    return 'todo'

def coverage(
    doc,        # the document
    changed,    # paths a diff says moved
):
    "What each change claims, what moved, and what nobody claimed."
    changed, rows, claimed = sorted(changed), [], set()
    for b in bundles(doc):
        hit = {p for c in b.paths for p in changed if _matches(c, p)}
        claimed |= hit
        rows.append({'id': b.id, 'title': b.title, 'goal': b.goal.id if b.goal else '',
                     'paths': b.paths, 'matched': sorted(hit),
                     'unmet': [c for c in b.paths if not any(_matches(c, p) for p in changed)],
                     'tasks_open': [t.id for t in b.of('task')
                                    if t.attrs.get('status', 'todo') not in ('done',)]})
    return {'bundles': rows, 'unclaimed': [p for p in changed if p not in claimed]}

def _reasoning(b):
    "The questions asked inside a change and the answers kept, which is the why a diff never has."
    out = []
    for q in b.of('ask'):
        r = b.doc.reply_to(q.id)
        if r is None: continue
        out.append(f'<details>\n<summary>{q.body.strip().splitlines()[0]}</summary>\n\n'
                   f'{strip_work_log(r.body).strip()}\n</details>')
    return out

def pr(doc, bid, branch=None):
    "A pull request cut from one change. It opens nothing."
    b = first(x for x in bundles(doc) if x.id == bid)
    if b is None: raise KeyError(bid)
    body = []
    if (g := b.goal) is not None:
        bits = [f'{k}: {v}' for k, v in g.attrs.items()
                if k in ('measure', 'baseline', 'target', 'by')]
        body.append(f'**Goal.** {g.body.strip()}' + (f'  \n{" | ".join(bits)}' if bits else ''))
        if b.contributes: body.append(f'**Contributes.** {b.contributes}')
    if b.brick.body.strip(): body.append(b.brick.body.strip())
    if (prose := [x.body.strip() for x in b.of('text', 'note') if x.body.strip()]):
        body.append('\n\n'.join(prose))
    if (tasks := b.of('task')):
        body.append('### Tasks\n' + '\n'.join(
            f"- [{'x' if t.attrs.get('status') == 'done' else ' '}] {t.body.strip()}"
            + (f" ({t.attrs['owner']})" if t.attrs.get('owner') else '') for t in tasks))
    if (why := _reasoning(b)): body.append('### Why\n' + '\n\n'.join(why))
    if b.refs: body.append('### Attached\n' + '\n'.join(f'- `{r}`' for r in b.refs))
    if b.paths: body.append('### Files\n' + '\n'.join(f'- `{p}`' for p in b.paths))
    return {'id': b.id, 'title': b.title, 'branch': branch or f'canvas/{b.id}',
            'body': '\n\n'.join(body) + '\n', 'paths': b.paths, 'refs': b.refs,
            'goal': b.goal.id if b.goal else ''}

def snip(brick, root='.'):
    "The code a `snippet` brick cites, read out of the file it names."
    path = Path(root)/brick.attrs.get('path', '')
    if not path.is_file(): return ''
    text = path.read_text(encoding='utf-8')
    if (rng := brick.attrs.get('lines')):
        a, _, b = rng.partition('-')
        rows = text.splitlines()
        return '\n'.join(rows[max(0, int(a) - 1):int(b or a)])
    if not (sym := brick.attrs.get('symbol')): return text
    return _symbol(text, sym)

import ast

#: A name being declared, in any of the languages a canvas cites. `ast` is exact where it applies.
DECL = re.compile(r'^(?:export\s+|async\s+)*(?:def|class|function|const|let|var)?\s*'
                  r'(?P<name>[A-Za-z_$][\w$]*)\s*(?:[=(:]|$)')

def _symbol(text, sym):
    "One named function or class out of a file's source, as written."
    if (got := _by_ast(text, sym)): return got
    return _by_scan(text, sym.rpartition('.')[2])

def _by_ast(text, sym):
    "Exact, for Python. A dotted name is a method of its class."
    try: tree = ast.parse(text)
    except SyntaxError: return ''
    outer, _, inner = sym.partition('.')
    node = first(n for n in tree.body if getattr(n, 'name', None) == outer)
    if node is None: return ''
    if inner: node = first(n for n in getattr(node, 'body', []) if getattr(n, 'name', None) == inner)
    if node is None: return ''
    start = min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])])
    rows = text.splitlines()
    return '\n'.join(rows[start - 1:node.end_lineno])

def _by_scan(text, name):
    "The block a declaration owns, for a file `ast` cannot read or a name it does not carry."
    rows = text.splitlines()
    at = first(i for i, r in enumerate(rows)
               if (m := DECL.match(r.strip())) and m.group('name') == name)
    if at is None: return ''
    lead = len(rows[at]) - len(rows[at].lstrip())
    end = at + 1
    for i in range(at + 1, len(rows)):
        if not rows[i].strip(): continue
        if len(rows[i]) - len(rows[i].lstrip()) <= lead: break
        end = i + 1
    return '\n'.join(rows[at:end])

_FILE = re.compile(r'^diff --git a/(\S+) b/(\S+)$', re.M)

def hunks(text):
    "`{path: diff text}` from unified diff output. One entry per file, headers kept."
    marks = list(_FILE.finditer(text or ''))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i+1].start() if i+1 < len(marks) else len(text)
        out[m.group(2)] = text[m.start():end].rstrip('\n')
    return out

def diff_stat(text):
    "Lines added and removed in one file's diff, ignoring the headers."
    add = sum(1 for l in text.splitlines() if l.startswith('+') and not l.startswith('+++'))
    rm = sum(1 for l in text.splitlines() if l.startswith('-') and not l.startswith('---'))
    return add, rm

def place_diff(
    doc,     # the document, with `diff` bricks that carry no body
    get,     # `get(paths, left, right) -> str`: the diff text those attributes ask for
):
    "Fill every empty `diff` brick from the diff it asks for. One brick per file."
    for slot in doc.of('diff').filter(lambda b: not b.body.strip()):
        at = doc.index(slot.id)
        if at is None: continue
        doc.bricks.pop(at)
        raw = get(_list(slot.attrs.get('paths')), slot.attrs.get('left', ''),
                  slot.attrs.get('right', ''))
        made, cut = [], hunks(raw)
        #: `_dids`, not the basename: two changed files called `app.py` would otherwise share an id,
        #: and `by_id` would resolve both to the first.
        dids = _dids(list(cut))
        for n, (path, text) in enumerate(cut.items()):
            add, rm = diff_stat(text)
            made.append(Brick('diff', text, id=f'{slot.id}-{dids[path][2:]}',
                              attrs={'path': path, 'added': str(add), 'removed': str(rm)}))
            doc.bricks.insert(at + n, made[-1])
        loose = set(coverage(doc, [b.attrs['path'] for b in made])['unclaimed'])
        for b in made:
            if b.attrs['path'] in loose: b.attrs['claimed'] = 'no'
    return doc._regions()

def _tally(b, changed=()):
    "One line of status for a change: how many tasks are done, and how much of the claim moved."
    st = [t.attrs.get('status', 'todo') for t in b.of('task')]
    hit = {p for c in b.paths for p in changed if _matches(c, p)}
    bits = [f"{sum(1 for x in st if x == 'done')}/{len(st)} tasks done" if st else 'no tasks']
    if b.paths: bits.append(f'{len(hit)}/{len(b.paths)} files changed')
    if (n := sum(1 for x in st if x == 'blocked')): bits.append(f'{n} blocked')
    return ' | '.join(bits)

def _copy(b, **attrs):
    return Brick(kind=b.kind, body=b.body, id=b.id, attrs={**b.attrs, **attrs},
                 binds=dict(b.binds), props={})

def _globby(p): return any(c in p for c in '*?[')

def _dids(paths):
    "One brick id per changed file: the basename, or the whole path when two files share one."
    n = Counter(Path(p).name for p in paths)
    uniq = lambda p: Path(p).name if n[Path(p).name] == 1 else re.sub(r'[^\w.-]+', '-', str(p))
    return {p: f'd-{uniq(p)}' for p in paths}

def review(
    doc,           # the document the change lives in
    bid,           # which bundle
    diff='',       # unified diff text
    values=None,   # `{brick id: output text}` from the live namespace
):
    "One change as a document: the value, the reasoning, the diff and the checks."
    b = first(x for x in bundles(doc) if x.id == bid)
    if b is None: raise KeyError(bid)
    files = hunks(diff)
    cov = first(r for r in coverage(doc, list(files))['bundles'] if r['id'] == bid) or {}
    out = Canvas(meta={'title': f'Review: {b.title}'}, path=f'{bid}.review.canvas.md')
    out.add(Brick('text', f'# {b.title}'))
    if (g := b.goal) is not None: out.add(_copy(g))
    if b.contributes: out.add(Brick('note', f'Contributes: {b.contributes}', id=f'{bid}-contrib'))
    if b.brick.body.strip(): out.add(Brick('text', b.brick.body.strip()))
    for t in b.of('task'): out.add(_copy(t))
    if (why := b.of('ask')):
        out.add(Brick('text', '## Why'))
        for q in why:
            out.add(_copy(q, scope='none'))          # its context lived in the document it came from
            if (r := doc.reply_to(q.id)) is not None: out.add(_copy(r))
    out.add(Brick('text', '## Change'))
    cited = {}
    for m in b.members:
        if m.kind in ('snippet', 'text', 'note') and m.attrs.get('path'):
            cited.setdefault(m.attrs['path'], []).append(m)
    dids, globs = _dids(files), {k: v for k, v in cited.items() if _globby(k)}
    for path, text in files.items():
        #: A glob note heads the run of files it matches; an exact-path note still follows that file's hunks.
        for pat in [k for k in globs if fnmatch(path, k)]:
            for m in globs.pop(pat): out.add(_copy(m))
            cited.pop(pat, None)
        add, rm = diff_stat(text)
        out.add(Brick('diff', text, id=dids[path],
                      attrs={'path': path, 'added': str(add), 'removed': str(rm),
                             **({'claimed': 'no'} if path not in cov.get('matched', []) else {})}))
        for m in cited.pop(path, []): out.add(_copy(m))   # the prose that explains this file
    for rest in cited.values():
        for m in rest: out.add(_copy(m))
    if not files: out.add(Brick('note', 'No diff supplied.', id=f'{bid}-nodiff'))
    if b.refs:
        out.add(Brick('text', '## Attached'))
        for r in b.refs:
            out.add(Brick('source', '', attrs={'title': r, 'path': r.split(':', 1)[-1]}))
    checks = []
    if cov.get('unmet'): checks.append('Claimed but unchanged: ' + ', '.join(f'`{p}`' for p in cov['unmet']))
    if cov.get('tasks_open'): checks.append(f"{len(cov['tasks_open'])} task(s) still open in this change.")
    loose = coverage(doc, list(files))['unclaimed']
    if loose: checks.append('Changed but claimed by no bundle: ' + ', '.join(f'`{p}`' for p in loose))
    out.add(Brick('note', '\n\n'.join(checks) or 'Every changed file is claimed and every task is done.',
                  id=f'{bid}-checks'))
    out.add(Brick('ask', 'Does this change do what the goal says, and what would you push back on?',
                  id=f'{bid}-q', attrs={'scope': 'doc', 'budget': '40000'},
                  pins=[g.id] if (g := b.goal) is not None else []))
    from .layout import arrange
    return arrange(out, values=values)

def value(doc, changed=()):
    "Every goal, and every change that serves it."
    from .layout import arrange
    out = Canvas(meta={'title': f'Value: {doc.title}'}, path='value.canvas.md')
    served, all_b = {}, bundles(doc)
    for b in all_b: served.setdefault(b.goal.id if b.goal else '', []).append(b)
    for g in doc.of('goal'):
        out.add(Brick('text', f'## {g.body.strip().rstrip(".")}'))
        out.add(_copy(g))
        mine = served.get(g.id, [])
        for b in mine: out.add(_summary(b, changed))
        if not mine:
            out.add(Brick('note', 'Nothing in this document is serving this goal.',
                          id=f'{g.id}-nothing'))
    if (loose := served.get('', [])):
        out.add(Brick('text', '## Serving no goal'))
        for b in loose: out.add(_summary(b, changed))
    cov = coverage(doc, list(changed))
    lines = [f'{len(all_b)} change(s) across {len(doc.of("goal"))} goal(s).']
    for st in STATES:
        if (n := [b.id for b in all_b if state(b, changed) == st]): lines.append(f'{st}: ' + ', '.join(n))
    if cov['unclaimed']:
        lines.append('Changed but claimed by no bundle: ' + ', '.join(f'`{p}`' for p in cov['unclaimed']))
    out.add(Brick('text', '## Loose ends'))
    out.add(Brick('note', '\n\n'.join(lines), id='value-tally'))
    out.add(Brick('ask', 'Which of these changes actually moves the measure, and what is missing?',
                  id='value-q', attrs={'scope': 'doc', 'budget': '40000'},
                  pins=[g.id for g in doc.of('goal')]))
    return arrange(out)

def _summary(b, changed=()):
    "One change as it reads in the value view: the same bundle brick, with its facts filled in."
    return Brick('bundle', _tally(b, changed), id=b.id,
                 attrs={k: v for k, v in
                        {'title': b.title, 'goal': b.brick.attrs.get('goal', ''),
                         'contributes': b.contributes, 'status': state(b, changed),
                         'paths': ','.join(b.paths), 'refs': ','.join(b.refs)}.items() if v})
