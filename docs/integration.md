# Plugging in vishalakshi and ramabana

What Leela expects, how to select an alternate, and how to find out whether yours fits
before wiring it into anything.

## The three seams

| port | Leela uses it for | satisfied today by | intended alternate |
|---|---|---|---|
| `MemoryPort` | pages, research briefs, agent notes and state | `leela.memory.Memory` (litesearch) | `vishalakshi.Vault` |
| `SearchPort` | code search: literal, semantic, call graph | `leela.search.Search` (Kosha + ripgrep) | vishalakshi's code leg |
| `RuntimePort` | one model session: history, streaming, tools | `leela.agent.runtime.Backend` | ramabana |

Definitions are in [`leela/core/ports.py`](../leela/core/ports.py). They are `Protocol`s,
extracted from what Leela's routes actually call — not from what the current classes
happen to offer. Nothing needs to inherit from them.

## Selecting one

A provider is a zero-argument-ish factory registered against a port name, chosen by
environment variable:

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

Register at import of your adapter module. `Workspace.__init__` calls
`build('memory', …)`, so a selected provider is what the workspace ends up holding —
there is no separate wiring step.

Three properties are deliberate:

- **Selection is late.** Factories import inside themselves, so naming a provider costs
  nothing until it is built, and `leela.core` stays importable without pulling in a memory
  stack.
- **Failure is loud.** An unknown, uninstalled or broken provider raises `ProviderError`.
  It never falls back to the built-in — a workspace that quietly ran on `leela.memory`
  after `LEELA_MEMORY=vishalakshi` failed would make the comparison you are running
  meaningless, because you would not know which one answered.
- **`leela` is a provider too.** The default is registered like any other, so there is no
  privileged path that only the built-in takes.

## Checking conformance before you wire it

`isinstance(x, MemoryPort)` answers only "are the names present". It does not compare
signatures — `runtime_checkable` Protocols never do. An implementation whose `search` takes
`(q, n)` passes `isinstance` and fails on the first query Leela sends it.

So check properly:

```sh
python -m leela.conformance memory vishalakshi
```

```python
from leela.core import check_port, port_report
print(port_report('memory', my_vault))
```

It reports three classes of problem:

```
memory <- a half-built alternate: 3 problem(s)
  - missing: agent_notes
  - search: leela passes ['query', 'limit'] which this does not accept
  - note: port declares an attribute, found a callable
```

1. **presence** — every member the port names exists
2. **kind** — an attribute is not a method and vice versa (`Backend.ready` is a property;
   a runtime that made it a method would break every call site)
3. **signature** — every keyword Leela actually passes is accepted by that name

The keyword lists live in `CALLS` in
[`leela/conformance.py`](../leela/conformance.py) and come from the real call
sites. An adapter that forwards `**kwargs` satisfies the signature check by construction,
which is usually the easiest way to write one.

Checking a *class* works too — constructor parameters count as present, so `Backend` can be
verified without starting a model.

## Writing an adapter

Adapters are the expected shape, rather than making vishalakshi implement Leela's names.
`MemoryPort` is fifteen methods of Leela vocabulary; `Vault` has its own. Translating in an
adapter keeps both projects free to name things for their own reasons.

```python
class VaultAdapter:
    "vishalakshi.Vault behind MemoryPort."

    def __init__(self, vault):
        self.v = vault
        self.note = vault.enc.note              # a value, not a call

    def search(self, query, limit=8, **kw): return self.v.find(query, n=limit)
    def toc(self, doc=None, depth=3, **kw):    return self.v.outline(doc, depth)
    ...
```

Two things the ports say that are easy to miss:

- `note` (memory, search) and `backend` (search) are **string attributes**, not methods.
  Every reply embeds them so an empty result always reports which backend produced it.
- `ready`, `busy` and `hist` on `RuntimePort` are **properties**, not methods.

Both are checked, because both were wrong in the first draft of the ports here.

## What `RuntimePort` deliberately leaves out

Compaction (`Compactor`), token accounting (`Usage`) and model resolution (`ModelSpec`,
`Routing`) are **not** in the port. They are Leela's policy about how to *use* a runtime,
not things a runtime must provide.

A ramabana backend that brought its own compaction would be substituting policy for
mechanism, and the two runtimes would then be incomparable — differences in output could
come from the model, or from a different context-management strategy, with no way to tell
which. Keeping the port at mechanism is what makes an A/B meaningful.

Since ramabana is currently an empty skeleton, `leela.agent.runtime.Backend` **is** the
specification. `tests/test_providers.py` asserts `Backend` conforms, so the port cannot
drift away from the thing it was extracted from.

## Where memory and search stay separate

They are two ports, not one "retrieval" port, and that is not an accident of history.
Source code is an AST-shaped corpus; prose is a document tree.
[`leela/memory.py`](../leela/memory.py) says so at the top, and the two share an embedder
while deliberately not sharing tables.

vishalakshi may well satisfy both. It should still do so as two adapters, because the day
one of them needs different chunking or a different index is the day a fused port becomes
expensive to unpick — and that day tends to arrive right after the swap.

## Checklist

1. Write the adapter; forward `**kwargs`.
2. `python -m leela.conformance <port> <name>` until it prints `OK`.
3. Register the factory with `@provider(port, name)` and lazy-import inside it.
4. Run Leela with `LEELA_<PORT>=<name>` and compare against the default.
