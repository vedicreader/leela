# Vault documents as files, and images you can look at

A vault document is a copy of something that already exists. Today the only way to see one is
the reader tab, which shows extracted text and nothing else — so a clipped PNG is invisible, a
clipped Markdown file cannot be edited, and a file that changes on disk leaves the vault holding
a stale copy with no sign that it has.

This design does four things: opens the *real file* behind a vault document, teaches leela to
display images, re-indexes a clipped file when it changes, and turns browsing from a flat list
into a tree you can walk like a file browser.

It deliberately does **not** make vault documents editable in place. Writing back into a
vishalakshi database means deciding what happens to the extracted nodes, the embeddings and the
content address, and none of that is needed to get the editing the user actually wants: the file
on disk is the document, and leela already knows how to edit files.

## What already exists

Established by reading the code, not assumed:

- `all_documents()` returns `source` as the **absolute file path** for a clipped file
  (`/…/notes.md`). Web clips store a URL; notes and pointers store `memory:<hash>` and
  `pointer:<hex>`. So a document knows where it came from, but only sometimes is that a file.
- `pdf` is already a tab kind (`workspace.py` `Tab.__post_init__`, `tabs/app.py`,
  `mountPdf` in `04_editor.js`). The tab carries no contents; the browser fetches `/file/raw`.
- `/file/raw` already serves `image/png`, `jpeg`, `gif`, `webp`, `svg+xml` and `x-icon` through
  the `SERVED_TYPES` allowlist. **No new route is needed to get image bytes to the page.**
- `Jobs.tick` already runs a daemon thread calling `memory.poll()`, and vishalakshi's watch
  actions already include `path`. **No new scheduler is needed.**
- `/vault/browse` already takes a `vault` parameter and opens any attached vault without
  activating it.

The work is therefore mostly wiring, plus one new tab kind and one new poll rule.

## 1. Open the file behind a vault document

`_doc_row` gains a second control beside the title: the title opens the reader as it does now,
and an **open file** button opens the real path in leela. The button is rendered only when the
document's `source` resolves to a file that exists — a web clip has no file, and offering a
control that cannot work is worse than not offering it.

A new route answers the question the client cannot:

```
GET /vault/source?doc=…&shelf=…&vault=…
  -> {ok, path, exists, inside_workspace, kind}   # kind: file | url | synthetic
```

`kind` is decided from the source string: a path that resolves under a workspace root is
`file`, a `http(s)://` source is `url`, and `memory:`/`pointer:` are `synthetic`.

**Outside the workspace roots.** `fs._check` refuses paths outside a root, and that refusal is
load-bearing — it is the sandbox every other path in leela is checked against. So a document
whose file lives outside is not opened by punching through it. Instead the client sees
`inside_workspace: false`, asks *"`~/Documents` is not open in this workspace. Add it as a
folder?"*, and on yes calls the existing `/fs/add-root` and then opens normally. The sandbox
keeps its meaning and the user gets one prompt, once, per folder.

**Deleted or moved files.** `exists: false` renders the button disabled with the path as its
tooltip, so the row says the file is gone rather than failing on click.

## 2. Images

Three pieces, all following the `pdf` precedent.

**A viewer tab.** `IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'}`
becomes a tab kind in `Tab.__post_init__`, beside the existing `.pdf` branch. `tabs/app.py`
returns `{'kind': 'image', 'path', 'title', 'disk_version'}` and no contents, exactly as `pdf`
does. `mountImage` in `04_editor.js` renders the same `lee-doc` chrome as `mountPdf` — open
externally, download — around an `<img>` with fit/actual-size toggle and the natural dimensions
shown. `saveTab` refuses an image tab the way it already refuses a PDF.

`.bmp` is in the tab set but not in `SERVED_TYPES`; it is added there too, since a tab kind
whose bytes cannot be served is a broken tab.

**Inline images in the reader.** `renderMarkdown` currently leaves image references as-is, so a
clipped document's figures are broken links. It gains a resolve step: a relative `src` is
rewritten against the document's directory to `/file/raw?path=…`, an absolute path likewise, and
an `http(s)` source is left alone. Anything that does not resolve inside a workspace root is
left as written rather than rewritten to a URL that would 403 — a broken image is honest; a
forbidden one looks like a bug.

**Images clippable into the vault.** Clipping an image files a document whose extracted text is
whatever the ingester manages (often nothing), so the value is the row and the path, not the
text. `_doc_row` therefore shows a thumbnail for an image document, and its reader tab shows the
image rather than an empty text pane. Documents with no extracted text stop rendering "No
section structure was extracted." as though something had failed.

## 3. Re-index a file when it changes

A `path` watch in vishalakshi calls `grab(target, force=True)` on every tick, re-embedding a
file whether or not it changed. On a shelf of any size that is a large recurring cost for no new
information, so leela gates it rather than registering raw `path` watches.

A new sweep, `Memory.reindex_changed(shelf=None)`, walks documents whose `source` is a real
file, compares the file's mtime against the document's `added_at`, and re-clips only those that
are newer. It returns `{checked, reindexed, missing}`. Missing files are reported, never
deleted: a vault is a record, and an unplugged external drive is not a reason to forget what was
on it.

`Jobs.tick` calls it on the same daemon thread that already polls watches, at its own slower
cadence (default 5 minutes, `0` disables). The vault panel gets a **re-index** button beside
**review** in the tidy section for an immediate sweep, and the result appears as a job card
like every other long-running vault operation.

The comparison is mtime-based rather than hash-based. Hashing every clipped file each sweep is
the cost this design is avoiding; mtime is what the filesystem already knows. A touched-but-
unchanged file costs one needless re-clip, which is acceptable; a changed-but-not-touched file
is not a thing a text editor produces.

## 4. Browsing a vault as a tree

A flat list answers "what is in here" and nothing else. Once a vault holds a clipped folder the
list is the wrong shape: the documents came from a directory tree and the list throws that away.
So browsing is a tree, and the flat list survives only as what a *search* returns.

Five levels, each drawn from structure that already exists:

```
workspace                       vault      vaults.dict()
  leela · 3 docs                shelf      Memory.shelves()
    docs/                       folder     derived from `source`
      deep/
        b.md                    document   the row
    notes/
      c.txt
  web · 12                      group      sources that are http(s), foldered by domain
    arxiv.org/
      2402.01234 — Some Paper
  notes · 4                     group      memory: and pointer: sources
```

Folders are derived by taking the `source` paths of a shelf's filed documents, stripping their
longest common prefix, and splitting what remains. Stripping the prefix matters: a vault clipped
from `/Users/me/projects/thing/docs` should open on `docs/`, not on six levels of chrome that
are the same for every row.

Documents with no file cannot sit in a folder, so they get **sibling top-level groups**: `web`,
foldered by domain, and `notes`. They are visible in the tree rather than reachable only through
search — a document you cannot see is a document you will not remember you have.

The tree ends at the document. Clicking one opens the reader, which already renders the section
TOC; putting sections in the tree would cost a `/vault/section` fetch per expand and make the
tree very tall for no new capability.

One route serves it:

```
GET /vault/tree?vault=…&shelf=…&path=…
  -> the fragment for that level, so expanding a node is one htmx swap
```

Expanding is server-rendered and lazy, like the file tree: a vault of any size must not have to
be serialised in full to show its first level. Open folders are remembered client-side in a
`Set`, the way `gitBranchFolders` already does for branch folders.

Search and tree are two views of one panel, toggled where the search box lives: typing a query
switches to hits, clearing it returns to the tree.

## 5. The vault from the research space

The research workspace (`researchWorkspace` in `19_research.js`) is a modal with a mode
segmentbar — Search, Read URL, Research. It gains a fourth: **Vault**.

In Vault mode the Sources column shows the §4 tree instead of search results, with the same
search box scoped to the same vault. Selecting a document shows its text in the research
reader — the surface that already renders a source — and the reader's action row gains **Open
file**, which is the same call as §1.

The browse fragment currently hardcodes `id="vaultbrowse"`, and rendering it in two places at
once would duplicate that id. `vault_browse` therefore takes an `elid` parameter (default
`vaultbrowse`) used for the container id and the form's `hx-target`, and the research modal asks
for `elid=researchvault`.

## Testing

- `source` classification: a clipped file is `file`, a web clip is `url`, a note is `synthetic`,
  a deleted file is `exists: false`.
- Opening a document outside the workspace returns `inside_workspace: false` rather than reading
  the file, and does not bypass `fs._check`.
- An image path becomes an `image` tab whose payload carries no contents, and `/file/raw` serves
  it with the right content type; `.bmp` included.
- `saveTab` refuses an image tab.
- Markdown image resolution: relative and absolute in-root paths are rewritten, `http` is left
  alone, out-of-root is left alone.
- `reindex_changed` re-clips a touched file, skips an untouched one, and reports a missing one
  without raising.
- `vault_browse(elid=…)` renders the given id in both the container and the form target, so two
  copies on one page do not collide.
- The tree strips the longest common prefix: three documents under one deep folder open on their
  own folder, not on the chrome above it. A single document does not collapse to nothing.
- Documents with no file appear under `web` (foldered by domain) and `notes`, not dropped and
  not mixed into the folder tree.
- Expanding a folder fetches only that level; a vault is never serialised in full to draw its
  first screen.
- A query switches the panel to hits and clearing it restores the tree, with open folders intact.

## Not doing

- Editing vault documents in place. The file is the document.
- Hash-based change detection. See §3.
- Image editing, cropping or annotation. Viewing only.
- Rewriting `renderMarkdown` into a full asset resolver; only `img` sources are touched.
- Sections as tree nodes. The tree stops at the document; the reader shows its headings.
- Moving, renaming or deleting documents from the tree. It browses; it is not a file manager.
