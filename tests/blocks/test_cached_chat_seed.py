"""CachedChat oneshot seeding stays available to feature blocks that need a model reply."""

from __future__ import annotations


def test_oneshot_seed_replays_without_a_live_model(tmp_path):
    from tests.blocks.conftest import cached_chat, seed_oneshot

    seed_oneshot(tmp_path, 'where is approval handled?', 'in the web HITL path')
    chat = cached_chat(tmp_path)
    assert chat.oneshot('where is approval handled?') == 'in the web HITL path'
