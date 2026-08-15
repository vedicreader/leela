# Plugging in vishalakshi and ramabana

What Leela expects, how to select an alternate, and how to find out whether yours fits
before wiring it into anything.

## The three seams

| port | Leela uses it for | satisfied today by | intended alternate |
|---|---|---|---|
| `MemoryPort` | pages, research briefs, agent notes and state | `blocks.memory.memory.Memory` (litesearch) | `vishalakshi.Vault` |
| `SearchPort` | code search: literal, semantic, call graph | `blocks.search.search.Search` (Kosha + ripgrep) | vishalakshi's code leg |
| `RuntimePort` | one model session: history, streaming, tools | `ramabana.runtime.Backend` | any other harness |

The definitions live in [`leela/core/ports.py`](../leela/core/ports.py). They are
`Protocol`s, taken from what Leela's routes call rather than from what the current classes
happen to offer. Nothing needs to inherit from them.

## Selecting one

A provider is a factory registered against a port name and chosen by environment variable:

```sh
LEELA_MEMORY=vishalakshi leela .
LEELA_SEARCH=vishalakshi leela .
LEELA_RUNTIME=ramabana    leela .
```

```python
from leela.core import provider

@provider('memory', 'vishalakshi')
def _vault(kosha=None, path=None, **kw):
    from vishalakshi import Vault              # imported only when selected
    return VaultAdapter(Vault(path))
```

Register at import of your adapter module. `Workspace.__init__` calls `build('memory', …)`,
so a selected provider is what the workspace ends up holding. There is no separate wiring
step.

Three properties are deliberate.

Selection is late. Factories import inside themselves, so naming a provider costs nothing
until it is built, and `leela.core` stays importable without a memory stack behind it.

Failure is loud. An unknown, uninstalled or broken provider raises `ProviderError`, and
never falls back to the built-in. A workspace that quietly ran on built-in memory after
`LEELA_MEMORY=vishalakshi` failed would make the comparison meaningless, because you could
not tell which one answered.

`leela` is a provider too. The default registers like any other, so no privileged path
exists that only the built-in takes.

## Checking conformance before you wire it

`isinstance(x, MemoryPort)` answers only whether the names are present. It does not compare
signatures, because `runtime_checkable` Protocols never do. An implementation whose `search`
takes `(q, n)` passes `isinstance` and fails on the first query Leela sends it.

So check properly:

```sh
python -m leela.conformance memory vishalakshi
```

```python
from leela import conformance
print(conformance.report('memory', my_vault))   # conformance.check returns the problems
```

It reports three classes of problem:

```
memory <- a half-built alternate: 3 problem(s)
  - missing: agent_notes
  - search: leela passes ['query', 'limit'] which this does not accept
  - note: port declares an attribute, found a callable
```

1. Presence: every member the port names exists.
2. Kind: an attribute is not a method, and a method is not an attribute. `Backend.ready` is
   a property, and a runtime that made it a method would break every call site.
3. Signature: every keyword Leela passes is accepted by that name.

The keyword lists live in `CALLS` in [`leela/conformance.py`](../leela/conformance.py) and
come from the real call sites. An adapter that forwards `**kwargs` satisfies the signature
check by construction, which is usually the easiest way to write one.

Checking a class works too. Constructor parameters count as present, so `Backend` verifies
without starting a model.

## Writing an adapter

An adapter is the expected shape, rather than making vishalakshi implement Leela's names.
`MemoryPort` is fifteen methods of Leela vocabulary and `Vault` has its own. Translating in
an adapter leaves both projects free to name things for their own reasons.

```python
class VaultAdapter:
    "vishalakshi.Vault behind MemoryPort."
    def __init__(self, vault):
        self.v = vault
        self.note = vault.enc.note              # a value, not a call
    def search(self, query, limit=8, **kw): return self.v.find(query, n=limit)
    def toc(self, doc=None, depth=3, **kw):    return self.v.outline(doc, depth)
```

Two things the ports say are easy to miss. `note` on memory and search, and `backend` on
search, are string attributes rather than methods. Every reply embeds them, so an empty
result still reports which backend produced it. On `RuntimePort`, `ready`, `busy` and `hist`
are properties rather than methods. Conformance checks both, because both were wrong in the
first draft of the ports.

## What `RuntimePort` leaves out

Compaction (`Compactor`), token accounting (`Usage`) and model resolution (`ModelSpec`,
`Routing`) are not in the port. They are Leela's policy about how to use a runtime, not
something a runtime must provide.

A backend that brought its own compaction would substitute policy for mechanism, and the two
runtimes would stop being comparable. A difference in output could then come from the model
or from a different context-management strategy, with no way to tell which. Keeping the port
at mechanism is what makes an A/B meaningful.

`ramabana.runtime.Backend` is the specification, and `leela.agent.runtime` is an alias for
it. `tests/test_core.py` asserts that it conforms, so the port cannot drift away from the
thing it was taken from.

## The other direction: what `WorkspaceHost` owes the harness

`Backend` is the port Leela consumes. `ramabana.tools.Host` is the port Leela *implements* — the
application under the agent — and it grows as the harness does. An unimplemented method is not an
error; it is a tool group that quietly does not appear. Three rules, each learned the hard way.

**Declare capabilities rather than being probed.** `tools_for` asks `Host.capabilities`, and
probes with a live call only where the host does not say. The probe is the first thing to touch a
host, so `memory_tree('')` opened the vault — an embedding model — on the first `Agent.tools`
access. `WorkspaceHost.capabilities` answers for everything a workspace has by construction, and
leaves `session` to the probe: it is the one that depends on whether a kernel is live.

**`api` is never probed.** An unloaded specification is not a missing capability, so the group is
gated on the declaration alone: implement `api_load`, `api_ops` and `api_call`, say nothing, and
get no API tools and no error. Leela borrows the three from `ramabana.spec.SpecHost`, which is a
`LocalHost` and so cannot be inherited — they are about specifications, not about a sandbox.

**The sandbox has two halves.** `check(path, reading=True)` is asked for a path a tool will only
read. Confining writes stops the agent damaging something nobody opened; confining reads stops it
answering from a sibling checkout or a library in the venv. `agent_read_outside` opens the read
half alone, refuses the credential paths in `tools.DENY` regardless, and leaves enumeration
confined — `walk` never leaves the open folders, so a read outside is a path the model was told,
never one it found by looking.

`Agent.lend_model` is the same obligation pointing the other way: a host that builds its own chats
declares `mk_chat = None` to opt in, and the agent fills it, so the vault answers on the model
being talked to instead of loading a second engine from `$VISHALAKSHI_MODEL`.

## Where memory and search stay separate

They are two ports rather than one retrieval port, and that is not an accident of history.
Source code is an AST-shaped corpus. Prose is a document tree.
[`leela/blocks/memory/memory.py`](../leela/blocks/memory/memory.py) says so at the top, and
the two share an embedder while deliberately not sharing tables.

vishalakshi may well satisfy both. It should still do so as two adapters. One of them will
eventually need different chunking, or a different index. That is the day a fused port
becomes expensive to unpick, and it tends to arrive right after the swap.

## Checklist

1. Write the adapter and forward `**kwargs`.
2. Run `python -m leela.conformance <port> <name>` until it prints `OK`.
3. Register the factory with `@provider(port, name)` and lazy-import inside it.
4. Run Leela with `LEELA_<PORT>=<name>` and compare against the default.
