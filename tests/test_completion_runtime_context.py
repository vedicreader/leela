"""The resident completion model sees code context and the selected runtime namespace."""

from leela.blocks.fs.fs import Sandbox
from leela.blocks.search.search import Search
from leela.agent.agent import Completer


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
