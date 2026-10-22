def test_an_api_spec_loaded_on_the_workspace_host_pages_its_operations(tmp_path):
    """A browser `_page` on the host shadowed `SpecHost._page`, and every API spec load answered 'no page is open'."""
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.workspace import Workspace
    spec = {'openapi': '3.0.0', 'info': {'title': 'T', 'version': '1'}, 'servers': [{'url': 'http://x'}],
            'paths': {f'/p{i}': {'get': {'operationId': f'op{i}', 'summary': 's'}} for i in range(5)}}
    h = WorkspaceHost(Workspace(roots=[tmp_path]))
    assert h.api_load(spec, name='t')['operations'] == 5
    assert [o['name'] for o in h.api_ops(name='t', limit=2, offset=1)] == ['op1', 'op2']