# vendored from the abhyasa repo, tests/flows.py: only `done` and `goal_walk`, which the demo seed uses
import time

STEP = dict(way='words', kind='short', depth=2)

def done(lr, jid, *ix, outcome='solid'):
    "Close steps `ix` of walk `jid` with `outcome`, and raise the floor of their concepts, as a check does."
    j = lr.journey(jid)
    for i in ix:
        lr.walk_step(jid, i, done=dict(outcome=outcome, at=time.time()))
        lr.update(j.steps[i]['slug'], floor=4, seen=1, last=time.time(), stability=5., due=time.time() + 5 * 86400)
    return lr.journey(jid)

def goal_walk(lr, done_=0):
    "A goal walk of three ideas, as the Start box makes it, with the first `done_` ideas done."
    for n, pre in (('Noise', []), ('Denoise', ['noise']), ('Sample', ['denoise'])): lr.put(n, f'{n} a picture.', 'ml', prereqs=pre)
    lr.put_journey(dict(id='gw', title='Diffusion for comics', goal='Fine-tune diffusion for comics', mode='walk', source=None, started=time.time(), created=1.,
                        steps=[dict(slug=s, status='todo', check=dict(STEP)) for s in ('noise', 'denoise', 'sample')], chips=[], chip_counts={}))
    return done(lr, 'gw', *range(done_)) if done_ else lr.journey('gw')
