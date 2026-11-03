<p align="center">
<img src="https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/leela-icon.png" width="120" alt="Leela logo">
</p>

<h1 align="center">Leela</h1>

<p align="center">A creative workspace that starts with coding.</p>

<p align="center">
<a href="https://github.com/vedicreader/leela/releases/latest/download/Leela-macOS.dmg"><img src="https://img.shields.io/badge/Download_for_macOS-Leela--macOS.dmg-2F2722?style=for-the-badge&logo=apple&logoColor=white" alt="Download Leela for macOS"></a>
</p>

<p align="center">
<a href="https://github.com/vedicreader/leela/releases/latest"><img src="https://img.shields.io/github/v/release/vedicreader/leela?label=release" alt="Latest release"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0 license"></a>
<img src="https://img.shields.io/badge/macOS-14%2B_Apple_silicon-black?logo=apple" alt="macOS 14 or later on Apple silicon">
</p>

Leela is an IDE for notebooks and code files. An assistant built on [ramabana](https://github.com/vedicreader/ramabana) works in the same window. Lessons from [abhyasa](https://github.com/vedicreader/abhyasa) open in it as notebooks, and the screen guide draws on the page to explain them.

![Open a file, open a notebook, run its cells, and see the live variables](https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/hero.gif)

## What you get

- **An editor and a file tree.** Edit Python, Rust, JavaScript and other files. Command-click goes to a definition.

  <img src="https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/editor.png" width="640" alt="The file tree on the left, sieve.py in the editor, and the agent pane on the right">

- **Notebooks that show what they make.** Run Python, Rust and JavaScript cells. Plots show under the cell. The variables pane shows every name a cell makes, while the cell runs.

  <img src="https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/notebook.png" width="640" alt="A notebook with a plot of the primes below n, and the variables pane with ps, xs and gaps">

- **An assistant that asks first.** Ask it to explain, change, run or test your code. It shows each change before it makes it, and nothing changes until you approve. It runs on a cloud model or on a model on your computer.

  <img src="https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/assistant.png" width="640" alt="A change approval card: the agent wants to add a test cell to explore.ipynb and waits for a decision">

  ![Ask for a test, approve the change, and see the new cell in the notebook](https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/assistant.gif)

- **Lessons from abhyasa.** In abhyasa, press Open in Leela on a step. Leela opens the step as a lesson notebook, with the passage from the source, a task, tests, and a Check button.

  <img src="https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/lesson.png" width="640" alt="A lesson notebook: the task, the tests, the evens function to write, and the Check and Ask the tutor buttons">

- **The screen guide's board.** Press "I don't get…" on a lesson cell and say what you do not understand. The guide explains it step by step and draws on the cell.

  <img src="https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/guide.png" width="640" alt="The screen guide circles the word yield and draws an arrow on the passage, with step 3 of 3 in the strip below">

  ![A step page opens as a lesson notebook, then the screen guide explains a passage](https://raw.githubusercontent.com/vedicreader/leela/main/docs/media/lesson-guide.gif)

Leela also presents a notebook as slides and runs its code live ([how](docs/present.md)), searches your code and your saved pages, papers and videos ([how](docs/search.md)), and stages, commits, merges and releases with its git tools. The [guide](docs/guide.md) explains each part.

## Install

You need a Mac with Apple silicon and macOS 14 or later.

With Homebrew:

```sh
brew install --cask vedicreader/tap/leela
```

The cask also installs uv. Lessons and project environments use uv.

Or download [Leela-macOS.dmg](https://github.com/vedicreader/leela/releases/latest/download/Leela-macOS.dmg) from the latest release, open it, and drag Leela into Applications. If you do not have uv, run `brew install uv`. The app is signed with a Developer ID and notarized by Apple.

On Linux, or on Windows inside WSL, run Leela from the command line. It opens in your browser at `http://localhost:5010`:

```sh
uv tool install git+https://github.com/vedicreader/leela
leela .
```

- The `leela` package on PyPI is a different project.
- On Windows, export model keys such as `OPENAI_API_KEY` in the WSL shell, not in Windows, and start Leela with `leela --shell none .`.

## First use

1. Open Leela. On the welcome screen, press **Open a folder** and pick a project.
2. Open a notebook or a file in the file tree. Put the cursor in a cell and press Shift+Return to run it.
3. Write a question in the agent pane and press Command+Return. If no model is set up, the pane lists the providers that you can use, and **+ model** adds one.

## Keys

On a Mac, `mod` is Command. Elsewhere it is Control.

| Key | Action |
|---|---|
| `mod+enter` | Run the cell. In the agent pane, send. |
| `shift+enter` | Run the cell and select the next one |
| `mod+shift+enter` | Run all cells |
| `mod+shift+p` | Command palette |
| `mod+shift+f` | Search code |
| `mod+shift+/` | Show all keys |
| `alt+shift+1` to `alt+shift+5` | Go to files, editor, exec, variables or agent |
| `alt+s` | Check the exercise that has the cursor |
| `alt+r` | Present the notebook from the selected cell |

You can change each key in `keys.json`. See [keys and buttons](docs/guide.md#keys-and-buttons).

## More

- [Using Leela](docs/guide.md): the command-line options, each part of the app, lessons, and the keys.
- [Developing Leela](docs/develop.md): get the code, the code layout, the desktop builds, the release steps and the tests.
- [All docs](docs/README.md): the design notes.
- [Release notes](CHANGELOG.md)

## License

Apache-2.0
