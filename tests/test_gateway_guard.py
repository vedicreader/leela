"The gateway guard. No `importorskip`: a partial install is what these cover."
import asyncio, sys

import pytest

from leela.blocks.runtime.kernels import GatewayKernel, GatewayService, check_gateway_deps

def _missing(monkeypatch, name): monkeypatch.setitem(sys.modules, name, None)
def _installed(monkeypatch):
    "Every import in the guard succeeds, so the version check is what the test is left looking at."
    import importlib
    monkeypatch.setattr(importlib, 'import_module', lambda name: None)

def test_a_missing_jupyasyncclient_names_itself_instead_of_raising_importerror(monkeypatch):
    _missing(monkeypatch, 'jupyasyncclient')
    with pytest.raises(RuntimeError) as e: check_gateway_deps()
    assert 'jupyasyncclient' in str(e.value)

def test_the_service_refuses_at_startup_so_serve_ide_can_fall_back_to_the_direct_transport(monkeypatch):
    "`serve_ide` catches `(ImportError, RuntimeError)` around this call and only around this call."
    _missing(monkeypatch, 'jupyasyncclient')
    with pytest.raises(RuntimeError) as e: GatewayService(port=0).start()
    assert 'jupyasyncclient' in str(e.value)

def test_a_kernel_start_reports_the_same_way_as_the_service(monkeypatch):
    _missing(monkeypatch, 'jupyasyncclient')
    k = GatewayKernel.__new__(GatewayKernel)
    with pytest.raises(RuntimeError) as e: asyncio.run(k.start())
    assert 'jupyasyncclient' in str(e.value)

def test_a_capped_out_version_is_named_rather_than_left_to_execute_nothing(monkeypatch):
    "jupyasyncclient 0.2.8 makes the gateway `async for` over a coroutine, so a kernel there runs nothing."
    import importlib.metadata
    _installed(monkeypatch)
    monkeypatch.setattr(importlib.metadata, 'version',
        lambda name: '0.2.8' if name == 'jupyasyncclient' else '1.0')
    with pytest.raises(RuntimeError) as e: check_gateway_deps()
    assert '0.2.8' in str(e.value) and '!=0.2.8' in str(e.value)

def test_an_unreported_version_is_not_a_reason_to_refuse(monkeypatch):
    import importlib.metadata
    _installed(monkeypatch)
    def gone(name): raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata, 'version', gone)
    check_gateway_deps()

def test_a_port_already_held_falls_back_instead_of_stalling_and_raising_oserror(monkeypatch):
    "jupygate gives up the listen with a `TimeoutError`, which is an `OSError`, past `serve_ide`'s except."
    jupygate = pytest.importorskip('jupygate.core')
    def busy(app, **kw): raise TimeoutError('uvicorn did not start')
    monkeypatch.setattr(jupygate, 'serve', busy)
    with pytest.raises(RuntimeError) as e: GatewayService(port=8787).start()
    assert '8787' in str(e.value) and 'another leela' in str(e.value)
    assert isinstance(e.value.__cause__, TimeoutError)
