<p align="center">
<img src="packaging/assets/Leela.png" width="128" alt="Leela">
</p>

<h1 align="center">Leela</h1>

<p align="center">A creative workspace that starts with coding.</p>

<p align="center">
<a href="https://github.com/vedicreader/leela/releases/latest/download/Leela-macOS.dmg"><b>Download Leela for Mac</b></a>
&nbsp;·&nbsp;
<a href="https://github.com/vedicreader/leela/releases">All releases</a>
&nbsp;·&nbsp;
<a href="docs/guide.md">Guide</a>
</p>

![Leela, the desktop app](docs/screenshots/desktop-window.png)

Leela is an editor for notebooks and code files, with a coding agent in the same window. You write code, run it, and see your live variables. The agent can read, run and change your code, and it asks before it changes anything.

## Get Leela

On a Mac with Apple silicon and macOS 14 or later:

With Homebrew:

    brew install --cask vedicreader/tap/leela

Or by hand:

1. Download [Leela-macOS.dmg](https://github.com/vedicreader/leela/releases/latest/download/Leela-macOS.dmg).
2. Open the file, and drag Leela into Applications.
3. Open Leela from Applications.

The app is signed with a Developer ID and notarized by Apple. It needs an Apple silicon Mac with macOS 14 or later. Lessons and project environments use uv, which the Homebrew cask installs.

On Linux, or on Windows inside WSL, run Leela from the command line. It opens in your browser at `http://localhost:5010`:

```sh
uv tool install git+https://github.com/vedicreader/leela
leela .
```

The install needs a GitHub sign-in that can read this repository (`gh auth login`). The `leela` package on PyPI is a different project. On Windows, export model keys such as `OPENAI_API_KEY` in the WSL shell, not in Windows, and start Leela with `leela --shell none .`.

## What you can do

- Edit notebooks and files side by side. Run Python, Rust and JavaScript cells.
- See every variable a cell makes, while the cell runs.
- Ask the agent to explain, change or test your code. It runs on a cloud model or on a model on your machine.
- Learn a topic step by step from abhyasa lessons, with exercises the agent checks.
- Present a notebook as slides, and run its code live ([how](docs/present.md)).
- Search your code and your saved pages, papers and videos.
- Stage, commit, merge and release with the git tools.

The [guide](docs/guide.md) explains each part, the command-line options and the keys.

## Work on Leela

```sh
git clone https://github.com/vedicreader/leela && cd leela
uv sync --group dev
uv run leela .
uv run pytest tests -q
```

[Developing Leela](docs/develop.md) has the code layout, the desktop builds and the release steps. [docs](docs/README.md) indexes the design notes.

Leela uses these packages from the same authors: [ramabana](https://github.com/vedicreader/ramabana) (the agent), [shalya](https://github.com/vedicreader/shalya) (the agent's tools), [kunda](https://github.com/vedicreader/kunda) (kernels), [dhrishti](https://github.com/vedicreader/dhrishti) (live variables), [gheasy](https://github.com/vedicreader/gheasy) (git), [kavacha](https://github.com/vedicreader/kavacha) (the app window) and [pullup](https://github.com/vedicreader/pullup) (releases and deploys).

## License

Apache-2.0
