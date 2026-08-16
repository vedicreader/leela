# The vault

Why leela's prose memory has a workbench, what the workbench is made of, and which decisions
in it were not obvious.

Most of this arrived from [cassowary](https://github.com/vedicreader/cassowary), which is leela's
agent and leela's palette pointed at a corpus instead of a repository. Cassowary answered a
question leela had left open: leela could *hold* a vault long before it could show you one.

## The block

`leela/blocks/vault/` was `leela/blocks/jobs/`. The rename is the honest name: every job kind the
block ever registered — `clip`, `clip_codebase`, `clip_api_spec`, `tidy`, `poll` — exists to put
something in the vault or to keep what is in it clean. A block called `jobs` that serves
`/vault/*` is a queue that happens to own a corpus. A block called `vault` is a corpus that
happens to own a queue, which is what it always was.

`jobs.py` keeps its name inside it, so `git log --follow` still works and the queue is still
findable by somebody looking for a queue.

## A place, not a document

The workbench opens as an editor tab (`kind='vaultwb'`), beside the notebooks. It is not a pane.

A pane is the wrong shape for it twice over. Panes in leela are 200–380px of chrome down one
side, which is enough for a tree and not enough for a document grid, a shelf rail and a search
result with its evidence. And the vault is not *about* the file you have open — the rail already
does that job, and keeps doing it. The workbench is somewhere you go.

It is also **one** tab however often it is opened, unlike a vault document, of which there can be
many. A document is a thing; the workbench is a place, and you do not want six copies of a place.
`open_vault_workbench` moves the existing tab to the view you asked for rather than adding another.

The tab holds only which view was last open. Everything else is server-rendered and swaps its own
body, so the six views cost one fetch each and no client state.

![The workbench, searching](screenshots/vault-workbench.png)

## Six views

| | |
|---|---|
| browse | the shelves, and what is on the one you chose |
| find | one search across every shelf, landing on sections |
| add | a web source, a folder on disk, or a note you write |
| news | feeds, and what they have said |
| specs | read an API specification, then file it |
| topics | what the corpus is about, off the entity graph |

The split is by *what you came to do*, not by what the data is. "Where is that thing about
pricing" and "what is on the specs shelf" are different errands even though both are documents.

**find** lands on sections rather than documents because that is where the evidence is. A hit
carries its breadcrumb, the words you searched for marked in its snippet, and — when the encoder
is a real one — which leg ranked it, keyword or embedding. Two ranks that disagree is a fact
about your query worth seeing.

**add** puts the three ways in one place because they are one intention. Which reader runs is a
detail of the address: leave the action blank and `detect` picks between `grab`, `arxiv`,
`youtube`, `github`, a file on disk, and a note. Naming the reader is available and never required.

A folder is never indexed without showing the plan first. `plan_tree` reads the structure and
proposes one shelf per top-level folder, a category per file from its path, and a list of
generated paths it will leave out. Indexing a folder is slow and hard to reverse; guessing wrong
about `node_modules` is expensive in a way a preview costs nothing to prevent.

![The three ways in](screenshots/vault-add.png)

## Asking the vault about named documents

This is the point of the whole thing.

`@` in the agent composer already meant "this file, in this project". It now also means "this
document, in the vault" — the same gesture, because *this document* is the same intention whether
the document is a file you have open or a paper you filed a month ago. Both lists are capped
short, and capped separately: a suggestion list where one source fills every visible row is a list
that only has one source, whatever the other one returned.

Every document row and every search hit also carries an **ask** button, and the find view has
*attach every hit* — because "what do all of these say about X" is one question, and attaching
six sections one at a time is that question typed six times.

An attached reference is not a path, so it cannot live in `agentAttachments`, which is a
path→name map. `lee.vaultRefs` holds `{vault, shelf, doc, title}` and travels in the same
`attachments` array as a dict, alongside the selection refs that were already dicts.
`Workspace._vault_context` turns one into `<attached-document vault=… shelf=… title=… source=…>`.

A section id carries its document's id before a `#`. Attaching a *section* reads only that
section — which is the whole reason a citation beats a book. Opening still opens the document,
because you read around a citation; you do not quote around it.

## Feeds

RSS and Atom are parsed here, with `xml.etree`, and no dependency was added for it. Nothing
underneath reads a feed: fossick's `news` is a news *search*, and a vault watch is a page, a
query, arXiv, YouTube or a reminder.

Paste a site address rather than a feed address and `fetch_feed` asks the page for the feed it
advertises in `<link rel="alternate">`. Sites disagree about where a feed lives — `/feed.xml`,
`/rss.xml`, `/index.xml` — and somebody following a source knows its address, not its feed's. The
feed is resolved when it is added, so an address carrying no feed is refused there rather than
failing quietly an hour later.

Each item is filed as an ordinary document on the `news` shelf. That is what makes "what did the
feeds say about agents this week?" answerable out of the vault, with the item as the citation. An
item already held is left alone rather than re-embedded, so a feed that republishes its whole
history costs nothing after the first read — the link is the identity.

The registry is `feeds.json` beside `vaults.json`, not a table. Three fields and a timestamp did
not earn a schema.

## What is not here

**A dashboard block.** Cassowary infers dashboards from its bundled SQLite files, which is a
sensible thing for an application that ships databases. Leela opens folders it did not write, so
the equivalent is "chart an arbitrary `.db` somebody has open", which is a different feature
wearing the same word — and leela already has notebooks, a kernel and a live variable tree, which
is a better answer to *look at this table* than any inferred chart. Left out deliberately.

**Extraction and PII as a page.** The vault's PII reporting is already in leela, on document rows
and in the tidy list, where a judgement is one click from the thing being judged. Cassowary's
`/extract` is a page you go to; that is the right shape when the corpus is the product and the
wrong one when it is a panel beside an editor.
