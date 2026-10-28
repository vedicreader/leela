from fasthtml.common import A, Blockquote, Body, Button, Code, Form, H1, Head, Hidden, Html, Input, Link, Main, Meta, P, Pre, Script, Section, Span, Strong, Title
from ...core.web import asset
from ..settings.settings import theme_boot

__all__ = ['Page', 'StepPage', 'OpenedPage', 'LookupPage']

# A frame takes the IDE's theme over its own saved one, and follows it when it changes.
FOLLOW = """try { if (window.parent !== window) { const d = document.documentElement, p = window.parent.document.documentElement;
const copy = () => { try { for (const k of ['theme', 'mode', 'density']) if (p.dataset[k]) d.dataset[k] = p.dataset[k];
if (p.style.colorScheme) d.style.colorScheme = p.style.colorScheme; } catch (_) {} };
copy(); new MutationObserver(copy).observe(p, {attributes: true, attributeFilter: ['data-theme', 'data-mode', 'data-density', 'style']}); } } catch (_) {}"""

def Page(title, *body, pane:bool=False, js:bool=False, root=None, here=None):
    "A `learn` page with the title `title` as its heading, in the theme saved for the project `root`. `pane` makes it a page in the side pane; `pane` or `js` loads `lee-pane.js`; `here` is the URL the pane keeps for it."
    return Html(Head(Meta(charset='utf-8'), Title(title), Script(theme_boot(root) + '\n' + FOLLOW), Link(rel='stylesheet', href=asset('lee-ide.css')),
                     Script(src=asset('lee-pane.js')) if pane or js else None),
                Body(Main(H1(title), *body, cls='lee-learn')), cls='lee-learn-page in-pane' if pane else 'lee-learn-page', data_rh_url=here)

def StepPage(v, q, pane:bool=False, root=None):
    "The page for the `find_step` result `v` of a step or a topic, with the button that opens it as a lesson. `pane` makes it a page in the side pane."
    if v.kind == 'step':
        r = v.step.get('read') or {}
        title, step = v.j.title, str(v.i)
        body = [P(r['section'], cls='lee-learn-section') if r.get('section') else None,
                Blockquote(r['text']) if r.get('text') else None,
                P(v.step['note'], cls='lee-learn-note') if v.step.get('note') else None,
                P('Idea: ', Strong(v.name), cls='lee-learn-line')]
    else:
        title, step = v.name, ''
        body = [P(v.concept.get('statement') or '') if v.concept else P('This idea is not in your learning store.', cls='lee-learn-line')]
    return Page(title, *body, Form(Hidden(name='walk', value=q.walk), Hidden(name='step', value=step), Hidden(name='topic', value=q.topic),
                                   Hidden(name='pane', value='1') if pane else None,
                                   Button('Open as a lesson', type='submit', cls='lee-btn'), method='post', action='/learn/open'), pane=pane, root=root)

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
