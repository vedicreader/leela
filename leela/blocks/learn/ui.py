from fasthtml.common import A, Blockquote, Body, Button, Code, Div, Form, H1, Head, Hidden, Html, Input, Link, Main, Meta, Nav, NotStr, P, Pre, Script, Section, Span, Strong, Title
from ...core.text import md_html
from ...core.web import asset
from ..settings.settings import theme_boot

__all__ = ['Page', 'StepPage', 'OpenedPage', 'LookupPage']

# A frame takes the IDE's theme over its own saved one, and follows it when it changes.
FOLLOW = """try { if (window.parent !== window) { const d = document.documentElement, p = window.parent.document.documentElement;
const copy = () => { try { for (const k of ['theme', 'mode', 'density']) if (p.dataset[k]) d.dataset[k] = p.dataset[k];
if (p.style.colorScheme) d.style.colorScheme = p.style.colorScheme; } catch (_) {} };
copy(); new MutationObserver(copy).observe(p, {attributes: true, attributeFilter: ['data-theme', 'data-mode', 'data-density', 'style']}); } } catch (_) {}"""

def Page(title, *body, pane:bool=False, js:bool=False, math:bool=False, root=None, here=None):
    "A `learn` page with the title `title` as its heading, in the theme saved for the project `root`. `pane` makes it a page in the side pane; `pane`, `js` or `math` loads `lee-pane.js`; `math` loads KaTeX; `here` is the URL the pane keeps for it."
    return Html(Head(Meta(charset='utf-8'), Title(title), Script(theme_boot(root) + '\n' + FOLLOW), Link(rel='stylesheet', href=asset('lee-ide.css')),
                     *((Link(rel='stylesheet', href=asset('katex/katex.min.css')), Script(src=asset('katex/katex.min.js'), defer=True)) if math else ()),
                     Script(src=asset('lee-pane.js')) if pane or js or math else None),
                Body(Main(H1(title), *body, cls='lee-learn')), cls='lee-learn-page in-pane' if pane else 'lee-learn-page', data_rh_url=here)

def _Steps(q, i, n, pane):
    "`Idea N of M`, with links to the ideas before and after `i` that keep the vault key `q.v`."
    from abhyasa.contract import handoff
    to = lambda k: handoff(q.walk, k, v=q.v) + ('&pane=1' if pane else '')
    return Nav(A('Previous idea', href=to(i - 1)) if i > 0 else None, Span(f'Idea {i + 1} of {n}'), A('Next idea', href=to(i + 1)) if i + 1 < n else None, cls='lee-learn-steps')

def _Source(p):
    "The source line of the passage `p` in words: your source, title and place; or from the web, site, date and a link."
    from abhyasa.sources import WEB
    parts = [p.place, p.date, A(p.title, href=p.url, target='_blank', rel='noopener noreferrer') if p.url else None] if p.label == WEB else [p.title, p.place]
    out = [Strong(p.label)]
    for x in filter(None, parts): out += [' · ', x]
    return P(*out, cls='lee-learn-source')

def _Env(v, q, pane):
    "The ask that makes the tool environment of a step whose `nb` has `requires`; None when there is none or it is ready."
    from .tools import tool_indexed, tool_kernel, tool_key
    if not (names := (v.get('nb') or {}).get('requires')) or (tool_kernel(key := tool_key(names)) and tool_indexed(key)): return None
    return Form(P(f"This lesson needs {', '.join(names)}.", cls='lee-learn-line'), Hidden(name='walk', value=q.walk), Hidden(name='step', value=str(v.i)),
                Hidden(name='v', value=q.v), Hidden(name='pane', value='1') if pane else None,
                Button('Set up the environment', type='submit', cls='lee-btn', data_key=key), method='post', action='/learn/env', cls='lee-learn-env')

def StepPage(v, q, pane:bool=False, root=None):
    "The page for the `find_step` result `v` of a step or a topic, with the button that opens it as a lesson. `pane` makes it a page in the side pane."
    if v.kind == 'step':
        from .learn import passages, walk_url
        r, back = v.step.get('read') or {}, walk_url(q.walk, v.i)
        title, step = v.j.title, str(v.i)
        body = [P(r['section'], cls='lee-learn-section') if r.get('section') else None,
                *[x for p in passages(v.j, r) for x in (Blockquote(NotStr(md_html(p.text))), _Source(p))],
                Div(NotStr(md_html(v.step['note'])), cls='lee-learn-note') if v.step.get('note') else None,
                P('Idea: ', Strong(v.name), cls='lee-learn-line'), _Steps(q, v.i, len(v.j.steps), pane), _Env(v, q, pane),
                P(A('Back to the walk ↗', href=back, target='_blank', rel='noopener', cls='lee-learn-back'), cls='lee-learn-line') if back else None]
    else:
        title, step = v.name, ''
        body = [P(v.concept.get('statement') or '') if v.concept else P('This idea is not in your learning store.', cls='lee-learn-line')]
    return Page(title, *body, Form(Hidden(name='walk', value=q.walk), Hidden(name='step', value=step), Hidden(name='topic', value=q.topic), Hidden(name='v', value=q.v),
                                   Hidden(name='pane', value='1') if pane else None,
                                   Button('Open as a lesson', type='submit', cls='lee-btn'), method='post', action='/learn/open'), pane=pane, js=True, math=v.kind == 'step', root=root)

def OpenedPage(title, here, pane:bool=False, root=None):
    "The page after a lesson opens: the step's title, the line `Opened in Leela.` and a link back to the step at `here`."
    back = here + '&pane=1' if pane else here
    return Page(title, P('Opened in Leela.', cls='lee-learn-line'), P(A('Back to the step', href=back, cls='lee-learn-back')), pane=pane, root=root, here=here)

def _Hit(r, path):
    return Section(P(Strong(r['name']), ' ', Span(r['package'], cls='lee-learn-line'), ' ', Code(f"{r['path']}:{r['line']}")),
                   P(r['doc'], cls='lee-learn-note') if r['doc'] else None, Pre(Code(r['snippet'])),
                   Button('Put in a scratch cell', type='button', onclick='leeScratch(this)', data_path=path, data_snippet=r['snippet'], cls='lee-btn') if path else None,
                   cls='lee-learn-hit')

def LookupPage(q, rows, packages=(), path='', pane:bool=False, root=None, say=None, tool=''):
    "The page of the `lookup` rows `rows` for `q`. With `path`, each row has a button that adds its snippet to that notebook as a scratch cell. `say` replaces the line above the rows."
    say = say or ('Type what to look for.' if not q else None if rows else 'Nothing found.')
    return Page('Look up code',
                Form(Input(type='search', name='q', value=q, aria_label='What to look for', placeholder='What to look for', autofocus=not pane, cls='lee-input'), *[Hidden(name='package', value=p) for p in packages],
                     Hidden(name='path', value=path) if path else None, Hidden(name='tool', value=tool) if tool else None, Hidden(name='pane', value='1') if pane else None,
                     Button('Look up', type='submit', cls='lee-btn'), method='get', action='/learn/lookup'),
                P(say, cls='lee-learn-line') if say else None, *[_Hit(r, path) for r in rows],
                P('', cls='lee-learn-line', role='status', aria_live='polite') if path else None, pane=pane, js=bool(path), root=root)
