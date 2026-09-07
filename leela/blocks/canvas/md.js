/* Enough markdown for a document: headings, emphasis, code, lists, quotes, links, rules, tables.
 * Leela's own tabs render through mdhtml; a canvas frame is one page and carries this instead. */
const cvEsc = s => String(s ?? '').replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));

function cvInline(s) {
  return cvEsc(s)
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img alt="$1" src="$2">')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>')
    .replace(/ {2}\u0001/g, '<br>').replace(/\u0001/g, ' ');
}

function cvMd(src) {
  const lines = String(src ?? '').split('\n'), out = [];
  let list = null, para = [], quote = [], fence = null, code = [], lang = '';
  //: Two trailing spaces are markdown's hard break, and the only way a line break survives here.
  const flushPara = () => { if (para.length) { out.push(`<p>${cvInline(para.join('\u0001'))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${cvInline(quote.join(' '))}</blockquote>`); quote = []; } };
  const flush = () => { flushPara(); flushList(); flushQuote(); };
  for (const raw of lines) {
    const l = raw.replace(/\s+$/, '');
    let m;
    if (fence) {                                           // inside a fence: kept verbatim to the closing ticks
      if ((m = l.match(/^(`{3,})\s*$/)) && m[1].length >= fence.length) {
        out.push(cvPre(lang, code)); fence = null; code = []; lang = '';
      } else code.push(raw);
      continue;
    }
    if ((m = l.match(/^(`{3,})(.*)$/))) { flush(); fence = m[1]; lang = m[2].trim(); code = []; continue; }
    if (!l.trim()) { flush(); continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { flush(); out.push(`<h${m[1].length}>${cvInline(m[2])}</h${m[1].length}>`); continue; }
    if (/^(-{3,}|\*{3,})$/.test(l.trim())) { flush(); out.push('<hr>'); continue; }
    if ((m = l.match(/^>\s?(.*)$/))) { flushPara(); flushList(); quote.push(m[1]); continue; }
    if ((m = l.match(/^\s*[-*+]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (list !== 'ul') { flushList(); out.push('<ul>'); list = 'ul'; }
      out.push(`<li>${cvInline(m[1])}</li>`); continue;
    }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara(); flushQuote();
      if (list !== 'ol') { flushList(); out.push('<ol>'); list = 'ol'; }
      out.push(`<li>${cvInline(m[1])}</li>`); continue;
    }
    if (l.includes('|') && l.trim().startsWith('|')) { flushPara(); out.push(cvRow(l)); continue; }
    flushList(); flushQuote(); para.push(raw.replace(/\s+$/, m => m.length >= 2 ? '  ' : ''));
  }
  if (fence) out.push(cvPre(lang, code));
  flush();
  return out.join('\n').replace(/(<tr>[\s\S]*<\/tr>)/, '<table>$1</table>');
}

//: The info string rides on the class, so `cvHtmlToMd` can put it back on the fence.
const cvPre = (lang, code) =>
  `<pre><code${lang ? ` class="language-${cvEsc(lang)}"` : ''}>${cvEsc(code.join('\n'))}</code></pre>`;

function cvRow(l) {
  const cells = l.trim().replace(/^\||\|$/g, '').split('|');
  if (cells.every(c => /^\s*:?-+:?\s*$/.test(c))) return '';
  return '<tr>' + cells.map(c => `<td>${cvInline(c.trim())}</td>`).join('') + '</tr>';
}
