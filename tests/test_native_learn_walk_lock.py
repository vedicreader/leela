import threading

from abhyasa.agent_tools import create_walk
from abhyasa.learner import temp_learning

from leela.blocks.learn.walk import answer_for, walk_state_for
from leela.blocks.memory.memory import _open_lock
from tools.s2_native_pilot import PLAN


def test_the_walk_routes_open_the_vault_before_they_take_its_lock(tmp_path):
    lr = temp_learning()
    class Memory:
        path = tmp_path/'vault.db'
        def _store(self, shelf):
            with _open_lock(self.path): return lr.v
    jid = create_walk(lr, lambda prompt, sp='': PLAN, 'fractions', settings={})['walk']
    for name, call in dict(state=lambda: walk_state_for(Memory(), jid, {}), answer=lambda: answer_for(Memory(), lambda prompt, sp='': '{}', jid, 99, 'a', 'k', {})).items():
        out = []
        t = threading.Thread(target=lambda: out.append(call()), daemon=True); t.start(); t.join(10)
        assert out, f'{name} waits on the vault lock that its own `_store` takes'