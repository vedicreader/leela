"The gateway guard. No `importorskip`: a partial install is what these cover."

import pytest

from leela.blocks.runtime.kernels import GatewayService, check_gateway_deps

def _installed(monkeypatch):
    "Every import in the guard succeeds, so the version check is what the test is left looking at."
    import importlib
    monkeypatch.setattr(importlib, 'import_module', lambda name: None)


def test_a_capped_out_version_is_named_rather_than_left_to_execute_nothing(monkeypatch):
    "jupyasyncclient 0.2.8 makes the gateway `async for` over a coroutine, so a kernel there runs nothing."
    import importlib.metadata
    _installed(monkeypatch)
    monkeypatch.setattr(importlib.metadata, 'version',
        lambda name: '0.2.8' if name == 'jupyasyncclient' else '1.0')
    with pytest.raises(RuntimeError): check_gateway_deps()


def test_a_port_already_held_falls_back_instead_of_stalling_and_raising_oserror(monkeypatch):
    "jupygate gives up the listen with a `TimeoutError`, which is an `OSError`, past `serve_ide`'s except."
    jupygate = pytest.importorskip('jupygate.core')
    def busy(app, **kw): raise TimeoutError('uvicorn did not start')
    monkeypatch.setattr(jupygate, 'serve', busy)
    with pytest.raises(RuntimeError) as e: GatewayService(port=8787).start()
    assert isinstance(e.value.__cause__, TimeoutError)
