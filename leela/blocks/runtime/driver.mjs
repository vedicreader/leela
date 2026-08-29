// The node half of `runners.NodeRunner`. One `vm` context for the whole notebook, so a binding
// made in one cell is there in the next. Requests and replies are newline-delimited JSON on
// stdin and stdout; nothing else may be written to stdout.
import vm from 'node:vm';
import path from 'node:path';
import {createRequire} from 'node:module';
import {inspect} from 'node:util';

const root = path.resolve(process.argv[2] || process.cwd());
const send = o => process.stdout.write(JSON.stringify(o) + '\n');
const show = x => typeof x === 'string' ? x : inspect(x, {depth: 4, colors: false});

let cur = null;
const emit = (name, text) => { if (cur !== null) send({t: 'stream', id: cur, name, text}); };
const write = name => (...a) => emit(name, a.map(show).join(' ') + '\n');

const ctx = vm.createContext({
  require: createRequire(path.join(root, 'cell.js')),
  process, Buffer, URL, URLSearchParams, TextEncoder, TextDecoder, AbortController,
  setTimeout, clearTimeout, setInterval, clearInterval, setImmediate, queueMicrotask,
  structuredClone, fetch: globalThis.fetch,
});
ctx.globalThis = ctx;
ctx.console = {log: write('stdout'), info: write('stdout'), debug: write('stdout'),
               warn: write('stderr'), error: write('stderr'), trace: write('stderr')};

const OPTS = {filename: 'cell.js',
              importModuleDynamically: vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER};

const DECL = /^(\s*)(?:let|const|var)\s+([\s\S]*)$/;
const STMT = /^(?:return|throw|if|for|while|do|switch|try|class|function|import|export|break|continue)\b/;

// Top-level chunks, split where brace depth is zero. Strings and comments are stepped over so a
// brace inside one does not open a block.
function chunks(src) {
  const parts = [];
  let buf = '', depth = 0, i = 0;
  const flush = () => {
    const m = buf.match(DECL);
    // A `let` inside the async wrapper would not outlive the cell, so the keyword goes and the
    // assignment lands on the context, which is not in strict mode. Destructuring keeps its
    // parentheses, or `{a} = x` reads as a block.
    if (m) parts.push({decl: true,
      text: /^[{[]/.test(m[2].trimStart()) ? `${m[1]}(${m[2].replace(/([;\s]*)$/, ')$1')}` : m[1] + m[2]});
    else parts.push({decl: false, text: buf});
    buf = '';
  };
  while (i < src.length) {
    const c = src[i];
    if (c === '/' && src[i+1] === '/') { const j = src.indexOf('\n', i); const k = j < 0 ? src.length : j; buf += src.slice(i, k); i = k; continue; }
    if (c === '/' && src[i+1] === '*') { const j = src.indexOf('*/', i+2); const k = j < 0 ? src.length : j+2; buf += src.slice(i, k); i = k; continue; }
    if (c === '"' || c === "'" || c === '`') {
      let j = i + 1, esc = false;
      while (j < src.length && (esc || src[j] !== c)) { esc = src[j] === '\\' && !esc; j++; }
      buf += src.slice(i, j+1); i = j + 1; continue;
    }
    if (c === '{' || c === '(' || c === '[') depth++;
    else if (c === '}' || c === ')' || c === ']') depth = Math.max(0, depth - 1);
    buf += c;
    if (depth === 0 && (c === ';' || c === '\n')) flush();
    i++;
  }
  flush();
  return parts;
}

// Only a wrapped cell needs telling that its last expression is its value. A bare script already
// has a completion value, and a wrapper that returns nothing throws that value away.
function wrapAwait(code) {
  const parts = chunks(code);
  let k = parts.length - 1;
  while (k >= 0 && !parts[k].text.trim()) k--;
  if (k >= 0 && !parts[k].decl) {
    const t = parts[k].text.trim();
    if (!STMT.test(t) && !t.endsWith('}')) parts[k].text = parts[k].text.replace(/^(\s*)/, '$1return ');
  }
  return `(async () => {\n${parts.map(p => p.text).join('')}\n})()`;
}

const AWAITS = /(^|[^.\w$])await[\s(]/;

// The driver's own frames are not the learner's. What is left is the cell and what it called.
const MINE = /driver\.mjs|node:(vm|internal|events)\b/;
const frames = e => String((e && e.stack) || e).split('\n').filter(l => !MINE.test(l));

async function evaluate(code) {
  const src = AWAITS.test(code) ? wrapAwait(code) : code;
  let v = vm.runInContext(src, ctx, OPTS);
  if (v && typeof v.then === 'function') v = await v;
  return v;
}

let buf = '';
process.stdin.on('data', async d => {
  buf += d;
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i);
    buf = buf.slice(i + 1);
    if (!line.trim()) continue;
    const {id, code} = JSON.parse(line);
    cur = id;
    try {
      const v = await evaluate(code);
      send({t: 'done', id, ok: true, repr: v === undefined ? null : show(v)});
    } catch (e) {
      send({t: 'done', id, ok: false, ename: (e && e.name) || 'Error',
            evalue: (e && e.message) || String(e),
            stack: frames(e)});
    }
    cur = null;
  }
});
process.stdin.on('end', () => process.exit(0));
send({t: 'ready'});
