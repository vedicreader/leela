import re
from urllib.parse import urlsplit, urlunsplit
from fastcore.basics import AttrDict
import abhyasa.journey  # adds Learning.journey
from abhyasa.journey import walk_state
from abhyasa.store import slugify

__all__ = ['find_step', 'is_local', 'pane_url']

# a copy of abhyasa.core.pane.is_local: abhyasa.core imports abhyasa's web UI (leela-reuse.md 5)
_BAD = re.compile(r'[\x00-\x1f\x7f\\]')
def is_local(url) -> bool:
    "Whether `url` is a path in this app: one `/` at the start, no scheme, no host, no backslash and no control character."
    return isinstance(url, str) and url.startswith('/') and not url.startswith('//') and not _BAD.search(url)

def pane_url(url) -> str|None:
    "`url` with `pane=1` in its query, when it is a local path; else None."
    if not is_local(url): return None
    p = urlsplit(url)
    q = [x for x in p.query.split('&') if x and not x.startswith('pane=')] + ['pane=1']
    return urlunsplit(('', '', p.path, '&'.join(q), p.fragment))

def find_step(lr, q) -> AttrDict:
    "The step, the done walk, the topic or the missing walk that the `read_handoff` result `q` names."
    if not q.walk:
        c = lr.concept(slugify(q.topic))
        return AttrDict(kind='topic', name=c.name if c else q.topic, concept=c)
    j = lr.journey(q.walk)
    if j is None: return AttrDict(kind='missing')
    i = walk_state(j).current if q.step is None else q.step
    if i is None: return AttrDict(kind='done', j=j)
    if i >= len(j.steps): raise ValueError(f'step: this walk has no step {i}')
    s = j.steps[i]
    c = lr.concept(s['slug'])
    return AttrDict(kind='step', j=j, i=i, step=s, name=c.name if c else s['slug'])
