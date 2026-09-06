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
    .replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>');
}

function cvMd(src) {
  const lines = String(src ?? '').split('\n'), out = [];
  let list = null, para = [], quote = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${cvInline(para.join(' '))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${cvInline(quote.join(' '))}</blockquote>`); quote = []; } };
  const flush = () => { flushPara(); flushList(); flushQuote(); };
  for (const raw of lines) {
    const l = raw.replace(/\s+$/, '');
    if (!l.trim()) { flush(); continue; }
    let m;
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
    flushList(); flushQuote(); para.push(l.trim());
  }
  flush();
  return out.join('\n').replace(/(<tr>[\s\S]*<\/tr>)/, '<table>$1</table>');
}

function cvRow(l) {
  const cells = l.trim().replace(/^\||\|$/g, '').split('|');
  if (cells.every(c => /^\s*:?-+:?\s*$/.test(c))) return '';
  return '<tr>' + cells.map(c => `<td>${cvInline(c.trim())}</td>`).join('') + '</tr>';
}
