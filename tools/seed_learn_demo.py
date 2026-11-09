"""Fill a new Learn vault with demo data, from the fixtures of Abhyasa's own tests. Nothing here calls a real model or the network."""
import sys, time
from fastcore.basics import first
from pathlib import Path

ABHYASA = Path(__file__).resolve().parent.parent.parent/'abhyasa-native-learn'
DAY = 86400
ATTEMPTS = [('softmax', 'What does softmax give for a list of scores?', 'Weights above 0 that add to 1.', True, 9, 6),
            ('softmax', 'Why do large scores matter to softmax?', 'They get all the weight.', True, 7, 4),
            ('sequential-computation', 'Why can a recurrent model not run in parallel?', 'It needs the last step first.', True, 8, 3),
            ('scaling-by-the-root-of-dk', 'Why divide by the root of dk?', 'To make the scores smaller.', False, 4, 1)]

def fixtures(abh=ABHYASA):
    "The walk, talk and flow fixtures of Abhyasa's tests, found beside its worktree."
    t = str(Path(abh)/'tests')
    if t not in sys.path: sys.path.append(t)
    import walk_data, talk_data, flows
    return walk_data, talk_data, flows

URL = 'https://arxiv.org/abs/1706.03762'

def seeded(lr): return first(j.id for j in lr.journeys() if j.get('demo') == 'paper')

def seed(lr, abh=ABHYASA, say=print):
    "Put a paper walk, a course, a talk and attempts over several days on `lr`. Idempotent; an `lr` that holds other walks is left alone. Returns the walk id, or None."
    if jid := seeded(lr): say('demo data is already in this vault; nothing added'); return jid
    if len(lr.journeys()): say('this vault holds learning of its own; no demo data added'); return
    wd, td, fl = fixtures(abh)
    import rupaka.check
    from abhyasa.models import Fake
    from abhyasa.path import journey_from_source, join_course
    from abhyasa.show import talk_from_walk
    can, rupaka.check.can_check = rupaka.check.can_check, lambda: False
    try:
        jid = td.prep_walk(lr, journey_from_source(lr, Fake(td.TALK_RULES), wd.add_paper(lr), lr.vault.name).id)
        lr.merge_journey(jid, demo='paper')
        for i, s in enumerate(lr.journey(jid).steps): lr.walk_step(jid, i, read={**s['read'], 'url': URL})
        now = time.time()
        fl.done(lr, jid, 0)
        talk = talk_from_walk(lr, Fake(td.TALK_RULES), jid)
        lr.put_talk({**talk, 'demo': True})
        fl.goal_walk(lr, 1); lr.merge_journey('gw', demo=True); join_course(lr, 'gw')
        for slug, q, a, ok, grade, days in ATTEMPTS:
            if lr.concept(slug) is None: continue
            r = lr.record(slug, q, answer=a, correct=ok, grade=grade, feedback='Demo attempt.', kind='explain', depth=3)
            lr.mark_attempt(r.id, at=now - days*DAY)
    finally: rupaka.check.can_check = can
    say(f'DEMO DATA: a 3-idea paper walk, a course, a talk with {len(talk.slides)} slides and {len(ATTEMPTS)} attempts were added to this vault')
    return jid
