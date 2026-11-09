"""Fill a new Learn vault with demo data, from the fixtures of Abhyasa's own tests. Nothing here calls a real model or the network."""
import re, struct, sys, time, zlib
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

def tiny_png(n=8):
    "A small grey square, as PNG bytes."
    ck = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    return b'\x89PNG\r\n\x1a\n' + ck(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 0, 0, 0, 0)) + ck(b'IDAT', zlib.compress((b'\0' + b'\xd0'*n)*n)) + ck(b'IEND', b'')

def paper(lr, wd):
    "File the demo paper: its text has no picture link, which no page of Leela can open, and the figure of its second idea is a real file."
    keep = wd.PAGES
    wd.PAGES = [(n, re.sub(r'\n*!\[[^\]]*\]\([^)]*\)', '', t)) for n, t in keep]
    try: did = wd.add_paper(lr)
    finally: wd.PAGES = keep
    (lr.vault.assets('attention')/'images'/'fig2.png').write_bytes(tiny_png())
    return did

URL = 'https://arxiv.org/abs/1706.03762'

def seeded(lr): return first(j.id for j in lr.journeys() if j.get('demo') == 'paper')

def seed(lr, abh=ABHYASA, say=print):
    "Put a paper walk, a course, a talk and attempts over several days on `lr`. Idempotent; an `lr` that holds other walks is left alone. Returns the walk id, or None."
    if jid := seeded(lr): circuits(lr, say); say('demo data is already in this vault; nothing added'); return jid
    if len(lr.journeys()): say('this vault holds learning of its own; no demo data added'); return
    wd, td, fl = fixtures(abh)
    import rupaka.check
    from abhyasa.models import Fake
    from abhyasa.path import journey_from_source, join_course
    from abhyasa.show import talk_from_walk
    can, rupaka.check.can_check = rupaka.check.can_check, lambda: False
    try:
        jid = td.prep_walk(lr, journey_from_source(lr, Fake(td.TALK_RULES), paper(lr, wd), lr.vault.name).id)
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
    circuits(lr, say)
    say(f'DEMO DATA: a 3-idea paper walk, a course, a talk with {len(talk.slides)} slides and {len(ATTEMPTS)} attempts were added to this vault')
    return jid

CIRCUITS = 'circuits'
# slug, name, statement, core, rupaka demo id, source page, prerequisite slug
TOPICS = [('ohms-law', "Ohm's law", "The current through a resistor is the voltage across it divided by its resistance: I = V / R.",
           'Raise the voltage and the current rises. Raise the resistance and the current falls.', 'ohms-law', 'https://en.wikipedia.org/wiki/Ohm%27s_law', ''),
          ('rc-circuit', 'An RC circuit', 'A capacitor charges through a resistor. Its voltage rises toward the source voltage, and it holds about 63 percent of it after one time constant, tau = R x C.',
           'A bigger R or C makes the capacitor charge more slowly.', 'rc-charging', 'https://en.wikipedia.org/wiki/RC_circuit', 'ohms-law'),
          ('rc-low-pass-filter', 'An RC low-pass filter', 'An RC low-pass filter passes slow signals and weakens fast ones. At the cutoff frequency f = 1 / (2 pi R C), the output is about 71 percent of the input.',
           'The filter is the same circuit as the charging capacitor: the output is the capacitor voltage.', 'rc-low-pass', 'https://en.wikipedia.org/wiki/Low-pass_filter', 'rc-circuit'),
          ('fourier-synthesis', 'Adding sine waves', 'Many repeating waves are a sum of sine waves. Each sine wave has its own frequency, size and phase.',
           'Add more sine waves and the sum gets closer to the shape that you want.', 'add-sine-waves', 'https://en.wikipedia.org/wiki/Fourier_series', ''),
          ('sampling-aliasing', 'Sampling and aliasing', 'A signal sampled at a rate fs shows frequencies below fs / 2 correctly. A higher frequency looks like a lower one: it aliases.',
           'To see a frequency, take more than two samples in each of its cycles.', 'sampling-aliasing', 'https://en.wikipedia.org/wiki/Aliasing', 'fourier-synthesis'),
          ('fourier-spectrum', 'The frequency spectrum', 'The spectrum of a signal shows how much of each frequency it holds. A sum of sine waves shows one peak for each wave.',
           'The spectrum shows the same signal as the wave does, in frequencies in place of time.', 'the-spectrum', 'https://en.wikipedia.org/wiki/Spectral_density', 'sampling-aliasing')]
LOWPASS = 'lowpass'
OLD = 'rupaka too old for the circuit demos'

def circuits_ready():
    "None when the installed rupaka has the six circuit demos and the ghost trace, else the reason in one line."
    from rupaka.spec import gallery, manifests
    return None if 'ghost' in manifests().get('plot', {}).get('props', ()) and all(t[4] in gallery() for t in TOPICS) else OLD

def circuits(lr, say=print):
    "Add the subject `circuits`: six ideas with their rupaka demos, a course and a walk with demo checks, an attempt. Idempotent. Returns the walk id, or None."
    if lr.journey(LOWPASS): return LOWPASS
    if why := circuits_ready(): say(why); return
    from abhyasa.path import join_course, new_course
    from rupaka.spec import gallery, validate
    g, now = gallery(), time.time()
    for slug, name, st, core, did, url, pre in TOPICS:
        assert not validate(g[did]), did
        lr.put(name, st, CIRCUITS, slug=slug, prereqs=[pre] if pre else [], core=core, provenance=[dict(src='demo data', url=url)])
        lr.put_demo(g[did], slug)
    steps = [dict(slug=t[0], status='todo', why='', read=dict(src='demo', title='Demo data', what='Demo data', url=t[5], text=t[2]), check=dict(way='demo', kind='demo', depth=2, why='')) for t in TOPICS[:3]]
    c = lr.put_course(new_course('Understand how a low-pass filter works', 'Circuits and signals', CIRCUITS))
    lr.put_journey(dict(id=LOWPASS, title='How a low-pass filter works', goal=c.goal, subject=CIRCUITS, mode='walk', source=None, started=now - DAY, created=now - DAY, steps=steps, chips=[], chip_counts={}))
    join_course(lr, LOWPASS); lr.merge_journey(LOWPASS, demo='circuits')
    r = lr.record('ohms-law', 'What happens to the current when the resistance doubles?', answer='It halves.', correct=True, grade=9, feedback='Demo attempt.', kind='explain', depth=3)
    lr.mark_attempt(r.id, at=now - 5*DAY)
    say('DEMO DATA: six circuit and signal ideas with live demos, a course and a 3-step walk were added to this vault')
    return LOWPASS
