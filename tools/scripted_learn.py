r"""The scripted model for native Learn. Its replies are canned and nothing leaves the machine. The end-to-end test and `try_native_learn.py` use the same one."""
from tools.s2_native_pilot import PLAN

QUESTION = r'{"question": "What does a fraction name?", "code": "", "answer": "Equal parts of a whole.", "core": "A fraction names equal parts of a whole.", "also": [], "wrong": ""}'
GRADE = r'{"correct": true, "grade": 10, "feedback": "Correct.", "first_error": "", "misconception": ""}'

def reply(prompt, sp, max_tokens=0, deadline=None):
    "The canned answer to one engine call: a question, a grade, or else the plan."
    if 'Write ONE question' in prompt: return QUESTION
    if 'grade' in sp.lower() or 'correct' in sp.lower(): return GRADE
    return PLAN

def install_scripted(ws):
    "Point every job on `ws` at a scripted model that answers each message by calling `create_walk` on it."
    from ramabana.core import ModelSpec
    from tests.fakemodel import Step, install
    be = install(ws, [], token_delay=0, spec=ModelSpec('hosted-scripted', 'remote', 'scripted/model', ctx=8000))
    be.supports_deadline, be._oneshot = True, reply
    run = be._run
    def _run(msg):
        be.steps = [Step(text='Making your module.', tool=('create_walk', dict(goal=str(msg))))]
        yield from run(msg)
    be._run = _run
    return be