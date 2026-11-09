import json
from tools.scripted_learn import reply, PLAN


def test_the_core_prompt_gets_a_core():
    out = json.loads(reply('Concept: Fractions\nReturn JSON: {"core": str, "wrong": [{"think": str, "fact": str}]}', 'You say what a learner must understand'))
    assert out['core'] and out['wrong'][0]['fact']


def test_the_plan_prompt_still_gets_the_plan():
    assert reply('Return JSON: {"steps": [{"name": str, "core": str, "wrong": [{"think": str, "fact": str}]}]}', 'You plan') == PLAN
