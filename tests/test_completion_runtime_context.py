"""The resident completion model sees code context and the selected runtime namespace."""

import importlib.util

from leela.blocks.fs.fs import Sandbox
from leela.blocks.search.search import Search
from leela.agent.agent import Completer
from leela.agent.core import LLAMA, available_models, resolve


class Host:
    def list_vars(self): return 'frame: DataFrame = DataFrame [18×4]\nthreshold: float = 0.73'


class Agent:
    host = Host()


def test_completion_prompt_includes_related_code_and_runtime_variables():
    c = Completer(Agent())
    prompt = c._prompt('frame.', 6, 'python', 'def clean(frame):\n    return frame.dropna()')
    assert '<related_code>' in prompt and 'def clean(frame)' in prompt
    assert '<runtime_variables>' in prompt and 'threshold: float = 0.73' in prompt
    assert '<before>\nframe.' in prompt


def test_kosha_adds_dynamic_patch_methods_to_runtime_completion(tmp_path):
    class Store:
        def rows_where(self,*a,**kw):
            return [{'content':'def read_json(self:Path, encoding=None): pass',
                     'metadata':{'name':'read_json','mod_name':'fastcore.xtras.read_json',
                                 'docstring':'Read JSON from this path'}}]
    class Kosha:
        code_st=env_st=Store()
        def public_api(self,*a,**kw): return []
    s=Search(Sandbox([tmp_path])); s._k=Kosha(); s._k_tried=True
    code='from fastcore.all import Path\np: Path\np.re'
    out=s.merge_completions(code,len(code),{'from':len(code)-2,'matches':['read_text']})
    assert out['matches']==['read_text','read_json']
    assert out['graph'][0]['symbol']=='fastcore.xtras.read_json'


def test_llama_cpp_models_are_explicit_optional_local_choices():
    spec = resolve('llama-qwen-0.6b')
    assert spec.backend == 'llama' and spec.local
    assert spec.model_id == LLAMA['llama-qwen-0.6b']


def test_llama_models_only_appear_when_llama_cpp_is_installed():
    rows = available_models()
    shown = any(r['value'] == 'llama-qwen-0.6b' and r['provider'] == 'llama.cpp' for r in rows)
    assert shown is (importlib.util.find_spec('llama_cpp') is not None)
