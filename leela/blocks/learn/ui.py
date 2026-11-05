from fasthtml.common import A, Blockquote, Body, Button, Code, Div, Form, H1, Head, Hidden, Html, Input, Link, Main, Meta, Nav, NotStr, P, Pre, Script, Section, Span, Strong, Title
from pathlib import Path
from ...core.text import md_html
from ...core.web import asset
from ..settings.settings import theme_boot

__all__ = ['Page', 'StepPage', 'DocPage', 'OpenedPage', 'LookupPage', 'FolderPage']

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

READY = 'The environment for this lesson is ready. The lesson runs now.'
INDEXING = READY + ' Leela is still building the code index for Look up code.'
WATCHED = ('installing', 'indexing')

def took(secs) -> str:
    "`secs` as `M min S s`, or `S s` under a minute."
    m, s = divmod(max(0, int(secs)), 60)
    return f'{m} min {s} s' if m else f'{s} s'

def _failed(job) -> str:
    "The sentence for a `tool_env` job that ended in an error; empty for any other."
    return f" The last setup did not finish: {job.error.removeprefix('JobError: ')}" if job and job.status == 'error' and job.error else ''

def env_say(st, job=None) -> str:
    "The line for the tool environment state `st` of `env_state`; `job` is its newest `tool_env` job."
    import time
    if st == 'installing': return f"Leela is setting up the environment for this lesson. {took(time.time() - (job.started_at or job.created_at) if job else 0)} so far. This page changes when it is ready."
    if st == 'unindexed': return 'The environment for this lesson is ready. Its code index for Look up code is not built.'
    if st == 'missing': return 'The environment for this lesson is not set up.' + _failed(job)
    return INDEXING if st == 'indexing' else READY

def _Env(v, q, pane, key, st, job=None):
    "The state `st` of the tool environment `key` of a step: a status line the page keeps asking about, or the button that makes it or builds its code index."
    if st in ('ready', *WATCHED): return P(env_say(st, job), cls='lee-learn-line lee-learn-env', role='status', aria_live='polite', data_env_key=key, data_env_state=st)
    names = v.nb['requires']
    say = env_say(st, job) if st == 'unindexed' else f"This lesson needs {', '.join(names)}." + _failed(job)
    return Form(P(say, cls='lee-learn-line'), Hidden(name='walk', value=q.walk), Hidden(name='step', value=str(v.i)),
                Hidden(name='v', value=q.v), Hidden(name='pane', value='1') if pane else None,
                Button('Build the code index' if st == 'unindexed' else 'Set up the environment', type='submit', cls='lee-btn', data_key=key),
                method='post', action='/learn/env', cls='lee-learn-env')

def _Data(v):
    "The line that names each data entry of the step with no path or a path that is not on this computer; None when there is none."
    from ..nb.lesson import MISSING_DATA, MISSING_HEAD, missing_data
    if not (gone := missing_data((v.get('nb') or {}).get('data') or [])): return None
    return P(f"{MISSING_HEAD}{', '.join(gone)}. {MISSING_DATA.replace(' here', ' in the setup cell of the lesson')}", cls='lee-learn-line')

def StepPage(v, q, pane:bool=False, root=None, jobs=None):
    "The page for the `find_step` result `v` of a step or a topic, with the button that opens it as a lesson. `pane` makes it a page in the side pane; `jobs` tells a running setup."
    st = None
    if v.kind == 'step':
        from .tools import env_job, env_state, tool_key
        if names := (v.get('nb') or {}).get('requires'): st = env_state(jobs, key := tool_key(names))
        from .learn import passages, walk_url
        r, back = v.step.get('read') or {}, walk_url(q.walk, v.i)
        title, step = v.j.title, str(v.i)
        body = [P(r['section'], cls='lee-learn-section') if r.get('section') else None,
                *[x for p in passages(v.j, r) for x in (Blockquote(NotStr(md_html(p.text))), _Source(p))],
                Div(NotStr(md_html(v.step['note'])), cls='lee-learn-note') if v.step.get('note') else None,
                P('Idea: ', Strong(v.name), cls='lee-learn-line'), _Steps(q, v.i, len(v.j.steps), pane), _Data(v), st and _Env(v, q, pane, key, st, env_job(jobs, key)),
                P(A('Back to the walk ↗', href=back, target='_blank', rel='noopener', cls='lee-learn-back'), cls='lee-learn-line') if back else None]
    else:
        title, step = v.name, ''
        body = [P(v.concept.get('statement') or '') if v.concept else P('This idea is not in your learning store.', cls='lee-learn-line')]
    return Page(title, *body, Form(Hidden(name='walk', value=q.walk), Hidden(name='step', value=step), Hidden(name='topic', value=q.topic), Hidden(name='v', value=q.v),
                                   Hidden(name='cell', value=str(q.cell)) if q.get('cell') is not None else None,
                                   Hidden(name='pane', value='1') if pane else None,
                                   Button('Open as a lesson', type='submit', cls='lee-btn go' if st in ('ready', 'indexing', 'unindexed') else 'lee-btn'), method='post', action='/learn/open'), pane=pane, js=True, math=v.kind == 'step', root=root)

def DocPage(nb, q, pane:bool=False, root=None):
    "The page for the notebook `nb` from abhyasa's vault, for a link that does not open it at once: where it runs, and the button that opens it."
    return Page(nb.name, P(f'Leela opens {nb.name} in its own project and runs it in {nb.parent}.', cls='lee-learn-line'),
                Form(*[Hidden(name=k, value=str(x)) for k, x in (('doc', q.doc), ('shelf', q.shelf), ('cell', q.cell), ('v', q.v)) if x not in ('', None)],
                     Hidden(name='pane', value='1') if pane else None, Button('Open the notebook', type='submit', cls='lee-btn go'), method='post', action='/learn/open'),
                pane=pane, root=root)

def OpenedPage(title, here, pane:bool=False, root=None):
    "The page after a lesson opens: the step's title, the line `Opened in Leela.` and a link back to the step at `here`, when there is one."
    back = here + '&pane=1' if pane and here else here
    return Page(title, P('Opened in Leela.', cls='lee-learn-line'), P(A('Back to the step', href=back, cls='lee-learn-back')) if here else None, pane=pane, root=root, here=here or None)

#: The Open button of `FolderPage`: the server asks the person, then the folder's window opens.
FOLDER_OPEN = """(async b => { const r = await fetch(b.dataset.url, {method: 'POST'}), d = await r.json().catch(() => ({error: r.statusText}));
  if (!d.ok) return b.closest('main').append(Object.assign(document.createElement('p'), {className: 'lee-learn-line', textContent: d.error}));
  if (window.pywebview?.api?.open_folder) return window.pywebview.api.open_folder(d.root);
  if (window.parent !== window) window.open(d.url, '_blank'); else location.href = d.url; })(this)"""

def FolderPage(title, file, need, pane:bool=False, root=None):
    "The question when the lesson `file` is in folders this window does not have open, `need` project first, and the Open button that asks to add them."
    from urllib.parse import urlencode
    url = '/hub/open?' + urlencode([('path', str(need[0])), ('file', str(file)), ('folder', '1'), *(('also', str(a)) for a in need[1:])])
    name = Path(need[0]).name
    return Page(title, P(f'This lesson is in {name}, which this window does not have open. Open {name} as a folder?', cls='lee-learn-line', title=str(need[0])),
                P(Button('Open', type='button', cls='lee-btn go', data_url=url, onclick=FOLDER_OPEN)), pane=pane, root=root)

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
