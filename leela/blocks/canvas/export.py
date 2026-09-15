"Getting work out: a notebook, a plain report, or the modules the code bricks were always for."

from __future__ import annotations
import re
from fastcore.all import Path

from .doc import Brick, Canvas, KINDS, order

__all__ = ['to_ipynb', 'from_ipynb', 'to_report', 'modules', 'directives']

def _out(values, bid):
    t = str((values or {}).get(bid) or '')
    return [{'output_type': 'execute_result', 'data': {'text/plain': t}, 'metadata': {}}] if t else []

def to_ipynb(doc, values=None):
    "The document as nbformat v4."
    cells, skip = [], set()
    for b in doc.bricks:
        if b.id in skip: continue
        m = {'kind': b.kind, 'attrs': dict(b.attrs), 'binds': dict(b.binds), 'props': dict(b.props),
             'pins': list(b.pins), 'mutes': list(b.mutes)}
        if b.runs:
            cells.append({'cell_type': 'code', 'source': b.body, 'id': b.id, 'execution_count': None,
                          'outputs': _out(values, b.id), 'metadata': {'canvas': m}})
        elif b.kind == 'ask':
            r = doc.reply_to(b.id)
            if r is not None: skip.add(r.id)
            cells.append({'cell_type': 'markdown', 'source': b.body, 'id': b.id,
                          'metadata': {'leela': {'kind': 'prompt', 'reply': r.body if r else '',
                                                 'calls': [], 'usage': {}}, 'canvas': m}})
        else:
            cells.append({'cell_type': 'markdown', 'source': to_report_brick(b), 'id': b.id,
                          'metadata': {'canvas': m}})
    return {'cells': cells, 'nbformat': 4, 'nbformat_minor': 5,
            'metadata': {'kernelspec': {'name': 'python3', 'language': 'python',
                                        'display_name': 'Python 3'},
                         'canvas': dict(doc.meta)}}

def from_ipynb(nb, path=''):
    "Read a notebook in. An unmarked cell becomes a code brick or prose, which is the migration."
    doc, seen = Canvas(path=path), set()
    for c in (nb.get('cells') or []):
        src = c.get('source')
        src = ''.join(src) if isinstance(src, list) else str(src or '')
        lee = (c.get('metadata') or {}).get('leela') or {}
        pm = (c.get('metadata') or {}).get('canvas') or {}
        kind = pm.get('kind') or ('ask' if lee.get('kind') == 'prompt'
                                  else 'code' if c.get('cell_type') == 'code' else 'text')
        if kind not in KINDS: kind = 'text'
        bid = str(c.get('id') or '')
        b = Brick(kind=kind, body=src, attrs=dict(pm.get('attrs') or {}),
                  binds=dict(pm.get('binds') or {}), props=dict(pm.get('props') or {}),
                  pins=list(pm.get('pins') or []), mutes=list(pm.get('mutes') or []),
                  **({'id': bid} if bid and bid not in seen else {}))
        seen.add(b.id)
        doc.add(b)
        if kind == 'ask' and (r := str(lee.get('reply') or '')).strip():
            doc.add(Brick(kind='reply', body=r, attrs={'of': b.id}))
    doc.meta = dict((nb.get('metadata') or {}).get('canvas') or {})
    return doc

def to_report_brick(b):
    "One brick as plain markdown, for a reader who has never heard of a canvas."
    if b.kind == 'goal':
        bits = [f'**{k}**: {v}' for k, v in b.attrs.items()
                if k in ('measure', 'baseline', 'target', 'by')]
        return '\n\n'.join(x for x in [b.body.strip(), '  \n'.join(bits)] if x)
    if b.kind == 'task':
        owner = f" ({b.attrs['owner']})" if b.attrs.get('owner') else ''
        return f"- [{'x' if b.attrs.get('status') == 'done' else ' '}] {b.body.strip()}{owner}"
    if b.kind == 'source':
        where = b.attrs.get('url') or b.attrs.get('path') or ''
        head = f'[{b.title or where}]({where})' if where else (b.title or '')
        return '\n\n'.join(x for x in [f'> {head}'.strip('> '), b.body.strip()] if x)
    if b.runs: return f'```python\n{b.body.strip()}\n```'
    if b.kind == 'ask': return f'**{b.body.strip()}**'
    if b.kind in ('brick', 'sim', 'data'):
        return f"`{b.attrs.get('src') or b.kind}`" + ''.join(f'\n- `{k}` = `{v}`'
                                                             for k, v in b.binds.items())
    return b.body.strip()

def to_report(doc, code=True):
    "The document as a report. `code` keeps the code bricks; without it, only the narrative."
    out = [to_report_brick(b) for b in doc.bricks if code or not b.runs]
    return '\n\n'.join(x for x in out if x.strip()) + '\n'

_DIRECT = re.compile(r'^#\|\s*(\S+)(?:\s+(\S+))?\s*$', re.M)

def directives(source):
    "The nbdev `#|` lines a code brick opens with, as `{name: value}`."
    head = []
    for line in (source or '').splitlines():
        if not line.lstrip().startswith('#|'): break
        head.append(line)
    return {m.group(1): (m.group(2) or '') for m in _DIRECT.finditer('\n'.join(head))}

def _body(source):
    lines = (source or '').splitlines(True)
    n = 0
    while n < len(lines) and lines[n].lstrip().startswith('#|'): n += 1
    return ''.join(lines[n:]).strip('\n')

def modules(doc, default=None):
    "`{relative path: source}` for the code bricks marked `#|export`."
    default = default or doc.meta.get('default_exp') or ''
    for b in doc.of('code'):
        if (d := directives(b.body)).get('default_exp'): default = d['default_exp']
    out = {}
    for b in order(doc.bricks):
        d = directives(b.body)
        mod = d.get('export') or d.get('exporti') or (default if 'export' in d or 'exporti' in d else '')
        if not mod: continue
        out.setdefault(mod.replace('.', '/') + '.py', []).append(_body(b.body))
    head = f'"""Generated from {Path(doc.path).name or "a dynamic document"}."""\n'
    return {p: head + '\n' + '\n\n'.join(v) + '\n' for p, v in out.items()}
