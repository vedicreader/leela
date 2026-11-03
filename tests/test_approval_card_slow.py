"The approval card in the agent pane: what pressing Run says and sends."
import asyncio
import pytest

pytestmark = pytest.mark.slow

RUN = r"""async () => {
  const posts = [], real = window.fetch;
  window.fetch = async (u, o) => {
    if (!String(u).startsWith('/agent/approv') && !String(u).startsWith('/agent/run-policy')) return real(u, o);
    posts.push([String(u), JSON.parse(o.body)]);
    return new Response('{"ok": true}', {headers: {'content-type': 'application/json'}});
  };
  leePane('right', true); leeRight('agent'); $('#agentlog').innerHTML = '';
  const f = (name, kind, required, dflt) => ({name, kind, required, default: dflt ?? null, multiline: false});
  const schemas = [{name: 'view_file', group: 'files', description: '', fields: [f('path', 'string', true)]},
    {name: 'run_cell', group: 'notebook', description: '', changes_state: true,
     fields: [f('path', 'string', true), f('cell_id', 'string', true), f('timeout', 'integer', false, 120)]}];
  const press = async (a, edit) => {
    showApproval({...a, schemas}); const card = approvalCards.get(a.id) || $(`.lee-approval[data-id="${a.id}"]`);
    if (edit) card.querySelector('[data-field="timeout"]').value = '5';
    updateAgentRunstrip({waiting: a.tool});
    card.querySelector('[data-ok="1"]').click();
    for (let i = 0; i < 50 && card.classList.contains('proposed'); i++) await new Promise(r => setTimeout(r, 20));
    const sent = posts.filter(p => p[0] === '/agent/approve').at(-1)[1];
    return {label: $('.lee-checkpoint-title small', card).textContent, edited: card.classList.contains('edited'),
            tool: sent.tool, args: sent.args, strip: $('.lee-agent-run-state').textContent};
  };
  return [await press({id: 'a1', tool: 'view_file', args: {path: 'a.py'}}),
          await press({id: 'a2', tool: 'run_cell', args: {cell_id: 'c1', path: 'n.ipynb'}}),
          await press({id: 'a3', tool: 'run_cell', args: {cell_id: 'c1', path: 'n.ipynb'}}, true)];
}"""

def test_run_this_tool_on_an_unchanged_card_is_not_an_edit(tmp_path):
    "The form fills in defaults and reorders keys, so a call that omitted `timeout` read as edited and was sent back rewritten."
    pytest.importorskip('playwright.async_api')
    from test_completion_caret_slow import _real_page
    async def go(pg): return await pg.evaluate(RUN)
    first, second, third = asyncio.run(_real_page(go, tmp_path))
    for got in (first, second):
        assert got['label'] == 'You approved it · running now' and not got['edited'], got
        assert got['tool'] is None and got['args'] is None, 'the original call runs as it was proposed'
        assert 'Waiting' not in got['strip'], got
    assert third['label'] == 'You edited the call · running now' and third['edited'], third
    assert third['tool'] == 'run_cell' and third['args'] == {'path': 'n.ipynb', 'cell_id': 'c1', 'timeout': 5}, third
