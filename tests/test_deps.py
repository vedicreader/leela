"The Claude Code runtime chain imports, and the suite bounds every test and every ask."
import tomllib
from pathlib import Path

def test_the_claude_code_runtime_chain_imports():
    "`rishi.claude` → `claude_agent_sdk`; the desktop bundle test (`test_packaging.py:408`) once died on this."
    import importlib
    importlib.import_module('rishi.claude'); importlib.import_module('claude_agent_sdk')
    from ramabana.core import HARNESS
    assert HARNESS['claude'][0] == 'rishi.claude'

def test_the_suite_bounds_every_test_and_every_ask():
    "A hung kernel or an ask nobody answers fails by name instead of stalling the run."
    import importlib; importlib.import_module('pytest_timeout')
    d = tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text())
    assert int(d['tool']['pytest']['ini_options']['timeout']) >= 60
    from leela.blocks.agent.ai import Interventions, _PolicyApprovals, WRITE_TOOLS
    assert Interventions(tools=WRITE_TOOLS).timeout == 2 and _PolicyApprovals(lambda tc: True).timeout == 2, 'the conftest default'
    assert Interventions(tools=WRITE_TOOLS, timeout=0.2).timeout == 0.2, 'a test that names its own keeps it'
