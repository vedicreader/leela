"The literate render: one document, one column, readable on a phone."

from __future__ import annotations
from dataclasses import replace
from collections import Counter
from html import escape
from importlib.resources import files
from fastcore.all import Path, first

from .change import bundles, coverage, diff_stat, snip, state
from .context import strip_work_log
from .doc import HEAD

__all__ = ['lit', 'html_of', 'md_html', 'GOAL_KEYS', 'FOLD_LINES', 'DIFF_CAP', 'DIFF_COLS']

#: What a goal states beyond the goal itself.
GOAL_KEYS = ('measure', 'baseline', 'target', 'by')
#: Longer than this and a snippet or a diff arrives folded. A phone holds about 20 lines.
FOLD_LINES = 22
#: A generated artifact diffs to thousands of unreadable lines. Past this, the rest is a count.
DIFF_CAP = 400
#: And one minified line can hold the whole file. Past this, the line ends in an ellipsis.
DIFF_COLS = 400

def md_html(text):
    "Markdown as HTML. `mdhtml` does this; nothing here parses markdown."
    from mdhtml import md2dom
    return md2dom(str(text or '')).to_html()

def _hd(text):
    "The heading level and title of a heading-only text brick."
    m = first(HEAD.finditer((text or '').strip()))
    return (len(m.group(1)), m.group(2)) if m else (0, '')

def _fold(summary, inner, open=False):
    o = ' open' if open else ''
    return f'<details{o}><summary>{escape(summary)}</summary><div class="in">{inner}</div></details>'

def _pre(code, lang=''):
    return f'<pre><code class="lang-{escape(lang or "text")}">{escape(code)}</code></pre>'

def _goal(b):
    rows = ''.join(f'<dt>{escape(k)}</dt><dd>{escape(str(b.attrs[k]))}</dd>'
                   for k in GOAL_KEYS if b.attrs.get(k))
    return (f'<div class="card goal"><div class="stmt">{escape(b.body.strip())}</div>'
            + (f'<dl>{rows}</dl>' if rows else '') + '</div>')

def _tasks(bricks):
    rows = []
    for b in bricks:
        st = b.attrs.get('status', 'todo')
        box = {'done': '[x]', 'blocked': '[!]', 'doing': '[~]'}.get(st, '[ ]')
        who = f'<span class="who">{escape(b.attrs["owner"])}</span>' if b.attrs.get('owner') else ''
        rows.append(f'<li class="{st}"><span class="box">{box}</span>'
                    f'<span>{escape(b.body.strip())}</span>{who}</li>')
    return f'<ul class="tasks">{"".join(rows)}</ul>' if rows else ''

def _change(b, doc, changed):
    u = first(x for x in bundles(doc) if x.id == b.id)
    if u is None: return f'<div class="card change">{md_html(b.body)}</div>'
    st = state(u, changed)
    files_ = ''.join(f'<span class="chip">{escape(p)}</span>' for p in u.paths)
    refs = ''.join(f'<span class="chip">{escape(r)}</span>' for r in u.refs)
    worth = f'<div class="meta">Worth: {escape(u.contributes)}</div>' if u.contributes else ''
    return (f'<div class="card change"><div class="chips"><span class="chip {st}">{st}</span></div>'
            f'{worth}{md_html(b.body)}'
            + (f'<div class="chips">{files_}</div>' if files_ else '')
            + (f'<div class="chips">{refs}</div>' if refs else '') + '</div>')

def _snippet(b, root):
    code = snip(b, root)
    where = b.attrs.get('symbol') or b.attrs.get('lines') or ''
    cap = (f'<figcaption><b>{escape(b.attrs.get("path", ""))}</b>'
           + (f' &middot; {escape(where)}' if where else '') + '</figcaption>')
    block = _pre(code, b.attrs.get('lang', 'python'))
    if code.count('\n') + 1 > FOLD_LINES:
        block = _fold(f'{where or b.attrs.get("path", "code")} ({code.count(chr(10)) + 1} lines)', block)
    return f'{md_html(b.body)}<figure>{cap}{block}</figure>'

_SKIP = ('diff --git', 'index ', '--- ', '+++ ', 'new file', 'deleted file', 'similarity ',
         'rename ', 'old mode', 'new mode')

def _dline(l):
    cls = 'a' if l[:1] == '+' else 'r' if l[:1] == '-' else 'h' if l[:2] == '@@' else ''
    if len(l) > DIFF_COLS: l = l[:DIFF_COLS] + f' … +{len(l) - DIFF_COLS} chars'
    return f'<span class="dl {cls}">{escape(l) or " "}</span>'

def _diff(b):
    rows = [l for l in b.body.split('\n') if not l.startswith(_SKIP)]
    body = ''.join(_dline(l) for l in rows[:DIFF_CAP])
    if (over := len(rows) - DIFF_CAP) > 0: body += f'<span class="dl cut">{over} more lines, not shown</span>'
    add, rm = diff_stat(b.body)
    chips = (f'<span class="chip add">+{add}</span><span class="chip rm">-{rm}</span>'
             + ('<span class="chip warn">no bundle claims this</span>'
                if b.attrs.get('claimed') == 'no' else ''))
    path = b.attrs.get('path', 'diff')
    if len(rows) > FOLD_LINES:                  # the summary already names the file and the counts
        warn = ' - no bundle claims this' if b.attrs.get('claimed') == 'no' else ''
        return _fold(f'{path} +{add} -{rm}{warn}', f'<div class="diff"><div class="body">{body}</div></div>')
    return (f'<figure><div class="diff"><div class="hd"><span class="p">{escape(path)}</span>'
            f'{chips}</div><div class="body">{body}</div></div></figure>')

def _ask(b, doc):
    r = doc.reply_to(b.id)
    ans = f'<div class="a">{md_html(strip_work_log(r.body))}</div>' if r is not None else ''
    return f'<div class="card ask"><div class="q">{md_html(b.body)}</div>{ans}</div>'

def _brick(b, doc, changed, root):
    if b.kind == 'goal': return _goal(b)
    if b.kind == 'bundle': return _change(b, doc, changed)
    if b.kind == 'snippet': return _snippet(b, root)
    if b.kind == 'diff': return _diff(b)
    if b.kind == 'ask': return _ask(b, doc)
    if b.kind == 'note': return f'<div class="card note">{md_html(b.body)}</div>'
    if b.kind == 'code': return f'<figure>{_pre(b.body, b.attrs.get("lang", "python"))}</figure>'
    if b.kind in ('data', 'brick', 'sim'):
        binds = '\n'.join(f'{k} = {v}' for k, v in b.binds.items())
        return (f'<figure><figcaption><b>{escape(b.attrs.get("src") or b.kind)}</b></figcaption>'
                f'{_pre(binds or b.body, "python")}</figure>')
    if b.kind == 'source': return _source(b)
    if b.kind == 'reply': return ''
    return md_html(b.body)

def _source(b):
    "An attached reference: its title, and its path when the title does not already end in it."
    path = b.attrs.get('path', '')
    ttl = b.attrs.get('title') or path or 'source'
    where = f' &middot; {escape(path)}' if path and not ttl.endswith(path) else ''
    return (f'<figure><figcaption><b>{escape(ttl)}</b>{where}</figcaption>'
            f'{md_html(b.body) if b.body.strip() else ""}</figure>')

def _sections(doc):
    "The document split at its headings, for the contents and the jump targets."
    out, cur = [], None
    def start(title):
        out.append(cur := {'title': title, 'bricks': []})
        return cur
    for b in doc.bricks:
        lvl, title = _hd(b.body) if b.kind == 'text' else (0, '')
        if lvl and lvl <= 2:
            cur = start(title)
            if (rest := HEAD.sub('', b.body.strip(), count=1).strip()):
                cur['bricks'].append(replace(b, body=rest))
            continue
        if cur is None: cur = start('')
        cur['bricks'].append(b)
    return out

def _slug(s, n):
    keep = ''.join(c if c.isalnum() else '-' for c in (s or '').lower())
    return '-'.join(x for x in keep.split('-') if x)[:40] or f's{n}'

def html_of(doc, changed=(), root='.', subtitle='', unclaimed=None):
    "The whole document as one page of HTML."
    secs = _sections(doc)
    tasks = {b.id for b in doc.of('task')}
    nav, body, used = [], [], Counter()
    for n, sec in enumerate(secs):
        sid = _slug(sec['title'], n)
        used[sid] += 1
        if used[sid] > 1: sid = f'{sid}-{used[sid]}'   # eight reviews on one page each have a Change
        if sec['title']:
            nav.append(f'<li><a href="#{sid}">{escape(sec["title"])}</a></li>')
            body.append(f'<h2 id="{sid}">{escape(sec["title"])}</h2>')
        run = []
        for b in sec['bricks']:
            if b.id in tasks: run.append(b)
            else:
                if run: body.append(_tasks(run)); run = []
                body.append(_brick(b, doc, changed, root))
        if run: body.append(_tasks(run))
    chips = []
    for u in bundles(doc):
        st = state(u, changed)
        chips.append(f'<span class="chip {st}">{escape(u.id)} {st}</span>')
    #: A stitched page carries no bundle brick, so its caller knows the coverage and this does not.
    if unclaimed is not None: loose = list(unclaimed)
    else: loose = coverage(doc, list(changed))['unclaimed'] if changed else []
    if loose: chips.append(f'<span class="chip warn">{len(loose)} file(s) claimed by nobody</span>')
    elif changed: chips.append(f'<span class="chip ok">{len(changed)} file(s), all claimed</span>')
    head = (f'<header><div class="in"><div class="mark">canvas &middot; literate diff</div>'
            f'<h1>{escape(doc.title)}</h1>'
            + (f'<div class="chips">{"".join(chips)}</div>' if chips else '') + '</div></header>')
    toc = _fold('Contents', f'<nav><ol>{"".join(nav)}</ol></nav>') if len(nav) > 2 else ''
    foot = (f'<footer>{escape(subtitle)}</footer>' if subtitle else '')
    return head + '<div class="wrap">' + toc + ''.join(x for x in body if x) + foot + '</div>'

def lit(
    doc,           # the document
    path,          # where to write the page
    changed=(),    # paths a diff says moved, for the header chips
    root='.',      # where a `snippet` brick's `path` is relative to
    subtitle='',   # the footer line
    unclaimed=None,# the coverage gap, when the caller knows it and the page's own bundles do not
):
    "Write the literate page to `path`. One file, no JavaScript, no other requests."
    css = files(__package__).joinpath('lit.css').read_text(encoding='utf-8')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<title>{escape(doc.title)}</title>\n<style>{css}</style></head><body>\n'
            f'{html_of(doc, changed, root, subtitle, unclaimed)}\n</body></html>\n')
    p = Path(path)
    p.write_text(page, encoding='utf-8')
    return p
