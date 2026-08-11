"""Servers, tunnels and DNS: the parts Leela adds, not the parts vpseasy and cfeasy do.

Reaching Hetzner or Cloudflare is those libraries' job and is tested there. What is here is
what happens around the call -- where the token comes from, that it does not outlive the
call, and that one half being unreachable does not hide the other.
"""

import os

import pytest

from leela.blocks.stack.infra import Infra, InfraError


class FakeStore:
    def __init__(self, **values): self.values = values
    def get(self, key, secret=True): return self.values.get(key, '')


def test_status_names_each_missing_piece():
    st = Infra(FakeStore()).status()
    assert set(st) == {'vpseasy', 'cfeasy', 'hcloud_token', 'cf_token', 'keys'}
    assert not st['hcloud_token'] and not st['cf_token']
    assert Infra(FakeStore(HCLOUD_TOKEN='x')).status()['hcloud_token']
    assert st['keys'] == ['HCLOUD_TOKEN', 'CLOUDFLARE_API_TOKEN'], 'the panel can say which to set'


def test_a_missing_token_is_refused_before_a_provider_is_reached():
    "The message names the key and where to set it; 'unauthorized' from an SDK does not."
    infra = Infra(FakeStore())
    with pytest.raises(InfraError, match='HCLOUD_TOKEN is not set'):
        infra.servers()
    with pytest.raises(InfraError, match='CLOUDFLARE_API_TOKEN is not set'):
        infra.tunnels()


def test_the_token_does_not_outlive_the_call(monkeypatch):
    """It is put in the environment because vpseasy reads it from there, and taken out again.

    A credential that stays in `os.environ` for the life of the process is a credential in
    every subprocess and every crash dump after it.
    """
    monkeypatch.delenv('HCLOUD_TOKEN', raising=False)
    infra = Infra(FakeStore(HCLOUD_TOKEN='secret-value'))
    seen = {}

    class FakeHetzner:
        def __init__(self): seen['env'] = os.environ.get('HCLOUD_TOKEN')
        def servers(self): return [{'name': 'kalpa', 'ip': '1.2.3.4', 'status': 'running'}]

    import leela.blocks.stack.infra as mod
    monkeypatch.setattr(mod.Infra, '_hetzner', lambda self: FakeHetzner())
    assert infra.servers()[0]['name'] == 'kalpa'
    assert os.environ.get('HCLOUD_TOKEN') is None


def test_one_provider_being_down_does_not_hide_the_other(monkeypatch):
    infra = Infra(FakeStore(HCLOUD_TOKEN='x'))
    monkeypatch.setattr(Infra, 'servers', lambda self: [{'name': 'kalpa'}])
    monkeypatch.setattr(Infra, 'tunnels', lambda self: (_ for _ in ()).throw(InfraError('no CF token')))
    monkeypatch.setattr(Infra, 'zones', lambda self: (_ for _ in ()).throw(InfraError('no CF token')))
    out = infra.overview()
    assert out['servers']['rows'] == [{'name': 'kalpa'}] and not out['servers']['error']
    assert out['tunnels']['error'] == 'no CF token' and out['tunnels']['rows'] == []


def test_deleting_refuses_a_server_this_token_cannot_see(monkeypatch):
    "A typo must not reach the provider's delete call at all."
    infra = Infra(FakeStore(HCLOUD_TOKEN='x'))
    monkeypatch.setattr(Infra, 'servers', lambda self: [{'name': 'kalpa'}])
    with pytest.raises(InfraError, match='no server called ghost'):
        infra.delete_server('ghost')
    with pytest.raises(InfraError, match='name the server'):
        infra.delete_server('')


def test_records_mark_the_ones_that_belong_to_a_tunnel(monkeypatch):
    "The answer to 'why is this host serving something else' is usually in this column."
    infra = Infra(FakeStore(CLOUDFLARE_API_TOKEN='x'))

    class FakeCF:
        def zone_id(self, name): return 'z' * 32
        def dns_records(self, zid):
            return [{'id': '1', 'type': 'CNAME', 'name': 'app.example.com',
                     'content': 'abc.cfargotunnel.com', 'proxied': True, 'ttl': 1},
                    {'id': '2', 'type': 'A', 'name': 'old.example.com',
                     'content': '1.2.3.4', 'proxied': False, 'ttl': 300}]

    monkeypatch.setattr(Infra, '_cf', lambda self: FakeCF())
    rows = {r['name']: r for r in infra.records('example.com')}
    assert rows['app.example.com']['tunnel'] and not rows['old.example.com']['tunnel']
    with pytest.raises(InfraError, match='choose a zone'):
        infra.records('')
