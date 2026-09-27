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
    assert deps['ramabana'].specifier.contains('0.2.0') and not deps['ramabana'].specifier.contains('0.1.42')
    assert deps['shalya'].specifier.contains('0.1.0') and not deps['shalya'].specifier.contains('0.0.11')
    assert deps['vishalakshi'].specifier.contains('0.1.17') and not deps['vishalakshi'].specifier.contains('0.1.16')
    assert deps['dhrona'].specifier.contains('0.1.4')
    assert 'cli' in deps['ramabana'].extras

def test_the_installed_set_matches_the_pins():
    import ramabana, shalya, vishalakshi, dhrona
    assert Version(ramabana.__version__) >= Version('0.2.0') and Version(shalya.__version__) >= Version('0.1.0')
    assert Version(vishalakshi.__version__) >= Version('0.1.17') and Version(dhrona.__version__) >= Version('0.1.4')

def test_the_claude_code_runtime_chain_imports():
    "`rishi.claude` → `claude_agent_sdk`; the desktop bundle test (`test_packaging.py:408`) once died on this."
    import importlib
    importlib.import_module('rishi.claude'); importlib.import_module('claude_agent_sdk')
    from ramabana.core import HARNESS
    assert HARNESS['claude'][0] == 'rishi.claude'
