import json
from tools.scripted_learn import reply, PLAN


def test_the_core_prompt_gets_a_core():
    out = json.loads(reply('Concept: Fractions\nReturn JSON: {"core": str, "wrong": [{"think": str, "fact": str}]}', 'You say what a learner must understand'))
    assert out['core'] and out['wrong'][0]['fact']


def test_the_plan_prompt_still_gets_the_plan():
    assert reply('Return JSON: {"steps": [{"name": str, "core": str, "wrong": [{"think": str, "fact": str}]}]}', 'You plan') == PLAN


# One test for each task of the hosted app: the prompt comes from the Abhyasa builder and the reply goes through the Abhyasa parser.
import pytest
from abhyasa.agent_tools import create_walk
from abhyasa.learner import temp_learning
from abhyasa.tutor import Tutor
from abhyasa import path as P, show as S

ask = lambda p, sp='': reply(p, sp)

@pytest.fixture
def walk():
    lr = temp_learning()
    jid = create_walk(lr, ask, 'teach me fractions', settings={})['walk']
    return lr, jid, Tutor(lr, ask, sources=[]), lr.journey(jid)

def _open(walk, i=0):
    lr, jid, t, j = walk
    q = P.open_short(t, j, i, 's1')
    return t, t.open[q.id]

def _clean(x): assert x.strip() and '{' not in x and 'could not' not in x, x

def test_plan_gives_three_steps(walk):
    lr, jid, t, j = walk
    assert [s['slug'] for s in j.steps] and len(j.steps) == 3 and all(lr.concept(s['slug']).statement for s in j.steps)

def test_plan_names_steps_from_another_goal():
    from abhyasa.path import plan_prompt
    out = json.loads(reply(plan_prompt('teach me the water cycle'), 'You plan'))
    assert len(out['steps']) == 3 and 'water cycle' in out['steps'][0]['name']

def test_core_prompt_gets_a_core(walk):
    lr, jid, t, j = walk
    c = lr.concept(j.steps[1]['slug']); assert not c.get('core')
    from abhyasa.sources import understand
    c = understand(lr, ask, c)
    assert c.core == c.statement and c.wrong[0]['fact']

def test_note_is_one_plain_text(walk):
    lr, jid, t, j = walk
    n = P.tutor_note(lr, ask, j, 0, t.sources)
    _clean(n); assert 'slice' in n

def test_note_of_an_idea_with_no_table_row_names_the_idea(walk):
    lr, jid, t, j = walk
    c = lr.put('Tides', 'The Moon pulls on the sea.', 'science')
    n = reply(f"Idea: {json.dumps(c.name)}\nThe learner already sees this, in the tutor's words: {json.dumps(c.statement)}\n\nUse at most 40 words.", 'You write a short note for a learner on one idea.')
    _clean(n); assert 'tides' in n.lower()

def test_question_prompt_gets_one_question(walk):
    t, q = _open(walk, 2)
    assert q.question.endswith('?') and q.question.count('?') == 1 and '{' not in q.question and q.answer and q.core

def test_choice_prompt_gets_options(walk):
    lr, jid, t, j = walk
    from abhyasa.tutor import question_prompt
    out = json.loads(reply(question_prompt(lr.concept(j.steps[0]['slug']), 1), 'You are a tutor'))
    assert len(out['options']) == 3 and out['options'][out['correct']]['text']

def test_a_right_answer_passes_and_a_wrong_one_names_its_error(walk):
    t, q = _open(walk)
    ok = t._grade(q, 'One of four equal parts of the pizza', '', 70)
    assert ok.correct and 'Correct' in ok.feedback and not ok.first_error
    bad = t._grade(q, 'banana', '', 70)
    assert not bad.correct and bad.first_error and bad.misconception and bad.feedback.count('?') == 1
    assert not t._grade(q, '', '', 70).correct

def test_hint_is_one_sentence(walk):
    t, q = _open(walk)
    h = t.hint(q.id); _clean(h)
    assert len(h.split('. ')) <= 2 and h != t.hint(q.id)

def test_lesson_is_three_numbered_steps_and_a_check(walk):
    t, q = _open(walk)
    l = t._lesson(q, 'The parts need the same size.')
    assert [x[:2] for x in l.splitlines()[:3]] == ['1.', '2.', '3.'] and 'Check:' in l and t.checks[q.concept][0].endswith('?')

def test_dont_know_closes_with_a_lesson(walk):
    t, q = _open(walk)
    r = t.answer(q.id, dont_know=True)
    assert r.done and not r.correct and r.lesson.startswith('1.') and '{' not in r.lesson

def test_research_gives_two_queries(walk):
    lr, jid, t, j = walk
    qs = P._more_queries(ask, lr, j, 0, [])
    assert len(qs) == 2 and all(2 <= len(x.split()) <= 6 for x in qs)

def test_talk_slide_gets_points_and_notes(walk):
    lr, jid, t, j = walk
    s = dict(id='s1', kind='idea', concept=j.steps[0]['slug'], title='Equal parts', show={}, beats=[], notes='', ask=dict(kind='words', q=S.words_q('Equal parts'), most=80))
    out = S.fill_slide(lr, ask, s)
    assert len(out['show']['body']) >= 2 and 'Ask the room' in out['notes'] and '{' not in out['notes']

def test_figure_labels_read_the_vision_reply():
    assert set(S.figure_labels(lambda p, img, sp='': reply(p, sp), b'\x89PNG', 'two boxes')) == {'Whole', 'Part'}

def test_board_has_numbered_steps():
    ctx = dict(page='/w/x/0', step='Equal parts', concept='Equal parts', anchors=[dict(id='passage', kind='passage', text='A fraction names equal parts.')])
    r = S.explain(ask, ctx, "I don't get equal parts", web=False)
    assert len(r.steps) == 3 and r.steps[0]['say'] and not r.failed

def test_a_rewrite_keeps_the_text(walk):
    from rupaka.agent import plain
    x = 'A fraction names equal parts; the parts have the same size.'
    assert plain(ask, x, ['fraction']) == x
    assert plain(ask, dict(a=x), ['fraction']) == dict(a=x)

def test_other_json_shapes_still_parse():
    out = json.loads(reply('Idea: Tides\nReturn JSON: {"name": str, "size": int, "ok": bool, "items": [str]}', 'You write'))
    assert out['name'] and out['size'] == 1 and out['ok'] is True and out['items']

def test_a_free_prompt_gets_a_paragraph():
    t = reply('Ask about this: Concept: Tides', 'You answer. Write at a US grade 9 level.')
    _clean(t)

@pytest.mark.parametrize('name', ['Equal parts', 'Tides'])
def test_demo_prompt_gets_a_spec_that_passes_rupakas_validator_and_check(name):
    from rupaka.agent import demo_prompt, demo_sp
    from rupaka.check import check
    from rupaka.spec import validate
    spec = json.loads(reply(demo_prompt(dict(name=name, statement='One idea.')), demo_sp()))
    assert not list(validate(spec)) and not check(spec).errors and name.lower() in spec['blocks'][0]['prompt']
    assert [b['type'] for b in spec['blocks']][:2] == ['gate', 'slider'] and len(spec['blocks'][0]['options']) == 3

@pytest.mark.parametrize('name', ['Equal parts', 'Tides'])
def test_explainer_prompt_gets_a_scene_that_passes_both_checks(name):
    from rupaka.spec import validate
    spec = json.loads(reply(S.explainer_prompt(dict(name=name, statement='One idea.')), S.explainer_sp()))
    assert not list(validate(spec)) and not S.scene_errors(spec) and name.lower() in spec['blocks'][0]['steps'][0]

def test_make_demo_and_make_explainer_save_specs(walk):
    lr, jid, t, j = walk
    slug = j.steps[0]['slug']
    d = S.make_demo(lr, ask, slug, check=True)
    e = S.make_explainer(lr, ask, slug)
    assert d and d.spec['blocks'][0]['type'] == 'gate' and e and e.spec['blocks'][0]['type'] == 'scene'
