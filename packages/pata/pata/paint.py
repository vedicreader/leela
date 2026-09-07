"The document drawn as a standalone page: both views, and the basket that feeds the model."

from __future__ import annotations
import json
from importlib.resources import files
from fastcore.all import L, Path, first

from .change import bundle_of, bundles, coverage, diff_stat
from .context import SCOPES, WRAP, _label, body_text, members, spec_of
from .doc import Doc, W, _owners

__all__ = ['payload', 'paint', 'wires']

def wires(doc):
    "The dataflow, plus the relations a brick declares that the code cannot show."
    owner, out = _owners(doc.bricks), []
    for b in doc.bricks:
        for n in b.reads:
            if (src := owner.get(n)) and src != b.id:
                out.append({'src': src, 'dst': b.id, 'rel': n})
        for rel, ids in b.links.items():
            out += [{'src': i, 'dst': b.id, 'rel': rel} for i in ids]
    seen, uniq = set(), []
    for w in out:
        k = (w['src'], w['dst'])
        if k in seen: continue
        seen.add(k)
        uniq.append(w)
    return uniq

def _bundles(doc, changed=()):
    "Each change, with what it claims and what a diff says actually moved."
    cov = {r['id']: r for r in coverage(doc, list(changed))['bundles']}
    out = []
    for b in bundles(doc):
        out.append({'id': b.id, 'title': b.title, 'region': b.brick.region, 'body': b.brick.body,
                    'goal': b.goal.id if b.goal else '', 'goalText': b.goal.body.strip() if b.goal else '',
                    'contributes': b.contributes, 'refs': b.refs, 'paths': b.paths,
                    'members': [m.id for m in b.members],
                    'tasks': [{'id': t.id, 'status': t.attrs.get('status', 'todo')} for t in b.of('task')],
                    **{k: cov.get(b.id, {}).get(k, []) for k in ('matched', 'unmet', 'tasks_open')}})
    return out

def payload(doc, values=None, changed=()):
    "Everything the prototype needs: bricks, regions, wires, and each question's scope membership."
    bricks = []
    for b in doc.bricks:
        t = body_text(b, values, doc)
        xy = b.xy or (None, None)
        bricks.append({'id': b.id, 'kind': b.kind, 'region': b.region, 'x': xy[0], 'y': xy[1],
                       'w': float(b.width or W), 'mode': b.mode, 'chars': len(t), 'text': t,
                       'heading': b.heading,
                       'label': _label(b),
                       'body': b.body, 'attrs': b.attrs, 'binds': b.binds, 'props': b.props,
                       'defs': list(b.defs), 'reads': list(b.reads),
                       'out': str((values or {}).get(b.id) or ''),
                       'reply': (r.body if (r := doc.reply_to(b.id)) is not None else ''),
                       'bundle': (u.id if (u := bundle_of(doc, b.id)) is not None else ''),
                       'stat': diff_stat(b.body) if b.kind == 'diff' else None})
    asks = {q.id: {'spec': {'scope': spec_of(q).scope, 'pins': list(q.pins), 'mutes': list(q.mutes),
                            'budget': spec_of(q).budget, 'goal': spec_of(q).goal},
                   'members': {s: [x.id for x in members(doc, q, s)] for s in SCOPES}}
            for q in doc.of('ask')}
    return {'title': doc.title, 'blocks': bricks, 'scopes': list(SCOPES), 'wrap': WRAP,
            'regions': list((getattr(doc, 'layout', None) or {}).values()), 'edges': wires(doc),
            'goal': doc.goal.id if doc.goal else '', 'prompts': asks, 'firstPrompt': first(asks) or '',
            'replies': [b.id for b in doc.of('reply')],
            'bundles': _bundles(doc, changed), 'unclaimed': coverage(doc, list(changed))['unclaimed']}

def _asset(name): return files(__package__).joinpath(name).read_text(encoding='utf-8')

def paint(
    doc,             # the document
    path=None,       # where to write the page
    shell='bare',    # `leela` draws it inside the IDE it would live in
    values=None,     # `{brick id: output text}` from the live namespace
    changed=(),      # paths a diff says moved
    **docs,          # another document per toggle, such as `review=` or `value=`
):
    "Write the prototype to `path`."
    d = payload(doc, values, changed)
    for name, other in docs.items():
        if other is not None: d[name] = payload(other, values, changed)
    html = (_asset('proto-ide.html' if shell == 'leela' else 'proto.html')
            .replace('__CSS__', _asset('proto.css'))
            .replace('__CSS2__', _asset('proto-ide.css') if shell == 'leela' else '')
            .replace('__JS__', _asset('proto.js'))
            .replace('__TITLE__', d['title'])
            .replace('__FILE__', Path(doc.path).name or 'plan.canvas.md')
            .replace('__GOAL__', doc.goal.body.strip() if doc.goal else '')
            .replace('__DATA__', json.dumps(d, ensure_ascii=False)))
    p = Path(path or 'pata.html')
    p.write_text(html, encoding='utf-8')
    return p
