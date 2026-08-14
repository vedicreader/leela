"""Provider selection and port conformance -- the seam vishalakshi and ramabana plug into."""

import pytest

from leela import conformance
from leela.core import ports as providers
from leela.core.ports import ProviderError, build, providers_for, selected


@pytest.fixture(autouse=True)
def clean_registry():
    "Each test gets the real registry back, so an installed fake cannot leak."
    import copy
    saved = copy.deepcopy(providers._REGISTRY)
    yield
    providers._REGISTRY.clear(); providers._REGISTRY.update(saved)


# -- selection ---------------------------------------------------------------

def test_the_builtin_is_registered_like_any_other_provider():
    "No privileged path for the default means no untested branch for the alternates."
    for port in ('memory', 'search', 'runtime'):
        assert 'leela' in providers_for(port)


def test_selection_prefers_an_explicit_override_then_the_environment(monkeypatch):
    monkeypatch.delenv('LEELA_MEMORY', raising=False)
    assert selected('memory') == 'leela'
    monkeypatch.setenv('LEELA_MEMORY', 'vishalakshi')
    assert selected('memory') == 'vishalakshi'
    assert selected('memory', 'ramabana') == 'ramabana', 'an explicit override wins'


def test_an_unknown_provider_raises_and_names_what_is_available(monkeypatch):
    monkeypatch.setenv('LEELA_MEMORY', 'nope')
    with pytest.raises(ProviderError, match="unknown memory provider 'nope'.*available: leela"):
        build('memory')


def test_a_provider_whose_package_is_missing_says_so(monkeypatch):
    "The failure a user actually hits before pip-installing the alternate."
    def missing(**kw): raise ImportError("No module named 'vishalakshi'")
    providers.register('memory', 'vishalakshi', missing)
    monkeypatch.setenv('LEELA_MEMORY', 'vishalakshi')
    with pytest.raises(ProviderError, match='not installed'): build('memory')


def test_a_broken_provider_never_falls_back_to_the_builtin(monkeypatch):
    """Silently running on the default would make an A/B comparison meaningless -- you
    would not know which implementation answered, which is the entire question."""
    providers.register('memory', 'boom', lambda **kw: 1/0)
    monkeypatch.setenv('LEELA_MEMORY', 'boom')
    with pytest.raises(ProviderError, match='failed to start'): build('memory')


def test_a_registered_alternate_is_what_the_workspace_builds(monkeypatch):
    "End to end: the switch really changes what a Workspace ends up holding."
    from leela.workspace import Workspace
    sentinel = object()
    providers.register('memory', 'fake', lambda **kw: sentinel)
    monkeypatch.setenv('LEELA_MEMORY', 'fake')
    assert Workspace(roots=[]).memory is sentinel


def test_the_default_workspace_still_builds_the_builtin(monkeypatch):
    from leela.blocks.memory.memory import Memory
    from leela.workspace import Workspace
    monkeypatch.delenv('LEELA_MEMORY', raising=False)
    assert isinstance(Workspace(roots=[]).memory, Memory)


# -- conformance -------------------------------------------------------------

def test_the_shipped_implementations_conform_to_their_ports():
    from leela.agent.runtime import Backend
    from leela.workspace import Workspace
    ws = Workspace(roots=[])
    assert conformance.check('memory', ws.memory) == []
    assert conformance.check('search', ws.search) == []
    assert conformance.check('runtime', Backend) == []


def _stub(port, **overrides):
    """A class with every member the port names, as real attributes.

    Real ones because `isinstance` against a Protocol uses `inspect.getattr_static` on
    3.12+, which deliberately does not invoke `__getattr__` -- a fake built out of dynamic
    attribute lookup would not satisfy the very check this is contrasting against.
    """
    proto = conformance.PORTS[port]
    ns = {}
    for name in proto.__protocol_attrs__:
        ns[name] = (lambda self, *a, **kw: None) if callable(getattr(proto, name, None)) else ''
    ns.update(overrides)
    return type(f'Stub{port.title()}', (), ns)


def test_conformance_catches_a_signature_that_isinstance_would_pass():
    """The check that earns the module.

    `MemoryPort` is runtime_checkable, and runtime_checkable Protocols do not compare
    signatures at all -- so an implementation whose `search` takes `(q, n)` passes
    `isinstance` and then fails on the first query leela sends it.
    """
    from leela.core import MemoryPort

    obj = _stub('memory', search=lambda self, q, n=8: [])()
    assert isinstance(obj, MemoryPort), 'isinstance is satisfied, which is the problem'
    problems = conformance.check('memory', obj)
    assert any("search: leela passes ['query', 'limit']" in p for p in problems)


def test_conformance_reports_a_member_of_the_wrong_kind():
    "A runtime that made `ready` a method would break every call site."
    obj = _stub('runtime', ready=lambda self: True)()
    problems = conformance.check('runtime', obj)
    assert any('ready: port declares an attribute' in p for p in problems)


def test_conformance_reports_a_method_supplied_as_a_value():
    obj = _stub('memory', search='not callable')()
    assert any('search: port declares a method' in p for p in conformance.check('memory', obj))


def test_conformance_accepts_kwargs_as_accepting_everything():
    "An adapter that forwards **kw is conforming; requiring named params would forbid that."
    assert conformance.check('memory', _stub('memory')()) == []


def test_a_class_is_checkable_without_constructing_it():
    "Checking `Backend` must not require starting a model, so init params count as present."
    from leela.agent.runtime import Backend
    assert 'missing: spec' not in conformance.check('runtime', Backend)


def test_report_is_readable_both_ways():
    from leela.workspace import Workspace
    ok = conformance.report('memory', Workspace(roots=[]).memory)
    assert ok.startswith('memory <- Memory: OK')
    bad = conformance.report('memory', object(), label='nothing')
    assert 'problem(s)' in bad and '  - missing:' in bad


def test_an_unknown_port_is_rejected():
    with pytest.raises(ValueError, match='unknown port'): conformance.check('telepathy', object())


# -- the command line --------------------------------------------------------

@pytest.mark.parametrize('port', ['memory', 'search', 'runtime'])
def test_every_port_can_be_checked_from_the_command_line(port, capsys):
    """`python -m leela.conformance <port>` is the first thing to run against an
    alternate, so each port has to be buildable without a model or an index."""
    assert conformance._main([port]) == 0
    assert 'OK' in capsys.readouterr().out


def test_the_cli_reports_a_bad_provider_without_a_traceback(capsys):
    assert conformance._main(['memory', 'nosuch']) == 2
    out = capsys.readouterr().out
    assert 'unknown memory provider' in out and 'Traceback' not in out


def test_the_cli_rejects_an_unknown_port_with_usage(capsys):
    assert conformance._main(['telepathy']) == 2
    assert 'usage:' in capsys.readouterr().out


def test_the_cli_exits_nonzero_when_an_implementation_does_not_conform(capsys, monkeypatch):
    providers.register('memory', 'broken', lambda **kw: _stub('memory', search='nope')())
    monkeypatch.setenv('LEELA_MEMORY', 'broken')
    assert conformance._main(['memory']) == 1
    assert 'port declares a method' in capsys.readouterr().out
