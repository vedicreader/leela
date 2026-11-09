import pytest

from leela.blocks.learn import surfaces


def test_manifest_gives_a_graph_page_d3_and_graph_js_with_graph_rerun():
    s = surfaces.surface('/library/graph?subject=x')
    assert [u.split('?')[0] for u in s['js']] == ['/learn/abh-asset/voice.js', '/learn/abh-asset/d3.min.js', '/learn/abh-asset/graph.js']
    assert [u.split('?')[0] for u in s['rerun']] == ['/learn/abh-asset/graph.js']
    assert surfaces.surface('/graph')['js'] == s['js']


def test_manifest_gives_nothing_to_a_page_it_does_not_name():
    s = surfaces.surface('/you')
    assert s['rerun'] == [] and s['css'] == [] and [u.split('?')[0] for u in s['js']] == ['/learn/abh-asset/voice.js'] and 'keys_float.js' not in s['known'] and 'graph.js' in s['known'] and surfaces.surface('') == surfaces.surface('/')


@pytest.mark.parametrize('name', ['../core.js', 'graph.js/../../x', 'base.css', 'nope.js', '..', 'abh.css'])
def test_assets_are_whitelisted_by_the_manifest_only(name):
    assert surfaces.asset(name) is None


def test_every_manifest_name_resolves_to_a_file():
    assert surfaces.known() and all(surfaces.asset(n) for n in surfaces.known())
