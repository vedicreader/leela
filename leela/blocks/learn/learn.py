from fastcore.basics import AttrDict
import abhyasa.journey  # adds Learning.journey
from abhyasa.journey import walk_state
from abhyasa.store import slugify

__all__ = ['find_step']

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
