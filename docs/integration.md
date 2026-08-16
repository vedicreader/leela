# vishalakshi and ramabana integration

| port | purpose | default | alternate |
|---|---|---|---|
| `MemoryPort` | pages, research, agent state | `blocks.memory.memory.Memory` | `vishalakshi.Vault` |
| `SearchPort` | code search | `blocks.search.search.Search` | vishalakshi code support |
| `RuntimePort` | model session | `ramabana.runtime.Backend` | another harness |

`leela/core/ports.py` defines ports. Environment variables choose providers.

```sh
LEELA_MEMORY=vishalakshi leela .
LEELA_SEARCH=vishalakshi leela .
LEELA_RUNTIME=ramabana leela .
python -m leela.conformance memory vishalakshi
```

Register adapters with `@provider(port, name)`. Import implementation dependencies inside the factory.

Conformance checks member presence, kind, and call signatures. `leela/conformance.py` contains keyword lists.

`ramabana.runtime.Backend` defines the runtime contract. `leela.agent.runtime` aliases it.

`WorkspaceHost` implements `ramabana.tools.Host`. Declare host capabilities. Enable `agent_read_outside` for controlled external reads; writes remain confined. `mk_chat = None` enables `Agent.lend_model`.

Memory and search remain separate ports: source code uses an AST corpus; prose uses a document tree.

1. Forward `**kwargs`.
2. Run conformance checks.
3. Register a lazy factory.
4. Compare the selected provider with the default.
