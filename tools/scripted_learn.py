r"""The scripted model for native Learn. Its replies are canned and nothing leaves the machine. The end-to-end test and `try_native_learn.py` use the same one.

`reply` finds the task from the markers of the prompt that Abhyasa builds (`tutor.py`, `path.py`, `show.py`), never from the system prompt alone, and answers in the shape that the parser of that task reads. Each reply uses the name and the statement that the prompt gives."""
import json, re

FRACTIONS = {
 'equal parts': dict(
  note='Cut a pizza into four slices of one size. Each slice is one of four equal parts of the pizza.',
  q='A pizza is cut into 4 slices of the same size. What does one slice name?', a='One of four equal parts of the pizza.',
  hint='Look at the sizes of the slices. What is true about them?', check='Predict this: a bar is cut into 3 pieces, and one piece is bigger. Is each piece one third?',
  fe='The parts of a fraction must have the same size.', wrong='Any piece of a whole is a fraction.'),
 'comparing fractions': dict(
  note='Two friends share the same cake size. One eats 1 of 4 slices, the other 1 of 8 slices. The first friend eats more.',
  q='You eat 1 of 4 equal slices of a cake, and a friend eats 1 of 8 equal slices of the same cake. Who eats more?', a='You eat more, because fourths are bigger than eighths.',
  hint='Think about how many slices make the whole cake. What happens to the size of each slice?', check='Predict this: which is bigger, 1 of 3 equal parts or 1 of 5 equal parts?',
  fe='A bigger number of parts means each part is smaller.', wrong='A bigger denominator makes a bigger fraction.'),
 'adding fractions': dict(
  note='You eat 1 of 5 slices of a cake and then 2 more of the same 5 slices. You ate 3 of the 5 slices.',
  q='A cake has 5 equal slices. You eat 1 slice, then 2 more slices. What fraction of the cake did you eat?', a='3 of 5, because the slices have the same size and you add the numerators.',
  hint='The slices have the same size. What do you count when you add them?', check='Predict this: what is 2 of 7 parts plus 3 of 7 parts?',
  fe='Fractions with the same denominator add by adding their numerators.', wrong='You add the numerators and the denominators.')}

PLAN = r'''{"title": "Fractions", "subject": "maths", "steps": [
 {"name": "Equal parts", "statement": "A fraction names equal parts of a whole thing.", "why": "Every fraction starts from equal parts.", "ways": ["words"]},
 {"name": "Comparing fractions", "statement": "With the same whole, more equal parts make each part smaller.", "why": "You compare sizes before you add them.", "ways": ["words"]},
 {"name": "Adding fractions", "statement": "Fractions with one denominator add by adding numerators.", "why": "Adding is the first use of equal parts.", "ways": ["words"]}]}'''

STOP = set('that with this from their each what have when does into your they them then than also only about which there would could should because over under same'.split())

def _clean(s): return re.sub(r'</?source[^>]*>', '', s or '').strip().strip('"').strip()
def _line(p, *keys):
    "The first value after any of `keys` at the start of a line of `p`."
    for k in keys:
        if m := re.search(rf'^{re.escape(k)}[^\n:]*:\s*(.+)$', p, re.M): return _clean(m[1])
    return ''
def _name(p): return _line(p, 'Concept', 'Idea') .split(' (subject')[0] or 'this idea'
def _said(p): return _line(p, 'Statement', 'Reference statement', 'The learner already sees this', 'In plain words') or _line(p, 'What the learner must understand', 'The core to teach', 'Core point')
def _core(p): return _line(p, 'What the learner must understand', 'Core point', 'The core to teach') or _said(p)
def _row(p): return FRACTIONS.get(_name(p).lower(), {})
def _stems(t): return {w[:5] for w in re.findall(r'[a-z]+', (t or '').lower()) if len(w) > 3 and w not in STOP}
def _j(**kw): return json.dumps(kw)
def _goal(p): return ' '.join(_clean(re.search(r'^Goal:\s*(.*?)(?=\n[A-Z][^\n]*:|\n\nReturn JSON|\Z)', p, re.S | re.M)[1] if re.search(r'^Goal:', p, re.M) else '').split())

def plan(p):
    "The plan of the goal in `p`: the fractions plan, or three steps named from the goal."
    g = re.sub(r'^(teach me|learn|explain|show me)( about)?\s+', '', re.sub(r'</?user-request>', '', _goal(p)).strip(), flags=re.I).strip(' .') or 'this topic'
    if 'fraction' in g.lower() or g == 'this topic': return PLAN
    t = g[0].upper() + g[1:]
    return _j(title=t[:40], subject='general', steps=[
        dict(name=f'What {g} is', statement=f'{t} is an idea with a clear meaning that you can say in one sentence.', why='Every later step builds on it.', ways=['words']),
        dict(name=f'A small case of {g}', statement=f'One small case of {g} shows what the idea does.', why='A case makes the idea concrete.', ways=['words']),
        dict(name=f'Using {g}', statement=f'You use {g} when you meet a new case and apply the same idea.', why='Use shows that you know it.', ways=['words'])])

def core(p):
    n, s = _name(p), _said(p) or f'{_name(p)} is one idea.'
    return _j(core=s, wrong=[dict(think=f'{n} is only a word to remember.', fact=s)])

def question(p):
    n, r, c = _name(p), _row(p), _core(p)
    q = r.get('q') or f'Think of one everyday case of {n.lower()}. What makes it a case of this idea?'
    out = dict(question=q, code='', answer=r.get('a') or c, core=c or r.get('a') or n, also=[], wrong=r.get('wrong', ''))
    if '"options"' in p:
        out |= dict(options=[dict(text=out['answer'], misconception=''), dict(text=f'It has nothing to do with {n.lower()}.', misconception=f'{n} is only a word.'),
                             dict(text='It depends on the colour of the page.', misconception='Looks decide the answer.')], correct=0)
    return _j(**out)

def grade(p):
    n, r = _name(p), _row(p)
    ans = _line(p, "Learner's answer")
    keys = _stems(_line(p, 'Core point') + ' ' + _line(p, 'Model answer'))
    ok = bool(ans) and ans != '(none)' and bool(_stems(ans) & keys)
    fe = r.get('fe') or f'The answer does not yet say the key point of {n.lower()}.'
    return _j(core_met=ok, correct=ok, also_met=0, grade=8 if ok else 3, slip='', known=-1, gaps=[], asks_for='', first_error='' if ok else fe,
              misconception='' if ok else r.get('wrong') or f'{n} is only a word to remember.',
              feedback=f'Correct. You said the key point of {n.lower()}. Next, use it in a new case.' if ok else f'Not yet. {fe} Think of one small case of your own. What does the idea tell you about it?')

def hint(p):
    n, k = _name(p), int(m[1]) if (m := re.search(r'Give hint level (\d+)', p)) else 1
    return (_row(p).get('hint') if k == 1 else '') or [f'Read the question again. Find the part that is about {n.lower()}.', f'Think of a small case of {n.lower()}. What happens in it?',
        f'Name the kind of idea that {n.lower()} is.', f'Say the rule of {n.lower()} in one sentence, without the numbers.', f'Say the first step that you would take, and why.',
        'Do the first step of a small case. Then do the next step yourself.'][min(k, 6) - 1]

def lesson(p):
    n, s, r = _name(p), _said(p) or _core(p), _row(p)
    chk = r.get('check') or f'Predict this: what do you see in a new case of {n.lower()}?'
    return f"1. Start with one small case of {n.lower()}: {r.get('note') or 'a thing that you can see and count.'}\n2. Look at what the case shows. {s}\n3. Say why it holds: the case follows the idea, so the idea fits the next case too.\nCheck: {chk}"

def explain(p):
    n, s, r = _name(p), _said(p), _row(p)
    if '3 or 4 short numbered steps' not in p: return f"{n} starts from one small case. {s} Look at the case again and find the idea in it."
    return f"1. Start with one small case of {n.lower()}: {r.get('note') or 'a thing that you can see and count.'}\n2. Look at what the case shows. {s}\n3. Say the idea in your own words, then look at the case again."

def note(p):
    n = _name(p)
    return _row(p).get('note') or f'You meet {n.lower()} in daily life, when you share, count or compare things. Look for one case near you.'

def research(p):
    n = _name(p)
    return _j(queries=[f'{n} explained simply', f'{n} for beginners with examples'])

def talk(p):
    n, s = _name(p), _said(p) or _name(p)
    return _j(points=[f'Start with one case that all can see: {n.lower()}.', s, f'Look at the case again and find {n.lower()} in it.'],
              say=f'Show one small case of {n.lower()} first. Then say the idea. Then let them find it in the case.', ask=f'Where do you meet {n.lower()} in your day?', watch=f'Some people say {n.lower()} is only a word. It is an idea that you can use.')

def vision(p): return _j(labels=[dict(text='Whole', box=[100, 100, 400, 250]), dict(text='Part', box=[500, 100, 800, 250])])

def board(p):
    n = _line(p, 'Concept') or _line(p, 'Page') or 'this idea'
    steps = [f'Start with one small case that you can picture.', f'Next, see what the case shows about {n.lower()}.', 'Last, say the idea in your own words, then try the check.']
    return '\n'.join([_j(op='v', n=1, sure=0.8, need='none'), *(_j(op='step', say=s) for s in steps)])

def plain(p):
    "The text that a rewrite asks to write again, unchanged: it is already plain."
    return m[1] if (m := re.search(r'(?:The text:|The texts, as JSON:)\n(.*?)\n\n(?:Its|The) problems', p, re.S)) else p

def shaped(p):
    "A reply for a JSON shape that no task above knows: each key gets a short value of its type."
    n, tail = _name(p), p.rsplit('Return JSON:', 1)[1]
    one = dict(str=f'A short line about {n.lower()}.', int=1, bool=True)
    def val(t): return ([one[t.strip('[]')]] if t.strip('[]') in one else []) if t.startswith('[') else one.get(t, '')
    return _j(**{k: val(t) for k, t in re.findall(r'"(\w+)":\s*(\[?(?:str|int|bool)\]?|\[|\{)', tail)})

def paragraph(p):
    n = _name(p)
    return f'{n[0].upper() + n[1:]} is one idea with one clear point. Start from a small case, see what it shows, and then say the idea in your own words.'

def reply(prompt, sp, max_tokens=0, deadline=None):
    "The canned answer to one engine call, found from the markers of its prompt; the plan, a grade or a paragraph when the prompt has none."
    p, s = prompt, sp or ''
    a = f'{p}\n{s}'   # a shape can be in the system prompt
    if 'Write this text again' in p or 'Write these texts again' in p: return plain(p)
    if 'Write ONE question' in p: return question(p)
    if 'Return JSON: {"core_met"' in p: return grade(p)
    if 'Give hint level' in p: return hint(p)
    if 'Their first error:' in p: return lesson(p)
    if 'What the learner does not get:' in p: return explain(p)
    if 'You write a short note' in s or 'Your last note said' in p: return note(p)
    if '"core": str, "wrong"' in a and '"name": str' not in a: return core(p)
    if '"steps": [{"name"' in a: return plan(p)
    if '{"queries"' in a: return research(p)
    if '"points": [' in a: return talk(p)
    if '"labels": [{"text"' in a: return vision(p)
    if 'Reply with the JSON lines.' in p: return board(p)
    if 'Return JSON:' in a: return shaped(a)
    if re.match(r'\s*you grade', s, re.I): return grade(p)
    if re.match(r'\s*(you )?plan', s, re.I): return plan(p)
    return paragraph(p)

def install_scripted(ws):
    "Point every job on `ws` at a scripted model that answers each message by calling `create_walk` on it."
    from ramabana.core import ModelSpec
    from tests.fakemodel import Step, install
    be = install(ws, [], token_delay=0, spec=ModelSpec('hosted-scripted', 'remote', 'scripted/model', ctx=8000))
    be.supports_deadline, be._oneshot = True, reply
    run = be._run
    def _run(msg):
        be.steps = [Step(text='Making your module.', tool=('create_walk', dict(goal=str(msg), research='no')))]
        yield from run(msg)
    be._run = _run
    return be
