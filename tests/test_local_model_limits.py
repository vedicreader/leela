"""Real end-to-end Rishi/LiteRT regression for the dialog prompt cell.

The model is multi-gigabyte, so this runs when it is already in Hugging Face's cache (or
when LEELA_RUN_RISHI_INTEGRATION=1 explicitly permits a download). Nothing here replaces
Rishi, Chat, Engine, Conversation, the tokenizer, Leela's tools, or prompt composition.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from leela.agent.core import LOCAL, local_ctx
from leela.nb import Notebook
from leela.workspace import Workspace

MODEL_NAME = 'gemma-e4b'
MODEL_ID = LOCAL[MODEL_NAME]
REPO = Path(__file__).resolve().parents[1]
DIALOG = REPO/'tests'/'fixtures'/'dialog.ipynb'
PROMPT_CELL = 2


def _model_available():
    from rishi.litert import _cached_model
    return bool(_cached_model(MODEL_ID))


@pytest.fixture(scope='module')
def dialog_agent():
    if not _model_available() and os.environ.get('LEELA_RUN_RISHI_INTEGRATION') != '1':
        pytest.skip(f'{MODEL_NAME} LiteRT bundle is not cached; set LEELA_RUN_RISHI_INTEGRATION=1 to download it')

    # `auto` is only to keep a tool call from waiting for a human inside pytest. It does
    # not alter the model, prompt, tools, notebook context, or streaming path.
    # Match the UI fixture setup exactly: the opened folder is tests/fixtures, not the
    # repository root. That root is part of the system prompt and changes its token count.
    ws = Workspace(roots=[str(DIALOG.parent)], inline_model=MODEL_NAME, approvals='auto')
    ws.open(DIALOG)
    nb = Notebook.load(DIALOG)

    async def prepare():
        kernel = await ws.kernel()
        result = await nb.run(1, kernel)
        assert not result.has_error
    asyncio.run(prepare())

    try: yield ws, nb
    finally:
        ws.ai.close()
        ws.inline_ai.close()
        asyncio.run(ws.pool.close_all())


def test_real_dialog_prompt_uses_a_16k_litert_engine(dialog_agent):
    ws, nb = dialog_agent
    backend = ws.inline_ai.backend
    assert backend.start() is not None
    assert local_ctx(MODEL_NAME) == 16384
    assert backend.chat.ctx_limit == 16384
    assert backend.chat.engine.max_num_tokens == 16384
    # Constrained decoding must be *asked for*, in whichever spelling the installed litert
    # accepts. Pinning the old kwarg name here is what let a litert release rename it and
    # turn every local model with tools into "model unavailable".
    conv_kw = backend.chat._conv_kw
    cfg = conv_kw.get('constrained_decoding_config')
    assert conv_kw.get('enable_constrained_decoding') is True or getattr(cfg, 'enable', False)
    assert {'run_python', 'inspect_python', 'list_vars'} <= {t.__name__ for t in backend.tools}

    cell = nb[PROMPT_CELL]
    message = ws.inline_ai.compose(
        cell.source,
        context=nb.context(PROMPT_CELL, since=nb.prompt_start(PROMPT_CELL)),
        context_path=nb.path,
    )
    # The actual Leela briefing and every real tool schema, plus the exact notebook context
    # and prompt, rendered by the real Gemma template. The band is what a 16k window can
    # afford to spend *before* the turn starts: everything above this is tool results.
    #
    # It came down from ~6,800 while four tools were added, because the exhash command
    # grammar stopped being pasted into every turn -- `replace_text` needs no grammar, so
    # the skill went back behind `read_skill`. That is the trade this number exists to
    # protect: schemas for capabilities the model uses, not prose for one tool.
    assert 3600 <= backend.pending_tokens(message) <= 5200
    assert backend.fits(message)


def test_real_dialog_prompt_cell_completes_end_to_end(dialog_agent):
    ws, nb = dialog_agent
    chunks = list(ws.ask_cell_stream(nb, PROMPT_CELL))

    assert chunks
    assert nb[PROMPT_CELL].reply.strip()
    assert 'the assistant failed' not in nb[PROMPT_CELL].reply
    assert 'produced no event' not in nb[PROMPT_CELL].reply
    assert not ws.inline_ai.problems
    rows = ws.kernel_peek().api_sync('/api/rows', {'profile': 'minimal', 'sort': 'name'})
    names = {v.get('name') for g in (rows or {}).get('groups', []) for v in g.get('nodes', [])}
    assert 'df_norm' in names, 'the imperative prompt must execute and bind its requested result'
