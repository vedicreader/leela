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
    assert rishis and all(Requirement(s).specifier.contains('0.1.45') and not Requirement(s).specifier.contains('0.1.44') for s in rishis), rishis
    assert deps['ramabana'].specifier.contains('0.2.44') and not deps['ramabana'].specifier.contains('0.2.43'), 'ContextFull, [image] in history, learned.set_enabled'
    assert deps['gheasy'].specifier.contains('0.0.13') and not deps['gheasy'].specifier.contains('0.0.12'), 'dependabot labels kept with assignees'
    assert deps['shalya'].specifier.contains('0.1.14') and not deps['shalya'].specifier.contains('0.1.13'), 'ramabana 0.2.38 needs it'
    assert deps['vishalakshi'].specifier.contains('0.1.31') and not deps['vishalakshi'].specifier.contains('0.1.30'), 'a stop inside a batch, and on a file, a PDF and a GitHub file'
    assert deps['lekhaka'].specifier.contains('0.0.4') and not deps['lekhaka'].specifier.contains('0.0.3'), 'read_book, book_md'
    assert not deps['rahasya'].specifier.contains('0.0.3') and not deps['varga'].specifier.contains('0.0.6')
    assert deps['dhrona'].specifier.contains('0.1.13') and not deps['dhrona'].specifier.contains('0.1.12'), 'a folded-in candidate keeps its id'
    assert deps['litesearch'].specifier.contains('0.1.46') and not deps['litesearch'].specifier.contains('0.1.45'), 'add_dir(stop=)'
    for n,lo in dict(dockeasy='0.0.9', pullup='0.0.8', vpseasy='0.0.23', cfeasy='0.0.5', kunda='0.0.3', kavacha='0.0.5', dhrishti='0.1.5', fossick='0.1.18', koshas='0.1.10').items(): assert not deps[n].specifier.contains(lo), n
    assert 'cli' in deps['ramabana'].extras
    extras = [Requirement(s) for g in ('desktop', 'macapp', 'windows') for s in d['project']['optional-dependencies'][g] if s.startswith('kavacha')]
    assert len(extras) == 3 and not any(r.specifier.contains('0.0.5') for r in extras), 'the window extras take the public kavacha names'

def test_the_installed_set_matches_the_pins():
    import ramabana, shalya, vishalakshi, dhrona, rishi
    assert Version(ramabana.__version__) >= Version('0.2.5') and Version(shalya.__version__) >= Version('0.1.1')
    assert Version(rishi.__version__) >= Version('0.1.45'), 'cached_model and EngineHold are public'
    from ramabana.tools import small_tool; from rishi.litert import EngineBusy  # noqa: F401  # the two seams 0.1.7 is built on
    assert Version(vishalakshi.__version__) >= Version('0.1.31') and Version(dhrona.__version__) >= Version('0.1.11')
    from ramabana.learned import learned_folder, pending, diff, accept, reject, learned_command, compact, enabled, set_enabled  # noqa: F401
    from ramabana.core import ContextFull, agent_err  # noqa: F401
    from dockeasy.core import FASTOPS_ENV; from pullup.workflows import gheasy_core  # noqa: F401

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
