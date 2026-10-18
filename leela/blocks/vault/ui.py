from __future__ import annotations

import json, re
from datetime import datetime
from urllib.parse import urlencode

from fasthtml.common import (Article, Button, Code, Datalist, Details, Div, Form, Hidden, Input, Label,
                             Mark, Option, Pre, Progress, Section, Select, Small, Span, Strong,
                             Summary, Table, Tbody, Td, Textarea, Th, Thead, Tr)

from ..memory.memory import source_kind
from ..memory.vaults import ACCESS
from .acquire import ACTIONS
from .jobs import cadence
from .news import news_rows

__all__ = ['job_card', 'pii_badge', 'vault_panel', 'vault_browse', 'vault_docs', 'vault_tree',
           'tidy_list', 'watch_list', 'workbench', 'browse_view', 'find_view', 'add_view',
           'news_view', 'specs_view', 'creds_panel', 'creds_view', 'topics_view', 'import_plan',
           'ops_table', 'call_form', 'call_panel', 'api_result', 'PII_COVERS',
           'VIEWS', 'SOURCES', 'SCOPES', 'HOME', 'KINDS', 'review_view', 'library_view', 'sources_view', 'vault_settings']

POLL_MS = 1200
LEVELS = (('open', 'Open'), ('personal', 'Personal'), ('local', 'Local only'))

PII_COVERS = ('covers pattern kinds and titled names — a bare name or loose address is never '
              'looked for, so this says what was found, never that there is nothing')

VIEWS = (('library', 'what is in it, and putting more in'), ('find', 'search it'),
         ('review', 'proofreading and personal information to decide'), ('sources', 'feeds, apis and topics'))
SOURCES = (('news', 'what the feeds said'), ('specs', 'ask an api'), ('topics', 'what it is about'))
#: The workbench's old section names, and the tab each now sits under. A saved tab still opens where it was.
HOME = {'browse': 'library', 'add': 'library', 'library': 'library', 'find': 'find', 'review': 'review', 'sources': 'sources',
        **{k: 'sources' for k, _ in SOURCES}}

KINDS = {'pdf': '▤', 'web': '◍', 'html': '◍', 'htm': '◍', 'news': '⚑', 'rss': '⚑',
         'code': '⌘', 'codebase': '⌘', 'api': '⚙', 'api_spec': '⚙', 'json': '⚙', 'yaml': '⚙',
         'arxiv': '✎', 'youtube': '▶', 'note': '✎', 'agent-note': '✎', 'agent-state': '◆',
         'research': '✦', 'image': '▣', 'png': '▣', 'jpg': '▣', 'data': '▦', 'csv': '▦',
         'md': '▪', 'markdown': '▪', 'txt': '▪', 'rst': '▪', 'ipynb': '◈'}

def _js(*args): return ', '.join(json.dumps(str(a or '')) for a in args)

def _q(**kw): return urlencode({k: v for k, v in kw.items() if v not in (None, '')})

def _glyph(kind): return KINDS.get(str(kind or '').lower(), '▪')

def _when(ts):
    if not ts: return 'never'
    return datetime.fromtimestamp(float(ts)).strftime('%a %d %b, %H:%M')

def empty(title, body, *extra):
    return Div(Strong(title), Span(body), *extra, cls='lee-wb-empty')

def _kinds(kinds):
    return ', '.join(f'{k}×{n}' for k, n in sorted((kinds or {}).items(), key=lambda kv: -kv[1])[:4])

def pii_badge(report):
    if not report.get('doc_id') and report.get('note'): return Span('pii unavailable', cls='lee-pii', title=report['note'])
    if not report.get('has_pii'): return Span('no pattern found', cls='lee-pii clear', title=PII_COVERS)
    # forced private is the case with nothing to count: what was found is that somebody said so
    return Span(_kinds(report.get('kinds')) or 'marked personal', cls='lee-pii found', title=PII_COVERS)

def _clip_pii_badge(pii):
    docs = pii.get('documents') or []
    if not docs: return Span('no pattern found', cls='lee-pii clear', title=PII_COVERS)
    return Span(f"pii in {len(docs)} document{'' if len(docs) == 1 else 's'} · {_kinds(pii.get('kinds'))}",
        cls='lee-pii found', title=PII_COVERS)

def _one_line(k, v):
    if isinstance(v, list):
        shown = ', '.join(map(str, v[:3])) + ('…' if len(v) > 3 else '')
        return f'{k}: {len(v)}' + (f' · {shown}' if v else '')
    if isinstance(v, dict): return f'{k}: ' + ', '.join(f'{a}={b}' for a, b in list(v.items())[:6])
    return f'{k}: {v}'

def _summarise(result, mx=40):
    if not isinstance(result, dict): return str(result)[:2000]
    return '\n'.join(_one_line(k, v) for k, v in list(result.items())[:mx])

def job_card(job):
    d = job.dict()
    active = d['active']
    attrs = dict(hx_get=f"/jobs/{d['id']}", hx_trigger=f'load delay:{POLL_MS}ms', hx_swap='outerHTML') if active else {}
    body = [Span(d['kind'], cls='lee-job-kind'), Span(d['status'], cls=f"lee-job-status {d['status']}"),
        Span(d['target'] or '', cls='lee-job-target', title=d['target'] or '')]
    if active:
        body.append(Progress(value=str(round(d['progress'] or 0, 3)), max='1', cls='lee-job-bar'))
        if d['current']: body.append(Span(d['current'], cls='lee-job-current'))
        if (d['params'] or {}).get('_cancel'):
            body.append(Form(Button('cancel', cls='lee-btn warn', data_job_cancel=d['id']), hx_post=f"/jobs/{d['id']}/cancel",
                             hx_target='closest .lee-job', hx_swap='outerHTML'))
        else: body.append(Span('committed documents are searchable while this runs', cls='lee-job-note'))
    if d['error']:
        body.append(Span(d['error'], cls='lee-job-error'))
        body.append(Form(Button('retry', cls='lee-btn'), hx_post=f"/jobs/{d['id']}/retry",
            hx_target='closest .lee-job', hx_swap='outerHTML'))
        body.append(Form(Button('dismiss', cls='lee-btn'), hx_post=f"/jobs/{d['id']}/forget",
            hx_target='closest .lee-job', hx_swap='delete'))
    result = d['result'] if isinstance(d['result'], dict) else {}
    if pii := result.get('pii'): body.append(_clip_pii_badge(pii))
    doc = result.get('doc_id') or (d['target'] if d['kind'] in ('reparse', 'proof') or (d['params'] or {}).get('again') else '')
    if d['kind'] in ('read', 'reparse', 'proof', 'book') and doc and not d['error']:
        title = result.get('title') or d['target'].rsplit('/', 1)[-1]
        body.append(Button('open', cls='lee-btn go', onclick=f"leeOpenVaultDoc({_js(doc, result.get('shelf'), result.get('vault'), title)})"))
        if d['kind'] == 'proof': body.append(Button('review', cls='lee-btn', onclick=f"leeVaultReview({_js(doc, result.get('shelf'), result.get('vault'))})"))
        if result.get('blocked'): body.append(Span(f"{len(result['blocked'])} page(s) not sent to {result.get('model') or 'the model'}", cls='lee-job-note'))
        said = [f"{result['model_pages']} page(s) read by model" if result.get('model_pages') else '',
                f"{result['changes']} change(s) filed, {result.get('proposed', 0)} proposed" if 'changes' in result else '',
                f"{result['chapters']} chapter(s), {result.get('verses', 0)} verse(s), {result.get('problems', 0)} problem(s) to check" if 'chapters' in result else '',
                f"${result['cost']:.4f}" if result.get('cost') else '']
        if s := ' · '.join(x for x in said if x): body.append(Span(s, cls='lee-job-cost'))
    if d['status'] == 'cancelled':
        n = len(result.get('unread') or [])
        body.append(Span(f"cancelled: the pages read are kept, {n} not read. Pages in flight when it stopped are counted in the cost."
                         ' Allow once does not carry over to a resume.', cls='lee-job-note'))
        if n: body.append(Form(Button('resume', cls='lee-btn'), hx_post=f"/jobs/{d['id']}/retry", hx_target='closest .lee-job', hx_swap='outerHTML'))
    if d['result']: body.append(Details(Summary('details'), Pre(_summarise(d['result']), cls='lee-job-result')))
    return Div(*body, cls=f"lee-job {d['status']}", id=f"job-{d['id']}", data_kind=result.get('kind') or None, **attrs)

def _why(row, n=3):
    feats = sorted(((k, v) for k, v in row.items() if isinstance(v, (int, float)) and k != 'score'),
        key=lambda kv: -abs(kv[1]))[:n]
    return ' · '.join(f'{k} {v:+.1f}' for k, v in feats) or 'ranked with no standout feature'

def _judge(doc, shelf, noisy, label, cls):
    return Form(Hidden(name='doc', value=doc), Hidden(name='shelf', value=shelf),
        Hidden(name='noisy', value=str(noisy).lower()), Button(label, cls=cls, type='submit'),
        hx_post='/vault/noisy', hx_target='closest .lee-tidy-row', hx_swap='outerHTML')

def _pii_slot(doc, shelf=''):
    return Span('scanning…', cls='lee-pii pending', hx_trigger='revealed', hx_swap='outerHTML',
        hx_get='/vault/pii/badge?' + _q(doc=doc, shelf=shelf))

def _tidy_row(row, shelf=''):
    doc = str(row.get('doc_id') or '')
    return Div(Span(row.get('title') or doc, cls='lee-tidy-title', title=doc),
        Span(f"{row.get('score') or 0:.2f}", cls='lee-tidy-score', title=_why(row)),
        _pii_slot(doc, shelf),
        _judge(doc, shelf, True, 'drop', 'lee-btn warn'), _judge(doc, shelf, False, 'keep', 'lee-btn'),
        cls='lee-tidy-row')

def tidy_list(memory, shelf='', k=20):
    "What the vault thinks dilutes retrieval. Judged documents are already excluded from it."
    rows = memory.noisy_candidates(shelf=shelf or None, k=k)
    body = ([_tidy_row(r, shelf) for r in rows] if rows else
            [Div('Nothing looks like noise, or the shelf is too small to have an opinion.', cls='lee-vault-empty')])
    return Div(*body, id='vaulttidy', cls='lee-vault-tidyrows')

def _watch_row(w):
    every = w.get('every') or 0
    return Div(Span(w.get('action', ''), cls='lee-watch-action'),
        Span(str(w.get('target', ''))[:60], cls='lee-watch-target', title=str(w.get('target', ''))),
        Span(f'every {round(every / 3600, 1)}h' if every else '', cls='lee-watch-every'),
        Form(Hidden(name='watch_id', value=w.get('id', '')), Button('stop', cls='lee-btn warn', type='submit'),
            hx_post='/vault/unwatch', hx_target='#vaultwatches', hx_swap='outerHTML'),
        cls='lee-watch-row')

def watch_list(watches):
    rows = [_watch_row(w) for w in watches] or [Div('Nothing on a cadence.', cls='lee-vault-empty')]
    return Div(*rows, id='vaultwatches', cls='lee-vault-watches')

def _ask_button(doc, shelf, vault, title, label='ask'):
    return Button(label, cls='lee-btn lee-vault-ask', title='attach this to the next question',
        data_doc=doc, data_shelf=shelf, data_vault=vault, data_title=title,
        onclick='leeVaultAsk(this)')

def _doc_row(d, vault='', depth=0):
    "One document, opening the reader tab. `onclick`, because the tab is mounted by the client."
    doc, shelf = d.get('doc_id') or d.get('id'), d.get('shelf', '')
    filed = source_kind(d.get('source')) == 'file'
    title = d.get('title') or doc
    return Div(Span(_glyph(d.get('kind')), cls='lee-vault-glyph', title=str(d.get('kind') or 'document')),
        Button(title, cls='lee-vault-doc', onclick=f'leeOpenVaultDoc({_js(doc, shelf, vault, title)})'),
        *([Button('file', cls='lee-vault-openfile', title=str(d.get('source') or ''),
                  onclick=f'leeOpenVaultFile({_js(doc, shelf, vault)})')] if filed else []),
        _type_chip(d.get('meta') or {}),
        _ask_button(doc, shelf, vault, title),
        Span(shelf, cls='lee-shelf-count'),
        style=f'--depth:{depth}', cls='lee-vault-docrow')

def _type_chip(m):
    "The document's type; a proposal waiting on a person is dashed, and an untyped document says so."
    dt, pr = m.get('doctype'), m.get('doctype_proposed')
    if dt: return Span(dt.replace('_', ' '), cls='lee-vault-type', title=f"type · {m.get('doctype_by') or ''}")
    if pr: return Span(pr.replace('_', ' '), cls='lee-vault-type proposed', title='proposed: decide it under Review > Types')
    return Span('untyped', cls='lee-vault-type none', title='no type yet')

def _hit_row(h, vault=''):
    "A search hit opens the document it is in; the breadcrumb says which part matched."
    doc, shelf = str(h.get('node_id') or '').split('#')[0], h.get('shelf', '')
    title = h.get('breadcrumb') or h.get('title') or doc
    return Div(Span('▸', cls='lee-vault-glyph'),
        Button(title, cls='lee-vault-doc', onclick=f'leeOpenVaultDoc({_js(doc, shelf, vault, title)})'),
        _ask_button(doc, shelf, vault, title),
        Span(shelf, cls='lee-shelf-count'), cls='lee-vault-docrow')

def vault_docs(memory, q='', vault='', shelf='', limit=60):
    "The browse/search fragment: what is in the vault, or what matched."
    rows = (memory.search_all(q, limit=limit, shelves=[shelf] if shelf else None) if q.strip()
            else memory.all_documents(limit=limit, shelves=[shelf] if shelf else None))
    body = ([(_hit_row if q.strip() else _doc_row)(r, vault) for r in rows] if rows else
            [Div('Nothing here yet. Clip a document, or attach a vault.', cls='lee-vault-empty')])
    return Div(*body, id='vaultdocs', cls='lee-vault-docs')

def _group_of(row):
    "Which top-level group a document belongs under, and the path it occupies inside it."
    src = str(row.get('source') or '')
    kind = source_kind(src)
    if kind == 'file': return 'files', src
    if kind == 'url': return 'web', src.split('://', 1)[-1]
    return 'notes', str(row.get('title') or row.get('doc_id') or '')

def _strip_prefix(paths):
    parts = [p.split('/') for p in paths]
    if not parts: return 0
    common = 0
    for seg in zip(*[p[:-1] for p in parts]):
        if len(set(seg)) != 1: break
        common += 1
    return common

def _placed(memory, shelf='', limit=2000):
    rows = memory.all_documents(limit=limit, shelves=[shelf] if shelf else None)
    by_shelf = {}
    for r in rows: by_shelf.setdefault(str(r.get('shelf') or 'main'), []).append(r)
    out = []
    for name, items in sorted(by_shelf.items()):
        groups = {}
        for r in items:
            group, path = _group_of(r)
            groups.setdefault(group, []).append((r, path.strip('/')))
        solo = len(groups) == 1
        for group, gi in groups.items():
            cut = _strip_prefix([p for _, p in gi]) if group == 'files' else 0
            for r, path in gi:
                rest = '/'.join(path.split('/')[cut:])
                out.append((f'{name}/' + ('' if solo else f'{group}/') + rest, r))
    return out

def _nest(placed):
    root = {}
    for key, r in placed:
        parts = key.split('/')
        node = root
        for part in parts[:-1]: node = node.setdefault(part, {})
        node.setdefault('', []).append((parts[-1], r))
    return root

def _tree_rows(node, vault, at='', open_folders=(), depth=0, elid='vaultbrowse', notes=None):
    out = []
    for name in sorted(k for k in node if k != ''):
        path = f'{at}/{name}'.strip('/')
        opened = path in open_folders
        nxt = tuple(x for x in open_folders if x != path) if opened else (*open_folders, path)
        out.append(Button(Span('▾' if opened else '▸', cls='lee-vault-caret'), Span(name),
            *([Span((notes or {}).get(name, ''), cls='lee-shelf-count')] if depth == 0 and notes else []),
            cls='lee-vault-folder' + (' shelf' if depth == 0 else ''), style=f'--depth:{depth}',
            aria_expanded=str(opened).lower(),
            hx_get='/vault/tree', hx_target=f'#{elid}tree', hx_swap='outerHTML',
            hx_vals=json.dumps({'vault': vault, 'open': '|'.join(nxt), 'elid': elid})))
        if opened: out += _tree_rows(node[name], vault, path, open_folders, depth + 1, elid, notes)
    for _, r in sorted(node.get('', []), key=lambda x: x[0].lower()):
        out.append(_doc_row(r, vault, depth))
    return out

def vault_tree(memory, vault='', shelf='', open_folders=None, limit=2000, elid='vaultbrowse'):
    placed = _placed(memory, shelf, limit)
    node = _nest(placed)
    counts = {}
    for key, _ in placed: counts[key.split('/')[0]] = counts.get(key.split('/')[0], 0) + 1
    notes = {k: f"{n} doc{'' if n == 1 else 's'}" for k, n in counts.items()}
    if open_folders is None: open_folders = tuple(k for k in node if k != '')
    rows = _tree_rows(node, vault, '', tuple(open_folders), 0, elid, notes)
    return Div(*(rows or [Div('Nothing here yet. Clip a document, or attach a vault.',
                              cls='lee-vault-empty')]),
               id=f'{elid}tree', cls='lee-vault-tree')

def vault_browse(memory, q='', vault='', shelf='', limit=60, open_folders=None, elid='vaultbrowse'):
    return Div(Span(f'documents · {vault}' if vault else 'documents', cls='lee-vault-legend'),
        Form(Hidden(name='vault', value=vault), Hidden(name='shelf', value=shelf),
            Hidden(name='open', value='|'.join(open_folders) if open_folders is not None else ''),
            Hidden(name='elid', value=elid),
            Input(name='q', value=q, cls='lee-input', placeholder='search this vault…', autocomplete='off'),
            Button('search', cls='lee-btn go', type='submit'), cls='lee-clip-form',
            hx_get='/vault/browse', hx_target=f'#{elid}', hx_swap='outerHTML'),
        vault_docs(memory, q, vault, shelf, limit) if q.strip()
            else vault_tree(memory, vault, shelf, open_folders, elid=elid),
        id=elid, cls='lee-vault-browse')

def _clip_form(target, kind, label, hint, into='#vaultwbjobs'):
    return Form(Input(name='target', cls='lee-input', value=target or '', placeholder=hint, autocomplete='off'),
        Hidden(name='kind', value=kind), Button(label, cls='lee-btn go', type='submit'),
        cls='lee-clip-form', hx_post='/clip', hx_target=into, hx_swap='afterbegin')

def _vault_row(r):
    name, act = r['name'], ('lee-shelf-name mine' if r['active'] else 'lee-shelf-name')
    hid = Hidden(name='name', value=name)
    return Div(Button(name, cls=act + ' lee-vault-open', title=f"{r['path']} — browse this vault",
            hx_get='/vault/browse', hx_vals=json.dumps({'vault': name}),
            hx_target='#vaultbrowse', hx_swap='outerHTML'),
        Span('●', cls='lee-shelf-count lee-vault-active', title='the active vault') if r['active'] else
        Form(hid, Button('○', cls='lee-btn lee-vault-use', type='submit',
                         title='make this the active vault'),
             hx_post='/vault/activate', hx_target='#vaultpanel', hx_swap='none'),
        Form(Hidden(name='name', value=name),
             Select(*[Option(a, value=a, selected=a == r['access']) for a in ACCESS],
                    name='access', cls='lee-input', onchange='this.form.requestSubmit()'),
             hx_post='/vault/access', hx_target='closest .lee-shelf-row', hx_swap='none'),
        Form(Hidden(name='name', value=name), Hidden(name='agent', value=str(not r['agent']).lower()),
             Button('agent ' + ('on' if r['agent_writable'] else 'off'),
                    cls='lee-btn' + (' go' if r['agent_writable'] else ''), type='submit',
                    title='whether the model may write here'),
             hx_post='/vault/access', hx_target='#vaultpanel', hx_swap='none'),
        *([] if r['reserved'] else [Form(hid, Button('detach', cls='lee-btn warn', type='submit'),
             hx_post='/vault/detach', hx_target='#vaultpanel', hx_swap='none')]),
        cls='lee-shelf-row')

def vault_panel(memory, jobs, active_path='', root='', vaults=None):
    "The rail is a way to the Vault tab now: everything it held lives in Library. `#vaultjobs` stays for old targets."
    return Section(
        Div(Span('vault', cls='lee-ptitle'), Span(memory.note or '', cls='lee-keyscope'), Span(cls='lee-spacer'),
            Button('open Vault', cls='lee-btn go', title='browse, read and find in the Vault tab',
                   onclick='leeVaultWorkbench()'), cls='lee-phead'),
        Div(*[job_card(j) for j in jobs.all(limit=4)], id='vaultjobs', cls='lee-vault-jobs'),
        cls='lee-panel lee-vault', id='vaultrail')

def vault_settings(memory, vaults=None):
    "Library's settings: which vaults are attached, cadence and tidy. The rail's, moved."
    return Section(
        Div(Span('vaults', cls='lee-vault-legend'),
            *[_vault_row(r) for r in (vaults or {}).get('vaults', [])],
            Form(Input(name='path', cls='lee-input', placeholder='path to a vault.db, or a folder for a new one'),
                Input(name='name', cls='lee-input lee-every', placeholder='name', size='6'),
                Button('attach', cls='lee-btn', type='submit', formaction='/vault/attach'),
                Button('create', cls='lee-btn go', type='submit', formaction='/vault/create'),
                cls='lee-clip-form', hx_post='/vault/attach', hx_target='#vaultpanel', hx_swap='none'),
            Button('find vaults', cls='lee-btn lee-vault-find', hx_get='/vault/find',
                   hx_target='#vaultfound', hx_swap='outerHTML'),
            Div(id='vaultfound', cls='lee-vault-found-rows'),
            cls='lee-vault-vaults'),
        Div(Span('privacy', cls='lee-vault-legend'),
            Label('floor', Select(*[Option(l, value=v, selected=v == memory.floor()) for v, l in LEVELS], name='privacy', cls='lee-input',
                                  data_vault_floor='1', data_was=memory.floor(), onchange='leeVaultFloor(this)',
                                  title='the level no document in this vault goes below; only a person lowers it')),
            Button('what left this machine', cls='lee-btn', onclick='leeVaultSends({})',
                   title='every page and section sent to a hosted model, which model, and under what policy'),
            cls='lee-vault-privacy-floor'),
        Div(Span('cadence', cls='lee-vault-legend'),
            Form(Input(name='target', cls='lee-input', autocomplete='off', placeholder='a url to re-read, or a reminder'),
                Select(*[Option(a, value=a) for a in ('url', 'remind', 'web', 'crawl')],
                    name='action', cls='lee-input'),
                Input(name='every', cls='lee-input lee-every', value='1d', size='4'),
                Button('watch', cls='lee-btn go', type='submit'),
                cls='lee-clip-form', hx_post='/vault/watch', hx_target='#vaultwatches', hx_swap='outerHTML'),
            watch_list(memory.watches()),
            cls='lee-vault-cadence'),
        Div(Span('tidy', cls='lee-vault-legend'),
            Button('review', cls='lee-btn', title='what the vault thinks dilutes search',
                hx_get='/vault/tidy/list', hx_target='#vaulttidy', hx_swap='outerHTML'),
            Button('re-index changed', cls='lee-btn', title='re-read clipped files that changed on disk',
                hx_post='/vault/reindex', hx_target='#vaulttidy', hx_swap='outerHTML'),
            Div(id='vaulttidy', cls='lee-vault-tidyrows'),
            cls='lee-vault-tidy'),
        cls='lee-panel lee-vault', id='vaultpanel')

def _swap(view, vault='', **kw):
    return dict(hx_get='/vault/view/' + view + (('?' + q) if (q := _q(vault=vault, **kw)) else ''),
                hx_target='#vaultwbbody', hx_swap='innerHTML')

def _metric(label, value): return Div(Strong(f'{value:,}' if isinstance(value, int) else str(value)),
                                      Span(label), cls='lee-wb-metric')

def _tabs_js(cls):
    return {'hx-on::after-request': f"this.parentNode.querySelectorAll('.{cls}')"
                                    ".forEach(b=>b.classList.remove('active'));this.classList.add('active')"}

def sources_view(body, view='news', vault=''):
    "News, specs and topics, one tab: each is a source the vault reads from rather than a place it keeps things."
    view = view if view in dict(SOURCES) else 'news'
    return Div(Div(*[Button(n, cls='lee-wb-subtab' + (' active' if n == view else ''), title=why, **_swap(n, vault),
                            **_tabs_js('lee-wb-subtab')) for n, why in SOURCES], cls='lee-wb-subtabs', role='tablist'),
               body, cls='lee-wb-sources')

def library_view(memory, vault='', shelf='', q='', jobs=None, root='', vaults=None, **_):
    "What is in the vault, and every way of putting more in: one box that reads a file or fetches an address."
    add = Form(Input(name='src', cls='lee-input', autocomplete='off', required=True,
                     placeholder='a PDF or page image to read, a folder, or an address to fetch'),
               Button('add', cls='lee-btn go', type='submit'), data_vault_add='1', cls='lee-wb-addbox',
               onsubmit='event.preventDefault();leeVaultAdd(this)')
    more = Details(Summary('more ways in'), add_view(memory, vault, jobs=jobs, root=root),
                   Div(_clip_form(root, 'clip_codebase', 'codebase', 'a repository root'),
                       _clip_form('', 'clip_api_spec', 'api spec', 'an OpenAPI url or path (JSON or YAML)'),
                       cls='lee-wb-card'), cls='lee-wb-more')
    settings = Details(Summary('settings'), vault_settings(memory, vaults.dict() if vaults else None), cls='lee-wb-more')
    types = Button('type untyped documents', cls='lee-btn', data_vault=vault, onclick='leeVaultGuessTypes(this)',
                   title='from their words alone: no model is asked, so nothing leaves this machine')
    return Div(Div(add, more, settings, types, cls='lee-wb-libhead'), browse_view(memory, vault, shelf=shelf, q=q), cls='lee-wb-library')

def workbench(memory, vaults, view='library', body=None, **kw):
    "The Vault tab: which vault, which section, and the section itself."
    stats, names = memory.vault_stats(), vaults.dict()
    active, home = names.get('active', ''), HOME.get(view, 'library')
    picker = Select(*[Option(r['name'], value=r['name'], selected=r['name'] == active)
                      for r in names.get('vaults', [])], cls='lee-input lee-wb-vault',
                    aria_label='which vault', title=str(memory.path), name='name',
                    hx_post='/vault/activate', hx_vals='{"wb": true}', hx_trigger='change',
                    hx_target='#vaultwb', hx_swap='outerHTML')
    tabs = [Button(name, cls='lee-wb-tab' + (' active' if name == home else ''), title=why,
                   **_swap(name, active), **_tabs_js('lee-wb-tab'))
            for name, why in VIEWS]
    return Div(
        Div(Span('Vault', cls='lee-wb-mark'), picker,
            Div(*tabs, cls='lee-wb-tabs', role='tablist', aria_label='vault sections'),
            Span(cls='lee-spacer'),
            Div(_metric('documents', stats['docs']), _metric('sections', stats['nodes']),
                _metric('chunks', stats['chunks']), _metric('shelves', stats['shelves']),
                _metric('encoder', stats['encoder']), cls='lee-wb-metrics'),
            cls='lee-wb-head'),
        Div(body if body is not None else library_view(memory, kw.pop('vault', active), vaults=vaults, **kw),
            id='vaultwbbody', cls='lee-wb-body'),
        id='vaultwb', cls='lee-wb', data_view=view)

def _shelf_rail(memory, vault='', shelf=''):
    rows = [Button(Span(s['store'].replace('_', ' ')), Span(str(s.get('docs', 0)), cls='lee-shelf-count'),
                   cls='lee-wb-shelf' + (' active' if s['store'] == shelf else ''),
                   **_swap('browse', vault, shelf='' if s['store'] == shelf else s['store']))
            for s in memory.shelves()]
    return Div(Span('shelves', cls='lee-vault-legend'),
        Button('everything', cls='lee-wb-shelf' + ('' if shelf else ' active'), **_swap('browse', vault)),
        *rows, cls='lee-wb-rail')

def browse_view(memory, vault='', shelf='', q='', limit=200, **_):
    "What is in the vault: the shelves down one side, the documents beside them."
    rows = memory.all_documents(limit=limit, shelves=[shelf] if shelf else None)
    filt = Input(cls='lee-input lee-wb-filter', placeholder='filter these documents…', autocomplete='off',
                 oninput='leeVaultFilter(this)', aria_label='filter documents')
    docs = ([_doc_row(r, vault) for r in rows] if rows else
            [empty('nothing on this shelf yet', 'put something in from Add, or clip a file from the rail.')])
    return Div(_shelf_rail(memory, vault, shelf),
        Div(Div(filt, Span(f'{len(rows)} shown', cls='lee-wb-count'), cls='lee-wb-filterbar'),
            Div(*docs, cls='lee-vault-docs lee-wb-docs'), cls='lee-wb-main'),
        cls='lee-wb-split')

def _jump(h):
    "Where opening a hit lands: its page, and words to find on it."
    return json.dumps(dict(page=h.get('page'), quote=' '.join(str(h.get('snippet') or '').split())[:80]))

def _hit(h, vault, q):
    "One hit, with the legs that ranked it and the two things worth doing with it."
    # Opening wants the document the section is in; attaching wants the section itself.
    node, shelf = str(h.get('node_id') or ''), h.get('shelf', '')
    doc = node.split('#')[0]
    title = h.get('breadcrumb') or h.get('title') or doc
    legs = [Span(f"p. {h['page'] + 1}", cls='lee-wb-leg') if isinstance(h.get('page'), int) else None,
            Span(f"kw #{h['fts_rank']}", cls='lee-wb-leg kw') if h.get('fts_rank') else None,
            Span(f"vec #{h['vector_rank']}", cls='lee-wb-leg vec') if h.get('vector_rank') else None,
            Span(f"{float(h.get('score') or 0):.3f}", cls='lee-wb-leg')]
    return Div(Div(Button(title, cls='lee-vault-doc',
                          onclick=f'leeOpenVaultDoc({_js(doc, shelf, vault, title)}, {_jump(h)})'),
                   Span(cls='lee-spacer'), *[x for x in legs if x is not None], cls='lee-wb-hithead'),
        Div(*_highlight(h.get('snippet') or '', q), cls='lee-wb-snippet'),
        Div(Span(shelf, cls='lee-shelf-count'), _ask_button(node, shelf, vault, title, 'ask about this'),
            cls='lee-wb-hitfoot'),
        cls='lee-wb-hit')

def _highlight(text, query):
    "The query's own words, marked in the snippet that matched them."
    terms = [x for x in dict.fromkeys(re.findall(r"[\w’-]+", query.lower())) if len(x) > 2]
    if not terms: return [Span(text or '')]
    pat = re.compile('(' + '|'.join(map(re.escape, sorted(terms, key=len, reverse=True))) + ')', re.I)
    return [Mark(part) if pat.fullmatch(part) else Span(part) for part in pat.split(text or '') if part]

def review_view(vault='', doc='', shelf='', mode='', **_):
    "The Review queue: a mount point review.js fills from `/vault/changes`, `/vault/pii/findings`, `/vault/types` and `/vault/book/problems`."
    return Div(Div('loading the queue', cls='lee-dim'), cls='lee-vault-review', tabindex='0', data_vault=vault, data_doc=doc, data_shelf=shelf,
               data_mode=mode if mode in ('proof', 'pii', 'types', 'book') else 'proof')

SCOPES = (('vault', 'whole vault'), ('doc', 'this document'), ('pages', 'pages'))

def find_view(memory, vault='', q='', shelf='', doc='', title='', pages='', scope='', limit=30, **_):
    "One box over the whole vault, one document or pages of it: sections to open, and an answer that cites them."
    from ..memory.memory import VaultRefused, page_list
    scope = 'vault' if not doc else scope if scope in dict(SCOPES) else 'doc'
    chip = Select(*[Option(f'{l}: {title or doc}' if k == 'doc' else l, value=k, selected=k == scope) for k, l in SCOPES if doc or k == 'vault'],
                  name='scope', cls='lee-input lee-wb-scope', aria_label='where to look', data_find_scope='1', onchange='leeVaultScope(this)')
    form = Form(Input(name='q', value=q, cls='lee-input', autocomplete='off', autofocus=True,
                      placeholder='a phrase, a requirement, a concept, or a question to ask'),
        chip, Input(name='pages', value=pages, cls='lee-input lee-wb-pages', placeholder='3-9', size='5', aria_label='pages',
                    hidden=scope != 'pages'),
        Hidden(name='vault', value=vault), Hidden(name='shelf', value=shelf), Hidden(name='doc', value=doc), Hidden(name='title', value=title),
        Button('search', cls='lee-btn go', type='submit'),
        Button('ask', cls='lee-btn', type='button', data_find_ask='1', title='an answer from these sections, with citations',
               onclick='leeVaultAskFind(this)'),
        hx_get='/vault/view/find', hx_target='#vaultwbbody', hx_swap='innerHTML', cls='lee-wb-search', data_vault_find='1')
    head = (form, Div(cls='lee-vault-sendline', data_send='1', role='status', hidden=True),
            Div(cls='lee-wb-answer', data_answer='1', aria_live='polite', hidden=True))
    if not q.strip():
        return Div(*head, empty('search the vault, or ask it',
            'results combine keyword rank and embedding rank. a hit is a section, so you can open exactly the part that matched. '
            'ask answers from the sections in scope and cites them; a citation opens the page it came from.'), cls='lee-wb-find')
    try: hits = memory.find(q, limit, doc if scope != 'vault' else None, shelf, page_list(pages) if scope == 'pages' else None)
    except VaultRefused as e: return Div(*head, Div(str(e), cls='lee-job-error', data_kind=e.kind), cls='lee-wb-find')
    body = ([_hit(h, vault, q) for h in hits] if hits else
            [empty(f'nothing matched “{q}”', 'try fewer words, or a wider scope.')])
    foot = Div(Span(memory.note or '', cls='lee-keyscope'), Span(cls='lee-spacer'),
               Button('attach every hit to the next question', cls='lee-btn',
                      onclick='leeVaultAskAll(this)'), cls='lee-wb-findfoot') if hits else None
    return Div(*head, foot, Div(*body, cls='lee-wb-hits'), cls='lee-wb-find')

def import_plan(plan):
    "What indexing a folder would do, before it does it."
    shelves = Div(*[Div(Strong(k), Span(f'{n} files')) for k, n in sorted(plan.shelves.items())],
                  cls='lee-wb-plan-shelves')
    cats = Div(*[Span(f'{k} · {n}', cls='lee-wb-badge') for k, n in sorted(plan.categories.items())],
               cls='lee-wb-plan-cats')
    sample = Details(Summary(f'files to index ({len(plan.files)})'),
        Div(*[Div(Span(x.relative), Small(f'{x.shelf} · {x.category}')) for x in plan.files[:100]],
            cls='lee-wb-plan-files'))
    skipped = (Details(Summary(f'generated paths left out ({len(plan.skipped)})'),
        Div(*[Div(str(p.relative_to(plan.root))) for p in plan.skipped[:100]], cls='lee-wb-plan-files'))
               if plan.skipped else None)
    run = Form(Hidden(name='kind', value='clip_tree'), Hidden(name='target', value=str(plan.root)),
        Button('index it, onto those shelves', cls='lee-btn go', type='submit'),
        hx_post='/clip', hx_target='#vaultwbjobs', hx_swap='afterbegin')
    return Div(Div(Strong(f'{len(plan.files)} files'), Span('·'), Strong(f'{len(plan.shelves)} shelves'),
                   Span(cls='lee-spacer'), Small(str(plan.root)), cls='lee-wb-plan-head'),
        shelves, cats, sample, skipped, run, cls='lee-wb-plan')

def add_view(memory, vault='', jobs=None, root='', **_):
    "Everything that puts something in: a web source, a folder on disk, or a note you write."
    smart = Form(Input(name='target', cls='lee-input', autocomplete='off', required=True,
                       placeholder='https://… · 2401.12345 · github.com/owner/repo · a youtube link'),
        Select(Option('work out what it is', value=''),
               *[Option(f'{a} — {why}', value=a) for a, why in ACTIONS], name='action', cls='lee-input'),
        Button('bring it in', cls='lee-btn go', type='submit'),
        hx_post='/vault/acquire', hx_target='#vaultwbjobs', hx_swap='afterbegin', cls='lee-wb-form')
    local = Form(Input(name='target', cls='lee-input', value=root or '', autocomplete='off', required=True,
                       placeholder='/a/folder/of/documents'),
        Button('preview what that would do', cls='lee-btn', type='submit'),
        hx_get='/vault/plan', hx_target='#vaultwbplan', hx_swap='innerHTML', cls='lee-wb-form')
    note = Form(Input(name='title', cls='lee-input', placeholder='a title'),
        Textarea(name='text', cls='lee-input lee-wb-note', rows='5', required=True,
                 placeholder='write it down; it is filed like anything else, and searched with it'),
        Button('keep it', cls='lee-btn go', type='submit'),
        hx_post='/vault/note', hx_target='#vaultwbjobs', hx_swap='afterbegin', cls='lee-wb-form')
    cards = Div(
        Div(Span('from the web', cls='lee-vault-legend'), smart,
            Small('each of these is a different reader. leave the action blank and the address '
                  'decides which one runs.', cls='lee-dim'), cls='lee-wb-card'),
        Div(Span('from this computer', cls='lee-vault-legend'), local,
            Small('shelves come from the folder structure, and generated paths are left out — '
                  'both are shown before anything is indexed.', cls='lee-dim'),
            Div(id='vaultwbplan'), cls='lee-wb-card'),
        Div(Span('write it yourself', cls='lee-vault-legend'), note, cls='lee-wb-card'),
        cls='lee-wb-cards')
    recent = [job_card(j) for j in (jobs.all(limit=10) if jobs else [])]
    return Div(cards, Div(Span('work', cls='lee-vault-legend'), *recent, id='vaultwbjobs',
                          cls='lee-vault-jobs'), cls='lee-wb-add')

def _day(iso):
    "The date an item carries, as a heading a reader recognises."
    try: d = datetime.fromisoformat(str(iso))
    except ValueError: return 'undated'
    days = (datetime.now(d.tzinfo).date() - d.date()).days
    return {0: 'today', 1: 'yesterday'}.get(days) or d.strftime('%a %d %b %Y')

def _feed_row(f):
    return Div(Div(Strong(f['title'] or f['url']), Span(cls='lee-spacer'),
                   Span(f"{f['items']} new", cls='lee-shelf-count'), cls='lee-wb-feedhead'),
        Small(f['url'], cls='lee-dim'),
        Small(f"{cadence(f['seconds'])} · last read {_when(f['last_run'])} · {f['last_status'] or 'not read yet'}",
              cls='lee-dim' if f['last_status'] in ('ok', '') else 'lee-job-error'),
        Div(Form(Hidden(name='fid', value=f['id']), Button('read it now', cls='lee-btn', type='submit'),
                 hx_post='/vault/news/pull', hx_target='#vaultwbbody', hx_swap='innerHTML'),
            Form(Hidden(name='fid', value=f['id']), Hidden(name='enabled', value=str(not f['enabled']).lower()),
                 Button('resume' if not f['enabled'] else 'pause', cls='lee-btn', type='submit'),
                 hx_post='/vault/news/toggle', hx_target='#vaultwbbody', hx_swap='innerHTML'),
            Form(Hidden(name='fid', value=f['id']), Button('stop following', cls='lee-btn warn', type='submit'),
                 hx_post='/vault/news/remove', hx_target='#vaultwbbody', hx_swap='innerHTML'),
            cls='lee-wb-feedactions'), cls='lee-wb-feed')

def _story(d, vault=''):
    "One story under the source, dateline and standfirst the feed wrote."
    m = d.get('meta') or {}
    line = ' · '.join(x for x in (m.get('feed'), (m.get('published') or '')[:10], m.get('author')) if x)
    return Div(_doc_row(d, vault), Small(line, cls='lee-dim') if line else None,
        Small(str(m.get('summary')), cls='lee-wb-standfirst') if m.get('summary') else None,
        cls='lee-wb-story')

def _narrow(rows, q='', feed=''):
    "A picker over what is followed: a name half-remembered is the one nobody types right."
    names = [f['title'] or f['url'] for f in rows]
    return Form(
        Select(Option('every source', value=''),
               *[Option(n, value=n, selected=(n == feed)) for n in names], name='feed', cls='lee-input'),
        Input(name='q', value=q, cls='lee-input', placeholder='a headline', size='12'),
        Button('narrow', cls='lee-btn', type='submit'),
        hx_get='/vault/view/news', hx_target='#vaultwbbody', hx_swap='innerHTML', cls='lee-wb-form')

def news_view(memory, vault='', feeds=None, error='', q='', feed='', **_):
    "Follow a source, read it on a cadence, and keep what it said with everything else."
    rows = (feeds.dict() if feeds else {'feeds': []})['feeds']
    add = Form(Input(name='url', cls='lee-input', required=True, autocomplete='off',
                     placeholder='a site, or the feed itself'),
        Input(name='title', cls='lee-input', placeholder='call it', size='10'),
        Select(*[Option(cadence(s), value=e) for e, s in (('1h', 3600), ('6h', 21600), ('1d', 86400))],
               name='every', cls='lee-input'),
        Button('follow it', cls='lee-btn go', type='submit'),
        hx_post='/vault/news/add', hx_target='#vaultwbbody', hx_swap='innerHTML', cls='lee-wb-form')
    read = Form(Hidden(name='force', value='true'), Button('read every feed now', cls='lee-btn go', type='submit'),
        hx_post='/vault/news/poll', hx_target='#vaultwbjobs', hx_swap='afterbegin')
    docs = news_rows(memory, match=q, feed=feed, limit=120)
    days = {}
    for d in docs: days.setdefault(_day((d.get('meta') or {}).get('published') or ''), []).append(d)
    items = ([Div(Span(day, cls='lee-vault-legend'), Div(*[_story(x, vault) for x in rows_], cls='lee-vault-docs'))
              for day, rows_ in days.items()] if docs else
             [empty('nothing to show', 'nothing matches that narrowing.' if (q or feed) else
                    'follow a feed and read it now — items land on the news shelf.')])
    return Div(
        Div(Span('feeds', cls='lee-vault-legend'), Span(cls='lee-spacer'), read, cls='lee-wb-cardhead'),
        Div(error, cls='lee-job-error') if error else None,
        add,
        Div(*[_feed_row(f) for f in rows] or [Div('No feeds yet.', cls='lee-vault-empty')], cls='lee-wb-feeds'),
        Div(id='vaultwbjobs', cls='lee-vault-jobs'),
        Div(Span('what they said', cls='lee-vault-legend'), Span(cls='lee-spacer'), _narrow(rows, q, feed),
            cls='lee-wb-cardhead'),
        Div(*items, cls='lee-wb-news'),
        Small('every item is an ordinary document on the news shelf, so “what did the feeds say '
              'about X this week?” is answered out of the vault, citing the item.', cls='lee-dim'),
        cls='lee-wb-newsview')

def _op_cell(o, name):
    "The operation name is what a call is made by, so it is a button that fills the call form."
    op = o.get('name') or ''
    if not op: return Td(Small('—'))
    return Td(Form(Hidden(name='name', value=name), Hidden(name='operation', value=op),
                   Button(op, cls='lee-btn quiet', type='submit', title=o.get('signature') or op),
                   hx_get='/vault/apis/form', hx_target='#vaultwbcall', hx_swap='innerHTML'))

def ops_table(rows, src='', match='', name=''):
    "What a loaded specification offers, which is the only readable form a big one has."
    if not rows: return Div('No operation matched.', cls='lee-vault-empty')
    # Every cell is escaped: a specification is somebody else's document, fetched from a url.
    body = [Tr(_op_cell(o, name), Td(Span(o['verb'], cls=f"lee-wb-verb {o['verb'].lower()}")),
               Td(Code(o['path'])), Td(o.get('summary') or ''),
               Td(Small(', '.join(o.get('required') or []) or '—')),
               Td(Small(o.get('group') or ''))) for o in rows[:400]]
    return Div(Small(f'{len(rows)} operations' + (f' matching “{match}”' if match else ''), cls='lee-dim'),
        Div(Table(Thead(Tr(Th('call it'), Th(''), Th('endpoint'), Th('what it does'), Th('required'),
                           Th('group'))), Tbody(*body), cls='lee-wb-table'), cls='lee-wb-tablewrap'),
        Form(Hidden(name='target', value=src), Hidden(name='kind', value='clip_api_spec'),
             Button('file it in the vault', cls='lee-btn go', type='submit',
                    title='one document, one section per operation — then ask about it like a paper'),
             hx_post='/clip', hx_target='#vaultwbjobs', hx_swap='afterbegin'),
        cls='lee-wb-ops')

def call_form(name='', operation='', params='', ops=()):
    "Run one operation from the page. The answer goes to the person who asked for it, ungated."
    names = [o.get('name') for o in (ops or []) if o.get('name')]
    return Div(
        Form(Input(name='name', value=name, cls='lee-input', placeholder='which api', size='12'),
             Input(name='operation', value=operation, cls='lee-input', required=True,
                   autocomplete='off', list='vaultwbops', placeholder='which operation'),
             Textarea(params or '', name='params', cls='lee-input', rows='2',
                      placeholder='{"parameter": "value"}  — a JSON object, or empty'),
             Button('call it', cls='lee-btn go', type='submit'),
             Datalist(*[Option(value=n) for n in names[:400]], id='vaultwbops'),
             hx_post='/vault/apis/call', hx_target='#vaultwbout', hx_swap='innerHTML',
             cls='lee-wb-form'),
        Small('the call goes out from here with the headers kept beside the spec, so this is a real '
              'response. an api marked local-only still answers you: the reach gate is about which '
              'model may read it.', cls='lee-dim'),
        Div(id='vaultwbout'))

def call_panel(name='', operation='', params='', ops=()):
    "The call form under its own legend, which is what a row's button swaps in."
    return Div(Div(Span('call one of them', cls='lee-vault-legend'), cls='lee-wb-cardhead'),
               call_form(name, operation, params, ops))

def api_result(out, note=''):
    "What an operation answered, as it came back."
    text = out if isinstance(out, str) else json.dumps(out, indent=2, default=str)
    return Div(Small(note, cls='lee-dim') if note else None,
        Pre(Code(text[:40000] + ('\n…' if len(text) > 40000 else '')), cls='lee-wb-apiout'))

def _policy_row(name, pol):
    "One spec: the headers it sends, the variables behind them, and who may call it."
    from .spec import env_status
    headers, reach = pol.get('headers') or [], pol.get('reach', 'cloud')
    env = env_status(pol.get('refs') or [])
    return Div(Div(Strong(name), Span(cls='lee-spacer'),
                   Span('local only' if reach == 'local' else 'any model', cls='lee-shelf-count'),
                   Span(', '.join(headers) or 'no key', cls='lee-shelf-count'), cls='lee-wb-feedhead'),
        *[Small(f'${{{k}}} is ' + ('set here' if ok else 'not set — a call will fail'),
                cls='lee-dim' if ok else 'lee-job-error') for k, ok in env.items()])

def creds_panel(policies):
    "What each api sends and who may call it. A value is never rendered."
    rows = [_policy_row(name, pol) for name, pol in sorted((policies or {}).items())]
    return Div(*(rows or [Small('no api carries a key, so calls go out unauthenticated — which most '
                                'apis answer with 401.', cls='lee-dim')]), cls='lee-wb-creds')

def creds_view(policies=None, error=''):
    "The keys panel, which is its own swap target: a key is set without reloading the page."
    form = Form(Input(name='name', cls='lee-input', required=True, autocomplete='off',
                      placeholder='which api, as api_load named it'),
        Input(name='headers', cls='lee-input', autocomplete='off',
              placeholder='Authorization: Bearer ${COSTING_TOKEN}   (one per line, empty to forget it)'),
        Select(Option('any model may call it', value='cloud'),
               Option('local models only', value='local'), name='reach', cls='lee-input'),
        Button('keep it', cls='lee-btn go', type='submit'),
        hx_post='/vault/apis/creds', hx_target='#vaultwbcreds', hx_swap='outerHTML', cls='lee-wb-form')
    return Div(Div(Span('the keys a real call needs', cls='lee-vault-legend'), cls='lee-wb-cardhead'),
        Div(error, cls='lee-job-error') if error else None, creds_panel(policies), form,
        Small('a key is kept where leela keeps its secrets, sent only with calls to the api it '
              'belongs to, and never given to the model. a header may name an environment variable '
              'instead — write ', Code('Bearer ${COSTING_TOKEN}'), ' and rotating the variable '
              'rotates the credential. an api marked local-only refuses a hosted model rather than '
              'sending anything.', cls='lee-dim'),
        id='vaultwbcreds', cls='lee-wb-credsview')

def specs_view(memory, vault='', src='', match='', ops=None, error='', creds=None, name='', **_):
    "A described endpoint is a document you can ask about, once it is in the vault."
    load = Form(Input(name='src', value=src, cls='lee-input', required=True, autocomplete='off',
                      placeholder='an OpenAPI url or path, or a Google discovery document'),
        Input(name='match', value=match, cls='lee-input', placeholder='search the operations', size='12'),
        Button('read it', cls='lee-btn go', type='submit'),
        hx_get='/vault/view/specs', hx_target='#vaultwbbody', hx_swap='innerHTML', cls='lee-wb-form')
    from .spec import EXAMPLES
    # something that answers on the first click: no key, no sign-up, and a response worth reading
    demo = Div(*[Form(Hidden(name='src', value=x.path), Hidden(name='name', value=x.name),
                      Button(x.label.lower(), cls='lee-btn', type='submit', title=x.note),
                      hx_get='/vault/view/specs', hx_target='#vaultwbbody', hx_swap='innerHTML')
                 for x in EXAMPLES], cls='lee-wb-form')
    about = Small('a real catalogue does not fit on a page, and a spec is not held anywhere until '
                  'you file it. filing writes every operation as its own section, so “which call '
                  'returns a deployment?” is answered out of the vault, citing the operation. the '
                  'bundled examples above are keyless.', cls='lee-dim')
    body = (Div(error, cls='lee-job-error') if error else
            ops_table(ops, src, match, name) if ops is not None else
            empty('load a specification', 'then search its operations, and file the ones you will ask about.'))
    from .spec import example_for
    ex = example_for(name)
    call = Div(call_panel(name, ex.call if ex else '', ex.params if ex else '', ops) if ops else None,
               id='vaultwbcall', cls='lee-wb-callview')
    return Div(Div(Span('a specification', cls='lee-vault-legend'), cls='lee-wb-cardhead'), load, demo, about,
        body, call, creds_view(creds), Div(id='vaultwbjobs', cls='lee-vault-jobs'), cls='lee-wb-specs')

def topics_view(memory, vault='', **_):
    "What the corpus is about, from the entity graph rather than from anybody's folder names."
    d = memory.clusters(limit=40)
    rows = d.get('clusters') or []
    build = Form(Button('build the graph and its topics', cls='lee-btn go', type='submit'),
        hx_post='/vault/connect', hx_target='#vaultwbjobs', hx_swap='afterbegin')
    if not rows:
        return Div(empty('no topics yet',
                         'topics are read off the entity graph, which is built after an import rather '
                         'than during one — it reads every chunk, so it is a job, not a page load.',
                         Small(d.get('note') or '', cls='lee-dim'), build),
                   Div(id='vaultwbjobs', cls='lee-vault-jobs'), cls='lee-wb-topics')
    top = max(int(t.get('chunks') or t.get('size') or 1) for t in rows)
    cards = [Article(Div(Span(f'{i + 1:02}', cls='lee-shelf-count'), Span(cls='lee-spacer'),
                         Span(f"{t.get('chunks', t.get('size', 0))} chunks", cls='lee-shelf-count'),
                         cls='lee-wb-topichead'),
                     Strong(t.get('label') or 'unlabelled topic'),
                     Small(f"{t.get('docs', 0)} contributing documents"),
                     Details(Summary('the documents under it'),
                         Div(*[_doc_row(dict(s, doc_id=s.get('doc_id'), shelf=s.get('store', '')), vault)
                               for s in t.get('sources', [])], cls='lee-vault-docs')),
                     style=f"--w:{max(1, round(int(t.get('chunks') or t.get('size') or 1) / top * 5))}",
                     cls='lee-wb-topic') for i, t in enumerate(rows)]
    return Div(Div(Span(d.get('note') or '', cls='lee-keyscope'), Span(cls='lee-spacer'), build,
                   cls='lee-wb-cardhead'),
        Div(*cards, cls='lee-wb-topiccards'), Div(id='vaultwbjobs', cls='lee-vault-jobs'),
        cls='lee-wb-topics')
