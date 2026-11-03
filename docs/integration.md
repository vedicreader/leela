# The agent host

`WorkspaceHost` in `leela/blocks/agent/ai.py` is what Leela gives the agent. It is a `shalya.Host`. It declares each capability group by inheriting the class that names it, and `Host.provides` is the only way to ask what it supports. `shalya.tools.tools_for` reads `provides` and builds the tools the host can back. The reasons are in [decisions.md](decisions.md#the-agent-host).

| group | what it is | where Leela implements it |
|---|---|---|
| `file` | the path boundary every host has | `blocks.fs.fs.Sandbox`, through `WorkspaceHost.check` |
| `code` | search, symbols, peers, public API | `blocks.search.search.Search` |
| `notebook` | cell listing, insertion, one live run | `blocks.nb.nb` and the kernel pool |
| `web` | search, one page, a cited digest | `blocks.research.research.Research` over `shalya.host.read_page` |
| `memory` | pages, research, agent notes and state | `blocks.memory.memory.Memory` over `vishalakshi.Vault` |
| `ask` | model-backed answers out of memory | `blocks.memory.vaults.Vaults` |
| `watch` | standing work that outlives the turn | `blocks.vault.jobs.Jobs` |
| `api` | a loaded spec, its operations, one call | `blocks.vault.spec` |
| `session` | the live namespace and the terminals | `blocks.runtime` and `blocks.term` |
| `shell` | one command, through the project env | `blocks.term.term` |
| `git` | status, divergence, a rehearsed rebase | `blocks.git.git` over `gheasy.repo` |

## Adding to the host

1. Inherit shalya's class for the group, and write every method it names. An incomplete group fails at construction.
2. Put the group in `without` when its backend is absent, so `provides` tells the truth.
3. Import the dependencies inside the method, not at module scope.
4. A capability for every agent belongs in shalya. One for every Ramabana session belongs in Ramabana. Say so, and do not write it on Leela's side.

## Providers, Azure OpenAI and AWS Bedrock

The model route is Ramabana's. Leela and the `ramabana` CLI read `~/.config/ramabana/config.toml` (or `$RAMABANA_CONFIG`) and the same env vars. When the agent's model cannot run here, the agent pane says why and lists each provider, what it needs and whether it is set up (`providers()`, from Ramabana's `PROVIDERS`).

**+ model** starts with a provider choice: OpenAI, Azure OpenAI (`https://NAME.openai.azure.com/openai/v1`, the deployment name as the model ID, Responses), AWS Bedrock (the Mantle endpoint `https://bedrock-mantle.<region>.api.aws/v1`, `AWS_BEARER_TOKEN_BEDROCK`), OpenRouter, Anthropic, Gemini, or any OpenAI-compatible server. Leela saves the model in `~/.config/leela/models.json`. The key stays in the environment.

The same in config.toml, which `ramabana setup` writes:

```toml
[azure]
endpoint = "https://NAME.openai.azure.com"   # or $AZURE_OPENAI_ENDPOINT; the key stays in $AZURE_OPENAI_API_KEY

[model."bedrock-gpt"]
model_id = "openai.gpt-5.4"
base_url = "https://bedrock-mantle.us-east-1.api.aws/v1"
api_key_env = "AWS_BEARER_TOKEN_BEDROCK"
api_name = "openai"

[jobs]
turn = "azure/gpt-5.4"                        # an Azure deployment, by name
summary = "bedrock-gpt"
```

- Claude on Bedrock, the Converse API, AWS profiles and SigV4 are not supported. fastllm has none of them.
- The pane's default model is Ramabana's `default_model`, so `[jobs] turn` reaches it unless the workspace saved its own. A name that config.toml defines wins over a saved one, and saving that name is refused.
- `generate_video` uses Ramabana's `video` job: `$RAMABANA_MODEL_VIDEO`, `[jobs] video`, or Veo 3 on Gemini. With no model that can run, the tool says what to set up and calls no provider.
