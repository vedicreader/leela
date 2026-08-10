import asyncio

import pytest

from leela.blocks.runtime.kernels import GatewayKernel, GatewayService, KernelPool


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


def test_kernel_pool_selects_gateway_transport_without_changing_workspace_callers():
    gateway = GatewayService(port=0)
    pool = KernelPool(transport='gateway', gateway=gateway)
    assert pool.transport == 'gateway' and pool.gateway is gateway
