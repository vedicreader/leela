"The pins leela's tool set is built against, and the Claude Code runtime chain they carry."
import tomllib
from pathlib import Path
from packaging.requirements import Requirement
from packaging.version import Version

def _deps():
    d = tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text())
    return {Requirement(s).name: Requirement(s) for s in d['project']['dependencies']}

def test_the_tool_simplification_releases_are_the_floor():
    deps = _deps()
    d = tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text())
    rishis = [s for g in (d['project']['optional-dependencies']['local'], d['dependency-groups']['dev']) for s in g if isinstance(s, str) and s.startswith('rishi')]
    assert rishis and all(Requirement(s).specifier.contains('0.1.39') and not Requirement(s).specifier.contains('0.1.38') for s in rishis), rishis
    assert deps['ramabana'].specifier.contains('0.2.3') and not deps['ramabana'].specifier.contains('0.2.2')
    assert deps['shalya'].specifier.contains('0.1.0') and not deps['shalya'].specifier.contains('0.0.11')
    assert deps['vishalakshi'].specifier.contains('0.1.17') and not deps['vishalakshi'].specifier.contains('0.1.16')
    assert deps['dhrona'].specifier.contains('0.1.4')
    assert 'cli' in deps['ramabana'].extras

def test_the_installed_set_matches_the_pins():
    import ramabana, shalya, vishalakshi, dhrona, rishi
    assert Version(ramabana.__version__) >= Version('0.2.3') and Version(shalya.__version__) >= Version('0.1.0')
    assert Version(rishi.__version__) >= Version('0.1.39'), 'the engine lock and `EngineBusy`'
    from ramabana.tools import small_tool; from rishi.litert import EngineBusy  # noqa: F401  # the two seams 0.1.7 is built on
    assert Version(vishalakshi.__version__) >= Version('0.1.17') and Version(dhrona.__version__) >= Version('0.1.4')

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
