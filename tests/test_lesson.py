import json, re
from copy import deepcopy
import pytest
from abhyasa.method import METHODS, TEXT_WAYS
from abhyasa.tutor import HINTS, TUTOR_SP
from fastcore.xtras import fenced_blocks
from rupaka.spec import validate
from leela.blocks.nb.lesson import CHARTER_TAIL, demo_refusal, lesson_charter, fence, lesson_notebook, lock, parse_card, same_lines
from leela.blocks.nb.nb import Cell, Notebook

@pytest.mark.parametrize('guess,actual,rows', [
    ('', '', []),
    (' \n\t', '\r\n', []),
    ('  a\t b \n\n c  ', 'a b\r\nc', [('a b', 'a b', 'match'), ('c', 'c', 'match')]),
    ('A', 'a', [('A', 'a', 'mismatch')]),
    ('1\n2', '1\n3', [('1', '1', 'match'), ('2', '3', 'mismatch')]),
    ('a', 'a\nb', [('a', 'a', 'match'), (None, 'b', 'missing')]),
    ('a\nb', 'a', [('a', 'a', 'match'), ('b', None, 'extra')]),
    ('', 'x', [(None, 'x', 'missing')]),
    ('x', '', [('x', None, 'extra')]),
    ('a\nb', 'b\na', [('a', 'b', 'mismatch'), ('b', 'a', 'mismatch')]),
    ('  नमस्ते\t world ', 'नमस्ते world', [('नमस्ते world', 'नमस्ते world', 'match')]),
])
def test_same_lines(guess, actual, rows):
    assert same_lines(guess, actual) == [dict(guess=g, actual=a, kind=k) for g, a, k in rows]

@pytest.mark.parametrize('text,expected', [
    ('### Question\nWhat prints?\n\n### Thinking\nFirst line.\nSecond line.',
     dict(question='What prints?', thinking='First line.\nSecond line.')),
    ('<!-- Write here.\n### Question\nHidden. -->\n### Question\nWhy?\n### Thinking\nBecause.\n<!-- instructions -->',
     dict(question='Why?', thinking='Because.')),
    ('### Thinking\nBecause.\n### Question\nWhy?\n### Feedback\nNot card input.', dict(question='Why?', thinking='Because.')),
    ('### question\nWhy?\n### THINKING\nBecause.', dict(question='Why?', thinking='Because.')),
    ('### Question\n```python\n### Thinking\n```\nWhy?', dict(question='```python\n### Thinking\n```\nWhy?', thinking='')),
    ('### Question\nOnly a question.', dict(question='Only a question.', thinking='')),
    ('No sections.', dict(question='', thinking='')),
    ('', dict(question='', thinking='')),
])
def test_parse_card(text, expected): assert parse_card(text) == expected

@pytest.mark.parametrize('confidence', [None, 10, 30, 50, 70, 90])
@pytest.mark.parametrize('count', [None, 7])
def test_lock_records_this_execution_and_keeps_other_metadata(confidence, count):
    c = Cell(execution_count=count, extra={'other': {'keep': True}, 'lesson': {'saved': 'old', 'for_count': 3}})
    lock(c, '  My guess.\nSecond line. ', confidence)
    assert c.extra == {'other': {'keep': True}, 'lesson': {
        'prediction': '  My guess.\nSecond line. ', 'for_count': count, 'confidence': confidence}}
    c.execution_count = 8
    lock(c, 'New guess.')
    assert c.extra['lesson'] == dict(prediction='New guess.', for_count=8, confidence=None)

@pytest.mark.parametrize('confidence', [0, 20, 60, 100, True, '70', ''])
def test_invalid_confidence_does_not_mutate(confidence):
    c = Cell(extra={'lesson': {'prediction': 'Before', 'for_count': 1}, 'other': 1})
    before = deepcopy(c.dict())
    with pytest.raises(ValueError): lock(c, 'After', confidence)
    assert c.dict() == before

@pytest.mark.parametrize('prediction', ['', ' \n\t'])
def test_lock_without_prediction_clears_only_lesson(prediction):
    c = Cell(extra={'lesson': {'prediction': 'Old'}, 'other': 1})
    lock(c, prediction)
    assert c.extra == {'other': 1}

@pytest.mark.parametrize('text', ['plain', '```', '`````', '`start ``` middle ````` end`', 'नमस्ते\n"quoted"\\path'])
def test_fence_has_one_json_line_and_safe_backticks(text):
    spec = {'title': text, 'nested': {'answer': [1, True, None]}}
    rendered = fence(spec)
    opening, body, closing = rendered.split('\n')
    ticks = opening.removesuffix('rupaka')
    assert set(ticks) == {'`'} and closing == ticks
    assert len(ticks) >= 3
    assert len(ticks) > max(map(len, re.findall(r'`+', body)), default=0)
    assert body == json.dumps(spec, ensure_ascii=False)
    assert json.loads(body) == spec
    assert fenced_blocks(rendered)[0][:2] == ('rupaka', body + '\n')

def test_lesson_notebook_template_and_metadata_roundtrip():
    nb = lesson_notebook('Softmax')
    assert isinstance(nb, Notebook) and nb.path == ''
    assert nb.meta['lesson'] == dict(v=1, name='Softmax')
    assert len(nb) == 5
    intro, demo, prediction, code, card = nb.cells
    assert [c.cell_type for c in nb.cells] == ['markdown', 'markdown', 'markdown', 'code', 'markdown']
    assert 'Softmax' in intro.source and 'lesson notebook' in intro.source
    assert demo.source == 'No demo yet. Ask the tutor to add one.'
    assert len({c.id for c in nb.cells}) == 5
    assert prediction.extra['lesson'] == {'role': 'prediction', 'for': code.id}
    assert card.extra['lesson'] == {'role': 'card', 'for': code.id}
    assert '### Question' in card.source and '### Thinking' in card.source
    assert '<!--' in card.source and '-->' in card.source
    assert parse_card(card.source) == dict(question='', thinking='')
    compile(code.source, '<lesson>', 'exec')
    assert code.source.strip()
    assert all(Cell.from_nb(c.nbcell()).extra == c.extra for c in nb.cells)
    other = lesson_notebook('Other')
    assert not {c.id for c in nb.cells} & {c.id for c in other.cells}
    nb.meta['lesson']['name'] = 'Changed'
    prediction.extra['lesson']['role'] = 'changed'
    assert other.meta['lesson']['name'] == 'Other'
    assert other[2].extra['lesson']['role'] == 'prediction'

def test_charter_uses_dependency_rules_and_hint_order(abhyasa_cfg):
    charter = lesson_charter()
    assert charter == TUTOR_SP + CHARTER_TAIL
    assert 'adult' in charter and 'never praise effort' in charter.lower()
    positions = [CHARTER_TAIL.index(f'{i}. {hint}') for i, hint in enumerate(HINTS, 1)]
    assert positions == sorted(positions)
    assert 'add_demo' in CHARTER_TAIL
    assert 'never write the reveal' in CHARTER_TAIL.lower()
    assert 'another way' in CHARTER_TAIL.lower() and 'not yet used' in CHARTER_TAIL
    ways = [l for l in CHARTER_TAIL.splitlines() if l.startswith('- ')]
    assert ways == [f'- {n}: {METHODS[n]}' for n in TEXT_WAYS]          # board, timeline and playground are not lesson ways yet

def test_demo_refusal_preserves_real_validator_lines():
    errors = validate({})
    assert errors
    assert demo_refusal(errors) == '\n'.join(errors)
    assert all(line in demo_refusal(errors).splitlines() for line in errors)
    assert demo_refusal(['  keep spaces  ']) == '  keep spaces  '
    assert demo_refusal([]) == ''
