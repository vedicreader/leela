import asyncio, json, sys, threading, time

import pytest
from fastcore.all import first
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.nb import nb as nbmod
from leela.blocks.runtime.kernels import GatewayKernel, GatewayService
from leela.workspace import Workspace

pytest.importorskip('jupygate')
pytest.importorskip('jupyasyncclient')

def test_gateway_kernel_executes_inspects_and_reconnects_without_local_zmq(tmp_path):
    gateway = GatewayService(port=0).start()
    async def run():
        kernel = GatewayKernel(gateway, cwd=tmp_path, name='gateway-test', inspect=True, port=18740)
        try:
            await kernel.start()
            result = await kernel.execute('gateway_value = 40 + 2; gateway_value')
            assert result.ok and result.execution_count == 1
            assert result.outputs[-1]['data']['text/plain'] == '42'
            assert 'gateway_value' in await kernel.names()
            completion = await kernel.complete('gateway_val', len('gateway_val'))
            assert 'gateway_value' in completion['matches']
            assert kernel.base and kernel.token
        finally:
            await kernel.shutdown()
            gateway.stop()
    asyncio.run(run())

def _run_gateway(tmp_path, srcs, during):
    "Run each of `srcs` through `/nb/run/stream` on a gateway kernel; `during(client, kernel)` acts while the last one runs."
    cells = [{'cell_type': 'code', 'id': f'c{i}', 'source': s, 'metadata': {}, 'outputs': [], 'execution_count': None} for i, s in enumerate(srcs)]
    p = tmp_path/'g.ipynb'
    p.write_text(json.dumps({'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    gw = GatewayService(port=0).start()
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable, transport='gateway', gateway=gw); ws.open(p)
    events = []
    try:
        with TestClient(ide_app(ws)) as client:
            path = client.get('/tab/state').json()['path']
            def stream(i, out):
                with client.stream('POST', '/nb/run/stream', json={'i': i, 'id': f'c{i}', 'source': srcs[i], 'path': path}) as r:
                    for l in r.iter_lines():
                        if l.startswith('event:'): ev = l[7:]
                        elif l.startswith('data: '): out.append((ev, json.loads(l[6:]), time.monotonic()))
            for i in range(len(srcs) - 1): stream(i, [])
            t = threading.Thread(target=stream, args=(len(srcs) - 1, events), daemon=True)
            began = time.monotonic(); t.start()
            during(client, client.portal.call(ws.runtime))
            t.join(30)
    finally:
        ws.shutdown_now(); gw.stop()
    return first(d for e, d, _ in events if e == 'done'), events, began

def test_a_reply_lost_with_a_dropped_gateway_socket_still_settles_the_cell(tmp_path, monkeypatch):
    """jupygate drops the frames in flight when its websocket dies, and the run waited forever on an `execute_reply` the idle kernel had already sent."""
    monkeypatch.setattr(nbmod, 'QUIET', 1)
    def drop(client, k):
        time.sleep(1); client.portal.call(lambda: k.kc._ws.transport.pause_reading())
        time.sleep(2.5); client.portal.call(lambda: k.kc._ws.transport.abort())
    done, events, began = _run_gateway(tmp_path, ['x = 1', 'import time; time.sleep(2); y = 2'], drop)
    took = next((at for e, _, at in events if e == 'done'), float('inf')) - began
    assert took < 15, f'done came {took:.0f}s after the run began: {events}'
    assert done['ok'] and done['lost'] and done['cell']['execution_count'] is not None, done

def test_the_idle_probe_does_not_settle_a_long_silent_cell_early(tmp_path, monkeypatch):
    """A shell `kernel_info` waits behind a running execute, so a busy kernel's probe goes unanswered and the cell keeps running."""
    monkeypatch.setattr(nbmod, 'QUIET', .5)
    answers, real = [], nbmod.shell_free
    async def spy(k):
        answers.append(r := await real(k))
        return r
    monkeypatch.setattr(nbmod, 'shell_free', spy)
    done, events, began = _run_gateway(tmp_path, ['x = 1', 'import time; time.sleep(4); y = 2'], lambda client, k: None)
    assert done, f'no done event: {events}'
    took = first(at for e, _, at in events if e == 'done') - began
    assert done['ok'] and not done.get('lost') and done['cell']['execution_count'] is not None, done
    assert took >= 4 and False in answers, (took, answers)
