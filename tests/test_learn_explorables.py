"""The circuit and signal explorables in the preview seed: the ideas, their demos, the course, and every page that shows them."""
import importlib.util
from pathlib import Path

import rupaka
from abhyasa.learner import temp_learning
from rupaka.spec import validate

from tests.test_learn_demo_crawl import crawl, walk  # noqa: F401
from tools import seed_learn_demo as sd

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('try_native_learn', ROOT/'tools'/'try_native_learn.py')
tnl = importlib.util.module_from_spec(spec); spec.loader.exec_module(tnl)

SLUGS = ['ohms-law', 'rc-circuit', 'rc-low-pass-filter', 'fourier-synthesis', 'sampling-aliasing', 'fourier-spectrum']
DEMOS = dict(zip(SLUGS, ['ohms-law', 'rc-charging', 'rc-low-pass', 'add-sine-waves', 'sampling-aliasing', 'the-spectrum']))


def test_the_rupaka_under_test_is_the_worktree_with_the_circuit_demos():
    print(rupaka.__file__)
    assert sd.circuits_ready() is None, rupaka.__file__


def test_seed_makes_six_ideas_each_with_its_valid_demo():
    lr = temp_learning(); sd.seed(lr, say=lambda *a: None)
    for slug in SLUGS:
        c = lr.concept(slug)
        assert c and c.statement and c.core and c.subject == 'circuits', slug
        d = lr.demo_for(slug)
        assert d and d.spec['id'] == DEMOS[slug] and not validate(d.spec), slug
    assert {s: list(lr.concept(s).prereqs) for s in SLUGS} == dict(zip(SLUGS, [[], ['ohms-law'], ['rc-circuit'], [], ['fourier-synthesis'], ['sampling-aliasing']]))


def test_seed_makes_a_course_and_a_walk_with_demo_checks_and_a_labelled_source():
    lr = temp_learning(); sd.seed(lr, say=lambda *a: None)
    j = lr.journey(sd.LOWPASS)
    assert j.title == 'How a low-pass filter works' and [s['slug'] for s in j.steps] == SLUGS[:3]
    assert all(s['check']['kind'] == 'demo' and s['read']['text'] and s['read']['title'] == 'Demo data' and s['read']['url'].startswith('https://') for s in j.steps)
    c = lr.course(j.course)
    assert c.title == 'Circuits and signals' and [s['walk'] for s in c.stages] == [sd.LOWPASS]
    assert any(a.concept == 'ohms-law' for a in lr.attempts())


def test_seed_twice_adds_nothing_and_a_vault_of_its_own_stays_alone():
    lr = temp_learning(); sd.seed(lr, say=lambda *a: None)
    n = lambda: (len(lr.concepts()), len(lr.demos()), len(lr.courses()), len(lr.journeys()), len(lr.attempts()))
    a = n(); sd.seed(lr, say=lambda *a: None); sd.circuits(lr, say=lambda *a: None)
    assert a == n()
    mine = temp_learning(); mine.put_journey(dict(id='mine', title='Mine', goal='', steps=[]))
    assert sd.seed(mine, say=lambda *a: None) is None and mine.concept('ohms-law') is None


def test_an_old_rupaka_skips_the_six_demos_and_says_so(monkeypatch):
    monkeypatch.setattr(sd, 'circuits_ready', lambda: sd.OLD)
    lr, out = temp_learning(), []
    sd.seed(lr, say=out.append)
    assert sd.OLD == 'rupaka too old for the circuit demos' and sd.OLD in out
    assert lr.concept('ohms-law') is None and not lr.demos('ohms-law') and lr.journey(sd.LOWPASS) is None and lr.journey('gw')
    assert sd.OLD in tnl.rupaka_line()


def test_launcher_takes_a_rupaka_and_the_banner_names_it():
    assert tnl.parse(['--rupaka', '/x/rupaka']).rupaka == '/x/rupaka'
    t = tnl.banner('http://127.0.0.1:9/', '/s', ('learn', '/s/v.db'), True, True, False, rupaka='rupaka 0.0.16  /x/rupaka')
    assert '\nrupaka 0.0.16  /x/rupaka\n' in t
    assert '\nrupaka ' not in tnl.banner('http://127.0.0.1:9/', '/s', ('learn', '/s/v.db'), True, True, False)


def test_every_new_idea_page_and_the_walk_render_and_load_the_rupaka_files(crawl):
    cl, lr, jid = crawl
    pages = walk(cl, [f'/c/{s}' for s in SLUGS] + [f'/w/{sd.LOWPASS}', *(f'/w/{sd.LOWPASS}/{i}' for i in range(3)), '/graph', '/library'])
    bad = {u: s for u, (s, _) in pages.items() if s >= 400}
    assert not bad, bad
    for s in SLUGS: assert pages[f'/c/{s}'][0] == 200 and "Show me" in pages[f'/c/{s}'][1], s
    for i in range(3):
        r = cl.get(f'/w/{sd.LOWPASS}/{i}/check', headers={'HX-Request': 'true'})
        assert r.status_code == 200 and 'data-rupaka' in r.text and '/rupaka/rupaka.js' in r.text and '/rupaka/rupaka.css' in r.text, i
        assert 'Demo data' in pages[f'/w/{sd.LOWPASS}/{i}'][1], i
    for f in ('js', 'css'): assert cl.get(f'/rupaka/rupaka.{f}').status_code == 200
    r = cl.get(f'/demo/{lr.demo_for("rc-circuit").slug}', follow_redirects=False)
    assert r.status_code in (200, 301), r.status_code
    assert cl.get(f'/demo/{lr.demo_for("rc-circuit").slug}.json').json()['id'] == 'rc-charging'


def test_the_first_step_has_code_that_shares_v_and_r_with_its_demo_and_the_ladder_follows(crawl):
    cl, lr, jid = crawl
    code = lr.journey(sd.LOWPASS).steps[0]['code']
    assert code['watch'] == ['V', 'R', 'I'] and code['expect'] == dict(var='I', value='2.0') and set(code['watch'][:2]) <= set(lr.demo_for('ohms-law').spec['state'])
    assert not any(s.get('code') for s in lr.journey(sd.LOWPASS).steps[1:])
    step = cl.get(f'/w/{sd.LOWPASS}/0').text
    assert 'lee-livecell' not in step or 'data-watch="V,R,I"' in step
    page = cl.get('/c/ohms-law').text
    assert 'The idea in four ways' in page and 'data-watch="V,R,I"' in page
    assert 'gate' not in cl.get('/c/ohms-law').text.split('As a picture')[1].split('As code')[0]   # the seed answered that gate right: no second lock
