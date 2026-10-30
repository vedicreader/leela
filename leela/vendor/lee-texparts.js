// TeX parts for the screen guide, as a browser global and a node module. abhyasa's guide.js uses it, and Leela vendors this
// one file, so both apps mark formulas and trust KaTeX in exactly the same way.
// window.abhyasaTex = {texParts, texAtoms, texWrap, trust}:
//   texParts(tex, f) -> [marked, parts]   `tex` with \htmlId{g-<f>-<k>}{...} around each part with a letter, and the parts as
//                                         [[part TeX, id], ...]. `f` is the number of the formula on the page.
//   texAtoms(s) -> [{s, e, cmd, ch, args}] the atoms of one level of `s`.
//   texWrap(s, f, tokens) -> string       `s` with ids around its parts; each part goes into `tokens` as [tex, id].
//   trust(context) -> bool                the KaTeX trust rule: only \htmlId with an id of the form g-<f>-<k>.
(() => {
// --- TeX parts ----------------------------------------------------------------------------------------------------------
// A formula is split into atoms: a command with its arguments, a {group} or one character, each with its _ and ^ scripts.
// A run in round brackets is an atom too. Each atom with a letter in it gets \htmlId{g-<formula>-<k>}, so KaTeX gives it
// its own element, and the board can draw on the exact part. The page does this, not the model.
var TEX_ARGS = {frac: 2, dfrac: 2, tfrac: 2, binom: 2, sqrt: 1, bar: 1, hat: 1, tilde: 1, vec: 1, dot: 1, ddot: 1, overline: 1,
                  underline: 1, widehat: 1, widetilde: 1, mathbf: 1, mathrm: 1, mathcal: 1, mathbb: 1, mathit: 1, mathsf: 1, mathtt: 1,
                  boldsymbol: 1, bm: 1, text: 1, textbf: 1, operatorname: 1};
var TEX_INNER = {sqrt: 1, frac: 1, dfrac: 1, tfrac: 1, binom: 1};   // their arguments get ids of their own; an accent's do not
var TEX_SKIP = /^(left|right|big|Big|bigg|Bigg|mid|cdot|times|quad|qquad|,|;|:|!| |cdots|ldots|dots|to|in|le|ge|leq|geq|ne|neq|approx|sim|propto|sum|prod|int|lim|log|exp|sin|cos|max|min|infty|partial|nabla|pm|mp)$/;

function texGroup(s, i) {   // the end of the {group} that starts at i
  let d = 0;
  for (let k = i; k < s.length; k++) {
    if (s[k] === '\\') { k++; continue; }
    if (s[k] === '{') d++;
    else if (s[k] === '}' && --d === 0) return k + 1;
  }
  return s.length;
}
function texToken(s, i) {   // one token at i: a command, a {group} or a character; returns [end, command name or null]
  while (s[i] === ' ') i++;
  if (s[i] === '{') return [texGroup(s, i), null, i];
  if (s[i] === '\\') {
    const m = /^\\([A-Za-z]+|.)/.exec(s.slice(i));
    return [i + (m ? m[0].length : 1), m ? m[1] : '', i];
  }
  return [i + 1, null, i];
}
function texAtoms(s) {   // the atoms of one level of `s`
  const out = [];
  let i = 0;
  while (i < s.length) {
    while (s[i] === ' ') i++;
    if (i >= s.length) break;
    const start = i;
    let [e, cmd] = texToken(s, i);
    const args = [];
    if (cmd && TEX_ARGS[cmd]) {
      if (cmd === 'sqrt' && s[e] === '[') e = s.indexOf(']', e) + 1 || s.length;
      for (let n = 0; n < TEX_ARGS[cmd]; n++) { const [ae, , as] = texToken(s, e); args.push([as, ae]); e = ae; }
    }
    for (;;) {   // the scripts
      let k = e; while (s[k] === ' ') k++;
      if (s[k] !== '_' && s[k] !== '^') break;
      const [se, , ss] = texToken(s, k + 1); args.push([ss, se, 'script']); e = se;
    }
    out.push({s: start, e, cmd, ch: cmd ? null : s[start], args});
    i = e;
  }
  return out;
}
function texWrap(s, f, tokens) {   // `s` with ids around its parts; each part's TeX goes into `tokens` as [tex, id]
  const atoms = texAtoms(s), pieces = [];
  const id = tex => { const k = `g-${f}-${tokens.length}`; tokens.push([tex.trim(), k]); return k; };
  for (const a of atoms) {
    const src = s.slice(a.s, a.e);
    let inner = src;
    if (a.ch === '{') inner = '{' + texWrap(src.slice(1, -1), f, tokens) + '}';
    else if (a.cmd && TEX_INNER[a.cmd]) {   // wrap inside the arguments of \sqrt and \frac, from the last, so the places stay right
      let t = src;
      for (const [as, ae, kind] of [...a.args].reverse()) {
        if (kind === 'script') continue;
        const arg = s.slice(as, ae), body = arg[0] === '{' ? '{' + texWrap(arg.slice(1, -1), f, tokens) + '}' : arg;
        t = t.slice(0, as - a.s) + body + t.slice(ae - a.s);
      }
      inner = t;
    }
    const letter = /[A-Za-z]/.test(a.ch || '') || (a.cmd && !TEX_SKIP.test(a.cmd) && /^[A-Za-z]+$/.test(a.cmd)) || (a.ch === '{' && /[A-Za-z]/.test(src));
    pieces.push({src, out: letter ? `\\htmlId{${id(src)}}{${inner}}` : inner, ch: a.ch});
  }
  // A run in round brackets is one part too, also inside another run. A list of arguments (with , or ;) gets no id of its own.
  const runs = ps => {
    const out = [];
    for (let k = 0; k < ps.length; k++) {
      if (ps[k].ch === '(') {
        let d = 0, m = k;
        for (; m < ps.length; m++) { if (ps[m].ch === '(') d++; if (ps[m].ch === ')' && --d === 0) break; }
        if (m < ps.length && m > k + 1) {
          const body = ps.slice(k + 1, m), src = ps.slice(k, m + 1).map(p => p.src).join(''), all = ps[k].out + runs(body) + ps[m].out;
          const list = body.some(p => p.ch === ',' || p.ch === ';');
          out.push(/[A-Za-z]/.test(src) && !list && src.length <= 80 ? `\\htmlId{${id(src)}}{${all}}` : all);
          k = m; continue;
        }
      }
      out.push(ps[k].out);
    }
    return out.join('');
  };
  return runs(pieces);
}
function texParts(tex, f) {   // [the TeX with ids, [[part TeX, id], …]]
  const tokens = [];
  return [texWrap(String(tex), f, tokens), tokens];
}
const trust = c => c.command === '\\htmlId' && /^g-\d+-\d+$/.test(c.id);   // KaTeX `trust`: our ids, nothing else
const api = {texParts, texAtoms, texWrap, trust};
if (typeof window !== 'undefined' && !window.abhyasaTex) window.abhyasaTex = api;
if (typeof module !== 'undefined') module.exports = api;
})();
