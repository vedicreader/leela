

def test_the_browser_helpers_leave_the_spec_pager_alone():
    """A browser `_page` shadowed `SpecHost._page`, and every API spec load answered 'no page is open'."""
    from leela.blocks.agent.ai import WorkspaceHost
    from leela.agent.spec import SpecHost
    assert WorkspaceHost._page is SpecHost._page
