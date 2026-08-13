/* ----------------------------------------------------- a Markdown diff, read as Markdown
 * A third way of reading the same diff, beside unified and side by side, and the only one in
 * which a README reads like a README: the new document rendered, with a bar in the margin
 * beside every block that changed and the line-level change shown *inside* a fenced block.
 *
 * The rendering is `/markdown/render`, unchanged and still `allow_raw: false` -- Markdown out
 * of a repository is untrusted input and this surface widens nothing. What makes the marks
 * placeable is `/markdown/diff`, which pairs the two versions block against block and reports
 * each block's source lines and the tag it should render as. Lines could not do this on their
 * own: a rendered paragraph has no line numbers, and an edit at the top of a file moves every
 * line below it while moving no blocks at all.
 */
const MARKDOWN_PATH = /\.(?:md|markdown|mdown|mkdn?)$/i;
const isMarkdownPath = path => MARKDOWN_PATH.test(String(path || ''));

// mdhtml's own top-level nodes, in document order. The footnotes section is generated from the
// definitions rather than from a block of its own, so it never carries a mark; a comment is a
// node a raw-HTML block legitimately produces, so it counts as a carrier even though there is
// nothing to draw beside it -- dropping it would silently shift every block after it.
function markdownCarriers(el) {
  return [...el.childNodes].filter(n => n.nodeType === 8 ||
    (n.nodeType === 1 && !(n.tagName === 'SECTION' && n.classList.contains('footnotes'))));
}
const markdownTagOf = n => n.nodeType === 1 ? n.tagName.toLowerCase() : '#comment';

/* Which element each block became. This is the crux of the whole view, and the part that has
 * to be allowed to fail: the server names the blocks in source order with the tag each is
 * expected to render as, and this walks the rendered nodes in that same order checking every
 * expectation it can. One mismatch, or one node no block claimed, and the answer is `null` --
 * a raw HTML block that produced two elements shifts everything after it, and a change bar
 * beside the wrong paragraph is a false statement about the diff. Nothing is drawn then, and
 * the surface says why rather than quietly looking correct.
 *
 * The answer is *positions*, not nodes, because the code-block upgrade later swaps each `<pre>`
 * for an editor surface in the same place. A caller that has to wait for a request before it can
 * draw reads the tags now and the nodes again afterwards, and the positions still hold.
 */
function alignMarkdownBlocks(tags, rows) {
  const pairs = [];
  let at = 0;
  for (const row of rows) {
    if (row.status === 'removed') { pairs.push({row, at: -1}); continue; }
    if (!row.renders) continue;                       // a link or footnote definition renders nothing
    if (at >= tags.length) return null;
    const tag = tags[at++], want = row.tags || [];
    if (want.length && !want.includes(tag)) return null;
    pairs.push({row, at: at - 1});
  }
  return at === tags.length ? pairs : null;
}

/* The line-level change inside one fenced block: the lines as they read now, additions on
 * green and removals struck through on pink, with `tokenDiffHtml` marking the words that
 * actually moved in a line that was edited. An LCS over lines is the same shape as the token
 * diff one level down and is affordable at a code fence's length; a pathologically long fence
 * falls back to "all of the old, then all of the new" rather than allocating a large matrix.
 */
function markdownCodeDiffHtml(before, after) {
  const a = String(before ?? '').replace(/\n$/, '').split('\n');
  const b = String(after ?? '').replace(/\n$/, '').split('\n');
  const line = (kind, html) => `<div class="lee-md-code-line ${kind}">${html || ' '}</div>`;
  if (a.length > 600 || b.length > 600)
    return a.map(x => line('del', esc(x))).join('') + b.map(x => line('add', esc(x))).join('');
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { rows.push({kind: 'ctx', now: b[j]}); i++; j++; }
    else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) rows.push({kind: 'add', now: b[j++]});
    else rows.push({kind: 'del', old: a[i++]});
  }
  // A removal immediately followed by an addition is one line somebody edited, and the words
  // that changed in it are the thing worth pointing at on both halves.
  return rows.map((r, k) => {
    if (r.kind === 'ctx') return line('ctx', esc(r.now));
    if (r.kind === 'del') {
      const twin = rows[k + 1]?.kind === 'add' ? rows[k + 1] : null;
      return line('del', twin ? tokenDiffHtml(r.old, twin.now) : esc(r.old));
    }
    const prior = rows[k - 1]?.kind === 'del' ? rows[k - 1] : null;
    return line('add', prior ? tokenDiffHtml(r.now, prior.old) : esc(r.now));
  }).join('');
}

// Pink for text that changed, green for text that is new, amber for a code fence -- the three
// the reader has to tell apart at a glance, and the same three the gutter already uses.
const markdownChangeKind = row => row.status === 'added' ? 'added'
  : row.status !== 'modified' ? '' : row.type === 'code_block' ? 'code' : 'modified';

function paintMarkdownDiff(doc, rows) {
  const nodes = markdownCarriers(doc), pairs = alignMarkdownBlocks(nodes.map(markdownTagOf), rows);
  const note = doc.parentElement?.querySelector('[data-md-diff-note]');
  if (!pairs) { if (note) note.hidden = false; return false; }
  // A removed block has nothing left to render, so it is reported on the block that now stands
  // where it stood: a second, thinner mark and the old text in the tooltip. Removals with
  // nothing after them belong to the last block in the document.
  let removed = [], last = null;
  for (const {row, at} of pairs) {
    if (row.status === 'removed') { removed.push(row); continue; }
    const node = nodes[at];
    let host = node;
    // A fenced block is the one place a rendering can carry a line diff itself, and it is also
    // the one place the mark cannot simply be put on the element: `enhanceCodeBlocks` replaces
    // every `pre > code` with an editor surface a moment after this runs. An edited fence
    // becomes the interleaved diff, which has no `<code>` for the upgrade to find; a fence that
    // is new keeps its highlighted rendering and gets a wrapper to hold the mark instead.
    if (row.type === 'code_block' && node?.nodeType === 1 && node.tagName === 'PRE'
        && (row.status !== 'equal' || removed.length)) {
      host = document.createElement('div');
      if (row.status === 'modified') {
        host.className = 'lee-md-code-diff';
        host.innerHTML = `<pre>${markdownCodeDiffHtml(row.old_code || '', row.code || '')}</pre>`;
        node.replaceWith(host);
      } else { node.replaceWith(host); host.className = 'lee-md-code-host'; host.appendChild(node); }
    }
    if (host?.nodeType !== 1) continue;               // a comment carries no mark
    last = host;
    const kind = markdownChangeKind(row), notes = [];
    if (kind === 'added') notes.push('added in this change');
    else if (kind) notes.push(`was:\n${row.old || ''}`);
    if (removed.length) {
      const gone = removed.reduce((n, r) => n + r.to - r.from + 1, 0);
      host.dataset.removedAbove = String(gone);
      notes.push(`${gone} line${gone === 1 ? '' : 's'} removed here:\n${removed.map(r => r.source).join('\n\n')}`);
      removed = [];
    }
    if (!kind && !host.dataset.removedAbove) continue;
    host.classList.add('lee-md-change');
    if (kind) host.dataset.change = kind;
    host.title = notes.join('\n\n');
  }
  if (removed.length && last) {
    const gone = removed.reduce((n, r) => n + r.to - r.from + 1, 0);
    last.classList.add('lee-md-change'); last.dataset.removedBelow = String(gone);
    last.title = `${last.title ? last.title + '\n\n' : ''}${gone} line${gone === 1 ? '' : 's'} removed after this:\n${removed.map(r => r.source).join('\n\n')}`;
  }
  return true;
}

async function mountMarkdownDiff(body, data) {
  body.classList.add('lee-md-diff');
  body.innerHTML = `<div class="lee-md-diff-stat"></div>` +
    `<div class="lee-md-diff-note" data-md-diff-note hidden>The blocks of this document cannot be matched to the elements they rendered as, so no change bars are drawn. Read it as unified or side by side to see where the change is.</div>` +
    `<article class="lee-md-preview lee-md-diff-doc" data-markdown=""></article>`;
  let d;
  try { d = await post('/markdown/diff', {left: data.left || '', right: data.right || ''}); }
  catch (e) {
    body.innerHTML = `<div class="lee-git-empty-state"><strong>Rendered diff unavailable</strong><span>${esc(e.message || e)}</span></div>`;
    return;
  }
  const rows = d.blocks || [], changed = rows.filter(r => r.status !== 'equal').length;
  body.querySelector('.lee-md-diff-stat').innerHTML =
    `<span class="add">+${d.added || 0}</span><span class="del">−${d.removed || 0}</span>` +
    `<span class="lee-dim">${changed || 'no'} changed block${changed === 1 ? '' : 's'}</span>` +
    `<span class="lee-spacer"></span><span class="lee-md-diff-legend">` +
    `<i data-change="added"></i>added<i data-change="modified"></i>changed<i data-change="code"></i>code<i data-change="removed"></i>removed</span>`;
  const doc = body.querySelector('.lee-md-diff-doc');
  if (!String(data.right || '').trim()) {
    doc.innerHTML = `<div class="lee-git-empty-state"><strong>Nothing left to render</strong>` +
      `<span>This comparison removes the whole file; its ${d.removed || 0} removed lines are in the unified view.</span></div>`;
    return;
  }
  // The document is rendered by the same route as every other Markdown surface in the app, and
  // annotated on the fragment it produced -- there is no second renderer here.
  renderMarkdown(doc, data.right || '', false, () => paintMarkdownDiff(doc, rows));
}

/* The same marks on the file's own rendered pane, from the ranges the gutter beside it is
 * already drawing. This is the line-range route rather than the block-pairing one: `/git/file`
 * reports changed lines in the working tree's own numbering, and a block owns a range when the
 * two overlap -- Git points a pure deletion at the line that closed over it, so a removal lands
 * on the block that now stands there.
 *
 * Only the first render asks. While the file is being typed the ranges describe the version on
 * disk, and the honest number of marks for a paragraph that has moved under them is none. The
 * tags are read before the request goes out, because by the time it answers the code-block
 * upgrade has already replaced every `<pre>` with an editor surface.
 */
async function paintMarkdownFileChanges(el, ranges) {
  if (!ranges?.length) return;
  const text = el.dataset.markdown, tags = markdownCarriers(el).map(markdownTagOf);
  let d;
  try { d = await post('/markdown/blocks', {text, ranges}); } catch (_) { return; }
  if (!el.isConnected || el.dataset.markdown !== text) return;
  const blocks = (d.blocks || []).map((b, i) => ({...b, kind: (d.kinds || [])[i]}));
  const pairs = alignMarkdownBlocks(tags, blocks);
  if (!pairs) return;
  const nodes = markdownCarriers(el);
  for (const {row, at} of pairs) {
    const node = nodes[at];
    if (!row.kind || node?.nodeType !== 1) continue;
    node.classList.add('lee-md-change'); node.dataset.change = row.kind;
    node.title = row.kind === 'added' ? 'added since HEAD'
      : row.kind === 'removed' ? 'text was removed here' : 'changed since HEAD';
  }
}

async function leeOpenFile(path) {
  // The absolute path is the identity. Use one versioned request rather than HTMX's
  // implicit swap: an older response must never remount a same-named file from another root.
  path=String(path||'');const version=++openFileVersion;lee.pendingFocusPath=path;
  // File rows stopPropagation on their own onclick, so the document listener never paints
  // `.sel`. Keyboard navigation already calls selectTreeNode; keep mouse opens in sync.
  const treeNode = $$('.lee-node').find(n => n.dataset.path === path);
  if (treeNode) selectTreeNode(treeNode);
  const response=await fetch('/tab/open?path='+encodeURIComponent(path),{method:'POST',headers:{'HX-Request':'true'}});
  if(!response.ok)throw new Error(await response.text());const html=await response.text();
  if(version!==openFileVersion)return;
  const doc=new DOMParser().parseFromString(html,'text/html'),fresh=doc.querySelector('#tabbar'),old=$('#tabbar');
  if(!fresh||!old)throw new Error('tab open returned no tab bar');old.replaceWith(fresh);htmx.process(fresh);
  await mountTab(path);await leeVars();refreshProjectPills();requestAnimationFrame(layoutTabs);
  const after = $$('.lee-node').find(n => n.dataset.path === path);
  if (after) selectTreeNode(after);
}
window.leeOpenFile = leeOpenFile;

